"""MissionScheduleService (Plan 88 step 88.1.6).

Real database; TemporalScheduleGateway is replaced by FakeScheduleGateway.
The service commits, so every test works on committed rows (committed_owner).
"""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import AsyncEngine
from temporalio.client import Schedule, ScheduleSpec
from temporalio.service import RPCError, RPCStatusCode

from modules.backend.core.config import get_app_config
from modules.backend.core.exceptions import NotFoundError, ValidationError
from modules.backend.core.utils import utc_now
from modules.backend.events.base import SessionEvent
from modules.backend.events.mission_run_types import MissionScheduleSyncFailedEvent
from modules.backend.models.mission import Mission, MissionStatus
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.models.mission_schedule import (
    MissionSchedule,
    MissionScheduleCompletedReason,
    MissionScheduleStatus,
    TemporalSyncState,
)
from modules.backend.models.workflow_definition import WorkflowDefinition
from modules.backend.schemas.mission_schedule import MissionScheduleCreate, MissionScheduleUpdate
from modules.backend.services.mission_schedule import MissionScheduleService

UTC = timezone.utc
GRID_ANCHOR = datetime(2027, 1, 1, tzinfo=UTC)


class RecordingBus:
    """Event bus that keeps every published event."""

    def __init__(self) -> None:
        self.events: list[SessionEvent] = []

    async def publish(self, event: SessionEvent) -> None:
        self.events.append(event)

    async def publish_to_mission(self, mission_id: str, event: SessionEvent) -> None:
        self.events.append(event)


class FakeScheduleGateway:
    """In-memory TemporalScheduleGateway; matching times lie on a fixed grid."""

    def __init__(self, interval: timedelta = timedelta(hours=1)) -> None:
        self.interval = interval
        self.schedules: dict[str, Schedule] = {}
        self.extra_ids: set[str] = set()
        self.deleted: list[str] = []
        self.validate_calls = 0
        self.validate_times: list[datetime] | None = None
        self.validate_error: Exception | None = None
        self.upsert_error: Exception | None = None
        self.on_upsert: Callable[[str], Awaitable[None]] | None = None

    async def upsert(self, schedule_id: str, schedule: Schedule) -> None:
        if self.on_upsert is not None:
            await self.on_upsert(schedule_id)
        if self.upsert_error is not None:
            raise self.upsert_error
        self.schedules[schedule_id] = schedule

    async def set_paused(self, schedule_id: str, paused: bool, note: str) -> None:
        self.schedules[schedule_id].state.paused = paused

    async def delete(self, schedule_id: str) -> None:
        self.schedules.pop(schedule_id, None)
        self.extra_ids.discard(schedule_id)
        self.deleted.append(schedule_id)

    async def describe(self, schedule_id: str) -> SimpleNamespace | None:
        if schedule_id not in self.schedules:
            return None
        now = utc_now()
        times = await self.list_matching_times(schedule_id, now, now + 6 * self.interval)
        return SimpleNamespace(info=SimpleNamespace(next_action_times=times))

    async def list_matching_times(
        self, schedule_id: str, start: datetime, end: datetime
    ) -> list[datetime]:
        steps = -((GRID_ANCHOR - start) // self.interval)
        times = []
        t = GRID_ANCHOR + steps * self.interval
        while t <= end:
            if t >= start:
                times.append(t)
            t += self.interval
        return times

    async def list_ids(self, prefix: str | None) -> list[str]:
        ids = set(self.schedules) | self.extra_ids
        return sorted(i for i in ids if prefix is None or i.startswith(prefix))

    async def validate_spec(self, spec: ScheduleSpec, window: timedelta) -> list[datetime]:
        self.validate_calls += 1
        if self.validate_error is not None:
            raise self.validate_error
        if self.validate_times is not None:
            return self.validate_times
        return [GRID_ANCHOR, GRID_ANCHOR + self.interval]


def _objective(name: str = "hourly", **overrides) -> MissionScheduleCreate:
    fields = {
        "name": name,
        "kind": "objective",
        "objective_template": "Run {sequence} of {mission_name} at {scheduled_for}",
        "cron_expression": "0 * * * *",
        "time_zone_name": "UTC",
    }
    fields.update(overrides)
    return MissionScheduleCreate(**fields)


@pytest.fixture
def gateway() -> FakeScheduleGateway:
    return FakeScheduleGateway()


@pytest.fixture
def bus() -> RecordingBus:
    return RecordingBus()


@pytest.fixture
async def service(db_session_factory, gateway, bus):
    async with db_session_factory() as session:
        yield MissionScheduleService(session, gateway, bus)


async def _set(db_session_factory, model, row_id: str, **values) -> None:
    async with db_session_factory() as session:
        await session.execute(update(model).where(model.id == row_id).values(**values))
        await session.commit()


async def _load(db_session_factory, schedule_id: str) -> MissionSchedule:
    async with db_session_factory() as session:
        return await session.get(MissionSchedule, schedule_id)


async def test_create_rejects_when_recurrence_disabled(
    service, gateway, committed_owner, monkeypatch
) -> None:
    user, mission, _plan = await committed_owner()
    monkeypatch.setattr(get_app_config().missions.recurrence, "enabled", False)
    with pytest.raises(ValidationError, match="recurrence disabled"):
        await service.create_schedule(mission.id, _objective(), user.id)
    assert gateway.validate_calls == 0


async def test_create_rejects_interactive_gate_mode(
    service, committed_owner, db_session_factory
) -> None:
    user, mission, plan = await committed_owner()
    await _set(db_session_factory, MissionPlan, plan.id, gate_mode=GateMode.INTERACTIVE)
    with pytest.raises(ValidationError, match="interactive"):
        await service.create_schedule(mission.id, _objective(), user.id)


async def test_create_rejects_unknown_placeholder(service, committed_owner) -> None:
    user, mission, _plan = await committed_owner()
    with pytest.raises(ValidationError, match="foo"):
        await service.create_schedule(
            mission.id, _objective(objective_template="Do {foo}"), user.id
        )


async def test_create_rejects_non_agent_steps(service, committed_owner, db_session_factory) -> None:
    user, mission, _plan = await committed_owner()
    async with db_session_factory() as session:
        definition = WorkflowDefinition(
            mission_id=mission.id,
            name="mixed",
            description="agent then human",
            objective={"statement": "s", "category": "c", "owner": "o", "priority": "low"},
            steps=[
                {"id": "research", "node_type": "agent_step", "capability": "research.web"},
                {
                    "id": "sign-off",
                    "node_type": "human_input",
                    "human_input_config": {"prompt_message": "ok?"},
                    "depends_on": ["research"],
                },
            ],
        )
        session.add(definition)
        await session.commit()
        definition_id = definition.id

    data = MissionScheduleCreate(
        name="wf",
        kind="workflow_definition",
        workflow_definition_id=definition_id,
        cron_expression="0 * * * *",
        time_zone_name="UTC",
    )
    with pytest.raises(ValidationError, match="sign-off"):
        await service.create_schedule(mission.id, data, user.id)


async def test_create_rejects_sub_minimum_interval(
    service, gateway, committed_owner, monkeypatch
) -> None:
    user, mission, _plan = await committed_owner()
    monkeypatch.setattr(get_app_config().missions.recurrence, "min_interval_seconds", 300)
    gateway.validate_times = [GRID_ANCHOR + timedelta(seconds=60 * i) for i in range(3)]
    with pytest.raises(ValidationError, match="cron fires every 60s; minimum 300s"):
        await service.create_schedule(mission.id, _objective(), user.id)


async def test_create_probes_before_db_access(
    service, gateway, committed_owner, db_engine: AsyncEngine
) -> None:
    user, mission, _plan = await committed_owner()
    gateway.validate_error = ValidationError("bad cron")
    statements: list[str] = []

    def record(_conn, _cursor, statement, *_args) -> None:
        statements.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", record)
    try:
        with pytest.raises(ValidationError, match="bad cron"):
            await service.create_schedule(mission.id, _objective(), user.id)
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", record)
    assert statements == []


async def test_create_commits_before_sync(
    service, gateway, committed_owner, db_session_factory
) -> None:
    user, mission, _plan = await committed_owner()
    seen: list[MissionSchedule | None] = []

    async def check_visible(temporal_id: str) -> None:
        async with db_session_factory() as other:
            seen.append(
                await other.scalar(
                    select(MissionSchedule).where(
                        MissionSchedule.temporal_schedule_id == temporal_id
                    )
                )
            )

    gateway.on_upsert = check_visible
    schedule = await service.create_schedule(mission.id, _objective(), user.id)
    assert len(seen) == 1 and seen[0] is not None
    assert seen[0].id == schedule.id
    assert schedule.temporal_sync_state == TemporalSyncState.SYNCED
    assert schedule.tick_config_hash


async def test_sync_failure_marks_failed_and_returns_row(
    service, gateway, bus, committed_owner, db_session_factory
) -> None:
    user, mission, _plan = await committed_owner()
    gateway.upsert_error = RPCError(
        "upstream refused bot123:secret", RPCStatusCode.UNAVAILABLE, b""
    )
    schedule = await service.create_schedule(mission.id, _objective(), user.id)

    stored = await _load(db_session_factory, schedule.id)
    assert stored.temporal_sync_state == TemporalSyncState.FAILED
    assert "<redacted>" in stored.temporal_sync_error
    assert "123:secret" not in stored.temporal_sync_error
    failed = [e for e in bus.events if isinstance(e, MissionScheduleSyncFailedEvent)]
    assert len(failed) == 1 and "123:secret" not in failed[0].error


async def test_effective_state_paused_when_mission_paused(
    service, gateway, committed_owner, db_session_factory
) -> None:
    user, mission, _plan = await committed_owner()
    schedule = await service.create_schedule(mission.id, _objective(), user.id)
    assert gateway.schedules[schedule.temporal_schedule_id].state.paused is False

    await _set(db_session_factory, Mission, mission.id, status=MissionStatus.PAUSED)
    assert await service.sync_to_temporal(schedule.id) == TemporalSyncState.SYNCED
    state = gateway.schedules[schedule.temporal_schedule_id].state
    assert state.paused is True
    assert state.note == "mission_paused"


async def test_get_for_other_mission_404(service, committed_owner) -> None:
    user, mission, _plan = await committed_owner()
    _other_user, other_mission, _other_plan = await committed_owner()
    schedule = await service.create_schedule(mission.id, _objective(), user.id)
    with pytest.raises(NotFoundError):
        await service.get_schedule(other_mission.id, schedule.id)


async def test_update_cron_resets_watermark(service, committed_owner, db_session_factory) -> None:
    user, mission, _plan = await committed_owner()
    schedule = await service.create_schedule(mission.id, _objective(), user.id)
    old = datetime(2020, 1, 1, tzinfo=UTC)
    await _set(db_session_factory, MissionSchedule, schedule.id, last_claimed_scheduled_for=old)
    before = utc_now()

    await service.update_schedule(
        mission.id, schedule.id, MissionScheduleUpdate(cron_expression="30 * * * *"), user.id
    )
    stored = await _load(db_session_factory, schedule.id)
    assert stored.cron_expression == "30 * * * *"
    assert stored.last_claimed_scheduled_for >= before


async def test_resume_resets_watermark(service, committed_owner, db_session_factory) -> None:
    user, mission, _plan = await committed_owner()
    schedule = await service.create_schedule(mission.id, _objective(), user.id)
    await service.pause_schedule(mission.id, schedule.id, user.id)
    old = datetime(2020, 1, 1, tzinfo=UTC)
    await _set(db_session_factory, MissionSchedule, schedule.id, last_claimed_scheduled_for=old)
    before = utc_now()

    await service.resume_schedule(mission.id, schedule.id, user.id)
    stored = await _load(db_session_factory, schedule.id)
    assert stored.status == MissionScheduleStatus.ACTIVE
    assert stored.last_claimed_scheduled_for >= before


async def test_sync_all_completes_end_date_and_deletes_orphans(
    service, gateway, committed_owner, db_session_factory
) -> None:
    user, mission, _plan = await committed_owner()
    ending = await service.create_schedule(
        mission.id, _objective("ending", ends_at=utc_now() + timedelta(days=1)), user.id
    )
    kept = await service.create_schedule(mission.id, _objective("kept"), user.id)
    await _set(
        db_session_factory, MissionSchedule, ending.id, ends_at=utc_now() - timedelta(minutes=1)
    )
    orphan = f"mission-schedule-{uuid4()}"
    probe = "mission-schedule-probe-x"
    gateway.extra_ids |= {orphan, probe}

    stats = await service.sync_all()

    stored = await _load(db_session_factory, ending.id)
    assert stored.status == MissionScheduleStatus.COMPLETED
    assert stored.completed_reason == MissionScheduleCompletedReason.END_DATE_REACHED
    assert stats.completed >= 1
    assert ending.temporal_schedule_id not in gateway.schedules
    assert orphan in gateway.deleted and probe in gateway.deleted
    assert stats.deleted_orphans >= 2
    assert kept.temporal_schedule_id in gateway.schedules
    assert kept.temporal_schedule_id not in gateway.deleted
