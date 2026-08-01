"""
WorkflowRun Service (Orchestrator).

Executes a workflow end-to-end: creates a WorkflowRun record, resolves
steps into executions, dispatches them in dependency order, chains outputs
between steps, and tracks aggregate cost.

Steps within the same wave (no mutual dependencies) execute in parallel,
each with its own DB session to avoid SQLAlchemy async flush conflicts.

This is the bridge between the stateless WorkflowService (YAML loading)
and the stateful ExecutionPersistenceService (execution lifecycle).

Wave-execution methods (_execute_steps, _execute_wave, _execute_step)
live in workflow_run_waves.py and are mixed in via WorkflowRunWavesMixin.
Per-node-type step executors and pure helpers live in the sibling
workflow_run_steps/ package (Plan 84 Phase 5.1).
"""

from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ConflictError, NotFoundError, ValidationError
from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now
from modules.backend.models.base import SYSTEM_CLI_ID
from modules.backend.models.human_input_request import HumanInputRequest, HumanInputRequestStatus
from modules.backend.models.workflow_run import WorkflowRun, WorkflowRunState
from modules.backend.repositories.workflow_run import WorkflowRunRepository
from modules.backend.schemas.workflow import WorkflowParameterSchema, WorkflowSchema
from modules.backend.services.base import BaseService
from modules.backend.services.workflow import WorkflowService
from modules.backend.services.workflow_run_waves import StepContext, WorkflowRunWavesMixin

# Factory that returns an async context manager yielding a StepContext.
StepContextFactory = Callable[[], AbstractAsyncContextManager[StepContext]]


def validate_workflow_parameters(
    parameters: list[WorkflowParameterSchema],
    overrides: dict[str, Any],
) -> list[str]:
    """Validate context_overrides against workflow parameter definitions.

    Returns a list of error messages. Empty list = valid.
    """
    errors: list[str] = []
    for param in parameters:
        value = overrides.get(param.key)

        # Required check
        if param.required and value is None and param.default is None:
            errors.append(f"'{param.label}' ({param.key}) is required")
            continue

        # Skip further validation if no value provided (will use default)
        if value is None:
            continue

        # Type checks
        if param.type == "number" and not isinstance(value, (int, float)):
            errors.append(f"'{param.label}' must be a number")
        elif param.type == "boolean" and not isinstance(value, bool):
            errors.append(f"'{param.label}' must be a boolean")
        elif param.type == "enum" and param.options and value not in param.options:
            errors.append(f"'{param.label}' must be one of: {', '.join(param.options)}")
        elif param.type in ("string", "text") and not isinstance(value, str):
            errors.append(f"'{param.label}' must be a string")

        # Range checks for numbers
        if param.type == "number" and isinstance(value, (int, float)):
            if param.min is not None and value < param.min:
                errors.append(f"'{param.label}' must be >= {param.min}")
            if param.max is not None and value > param.max:
                errors.append(f"'{param.label}' must be <= {param.max}")

    return errors


logger = get_logger(__name__)


class WorkflowRunService(WorkflowRunWavesMixin, BaseService):
    """Orchestrates workflow execution."""

    def __init__(
        self,
        session: AsyncSession,
        step_context_factory: StepContextFactory | None = None,
        workflow_service: WorkflowService | None = None,
        event_bus: Any | None = None,
    ) -> None:
        super().__init__(session)
        self._run_repo = WorkflowRunRepository(session)
        self._step_context_factory = step_context_factory
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
        """
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            yield WorkflowRunService(
                session=db,
                step_context_factory=StepContext.factory,
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
                "mission_id is required. Use --mission <name> to specify " "the target mission."
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
        from modules.backend.repositories.workflow_definition import WorkflowDefinitionRepository

        defn_repo = WorkflowDefinitionRepository(self._session)
        defn = await defn_repo.get_by_id(workflow_definition_id)

        if not defn.enabled:
            raise ValueError(f"Workflow definition '{defn.name}' is disabled")

        workflow = self._definition_to_schema(defn)
        effective_budget = budget_usd or workflow.budget.max_cost_usd

        errors = self._workflow_service.validate_workflow_capabilities(workflow)
        if errors:
            msg = f"Workflow capability errors: {'; '.join(errors)}"
            logger.warning(msg, mission_id=mission_id)
            raise ValueError(msg)

        # Validate required parameters are provided
        param_errors = validate_workflow_parameters(
            workflow.parameters,
            context_overrides or {},
        )
        if param_errors:
            msg = f"Missing required parameters: {'; '.join(param_errors)}"
            raise ValueError(msg)

        from modules.backend.schemas.session import SessionCreate
        from modules.backend.services.session import SessionService

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
            # Safe default if the process crashes; updated on completion.
            status=ExecutionRecordStatus.FAILED,
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
        step_task_map = await self._persist_workflow_as_plan(mission_id, workflow)

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
                run,
                workflow,
                session.id,
                on_progress,
                gate=gate,
                edges=defn.edges_json if hasattr(defn, "edges_json") else None,
                step_task_map=step_task_map,
            )
            run.status = WorkflowRunState.COMPLETED
            run.completed_at = utc_now()
            run.result_summary = (
                f"Workflow completed: {len(workflow.steps)} steps, " f"${run.total_cost_usd:.4f}"
            )
            exec_record.status = ExecutionRecordStatus.COMPLETED
            # Publish completion event to SSE stream
            if self._event_bus and mission_id:
                try:
                    import uuid as _uuid

                    from modules.backend.events.types import WorkflowRunCompletedEvent

                    elapsed = (
                        (run.completed_at - run.started_at).total_seconds()
                        if run.completed_at and run.started_at
                        else None
                    )
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
                    logger.debug(
                        "workflow run completed event publish failed (best-effort)", exc_info=True
                    )
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
                    logger.debug(
                        "workflow run failed event publish failed (best-effort)", exc_info=True
                    )

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

        from modules.backend.schemas.workflow import WorkflowParameterSchema

        return WorkflowSchema(
            workflow_name=name,
            description=defn.description or name,
            objective=WorkflowObjectiveSchema(**defn.objective),
            version=defn.version,
            enabled=defn.enabled,
            trigger=WorkflowTriggerSchema(**defn.trigger_config),
            budget=WorkflowBudgetSchema(**defn.budget_config),
            parameters=[WorkflowParameterSchema(**p) for p in (defn.parameters or [])],
            context=defn.context or {},
            steps=[WorkflowStepSchema(**s) for s in defn.steps],
        )

    async def _persist_workflow_as_plan(
        self,
        mission_id: str,
        workflow: WorkflowSchema,
    ) -> dict[str, str]:
        """Convert workflow steps to a TaskPlan and persist for Kanban visibility.

        Creates Task rows and auto-approves all tasks since
        workflow dispatch is pre-approved. Best-effort — failure logs
        a warning but does not block workflow execution.

        Returns a step_id → task_uuid mapping for Kanban state sync.
        Empty dict on failure.
        """
        try:
            import uuid as _uuid

            from modules.backend.schemas.task_plan import TaskDefinition, TaskInputs, TaskPlan
            from modules.backend.services.mission_plan import MissionPlanService
            from modules.backend.services.mission_plan_orchestrator import MissionPlanOrchestrator

            # Map step IDs to UUIDs so Task rows get valid PKs
            step_uuid_map = {step.id: str(_uuid.uuid4()) for step in workflow.steps}

            tasks = []
            for step in workflow.steps:
                task_id = step_uuid_map[step.id]
                # capability is the short form (e.g. "research.synthesizer");
                # the roster keys agents by full name "<capability>.agent".
                # Must match the dispatch path in workflow_run_waves.py
                # so retry/redispatch validates against the same name.
                agent = (
                    f"{step.capability}.agent" if step.capability else f"workflow:{step.node_type}"
                )
                tasks.append(
                    TaskDefinition(
                        task_id=task_id,
                        agent=agent,
                        description=step.description or step.label or step.id,
                        instructions=step.description or f"Workflow step: {step.id}",
                        dependencies=[
                            step_uuid_map[d] for d in step.depends_on if d in step_uuid_map
                        ],
                        inputs=TaskInputs(static=step.input or {}),
                    )
                )

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
            #
            # Plan 80g: when the plan's gate_mode is `manual` (or other
            # interactive modes), preserve it — workflow_run_waves now calls
            # ConfigurableGate.review() before each step, so the gate fires
            # during execution. Setting `workflow_managed` here would lose
            # that mode and the gate would silently no-op.
            if plan.gate_mode not in ("manual", "interactive", "ai_assisted"):
                plan.gate_mode = "workflow_managed"

            # Plan 80h: tasks always start PROPOSED. Mode determines who
            # triggers the PROPOSED → APPROVED transition:
            #   - autonomous: auto-approver below transitions immediately
            #   - manual / interactive / ai_assisted: operator approves
            #     via `mc plan approve <task_id>` (or TTY prompt etc.)
            from modules.backend.core.utils import utc_now
            from modules.backend.models.task import TaskStatus
            from modules.backend.repositories.task import TaskRepository

            task_repo = TaskRepository(self._session)
            tasks = await task_repo.get_by_plan_id(
                plan.id,
                status=TaskStatus.PROPOSED,
            )
            if plan.gate_mode in ("workflow_managed", "autonomous"):
                # Autonomous-mode auto-approver: transition immediately at
                # creation. Same end state as the legacy bulk-approve, but
                # routed through the canonical lifecycle so the Kanban
                # tells the truth.
                now = utc_now()
                for task in tasks:
                    task.status = TaskStatus.APPROVED
                    task.approved_at = now
                logger.info(
                    "Autonomous gate mode — auto-approved %d tasks at creation",
                    len(tasks),
                    extra={"mission_id": mission_id, "plan_id": plan.id},
                )
            else:
                logger.info(
                    "Interactive gate mode — %d tasks left PROPOSED for operator approval",
                    len(tasks),
                    extra={
                        "mission_id": mission_id,
                        "plan_id": plan.id,
                        "gate_mode": plan.gate_mode,
                    },
                )
            await self._session.commit()

            logger.info(
                "Workflow plan persisted for Kanban",
                extra={
                    "mission_id": mission_id,
                    "plan_id": plan.id,
                    "task_count": len(tasks),
                },
            )
            return step_uuid_map
        except Exception:
            logger.warning(
                "Failed to persist workflow plan for Kanban (non-fatal)",
                extra={"mission_id": mission_id},
                exc_info=True,
            )
            try:
                await self._session.rollback()
            except Exception:
                logger.debug("db rollback failed after workflow plan persist error", exc_info=True)
            return {}

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
            from modules.backend.models.task import TaskStatus
            from modules.backend.repositories.mission_plan import MissionPlanRepository
            from modules.backend.repositories.task import TaskRepository

            async with get_async_session() as db:
                repo = MissionPlanRepository(db)
                plan = await repo.get_by_mission_id(mission_id)
                if not plan:
                    return

                task_repo = TaskRepository(db)
                import uuid as _uuid

                for task in await task_repo.get_by_plan_id(plan.id):
                    if task.status in (TaskStatus.RUNNING, TaskStatus.APPROVED):
                        from_status = task.status
                        task.status = TaskStatus.FAILED
                        task.failure_reason = error[:500]

                        if self._event_bus:
                            try:
                                await self._event_bus.publish_to_mission(
                                    mission_id,
                                    MissionPlanTaskStatusChangedEvent(
                                        session_id=_uuid.UUID(session_id),
                                        source="workflow_run_service",
                                        mission_id=mission_id,
                                        plan_id=plan.id,
                                        task_id=task.id,
                                        from_status=from_status,
                                        to_status=TaskStatus.FAILED,
                                        actor="workflow_run_service",
                                    ),
                                )
                            except Exception:
                                logger.debug(
                                    "task status update event publish failed (best-effort)",
                                    exc_info=True,
                                )

                await db.commit()
        except Exception:
            logger.debug("Failed to mark plan tasks as failed (non-fatal)", exc_info=True)

    async def list_runs(
        self,
        workflow_name: str | None = None,
        limit: int = 20,
        *,
        mission_id: str | None = None,
        status: str | None = None,
        offset: int = 0,
    ) -> tuple[list[WorkflowRun], int]:
        """List workflow runs with optional filters.

        Args:
            workflow_name: Filter to one workflow.
            limit: Page size.
            mission_id: Filter to one mission.
            status: Case-insensitive WorkflowRunState name (e.g. "running").
            offset: Pagination offset.

        Raises:
            ValidationError: `status` is not a valid WorkflowRunState name.
        """
        status_filter: WorkflowRunState | None = None
        if status:
            try:
                status_filter = WorkflowRunState[status.upper()]
            except KeyError:
                raise ValidationError(
                    f"Unknown workflow run status {status!r}. "
                    f"Valid: {sorted(s.name.lower() for s in WorkflowRunState)}"
                )
        return await self._run_repo.list_runs(
            workflow_name=workflow_name,
            status=status_filter,
            mission_id=mission_id,
            limit=limit,
            offset=offset,
        )

    async def get_run(self, run_id: str) -> WorkflowRun | None:
        """Get a workflow run by ID."""
        return await self._run_repo.get_by_id_or_none(run_id)

    async def get_run_executions(self, run_id: str) -> list:
        """Get the step execution records for a workflow run, in creation order."""
        from modules.backend.repositories.execution_record import ExecutionRecordRepository

        exec_repo = ExecutionRecordRepository(self._session)
        return await exec_repo.get_by_workflow_run(run_id)

    async def cancel_run(
        self,
        run_id: str,
        mission_id: str | None = None,
    ) -> tuple[WorkflowRun, bool]:
        """Mark a workflow run CANCELLED unless it is already terminal.

        Args:
            run_id: The run to cancel.
            mission_id: When given, the run must belong to this mission.

        Returns:
            (run, changed) — `changed` is False when the run was already
            in a terminal state (idempotent no-op). Caller commits.

        Raises:
            NotFoundError: unknown run, or run not in `mission_id`.
        """
        run = await self._run_repo.get_by_id(run_id)
        if mission_id is not None and run.mission_id != mission_id:
            raise NotFoundError(f"Workflow run {run_id} not found in mission {mission_id}")

        current = run.status.value if hasattr(run.status, "value") else str(run.status)
        terminal = {
            WorkflowRunState.COMPLETED.value,
            WorkflowRunState.FAILED.value,
            WorkflowRunState.CANCELLED.value,
        }
        if str(current).lower() in terminal:
            return run, False

        run.status = WorkflowRunState.CANCELLED
        run.completed_at = utc_now()
        await self._session.flush()
        logger.info(
            "Workflow run cancelled",
            extra={"run_id": run_id, "previous_status": str(current)},
        )
        return run, True

    # ── Human input requests (Plan 45) ──────────────────────────────────

    async def list_pending_human_input(self, mission_id: str) -> list[HumanInputRequest]:
        """List a mission's PENDING human input requests, newest first."""
        result = await self._session.execute(
            select(HumanInputRequest)
            .where(
                HumanInputRequest.mission_id == mission_id,
                HumanInputRequest.status == HumanInputRequestStatus.PENDING,
            )
            .order_by(HumanInputRequest.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_pending_human_input_request(
        self,
        mission_id: str,
        input_request_id: str,
    ) -> HumanInputRequest:
        """Return a pending human input request scoped to the mission.

        Raises:
            NotFoundError: unknown id, or the request belongs to another
                mission (scoping — the id alone must not let a caller
                signal another mission's pending request).
            ConflictError: the request is no longer pending.
        """
        result = await self._session.execute(
            select(HumanInputRequest).where(HumanInputRequest.id == input_request_id)
        )
        req = result.scalar_one_or_none()
        if req is None or req.mission_id != mission_id:
            raise NotFoundError("Human input request not found")
        if (
            req.status != HumanInputRequestStatus.PENDING.value
            and req.status != HumanInputRequestStatus.PENDING
        ):
            raise ConflictError(f"Request is not pending (status: {req.status})")
        return req

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
