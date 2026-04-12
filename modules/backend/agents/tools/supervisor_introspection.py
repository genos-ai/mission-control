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

import json
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


# get_plan extracted to agents/tools/plan_introspection.py (shared
# with Director). Re-export for backwards compatibility.
from modules.backend.agents.tools.plan_introspection import get_plan_state as get_plan  # noqa: F401


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
    from modules.backend.models.execution_record import ExecutionRecord

    stmt = (
        select(ExecutionRecord)
        .where(ExecutionRecord.mission_id == mission_id)
        .order_by(ExecutionRecord.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())

    return [
        {
            "execution_record_id": r.id,
            "status": r.status if isinstance(r.status, str) else r.status.value,
            "total_cost_usd": r.total_cost_usd,
            "completed_task_count": getattr(r, "completed_task_count", 0),
            "failed_task_count": getattr(r, "failed_task_count", 0),
            "started_at": r.started_at,
            "completed_at": r.completed_at,
            "created_at": str(r.created_at),
        }
        for r in rows
    ]


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
    from modules.backend.models.execution_record import (
        DecisionType,
        ExecutionDecision,
        ExecutionRecord,
    )

    stmt = (
        select(ExecutionDecision)
        .join(
            ExecutionRecord,
            ExecutionDecision.execution_record_id == ExecutionRecord.id,
        )
        .where(
            and_(
                ExecutionRecord.mission_id == mission_id,
                ExecutionDecision.decision_type == DecisionType.POST_RUN_SUPERVISOR.value,
            )
        )
        .order_by(ExecutionDecision.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())

    decisions = []
    for row in rows:
        reasoning = row.reasoning or ""
        # Split human-readable prefix from JSON tail (marked with __META__ prefix)
        meta: dict[str, Any] = {}
        if "__META__" in reasoning:
            human_text, raw_meta = reasoning.split("__META__", 1)
            human_text = human_text.strip()
            try:
                meta = json.loads(raw_meta)
            except (json.JSONDecodeError, ValueError):
                pass
        else:
            human_text = reasoning.strip()

        decisions.append({
            "decision_id": row.id,
            "execution_record_id": row.execution_record_id,
            "action": meta.get("action", "unknown"),
            "rule": meta.get("rule", "unknown"),
            "reviewer": meta.get("reviewer", "unknown"),
            "reason": human_text,
            "model_metadata": meta.get("model_metadata"),
            "created_at": str(row.created_at),
        })

    return decisions
