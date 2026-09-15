"""
Tool: list_team

List the agents on the mission team with capabilities, tools and scope.
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


async def list_team(db_session: AsyncSession, mission_id: str) -> list:
    """Read the mission's full team roster.

    Args:
        db_session: Active async session.
        mission_id: Mission whose team to list.

    Returns:
        One entry per team member, with capabilities, tools and scope.
    """
    from modules.backend.services.mission_team import MissionTeamService

    return await MissionTeamService(db_session).list_team_full(mission_id)


# ── Registry integration ─────────────────────────────────

_impl = list_team


def register(agent) -> None:
    """Register this tool on a PydanticAI agent."""

    @agent.tool
    async def list_team(ctx: RunContext[MissionDirectorDeps]) -> str:
        """List all agents on the mission team with their capabilities, tools, and access scope."""
        return await run_tool(
            ctx,
            "list_team",
            partial(_impl, ctx.deps.db_session, ctx.deps.mission_id),
        )
