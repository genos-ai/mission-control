"""MissionLifecycleService (Plan 88 step 88.4.5, contracts 3.2.2 and 3.5.1).

Real db_session; both Temporal gateways are fakes.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ConflictError
from modules.backend.core.utils import utc_now
from modules.backend.models.gate_request import GateRequest, GateRequestStatus
from modules.backend.models.mission import Mission, MissionPauseReason, MissionStatus
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.models.mission_run import (
    MissionRun,
    MissionRunStatus,
    MissionRunStatusReason,
)
from modules.backend.models.mission_schedule import (
    MissionSchedule,
    MissionScheduleKind,
    MissionScheduleStatus,
)
from modules.backend.services import mission_lifecycle as lifecycle_module
from modules.backend.services.mission_lifecycle import MissionLifecycleService
from modules.backend.services.mission_run import MissionRunService
from modules.backend.services.mission_schedule import MissionScheduleService
from modules.backend.temporal.mission_run_models import PauseRequest, ResumeRequest
from modules.backend.temporal.schedule_gateway import TemporalScheduleGateway
from modules.backend.temporal.workflow_gateway import TemporalWorkflowGateway, WorkflowState
from modules.backend.temporal.workflow_ids import mission_run_workflow_id
from tests.unit.backend.services import budget_fixtures as bf

UTC = timezone.utc


class _Bus:
    def __init__(self) -> None:
        self.events: list = []

    async def publish(self, event) -> None:
        self.events.append(event)

    async def publish_to_mission(self, mission_id: str, event) -> None:
        self.events.append(event)


class _ScheduleGateway:
    """Hourly matching times on the hour; records deletes and upserts."""

    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.upserted: list[str] = []
        self.listed: list[tuple[str, datetime, datetime]] = []

    async def upsert(self, schedule_id, schedule) -> None:
        self.upserted.append(schedule_id)

    async def delete(self, schedule_id) -> None:
        self.deleted.append(schedule_id)

    async def list_matching_times(self, schedule_id, start, end) -> list[datetime]:
        self.listed.append((schedule_id, start, end))
        t = start.replace(minute=0, second=0, microsecond=0)
        times = []
        while t <= end:
            if t >= start:
                times.append(t)
            t += timedelta(hours=1)
        return times


@pytest.fixture
def workflows(monkeypatch) -> AsyncMock:
    fake = AsyncMock()
    fake.signal.return_value = WorkflowState.RUNNING
    fake.cancel.return_value = WorkflowState.RUNNING
    monkeypatch.setattr(TemporalWorkflowGateway, "connect", AsyncMock(return_value=fake))
    return fake


@pytest.fixture
def schedules(monkeypatch) -> _ScheduleGateway:
    fake = _ScheduleGateway()
    monkeypatch.setattr(TemporalScheduleGateway, "create", AsyncMock(return_value=fake))
    return fake


@pytest.fixture
def bus() -> _Bus:
    return _Bus()


def _svc(db: AsyncSession, bus: _Bus) -> MissionLifecycleService:
    return MissionLifecycleService(db, bus)


async def _mission(db: AsyncSession, owner_id: str, **caps) -> tuple[str, str]:
    return await bf.mission_with_plan(db, owner_id, **caps)


async def _pause_row(
    db: AsyncSession, mission_id: str, reason: MissionPauseReason, paused_at: datetime
) -> None:
    mission = await db.get(Mission, mission_id)
    mission.status = MissionStatus.PAUSED
    mission.paused_reason = reason
    mission.paused_at = paused_at
    await db.flush()


async def _schedule(
    db: AsyncSession,
    mission_id: str,
    user_id: str,
    status: MissionScheduleStatus = MissionScheduleStatus.ACTIVE,
) -> str:
    schedule = MissionSchedule(
        mission_id=mission_id,
        name=f"hourly-{uuid.uuid4().hex[:6]}",
        kind=MissionScheduleKind.OBJECTIVE,
        objective_template="Run at {scheduled_for}",
        cron_expression="0 * * * *",
        time_zone_name="UTC",
        catch_up_window_seconds=3600,
        status=status,
        created_by_user_id=user_id,
    )
    db.add(schedule)
    await db.flush()
    return schedule.id


async def _gate(db: AsyncSession, mission_id: str, status: GateRequestStatus) -> str:
    gate = GateRequest(
        mission_id=mission_id,
        gate_type="post_run",
        context_json={},
        status=status,
        created_at=utc_now(),
    )
    db.add(gate)
    await db.flush()
    return gate.id


# ── pause ────────────────────────────────────────────────────────────────


async def test_pause_sets_columns_commits_then_syncs(
    db_session, test_user, workflows, schedules, bus, monkeypatch
):
    mission_id, _ = await _mission(db_session, test_user.id)
    order: list[str] = []
    real_commit = db_session.commit

    async def commit() -> None:
        order.append("commit")
        await real_commit()

    async def sync_mission(self, mid: str):
        order.append("sync")
        row = await db_session.get(Mission, mid)
        assert row.status == MissionStatus.PAUSED

    monkeypatch.setattr(db_session, "commit", commit)
    monkeypatch.setattr(MissionScheduleService, "sync_mission", sync_mission)

    mission = await _svc(db_session, bus).pause_mission(
        mission_id, reason=MissionPauseReason.USER, user_id=test_user.id
    )

    assert order[:2] == ["commit", "sync"]
    assert mission.status == MissionStatus.PAUSED
    assert mission.paused_reason == MissionPauseReason.USER
    assert mission.paused_at is not None
    assert mission.paused_by_user_id == test_user.id
    changed = [e for e in bus.events if e.event_type == "mission.lifecycle_changed"]
    assert [(e.from_status, e.to_status, e.paused_reason) for e in changed] == [
        ("active", "paused", "user")
    ]
    workflows.signal.assert_not_awaited()


async def _assert_user_pause_signals(db_session, user_id, workflows, bus, status) -> None:
    mission_id, plan_id = await _mission(db_session, user_id)
    run_id = await bf.run(db_session, mission_id, plan_id, status=status)

    await _svc(db_session, bus).pause_mission(
        mission_id, reason=MissionPauseReason.USER, user_id=user_id
    )

    workflows.signal.assert_awaited_once_with(
        mission_run_workflow_id(run_id),
        "request_pause",
        PauseRequest(requested_by_user_id=user_id, reason="user"),
    )


async def test_pause_user_signals_running_run(db_session, test_user, workflows, schedules, bus):
    await _assert_user_pause_signals(
        db_session, test_user.id, workflows, bus, MissionRunStatus.RUNNING
    )


async def test_pause_user_signals_awaiting_gate_run(
    db_session, test_user, workflows, schedules, bus
):
    await _assert_user_pause_signals(
        db_session, test_user.id, workflows, bus, MissionRunStatus.AWAITING_GATE
    )


async def test_pause_system_reason_does_not_signal(
    db_session, test_user, workflows, schedules, bus
):
    mission_id, plan_id = await _mission(db_session, test_user.id)
    await bf.run(db_session, mission_id, plan_id)

    await _svc(db_session, bus).pause_mission(
        mission_id, reason=MissionPauseReason.BUDGET_MONTHLY_CAP, user_id=None
    )

    workflows.signal.assert_not_awaited()


async def test_pause_sends_no_notification(
    db_session, test_user, workflows, schedules, bus, monkeypatch
):
    from modules.backend.services.notification import NotificationService

    notify = AsyncMock()
    monkeypatch.setattr(NotificationService, "notify", notify)
    mission_id, _ = await _mission(db_session, test_user.id)

    await _svc(db_session, bus).pause_mission(
        mission_id, reason=MissionPauseReason.GATE_TIMEOUT, user_id=None
    )

    notify.assert_not_awaited()
    assert not [e for e in bus.events if e.event_type.startswith("notification")]


async def test_pause_rejects_non_active(db_session, test_user, workflows, schedules, bus):
    mission_id, _ = await _mission(db_session, test_user.id)
    await _pause_row(db_session, mission_id, MissionPauseReason.USER, utc_now())

    with pytest.raises(ConflictError, match="not active"):
        await _svc(db_session, bus).pause_mission(
            mission_id, reason=MissionPauseReason.USER, user_id=test_user.id
        )


async def test_pause_for_run_leaves_paused_mission(
    db_session, test_user, workflows, schedules, bus
):
    mission_id, plan_id = await _mission(db_session, test_user.id)
    run_id = await bf.run(db_session, mission_id, plan_id)
    await _pause_row(db_session, mission_id, MissionPauseReason.USER, utc_now())

    paused = await _svc(db_session, bus).pause_for_run(run_id, MissionPauseReason.GATE_TIMEOUT)

    assert paused is False
    row = await db_session.get(Mission, mission_id)
    assert row.paused_reason == MissionPauseReason.USER


# ── resume ───────────────────────────────────────────────────────────────


async def test_resume_signals_running_run_with_pending_pause(
    db_session, test_user, workflows, schedules, bus
):
    mission_id, plan_id = await _mission(db_session, test_user.id)
    run_id = await bf.run(db_session, mission_id, plan_id)
    await _pause_row(db_session, mission_id, MissionPauseReason.USER, utc_now())

    mission = await _svc(db_session, bus).resume_mission(mission_id, test_user.id)

    assert mission.status == MissionStatus.ACTIVE
    assert mission.paused_reason is None
    assert mission.paused_at is None
    workflows.signal.assert_awaited_once_with(
        mission_run_workflow_id(run_id),
        "resume",
        ResumeRequest(requested_by_user_id=test_user.id),
    )


async def test_resume_rejects_gate_timeout_with_undecided_gate(
    db_session, test_user, workflows, schedules, bus
):
    mission_id, _ = await _mission(db_session, test_user.id)
    await _pause_row(db_session, mission_id, MissionPauseReason.GATE_TIMEOUT, utc_now())
    await _gate(db_session, mission_id, GateRequestStatus.TIMED_OUT)

    with pytest.raises(ConflictError, match="undecided gate"):
        await _svc(db_session, bus).resume_mission(mission_id, test_user.id)


async def test_resume_allows_gate_timeout_without_undecided_gate(
    db_session, test_user, workflows, schedules, bus
):
    mission_id, _ = await _mission(db_session, test_user.id)
    await _pause_row(db_session, mission_id, MissionPauseReason.GATE_TIMEOUT, utc_now())
    await _gate(db_session, mission_id, GateRequestStatus.DECIDED)

    mission = await _svc(db_session, bus).resume_mission(mission_id, test_user.id)

    assert mission.status == MissionStatus.ACTIVE


async def test_resume_rejects_when_monthly_cap_breached(
    db_session, test_user, workflows, schedules, bus
):
    mission_id, _ = await _mission(db_session, test_user.id, per_month=10.0)
    await bf.call(db_session, mission_id, 12.0, utc_now())
    await _pause_row(db_session, mission_id, MissionPauseReason.BUDGET_MONTHLY_CAP, utc_now())

    with pytest.raises(ConflictError, match="budget_monthly_cap"):
        await _svc(db_session, bus).resume_mission(mission_id, test_user.id)


async def test_resume_advances_watermark_to_now(
    db_session, test_user, workflows, schedules, bus, monkeypatch
):
    now = datetime(2027, 3, 1, 15, 30, tzinfo=UTC)
    monkeypatch.setattr(lifecycle_module, "utc_now", lambda: now)
    mission_id, _ = await _mission(db_session, test_user.id)
    active_a = await _schedule(db_session, mission_id, test_user.id)
    active_b = await _schedule(db_session, mission_id, test_user.id)
    paused = await _schedule(db_session, mission_id, test_user.id, MissionScheduleStatus.PAUSED)
    await _pause_row(db_session, mission_id, MissionPauseReason.USER, now - timedelta(hours=2))

    await _svc(db_session, bus).resume_mission(mission_id, test_user.id)

    for schedule_id in (active_a, active_b):
        row = await db_session.get(MissionSchedule, schedule_id, populate_existing=True)
        assert row.last_claimed_scheduled_for == now
    untouched = await db_session.get(MissionSchedule, paused, populate_existing=True)
    assert untouched.last_claimed_scheduled_for is None
    missed = (
        (await db_session.execute(select(MissionRun).where(MissionRun.mission_id == mission_id)))
        .scalars()
        .all()
    )
    # 14:00 and 15:00 for each ACTIVE schedule; each with its own sequence.
    assert len(missed) == 4
    assert {r.status for r in missed} == {MissionRunStatus.MISSED}
    assert {r.status_reason for r in missed} == {MissionRunStatusReason.NOT_FIRED}
    assert sorted(r.sequence for r in missed) == [1, 2, 3, 4]


# ── archive and unarchive ────────────────────────────────────────────────


async def test_archive_archives_schedules_deletes_temporal_cancels_run_cancels_gates(
    db_session, test_user, workflows, schedules, bus, monkeypatch
):
    mission_id, plan_id = await _mission(db_session, test_user.id)
    active = await _schedule(db_session, mission_id, test_user.id)
    paused = await _schedule(db_session, mission_id, test_user.id, MissionScheduleStatus.PAUSED)
    run_id = await bf.run(db_session, mission_id, plan_id)
    gate_id = await _gate(db_session, mission_id, GateRequestStatus.ESCALATED)
    cancel_run = AsyncMock()
    monkeypatch.setattr(MissionRunService, "cancel_run", cancel_run)

    mission = await _svc(db_session, bus).archive_mission(mission_id, test_user.id)

    assert mission.status == MissionStatus.ARCHIVED
    assert mission.paused_reason is None
    for schedule_id in (active, paused):
        row = await db_session.get(MissionSchedule, schedule_id, populate_existing=True)
        assert row.status == MissionScheduleStatus.ARCHIVED
    assert sorted(schedules.deleted) == sorted(
        [
            (await db_session.get(MissionSchedule, active)).temporal_schedule_id,
            (await db_session.get(MissionSchedule, paused)).temporal_schedule_id,
        ]
    )
    cancel_run.assert_awaited_once_with(
        mission_id, run_id, test_user.id, MissionRunStatusReason.MISSION_ARCHIVED
    )
    gate = await db_session.get(GateRequest, gate_id, populate_existing=True)
    assert gate.status == GateRequestStatus.CANCELLED


async def test_unarchive_leaves_schedules_archived_mission_paused_user(
    db_session, test_user, workflows, schedules, bus
):
    mission_id, _ = await _mission(db_session, test_user.id)
    schedule_id = await _schedule(
        db_session, mission_id, test_user.id, MissionScheduleStatus.ARCHIVED
    )
    mission = await db_session.get(Mission, mission_id)
    mission.status = MissionStatus.ARCHIVED
    await db_session.flush()

    mission = await _svc(db_session, bus).unarchive_mission(mission_id, test_user.id)

    assert mission.status == MissionStatus.PAUSED
    assert mission.paused_reason == MissionPauseReason.USER
    assert mission.paused_by_user_id == test_user.id
    row = await db_session.get(MissionSchedule, schedule_id, populate_existing=True)
    assert row.status == MissionScheduleStatus.ARCHIVED
    assert schedules.upserted == []


# ── emergency stop ───────────────────────────────────────────────────────


async def test_pause_all_active_only_autonomous(db_session, test_user, workflows, schedules, bus):
    autonomous, plan_id = await _mission(db_session, test_user.id)
    plan = await db_session.get(MissionPlan, plan_id)
    plan.gate_mode = GateMode.AUTONOMOUS
    manual, _ = await _mission(db_session, test_user.id)
    await db_session.flush()

    count = await _svc(db_session, bus).pause_all_active(test_user.id)

    assert count >= 1
    paused = await db_session.get(Mission, autonomous, populate_existing=True)
    assert paused.status == MissionStatus.PAUSED
    assert paused.paused_reason == MissionPauseReason.USER
    assert paused.paused_by_user_id == test_user.id
    untouched = await db_session.get(Mission, manual, populate_existing=True)
    assert untouched.status == MissionStatus.ACTIVE
