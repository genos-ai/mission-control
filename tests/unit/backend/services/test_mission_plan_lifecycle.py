"""Plan 88 step 88.4.2: MissionPlanService acts on the mission lifecycle, not a plan status."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ValidationError
from modules.backend.models.mission import Mission, MissionPauseReason, MissionStatus
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.services.mission_plan import MissionPlanService
from tests.unit.backend.services.budget_fixtures import mission_with_plan


async def _autonomous(db: AsyncSession, owner_id: str) -> str:
    mission_id, plan_id = await mission_with_plan(db, owner_id)
    plan = await db.get(MissionPlan, plan_id)
    plan.gate_mode = GateMode.AUTONOMOUS
    await db.flush()
    return mission_id


async def test_emergency_stop_pauses_active_autonomous_missions(
    db_session: AsyncSession, test_user
):
    autonomous = await _autonomous(db_session, test_user.id)
    manual, _ = await mission_with_plan(db_session, test_user.id)

    await MissionPlanService(db_session).pause_all_autonomous_plans()

    paused = await db_session.get(Mission, autonomous, populate_existing=True)
    assert paused.status == MissionStatus.PAUSED
    assert paused.paused_reason == MissionPauseReason.USER
    assert paused.paused_at is not None
    untouched = await db_session.get(Mission, manual, populate_existing=True)
    assert untouched.status == MissionStatus.ACTIVE
    assert untouched.paused_reason is None


async def test_add_task_rejects_archived_mission(db_session: AsyncSession, test_user):
    mission_id, plan_id = await mission_with_plan(db_session, test_user.id)
    mission = await db_session.get(Mission, mission_id)
    mission.status = MissionStatus.ARCHIVED
    await db_session.flush()

    with pytest.raises(ValidationError, match="archived mission"):
        await MissionPlanService(db_session).add_task(
            plan_id, description="new work", agent="research.analyst.agent"
        )
