"""
Tool: get_execution_history

Recent runs for the mission: status, cost, objective, timestamps.
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


async def get_execution_history(
    db_session: AsyncSession,
    mission_id: str,
    limit: int = 10,
) -> dict:
    """Read recent runs, persisted and in-flight, as one list.

    Args:
        db_session: Active async session.
        mission_id: Mission whose runs to read.
        limit: Maximum runs to return.

    Returns:
        The runs and the total available.
    """
    from modules.backend.services.execution_persistence import ExecutionPersistenceService

    runs, total = await ExecutionPersistenceService(db_session).list_all_runs(
        mission_id=mission_id,
        limit=limit,
    )
    return {"executions": runs, "total": total}


# ── Registry integration ─────────────────────────────────

_impl = get_execution_history


def register(agent) -> None:
    """Register this tool on a PydanticAI agent."""

    @agent.tool
    async def get_execution_history(
        ctx: RunContext[MissionDirectorDeps],
        limit: int = 10,
    ) -> str:
        """Get recent execution history: status, cost, objective, timestamps.

        Queries both execution_records (plan dispatches, research, workflows)
        and live in-flight executions for a unified view of all runs.

        Args:
            limit: Maximum number of executions to return (default 10).
        """
        return await run_tool(
            ctx,
            "get_execution_history",
            partial(_impl, ctx.deps.db_session, ctx.deps.mission_id, limit),
        )
