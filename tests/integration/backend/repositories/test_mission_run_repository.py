"""MissionRunRepository and MissionRepository.increment_run_sequence (Plan 88, 88.1.4)."""

import asyncio
from datetime import timedelta
from uuid import uuid7

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modules.backend.core.utils import utc_now
from modules.backend.models.mission import Mission
from modules.backend.models.mission_plan import MissionPlan
from modules.backend.models.mission_run import MissionRun, MissionRunStatus, MissionRunTrigger
from modules.backend.models.mission_schedule import MissionSchedule, MissionScheduleKind
from modules.backend.repositories.mission import MissionRepository
from modules.backend.repositories.mission_run import MissionRunRepository
from modules.backend.temporal.workflow_ids import mission_run_workflow_id
from tests.integration.backend.api.helpers import create_mission


async def _plan_id(db: AsyncSession, mission: Mission) -> str:
    return await db.scalar(select(MissionPlan.id).where(MissionPlan.mission_id == mission.id))


async def _add_run(
    db: AsyncSession, mission: Mission, plan_id: str, sequence: int, status: MissionRunStatus
) -> MissionRun:
    run = MissionRun(
        mission_id=mission.id,
        plan_id=plan_id,
        sequence=sequence,
        trigger=MissionRunTrigger.MANUAL,
        status=status,
    )
    db.add(run)
    await db.flush()
    return run


async def _add_schedule(db: AsyncSession, mission: Mission, owner_id: str) -> MissionSchedule:
    schedule = MissionSchedule(
        mission_id=mission.id,
        name=f"s-{uuid7()}"[:100],
        kind=MissionScheduleKind.OBJECTIVE,
        objective_template="do it",
        cron_expression="0 * * * *",
        time_zone_name="UTC",
        catch_up_window_seconds=3600,
        created_by_user_id=owner_id,
    )
    db.add(schedule)
    await db.flush()
    return schedule


async def test_increment_run_sequence_concurrent(
    db_session_factory: async_sessionmaker[AsyncSession], committed_owner
) -> None:
    _user, mission, _plan = await committed_owner()

    async def increment() -> int:
        async with db_session_factory() as session:
            value = await MissionRepository(session).increment_run_sequence(mission.id)
            await session.commit()
            return value

    values = await asyncio.gather(*(increment() for _ in range(20)))
    assert sorted(values) == list(range(1, 21))


async def test_increment_rolled_back_with_savepoint(db_session: AsyncSession, test_user) -> None:
    mission = await create_mission(db_session, "seq-savepoint", test_user.id)
    mission_id = mission.id  # the savepoint rollback expires the ORM object
    repo = MissionRepository(db_session)
    assert await repo.increment_run_sequence(mission_id) == 1

    savepoint = await db_session.begin_nested()
    assert await repo.increment_run_sequence(mission_id) == 2
    await savepoint.rollback()

    counter = await db_session.scalar(
        select(Mission.run_sequence_counter).where(Mission.id == mission_id)
    )
    assert counter == 1


async def test_insert_occurrence_conflict_returns_none(db_session: AsyncSession, test_user) -> None:
    mission = await create_mission(db_session, "occ-conflict", test_user.id)
    plan_id = await _plan_id(db_session, mission)
    schedule = await _add_schedule(db_session, mission, test_user.id)
    repo = MissionRunRepository(db_session)
    slot = utc_now().replace(microsecond=0)

    def occurrence(sequence: int, status: MissionRunStatus) -> dict:
        run_id = str(uuid7())
        return {
            "id": run_id,
            "mission_id": mission.id,
            "plan_id": plan_id,
            "schedule_id": schedule.id,
            "sequence": sequence,
            "scheduled_for": slot,
            "status": status,
            "status_reason": None,
            "status_detail": None,
            "objective": "do it",
            "workflow_definition_id": None,
            "workflow_parameters": {},
            "temporal_workflow_id": mission_run_workflow_id(run_id),
            "config_snapshot": {},
        }

    first = await repo.insert_occurrence(**occurrence(1, MissionRunStatus.PENDING))
    assert first is not None
    assert first.trigger is MissionRunTrigger.SCHEDULE
    assert first.status is MissionRunStatus.PENDING

    second = await repo.insert_occurrence(**occurrence(2, MissionRunStatus.SUCCEEDED))
    assert second is None
    assert (await repo.get_by_slot(schedule.id, slot)).id == first.id


async def test_get_active_for_mission_ignores_terminal(db_session: AsyncSession, test_user) -> None:
    mission = await create_mission(db_session, "active-run", test_user.id)
    plan_id = await _plan_id(db_session, mission)
    repo = MissionRunRepository(db_session)
    await _add_run(db_session, mission, plan_id, 1, MissionRunStatus.SUCCEEDED)
    await _add_run(db_session, mission, plan_id, 2, MissionRunStatus.FAILED)
    assert await repo.get_active_for_mission(mission.id) is None

    active = await _add_run(db_session, mission, plan_id, 3, MissionRunStatus.RUNNING)
    assert (await repo.get_active_for_mission(mission.id)).id == active.id


async def test_get_for_mission_rejects_other_mission(db_session: AsyncSession, test_user) -> None:
    mission_a = await create_mission(db_session, "run-scope-a", test_user.id)
    mission_b = await create_mission(db_session, "run-scope-b", test_user.id)
    run_b = await _add_run(
        db_session, mission_b, await _plan_id(db_session, mission_b), 1, MissionRunStatus.PENDING
    )
    repo = MissionRunRepository(db_session)

    assert await repo.get_for_mission(mission_a.id, run_b.id) is None
    assert await repo.lock_for_mission(mission_a.id, run_b.id) is None
    assert (await repo.get_for_mission(mission_b.id, run_b.id)).id == run_b.id


async def test_list_for_mission_paginates_by_sequence(db_session: AsyncSession, test_user) -> None:
    mission = await create_mission(db_session, "run-pages", test_user.id)
    plan_id = await _plan_id(db_session, mission)
    for seq in range(1, 6):
        await _add_run(db_session, mission, plan_id, seq, MissionRunStatus.SUCCEEDED)
    repo = MissionRunRepository(db_session)

    page1 = await repo.list_for_mission(mission.id, statuses=None, limit=2, before_sequence=None)
    assert [r.sequence for r in page1] == [5, 4]
    page2 = await repo.list_for_mission(
        mission.id, statuses=None, limit=2, before_sequence=page1[-1].sequence
    )
    assert [r.sequence for r in page2] == [3, 2]
    page3 = await repo.list_for_mission(
        mission.id, statuses=None, limit=2, before_sequence=page2[-1].sequence
    )
    assert [r.sequence for r in page3] == [1]

    filtered = await repo.list_for_mission(
        mission.id, statuses=[MissionRunStatus.FAILED], limit=10, before_sequence=None
    )
    assert filtered == []
    stale = await repo.list_active_older_than(utc_now() + timedelta(seconds=1))
    assert all(r.mission_id != mission.id for r in stale)
