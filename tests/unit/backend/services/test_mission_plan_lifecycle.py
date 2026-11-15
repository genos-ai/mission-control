"""Plan 88 step 88.4.2: MissionPlanService acts on the mission lifecycle, not a plan status."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ValidationError
from modules.backend.models.mission import Mission, MissionStatus
from modules.backend.services.mission_plan import MissionPlanService
from tests.unit.backend.services.budget_fixtures import mission_with_plan


async def test_add_task_rejects_archived_mission(db_session: AsyncSession, test_user):
    mission_id, plan_id = await mission_with_plan(db_session, test_user.id)
    mission = await db_session.get(Mission, mission_id)
    mission.status = MissionStatus.ARCHIVED
    await db_session.flush()

    with pytest.raises(ValidationError, match="archived mission"):
        await MissionPlanService(db_session).add_task(
            plan_id, description="new work", agent="research.analyst.agent"
        )
