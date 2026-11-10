"""
Tool: design_workflow

Delegate workflow design to the Workflow Architect, forked into Temporal
so the Director returns immediately.
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


async def design_workflow(
    mission_id: str,
    session_id: str,
    name: str,
    description: str,
    instructions: str,
) -> dict:
    """Fork a workflow design run into Temporal and return its identifiers.

    Takes no session for the same reason as run_workflow: the execution
    record is created and committed through the persistence service's own
    session before the worker picks the workflow up.

    Args:
        mission_id: Mission the workflow is being designed for.
        session_id: Transport session that requested it (P15).
        name: Workflow name, for example "ops.health-check".
        description: What the workflow does.
        instructions: Detailed brief for the Architect.

    Returns:
        The execution record id, Temporal workflow id, name and a message
        pointing at check_background_tasks.
    """
    from modules.backend.temporal.config_snapshots import (
        build_workflow_timeouts_snapshot,
    )
    from modules.backend.temporal.tool_fork_models import DesignWorkflowInput

    record = await create_background_record(
        mission_id=mission_id,
        session_id=session_id,
        task_type="design_workflow",
        objective=f"Design workflow: {name}",
        params={"name": name, "description": description, "instructions": instructions},
    )

    workflow_id = await start_tool_fork_workflow(
        workflow_name="DesignWorkflowWorkflow",
        input_data=DesignWorkflowInput(
            mission_id=mission_id,
            session_id=session_id,
            execution_record_id=record.id,
            workflow_name=name,
            description=description,
            instructions=instructions,
            timeouts=build_workflow_timeouts_snapshot(),
        ),
        record_id=record.id,
    )

    return {
        "execution_record_id": record.id,
        "temporal_workflow_id": workflow_id,
        "status": "started_in_background",
        "workflow_name": name,
        "message": f"The Workflow Architect is designing '{name}'. "
        "You'll see progress in the stream tab. "
        "Use check_background_tasks to check completion.",
    }


# ── Registry integration ─────────────────────────────────

_impl = design_workflow


def register(agent) -> None:
    """Register this tool on a PydanticAI agent."""

    @agent.tool
    async def design_workflow(
        ctx: RunContext[MissionDirectorDeps],
        name: str,
        description: str,
        instructions: str,
    ) -> str:
        """Delegate workflow design to the Workflow Architect agent.

        Starts the Architect in a durable Temporal workflow and returns
        immediately. The user sees progress in the stream tab. Use
        check_background_tasks to check completion.

        Args:
            name: Workflow name (e.g. 'ops.health-check').
            description: What the workflow does.
            instructions: Detailed instructions for the architect — what
                agents to use, what steps to include, what to check.
        """
        return await run_tool(
            ctx,
            "design_workflow",
            partial(
                _impl,
                ctx.deps.mission_id,
                ctx.deps.session_id,
                name,
                description,
                instructions,
            ),
        )
