"""
Workflow Run Waves Mixin — extracted from workflow_run.py.

Contains the wave-execution engine: topological sorting of steps into
parallel waves, concurrent step dispatch within a wave, single-step
execution, and objective building. Separated because wave orchestration
is a distinct concern from run lifecycle management, definition
resolution, and notification.

Mixed into WorkflowRunService — do not instantiate directly.
"""

from __future__ import annotations

import asyncio
import uuid as _uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import SQLAlchemyError

from modules.backend.core.config import get_app_config
from modules.backend.core.exceptions import WorkflowOutputMappingError
from modules.backend.core.logging import get_logger
from modules.backend.events.types import (
    SystemEvent,
    WorkflowBranchPassedEvent,
    WorkflowConditionEvaluatedEvent,
    WorkflowExecutionCompletedEvent,
    WorkflowExecutionStartedEvent,
    WorkflowHumanInputRequestedEvent,
    WorkflowHumanInputRespondedEvent,
    WorkflowLlmCallCompletedEvent,
    WorkflowMergeCompletedEvent,
    WorkflowNotificationSentEvent,
    WorkflowRunStartedEvent,
    WorkflowStepSkippedEvent,
    WorkflowSubWorkflowCompletedEvent,
    WorkflowToolCallCompletedEvent,
)
from modules.backend.models.task import TaskStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from modules.backend.models.workflow_run import WorkflowRun
    from modules.backend.schemas.workflow import WorkflowSchema, WorkflowStepSchema
    from modules.backend.services.execution_persistence import ExecutionPersistenceService

logger = get_logger(__name__)


def _extract_run_cost(result: Any, model_name: str | None = None) -> float:
    """Extract cost from a PydanticAI run result using the project's cost calculator."""
    try:
        from modules.backend.agents.mission_control.cost import compute_cost_usd
        from modules.backend.core.model_builder import _resolve_model_alias

        resolved = _resolve_model_alias(model_name) if model_name else None
        usage = result.usage()
        return compute_cost_usd(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            model=resolved,
            cache_read_tokens=getattr(usage, "cache_read_tokens", 0),
            cache_write_5m_tokens=getattr(usage, "cache_write_tokens", 0),
        )
    except (AttributeError, TypeError):
        # Narrowed deliberately: result.usage() shape mismatches only.
        # compute_cost_usd's own pricing errors (e.g. unknown model) must
        # NOT be swallowed here — silently returning 0.0 for those would
        # defeat budget enforcement (see Phase 4.6).
        logger.debug("Cost extraction failed", extra={"model": model_name}, exc_info=True)
        return 0.0


def _extract_default_agent_output(
    outcome_dict: dict | None,
    *,
    expected_agent: str | None = None,
    mission_id: str | None = None,
) -> dict[str, Any]:
    """Default-populate completed_outcomes for an agent_step (Plan 79 §8.3).

    Without this, agent_step nodes whose workflow YAML does not declare
    output_mapping land in completed_outcomes as `{}` (because
    ExecutionPersistence.extract_outputs short-circuits on no mapping).
    Downstream @node.X.output.field refs then silently resolve to None.

    Strategy:
    1. If `expected_agent` is given, find the TaskResult whose agent_name
       matches. This is the deterministic case for single-capability
       agent_step dispatch (the Plan 79 deliberation workflow case).
    2. Otherwise fall back to the last task_result (legacy multi-task
       behaviour). Log a warning when the fallback fires.

    The result is wrapped under "output" key so @node.X.output.field
    references auto-unwrap (matching the convention used by tool_call
    and llm_call dispatchers).
    """
    if not outcome_dict:
        return {}
    task_results = outcome_dict.get("task_results", []) or []
    if not task_results:
        return {}

    if expected_agent:
        for tr in task_results:
            if isinstance(tr, dict) and tr.get("agent_name") == expected_agent:
                return {"output": tr.get("output_reference", {})}
        logger.warning(
            "Agent name match failed for default-output extraction; "
            "falling back to last task_result",
            extra={
                "mission_id": mission_id,
                "expected_agent": expected_agent,
                "available_agent_names": [
                    tr.get("agent_name") for tr in task_results if isinstance(tr, dict)
                ],
            },
        )

    last = task_results[-1]
    output_ref = last.get("output_reference", {}) if isinstance(last, dict) else {}
    return {"output": output_ref}


@dataclass
class VirtualExecution:
    """Stand-in for condition/notification nodes that don't create DB Execution records."""

    id: str
    status: str = "COMPLETED"
    total_cost_usd: float = 0.0
    error_data: dict = field(default_factory=dict)


@dataclass
class StepContext:
    """Per-step execution context with its own DB session (Plan 71)."""

    db: AsyncSession
    persistence: ExecutionPersistenceService

    @staticmethod
    @asynccontextmanager
    async def factory():
        """Create a StepContext with its own DB session."""
        from modules.backend.core.database import get_async_session
        from modules.backend.services.execution_persistence import ExecutionPersistenceService

        async with get_async_session() as step_db:
            yield StepContext(
                db=step_db,
                persistence=ExecutionPersistenceService(step_db),
            )
            await step_db.commit()


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
            from modules.backend.events.types import MissionPlanTaskStatusChangedEvent
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
        waves = self._compute_waves(workflow.steps)
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
                if self._should_skip(
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
                waiters = [
                    wait_until_approved(
                        task_id=_step_task_map[sid],
                        session_factory=factory,
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
                            or self._extract_first_task_failure(execution)
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
            return await self._execute_condition_step(run, step, completed_outcomes)
        if node_type == "notification":
            return await self._execute_notification_step(run, step, completed_outcomes)
        if node_type == "human_input":
            return await self._execute_human_input_step(run, step, completed_outcomes)
        if node_type == "tool_call":
            return await self._execute_tool_call_step(run, step, completed_outcomes)
        if node_type == "llm_call":
            return await self._execute_llm_call_step(run, step, completed_outcomes)
        if node_type == "branch":
            return await self._execute_branch_step(run, step, completed_outcomes)
        if node_type == "merge":
            return await self._execute_merge_step(run, step, completed_outcomes)
        if node_type == "decision":
            return await self._execute_decision_step(run, step, completed_outcomes)
        if node_type == "sub_workflow":
            return await self._execute_sub_workflow_step(
                run, step, session_id, completed_outcomes, ctx
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
        objective = self._build_step_objective(step, step_input)

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
        from modules.backend.agents.mission_control.models import NoOpEventBus
        from modules.backend.core.config import get_default_budget_usd
        from modules.backend.services.session import SessionService

        resolved_mode, roster_name = await self._resolve_dispatch_params(
            ctx.db,
            run.mission_id,
            step,
        )

        session_svc = SessionService(ctx.db)
        event_bus = self._event_bus or NoOpEventBus()
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
        extracted = _extract_default_agent_output(
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
            reason = getattr(outcome, "abort_reason", None) or self._extract_first_task_failure(
                outcome
            )
            detail = f": {reason}" if reason else ""
            raise RuntimeError(f"Step '{step.id}' execution failed{detail}")

        result = VirtualExecution(
            id=record.id,
            status=status_str,
            total_cost_usd=total_cost,
        )
        return result, extracted

    async def _execute_condition_step(
        self,
        run: WorkflowRun,
        step: WorkflowStepSchema,
        completed_outcomes: dict[str, dict],
    ) -> tuple[VirtualExecution, dict]:
        """Evaluate a condition expression and return branch result."""
        from modules.backend.services.condition_evaluator import (
            ConditionEvaluationError,
            evaluate_condition,
        )

        config = step.condition_config
        expression = config.expression if config else ""

        try:
            result = evaluate_condition(expression, completed_outcomes, run.context)
        except ConditionEvaluationError as e:
            logger.error(
                "Condition evaluation failed",
                extra={
                    "mission_id": run.mission_id,
                    "step_id": step.id,
                    "error": str(e),
                },
            )
            await self._publish_workflow_event(
                run.mission_id,
                SystemEvent(
                    session_id=_uuid.UUID(run.session_id) if run.session_id else _uuid.uuid4(),
                    source="workflow_run_waves",
                    level="error",
                    message=f"Condition '{step.id}' failed: {e}"[:500],
                    mission_id=run.mission_id,
                ),
            )
            raise RuntimeError(f"Condition '{step.id}' failed: {e}") from e

        branch = (
            (config.true_label if result else config.false_label)
            if config
            else ("Yes" if result else "No")
        )

        logger.info(
            "Condition evaluated",
            extra={
                "step_id": step.id,
                "expression": expression,
                "result": result,
                "branch": branch,
            },
        )

        outputs = {"result": result, "branch": branch, "_branch": branch}
        await self._publish_workflow_event(
            run.mission_id,
            WorkflowConditionEvaluatedEvent(
                session_id=_uuid.UUID(str(run.session_id)),
                source="workflow_run_service",
                workflow_run_id=run.id,
                step_id=step.id,
                expression=expression,
                result=result,
                branch=branch,
            ),
        )
        return VirtualExecution(id=step.id), outputs

    async def _execute_decision_step(
        self,
        run: WorkflowRun,
        step: WorkflowStepSchema,
        completed_outcomes: dict[str, dict],
    ) -> tuple[VirtualExecution, dict]:
        """Resolve a decision and return the chosen option as _branch.

        Follows the same signature pattern as _execute_condition_step
        (lightweight routing — no session_id needed, extracted from run).
        """
        from modules.backend.events.types import WorkflowDecisionResolvedEvent

        config = step.decision_config
        if not config:
            raise RuntimeError(f"decision_config missing for step '{step.id}'")

        valid_keys = {o.key for o in config.options}
        self._last_decision_cost = 0.0

        if config.resolver == "agent":
            chosen = await self._resolve_agent_decision(
                step,
                completed_outcomes,
                run.context or {},
            )
        elif config.resolver == "human":
            chosen = await self._resolve_human_decision(
                run,
                step,
                completed_outcomes,
            )
        elif config.resolver == "rule":
            chosen = await self._resolve_rule_decision(
                step,
                completed_outcomes,
                run.context or {},
            )
        else:
            raise RuntimeError(f"Unknown resolver '{config.resolver}' in step '{step.id}'")

        if chosen not in valid_keys:
            raise RuntimeError(
                f"Decision '{step.id}' resolver returned '{chosen}' "
                f"which is not in options: {sorted(valid_keys)}"
            )

        logger.info(
            "Decision resolved",
            extra={
                "step_id": step.id,
                "run_id": run.id,
                "resolver": config.resolver,
                "chosen": chosen,
            },
        )

        await self._publish_workflow_event(
            run.mission_id,
            WorkflowDecisionResolvedEvent(
                session_id=_uuid.UUID(str(run.session_id)),
                source="workflow_run_service",
                workflow_run_id=run.id,
                step_id=step.id,
                resolver=config.resolver,
                chosen_option=chosen,
                options=[o.key for o in config.options],
            ),
        )

        outputs = {"chosen": chosen, "_branch": chosen}
        return VirtualExecution(id=step.id, total_cost_usd=self._last_decision_cost), outputs

    async def _resolve_agent_decision(
        self,
        step: WorkflowStepSchema,
        completed_outcomes: dict[str, dict],
        workflow_context: dict,
    ) -> str:
        """LLM picks an option key."""
        config = step.decision_config

        if not config.model:
            raise RuntimeError(
                f"Decision '{step.id}' agent resolver requires a model. "
                f"Set decision_config.model in the workflow step definition."
            )
        model_name = config.model

        from modules.backend.services.condition_evaluator import resolve_template

        prompt = resolve_template(config.prompt, completed_outcomes, workflow_context)
        options_desc = "\n".join(f"- {o.key}: {o.label}" for o in config.options)

        full_prompt = (
            f"{prompt}\n\n"
            f"Available options:\n{options_desc}\n\n"
            f"Respond with ONLY the option key. No explanation."
        )

        from pydantic_ai import Agent as PydanticAgent

        from modules.backend.core.model_builder import _build_model

        model = _build_model(model_name)
        agent = PydanticAgent(
            model,
            output_type=str,
            instructions="You are a routing decision agent. Return only the option key.",
        )
        result = await agent.run(full_prompt)

        # Track cost on the parent decision step's VirtualExecution
        self._last_decision_cost = _extract_run_cost(result, model_name)

        import re

        chosen = re.sub(r"[^a-z0-9_]", "", result.output.strip().lower())
        return chosen

    async def _resolve_human_decision(
        self,
        run: WorkflowRun,
        step: WorkflowStepSchema,
        completed_outcomes: dict[str, dict],
    ) -> str:
        """Present options to human and wait for selection.

        Reuses _execute_human_input_step by constructing a temporary
        human_input-shaped step. Template resolution of prompt_message
        happens inside _execute_human_input_step — do NOT resolve here
        or the template gets resolved twice.
        """
        config = step.decision_config
        choices = [o.key for o in config.options]

        from modules.backend.schemas.workflow import HumanInputConfig
        from modules.backend.schemas.workflow import WorkflowStepSchema as StepSchema

        hi_config = HumanInputConfig(
            prompt_message=config.prompt_message,
            channel=config.channel or "chat",
            timeout_hours=config.timeout_hours,
            default_response=config.default_option,
            choices=choices,
        )

        temp_step = StepSchema(
            id=step.id,
            node_type="human_input",
            human_input_config=hi_config,
            depends_on=step.depends_on,
        )

        _, outputs = await self._execute_human_input_step(
            run,
            temp_step,
            completed_outcomes,
        )

        response = outputs.get("response", "")
        if response in {o.key for o in config.options}:
            return response
        if outputs.get("timed_out") and config.default_option:
            return config.default_option

        raise RuntimeError(
            f"Decision '{step.id}' human response '{response}' " f"does not match any option key"
        )

    async def _resolve_rule_decision(
        self,
        step: WorkflowStepSchema,
        completed_outcomes: dict[str, dict],
        workflow_context: dict,
    ) -> str:
        """Evaluate expression to get option key."""
        config = step.decision_config

        from modules.backend.services.condition_evaluator import (
            ConditionEvaluationError,
            evaluate_expression,
        )

        try:
            return evaluate_expression(
                config.expression,
                completed_outcomes,
                workflow_context,
            )
        except ConditionEvaluationError as e:
            raise RuntimeError(f"Decision '{step.id}' rule evaluation failed: {e}") from e

    async def _execute_notification_step(
        self,
        run: WorkflowRun,
        step: WorkflowStepSchema,
        completed_outcomes: dict[str, dict],
    ) -> tuple[VirtualExecution, dict]:
        """Send a notification via the configured channel."""
        from modules.backend.services.condition_evaluator import resolve_template
        from modules.backend.services.run_notifier import _dispatch_to_channels

        config = step.notification_config
        channel = config.channel if config else "sse"
        template = config.message_template if config else ""

        message = resolve_template(template, completed_outcomes, run.context)
        title = f"Workflow notification: {step.id}"

        try:
            await _dispatch_to_channels(
                [channel],
                title,
                message,
                "info",
                {"mission_id": run.mission_id, "run_id": run.id},
            )
            success = True
        except Exception:
            # Catch-all justified: wraps an external notification dispatch
            # whose failure modes are unbounded (network, auth, service
            # down). best-effort — the step continues with success=False,
            # which is reported via the unconditional
            # WorkflowNotificationSentEvent below.
            logger.warning("Notification step failed", extra={"step_id": step.id}, exc_info=True)
            success = False

        logger.info(
            "Notification sent", extra={"step_id": step.id, "channel": channel, "success": success}
        )
        await self._publish_workflow_event(
            run.mission_id,
            WorkflowNotificationSentEvent(
                session_id=_uuid.UUID(str(run.session_id)),
                source="workflow_run_service",
                workflow_run_id=run.id,
                step_id=step.id,
                channel=channel,
                success=success,
            ),
        )
        outputs = {"sent": success, "channel": channel}
        return VirtualExecution(id=step.id), outputs

    async def _execute_tool_call_step(
        self,
        run: WorkflowRun,
        step: WorkflowStepSchema,
        completed_outcomes: dict[str, dict],
    ) -> tuple[VirtualExecution, dict]:
        """Invoke a registered tool directly without an agent wrapper."""
        from modules.backend.services.condition_evaluator import resolve_template, walk_refs
        from modules.backend.tools.registry import get_tool_registry

        config = step.tool_call_config
        tool_name = config.tool_name if config else ""
        tool_args = dict(config.tool_args) if config else {}

        registry = get_tool_registry()
        if not registry.has(tool_name):
            raise RuntimeError(f"Tool '{tool_name}' not found in registry (step '{step.id}')")

        tool_info = registry.get(tool_name)
        tool_mod = tool_info["module"]
        impl = getattr(tool_mod, "_impl", None)
        if impl is None:
            raise RuntimeError(f"Tool '{tool_name}' has no _impl function (step '{step.id}')")

        # Plan 79 §8.4 — deep-resolve refs in tool_args. Walks nested dicts
        # and lists so structured args (e.g. compute_stance_delta's
        # previous_round: {systems: "{{@node.X.output}}", ...}) get their
        # inner refs resolved. Standalone refs preserve Python type per §8.6.
        resolved_args = walk_refs(
            tool_args,
            completed_outcomes,
            run.context,
            leaf_resolver=lambda s: resolve_template(
                s,
                completed_outcomes,
                run.context,
            ),
        )

        # Provision tool dependencies
        deps = tool_info.get("deps", [])
        _HANDLED_DEPS = {"http_client", "mission_id"}
        if "mission_id" in deps:
            resolved_args["mission_id"] = str(run.mission_id)

        try:
            import httpx

            if "http_client" in deps:
                async with httpx.AsyncClient(timeout=60) as client:
                    resolved_args["http_client"] = client
                    result = await impl(**resolved_args)
            else:
                unsupported = [d for d in deps if d not in _HANDLED_DEPS]
                if unsupported:
                    raise RuntimeError(
                        f"Tool '{tool_name}' requires unsupported deps: "
                        f"{unsupported} (step '{step.id}')"
                    )
                result = await impl(**resolved_args)
            success = True
        except RuntimeError:
            raise
        except Exception as e:
            # Catch-all justified: `impl` is an arbitrary tool function
            # whose exception surface is unbounded. best-effort — the step
            # continues with success=False, which is reported via the
            # unconditional WorkflowToolCallCompletedEvent below.
            logger.warning(
                "Tool call step failed",
                extra={"step_id": step.id, "tool": tool_name},
                exc_info=True,
            )
            result = {"error": str(e)}
            success = False

        logger.info(
            "Tool call completed", extra={"step_id": step.id, "tool": tool_name, "success": success}
        )
        await self._publish_workflow_event(
            run.mission_id,
            WorkflowToolCallCompletedEvent(
                session_id=_uuid.UUID(str(run.session_id)),
                source="workflow_run_service",
                workflow_run_id=run.id,
                step_id=step.id,
                tool_name=tool_name,
                success=success,
            ),
        )
        outputs = {"output": result, "tool_name": tool_name}
        return VirtualExecution(id=step.id), outputs

    async def _execute_llm_call_step(
        self,
        run: WorkflowRun,
        step: WorkflowStepSchema,
        completed_outcomes: dict[str, dict],
    ) -> tuple[VirtualExecution, dict]:
        """Make a raw LLM call with template substitution — no agent framework."""
        from modules.backend.services.condition_evaluator import resolve_template

        config = step.llm_call_config
        if not config:
            raise RuntimeError(f"llm_call_config missing for step '{step.id}'")

        # Resolve templates
        prompt = resolve_template(config.prompt_template, completed_outcomes, run.context)
        system = (
            resolve_template(config.system_prompt, completed_outcomes, run.context)
            if config.system_prompt
            else None
        )

        try:
            from pydantic_ai import Agent as PydanticAgent

            from modules.backend.core.model_builder import _build_model

            model = _build_model(config.model)
            agent = PydanticAgent(model, output_type=str, instructions=system or "")
            result = await agent.run(prompt)
            text = result.output
            cost = _extract_run_cost(result, config.model)
            success = True
        except Exception as e:
            # Catch-all justified: wraps a raw LLM call whose exception
            # surface is unbounded (network, auth, quota, provider bugs).
            # best-effort — the step continues with success=False, which
            # is reported via the unconditional
            # WorkflowLlmCallCompletedEvent below.
            logger.warning(
                "LLM call step failed",
                extra={
                    "mission_id": run.mission_id,
                    "step_id": step.id,
                    "model": config.model,
                },
                exc_info=True,
            )
            text = f"Error: {e}"
            cost = 0.0
            success = False

        logger.info(
            "LLM call completed",
            extra={"step_id": step.id, "model": config.model, "success": success, "cost": cost},
        )
        await self._publish_workflow_event(
            run.mission_id,
            WorkflowLlmCallCompletedEvent(
                session_id=_uuid.UUID(str(run.session_id)),
                source="workflow_run_service",
                workflow_run_id=run.id,
                step_id=step.id,
                model=config.model,
                success=success,
            ),
        )
        outputs = {"output": text, "model": config.model}
        return VirtualExecution(id=step.id, total_cost_usd=cost), outputs

    async def _execute_branch_step(
        self,
        run: WorkflowRun,
        step: WorkflowStepSchema,
        completed_outcomes: dict[str, dict],
    ) -> tuple[VirtualExecution, dict]:
        """Pass-through fork node. Downstream steps run in parallel via wave scheduling."""
        # Forward all upstream outputs so downstream forks can reference them
        upstream_data: dict[str, Any] = {}
        for dep_id in step.depends_on:
            dep_out = completed_outcomes.get(dep_id, {})
            upstream_data[dep_id] = dep_out

        # Count outgoing edges (fork_count) — not available here, use 0 as placeholder
        logger.info("Branch passed", extra={"step_id": step.id, "run_id": run.id})
        await self._publish_workflow_event(
            run.mission_id,
            WorkflowBranchPassedEvent(
                session_id=_uuid.UUID(str(run.session_id)),
                source="workflow_run_service",
                workflow_run_id=run.id,
                step_id=step.id,
                fork_count=0,
            ),
        )
        outputs = {"_passthrough": True, **upstream_data}
        return VirtualExecution(id=step.id), outputs

    async def _execute_merge_step(
        self,
        run: WorkflowRun,
        step: WorkflowStepSchema,
        completed_outcomes: dict[str, dict],
    ) -> tuple[VirtualExecution, dict]:
        """Sync barrier — collects outputs from all incoming paths.

        Flat-merges all output-mapped keys from non-skipped dependencies into
        a single dict. This allows downstream steps to receive all upstream
        data naturally via resolve_upstream_context, regardless of which
        branches actually ran.
        """
        flat: dict[str, Any] = {}
        merged_by_dep: dict[str, dict] = {}
        for dep_id in step.depends_on:
            dep_out = completed_outcomes.get(dep_id, {})
            if not dep_out.get("_skipped"):
                merged_by_dep[dep_id] = dep_out
                # Flat-merge: output-mapped keys from each dep become top-level
                for k, v in dep_out.items():
                    if not k.startswith("_"):
                        flat[k] = v

        strategy = "wait_all"
        if step.merge_config:
            strategy = step.merge_config.strategy

        logger.info(
            "Merge completed",
            extra={
                "step_id": step.id,
                "run_id": run.id,
                "strategy": strategy,
                "inputs": len(merged_by_dep),
            },
        )
        await self._publish_workflow_event(
            run.mission_id,
            WorkflowMergeCompletedEvent(
                session_id=_uuid.UUID(str(run.session_id)),
                source="workflow_run_service",
                workflow_run_id=run.id,
                step_id=step.id,
                strategy=strategy,
                inputs_merged=len(merged_by_dep),
            ),
        )
        outputs = {
            **flat,
            "_merged_deps": list(merged_by_dep.keys()),
            "_input_count": len(merged_by_dep),
        }
        return VirtualExecution(id=step.id), outputs

    async def _execute_sub_workflow_step(
        self,
        run: WorkflowRun,
        step: WorkflowStepSchema,
        session_id: str,
        completed_outcomes: dict[str, dict],
        ctx: StepContext,
    ) -> tuple[VirtualExecution, dict]:
        """Invoke another saved workflow as a child and await its completion."""
        config = step.sub_workflow_config
        if not config:
            raise RuntimeError(f"sub_workflow_config missing for step '{step.id}'")

        # Depth guard — prevent unbounded recursion
        parent_depth = (run.context or {}).get("_sub_workflow_depth", 0)
        if parent_depth >= config.max_depth:
            raise RuntimeError(
                f"Sub-workflow depth limit reached ({config.max_depth}) at step '{step.id}'"
            )

        # Build child context
        child_context: dict[str, Any] = {"_sub_workflow_depth": parent_depth + 1}
        if config.pass_context:
            child_context.update(run.context or {})
            child_context["_sub_workflow_depth"] = parent_depth + 1

        logger.info(
            "Starting sub-workflow",
            extra={
                "step_id": step.id,
                "run_id": run.id,
                "child_workflow_id": config.workflow_id,
                "depth": parent_depth + 1,
            },
        )

        child_run = await self.run_workflow_from_definition(
            workflow_definition_id=config.workflow_id,
            mission_id=run.mission_id,
            triggered_by=f"sub_workflow:{step.id}",
            context_overrides=child_context,
        )

        child_status = (
            child_run.status if isinstance(child_run.status, str) else child_run.status.value
        )
        success = child_status.upper() != "FAILED"

        await self._publish_workflow_event(
            run.mission_id,
            WorkflowSubWorkflowCompletedEvent(
                session_id=_uuid.UUID(session_id),
                source="workflow_run_service",
                workflow_run_id=run.id,
                step_id=step.id,
                child_run_id=child_run.id,
                success=success,
                child_cost_usd=child_run.total_cost_usd,
            ),
        )

        outputs = {
            "child_run_id": child_run.id,
            "status": child_status,
            "result_summary": child_run.result_summary or "",
            "total_cost_usd": child_run.total_cost_usd,
        }

        if not success:
            raise RuntimeError(
                f"Sub-workflow step '{step.id}' child run failed: {child_run.error_data}"
            )

        return VirtualExecution(id=step.id, total_cost_usd=child_run.total_cost_usd), outputs

    async def _execute_human_input_step(
        self,
        run: WorkflowRun,
        step: WorkflowStepSchema,
        completed_outcomes: dict[str, dict],
    ) -> tuple[VirtualExecution, dict]:
        """Start a HumanInputWorkflow in Temporal and await its result."""
        from uuid import uuid4

        from modules.backend.services.condition_evaluator import resolve_template
        from modules.backend.temporal.client import get_temporal_client
        from modules.backend.temporal.human_input_models import (
            HumanInputResult,
            HumanInputWorkflowInput,
        )
        from modules.backend.temporal.human_input_workflow import HumanInputWorkflow

        config = step.human_input_config
        prompt_template = config.prompt_message if config else ""
        prompt = resolve_template(prompt_template, completed_outcomes, run.context)

        # Resolve timeout: step config > default 4h
        if config and config.timeout_hours:
            timeout_seconds = int(config.timeout_hours * 3600)
        else:
            app_config = get_app_config()
            timeout_seconds = getattr(app_config.temporal, "approval_timeout_seconds", 14400)

        request_id = str(uuid4())
        temporal_wf_id = f"human-input-{run.id}-{step.id}"

        wf_input = HumanInputWorkflowInput(
            request_id=request_id,
            workflow_run_id=run.id,
            step_id=step.id,
            mission_id=run.mission_id or "",
            session_id=run.session_id or "",
            prompt_message=prompt,
            channel=config.channel if config else "telegram",
            timeout_seconds=timeout_seconds,
            default_response=config.default_response if config else None,
            choices=config.choices or [] if config else [],
        )

        client = await get_temporal_client()

        # Start workflow with deterministic ID (idempotent across retries)
        from temporalio.service import RPCError

        try:
            handle = await client.start_workflow(
                HumanInputWorkflow.run,
                wf_input,
                id=temporal_wf_id,
                task_queue=get_app_config().temporal.task_queue,
            )
        except RPCError:
            # Already started (crash recovery) — reconnect
            handle = client.get_workflow_handle(temporal_wf_id)

        logger.info(
            "HumanInputWorkflow started, awaiting response",
            extra={
                "step_id": step.id,
                "temporal_wf_id": temporal_wf_id,
                "timeout_s": timeout_seconds,
            },
        )

        # Notify frontend that we're waiting for human input
        from datetime import timedelta

        from modules.backend.core.utils import utc_now

        timeout_at = (utc_now() + timedelta(seconds=timeout_seconds)).isoformat()
        await self._publish_workflow_event(
            run.mission_id,
            WorkflowHumanInputRequestedEvent(
                session_id=_uuid.UUID(str(run.session_id)),
                source="workflow_run_service",
                workflow_run_id=run.id,
                step_id=step.id,
                request_id=request_id,
                prompt_message=prompt,
                channel=wf_input.channel,
                choices=wf_input.choices,
                timeout_at=timeout_at,
            ),
        )

        # Block until human responds or timeout
        result: HumanInputResult = await handle.result()

        if result.timed_out and not (config and config.default_response):
            raise RuntimeError(f"Human input step '{step.id}' timed out with no default response")

        logger.info(
            "Human input received",
            extra={
                "step_id": step.id,
                "timed_out": result.timed_out,
                "response_len": len(result.response),
            },
        )

        # Notify frontend that human has responded
        await self._publish_workflow_event(
            run.mission_id,
            WorkflowHumanInputRespondedEvent(
                session_id=_uuid.UUID(str(run.session_id)),
                source="workflow_run_service",
                workflow_run_id=run.id,
                step_id=step.id,
                request_id=request_id,
                response=result.response,
                responder_id=result.responder_id or "",
                timed_out=result.timed_out,
            ),
        )

        outputs = {
            "response": result.response,
            "timed_out": result.timed_out,
            "responder_id": result.responder_id,
        }
        return VirtualExecution(id=step.id), outputs

    @staticmethod
    async def _resolve_dispatch_params(
        db_session: AsyncSession,
        mission_id: str | None,
        step: WorkflowStepSchema,
    ) -> tuple[str, str]:
        """Resolve execution mode and roster name for a workflow step.

        Returns (execution_mode, roster_name).
        """
        import os

        from modules.backend.agents.mission_control.dispatch.environment import (
            resolve_execution_mode,
        )
        from modules.backend.core.config import find_project_root

        mission_environment = None
        mission_repo_root = None
        if mission_id:
            try:
                from modules.backend.repositories.mission import MissionRepository

                repo = MissionRepository(db_session)
                mission_obj = await repo.get_by_id_or_none(mission_id)
                if mission_obj:
                    mission_environment = mission_obj.execution_environment
                    mission_repo_root = mission_obj.repo_root
            except SQLAlchemyError:
                logger.debug("Could not load mission for env resolution", exc_info=True)

        resolved_mode = step.environment or resolve_execution_mode(
            mission_environment=mission_environment,
            mission_repo_root=mission_repo_root,
        )

        roster_name = step.roster
        if step.complexity_tier and step.complexity_tier != "simple":
            tier_roster = (
                find_project_root()
                / "config"
                / "mission_control"
                / "rosters"
                / f"{step.roster}-{step.complexity_tier}.yaml"
            )
            if os.path.exists(tier_roster):
                roster_name = f"{step.roster}-{step.complexity_tier}"

        return resolved_mode, roster_name

    @staticmethod
    def _extract_first_task_failure(execution: Any) -> str | None:
        """Pull a human-meaningful failure reason from an ExecutionOutcome.

        Looks at the first task_results entry's output_reference,
        retry_history, and verification_outcome for any error /
        failure_reason / abort_reason hint. Returns None when we can't
        find a specific reason — caller should fall back to a generic
        message.
        """
        task_results = getattr(execution, "task_results", None) or []
        if not task_results:
            return None
        first = task_results[0]
        output = getattr(first, "output_reference", None) or {}
        if isinstance(output, dict):
            for key in ("error", "failure_reason", "abort_reason"):
                value = output.get(key)
                if value:
                    return str(value)
        retry_history = getattr(first, "retry_history", None) or []
        if retry_history:
            last = retry_history[-1]
            reason = getattr(last, "failure_reason", None)
            if reason:
                return str(reason)
        verification = getattr(first, "verification_outcome", None)
        if verification:
            for tier_attr in ("tier_3", "tier_2", "tier_1"):
                tier = getattr(verification, tier_attr, None)
                tier_status = getattr(tier, "status", None) if tier else None
                tier_reason = getattr(tier, "failure_reason", None) if tier else None
                if tier_status == "fail" and tier_reason:
                    return f"{tier_attr}: {tier_reason}"
        return None

    @staticmethod
    def _should_skip(
        step_id: str,
        step_map: dict[str, WorkflowStepSchema],
        completed_outcomes: dict[str, dict],
        edges_map: dict[tuple[str, str], str | None],
        workflow_context: dict[str, Any] | None = None,
        mission_id: str | None = None,
    ) -> bool:
        """Check if a step should be skipped.

        A step is skipped when:
        1. It has an inline ``condition`` expression that evaluates to false, OR
        2. ANY of its dependencies is a condition node whose branch result
           does not match the edge label connecting them, OR
        3. ANY of its dependencies was itself skipped (propagation).

        Exception: merge nodes never propagate skips from dependencies.
        A merge is a join point that collects whatever completed; its
        _execute_merge_step already filters out skipped deps at runtime.

        If no edge label exists on a condition-node edge the step always runs
        (backward-compatible).
        """
        step = step_map[step_id]

        # ── Inline step-level condition guard ──
        if step.condition:
            from modules.backend.services.condition_evaluator import (
                ConditionEvaluationError,
                evaluate_condition,
            )

            try:
                result = evaluate_condition(
                    step.condition,
                    completed_outcomes,
                    workflow_context or {},
                )
                if not result:
                    logger.info(
                        "Step skipped by inline condition",
                        extra={"step_id": step_id, "condition": step.condition},
                    )
                    return True
            except ConditionEvaluationError:
                # best-effort — this is a static helper with no event_bus in
                # scope; fails safe by treating the step as skipped rather
                # than crashing the whole run.
                logger.error(
                    "Inline condition evaluation failed — skipping step",
                    extra={
                        "mission_id": mission_id,
                        "step_id": step_id,
                        "condition": step.condition,
                    },
                    exc_info=True,
                )
                return True

        # Merge nodes are join points — they never skip due to dep propagation.
        # Their execution logic already handles skipped deps gracefully.
        is_merge = getattr(step, "node_type", "agent_step") == "merge"

        # ── Graph-based condition-node routing ──
        for dep_id in step.depends_on:
            dep = step_map.get(dep_id)
            if dep is None:
                continue
            dep_type = getattr(dep, "node_type", "agent_step")
            if dep_type not in ("condition", "decision"):
                # Propagate skips — unless this step is a merge node
                if not is_merge:
                    dep_outcome = completed_outcomes.get(dep_id, {})
                    if dep_outcome.get("_skipped"):
                        return True
                continue

            # Dependency is a condition or decision node — check the branch
            dep_outcome = completed_outcomes.get(dep_id, {})
            if dep_outcome.get("_skipped") and not is_merge:
                return True
            branch_taken = dep_outcome.get("_branch")
            if branch_taken is None:
                continue  # condition hasn't run yet — shouldn't happen in wave order

            edge_label = edges_map.get((dep_id, step_id))
            if edge_label is None:
                continue  # no label on edge — always run
            if edge_label != branch_taken and not is_merge:
                return True
            # Merge nodes: the edge-label-mismatch check is suppressed.
            # A merge is a multi-path join point: it should run whenever
            # *any* incoming branch reached it, not require *every*
            # condition/decision dep's branch label to match. Without
            # this guard, a merge that has both labelled (e.g. halt/
            # continue) and unlabelled (always-run) incoming edges gets
            # skipped whenever a labelled dep chose the unmatched
            # branch, even though the unlabelled dep correctly reached
            # the merge. _execute_merge_step already filters skipped
            # deps at runtime; this matches that intent here.

        return False

    def _build_step_objective(
        self,
        step: WorkflowStepSchema,
        step_input: dict[str, Any],
    ) -> str:
        """Build an objective string from the step definition and resolved input.

        Plan 79 §8.2 — dict/list values are JSON-encoded so structured
        upstream context (e.g. a debater's prior turn, the research
        packet) reaches the agent in machine-parseable form rather than
        being dropped silently. None values are skipped. Scalar values
        (str/int/float/bool) format as `key: value`.
        """
        import json

        parts = [step.description or f"Execute step: {step.id}"]

        if step_input:
            context_parts = []
            for key, value in step_input.items():
                if value is None:
                    continue
                if isinstance(value, str):
                    context_parts.append(f"{key}: {value}")
                elif isinstance(value, (dict, list)):
                    context_parts.append(f"{key}: {json.dumps(value, default=str)}")
                else:
                    # int, float, bool, etc.
                    context_parts.append(f"{key}: {value}")
            if context_parts:
                parts.append("Context: " + "; ".join(context_parts))

        return ". ".join(parts)

    @staticmethod
    def _compute_waves(
        steps: list[WorkflowStepSchema],
    ) -> list[list[str]]:
        """Topologically sort steps into execution waves.

        Steps with no unmet dependencies run in the same wave (parallel).
        Returns a list of waves, each wave is a list of step IDs.
        """
        # Build dependency graph
        in_degree: dict[str, int] = {}
        dependents: dict[str, list[str]] = defaultdict(list)

        for step in steps:
            in_degree[step.id] = len(step.depends_on)
            for dep in step.depends_on:
                dependents[dep].append(step.id)

        waves: list[list[str]] = []
        remaining = set(in_degree.keys())

        while remaining:
            # Find all steps with no unmet dependencies
            wave = [sid for sid in remaining if in_degree[sid] == 0]

            if not wave:
                raise RuntimeError("Dependency cycle detected in workflow steps")

            waves.append(sorted(wave))

            # Remove completed steps and update degrees
            for sid in wave:
                remaining.remove(sid)
                for dependent in dependents[sid]:
                    in_degree[dependent] -= 1

        return waves
