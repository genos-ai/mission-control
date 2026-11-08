"""
Scheduled workflow activities (Plan 52 Phase D).

Activities for the ScheduledMissionCheckWorkflow. One activity:
find_ready_plans — queries the DB for missions with approved tasks
in autonomous gate_mode, same logic as MissionPlanDaemon's
_find_ready_plan_ids but as a Temporal Activity.
"""

from temporalio import activity

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


@activity.defn
async def find_ready_plans() -> list[dict]:
    """Find mission plans with approved tasks ready to dispatch.

    Returns a list of dicts with plan_id, mission_id, brief, budget_remaining_usd,
    gate_mode, roster — the minimum info needed to start a
    MissionRunWorkflow.

    Mirrors the query logic from MissionPlanDaemon._find_ready_plan_ids
    but returns richer data so the workflow can start child workflows
    without additional DB queries.
    """
    from sqlalchemy import exists, func, select

    from modules.backend.core.database import get_async_session
    from modules.backend.models.mission import Mission, MissionStatus
    from modules.backend.models.mission_plan import (
        MissionPlan,
        MissionPlanStatus,
        resolve_gate_mode,
    )
    from modules.backend.models.task import Task, TaskStatus
    from modules.backend.models.workflow_run import WorkflowRun, WorkflowRunState
    from modules.backend.services.mission_plan import remaining_plan_budget_usd

    async with get_async_session() as db:
        # Find plans that have at least one approved task and are in
        # autonomous gate_mode (or unset) with active status.
        approved_count = (
            select(func.count())
            .where(
                Task.plan_id == MissionPlan.id,
                Task.status == TaskStatus.APPROVED,
            )
            .correlate(MissionPlan)
            .scalar_subquery()
        )

        stmt = (
            select(MissionPlan, Mission)
            .join(Mission, MissionPlan.mission_id == Mission.id)
            .where(
                # Only dispatch for active missions — paused/archived skip
                Mission.status == MissionStatus.ACTIVE,
                MissionPlan.status == MissionPlanStatus.ACTIVE,
                MissionPlan.gate_mode == "autonomous",
                approved_count > 0,
                # A workflow run owns the tasks of its mission while active.
                ~exists(
                    select(WorkflowRun.id).where(
                        WorkflowRun.mission_id == Mission.id,
                        WorkflowRun.status.in_(
                            [
                                WorkflowRunState.PENDING,
                                WorkflowRunState.RUNNING,
                                WorkflowRunState.AWAITING_INPUT,
                            ]
                        ),
                    )
                ),
            )
        )

        result = await db.execute(stmt)
        rows = result.all()

    plans = []
    for plan, mission in rows:
        remaining = remaining_plan_budget_usd(plan)
        if remaining <= 0:
            continue
        plans.append(
            {
                "plan_id": plan.id,
                "mission_id": plan.mission_id,
                "brief": mission.brief or mission.description or "",
                "budget_remaining_usd": remaining,
                "gate_mode": resolve_gate_mode(plan.gate_mode),
                "roster": mission.default_roster or "default",
                "owner_id": mission.owner_id,
            }
        )

    if plans:
        activity.logger.info(
            "Found ready plans",
            extra={"count": len(plans), "plan_ids": [p["plan_id"] for p in plans]},
        )

    return plans
