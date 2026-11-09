"""MissionScheduleService.claim_occurrence (Plan 88 step 88.1.6, contract 3.3.2).

Real database, FakeScheduleGateway on an hourly grid, and a patched utc_now.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modules.backend.core.config import get_app_config
from modules.backend.models.mission import Mission
from modules.backend.models.mission_plan import MissionPlan
from modules.backend.models.mission_run import (
    MissionRun,
    MissionRunStatus,
    MissionRunStatusReason,
    MissionRunTrigger,
)
from modules.backend.models.mission_schedule import (
    MissionSchedule,
    MissionScheduleCompletedReason,
    MissionScheduleKind,
    MissionScheduleStatus,
)
from modules.backend.models.user import User
from modules.backend.repositories.mission import MissionRepository
from modules.backend.services.mission_schedule import MissionScheduleService
from modules.backend.services.mission_schedule_claim import RUN_MISSED, RUN_SKIPPED
from modules.backend.temporal.workflow_ids import mission_run_workflow_id
from tests.integration.backend.services.test_mission_schedule_service import (
    FakeScheduleGateway,
    RecordingBus,
)

UTC = timezone.utc
T = datetime(2027, 3, 1, 12, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)
CLAIM_MODULE = "modules.backend.services.mission_schedule_claim"


@pytest.fixture
def gateway() -> FakeScheduleGateway:
    return FakeScheduleGateway(interval=HOUR)


@pytest.fixture
def set_now(monkeypatch):
    def apply(now: datetime) -> None:
        monkeypatch.setattr(f"{CLAIM_MODULE}.utc_now", lambda: now)

    apply(T + timedelta(seconds=10))
    return apply


@pytest.fixture
def owner(committed_owner):
    return committed_owner


async def _schedule(
    factory: async_sessionmaker[AsyncSession],
    user: User,
    mission: Mission,
    *,
    watermark: datetime,
    catch_up: int = 7200,
    max_runs: int | None = None,
) -> str:
    async with factory() as session:
        schedule = MissionSchedule(
            mission_id=mission.id,
            name="hourly",
            kind=MissionScheduleKind.OBJECTIVE,
            objective_template="Run {sequence} of {mission_name} at {scheduled_for}",
            cron_expression="0 * * * *",
            time_zone_name="Europe/London",
            catch_up_window_seconds=catch_up,
            max_runs=max_runs,
            last_claimed_scheduled_for=watermark,
            created_by_user_id=user.id,
        )
        session.add(schedule)
        await session.commit()
        return schedule.id


async def _claim(factory, gateway, schedule_id: str, scheduled_for: datetime):
    async with factory() as session:
        return await MissionScheduleService(session, gateway, RecordingBus()).claim_occurrence(
            schedule_id, scheduled_for
        )


async def _runs(factory, mission_id: str) -> list[MissionRun]:
    async with factory() as session:
        result = await session.execute(
            select(MissionRun)
            .where(MissionRun.mission_id == mission_id)
            .order_by(MissionRun.sequence)
        )
        return list(result.scalars().all())


async def _add_manual_run(factory, mission: Mission, plan: MissionPlan) -> MissionRun:
    async with factory() as session:
        sequence = await MissionRepository(session).increment_run_sequence(mission.id)
        run = MissionRun(
            mission_id=mission.id,
            plan_id=plan.id,
            sequence=sequence,
            trigger=MissionRunTrigger.MANUAL,
            status=MissionRunStatus.RUNNING,
        )
        session.add(run)
        await session.commit()
        return run


async def _schedule_row(factory, schedule_id: str) -> MissionSchedule:
    async with factory() as session:
        return await session.get(MissionSchedule, schedule_id)


async def test_run_outcome_inserts_pending_and_increments(
    db_session_factory, gateway, owner, set_now
) -> None:
    user, mission, plan = await owner()
    schedule_id = await _schedule(db_session_factory, user, mission, watermark=T - HOUR)

    claim = await _claim(db_session_factory, gateway, schedule_id, T)

    assert claim.outcome == "run"
    run = claim.run
    assert run.status == MissionRunStatus.PENDING
    assert run.trigger == MissionRunTrigger.SCHEDULE
    assert run.sequence == 1
    assert run.temporal_workflow_id == mission_run_workflow_id(run.id)
    assert run.config_snapshot
    assert run.objective == f"Run 1 of {mission.name} at 2027-03-01T12:00:00+00:00"
    assert claim.run_input.mission_run_id == run.id
    assert claim.run_input.plan_id == plan.id
    assert claim.notifications == []
    stored = await _schedule_row(db_session_factory, schedule_id)
    assert stored.executed_run_count == 1
    assert stored.last_claimed_scheduled_for == T


async def test_recurrence_disabled_skips_tick(
    db_session_factory, gateway, owner, set_now, monkeypatch
) -> None:
    user, mission, _plan = await owner()
    schedule_id = await _schedule(db_session_factory, user, mission, watermark=T - 10 * HOUR)
    monkeypatch.setattr(get_app_config().missions.recurrence, "enabled", False)

    claim = await _claim(db_session_factory, gateway, schedule_id, T)

    assert claim.outcome == "skipped"
    assert claim.run_input is None
    runs = await _runs(db_session_factory, mission.id)
    assert [(r.status, r.status_reason, r.scheduled_for) for r in runs] == [
        (MissionRunStatus.SKIPPED, MissionRunStatusReason.SCHEDULE_NOT_ACTIVE, T)
    ]
    assert (await _schedule_row(db_session_factory, schedule_id)).last_claimed_scheduled_for == T


async def test_duplicate_slot_returns_duplicate(
    db_session_factory, gateway, owner, set_now
) -> None:
    user, mission, _plan = await owner()
    schedule_id = await _schedule(db_session_factory, user, mission, watermark=T - HOUR)
    first = await _claim(db_session_factory, gateway, schedule_id, T - HOUR)
    assert first.outcome == "missed"

    again = await _claim(db_session_factory, gateway, schedule_id, T - HOUR)

    assert again.outcome == "duplicate"
    assert again.run.id == first.run.id
    assert again.run_input is None
    assert len(await _runs(db_session_factory, mission.id)) == 1


async def test_duplicate_pending_returns_run_input(
    db_session_factory, gateway, owner, set_now
) -> None:
    user, mission, _plan = await owner()
    schedule_id = await _schedule(db_session_factory, user, mission, watermark=T - HOUR)
    first = await _claim(db_session_factory, gateway, schedule_id, T)

    again = await _claim(db_session_factory, gateway, schedule_id, T)

    assert again.outcome == "duplicate"
    assert again.run_input is not None
    assert again.run_input.mission_run_id == first.run.id


async def test_overlap_records_skipped(db_session_factory, gateway, owner, set_now) -> None:
    user, mission, plan = await owner()
    schedule_id = await _schedule(db_session_factory, user, mission, watermark=T - HOUR)
    await _add_manual_run(db_session_factory, mission, plan)

    claim = await _claim(db_session_factory, gateway, schedule_id, T)

    assert claim.outcome == "skipped"
    assert claim.run.status_reason == MissionRunStatusReason.OVERLAP
    assert claim.run_input is None
    assert [n.kind for n in claim.notifications] == [RUN_SKIPPED]
    assert claim.notifications[0].subject_id == f"{schedule_id}:{T.isoformat()}"


async def test_outside_catch_up_window_records_missed(
    db_session_factory, gateway, owner, set_now
) -> None:
    user, mission, _plan = await owner()
    schedule_id = await _schedule(db_session_factory, user, mission, watermark=T - HOUR)
    set_now(T + 3 * HOUR)

    claim = await _claim(db_session_factory, gateway, schedule_id, T)

    assert claim.outcome == "missed"
    assert claim.run.status_reason == MissionRunStatusReason.OUTSIDE_CATCHUP_WINDOW
    assert [n.kind for n in claim.notifications] == [RUN_MISSED]
    assert claim.notifications[0].payload["count"] == 1


async def test_superseded_when_later_slot_due(db_session_factory, gateway, owner, set_now) -> None:
    user, mission, _plan = await owner()
    schedule_id = await _schedule(db_session_factory, user, mission, watermark=T - HOUR)
    set_now(T + HOUR + timedelta(seconds=10))

    claim = await _claim(db_session_factory, gateway, schedule_id, T)

    assert claim.outcome == "missed"
    assert claim.run.status_reason == MissionRunStatusReason.SUPERSEDED


async def test_backfill_records_only_undeliverable_slots(
    db_session_factory, gateway, owner, set_now
) -> None:
    user, mission, _plan = await owner()
    schedule_id = await _schedule(
        db_session_factory, user, mission, watermark=T - 10 * HOUR, catch_up=7200
    )

    claim = await _claim(db_session_factory, gateway, schedule_id, T)

    runs = {r.scheduled_for: r for r in await _runs(db_session_factory, mission.id)}
    for hours in range(2, 10):
        row = runs[T - hours * HOUR]
        assert (row.status, row.status_reason) == (
            MissionRunStatus.MISSED,
            MissionRunStatusReason.NOT_FIRED,
        )
    assert T - HOUR not in runs
    assert runs[T].status == MissionRunStatus.PENDING
    assert len(runs) == 9
    assert claim.outcome == "run"
    missed = [n for n in claim.notifications if n.kind == RUN_MISSED]
    assert len(missed) == 1 and missed[0].payload["count"] == 8
    assert len(claim.recorded) == 8


async def test_out_of_order_ticks_record_every_slot(
    db_session_factory, gateway, owner, set_now
) -> None:
    user, mission, _plan = await owner()
    schedule_id = await _schedule(
        db_session_factory, user, mission, watermark=T - 10 * HOUR, catch_up=6 * 3600
    )

    for hours in range(5, -1, -1):
        await _claim(db_session_factory, gateway, schedule_id, T - hours * HOUR)

    runs = await _runs(db_session_factory, mission.id)
    by_slot = {r.scheduled_for: r for r in runs}
    assert len(by_slot) == len(runs) == 10
    for hours in range(6, 10):
        assert by_slot[T - hours * HOUR].status_reason == MissionRunStatusReason.NOT_FIRED
    for hours in range(1, 6):
        assert by_slot[T - hours * HOUR].status_reason == MissionRunStatusReason.SUPERSEDED
    assert [r.scheduled_for for r in runs if r.status == MissionRunStatus.PENDING] == [T]


async def test_max_runs_completes_schedule(db_session_factory, gateway, owner, set_now) -> None:
    user, mission, _plan = await owner()
    schedule_id = await _schedule(db_session_factory, user, mission, watermark=T - HOUR, max_runs=1)

    claim = await _claim(db_session_factory, gateway, schedule_id, T)

    assert claim.outcome == "run"
    stored = await _schedule_row(db_session_factory, schedule_id)
    assert stored.executed_run_count == 1
    assert stored.status == MissionScheduleStatus.COMPLETED
    assert stored.completed_reason == MissionScheduleCompletedReason.MAX_RUNS_REACHED


async def test_concurrent_claims_serialise(db_session_factory, gateway, owner, set_now) -> None:
    user, mission, _plan = await owner()
    schedule_id = await _schedule(db_session_factory, user, mission, watermark=T - 2 * HOUR)

    await asyncio.gather(
        _claim(db_session_factory, gateway, schedule_id, T - HOUR),
        _claim(db_session_factory, gateway, schedule_id, T),
    )

    by_slot = {r.scheduled_for: r for r in await _runs(db_session_factory, mission.id)}
    assert sum(r.status == MissionRunStatus.PENDING for r in by_slot.values()) == 1
    earlier, later = by_slot[T - HOUR], by_slot[T]
    assert (later.status, earlier.status_reason) == (
        MissionRunStatus.PENDING,
        MissionRunStatusReason.SUPERSEDED,
    ) or (earlier.status, later.status_reason) == (
        MissionRunStatus.PENDING,
        MissionRunStatusReason.OVERLAP,
    )


async def test_manual_run_race_records_overlap(
    db_session_factory, gateway, owner, set_now, monkeypatch
) -> None:
    user, mission, plan = await owner()
    schedule_id = await _schedule(db_session_factory, user, mission, watermark=T - HOUR)
    original = MissionRepository.increment_run_sequence
    raced: list[MissionRun] = []

    async def racing_increment(self, mission_id: str) -> int:
        if self.session.in_nested_transaction() and not raced:
            raced.append(await _add_manual_run(db_session_factory, mission, plan))
        return await original(self, mission_id)

    monkeypatch.setattr(MissionRepository, "increment_run_sequence", racing_increment)

    claim = await _claim(db_session_factory, gateway, schedule_id, T)

    assert raced, "the race hook did not run inside the savepoint"
    assert claim.outcome == "skipped"
    assert claim.run.status_reason == MissionRunStatusReason.OVERLAP
    runs = await _runs(db_session_factory, mission.id)
    assert [r.sequence for r in runs] == [1, 2]
    assert runs[0].trigger == MissionRunTrigger.MANUAL
    assert (runs[1].status, runs[1].status_reason) == (
        MissionRunStatus.SKIPPED,
        MissionRunStatusReason.OVERLAP,
    )


async def test_sequence_monotonic_across_outcomes(
    db_session_factory, gateway, owner, set_now
) -> None:
    user, mission, plan = await owner()
    schedule_id = await _schedule(
        db_session_factory, user, mission, watermark=T - 4 * HOUR, catch_up=7200
    )

    await _claim(db_session_factory, gateway, schedule_id, T - HOUR)  # backfill 2 + superseded
    await _claim(db_session_factory, gateway, schedule_id, T)  # run
    set_now(T + HOUR + timedelta(seconds=5))
    await _claim(db_session_factory, gateway, schedule_id, T + HOUR)  # overlap

    runs = await _runs(db_session_factory, mission.id)
    assert [r.sequence for r in runs] == list(range(1, len(runs) + 1))
    assert len(runs) == 5
    slots = [r.scheduled_for for r in runs]
    assert slots == sorted(slots)
    assert runs[-1].status_reason == MissionRunStatusReason.OVERLAP
