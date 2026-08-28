"""
Supervisor introspection tools (Plan 51 Phase D).

Pure functions for the supervisor agent's read-only tools. The
agent's PydanticAI @agent.tool wrappers live in
agents/mission/supervisor/agent.py and delegate here.

Three tools:
- get_plan — reads mission plan state (duplicates Director's tool
  body for v1; future DRY pass can extract to shared module)
- get_recent_run_outcomes — reads last N execution records
- get_past_decisions — reads post_run_supervisor decision rows

Same convention as tools/workflow_design.py: accept db session +
structured args, return dict, no PydanticAI dependency.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# get_plan extracted to agents/adapters/plan_introspection.py (shared
# with Director). Re-export for backwards compatibility.
from modules.backend.agents.adapters.plan_introspection import (  # noqa: F401
    get_plan_state as get_plan,
)
from modules.backend.services.execution_persistence import ExecutionPersistenceService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def get_recent_run_outcomes(
    session: AsyncSession,
    *,
    mission_id: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Read the last N execution records for a mission.

    Returns a list of dicts with run metadata, task counts, cost,
    and status. Used by the supervisor's chat mode to answer "what
    happened in the last few waves?" and by the decision matrix to
    feed GateContext.recent_run_outcomes.
    """
    svc = ExecutionPersistenceService(session)
    return await svc.list_recent_run_outcomes(mission_id, limit=limit)


async def get_past_decisions(
    session: AsyncSession,
    *,
    mission_id: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Read post_run_supervisor decisions for a mission.

    Queries execution_decisions joined through execution_records to
    filter by mission_id. Returns the human-readable prefix and the
    structured JSON tail from the reasoning field.
    """
    svc = ExecutionPersistenceService(session)
    return await svc.list_past_decisions(mission_id, limit=limit)
