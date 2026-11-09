"""
Workflow Run Waves Mixin — extracted from workflow_run.py.

Contains the wave-execution engine: topological sorting of steps into
parallel waves, concurrent step dispatch within a wave, single-step
execution, and objective building. Separated because wave orchestration
is a distinct concern from run lifecycle management, definition
resolution, and notification.

Per-node-type step executors (condition, decision, branch, merge,
notification, tool_call, llm_call, human_input, sub_workflow) live in
the sibling workflow_run_steps/ package (Plan 84 Phase 5.1) — this file
keeps the wave engine and _execute_step's dispatch table plus the
agent_step default-path logic (the one node_type with no dedicated
executor module, since it's the load-bearing handle_mission dispatch).

Mixed into WorkflowRunService — do not instantiate directly.
"""

from __future__ import annotations

import asyncio
import uuid as _uuid
from typing import TYPE_CHECKING, Any

from modules.backend.core.config import get_app_config
from modules.backend.core.exceptions import WorkflowOutputMappingError
from modules.backend.core.logging import get_logger
from modules.backend.events.types import (
    MissionPlanTaskStatusChangedEvent,
    SystemEvent,
    WorkflowExecutionCompletedEvent,
    WorkflowExecutionStartedEvent,
    WorkflowRunStartedEvent,
    WorkflowStepSkippedEvent,
)
from modules.backend.models.task import TaskStatus
from modules.backend.services.workflow_run_steps import control, io, sub_workflow
from modules.backend.services.workflow_run_steps.helpers import (
    StepContext,
    VirtualExecution,
    build_step_objective,
    compute_waves,
    extract_default_agent_output,
    extract_first_task_failure,
    resolve_dispatch_params,
    should_skip,
)
from modules.backend.services.workflow_run_steps.human_input import execute_human_input_step

if TYPE_CHECKING:
    from modules.backend.models.workflow_run import WorkflowRun
    from modules.backend.schemas.workflow import WorkflowSchema, WorkflowStepSchema

logger = get_logger(__name__)

# Re-exported for backward compatibility — external callers (workflow_run.py)
# import StepContext from this module. VirtualExecution
# has no external callers but is kept here too since it's this module's
# public-facing return type.
__all__ = ["StepContext", "VirtualExecution", "WorkflowRunWavesMixin"]


class WorkflowRunWavesMixin:
    """Wave-execution methods for WorkflowRunService.

    Mixed into WorkflowRunService — do not instantiate directly.
    All methods reference self._step_context_factory and
    self._workflow_service which are set by
    WorkflowRunService.__init__().
    """

    async def _publish_workflow_event(self, mission_id: str | None, event: Any) -> None:
        """Best-effort publish to mission SSE stream."""
        if not self._event_bus or not mission_id:
            return
        try:
            await self._event_bus.publish_to_mission(mission_id, event)
        except Exception:
            # Catch-all justified: this IS the event-emission path
            # (Redis publish can fail many ways) and there is nowhere
            # further to escalate to.
            logger.debug("Workflow event publish failed", exc_info=True)

    async def _resolve_workflow_plan_id(self, mission_id: str | None) -> str | None:
        """Look up the MissionPlan ID for Kanban state transitions. Best-effort."""
        if not mission_id:
            return None
        try:
            from sqlalchemy.exc import SQLAlchemyError

            from modules.backend.core.database import get_async_session
            from modules.backend.repositories.mission_plan import MissionPlanRepository

            async with get_async_session() as db:
                repo = MissionPlanRepository(db)
                plan = await repo.get_by_mission_id(mission_id)
                return plan.id if plan else None
        except SQLAlchemyError:
            logger.debug(
                "Plan ID lookup failed for mission", extra={"mission_id": mission_id}, exc_info=True
            )
            return None

    async def _sync_plan_task_states(
        self,
        plan_id: str | None,
        mission_id: str | None,
        step_updates: list[tuple[str, TaskStatus]],
        session_id: str,
        *,
        failure_reason: str | None = None,
        failure_reasons: dict[str, str] | None = None,
        cost_map: dict[str, float] | None = None,
        step_task_map: dict[str, str] | None = None,
    ) -> None:
        """Batch update Task statuses for Kanban board visibility.

        Uses a separate DB session to avoid interfering with the main
        workflow session. Best-effort — failures are logged, not raised.

        Args:
            step_task_map: Maps workflow step_id → Task UUID. Created by
                _persist_workflow_as_plan when tasks get real UUIDs.
        """
        if not plan_id or not mission_id or not step_updates:
            return
        try:
            from modules.backend.core.database import get_async_session
            from modules.backend.core.utils import utc_now
            from modules.backend.repositories.task import TaskRepository

            _map = step_task_map or {}

            async with get_async_session() as db:
                task_repo = TaskRepository(db)
                for step_id, to_status in step_updates:
                    task_id = _map.get(step_id, step_id)
                    task = await task_repo.get_by_id_or_none(task_id)
                    if not task:
                        continue

                    from_status = task.status
                    task.status = to_status

                    if to_status == TaskStatus.RUNNING:
                        task.last_attempt_at = utc_now()
                    if to_status == TaskStatus.FAILED:
                        # Prefer per-step reason; fall back to shared one.
                        reason = (failure_reasons or {}).get(step_id) or failure_reason
                        if reason:
                            task.failure_reason = reason[:500]
                    if cost_map and step_id in cost_map:
                        task.cost_usd = cost_map[step_id]

                    await self._publish_workflow_event(
                        mission_id,
                        MissionPlanTaskStatusChangedEvent(
                            session_id=_uuid.UUID(session_id),
                            source="workflow_run_service",
                            mission_id=mission_id,
                            plan_id=plan_id,
                            task_id=task.id,
                            from_status=from_status,
                            to_status=to_status,
                            actor="workflow_run_service",
                        ),
                    )

                await db.commit()
        except Exception:
            # Catch-all justified: this is a best-effort Kanban sync (see
            # docstring) spanning DB writes and event publishes across a
            # loop of steps — a partial failure must not break the main
            # workflow run.
            logger.debug("Plan task state sync failed (non-fatal)", exc_info=True)

    async def _execute_steps(
        self,
        run: WorkflowRun,
        workflow: WorkflowSchema,
        session_id: str,
        on_progress: Any | None = None,
        gate: object | None = None,
        edges: list[dict] | None = None,
        step_task_map: dict[str, str] | None = None,
    ) -> None:
        """Execute steps in topological wave order.

        Steps within a wave have no mutual dependencies and run in
        parallel via asyncio.gather. Each step gets its own DB session
        (via step_context_factory) to avoid SQLAlchemy flush conflicts.
        Falls back to sequential execution when no factory is provided.
        """
        waves = compute_waves(workflow.steps)
        completed_outcomes: dict[str, dict] = {}
        step_map = {step.id: step for step in workflow.steps}
        total_steps = len(workflow.steps)

        # Resolve plan_id for Kanban task state updates (best-effort)
        _plan_id = await self._resolve_workflow_plan_id(run.mission_id)
        _step_task_map = step_task_map or {}

        # Build edge map: (source, target) → label (for condition routing)
        edges_map: dict[tuple[str, str], str | None] = {}
        for e in edges or []:
            edges_map[(e.get("source", ""), e.get("target", ""))] = e.get("label")

        def _emit(event: dict) -> None:
            if on_progress:
                on_progress(event)

        _emit(
            {
                "type": "workflow_start",
                "workflow": workflow.workflow_name,
                "total_steps": total_steps,
            }
        )
        await self._publish_workflow_event(
            run.mission_id,
            WorkflowRunStartedEvent(
                session_id=_uuid.UUID(session_id),
                source="workflow_run_service",
                workflow_run_id=run.id,
                workflow_name=workflow.workflow_name,
                workflow_version=run.workflow_version or 1,
                step_count=total_steps,
                trigger_type=run.trigger_type or "on_demand",
                triggered_by=run.triggered_by or "",
            ),
        )

        for wave_num, wave_step_ids in enumerate(waves):
            logger.info(
                "Executing wave",
                extra={
                    "run_id": run.id,
                    "wave": wave_num + 1,
                    "steps": wave_step_ids,
                },
            )

            # Check budget before each wave
            if run.budget_usd and run.total_cost_usd >= run.budget_usd:
                raise RuntimeError(
                    f"Budget exceeded: ${run.total_cost_usd:.4f} >= " f"${run.budget_usd:.2f}"
                )

            # Partition wave into skipped and executable steps
            executable_ids: list[str] = []
            for step_id in wave_step_ids:
                if should_skip(
                    step_id,
                    step_map,
                    completed_outcomes,
                    edges_map,
                    run.context,
                    mission_id=run.mission_id,
                ):
                    completed_outcomes[step_id] = {"_skipped": True}
                    step_obj = step_map[step_id]
                    reason = (
                        f"inline condition false: {step_obj.condition}"
                        if step_obj.condition
                        else "condition branch not taken"
                    )
                    _emit(
                        {
                            "type": "step_skipped",
                            "step_id": step_id,
                            "reason": reason,
                        }
                    )
                    await self._publish_workflow_event(
                        run.mission_id,
                        WorkflowStepSkippedEvent(
                            session_id=_uuid.UUID(session_id),
                            source="workflow_run_service",
                            workflow_run_id=run.id,
                            step_id=step_id,
                            reason=reason,
                        ),
                    )
                    logger.info(
                        "Skipping step",
                        extra={"step_id": step_id, "run_id": run.id, "reason": reason},
                    )
                else:
                    executable_ids.append(step_id)

            # Emit step_start for executable steps
            for step_id in executable_ids:
                step = step_map[step_id]
                _emit(
                    {
                        "type": "step_start",
                        "step_id": step_id,
                        "capability": step.capability,
                        "description": step.description or step_id,
                    }
                )
                await self._publish_workflow_event(
                    run.mission_id,
                    WorkflowExecutionStartedEvent(
                        session_id=_uuid.UUID(session_id),
                        source="workflow_run_service",
                        workflow_run_id=run.id,
                        mission_id=run.mission_id or "",
                        step_id=step_id,
                        roster_ref=step.roster or "",
                        complexity_tier=step.complexity_tier or "standard",
                    ),
                )

            # Kanban: mark skipped steps as SKIPPED, executable as RUNNING
            if _plan_id:
                _wave_skipped = [sid for sid in wave_step_ids if sid not in set(executable_ids)]
                _state_updates: list[tuple[str, TaskStatus]] = [
                    (sid, TaskStatus.SKIPPED) for sid in _wave_skipped
                ]
                if _state_updates:
                    await self._sync_plan_task_states(
                        _plan_id,
                        run.mission_id,
                        _state_updates,
                        session_id,
                        step_task_map=_step_task_map,
                    )

            # ── Pre-execution approval (Plan 80h) ────────────────────
            # Block until each executable step's task is APPROVED. For
            # autonomous mode this is a fast pass-through (auto-approver
            # already transitioned the task at creation). For interactive
            # modes (manual/interactive/ai_assisted), waits for the
            # operator to approve via `mc plan approve <task_id>`. The
            # waits run in parallel — operator can approve in any order.
            if _step_task_map and executable_ids:
                from modules.backend.agents.mission_control.task_approval import wait_until_approved
                from modules.backend.core.database import get_session_factory

                factory = get_session_factory()
                manual = get_app_config().gate.manual
                waiters = [
                    wait_until_approved(
                        task_id=_step_task_map[sid],
                        session_factory=factory,
                        timeout_seconds=manual.timeout_seconds,
                        poll_interval_seconds=manual.poll_interval_seconds,
                    )
                    for sid in executable_ids
                    if sid in _step_task_map
                ]
                if waiters:
                    await asyncio.gather(*waiters)

            # Now transition approved tasks to RUNNING.
            if _plan_id and executable_ids:
                await self._sync_plan_task_states(
                    _plan_id,
                    run.mission_id,
                    [(sid, TaskStatus.RUNNING) for sid in executable_ids],
                    session_id,
                    step_task_map=_step_task_map,
                )

            # Execute all steps in this wave concurrently
            wave_steps = [step_map[sid] for sid in executable_ids]
            if not wave_steps:
                continue
            results = await self._execute_wave(
                run,
                wave_steps,
                session_id,
                completed_outcomes,
                gate=gate,
                step_task_map=_step_task_map,
            )

            # Collect results sequentially (cost, outcomes, events)
            for step, (execution, extracted_outputs) in zip(wave_steps, results):
                completed_outcomes[step.id] = extracted_outputs
                run.total_cost_usd += execution.total_cost_usd
                status_str = (
                    execution.status
                    if isinstance(execution.status, str)
                    else execution.status.value
                )
                _emit(
                    {
                        "type": "step_done",
                        "step_id": step.id,
                        "status": status_str,
                        "cost_usd": execution.total_cost_usd,
                        "completed_steps": len(completed_outcomes),
                        "total_steps": total_steps,
                    }
                )
                await self._publish_workflow_event(
                    run.mission_id,
                    WorkflowExecutionCompletedEvent(
                        session_id=_uuid.UUID(session_id),
                        source="workflow_run_service",
                        workflow_run_id=run.id,
                        mission_id=run.mission_id or "",
                        step_id=step.id,
                        success=(status_str != "FAILED"),
                        cost_usd=execution.total_cost_usd,
                    ),
                )

            # Kanban: per-step terminal status reflects the inner execution
            # outcome (Plan 80h fix). Previously every step was force-written
            # to COMPLETED regardless of whether handle_mission's inner agent
            # actually failed — the Kanban lied while the trace told the truth.
            if _plan_id and wave_steps:
                _cost_map = {
                    s.id: getattr(ex, "total_cost_usd", 0.0)
                    for s, (ex, _) in zip(wave_steps, results)
                }
                _step_statuses: list[tuple[str, TaskStatus]] = []
                _failure_reasons: dict[str, str] = {}
                for step, (execution, _) in zip(wave_steps, results):
                    ex_status = (
                        execution.status
                        if isinstance(execution.status, str)
                        else execution.status.value
                    ).lower()
                    # `completed` is what _execute_step writes for successful
                    # agent_step outcomes (see line ~676). It joins `success`
                    # and `partial` (handle_mission outcome status values) as
                    # an indicator of success on the Kanban. Without this the
                    # else branch mis-marks every agent_step as FAILED while
                    # the workflow engine itself correctly advances -- the
                    # Kanban lied while the trace told the truth.
                    if ex_status in ("success", "partial", "completed"):
                        ts = TaskStatus.COMPLETED
                    elif ex_status == "skipped":
                        ts = TaskStatus.SKIPPED
                    else:
                        ts = TaskStatus.FAILED
                        # Pull the most specific failure reason we can find.
                        # Order: abort_reason on the outcome, first task_result's
                        # failure path, fall back to a generic message.
                        reason = (
                            getattr(execution, "abort_reason", None)
                            or extract_first_task_failure(execution)
                            or f"Step '{step.id}' execution failed (status={ex_status})"
                        )
                        _failure_reasons[step.id] = str(reason)
                    _step_statuses.append((step.id, ts))
                await self._sync_plan_task_states(
                    _plan_id,
                    run.mission_id,
                    _step_statuses,
                    session_id,
                    cost_map=_cost_map,
                    step_task_map=_step_task_map,
                    failure_reasons=_failure_reasons or None,
                )

    async def _execute_wave(
        self,
        run: WorkflowRun,
        steps: list[WorkflowStepSchema],
        session_id: str,
        completed_outcomes: dict[str, dict],
        gate: object | None = None,
        step_task_map: dict[str, str] | None = None,
    ) -> list[tuple[Any, dict]]:
        """Execute all steps in a wave concurrently.

        Each step gets its own DB session via the factory to avoid
        SQLAlchemy async flush conflicts.

        ``step_task_map`` (Plan 80h) passes the step → task UUID map down
        to ``_execute_step`` so handle_mission can be given a precomputed
        TaskPlan that points at the workflow's task, skipping the
        Planning Agent.
        """
        if self._step_context_factory is None:
            raise RuntimeError("step_context_factory is required to execute workflows")

        _step_task_map = step_task_map or {}

        async def _run_step(step: WorkflowStepSchema) -> tuple[Any, dict]:
            async with self._step_context_factory() as ctx:
                return await self._execute_step(
                    run,
                    step,
                    session_id,
                    completed_outcomes,
                    ctx,
                    gate=gate,
                    step_task_id=_step_task_map.get(step.id),
                )

        results = await asyncio.gather(
            *[_run_step(step) for step in steps],
        )
        return list(results)

    async def _execute_step(
        self,
        run: WorkflowRun,
        step: WorkflowStepSchema,
        session_id: str,
        completed_outcomes: dict[str, dict],
        ctx: StepContext,
        gate: object | None = None,
        step_task_id: str | None = None,
    ) -> tuple[Any, dict]:
        """Execute a single workflow step, dispatching by node_type.

        Pre-execution approval (Plan 80h): the per-step pre_layer gate
        was removed in favour of the unified task lifecycle. The wave-
        level wait happens in ``_execute_steps`` before this method is
        called. By the time we get here the task is already APPROVED
        (or autonomously auto-approved).

        ``step_task_id`` is the UUID of the Task row that represents
        this step in the plan. Used to build a precomputed_plan for
        handle_mission so it skips the Planning Agent (which would
        otherwise create a competing plan and break the workflow).
        """
        node_type = getattr(step, "node_type", "agent_step")

        if node_type == "condition":
            return await control.execute_condition_step(self, run, step, completed_outcomes)
        if node_type == "notification":
            return await io.execute_notification_step(self, run, step, completed_outcomes)
        if node_type == "human_input":
            return await execute_human_input_step(self, run, step, completed_outcomes)
        if node_type == "tool_call":
            return await io.execute_tool_call_step(self, run, step, completed_outcomes)
        if node_type == "llm_call":
            return await io.execute_llm_call_step(self, run, step, completed_outcomes)
        if node_type == "branch":
            return await control.execute_branch_step(self, run, step, completed_outcomes)
        if node_type == "merge":
            return await control.execute_merge_step(self, run, step, completed_outcomes)
        if node_type == "decision":
            return await control.execute_decision_step(self, run, step, completed_outcomes)
        if node_type == "sub_workflow":
            return await sub_workflow.execute_sub_workflow_step(
                self, run, step, session_id, completed_outcomes, ctx
            )

        # Default: agent_step — dispatch via handle_mission (Plan 71)
        # Resolve upstream context from dependencies
        upstream = self._workflow_service.resolve_upstream_context(
            step,
            completed_outcomes,
            run.context,
        )

        # Build the objective from step description + input context
        step_input = upstream.get("_step_input", step.input)
        objective = build_step_objective(step, step_input)

        app_config = get_app_config()
        cost_ceiling = step.cost_ceiling_usd or app_config.workflows.default_budget_usd

        # Concurrency check
        active_count = await ctx.persistence.count_active()
        if active_count >= app_config.workflows.max_concurrent_missions:
            from modules.backend.core.exceptions import ValidationError

            raise ValidationError(
                message=(
                    f"Maximum concurrent executions "
                    f"({app_config.workflows.max_concurrent_missions}) "
                    f"reached. {active_count} currently active."
                ),
            )

        # 1. Create early ExecutionRecord (RUNNING)
        record = await ctx.persistence.save_execution(
            session_id=session_id,
            status="running",
            roster_name=step.roster,
            objective_statement=objective,
            mission_id=run.mission_id,
            started_at=None,
            completed_at=None,
            workflow_run_id=run.id,
            workflow_step_id=step.id,
            execution_environment=step.environment,
            cost_ceiling_usd=cost_ceiling,
        )

        logger.info(
            "Step execution record created",
            extra={
                "run_id": run.id,
                "step_id": step.id,
                "execution_record_id": record.id,
                "agent": f"{step.capability}.agent",
            },
        )

        # 2. Dispatch via handle_mission directly (no dispatch adapter)
        from modules.backend.core.config import get_default_budget_usd
        from modules.backend.services.session import SessionService

        resolved_mode, roster_name = await resolve_dispatch_params(
            ctx.db,
            run.mission_id,
            step,
        )

        session_svc = SessionService(ctx.db)
        if self._event_bus is None:
            raise RuntimeError(
                "WorkflowRunService.event_bus is required to dispatch an "
                "agent_step (handle_mission needs a real SessionEventBus) — "
                "construct the service with event_bus=... rather than "
                "relying on a default."
            )
        event_bus = self._event_bus
        budget = cost_ceiling or get_default_budget_usd()

        # Build a 1-task precomputed_plan pointing at the workflow's task
        # (Plan 80h). Without this, handle_mission runs its Planning Agent
        # and produces a competing plan whose task IDs don't match the
        # workflow's, breaking the unified task-lifecycle approval.
        from modules.backend.schemas.task_plan import TaskDefinition, TaskInputs, TaskPlan

        # Agent name in roster is `<capability>.agent` (see ExecutionRecord
        # logging above and the elsewhere-used convention). Workflow YAML
        # exposes only the capability prefix.
        precomputed_plan_agent = (
            f"{step.capability}.agent" if step.capability else f"workflow:{step.node_type}"
        )
        precomputed_plan: TaskPlan | None = None
        if step_task_id:
            precomputed_plan = TaskPlan(
                version="1.0.0",
                mission_id=run.mission_id,
                summary=step.description or step.label or step.id,
                estimated_cost_usd=cost_ceiling or 0.0,
                estimated_duration_seconds=step.timeout_seconds or 0,
                tasks=[
                    TaskDefinition(
                        task_id=step_task_id,
                        agent=precomputed_plan_agent,
                        description=step.description or step.label or step.id,
                        instructions=objective,
                        dependencies=[],
                        inputs=TaskInputs(static=step.input or {}),
                    ),
                ],
            )

        try:
            from modules.backend.agents.mission_control.mission_dispatch import handle_mission

            outcome = await handle_mission(
                mission_run_id=f"mission-{session_id}",
                mission_brief=objective,
                session_service=session_svc,
                event_bus=event_bus,
                roster_name=roster_name,
                mission_budget_usd=budget,
                upstream_context=upstream,
                session_id=session_id,
                mission_id=run.mission_id,
                db_session=ctx.db,
                gate=gate,
                execution_mode=resolved_mode,
                precomputed_plan=precomputed_plan,
                container_image=step.container_image,
                extra_volumes=step.extra_volumes,
                execution_record_id=record.id,
            )

            outcome_dict = outcome.model_dump()
            success = outcome.status in ("success", "partial")
            status_str = "completed" if success else "failed"
            total_cost = outcome.total_cost_usd
        except Exception as e:
            # Catch-all justified: wraps handle_mission(), a full agent
            # dispatch (LLM calls, tool calls, DB writes) whose exception
            # surface is unbounded — logged and emitted here for Console
            # visibility, then re-raised as RuntimeError below.
            import traceback

            tb_str = traceback.format_exception(e)
            logger.error(
                "Step execution failed",
                extra={
                    "mission_id": run.mission_id,
                    "run_id": run.id,
                    "step_id": step.id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "traceback": "".join(tb_str)[-500:],
                },
            )
            await self._publish_workflow_event(
                run.mission_id,
                SystemEvent(
                    session_id=_uuid.UUID(session_id) if session_id else _uuid.uuid4(),
                    source="workflow_run_waves",
                    level="error",
                    message=f"Step '{step.id}' execution failed: {type(e).__name__}: {e}"[:500],
                    mission_id=run.mission_id,
                ),
            )
            raise RuntimeError(f"Step '{step.id}' execution failed: {type(e).__name__}: {e}") from e

        # 3. Extract outputs from the outcome.
        # Plan 79 §8.3 — default-populate completed_outcomes[step.id] with the
        # agent's structured output (matched by agent_name) so downstream
        # @node.X.output.field refs resolve. Explicit output_mapping continues
        # to take precedence and merges on top.
        expected_agent = f"{step.capability}.agent" if step.capability else None
        extracted = extract_default_agent_output(
            outcome_dict,
            expected_agent=expected_agent,
            mission_id=run.mission_id,
        )
        output_mapping = step.output_mapping.model_dump() if step.output_mapping else None
        if output_mapping:
            try:
                extracted.update(
                    ctx.persistence.extract_outputs(
                        outcome_dict,
                        output_mapping,
                    ),
                )
            except WorkflowOutputMappingError as e:
                # Output-mapping contract failure — surface as a step
                # failure with the full schema delta in the message.
                # The agent's run succeeded; we're refusing to silently
                # degrade the downstream context by accepting a partial
                # output. Any other exception types are bugs we
                # shouldn't mask — let them propagate.
                logger.error(
                    "Step output mapping failed",
                    extra={
                        "mission_id": run.mission_id,
                        "run_id": run.id,
                        "step_id": step.id,
                        "error": str(e),
                        "details": e.details,
                    },
                )
                await self._publish_workflow_event(
                    run.mission_id,
                    SystemEvent(
                        session_id=_uuid.UUID(session_id) if session_id else _uuid.uuid4(),
                        source="workflow_run_waves",
                        level="error",
                        message=f"Step '{step.id}' output mapping failed: {e}"[:500],
                        mission_id=run.mission_id,
                    ),
                )
                raise RuntimeError(f"Step '{step.id}' output mapping failed: {e}") from e

        logger.info(
            "Step completed",
            extra={
                "run_id": run.id,
                "step_id": step.id,
                "execution_record_id": record.id,
                "status": status_str,
                "cost": total_cost,
            },
        )

        if not success:
            # Surface the real underlying failure (e.g. "Copilot quota
            # exhausted (402): ...") that the retry handler captured.
            # Without this, every step failure presents as a generic
            # "Step 'X' execution failed", hiding root-cause signals
            # from logs, SSE events, and the run-detail UI.
            reason = getattr(outcome, "abort_reason", None) or extract_first_task_failure(outcome)
            detail = f": {reason}" if reason else ""
            raise RuntimeError(f"Step '{step.id}' execution failed{detail}")

        result = VirtualExecution(
            id=record.id,
            status=status_str,
            total_cost_usd=total_cost,
        )
        return result, extracted
