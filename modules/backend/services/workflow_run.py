"""
WorkflowRun Service (Orchestrator).

Executes a workflow end-to-end: creates a WorkflowRun record, resolves
steps into executions, dispatches them in dependency order, chains outputs
between steps, and tracks aggregate cost.

Steps within the same wave (no mutual dependencies) execute in parallel,
each with its own DB session to avoid SQLAlchemy async flush conflicts.

This is the bridge between the stateless WorkflowService (YAML loading)
and the stateful ExecutionService (execution lifecycle).

Wave-execution methods (_execute_steps, _execute_wave, _execute_step,
_build_step_objective, _compute_waves) live in workflow_run_waves.py
and are mixed in via WorkflowRunWavesMixin.
"""

from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now
from modules.backend.models.execution import WorkflowRun, WorkflowRunState
from modules.backend.repositories.workflow_run import WorkflowRunRepository
from modules.backend.schemas.workflow import WorkflowSchema
from modules.backend.models.base import SYSTEM_CLI_ID
from modules.backend.services.base import BaseService
from modules.backend.services.execution import ExecutionService
from modules.backend.services.workflow import WorkflowService
from modules.backend.services.workflow_run_waves import WorkflowRunWavesMixin

# Factory that returns an async context manager yielding an ExecutionService.
# Default implementation: ExecutionService.factory
ExecutionServiceFactory = Callable[[], AbstractAsyncContextManager[ExecutionService]]

logger = get_logger(__name__)


class WorkflowRunService(WorkflowRunWavesMixin, BaseService):
    """Orchestrates workflow execution."""

    def __init__(
        self,
        session: AsyncSession,
        execution_service_factory: ExecutionServiceFactory | None = None,
        workflow_service: WorkflowService | None = None,
        event_bus: Any | None = None,
    ) -> None:
        super().__init__(session)
        self._run_repo = WorkflowRunRepository(session)
        self._execution_service_factory = execution_service_factory
        self._workflow_service = workflow_service or WorkflowService()
        self._event_bus = event_bus

    @staticmethod
    @asynccontextmanager
    async def factory(
        event_bus: Any | None = None,
    ) -> AsyncGenerator["WorkflowRunService", None]:
        """Create a WorkflowRunService with its own DB session.

        Args:
            event_bus: Optional EventBusProtocol for real-time progress events.
                       Passed through to each ExecutionService instance.
        """
        from modules.backend.core.database import get_async_session

        def _execution_factory():
            return ExecutionService.factory(event_bus=event_bus)

        async with get_async_session() as db:
            yield WorkflowRunService(
                session=db,
                execution_service_factory=_execution_factory,
                event_bus=event_bus,
            )
            await db.commit()

    async def run_workflow(
        self,
        workflow_name: str,
        triggered_by: str = SYSTEM_CLI_ID,
        context_overrides: dict[str, Any] | None = None,
        on_progress: Any | None = None,
        mission_id: str | None = None,
        gate: object | None = None,
    ) -> WorkflowRun:
        """Execute a workflow by name from the DB.

        Resolution order:
        1. Mission-scoped workflow (mission_id + workflow_name)
        2. System template (mission_id IS NULL + workflow_name)
        3. Raise ValueError

        Delegates to run_workflow_from_definition() once the definition
        is resolved.
        """
        from modules.backend.core.exceptions import NotFoundError
        from modules.backend.services.workflow_definition import WorkflowDefinitionService

        if not mission_id:
            raise ValueError(
                "mission_id is required. Use --mission <name> to specify "
                "the target mission."
            )

        defn_svc = WorkflowDefinitionService(self._session)

        # Try mission-scoped first, then system template
        defn = None
        try:
            defn = await defn_svc.get_workflow(mission_id, workflow_name)
        except NotFoundError:
            try:
                defn = await defn_svc.get_workflow(None, workflow_name)
            except NotFoundError:
                raise ValueError(
                    f"Workflow '{workflow_name}' not found (checked mission "
                    f"'{mission_id}' and system templates)"
                )

        return await self.run_workflow_from_definition(
            workflow_definition_id=defn.id,
            mission_id=mission_id,
            triggered_by=triggered_by,
            context_overrides=context_overrides,
            on_progress=on_progress,
            gate=gate,
        )

    async def run_workflow_from_definition(
        self,
        workflow_definition_id: str,
        mission_id: str,
        *,
        triggered_by: str = "scheduler",
        budget_usd: float | None = None,
        context_overrides: dict[str, Any] | None = None,
        on_progress: Any | None = None,
        gate: object | None = None,
    ) -> WorkflowRun:
        """Execute a DB-backed workflow definition.

        Loads the WorkflowDefinition, converts it to a WorkflowSchema,
        and runs it through the same execution pipeline as YAML workflows.
        """
        from modules.backend.repositories.workflow_definition import (
            WorkflowDefinitionRepository,
        )

        defn_repo = WorkflowDefinitionRepository(self._session)
        defn = await defn_repo.get_by_id(workflow_definition_id)

        if not defn.enabled:
            raise ValueError(
                f"Workflow definition '{defn.name}' is disabled"
            )

        workflow = self._definition_to_schema(defn)
        effective_budget = budget_usd or workflow.budget.max_cost_usd

        errors = self._workflow_service.validate_workflow_capabilities(workflow)
        if errors:
            msg = f"Workflow capability errors: {'; '.join(errors)}"
            logger.warning(msg, mission_id=mission_id)
            raise ValueError(msg)

        from modules.backend.services.session import SessionService
        from modules.backend.schemas.session import SessionCreate

        session_service = SessionService(self._session)
        session = await session_service.create_session(
            SessionCreate(
                agent_id=None,
                goal=f"Workflow: {defn.description[:200]}",
            ),
        )

        # Create a parent ExecutionRecord so the workflow run appears in
        # the Runs tab alongside single-agent executions.
        # Created via repository (not ExecutionPersistenceService) because
        # the service is designed for post-execution persistence and
        # defaults completed_at to "now" — we need it NULL until the
        # workflow finishes.
        from modules.backend.models.execution_record import ExecutionRecordStatus
        from modules.backend.repositories.execution_record import ExecutionRecordRepository

        now = utc_now()
        exec_repo = ExecutionRecordRepository(self._session)
        exec_record = await exec_repo.create(
            session_id=session.id,
            mission_id=mission_id,
            roster_name=f"workflow:{defn.name}",
            objective_statement=defn.description[:500] if defn.description else defn.name,
            objective_category=defn.objective.get("category") if defn.objective else None,
            status=ExecutionRecordStatus.FAILED,  # safe default if process crashes; updated on completion
            total_cost_usd=0.0,
            started_at=now,
        )

        run = WorkflowRun(
            workflow_name=defn.name,
            workflow_version=defn.version,
            status=WorkflowRunState.RUNNING,
            session_id=session.id,
            trigger_type=defn.trigger_config.get("type", "on_demand"),
            triggered_by=triggered_by,
            context=dict(defn.context),
            total_cost_usd=0.0,
            budget_usd=effective_budget,
            started_at=now,
            mission_id=mission_id,
            execution_record_id=exec_record.id,
        )
        if context_overrides:
            run.context.update(context_overrides)

        self._session.add(run)
        await self._session.flush()
        await self._session.refresh(run)

        # Commit session + exec_record + workflow_run so child DB sessions
        # (opened by _execute_wave via factory) can see them. Without this,
        # the session_id FK in create_execution_from_step fails because the
        # session row exists only in this transaction's uncommitted state.
        await self._session.commit()

        # Persist workflow steps as a TaskPlan for Kanban board visibility
        await self._persist_workflow_as_plan(mission_id, workflow)

        logger.info(
            "DB workflow run started",
            extra={
                "run_id": run.id,
                "execution_record_id": exec_record.id,
                "workflow_definition_id": workflow_definition_id,
                "steps": len(workflow.steps),
                "budget_usd": run.budget_usd,
            },
        )

        try:
            await self._execute_steps(
                run, workflow, session.id, on_progress, gate=gate,
                edges=defn.edges_json if hasattr(defn, "edges_json") else None,
            )
            run.status = WorkflowRunState.COMPLETED
            run.completed_at = utc_now()
            run.result_summary = (
                f"Workflow completed: {len(workflow.steps)} steps, "
                f"${run.total_cost_usd:.4f}"
            )
            exec_record.status = ExecutionRecordStatus.COMPLETED
            # Publish completion event to SSE stream
            if self._event_bus and mission_id:
                try:
                    import uuid as _uuid
                    from modules.backend.events.types import WorkflowRunCompletedEvent
                    elapsed = (run.completed_at - run.started_at).total_seconds() if run.completed_at and run.started_at else None
                    await self._event_bus.publish_to_mission(
                        mission_id,
                        WorkflowRunCompletedEvent(
                            session_id=_uuid.UUID(session.id),
                            source="workflow_run_service",
                            workflow_run_id=run.id,
                            workflow_name=run.workflow_name,
                            total_cost_usd=run.total_cost_usd,
                            mission_count=len(workflow.steps),
                            elapsed_seconds=elapsed,
                            result_summary=run.result_summary,
                        ),
                    )
                except Exception:
                    pass  # best-effort
        except (RuntimeError, ValueError, OSError) as e:
            run.status = WorkflowRunState.FAILED
            run.completed_at = utc_now()
            run.error_data = {"message": str(e), "type": type(e).__name__}
            run.result_summary = f"Workflow failed: {e}"
            exec_record.status = ExecutionRecordStatus.FAILED
            logger.error(
                "DB workflow run failed",
                extra={"run_id": run.id, "error": str(e), "mission_id": mission_id},
            )
            # Emit error + failure events so they surface in the console/editor
            if self._event_bus and mission_id:
                try:
                    import uuid as _uuid
                    from modules.backend.events.types import SystemEvent, WorkflowRunFailedEvent
                    _sid = _uuid.UUID(session.id) if session else _uuid.uuid4()
                    await self._event_bus.publish_to_mission(
                        mission_id,
                        SystemEvent(
                            session_id=_sid,
                            source="workflow_run_service",
                            level="error",
                            message=f"Workflow '{run.workflow_name}' failed: {str(e)[:200]}",
                            mission_id=mission_id,
                        ),
                    )
                    await self._event_bus.publish_to_mission(
                        mission_id,
                        WorkflowRunFailedEvent(
                            session_id=_sid,
                            source="workflow_run_service",
                            workflow_run_id=run.id,
                            workflow_name=run.workflow_name,
                            error=str(e)[:200],
                            total_cost_usd=run.total_cost_usd,
                        ),
                    )
                except Exception:
                    pass  # best-effort

            # Mark remaining plan tasks as FAILED for Kanban board
            await self._fail_remaining_plan_tasks(mission_id, session.id, str(e))

        # Sync the parent ExecutionRecord with workflow outcome
        exec_record.total_cost_usd = run.total_cost_usd
        exec_record.completed_at = utc_now()
        exec_record.execution_outcome_json = {
            "workflow_run_id": run.id,
            "workflow_name": run.workflow_name,
            "status": run.status.value if hasattr(run.status, "value") else str(run.status),
            "result_summary": run.result_summary,
            "step_count": len(workflow.steps),
        }

        await self._session.flush()
        await self._notify_run_outcome(run, len(workflow.steps))

        logger.info(
            "DB workflow run finished",
            extra={
                "run_id": run.id,
                "execution_record_id": exec_record.id,
                "status": run.status,
                "cost": run.total_cost_usd,
            },
        )

        return run

    @staticmethod
    def _definition_to_schema(defn) -> WorkflowSchema:
        """Convert a WorkflowDefinition model to a WorkflowSchema.

        The WorkflowSchema name pattern requires '.workflow' suffix,
        so we normalize the definition name.
        """
        from modules.backend.schemas.workflow import (
            WorkflowBudgetSchema,
            WorkflowObjectiveSchema,
            WorkflowStepSchema,
            WorkflowTriggerSchema,
        )

        name = defn.name
        if not name.endswith(".workflow"):
            name = f"db.{name.replace(' ', '_').replace('-', '_').lower()}.workflow"

        return WorkflowSchema(
            workflow_name=name,
            description=defn.description or name,
            objective=WorkflowObjectiveSchema(**defn.objective),
            version=defn.version,
            enabled=defn.enabled,
            trigger=WorkflowTriggerSchema(**defn.trigger_config),
            budget=WorkflowBudgetSchema(**defn.budget_config),
            context=defn.context or {},
            steps=[WorkflowStepSchema(**s) for s in defn.steps],
        )

    async def _persist_workflow_as_plan(
        self,
        mission_id: str,
        workflow: WorkflowSchema,
    ) -> None:
        """Convert workflow steps to a TaskPlan and persist for Kanban visibility.

        Creates PlanTaskState rows and auto-approves all tasks since
        workflow dispatch is pre-approved. Best-effort — failure logs
        a warning but does not block workflow execution.
        """
        try:
            from modules.backend.schemas.task_plan import TaskDefinition, TaskInputs, TaskPlan
            from modules.backend.services.mission_plan import MissionPlanService
            from modules.backend.services.mission_plan_orchestrator import MissionPlanOrchestrator

            tasks = []
            for step in workflow.steps:
                task_id = f"wf-{step.id}"
                agent = step.capability or f"workflow:{step.node_type}"
                tasks.append(TaskDefinition(
                    task_id=task_id,
                    agent=agent,
                    description=step.description or step.label or step.id,
                    instructions=step.description or f"Workflow step: {step.id}",
                    dependencies=[f"wf-{d}" for d in step.depends_on],
                    inputs=TaskInputs(static=step.input or {}),
                ))

            task_plan = TaskPlan(
                version="1.0.0",
                mission_id=mission_id,
                summary=workflow.description,
                estimated_cost_usd=workflow.budget.max_cost_usd,
                estimated_duration_seconds=0,
                tasks=tasks,
            )

            plan_svc = MissionPlanService(self._session, event_bus=self._event_bus)
            plan = await plan_svc.get_or_create_plan(mission_id)

            orchestrator = MissionPlanOrchestrator(self._session, event_bus=self._event_bus)
            await orchestrator._persist_plan(plan, task_plan, source="workflow_run_service")

            # Mark as workflow-managed so the Temporal autonomous scheduler
            # (find_ready_plans) skips these — the workflow engine owns dispatch.
            plan.gate_mode = "workflow_managed"

            # Auto-approve all tasks — workflow dispatch is pre-approved.
            # Can't use approve_all_proposed() because it requires a user_id FK.
            # Update status directly on the PlanTaskState rows.
            from modules.backend.models.mission_plan import PlanTaskStatus
            from modules.backend.core.utils import utc_now
            states = await plan_svc._repo.get_task_states(
                plan.id, status=PlanTaskStatus.PROPOSED,
            )
            now = utc_now()
            for state in states:
                state.status = PlanTaskStatus.APPROVED
                state.approved_at = now
            await self._session.commit()

            logger.info(
                "Workflow plan persisted for Kanban",
                extra={
                    "mission_id": mission_id,
                    "plan_id": plan.id,
                    "task_count": len(tasks),
                },
            )
        except Exception:
            logger.warning(
                "Failed to persist workflow plan for Kanban (non-fatal)",
                extra={"mission_id": mission_id},
                exc_info=True,
            )
            try:
                await self._session.rollback()
            except Exception:
                pass

    async def _fail_remaining_plan_tasks(
        self,
        mission_id: str,
        session_id: str,
        error: str,
    ) -> None:
        """Mark any RUNNING/APPROVED plan tasks as FAILED after workflow failure."""
        try:
            from modules.backend.core.database import get_async_session
            from modules.backend.events.types import MissionPlanTaskStatusChangedEvent
            from modules.backend.models.mission_plan import PlanTaskStatus
            from modules.backend.repositories.mission_plan import MissionPlanRepository

            async with get_async_session() as db:
                repo = MissionPlanRepository(db)
                plan = await repo.get_by_mission_id(mission_id)
                if not plan:
                    return

                import uuid as _uuid
                for state in await repo.get_task_states(plan.id):
                    if state.status in (PlanTaskStatus.RUNNING, PlanTaskStatus.APPROVED):
                        from_status = state.status
                        state.status = PlanTaskStatus.FAILED
                        state.failure_reason = error[:500]

                        if self._event_bus:
                            try:
                                await self._event_bus.publish_to_mission(
                                    mission_id,
                                    MissionPlanTaskStatusChangedEvent(
                                        session_id=_uuid.UUID(session_id),
                                        source="workflow_run_service",
                                        mission_id=mission_id,
                                        plan_id=plan.id,
                                        task_id=state.task_id,
                                        from_status=from_status,
                                        to_status=PlanTaskStatus.FAILED,
                                        actor="workflow_run_service",
                                    ),
                                )
                            except Exception:
                                pass

                await db.commit()
        except Exception:
            logger.debug("Failed to mark plan tasks as failed (non-fatal)", exc_info=True)

    async def list_runs(
        self,
        workflow_name: str | None = None,
        limit: int = 20,
    ) -> tuple[list[WorkflowRun], int]:
        """List workflow runs."""
        return await self._run_repo.list_runs(
            workflow_name=workflow_name,
            limit=limit,
        )

    async def get_run(self, run_id: str) -> WorkflowRun | None:
        """Get a workflow run by ID."""
        return await self._run_repo.get_by_id_or_none(run_id)

    @staticmethod
    async def _notify_run_outcome(run: "WorkflowRun", step_count: int) -> None:
        """Send notifications based on run outcome. Best-effort."""
        try:
            from modules.backend.services.run_notifier import RunNotifierService

            status = run.status if isinstance(run.status, str) else run.status.value

            if status == WorkflowRunState.COMPLETED.value:
                await RunNotifierService.notify_run_completed(
                    run_id=run.id,
                    workflow_name=run.workflow_name,
                    total_cost_usd=run.total_cost_usd,
                    step_count=step_count,
                    mission_id=run.mission_id,
                )
            elif status == WorkflowRunState.FAILED.value:
                error_msg = ""
                if run.error_data and isinstance(run.error_data, dict):
                    error_msg = run.error_data.get("message", "Unknown error")
                await RunNotifierService.notify_run_failed(
                    run_id=run.id,
                    workflow_name=run.workflow_name,
                    error=error_msg,
                    total_cost_usd=run.total_cost_usd,
                    mission_id=run.mission_id,
                )

            if run.budget_usd and run.budget_usd > 0:
                pct = (run.total_cost_usd / run.budget_usd) * 100
                await RunNotifierService.notify_budget_warning(
                    run_id=run.id,
                    workflow_name=run.workflow_name,
                    cost_usd=run.total_cost_usd,
                    budget_usd=run.budget_usd,
                    pct_used=pct,
                )
        except Exception:
            logger.debug("Run notification failed", exc_info=True)

