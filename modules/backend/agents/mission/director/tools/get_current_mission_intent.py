"""
Tool: get_current_mission_intent

Read back the mission's current intent and scope.
"""

from __future__ import annotations

from pydantic_ai import RunContext

from modules.backend.agents.mission.director.deps import MissionDirectorDeps


async def get_current_mission_intent(mission_id: str) -> str:
    """Restate the mission's current intent and scope.

    Args:
        mission_id: Mission whose intent to read.

    Returns:
        The adapter's own formatted summary, passed through unchanged.
    """
    from modules.backend.agents.adapters.intent import restate_current_intent

    return await restate_current_intent(mission_id)


# ── Registry integration ─────────────────────────────────

_impl = get_current_mission_intent


def register(agent) -> None:
    """Register this tool on a PydanticAI agent.

    Does not use `run_tool`, for the same reasons as
    capture_mission_intent: the adapter returns a formatted string and
    this tool had no session guard or error handling before extraction.
    """

    @agent.tool
    async def get_current_mission_intent(
        ctx: RunContext[MissionDirectorDeps],
    ) -> str:
        """Retrieve the current mission intent and scope."""
        return await _impl(ctx.deps.mission_id)
