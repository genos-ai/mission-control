"""
Tool: list_workflows

List the workflows available to the mission: its own, plus system
templates it has not overridden.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from pydantic_ai import RunContext

from modules.backend.agents.mission.director.deps import MissionDirectorDeps
from modules.backend.agents.mission.director.tool_helpers import run_tool

# Guarded so the agent layer does not import sqlalchemy at runtime (rule 011.1).
if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _as_workflow(definition, scope: str) -> dict:
    """Shape one workflow definition for the model."""
    return {
        "name": definition.name,
        "description": definition.description,
        "version": definition.version,
        "trigger_type": definition.trigger_type,
        "step_count": definition.step_count,
        "scope": scope,
    }


def merge_with_precedence(mission_workflows: list, system_workflows: list) -> list[dict]:
    """Combine mission and system workflows, mission winning on a name clash.

    A mission may define a workflow with the same name as a system
    template in order to override it, so the system copy is dropped
    rather than listed twice.

    Args:
        mission_workflows: Definitions scoped to the mission.
        system_workflows: System-wide templates.

    Returns:
        Mission workflows first, then the system templates not shadowed.
    """
    results = [_as_workflow(wf, "mission") for wf in mission_workflows]
    mission_names = {wf.name for wf in mission_workflows}
    results.extend(
        _as_workflow(wf, "system") for wf in system_workflows if wf.name not in mission_names
    )
    return results


async def list_workflows(db_session: AsyncSession, mission_id: str) -> list[dict]:
    """List enabled workflows visible to the mission.

    Args:
        db_session: Active async session.
        mission_id: Mission whose workflows to list.

    Returns:
        Mission-scoped workflows followed by un-shadowed system templates.
    """
    from modules.backend.services.workflow_definition import WorkflowDefinitionService

    svc = WorkflowDefinitionService(db_session)
    mission_wfs = await svc.list_workflows(mission_id, enabled_only=True)
    system_wfs = await svc.list_workflows(None, enabled_only=True)
    return merge_with_precedence(mission_wfs, system_wfs)


# ── Registry integration ─────────────────────────────────

_impl = list_workflows


def register(agent) -> None:
    """Register this tool on a PydanticAI agent."""

    @agent.tool
    async def list_workflows(ctx: RunContext[MissionDirectorDeps]) -> str:
        """List available workflows (mission-scoped + system templates)."""
        return await run_tool(
            ctx,
            "list_workflows",
            partial(_impl, ctx.deps.db_session, ctx.deps.mission_id),
        )
