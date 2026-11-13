"""Plan 88 step 88.4.2: TaskRepository.summarise_for_missions reads the mission's status."""

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.utils import utc_now
from modules.backend.models.mission import Mission, MissionPauseReason, MissionStatus
from modules.backend.models.task import Task, TaskStatus
from modules.backend.repositories.task import TaskRepository
from tests.unit.backend.services.budget_fixtures import mission_with_plan


async def _failed_task(db: AsyncSession, mission_id: str, plan_id: str) -> None:
    db.add(
        Task(
            mission_id=mission_id,
            plan_id=plan_id,
            agent="research.analyst.agent",
            description="failed task",
            status=TaskStatus.FAILED,
        )
    )
    await db.flush()


async def _set_status(
    db: AsyncSession, mission_id: str, status: MissionStatus, reason=None
) -> None:
    mission = await db.get(Mission, mission_id)
    mission.status = status
    mission.paused_reason = reason
    mission.paused_at = utc_now() if reason else None
    await db.flush()


async def test_pending_counts_exclude_archived_missions(db_session: AsyncSession, test_user):
    active = await mission_with_plan(db_session, test_user.id)
    paused = await mission_with_plan(db_session, test_user.id)
    archived = await mission_with_plan(db_session, test_user.id)
    for mission_id, plan_id in (active, paused, archived):
        await _failed_task(db_session, mission_id, plan_id)
    await _set_status(db_session, paused[0], MissionStatus.PAUSED, MissionPauseReason.USER)
    await _set_status(db_session, archived[0], MissionStatus.ARCHIVED)

    groups = await TaskRepository(db_session).summarise_for_missions(
        [active[0], paused[0], archived[0]], TaskStatus.FAILED
    )

    assert {g.mission_id: g.count for g in groups} == {active[0]: 1, paused[0]: 1}
