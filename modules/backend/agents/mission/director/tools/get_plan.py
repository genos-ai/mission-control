"""
Tool: get_plan

Read the current mission plan — body, per-task status, autonomy mode
and cumulative budget.
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


async def get_plan(db_session: AsyncSession, mission_id: str) -> dict:
    """Read the current plan state for a mission.

    Args:
        db_session: Active async session.
        mission_id: Mission whose plan to read.

    Returns:
        Plan body, per-task status, autonomy mode and cumulative budget.
        The plan is created lazily, so the task list is empty until a
        refinement has run.
    """
    from modules.backend.agents.adapters.plan_introspection import get_plan_state

    return await get_plan_state(db_session, mission_id=mission_id)


# ── Registry integration ─────────────────────────────────

_impl = get_plan


def register(agent) -> None:
    """Register this tool on a PydanticAI agent."""

    @agent.tool
    async def get_plan(ctx: RunContext[MissionDirectorDeps]) -> str:
        """Read the current mission plan — the long-lived backlog.

        Returns the plan body (TaskPlan JSON), per-task status for every
        task in the plan, the current autonomy mode, and cumulative
        budget. Use this before calling refine_plan so you can reason
        about what already exists rather than starting from scratch, and
        to answer questions like "what's in the plan?" or "what tasks
        are approved?"

        The plan is created lazily — if no refinement has happened yet,
        the tasks relationship will be empty.
        """
        return await run_tool(
            ctx,
            "get_plan",
            partial(_impl, ctx.deps.db_session, ctx.deps.mission_id),
        )
