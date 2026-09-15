"""
Tool: get_mission_context

Read the Mission Context Document (MCD), the mission's strategic context.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from pydantic_ai import RunContext

from modules.backend.agents.mission.director.deps import MissionDirectorDeps
from modules.backend.agents.mission.director.tool_helpers import CompactResult, run_tool

# Guarded so the agent layer does not import sqlalchemy at runtime (rule 011.1).
if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_NO_CONTEXT_MESSAGE = "No mission context document found."


async def get_mission_context(db_session: AsyncSession, mission_id: str) -> dict | CompactResult:
    """Read the mission's context document.

    Args:
        db_session: Active async session.
        mission_id: Mission whose context to read.

    Returns:
        The context document, or a `CompactResult` carrying a message when
        the mission has none. Absence is not an error, so it is reported
        under `message` rather than `error`.
    """
    from modules.backend.services.mission_context import MissionContextManager

    context = await MissionContextManager(db_session).get_context(mission_id)
    if not context:
        return CompactResult({"message": _NO_CONTEXT_MESSAGE})
    return context


# ── Registry integration ─────────────────────────────────

_impl = get_mission_context


def register(agent) -> None:
    """Register this tool on a PydanticAI agent."""

    @agent.tool
    async def get_mission_context(ctx: RunContext[MissionDirectorDeps]) -> str:
        """Get the Mission Context Document (MCD) -- strategic context for the mission."""
        return await run_tool(
            ctx,
            "get_mission_context",
            partial(_impl, ctx.deps.db_session, ctx.deps.mission_id),
        )
