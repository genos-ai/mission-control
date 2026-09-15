"""
Tool: get_mission_info

Read the mission's own details: name, description, brief, gate mode, budget.
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


async def get_mission_info(db_session: AsyncSession, mission_id: str) -> dict:
    """Read a mission's descriptive and governance fields.

    Args:
        db_session: Active async session.
        mission_id: Mission to read.

    Returns:
        Name, description, brief, status, gate mode, budget ceiling, owner
        and creation time.
    """
    from modules.backend.services.mission import MissionService

    mission = await MissionService(db_session).get_mission(mission_id)

    return {
        "name": mission.name,
        "description": mission.description,
        "brief": mission.brief,
        # status may be the enum or an already-coerced string.
        "status": (mission.status if isinstance(mission.status, str) else mission.status.value),
        "gate_mode": mission.gate_mode,
        "budget_ceiling_usd": mission.budget_ceiling_usd,
        "owner_id": mission.owner_id,
        "created_at": str(mission.created_at),
    }


# ── Registry integration ─────────────────────────────────

_impl = get_mission_info


def register(agent) -> None:
    """Register this tool on a PydanticAI agent."""

    @agent.tool
    async def get_mission_info(ctx: RunContext[MissionDirectorDeps]) -> str:
        """Get current mission details: name, description, brief, gate mode, budget."""
        return await run_tool(
            ctx,
            "get_mission_info",
            partial(_impl, ctx.deps.db_session, ctx.deps.mission_id),
        )
