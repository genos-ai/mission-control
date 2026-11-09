"""MissionScheduleRepository (Plan 88, 88.1.4)."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modules.backend.models.mission_schedule import MissionSchedule, MissionScheduleKind
from modules.backend.repositories.mission_schedule import MissionScheduleRepository
from tests.integration.backend.api.helpers import create_mission


def _schedule(mission_id: str, owner_id: str, name: str) -> MissionSchedule:
    return MissionSchedule(
        mission_id=mission_id,
        name=name,
        kind=MissionScheduleKind.OBJECTIVE,
        objective_template="do it",
        cron_expression="0 * * * *",
        time_zone_name="UTC",
        catch_up_window_seconds=3600,
        created_by_user_id=owner_id,
    )


async def test_get_for_mission_rejects_foreign_schedule(
    db_session: AsyncSession, test_user
) -> None:
    mission_a = await create_mission(db_session, "sched-scope-a", test_user.id)
    mission_b = await create_mission(db_session, "sched-scope-b", test_user.id)
    schedule_b = _schedule(mission_b.id, test_user.id, "nightly")
    db_session.add(schedule_b)
    await db_session.flush()
    repo = MissionScheduleRepository(db_session)

    assert await repo.get_for_mission(mission_a.id, schedule_b.id) is None
    assert (await repo.get_for_mission(mission_b.id, schedule_b.id)).id == schedule_b.id


async def test_lock_blocks_second_session(
    db_session_factory: async_sessionmaker[AsyncSession], committed_owner
) -> None:
    user, mission, _plan = await committed_owner()
    async with db_session_factory() as session:
        schedule = _schedule(mission.id, user.id, "locked")
        session.add(schedule)
        await session.commit()
        schedule_id = schedule.id

    async with db_session_factory() as first, db_session_factory() as second:
        assert await MissionScheduleRepository(first).lock(schedule_id) is not None

        async def lock_second() -> MissionSchedule | None:
            locked = await MissionScheduleRepository(second).lock(schedule_id)
            await second.commit()
            return locked

        waiter = asyncio.create_task(lock_second())
        await asyncio.sleep(0.5)
        assert not waiter.done()

        await first.commit()
        locked = await asyncio.wait_for(waiter, timeout=10)
        assert locked is not None and locked.id == schedule_id
