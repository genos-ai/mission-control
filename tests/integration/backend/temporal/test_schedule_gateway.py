"""TemporalScheduleGateway against a local Temporal dev server (Plan 88 step 88.1.5)."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from temporalio.client import Schedule, ScheduleActionStartWorkflow, ScheduleSpec, ScheduleState
from temporalio.testing import WorkflowEnvironment

from modules.backend.core.exceptions import ValidationError
from modules.backend.temporal.schedule_gateway import PROBE_PREFIX, TemporalScheduleGateway

_QUEUE = "p88-schedule-gateway-test"
_LONDON = ZoneInfo("Europe/London")


@pytest.fixture
def gateway(temporal_env: WorkflowEnvironment) -> TemporalScheduleGateway:
    return TemporalScheduleGateway(temporal_env.client, _QUEUE)


def _schedule(schedule_id: str, cron: str, time_zone: str | None = None) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            "MissionScheduleProbe", id=f"{schedule_id}-wf", task_queue=_QUEUE
        ),
        spec=ScheduleSpec(cron_expressions=[cron], time_zone_name=time_zone),
        state=ScheduleState(paused=True),
    )


def _schedule_id() -> str:
    return f"p88-gateway-test-{uuid4().hex[:8]}"


async def test_upsert_creates_then_updates(gateway: TemporalScheduleGateway) -> None:
    schedule_id = _schedule_id()
    try:
        await gateway.upsert(schedule_id, _schedule(schedule_id, "0 * * * *"))
        await gateway.upsert(schedule_id, _schedule(schedule_id, "30 * * * *"))
        desc = await gateway.describe(schedule_id)
        assert desc is not None
        # The server normalises cron_expressions into calendars on describe.
        (calendar,) = desc.schedule.spec.calendars
        assert [(r.start, r.end) for r in calendar.minute] == [(30, 30)]
    finally:
        await gateway.delete(schedule_id)
    assert await gateway.describe(schedule_id) is None


async def test_delete_missing_is_noop(gateway: TemporalScheduleGateway) -> None:
    await gateway.delete(_schedule_id())


async def test_list_matching_times_respects_time_zone(gateway: TemporalScheduleGateway) -> None:
    schedule_id = _schedule_id()
    start = datetime(2027, 7, 4, 0, 0, tzinfo=timezone.utc)
    try:
        await gateway.upsert(schedule_id, _schedule(schedule_id, "0 6 * * 1", "Europe/London"))
        times = await gateway.list_matching_times(schedule_id, start, start + timedelta(days=14))
    finally:
        await gateway.delete(schedule_id)

    # 06:00 BST on Mondays 5 and 12 July 2027 is 05:00 UTC.
    assert times == [
        datetime(2027, 7, 5, 5, 0, tzinfo=timezone.utc),
        datetime(2027, 7, 12, 5, 0, tzinfo=timezone.utc),
    ]
    assert all(t.astimezone(_LONDON).hour == 6 for t in times)


async def test_validate_spec_rejects_bad_cron(gateway: TemporalScheduleGateway) -> None:
    with pytest.raises(ValidationError):
        await gateway.validate_spec(
            ScheduleSpec(cron_expressions=["61 * * * *"]), timedelta(days=1)
        )
    assert await gateway.list_ids(PROBE_PREFIX) == []


async def test_validate_spec_returns_times_and_cleans_up(
    gateway: TemporalScheduleGateway,
) -> None:
    times = await gateway.validate_spec(
        ScheduleSpec(cron_expressions=["0 * * * *"], time_zone_name="Europe/London"),
        timedelta(days=1),
    )
    assert len(times) == 24
    assert all(t.tzinfo == timezone.utc and t.minute == 0 for t in times)
    assert await gateway.list_ids(PROBE_PREFIX) == []
