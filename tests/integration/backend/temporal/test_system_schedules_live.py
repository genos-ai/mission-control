"""System schedule registration against a local Temporal dev server (Plan 88 step 88.1.10)."""

import asyncio
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from temporalio.client import Schedule, ScheduleActionStartWorkflow, ScheduleSpec, ScheduleState
from temporalio.testing import WorkflowEnvironment

from modules.backend.core.config import get_app_config
from modules.backend.core.config_schema import SystemScheduleSchema
from modules.backend.temporal.schedule_gateway import TemporalScheduleGateway
from modules.backend.temporal.system_schedules import register_system_schedules


@pytest.fixture
async def gateway(
    temporal_env: WorkflowEnvironment,
) -> AsyncGenerator[TemporalScheduleGateway, None]:
    gw = TemporalScheduleGateway(temporal_env.client, get_app_config().temporal.task_queue)
    yield gw
    for sid in await gw.list_ids("system-"):
        await gw.delete(sid)


def _paused(schedule_id: str) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            "MissionScheduleTickWorkflow",
            id=f"{schedule_id}-wf",
            task_queue=get_app_config().temporal.task_queue,
        ),
        spec=ScheduleSpec(cron_expressions=["0 6 * * 1"]),
        state=ScheduleState(paused=True),
    )


async def _wait_listed(gateway: TemporalScheduleGateway, ids: set[str]) -> None:
    """Wait until ids appear in the eventually consistent schedule list (at most ~10s)."""
    for _ in range(100):
        if ids <= set(await gateway.list_ids(None)):
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"schedules never listed: {sorted(ids)}")


def _minutes(desc) -> list[tuple[int, int]]:
    # The server normalises cron_expressions into calendars on describe.
    (calendar,) = desc.schedule.spec.calendars
    return [(r.start, r.end) for r in calendar.minute]


async def test_register_updates_changed_cron(gateway: TemporalScheduleGateway) -> None:
    await register_system_schedules(gateway)
    first = await gateway.describe("system-hourly_health_check")
    assert first is not None
    assert _minutes(first) == [(0, 0)]

    temporal = get_app_config().temporal
    schedules = {
        **temporal.system_schedules,
        "hourly_health_check": SystemScheduleSchema(cron="30 * * * *"),
    }
    fake = SimpleNamespace(temporal=temporal.model_copy(update={"system_schedules": schedules}))
    with patch("modules.backend.temporal.system_schedules.get_app_config", return_value=fake):
        await register_system_schedules(gateway)

    second = await gateway.describe("system-hourly_health_check")
    assert second is not None
    assert _minutes(second) == [(30, 30)]


async def test_register_keeps_mission_schedules(gateway: TemporalScheduleGateway) -> None:
    mission_sid = f"mission-schedule-{uuid4().hex}"
    legacy_sid = "maintenance-daily-cleanup"
    await gateway.upsert(mission_sid, _paused(mission_sid))
    await gateway.upsert(legacy_sid, _paused(legacy_sid))
    try:
        await _wait_listed(gateway, {mission_sid, legacy_sid})
        await register_system_schedules(gateway)

        # describe, not list_ids: the schedule list is eventually consistent.
        assert await gateway.describe(mission_sid) is not None
        assert await gateway.describe(legacy_sid) is None
        for key in get_app_config().temporal.system_schedules:
            assert await gateway.describe(f"system-{key}") is not None
    finally:
        await gateway.delete(mission_sid)
        await gateway.delete(legacy_sid)
