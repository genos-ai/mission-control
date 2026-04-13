"""
Scheduled workflow activities (Plan 52 Phase D).

Activities for the ScheduledMissionCheckWorkflow. One activity:
find_ready_plans — queries the DB for missions with approved tasks
in autonomous/off gate_mode, same logic as MissionPlanDaemon's
_find_ready_plan_ids but as a Temporal Activity.
"""

from temporalio import activity

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


@activity.defn
async def find_ready_plans() -> list[dict]:
    """Find mission plans with approved tasks ready to dispatch.

    Returns a list of dicts with plan_id, mission_id, brief, budget,
    gate_mode, roster — the minimum info needed to start a
    MissionRunWorkflow.

    Mirrors the query logic from MissionPlanDaemon._find_ready_plan_ids
    but returns richer data so the workflow can start child workflows
    without additional DB queries.
    """
    from sqlalchemy import and_, func, or_, select

    from modules.backend.core.database import get_async_session
    from modules.backend.models.mission import Mission
    from modules.backend.models.mission_plan import (
        MissionPlan,
        MissionPlanStatus,
        PlanTaskState,
        PlanTaskStatus,
    )

    async with get_async_session() as db:
        # Find plans that have at least one approved task and are in
        # autonomous or off gate_mode with active status.
        approved_count = (
            select(func.count())
            .where(
                PlanTaskState.mission_plan_id == MissionPlan.id,
                PlanTaskState.status == PlanTaskStatus.APPROVED.value,
            )
            .correlate(MissionPlan)
            .scalar_subquery()
        )

        stmt = (
            select(MissionPlan, Mission)
            .join(Mission, MissionPlan.mission_id == Mission.id)
            .where(
                # Only dispatch for active missions — paused/archived skip
                Mission.status == "active",
                MissionPlan.status == MissionPlanStatus.ACTIVE.value,
                or_(
                    MissionPlan.gate_mode == "autonomous",
                    MissionPlan.gate_mode == "off",
                    MissionPlan.gate_mode.is_(None),
                ),
                approved_count > 0,
            )
        )

        # Budget filter: exclude plans where total_spent >= ceiling
        stmt = stmt.where(
            or_(
                MissionPlan.budget_usd_ceiling.is_(None),
                MissionPlan.total_spent_usd < MissionPlan.budget_usd_ceiling,
            )
        )

        result = await db.execute(stmt)
        rows = result.all()

    plans = []
    for plan, mission in rows:
        plans.append({
            "plan_id": plan.id,
            "mission_id": plan.mission_id,
            "brief": mission.brief or mission.description or "",
            "budget": plan.budget_usd_ceiling or 10.0,
            "gate_mode": plan.gate_mode or "autonomous",
            "roster": mission.default_roster or "default",
            "session_id": plan.id,  # Use plan ID as session reference
        })

    if plans:
        activity.logger.info(
            "Found ready plans",
            extra={"count": len(plans), "plan_ids": [p["plan_id"] for p in plans]},
        )

    return plans
