"""
WorkflowRun Service (Orchestrator).

Executes a workflow end-to-end: creates a WorkflowRun record, resolves
steps into missions, dispatches them in dependency order, chains outputs
between steps, and tracks aggregate cost.

Steps within the same wave (no mutual dependencies) execute in parallel,
each with its own DB session to avoid SQLAlchemy async flush conflicts.

This is the bridge between the stateless WorkflowService (YAML loading)
and the stateful MissionService (mission lifecycle).
"""

import asyncio
from collections import defaultdict
from contextlib import AbstractAsyncContextManager
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config import get_app_config
from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now
from modules.backend.models.mission import WorkflowRun, WorkflowRunState
from modules.backend.repositories.workflow_run import WorkflowRunRepository
from modules.backend.schemas.workflow import WorkflowSchema, WorkflowStepSchema
from modules.backend.services.base import BaseService
from modules.backend.services.mission import MissionService
from modules.backend.services.workflow import WorkflowService

# Factory that returns an async context manager yielding a MissionService.
# Default implementation: MissionService.factory
MissionServiceFactory = Callable[[], AbstractAsyncContextManager[MissionService]]

logger = get_logger(__name__)


class WorkflowRunService(BaseService):
    """Orchestrates workflow execution."""

    def __init__(
        self,
        session: AsyncSession,
        mission_service_factory: MissionServiceFactory | None = None,
        workflow_service: WorkflowService | None = None,
    ) -> None:
        super().__init__(session)
        self._run_repo = WorkflowRunRepository(session)
        self._mission_service_factory = mission_service_factory
        self._workflow_service = workflow_service or WorkflowService()

    async def run_workflow(
        self,
        workflow_name: str,
        triggered_by: str = "user:cli",
        context_overrides: dict[str, Any] | None = None,
        on_progress: Any | None = None,
        project_name: str | None = None,
        gate: object | None = None,
    ) -> WorkflowRun:
        """Execute a workflow end-to-end.

        1. Load and validate the workflow YAML
        2. Create a WorkflowRun record (PENDING -> RUNNING)
        3. Topologically sort steps by dependencies
        4. Execute steps in waves (parallel within each wave)
        5. Chain outputs between steps via output_mapping
        6. Update WorkflowRun with final status and cost
        """
        # Load workflow
        workflow = self._workflow_service.get_workflow(workflow_name)
        if not workflow:
            raise ValueError(f"Workflow '{workflow_name}' not found")
        if not workflow.enabled:
            raise ValueError(f"Workflow '{workflow_name}' is disabled")

        # Validate capabilities resolve to real agents
        errors = self._workflow_service.validate_workflow_capabilities(workflow)
        if errors:
            raise ValueError(
                f"Workflow capability errors: {'; '.join(errors)}"
            )

        # Resolve project by name (get-or-create)
        if not project_name:
            raise ValueError(
                "Project name is required. Use --project <name> to specify "
                "the target project."
            )

        project_id = await self._resolve_project(project_name, workflow)

        # Create session for the workflow run
        from modules.backend.services.session import SessionService
        from modules.backend.schemas.session import SessionCreate

        session_service = SessionService(self._session)
        session = await session_service.create_session(
            SessionCreate(
                agent_id=None,
                goal=f"Workflow: {workflow.description[:200]}",
            ),
        )

        # Create WorkflowRun record
        run = WorkflowRun(
            playbook_name=workflow.workflow_name,
            playbook_version=workflow.version,
            status=WorkflowRunState.RUNNING,
            session_id=session.id,
            trigger_type=workflow.trigger.type,
            triggered_by=triggered_by,
            context=dict(workflow.context),
            total_cost_usd=0.0,
            budget_usd=workflow.budget.max_cost_usd,
            started_at=utc_now().isoformat(),
            project_id=project_id,
        )
        if context_overrides:
            run.context.update(context_overrides)

        self._session.add(run)
        await self._session.flush()
        await self._session.refresh(run)

        logger.info(
            "Workflow run started",
            extra={
                "run_id": run.id,
                "workflow": workflow_name,
                "version": workflow.version,
                "steps": len(workflow.steps),
                "budget_usd": run.budget_usd,
            },
        )

        try:
            await self._execute_steps(run, workflow, session.id, on_progress, gate=gate)

            run.status = WorkflowRunState.COMPLETED
            run.completed_at = utc_now().isoformat()
            run.result_summary = (
                f"Workflow completed: {len(workflow.steps)} steps, "
                f"${run.total_cost_usd:.4f}"
            )

        except (RuntimeError, ValueError, OSError) as e:
            run.status = WorkflowRunState.FAILED
            run.completed_at = utc_now().isoformat()
            run.error_data = {"message": str(e), "type": type(e).__name__}
            run.result_summary = f"Workflow failed: {e}"
            logger.error(
                "Workflow run failed",
                extra={"run_id": run.id, "error": str(e)},
            )

        await self._session.flush()

        logger.info(
            "Workflow run finished",
            extra={
                "run_id": run.id,
                "status": run.status,
                "cost": run.total_cost_usd,
            },
        )

        return run

    async def _resolve_project(
        self,
        project_name: str,
        workflow: WorkflowSchema,
    ) -> str:
        """Resolve a project name to a UUID, creating the project if needed.

        Returns the project UUID.
        """
        from modules.backend.services.project import ProjectService

        project_service = ProjectService(self._session)
        project = await project_service.get_project_by_name(project_name)

        if project:
            return project.id

        # Auto-create project from name
        project = await project_service.create_project(
            name=project_name,
            description=f"Auto-created for workflow: {workflow.description[:200]}",
            owner_id="system:workflow",
        )
        # Commit so parallel step sessions can see the project
        await self._session.commit()
        logger.info(
            "Auto-created project",
            extra={"project_name": project_name, "project_id": project.id},
        )
        return project.id

    async def list_runs(
        self,
        playbook_name: str | None = None,
        limit: int = 20,
    ) -> tuple[list[WorkflowRun], int]:
        """List workflow runs."""
        return await self._run_repo.list_runs(
            playbook_name=playbook_name,
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
        (via mission_service_factory) to avoid SQLAlchemy flush conflicts.
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
            for step, (mission, extracted_outputs) in zip(wave_steps, results):
                completed_outcomes[step.id] = extracted_outputs
                run.total_cost_usd += mission.total_cost_usd
                status_str = mission.status if isinstance(mission.status, str) else mission.status.value
                _emit({
                    "type": "step_done",
                    "step_id": step.id,
                    "status": status_str,
                    "cost_usd": mission.total_cost_usd,
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
        if self._mission_service_factory is None:
            raise RuntimeError(
                "mission_service_factory is required to execute workflows"
            )

        async def _run_step(step: WorkflowStepSchema) -> tuple[Any, dict]:
            async with self._mission_service_factory() as mission_service:
                return await self._execute_step(
                    run, step, session_id, completed_outcomes,
                    mission_service, gate=gate,
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
        mission_service: MissionService,
        gate: object | None = None,
    ) -> tuple[Any, dict]:
        """Execute a single workflow step as a mission."""
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

        # Create mission from workflow step
        mission = await mission_service.create_mission_from_step(
            playbook_run_id=run.id,
            step_id=step.id,
            objective=objective,
            roster_ref=step.roster,
            complexity_tier=step.complexity_tier,
            cost_ceiling_usd=cost_ceiling,
            upstream_context=upstream,
            session_id=session_id,
            project_id=run.project_id,
        )

        logger.info(
            "Step mission created",
            extra={
                "run_id": run.id,
                "step_id": step.id,
                "mission_id": mission.id,
                "agent": f"{step.capability}.agent",
            },
        )

        # Execute the mission
        mission = await mission_service.execute_mission(mission.id, gate=gate)

        # Extract outputs for downstream steps
        output_mapping = (
            step.output_mapping.model_dump()
            if step.output_mapping
            else None
        )
        extracted = mission_service.extract_outputs(
            mission, output_mapping,
        )

        status_str = mission.status if isinstance(mission.status, str) else mission.status.value
        logger.info(
            "Step completed",
            extra={
                "run_id": run.id,
                "step_id": step.id,
                "mission_id": mission.id,
                "status": status_str,
                "cost": mission.total_cost_usd,
            },
        )

        if status_str == "failed":
            raise RuntimeError(
                f"Step '{step.id}' mission failed: "
                f"{mission.error_data}"
            )

        return mission, extracted

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
