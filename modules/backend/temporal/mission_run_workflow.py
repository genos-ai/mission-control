"""Mission Run Workflow (Plan 88 steps 88.1.8 to 88.4.6, contract 3.3.3).

One durable workflow per MissionRun. It begins the run, plans it, then loops:
fetch the run's task graph, run each approved task as its own
execute_plan_task activity (layer by layer, at most max_parallel_tasks at a
time), ask the post-run supervisor, and route its decision. The loop ends
through _end_run, which compacts the MCD, writes the run digest (88.3.8,
patch p88-run-memory) and finalises the run.

The workflow reads no config: every timeout and retry policy comes from the
RunConfigSnapshot pinned in MissionRunWorkflowInput. The run is bounded by
max_run_duration_seconds of active time; human approval waits are excluded.
A supervisor WAIT is a durable wait_condition, not a timer, and costs nothing.
History is bounded by continue-as-new at the loop top, carrying
MissionRunWorkflowState and the unchanged config snapshot.

Pause and resume arrive as the request_pause and resume signals (88.4.5,
patch p88-lifecycle-signals): the run pauses at its next layer boundary, after
the in-flight tasks finish. The run-end notification is sent through _notify
under the same patch; a notification failure never fails the run. The patch is
evaluated once, as the first command of each run, so an execution that started
before the patch replays on the old branch throughout.

Budget caps (88.4.6, patch p88-budget-caps, evaluated once the same way):
check_run_budget runs before planning and at every layer boundary. A breached
cap ends the run BUDGET_STOPPED, pauses the mission and sends BUDGET_PAUSED.
Each task of a chunk gets an equal share of the run's headroom, which its
agent executor enforces; a task stopped by its share ends the run the same way.
Zero headroom always stops; it never means unlimited.
"""

import asyncio
import dataclasses
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    is_cancelled_exception,
)

with workflow.unsafe.imports_passed_through():
    from modules.backend.temporal.activity_options import activity_kwargs
    from modules.backend.temporal.mission_run_activities import (
        begin_mission_run,
        check_run_budget,
        fetch_run_task_graph,
        finalise_mission_run,
        pause_mission_for_run,
        plan_mission_run,
        set_mission_run_status,
    )
    from modules.backend.temporal.mission_run_models import (
        ActivityPolicySnapshot,
        BeginRunInput,
        CompactContextInput,
        DirectorTurnInput,
        ExecuteTaskInput,
        ExecuteTaskResult,
        FinaliseRunInput,
        GateDecisionUpdate,
        MissionRunWorkflowInput,
        MissionRunWorkflowState,
        MissionRunWorkflowStatus,
        NotificationRequest,
        PauseForRunInput,
        PauseRequest,
        PlanRunInput,
        RefinementOutcome,
        ResolveTaskInput,
        ResumeRequest,
        RunBudgetCheck,
        RunStatusUpdate,
        RunTaskGraph,
        SupervisorFollowupInput,
        TaskFailureDigest,
        TasksApprovedSignal,
        WriteDigestInput,
        digest_failures,
    )
    from modules.backend.temporal.notification_activities import send_mission_notification
    from modules.backend.temporal.run_memory_activities import (
        compact_mission_context,
        write_run_digest,
    )
    from modules.backend.temporal.supervisor_activities import (
        PostRunEvalInput,
        approve_run_proposed_tasks,
        check_plan_active,
        evaluate_post_run,
        fire_supervisor_followups,
        start_director_turn,
    )
    from modules.backend.temporal.task_activities import (
        execute_plan_task,
        resolve_failed_task,
    )

REFINE_PROMPT = (
    "The supervisor decided to advance the plan after wave {iteration}. "
    "Failures in that wave:\n{failures}\n"
    "Please call refine_plan to generate the next wave of tasks "
    "based on the outcomes, then approve them. "
    "If you judge that the mission objective is already met and no further "
    "tasks are needed, call declare_objective_met with your reason instead "
    "of refine_plan; do not just say so in your reply, and do not call both."
)
COMPLETE_PROMPT = (
    "The supervisor believes the mission objective may be met after {iteration} waves. "
    "Please review the plan outcomes and ask the user to confirm "
    "whether the mission is complete or needs more work."
)
ESCALATE_PROMPT = (
    "The supervisor escalated. Reason: {reason}. " "Please inform the user and ask for guidance."
)


# No digest-agent spend after a budget breach or a cancellation (contract 3.1.7).
_DETERMINISTIC_DIGEST_STATUSES = ("budget_stopped", "cancelled")
# ExecuteTaskResult.failure_class of a task stopped by its budget share (3.8.3).
_BUDGET_EXCEEDED = "budget_exceeded"
# The stop reason when a task exhausted its share but the run is under every cap.
_DEFAULT_BUDGET_BREACH = "budget_run_cap"


def _cause_type(e: ActivityError) -> str:
    cause = e.cause
    if isinstance(cause, ApplicationError):
        return cause.type or type(cause).__name__
    return type(cause).__name__


async def _exec(fn: Callable[..., Any], arg: object, p: ActivityPolicySnapshot) -> Any:
    return await workflow.execute_activity(fn, arg, **activity_kwargs(p))


def _render_failures(digests: list[TaskFailureDigest], truncated: int) -> str:
    lines = [
        f"- [{d.origin}/{d.failure_class}] x{d.occurrences} task {d.task_id}: {d.summary}"
        for d in digests
    ]
    if truncated:
        lines.append(f"- and {truncated} more distinct failures (see TaskFailedEvent history)")
    return "\n".join(lines) if lines else "- none"


@workflow.defn
class MissionRunWorkflow:
    @workflow.init
    def __init__(self, inp: MissionRunWorkflowInput) -> None:
        st = inp.state
        self._input = inp
        self._state: MissionRunWorkflowState | None = st
        self._phase = "planning"
        self._refinement_done = False
        self._refinement_outcome: RefinementOutcome | None = None
        self._approved_seq = st.approved_seq if st is not None else 0
        self._pause_requested = st.pause_requested if st is not None else False
        self._paused = st.paused if st is not None else False
        self._decision: GateDecisionUpdate | None = st.decision if st is not None else None
        self._wave_results: dict[str, ExecuteTaskResult] = {}
        self._wave_status = "completed"
        self._wave_cost_usd = 0.0
        self._wave_failure_reason: str | None = None
        self._wave_failures: list[TaskFailureDigest] = []
        self._wave_failures_truncated = 0
        self._lifecycle_signals = False  # set by run(): p88-lifecycle-signals (88.4.5)
        self._budget_caps = False  # set by run(): p88-budget-caps (88.4.6)
        # The run's headroom from the last budget point; recomputed before it is
        # used, so it is not carried across continue-as-new.
        self._headroom_usd: float | None = None

    @workflow.signal
    def tasks_approved(self, s: TasksApprovedSignal) -> None:
        self._approved_seq += 1

    @workflow.signal
    def request_pause(self, req: PauseRequest) -> None:
        """Pause at the next layer boundary, after the in-flight tasks finish (88.4.5)."""
        self._pause_requested = True

    @workflow.signal
    def resume(self, req: ResumeRequest) -> None:
        """Clear a pending pause; release a pause that no open gate holds (88.4.5)."""
        self._pause_requested = False
        if self._state is None or self._state.pending_gate is None:
            self._paused = False

    @workflow.signal
    def refinement_complete(self, outcome: RefinementOutcome | None = None) -> None:
        """Signal from ChatTurnWorkflow when the Director's refine turn ends.

        It means the turn ended, not that it refined: a turn that errored or
        never called refine_plan signals too. refine_plan waits for its
        refinement to commit or fail while a run is active, so the turn ends
        after it. _refine only wakes on this and fetch_run_task_graph
        decides; no new tasks fails the run with the outcome as the cause,
        unless the Director declared the objective met (objective_met_reason).
        """
        self._refinement_outcome = outcome
        self._refinement_done = True

    @workflow.query
    def get_run_state(self) -> MissionRunWorkflowStatus:
        s = self._state
        return MissionRunWorkflowStatus(
            mission_run_id=self._input.mission_run_id,
            iteration=s.iteration if s is not None else 0,
            phase=self._phase,
            pending_gate_id=None,
            pause_requested=self._pause_requested,
            last_supervisor_action=s.last_supervisor_action if s is not None else None,
        )

    @workflow.run
    async def run(self, inp: MissionRunWorkflowInput) -> str:
        c = inp.config
        self._lifecycle_signals = workflow.patched("p88-lifecycle-signals")
        self._budget_caps = workflow.patched("p88-budget-caps")
        try:
            if self._state is None:
                try:
                    b = await _exec(
                        begin_mission_run,
                        BeginRunInput(inp.mission_run_id),
                        c.persistence,
                    )
                except ActivityError as e:
                    if is_cancelled_exception(e):
                        raise
                    if _cause_type(e) == "RunStartRejectedError":
                        return "failed"
                    raise
                self._state = MissionRunWorkflowState(
                    iteration=0,
                    session_id=b.session_id,
                    execution_record_id=b.execution_record_id,
                    context_version_start=b.context_version_start,
                    run_started_at=workflow.now(),
                    excluded_wait_seconds=0,
                    pending_gate=None,
                    last_supervisor_action=None,
                    approved_seq=self._approved_seq,
                    pause_requested=self._pause_requested,
                    paused=self._paused,
                    decision=None,
                    last_can_iteration=0,
                )
                end = await self._budget_point()  # no planner spend after a breach
                if end is not None:
                    return end
                try:
                    p = await _exec(
                        plan_mission_run,
                        PlanRunInput(inp.mission_run_id, b.session_id),
                        c.plan_run,
                    )
                except ActivityError as e:
                    if is_cancelled_exception(e):
                        raise
                    return await self._end_run("failed", "planning_failed", _cause_type(e))
                if p.status == "failed":
                    return await self._end_run("failed", "planning_failed", p.detail)
            while True:
                await self._maybe_continue_as_new()
                seen = self._approved_seq  # recorded before the fetch (contracts 3.3.3)
                graph = await _exec(fetch_run_task_graph, inp.mission_run_id, c.persistence)
                if graph.approved == 0:
                    if graph.proposed == 0:
                        return await self._end_run("succeeded", "no_further_work", None)
                    await self._wait_for_approval(seen)
                    continue
                self._state.iteration += 1  # one iteration == one executed wave
                end = await self._execute_layers(graph)
                if end is not None:
                    return end
                end = await self._supervise(seen)
                if end is not None:
                    return end
        except (asyncio.CancelledError, ActivityError) as e:
            # Workflow cancellation reaches an awaited activity as ActivityError
            # with a CancelledError cause, not as asyncio.CancelledError.
            if not is_cancelled_exception(e):
                raise
            await self._end_run("cancelled", None, None)
            raise

    # ── Layers ───────────────────────────────────────────────────────────

    async def _execute_layers(self, graph: RunTaskGraph) -> str | None:
        cfg = self._input.config
        self._phase = "executing"
        self._wave_results = {}  # final result per task id, in execution order
        if await self._gate("pre_dispatch", None) == "abort":
            return await self._end_run("cancelled", "gate_rejected", "aborted at pre_dispatch")
        for layer in graph.layers:
            if await self._gate("pre_layer", None) == "abort":
                return await self._end_run("cancelled", "gate_rejected", "aborted at pre_layer")
            for start in range(0, len(layer), cfg.max_parallel_tasks):
                end = await self._layer_boundary()
                if end is not None:
                    return end
                chunk = layer[start : start + cfg.max_parallel_tasks]
                share = None if self._headroom_usd is None else self._headroom_usd / len(chunk)
                outcomes = await asyncio.gather(
                    *(self._run_task(t, share) for t in chunk), return_exceptions=True
                )
                for outcome in outcomes:
                    if isinstance(outcome, BaseException) and (
                        not isinstance(outcome, ActivityError) or is_cancelled_exception(outcome)
                    ):
                        raise outcome
                end = await self._budget_exceeded_stop(outcomes)
                if end is not None:
                    return end
                failed = [o for o in outcomes if isinstance(o, ActivityError)]
                if failed:
                    return await self._end_run("failed", "task_failures", str(failed[0])[:500])
                for task_id, result in zip(chunk, outcomes, strict=True):
                    end = await self._after_task(task_id, result)
                    if end is not None:
                        return end
            if await self._gate("post_layer", None) == "abort":
                return await self._end_run("cancelled", "gate_rejected", "aborted at post_layer")
        results = list(self._wave_results.values())
        failed_results = [r for r in results if r.status == "failed"]
        self._wave_status = "failed" if failed_results else "completed"
        if any(r.status == "completed" for r in results):
            self._state.zero_completion_waves = 0
        else:
            self._state.zero_completion_waves += 1
        self._wave_cost_usd = sum(r.cost_usd for r in results)
        self._wave_failure_reason = failed_results[0].failure_reason if failed_results else None
        self._wave_failures, self._wave_failures_truncated = digest_failures(
            failed_results, cfg.max_failure_digests
        )
        return None

    async def _layer_boundary(self) -> str | None:
        """Runs before each chunk: the pause point, the duration check, the budget point."""
        await self._pause_point()
        if self._duration_exhausted():
            return await self._end_run(
                "failed",
                "max_duration_exceeded",
                "max_run_duration_seconds reached at a layer boundary",
            )
        return await self._budget_point()

    async def _budget_point(self) -> str | None:
        """Refresh the run's headroom; stop the run when a cap is breached (88.4.6)."""
        if not self._budget_caps:
            return None
        inp = self._input
        check: RunBudgetCheck = await _exec(
            check_run_budget, inp.mission_run_id, inp.config.persistence
        )
        self._headroom_usd = check.headroom_usd
        if check.breach is None:
            return None
        return await self._budget_stop(check.breach)

    async def _budget_exceeded_stop(self, outcomes: list[Any]) -> str | None:
        """Stop the run when a task of the chunk was stopped by its budget share.

        Every future of the chunk has resolved, so no task is in flight. The
        check reads failure_class, never failure_reason, which committed replay
        histories redact (contracts 3.8.1 item 5).
        """
        if not self._budget_caps or not any(
            isinstance(o, ExecuteTaskResult) and o.failure_class == _BUDGET_EXCEEDED
            for o in outcomes
        ):
            return None
        inp = self._input
        check: RunBudgetCheck = await _exec(
            check_run_budget, inp.mission_run_id, inp.config.persistence
        )
        return await self._budget_stop(check.breach or _DEFAULT_BUDGET_BREACH)

    async def _budget_stop(self, breach: str) -> str:
        """End the run BUDGET_STOPPED, pause the mission, then send BUDGET_PAUSED."""
        inp = self._input
        status = await self._end_run("budget_stopped", breach, None)
        await _exec(
            pause_mission_for_run,
            PauseForRunInput(inp.mission_run_id, breach),
            inp.config.persistence,
        )
        await self._notify(
            NotificationRequest(
                kind="budget_paused",
                mission_id=inp.mission_id,
                mission_run_id=inp.mission_run_id,
                gate_request_id=None,
                subject_id=inp.mission_run_id,
                payload={"cap": breach},
            )
        )
        return status

    async def _pause_point(self) -> None:
        """Hold the run PAUSED while a user pause stands; the pause is excluded from the duration.

        A layer boundary is reached only after the previous chunk's tasks
        resolved, so no task is in flight while the run is paused.
        """
        if not self._lifecycle_signals or not self._pause_requested:
            return
        inp = self._input
        await _exec(
            set_mission_run_status,
            RunStatusUpdate(inp.mission_run_id, "paused", "user_pause", None),
            inp.config.persistence,
        )
        self._paused = True
        self._phase = "paused"
        paused_at = workflow.now()
        await workflow.wait_condition(lambda: not self._paused)
        self._state.excluded_wait_seconds += int((workflow.now() - paused_at).total_seconds())
        self._phase = "executing"
        await _exec(
            set_mission_run_status,
            RunStatusUpdate(inp.mission_run_id, "running", None, None),
            inp.config.persistence,
        )

    async def _run_task(self, task_id: str, budget_headroom_usd: float | None) -> ExecuteTaskResult:
        cfg = self._input.config
        return await workflow.execute_activity(
            execute_plan_task,
            ExecuteTaskInput(
                mission_run_id=self._input.mission_run_id,
                task_id=task_id,
                session_id=self._state.session_id,
                execution_record_id=self._state.execution_record_id,
                budget_headroom_usd=budget_headroom_usd,
                heartbeat_interval_seconds=cfg.task_heartbeat_interval_seconds,
            ),
            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            **activity_kwargs(cfg.execute_task),
        )

    async def _after_task(self, task_id: str, result: ExecuteTaskResult) -> str | None:
        self._wave_results[task_id] = result
        while result.verification_failed:
            action = await self._gate("verification_failed", task_id)
            if action == "abort":
                return await self._end_run(
                    "cancelled",
                    "gate_rejected",
                    f"aborted at verification_failed for {task_id}",
                )
            if action not in ("retry", "skip"):
                return None  # "continue" from the Phase 2 seam: the task stays FAILED
            await _exec(
                resolve_failed_task,
                ResolveTaskInput(self._input.mission_run_id, task_id, action),
                self._input.config.persistence,
            )
            if action == "skip":
                # 3.3.5: failure fields are set only when status == "failed"
                self._wave_results[task_id] = dataclasses.replace(
                    result,
                    status="skipped",
                    failure_origin=None,
                    failure_class=None,
                    failure_fingerprint=None,
                )
                return None
            if self._duration_exhausted():
                return await self._end_run(
                    "failed",
                    "max_duration_exceeded",
                    "max_run_duration_seconds reached before a retry",
                )
            end = await self._budget_point()  # the retry runs on fresh headroom
            if end is not None:
                return end
            try:
                result = await self._run_task(task_id, self._headroom_usd)
            except ActivityError as err:
                if is_cancelled_exception(err):
                    raise
                return await self._end_run("failed", "task_failures", str(err)[:500])
            end = await self._budget_exceeded_stop([result])
            if end is not None:
                return end
            self._wave_results[task_id] = result
        if result.status == "completed" and await self._gate("post_task", task_id) == "abort":
            return await self._end_run(
                "cancelled", "gate_rejected", f"aborted at post_task for {task_id}"
            )
        return None

    async def _gate(self, gate_point: str, task_id: str | None) -> str:
        """Return an action from 3.3.6, or "continue"; issues no command.

        88.4.8 replaces the body under patch id p88-durable-gate.
        """
        return "continue"

    # ── Supervisor ───────────────────────────────────────────────────────

    async def _supervise(self, seen: int) -> str | None:
        inp = self._input
        c = inp.config
        s = self._state
        self._phase = "supervising"
        try:
            ev = await _exec(
                evaluate_post_run,
                PostRunEvalInput(
                    inp.mission_id,
                    inp.mission_run_id,
                    s.execution_record_id,
                    s.iteration - 1,
                    s.session_id,
                    s.zero_completion_waves,
                    wave_task_ids=list(self._wave_results),
                ),
                c.evaluate_post_run,
            )
        except ActivityError as e:
            if is_cancelled_exception(e):
                raise
            return await self._end_run("failed", "supervisor_escalated", _cause_type(e))
        s.last_supervisor_action = ev.action
        await _exec(
            fire_supervisor_followups,
            SupervisorFollowupInput(
                mission_id=inp.mission_id,
                mission_run_id=inp.mission_run_id,
                execution_record_id=s.execution_record_id,
                action=ev.action,
                reason=ev.reason[:200],
                reviewer=ev.reviewer,
                wave_status=self._wave_status,
                wave_cost_usd=self._wave_cost_usd,
                failure_reason=self._wave_failure_reason,
            ),
            c.persistence,
        )
        # Executions on the old branch still poll the mission; from
        # p88-lifecycle-signals a pause arrives through request_pause.
        if not self._lifecycle_signals:
            if not await _exec(check_plan_active, inp.mission_id, c.persistence):
                return await self._end_run("cancelled", "cancelled_by_user", "plan paused")
        if ev.action == "wait":
            return await self._supervisor_wait(seen)
        if ev.action == "advance_approved":
            await _exec(approve_run_proposed_tasks, inp.mission_run_id, c.persistence)
            return None
        if ev.action == "advance_refine":
            return await self._refine()
        if ev.action == "propose_complete":
            await self._director_turn(COMPLETE_PROMPT.format(iteration=s.iteration), None)
            return await self._end_run("succeeded", "objective_met", ev.reason[:500])
        if ev.action == "escalate":
            await self._director_turn(ESCALATE_PROMPT.format(reason=ev.reason[:200]), None)
            return await self._end_run("failed", "supervisor_escalated", ev.reason[:500])
        return await self._end_run("failed", "supervisor_escalated", f"unknown action {ev.action}")

    async def _refine(self) -> str | None:
        inp = self._input
        c = inp.config
        self._refinement_done = False
        self._refinement_outcome = None
        failures = _render_failures(self._wave_failures, self._wave_failures_truncated)
        await self._director_turn(
            REFINE_PROMPT.format(iteration=self._state.iteration, failures=failures),
            workflow.info().workflow_id,
        )
        try:
            await workflow.wait_condition(
                lambda: self._refinement_done,
                timeout=timedelta(seconds=c.refine_wait_seconds),
            )
        except asyncio.TimeoutError:
            # best-effort — workflow code stays deterministic, so no event
            # bus is reachable here; the graph fetch below decides what next.
            workflow.logger.warning(
                "refinement signal not received", extra={"mission_id": inp.mission_id}
            )
        outcome = self._refinement_outcome if self._refinement_done else None
        declared = outcome.objective_met_reason if outcome is not None else None
        if declared is not None and outcome.refined:
            # The Director said there is nothing left to do and also refined:
            # neither reading is safe to act on, so stop loudly. The task graph
            # cannot decide this: it holds APPROVED tasks the turn did not add.
            detail = (
                "refine contradiction: the Director declared the objective met "
                f"and called refine_plan; Director's reason: {declared}"
            )
            return await self._end_run("failed", "supervisor_escalated", detail[:500])
        # A turn that failed after declaring is not trusted: it is handled
        # below as any failed turn, with the turn's error as the cause.
        if declared is not None and not outcome.error:
            detail = f"Director declared the objective met: {declared}"
            return await self._end_run(
                "succeeded", "objective_met", detail[:500], director_objective_met=declared
            )
        after = await _exec(fetch_run_task_graph, inp.mission_run_id, c.persistence)
        if after.proposed > 0:
            await _exec(approve_run_proposed_tasks, inp.mission_run_id, c.persistence)
        if after.proposed > 0 or after.approved > 0:
            return None
        detail = f"refine produced no tasks: {self._refine_cause()}"
        return await self._end_run("failed", "supervisor_escalated", detail[:500])

    def _refine_cause(self) -> str:
        """Why the refine turn added no tasks, from the refinement_complete payload."""
        if not self._refinement_done:
            seconds = self._input.config.refine_wait_seconds
            return f"no refinement_complete signal within {seconds}s"
        outcome = self._refinement_outcome
        if outcome is None:
            return "Director turn ended without an outcome"
        if outcome.error:
            return outcome.error
        return f"Director turn ended without new tasks; Director replied: {outcome.reply}"

    async def _director_turn(self, prompt: str, signal_workflow_id: str | None) -> None:
        inp = self._input
        await _exec(
            start_director_turn,
            DirectorTurnInput(
                inp.mission_id,
                inp.mission_run_id,
                self._state.session_id,
                prompt,
                signal_workflow_id,
            ),
            inp.config.director_turn,
        )

    # ── Continue-as-new ──────────────────────────────────────────────────

    async def _maybe_continue_as_new(self) -> None:
        """Hand over to a fresh run at the loop top, a layer boundary with no activity in flight.

        Fires after config.continue_as_new_after_iterations waves since the last
        hand-over, or earlier when the server suggests it, but only after
        progress and never with a gate open. The workflow id and the config
        snapshot are carried unchanged, and the handler-owned fields travel in
        state, so a pending approval and the elapsed-time budget survive.
        """
        s = self._state
        if s.pending_gate is not None or s.iteration <= s.last_can_iteration:
            return
        n = self._input.config.continue_as_new_after_iterations
        due = s.iteration - s.last_can_iteration >= n
        if not (due or workflow.info().is_continue_as_new_suggested()):
            return
        await workflow.wait_condition(workflow.all_handlers_finished)
        s.last_can_iteration = s.iteration
        s.approved_seq = self._approved_seq
        s.pause_requested = self._pause_requested
        s.paused = self._paused
        s.decision = self._decision
        workflow.continue_as_new(dataclasses.replace(self._input, state=s))

    # ── Waits and the hard stop ──────────────────────────────────────────

    async def _supervisor_wait(self, seen: int) -> str | None:
        """Durable WAIT: counts against the duration and holds the active-run slot."""
        self._phase = "supervising"
        try:
            await workflow.wait_condition(
                lambda: self._approved_seq > seen, timeout=self._remaining_duration()
            )
        except asyncio.TimeoutError:
            return await self._end_run(
                "failed",
                "max_duration_exceeded",
                "idle wait exceeded max_run_duration_seconds",
            )
        return None

    async def _wait_for_approval(self, seen: int) -> None:
        """Human approval wait: no timeout until 88.4.8; excluded from the duration."""
        self._phase = "awaiting_gate"
        opened = workflow.now()
        await workflow.wait_condition(lambda: self._approved_seq > seen)
        self._state.excluded_wait_seconds += int((workflow.now() - opened).total_seconds())

    def _duration_used_seconds(self) -> float:
        elapsed = (workflow.now() - self._state.run_started_at).total_seconds()
        return elapsed - self._state.excluded_wait_seconds

    def _duration_exhausted(self) -> bool:
        return self._duration_used_seconds() >= self._input.config.max_run_duration_seconds

    def _remaining_duration(self) -> timedelta:
        remaining = self._input.config.max_run_duration_seconds - self._duration_used_seconds()
        return timedelta(seconds=max(remaining, 1))

    async def _end_run(
        self,
        status: str,
        reason: str | None,
        detail: str | None,
        *,
        director_objective_met: str | None = None,
    ) -> str:
        self._phase = "finalising"
        inp = self._input
        c = inp.config
        # _state is set only once begin_mission_run returned (or from a
        # continue-as-new input), so a non-None state means the run reached
        # RUNNING and owes a digest (contract 3.1.7 invariant).
        if self._state is not None and workflow.patched("p88-run-memory"):
            try:
                await _exec(
                    compact_mission_context,
                    CompactContextInput(
                        mission_id=inp.mission_id, mission_run_id=inp.mission_run_id
                    ),
                    c.persistence,
                )
            except ActivityError:
                # non-fatal: the digest must still be written; the next MCD write
                # over the cap compacts again. Workflows cannot publish events;
                # the failure stays in this run's Temporal history.
                workflow.logger.warning(
                    "run-end compaction failed; digest continues",
                    extra={"mission_id": inp.mission_id, "mission_run_id": inp.mission_run_id},
                )
            await _exec(
                write_run_digest,
                WriteDigestInput(
                    mission_run_id=inp.mission_run_id,
                    status=status,
                    reason=reason,
                    force_deterministic=status in _DETERMINISTIC_DIGEST_STATUSES,
                ),
                c.write_digest,
            )
        result = await _exec(
            finalise_mission_run,
            FinaliseRunInput(inp.mission_run_id, status, reason, detail, director_objective_met),
            c.persistence,
        )
        # A budget stop sends BUDGET_PAUSED itself, after pausing the mission.
        if (
            self._lifecycle_signals
            and result.notification is not None
            and status != "budget_stopped"
        ):
            await self._notify(result.notification)
        return status

    async def _notify(self, req: NotificationRequest) -> None:
        """The workflow's only way to send a notification; a failure is logged, never raised."""
        try:
            await _exec(send_mission_notification, req, self._input.config.notify)
        except ActivityError as e:
            # best-effort — workflows cannot publish events; the failure stays in
            # this run's Temporal history and the delivery rows record it.
            workflow.logger.warning(
                "notification failed",
                extra={
                    "mission_id": req.mission_id,
                    "mission_run_id": self._input.mission_run_id,
                    "kind": req.kind,
                    "cause": _cause_type(e),
                },
            )
