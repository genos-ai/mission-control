"""Mission Run Workflow (Plan 88 step 88.1.8, contract 3.3.3).

One durable workflow per MissionRun. It begins the run, plans it, then loops:
fetch the run's task graph, execute a wave of approved tasks, persist, ask the
post-run supervisor, and route its decision. The loop ends through _end_run,
which finalises the run.

The workflow reads no config: every timeout and retry policy comes from the
RunConfigSnapshot pinned in MissionRunWorkflowInput. The loop is bounded by the
supervisor's iteration breaker (gate_post_run.py breaker #2); there is no
workflow iteration cap and no continue-as-new in Phase 1.
"""

import asyncio
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.exceptions import ActivityError, ApplicationError, is_cancelled_exception

with workflow.unsafe.imports_passed_through():
    from modules.backend.temporal.activities import execute_mission, persist_mission_outcome
    from modules.backend.temporal.activity_options import activity_kwargs
    from modules.backend.temporal.mission_run_activities import (
        begin_mission_run,
        fetch_run_task_graph,
        finalise_mission_run,
        plan_mission_run,
    )
    from modules.backend.temporal.mission_run_models import (
        ActivityPolicySnapshot,
        BeginRunInput,
        DirectorTurnInput,
        ExecuteWaveInput,
        FinaliseRunInput,
        GateDecisionUpdate,
        MissionRunWorkflowInput,
        MissionRunWorkflowState,
        MissionRunWorkflowStatus,
        PlanRunInput,
        SupervisorFollowupInput,
        TasksApprovedSignal,
    )
    from modules.backend.temporal.supervisor_activities import (
        PostRunEvalInput,
        approve_run_proposed_tasks,
        check_plan_active,
        evaluate_post_run,
        fire_supervisor_followups,
        start_director_turn,
    )

REFINE_PROMPT = (
    "The supervisor decided to advance the plan after wave {iteration}. "
    "Please call refine_plan to generate the next wave of tasks "
    "based on the outcomes, then approve them."
)
COMPLETE_PROMPT = (
    "The supervisor believes the mission objective may be met after {iteration} waves. "
    "Please review the plan outcomes and ask the user to confirm "
    "whether the mission is complete or needs more work."
)
ESCALATE_PROMPT = (
    "The supervisor escalated. Reason: {reason}. " "Please inform the user and ask for guidance."
)


def _cause_type(e: ActivityError) -> str:
    cause = e.cause
    if isinstance(cause, ApplicationError):
        return cause.type or type(cause).__name__
    return type(cause).__name__


async def _exec(fn: Callable[..., Any], arg: object, p: ActivityPolicySnapshot) -> Any:
    return await workflow.execute_activity(fn, arg, **activity_kwargs(p))


def _wave_failure(outcome_json: dict) -> str | None:
    """The wave's abort reason or error, truncated; None when it has neither."""
    failure = outcome_json.get("abort_reason") or outcome_json.get("error")
    return str(failure)[:500] if failure else None


@workflow.defn
class MissionRunWorkflow:
    @workflow.init
    def __init__(self, inp: MissionRunWorkflowInput) -> None:
        st = inp.state
        self._input = inp
        self._state: MissionRunWorkflowState | None = st
        self._phase = "planning"
        self._refinement_done = False
        self._approved_seq = st.approved_seq if st is not None else 0
        self._pause_requested = st.pause_requested if st is not None else False
        self._paused = st.paused if st is not None else False
        self._decision: GateDecisionUpdate | None = st.decision if st is not None else None

    @workflow.signal
    def tasks_approved(self, s: TasksApprovedSignal) -> None:
        self._approved_seq += 1

    @workflow.signal
    def refinement_complete(self) -> None:
        """Signal from ChatTurnWorkflow when the Director finishes refining."""
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
        try:
            if self._state is None:
                try:
                    b = await _exec(
                        begin_mission_run, BeginRunInput(inp.mission_run_id), c.persistence
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
                    pending_gate=None,
                    last_supervisor_action=None,
                    approved_seq=self._approved_seq,
                    pause_requested=self._pause_requested,
                    paused=self._paused,
                    decision=None,
                )
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
            s = self._state
            while True:
                seen = self._approved_seq
                g = await _exec(fetch_run_task_graph, inp.mission_run_id, c.persistence)
                if g.approved == 0:
                    if g.proposed == 0:
                        return await self._end_run("succeeded", "no_further_work", None)
                    self._phase = "awaiting_gate"
                    await workflow.wait_condition(lambda: self._approved_seq > seen)
                    continue
                s.iteration += 1
                self._phase = "executing"
                try:
                    wave = await _exec(
                        execute_mission,
                        ExecuteWaveInput(inp.mission_run_id, s.session_id, s.execution_record_id),
                        c.execute_task,
                    )
                except ActivityError as e:
                    if is_cancelled_exception(e):
                        raise
                    return await self._end_run("failed", "task_failures", _cause_type(e))
                await workflow.execute_activity(
                    persist_mission_outcome,
                    args=[
                        inp.mission_run_id,
                        s.session_id,
                        wave.outcome_json,
                        inp.mission_id,
                        s.execution_record_id,
                    ],
                    **activity_kwargs(c.persistence),
                )
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
                        wave_status=wave.status,
                        wave_cost_usd=wave.total_cost_usd,
                        failure_reason=_wave_failure(wave.outcome_json),
                    ),
                    c.persistence,
                )
                if not await _exec(check_plan_active, inp.mission_id, c.persistence):
                    return await self._end_run("cancelled", "cancelled_by_user", "plan paused")
                if ev.action == "wait":
                    continue
                if ev.action == "advance_approved":
                    await _exec(approve_run_proposed_tasks, inp.mission_run_id, c.persistence)
                    continue
                if ev.action == "advance_refine":
                    self._refinement_done = False
                    await _exec(
                        start_director_turn,
                        DirectorTurnInput(
                            inp.mission_id,
                            inp.mission_run_id,
                            s.session_id,
                            REFINE_PROMPT.format(iteration=s.iteration),
                            workflow.info().workflow_id,
                        ),
                        c.director_turn,
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
                    after = await _exec(fetch_run_task_graph, inp.mission_run_id, c.persistence)
                    if after.proposed > 0:
                        await _exec(approve_run_proposed_tasks, inp.mission_run_id, c.persistence)
                    if after.proposed == 0 and after.approved == 0:
                        return await self._end_run(
                            "failed", "supervisor_escalated", "refine produced no tasks"
                        )
                    continue
                if ev.action == "propose_complete":
                    await _exec(
                        start_director_turn,
                        DirectorTurnInput(
                            inp.mission_id,
                            inp.mission_run_id,
                            s.session_id,
                            COMPLETE_PROMPT.format(iteration=s.iteration),
                            None,
                        ),
                        c.director_turn,
                    )
                    return await self._end_run("succeeded", "objective_met", ev.reason[:500])
                if ev.action == "escalate":
                    await _exec(
                        start_director_turn,
                        DirectorTurnInput(
                            inp.mission_id,
                            inp.mission_run_id,
                            s.session_id,
                            ESCALATE_PROMPT.format(reason=ev.reason[:200]),
                            None,
                        ),
                        c.director_turn,
                    )
                    return await self._end_run("failed", "supervisor_escalated", ev.reason[:500])
                return await self._end_run(
                    "failed", "supervisor_escalated", f"unknown action {ev.action}"
                )
        except (asyncio.CancelledError, ActivityError) as e:
            # Workflow cancellation reaches an awaited activity as ActivityError
            # with a CancelledError cause, not as asyncio.CancelledError.
            if not is_cancelled_exception(e):
                raise
            await self._end_run("cancelled", None, None)
            raise

    async def _end_run(self, status: str, reason: str | None, detail: str | None) -> str:
        self._phase = "finalising"
        await _exec(
            finalise_mission_run,
            FinaliseRunInput(self._input.mission_run_id, status, reason, detail),
            self._input.config.persistence,
        )
        return status
