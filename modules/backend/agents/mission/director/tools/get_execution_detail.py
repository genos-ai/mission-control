"""
Tool: get_execution_detail

Full detail for one execution record, including task results.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from pydantic_ai import RunContext

from modules.backend.agents.mission.director.deps import MissionDirectorDeps
from modules.backend.agents.mission.director.tool_helpers import ToolRefusal, run_tool

# Guarded so the agent layer does not import sqlalchemy at runtime (rule 011.1).
if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _as_detail(record) -> dict:
    """Shape one execution record for the model."""
    return {
        "id": str(record.id),
        "objective": record.objective_statement,
        # status may be the enum or an already-coerced string.
        "status": (record.status.value if hasattr(record.status, "value") else str(record.status)),
        "roster_name": record.roster_name,
        "total_cost_usd": record.total_cost_usd,
        "cost_ceiling_usd": record.cost_ceiling_usd,
        "started_at": str(record.started_at) if record.started_at else None,
        "completed_at": str(record.completed_at) if record.completed_at else None,
        "execution_outcome": record.execution_outcome_json,
        "workflow_run_id": record.workflow_run_id,
        "workflow_step_id": record.workflow_step_id,
    }


async def get_execution_detail(db_session: AsyncSession, execution_id: str) -> dict:
    """Read one execution record in full.

    Args:
        db_session: Active async session.
        execution_id: UUID of the execution to inspect.

    Returns:
        The record's identity, objective, status, cost and outcome.

    Raises:
        ToolRefusal: No execution exists with that id.
    """
    from modules.backend.services.execution_persistence import ExecutionPersistenceService

    record = await ExecutionPersistenceService(db_session).get_execution(execution_id)
    if not record:
        raise ToolRefusal(f"Execution '{execution_id}' not found")
    return _as_detail(record)


# ── Registry integration ─────────────────────────────────

_impl = get_execution_detail


def register(agent) -> None:
    """Register this tool on a PydanticAI agent."""

    @agent.tool
    async def get_execution_detail(
        ctx: RunContext[MissionDirectorDeps],
        execution_id: str,
    ) -> str:
        """Get full detail for a specific execution including task results.

        Args:
            execution_id: The UUID of the execution to inspect.
        """
        return await run_tool(
            ctx,
            "get_execution_detail",
            partial(_impl, ctx.deps.db_session, execution_id),
        )
