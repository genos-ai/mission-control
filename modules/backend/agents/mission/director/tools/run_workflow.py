"""
Tool: run_workflow

Start a named workflow against the mission, forked into Temporal so the
Director returns immediately.
"""

from __future__ import annotations

from functools import partial

from pydantic_ai import RunContext

from modules.backend.agents.mission.director.deps import MissionDirectorDeps
from modules.backend.agents.mission.director.tool_helpers import run_tool
from modules.backend.agents.mission.director.tools._fork import (
    create_background_record,
    start_tool_fork_workflow,
)

_WORKFLOW_SUFFIX = ".workflow"


def strip_workflow_suffix(workflow_name: str) -> str:
    """Drop a trailing `.workflow`, which the database does not store.

    Callers and the model use both forms interchangeably, for example
    `system.platform-audit` and `system.platform-audit.workflow`.
    """
    if workflow_name.endswith(_WORKFLOW_SUFFIX):
        return workflow_name[: -len(_WORKFLOW_SUFFIX)]
    return workflow_name


async def run_workflow(
    mission_id: str,
    session_id: str,
    workflow_name: str,
    context_overrides: dict[str, str] | None = None,
) -> dict:
    """Fork a workflow run into Temporal and return its identifiers.

    Takes no session: the execution record is created through the
    persistence service's own session, so it is committed and visible to
    the worker before the workflow starts.

    Args:
        mission_id: Mission to run against.
        session_id: Transport session that requested the run (P15).
        workflow_name: Workflow identifier, with or without `.workflow`.
        context_overrides: Values merged into the workflow context.

    Returns:
        The execution record id, Temporal workflow id, resolved name and
        a message pointing at check_background_tasks.
    """
    from modules.backend.temporal.tool_fork_models import RunWorkflowInput

    clean_name = strip_workflow_suffix(workflow_name)

    record = await create_background_record(
        mission_id=mission_id,
        session_id=session_id,
        task_type="run_workflow",
        objective=f"Run workflow: {clean_name}",
        params={"workflow_name": clean_name, "context_overrides": context_overrides},
    )

    workflow_id = await start_tool_fork_workflow(
        workflow_name="RunWorkflowWorkflow",
        input_data=RunWorkflowInput(
            mission_id=mission_id,
            session_id=session_id,
            execution_record_id=record.id,
            workflow_name=clean_name,
            context_overrides=context_overrides,
        ),
        record_id=record.id,
    )

    return {
        "execution_record_id": record.id,
        "temporal_workflow_id": workflow_id,
        "workflow_name": clean_name,
        "mission_id": mission_id,
        "status": "started_in_background",
        "message": ("Workflow started in background. Check progress via check_background_tasks."),
    }


# ── Registry integration ─────────────────────────────────

_impl = run_workflow


def register(agent) -> None:
    """Register this tool on a PydanticAI agent."""

    @agent.tool
    async def run_workflow(
        ctx: RunContext[MissionDirectorDeps],
        workflow_name: str,
        context_overrides: dict[str, str] | None = None,
    ) -> str:
        """Start a named workflow against the current mission.

        Creates an execution record and starts a durable Temporal workflow
        in the background. Returns immediately — use check_background_tasks
        to check progress.

        Resolves workflow_name against mission-scoped workflows first,
        then system templates. Strips '.workflow' suffix if present.

        Args:
            workflow_name: The workflow identifier (e.g., "security.webapp-assessment"
                          or "system.platform-audit.workflow").
            context_overrides: Optional key-value pairs merged into the workflow
                              context before execution (e.g., {"target_path": "/path/to/code"}).
        """
        return await run_tool(
            ctx,
            "run_workflow",
            partial(
                _impl,
                ctx.deps.mission_id,
                ctx.deps.session_id,
                workflow_name,
                context_overrides,
            ),
        )
