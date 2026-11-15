"""Schedule completion and reactivation (Plan 88 step 88.4.7, contract 3.2.3).

The repositories, session and Temporal gateway are fakes. sync_to_temporal runs
for real in the sync_all test, so the Temporal delete is the one the service
makes for a COMPLETED row. The real-database path is covered by
tests/integration/backend/services/test_mission_schedule_service.py.
"""

import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.backend.core.exceptions import ConflictError
from modules.backend.core.utils import utc_now
from modules.backend.events.mission_run_types import MissionScheduleChangedEvent
from modules.backend.models.mission import MissionStatus
from modules.backend.models.mission_schedule import (
    MissionSchedule,
    MissionScheduleCompletedReason,
    MissionScheduleKind,
    MissionScheduleStatus,
    TemporalSyncState,
)
from modules.backend.schemas.mission_schedule import MissionScheduleUpdate
from modules.backend.services.mission_schedule import MissionScheduleService

_MOD = "modules.backend.services.mission_schedule"
MISSION_ID = str(uuid.uuid4())
USER_ID = str(uuid.uuid4())


def _schedule(**values) -> MissionSchedule:
    schedule_id = str(uuid.uuid4())
    fields = {
        "id": schedule_id,
        "mission_id": MISSION_ID,
        "name": "hourly",
        "kind": MissionScheduleKind.OBJECTIVE,
        "objective_template": "Run {sequence}",
        "workflow_parameters": {},
        "cron_expression": "0 * * * *",
        "time_zone_name": "UTC",
        "starts_at": None,
        "ends_at": None,
        "max_runs": None,
        "executed_run_count": 0,
        "catch_up_window_seconds": 60,
        "status": MissionScheduleStatus.ACTIVE,
        "completed_reason": None,
        "temporal_schedule_id": f"mission-schedule-{schedule_id}",
        "temporal_sync_state": TemporalSyncState.SYNCED,
        "last_claimed_scheduled_for": utc_now() - timedelta(days=30),
    }
    fields.update(values)
    return MissionSchedule(**fields)


def _service(rows: list[MissionSchedule]) -> tuple[MissionScheduleService, MagicMock, MagicMock]:
    session = MagicMock(commit=AsyncMock(), refresh=AsyncMock())
    gateway = MagicMock(
        delete=AsyncMock(),
        upsert=AsyncMock(),
        list_ids=AsyncMock(return_value=[]),
        validate_spec=AsyncMock(return_value=[]),
    )
    bus = MagicMock(publish_to_mission=AsyncMock())
    svc = MissionScheduleService(session, gateway, bus)
    by_id = {row.id: row for row in rows}
    svc._schedule_repo = MagicMock(
        list_syncable=AsyncMock(return_value=list(rows)),
        lock=AsyncMock(side_effect=lambda sid: by_id.get(sid)),
        get_by_id=AsyncMock(side_effect=lambda sid: by_id[sid]),
        get_for_mission=AsyncMock(side_effect=lambda mid, sid: by_id.get(sid)),
        list_temporal_schedule_ids=AsyncMock(
            return_value={row.temporal_schedule_id for row in rows}
        ),
    )
    svc._mission_repo = MagicMock(
        get_by_id=AsyncMock(return_value=MagicMock(status=MissionStatus.ACTIVE.value))
    )
    return svc, gateway, bus


def _changed(bus: MagicMock) -> list[MissionScheduleChangedEvent]:
    return [
        c.args[1]
        for c in bus.publish_to_mission.await_args_list
        if isinstance(c.args[1], MissionScheduleChangedEvent)
    ]


async def _update(
    svc: MissionScheduleService, schedule: MissionSchedule, **fields
) -> MissionSchedule:
    with (
        patch(f"{_MOD}.check_update_target", AsyncMock()),
        patch.object(svc, "sync_to_temporal", AsyncMock(return_value=TemporalSyncState.SYNCED)),
    ):
        return await svc.update_schedule(
            MISSION_ID, schedule.id, MissionScheduleUpdate(**fields), USER_ID
        )


async def test_sync_all_completes_end_date_and_deletes_temporal():
    expired = _schedule(ends_at=utc_now() - timedelta(minutes=1))
    paused = _schedule(
        status=MissionScheduleStatus.PAUSED, ends_at=utc_now() - timedelta(minutes=1)
    )
    live = _schedule(ends_at=utc_now() + timedelta(days=1))
    svc, gateway, bus = _service([expired, paused, live])

    with patch(f"{_MOD}.build_tick_config_snapshot", MagicMock(config_hash="h")):
        stats = await svc.sync_all()

    for row in (expired, paused):
        assert row.status == MissionScheduleStatus.COMPLETED
        assert row.completed_reason == MissionScheduleCompletedReason.END_DATE_REACHED
    assert live.status == MissionScheduleStatus.ACTIVE
    deleted = [c.args[0] for c in gateway.delete.await_args_list]
    assert sorted(deleted) == sorted([expired.temporal_schedule_id, paused.temporal_schedule_id])
    assert live.temporal_schedule_id not in deleted
    assert stats.completed == 2
    assert stats.synced == 3
    events = _changed(bus)
    assert {(e.schedule_id, e.from_status) for e in events} == {
        (expired.id, "active"),
        (paused.id, "paused"),
    }
    assert all(e.to_status == "completed" for e in events)
    assert all(e.completed_reason == "end_date_reached" for e in events)


async def test_update_raising_max_runs_reactivates():
    watermark = utc_now() - timedelta(days=30)
    schedule = _schedule(
        status=MissionScheduleStatus.COMPLETED,
        completed_reason=MissionScheduleCompletedReason.MAX_RUNS_REACHED,
        max_runs=3,
        executed_run_count=3,
        last_claimed_scheduled_for=watermark,
    )
    svc, _gateway, bus = _service([schedule])

    await _update(svc, schedule, max_runs=5)

    assert schedule.status == MissionScheduleStatus.ACTIVE
    assert schedule.completed_reason is None
    assert schedule.last_claimed_scheduled_for > watermark
    assert [(e.from_status, e.to_status) for e in _changed(bus)] == [("completed", "active")]


async def test_update_future_end_date_reactivates():
    schedule = _schedule(
        status=MissionScheduleStatus.COMPLETED,
        completed_reason=MissionScheduleCompletedReason.END_DATE_REACHED,
        ends_at=utc_now() - timedelta(days=1),
    )
    svc, _gateway, bus = _service([schedule])

    await _update(svc, schedule, ends_at=utc_now() + timedelta(days=7))

    assert schedule.status == MissionScheduleStatus.ACTIVE
    assert schedule.completed_reason is None
    assert [(e.from_status, e.to_status) for e in _changed(bus)] == [("completed", "active")]


@pytest.mark.parametrize(
    ("values", "update"),
    [
        (
            {
                "completed_reason": MissionScheduleCompletedReason.MAX_RUNS_REACHED,
                "max_runs": 3,
                "executed_run_count": 3,
            },
            {"max_runs": 3},
        ),
        (
            {
                "completed_reason": MissionScheduleCompletedReason.MAX_RUNS_REACHED,
                "max_runs": 3,
                "executed_run_count": 3,
            },
            {"name": "renamed"},
        ),
        (
            {
                "completed_reason": MissionScheduleCompletedReason.END_DATE_REACHED,
                "ends_at": utc_now() - timedelta(days=1),
            },
            {"ends_at": utc_now() - timedelta(hours=1)},
        ),
        (
            {
                "completed_reason": MissionScheduleCompletedReason.MAX_RUNS_REACHED,
                "max_runs": 3,
                "executed_run_count": 3,
                "ends_at": utc_now() - timedelta(days=1),
            },
            {"max_runs": 10},
        ),
    ],
    ids=["same-max-runs", "unrelated-field", "past-end-date", "more-runs-but-ended"],
)
async def test_update_completed_without_relief_stays_completed(values, update):
    schedule = _schedule(status=MissionScheduleStatus.COMPLETED, **values)
    reason = schedule.completed_reason
    svc, _gateway, bus = _service([schedule])

    await _update(svc, schedule, **update)

    assert schedule.status == MissionScheduleStatus.COMPLETED
    assert schedule.completed_reason == reason
    assert _changed(bus) == []


async def test_archive_archived_conflict():
    schedule = _schedule(status=MissionScheduleStatus.ARCHIVED)
    svc, gateway, _bus = _service([schedule])

    with pytest.raises(ConflictError):
        await svc.archive_schedule(MISSION_ID, schedule.id, USER_ID)

    gateway.delete.assert_not_awaited()


@pytest.mark.parametrize(
    "status",
    [
        MissionScheduleStatus.ACTIVE,
        MissionScheduleStatus.PAUSED,
        MissionScheduleStatus.COMPLETED,
    ],
)
async def test_archive_deletes_temporal_from_any_live_status(status):
    schedule = _schedule(status=status)
    svc, gateway, _bus = _service([schedule])

    await svc.archive_schedule(MISSION_ID, schedule.id, USER_ID)

    assert schedule.status == MissionScheduleStatus.ARCHIVED
    gateway.delete.assert_awaited_once_with(schedule.temporal_schedule_id)
