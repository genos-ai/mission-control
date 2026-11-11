"""
Shared plan introspection tool (extracted from Director + Supervisor).

Pure function that reads the mission plan state. Both
mission.director.agent and mission.supervisor.agent delegate
their get_plan @agent.tool wrappers here.

Same convention as tools/workflow_design.py: accepts a db session
+ structured args, returns a dict, no PydanticAI dependency.

Plan 72: reads tasks from the tasks table instead of task_plan_json.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from modules.backend.core.logging import get_logger
from modules.backend.services.mission_plan import MissionPlanService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


async def get_plan_state(
    session: AsyncSession,
    *,
    mission_id: str,
) -> dict[str, Any]:
    """Read the current mission plan with all tasks.

    Returns plan metadata, per-task status, gate_mode, budget and
    supervisor counters. Used by both Director and
    Supervisor agents.
    """
    svc = MissionPlanService(session)
    plan = await svc.get_or_create_plan(mission_id)
    tasks = await svc.get_tasks(plan.id)

    return {
        "plan_id": plan.id,
        "version": plan.version,
        "status": plan.status,
        "gate_mode": plan.gate_mode,
        "budget_usd_ceiling": plan.budget_usd_ceiling,
        "total_spent_usd": plan.total_spent_usd,
        "supervisor_iteration_count": plan.supervisor_iteration_count,
        "summary": plan.summary,
        "estimated_cost_usd": plan.estimated_cost_usd,
        "estimated_duration": plan.estimated_duration,
        "tasks": [
            {
                "task_id": t.id,
                "agent": t.agent,
                "description": t.description,
                "status": t.status,
                "retry_count": t.retry_count,
                "result_summary": t.result_summary,
                "failure_reason": t.failure_reason,
                "approved_at": str(t.approved_at) if t.approved_at else None,
                "dependencies": [d.depends_on_id for d in t.dependencies],
            }
            for t in tasks
        ],
    }
