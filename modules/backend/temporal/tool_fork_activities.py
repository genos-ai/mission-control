"""
Tool fork activities (Plan 56 Phase B).

Activities for workflows that handle Director tool calls forked to Temporal:
- execute_design_workflow: Runs the Workflow Architect agent
- execute_run_objective: Runs an ad-hoc execution
- execute_run_workflow: Runs a named workflow
- update_execution_record_status: Updates the ExecutionRecord lifecycle

Each activity opens its own DB session and commits independently.
"""

from temporalio import activity

from modules.backend.core.logging import get_logger
from modules.backend.temporal.tool_fork_models import (
    DesignWorkflowInput,
    RunObjectiveInput,
    RunWorkflowInput,
    ToolForkResult,
)

logger = get_logger(__name__)


@activity.defn
async def update_execution_record_status(
    execution_record_id: str,
    status: str,
    error: str | None = None,
) -> None:
    """Update an ExecutionRecord's status. Used at start and end of forked work."""
    from modules.backend.core.database import get_async_session
    from modules.backend.core.utils import utc_now
    from modules.backend.models.execution_record import ExecutionRecord

    from sqlalchemy import select

    async with get_async_session() as db:
        result = await db.execute(
            select(ExecutionRecord).where(ExecutionRecord.id == execution_record_id)
        )
        record = result.scalar_one_or_none()
        if record is not None:
            record.status = status
            if status == "running" and record.started_at is None:
                record.started_at = utc_now()
            if status in ("completed", "failed", "cancelled"):
                record.completed_at = utc_now()
            await db.commit()

    activity.logger.info(
        "ExecutionRecord status updated",
        extra={"execution_record_id": execution_record_id, "status": status},
    )


@activity.defn
async def execute_design_workflow(input: DesignWorkflowInput) -> ToolForkResult:
    """Run the Workflow Architect agent to design a workflow.

    This is the actual heavy work — runs the architect agent with tool calls
    (browse_catalog, validate_workflow, save_workflow). Can take 30+ seconds.
    """
    activity.logger.info(
        "Designing workflow",
        extra={
            "mission_id": input.mission_id,
            "workflow_name": input.workflow_name,
        },
    )

    try:
        from modules.backend.agents.mission_control.helpers import (
            _build_model,
            assemble_instructions,
        )
        from modules.backend.agents.mission_control.registry import get_registry
        from modules.backend.agents.mission.workflow.deps import ArchitectAgentDeps
        from modules.backend.agents.deps.base import FileScope
        from modules.backend.core.config import find_project_root
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            registry = get_registry()
            agent_config = registry.get("mission.workflow.agent")
            model = _build_model(agent_config.model)
            architect = registry.get_instance("mission.workflow.agent", model)

            scope = FileScope(
                read_paths=agent_config.scope.read,
                write_paths=agent_config.scope.write,
            )
            deps = ArchitectAgentDeps(
                project_root=find_project_root(),
                scope=scope,
                config=agent_config,
                session_id=input.session_id,
                mission_id=input.mission_id,
                db_session=db,
            )

            prompt = (
                f"Design and save a workflow with these specifications:\n\n"
                f"Name: {input.workflow_name}\n"
                f"Description: {input.description}\n\n"
                f"Instructions:\n{input.instructions}\n\n"
                f"Use browse_catalog to check available agents, then "
                f"design the steps, validate with validate_workflow, "
                f"and save with save_workflow. Do NOT ask for confirmation — "
                f"the user already confirmed by requesting this."
            )

            result = await architect.run(prompt, deps=deps)
            await db.commit()

        return ToolForkResult(
            execution_record_id=input.execution_record_id,
            status="completed",
            summary=str(result.output)[:500],
            cost_usd=result.usage().total_tokens * 0.00001 if result.usage() else 0.0,
        )
    except Exception as e:
        activity.logger.error(
            "execute_design_workflow failed",
            extra={"mission_id": input.mission_id, "error": str(e)},
            exc_info=True,
        )
        return ToolForkResult(
            execution_record_id=input.execution_record_id,
            status="failed",
            error=str(e)[:500],
        )


@activity.defn
async def execute_run_objective(input: RunObjectiveInput) -> ToolForkResult:
    """Run an ad-hoc execution objective via ExecutionService."""
    activity.logger.info(
        "Running objective",
        extra={
            "mission_id": input.mission_id,
            "objective": input.objective[:100],
        },
    )

    try:
        from modules.backend.services.execution import ExecutionService

        async with ExecutionService.factory() as svc:
            execution = await svc.create_adhoc_execution(
                objective=input.objective,
                triggered_by="mission_director",
                cost_ceiling_usd=input.budget_usd,
                mission_id=input.mission_id,
            )
            execution_id = str(execution.id)

        async with ExecutionService.factory() as svc:
            await svc.run_execution(execution_id)

        return ToolForkResult(
            execution_record_id=input.execution_record_id,
            status="completed",
            summary=f"Execution {execution_id} completed",
        )
    except Exception as e:
        activity.logger.error(
            "execute_run_objective failed",
            extra={"mission_id": input.mission_id, "error": str(e)},
            exc_info=True,
        )
        return ToolForkResult(
            execution_record_id=input.execution_record_id,
            status="failed",
            error=str(e)[:500],
        )


@activity.defn
async def execute_run_workflow(input: RunWorkflowInput) -> ToolForkResult:
    """Run a named workflow via WorkflowRunService."""
    activity.logger.info(
        "Running workflow",
        extra={
            "mission_id": input.mission_id,
            "workflow_name": input.workflow_name,
        },
    )

    try:
        from modules.backend.services.workflow_run import WorkflowRunService

        async with WorkflowRunService.factory() as svc:
            await svc.run_workflow(
                workflow_name=input.workflow_name,
                triggered_by="mission_director",
                mission_id=input.mission_id,
            )

        return ToolForkResult(
            execution_record_id=input.execution_record_id,
            status="completed",
            summary=f"Workflow {input.workflow_name} completed",
        )
    except Exception as e:
        activity.logger.error(
            "execute_run_workflow failed",
            extra={"mission_id": input.mission_id, "error": str(e)},
            exc_info=True,
        )
        return ToolForkResult(
            execution_record_id=input.execution_record_id,
            status="failed",
            error=str(e)[:500],
        )
