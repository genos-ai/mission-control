"""
Shared plan introspection tool (extracted from Director + Supervisor).

Pure function that reads the mission plan state. Both
mission.director.agent and mission.supervisor.agent delegate
their get_plan @agent.tool wrappers here.

Same convention as tools/workflow_design.py: accepts a db session
+ structured args, returns a dict, no PydanticAI dependency.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.logging import get_logger
from modules.backend.services.mission_plan import MissionPlanService

logger = get_logger(__name__)


async def get_plan_state(
    session: AsyncSession,
    *,
    mission_id: str,
) -> dict[str, Any]:
    """Read the current mission plan with all task states.

    Returns plan body, per-task status, gate_mode, budget, veto
    window, and supervisor counters. Used by both Director and
    Supervisor agents.
    """
    svc = MissionPlanService(session)
    plan = await svc.get_or_create_plan(mission_id)
    task_states = await svc.get_task_states(plan.id)

    return {
        "plan_id": plan.id,
        "version": plan.version,
        "status": plan.status,
        "gate_mode": plan.gate_mode,
        "budget_usd_ceiling": plan.budget_usd_ceiling,
        "total_spent_usd": plan.total_spent_usd,
        "veto_window_sec": plan.veto_window_sec,
        "supervisor_iteration_count": plan.supervisor_iteration_count,
        "max_supervisor_iterations": plan.max_supervisor_iterations,
        "task_plan_json": plan.task_plan_json,
        "task_states": [
            {
                "task_id": s.task_id,
                "status": s.status,
                "retry_count": s.retry_count,
                "result_summary": s.result_summary,
                "failure_reason": s.failure_reason,
                "approved_at": str(s.approved_at) if s.approved_at else None,
            }
            for s in task_states
        ],
    }
