"""
WorkflowRun Service (Orchestrator).

Executes a workflow end-to-end: creates a WorkflowRun record, resolves
steps into executions, dispatches them in dependency order, chains outputs
between steps, and tracks aggregate cost.

Steps within the same wave (no mutual dependencies) execute in parallel,
each with its own DB session to avoid SQLAlchemy async flush conflicts.

This is the bridge between the stateless WorkflowService (YAML loading)
and the stateful ExecutionService (execution lifecycle).
"""

import asyncio
from collections import defaultdict
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config import get_app_config
from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now
from modules.backend.models.execution import WorkflowRun, WorkflowRunState
from modules.backend.repositories.workflow_run import WorkflowRunRepository
from modules.backend.schemas.workflow import WorkflowSchema, WorkflowStepSchema
from modules.backend.services.base import BaseService
from modules.backend.services.execution import ExecutionService
from modules.backend.services.workflow import WorkflowService

# Factory that returns an async context manager yielding an ExecutionService.
# Default implementation: ExecutionService.factory
ExecutionServiceFactory = Callable[[], AbstractAsyncContextManager[ExecutionService]]

logger = get_logger(__name__)


class WorkflowRunService(BaseService):
    """Orchestrates workflow execution."""

    def __init__(
        self,
        session: AsyncSession,
        execution_service_factory: ExecutionServiceFactory | None = None,
        workflow_service: WorkflowService | None = None,
    ) -> None:
        super().__init__(session)
        self._run_repo = WorkflowRunRepository(session)
        self._execution_service_factory = execution_service_factory
        self._workflow_service = workflow_service or WorkflowService()

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
            )
            await db.commit()

    async def run_workflow(
        self,
        workflow_name: str,
        triggered_by: str = "system:cli",
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
            raise ValueError(
                f"Workflow capability errors: {'; '.join(errors)}"
            )

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
        from modules.backend.models.execution_record import (
            ExecutionRecord,
            ExecutionRecordStatus,
        )
        from modules.backend.repositories.execution_record import ExecutionRecordRepository

        now = utc_now()
        exec_repo = ExecutionRecordRepository(self._session)
        exec_record = await exec_repo.create(
            session_id=session.id,
            mission_id=mission_id,
            roster_name=f"workflow:{defn.name}",
            objective_statement=defn.description[:500] if defn.description else defn.name,
            objective_category=defn.objective.get("category") if defn.objective else None,
            status=ExecutionRecordStatus.COMPLETED,  # updated to actual outcome at end
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
            started_at=now.isoformat(),
            mission_id=mission_id,
            execution_record_id=exec_record.id,
        )
        if context_overrides:
            run.context.update(context_overrides)

        self._session.add(run)
        await self._session.flush()
        await self._session.refresh(run)

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
            )
            run.status = WorkflowRunState.COMPLETED
            run.completed_at = utc_now().isoformat()
            run.result_summary = (
                f"Workflow completed: {len(workflow.steps)} steps, "
                f"${run.total_cost_usd:.4f}"
            )
            exec_record.status = ExecutionRecordStatus.COMPLETED
        except (RuntimeError, ValueError, OSError) as e:
            run.status = WorkflowRunState.FAILED
            run.completed_at = utc_now().isoformat()
            run.error_data = {"message": str(e), "type": type(e).__name__}
            run.result_summary = f"Workflow failed: {e}"
            exec_record.status = ExecutionRecordStatus.FAILED
            logger.error(
                "DB workflow run failed",
                extra={"run_id": run.id, "error": str(e), "mission_id": mission_id},
            )

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

    # ---- Internal orchestration ----

    async def _execute_steps(
        self,
        run: WorkflowRun,
        workflow: WorkflowSchema,
        session_id: str,
        on_progress: Any | None = None,
        gate: object | None = None,
    ) -> None:
        """Execute steps in topological wave order.

        Steps within a wave have no mutual dependencies and run in
        parallel via asyncio.gather. Each step gets its own DB session
        (via execution_service_factory) to avoid SQLAlchemy flush conflicts.
        Falls back to sequential execution when no factory is provided.
        """
        waves = self._compute_waves(workflow.steps)
        completed_outcomes: dict[str, dict] = {}
        step_map = {step.id: step for step in workflow.steps}
        total_steps = len(workflow.steps)

        def _emit(event: dict) -> None:
            if on_progress:
                on_progress(event)

        _emit({"type": "workflow_start", "workflow": workflow.workflow_name, "total_steps": total_steps})

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
                    f"Budget exceeded: ${run.total_cost_usd:.4f} >= "
                    f"${run.budget_usd:.2f}"
                )

            # Emit step_start for all steps in wave
            for step_id in wave_step_ids:
                step = step_map[step_id]
                _emit({
                    "type": "step_start",
                    "step_id": step_id,
                    "capability": step.capability,
                    "description": step.description or step_id,
                })

            # Execute all steps in this wave concurrently
            wave_steps = [step_map[sid] for sid in wave_step_ids]
            results = await self._execute_wave(
                run, wave_steps, session_id, completed_outcomes, gate=gate,
            )

            # Collect results sequentially (cost, outcomes, events)
            for step, (execution, extracted_outputs) in zip(wave_steps, results):
                completed_outcomes[step.id] = extracted_outputs
                run.total_cost_usd += execution.total_cost_usd
                status_str = execution.status if isinstance(execution.status, str) else execution.status.value
                _emit({
                    "type": "step_done",
                    "step_id": step.id,
                    "status": status_str,
                    "cost_usd": execution.total_cost_usd,
                    "completed_steps": len(completed_outcomes),
                    "total_steps": total_steps,
                })

    async def _execute_wave(
        self,
        run: WorkflowRun,
        steps: list[WorkflowStepSchema],
        session_id: str,
        completed_outcomes: dict[str, dict],
        gate: object | None = None,
    ) -> list[tuple[Any, dict]]:
        """Execute all steps in a wave concurrently.

        Each step gets its own DB session via the factory to avoid
        SQLAlchemy async flush conflicts.
        """
        if self._execution_service_factory is None:
            raise RuntimeError(
                "execution_service_factory is required to execute workflows"
            )

        async def _run_step(step: WorkflowStepSchema) -> tuple[Any, dict]:
            async with self._execution_service_factory() as execution_service:
                return await self._execute_step(
                    run, step, session_id, completed_outcomes,
                    execution_service, gate=gate,
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
        execution_service: ExecutionService,
        gate: object | None = None,
    ) -> tuple[Any, dict]:
        """Execute a single workflow step as an execution."""
        # Resolve upstream context from dependencies
        upstream = self._workflow_service.resolve_upstream_context(
            step, completed_outcomes, run.context,
        )

        # Build the objective from step description + input context
        step_input = upstream.get("_step_input", step.input)
        objective = self._build_step_objective(step, step_input)

        app_config = get_app_config()
        cost_ceiling = (
            step.cost_ceiling_usd
            or app_config.workflows.default_budget_usd
        )

        execution = await execution_service.create_execution_from_step(
            workflow_run_id=run.id,
            step_id=step.id,
            objective=objective,
            roster_ref=step.roster,
            complexity_tier=step.complexity_tier,
            cost_ceiling_usd=cost_ceiling,
            upstream_context=upstream,
            session_id=session_id,
            mission_id=run.mission_id,
        )

        logger.info(
            "Step execution created",
            extra={
                "run_id": run.id,
                "step_id": step.id,
                "execution_id": execution.id,
                "agent": f"{step.capability}.agent",
            },
        )

        execution = await execution_service.run_execution(execution.id, gate=gate)

        output_mapping = (
            step.output_mapping.model_dump()
            if step.output_mapping
            else None
        )
        extracted = execution_service.extract_outputs(
            execution, output_mapping,
        )

        status_str = execution.status if isinstance(execution.status, str) else execution.status.value
        logger.info(
            "Step completed",
            extra={
                "run_id": run.id,
                "step_id": step.id,
                "execution_id": execution.id,
                "status": status_str,
                "cost": execution.total_cost_usd,
            },
        )

        if status_str == "failed":
            raise RuntimeError(
                f"Step '{step.id}' execution failed: "
                f"{execution.error_data}"
            )

        return execution, extracted

    def _build_step_objective(
        self,
        step: WorkflowStepSchema,
        step_input: dict[str, Any],
    ) -> str:
        """Build an objective string from the step definition and resolved input."""
        parts = [step.description or f"Execute step: {step.id}"]

        if step_input:
            context_parts = []
            for key, value in step_input.items():
                if isinstance(value, str):
                    context_parts.append(f"{key}: {value}")
                elif isinstance(value, list):
                    context_parts.append(f"{key}: {', '.join(str(v) for v in value)}")
            if context_parts:
                parts.append("Context: " + "; ".join(context_parts))

        return ". ".join(parts)

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
            wave = [
                sid for sid in remaining
                if in_degree[sid] == 0
            ]

            if not wave:
                raise RuntimeError("Dependency cycle detected in workflow steps")

            waves.append(sorted(wave))

            # Remove completed steps and update degrees
            for sid in wave:
                remaining.remove(sid)
                for dependent in dependents[sid]:
                    in_degree[dependent] -= 1

        return waves
