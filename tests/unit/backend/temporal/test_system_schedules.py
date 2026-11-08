"""Plan 88 step 88.0.10: system schedule registration (mock Temporal client)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from temporalio.client import ScheduleAlreadyRunningError, ScheduleOverlapPolicy, ScheduleUpdate

from modules.backend.core.config import get_app_config
from modules.backend.temporal.config_snapshots import config_hash
from modules.backend.temporal.mission_run_models import ReconcilerInput
from modules.backend.temporal.system_schedules import register_system_schedules


def _client() -> MagicMock:
    client = MagicMock()
    client.create_schedule = AsyncMock()
    handle = MagicMock()
    handle.update = AsyncMock()
    client.get_schedule_handle = MagicMock(return_value=handle)
    return client


@pytest.mark.asyncio
async def test_creates_reconciler_schedule_when_absent():
    client = _client()

    await register_system_schedules(client)

    client.create_schedule.assert_awaited_once()
    schedule_id, schedule = client.create_schedule.await_args.args
    assert schedule_id == "system-reconciler"
    assert schedule.spec.cron_expressions == ["*/5 * * * *"]
    assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
    assert schedule.action.id == "system-reconciler"
    assert schedule.action.task_queue == get_app_config().temporal.task_queue
    (arg,) = schedule.action.args
    assert isinstance(arg, ReconcilerInput)
    assert arg.orphan_grace_seconds == 600
    assert arg.config_hash == config_hash(arg)
    client.get_schedule_handle.assert_not_called()


@pytest.mark.asyncio
async def test_updates_existing_schedule():
    client = _client()
    client.create_schedule.side_effect = ScheduleAlreadyRunningError()

    await register_system_schedules(client)

    client.get_schedule_handle.assert_called_once_with("system-reconciler")
    handle = client.get_schedule_handle.return_value
    handle.update.assert_awaited_once()
    (updater,) = handle.update.await_args.args
    update = updater(MagicMock())
    assert isinstance(update, ScheduleUpdate)
    assert update.schedule.spec.cron_expressions == ["*/5 * * * *"]


@pytest.mark.asyncio
async def test_unknown_key_raises():
    temporal = get_app_config().temporal
    schedules = {**temporal.system_schedules, "bogus": temporal.system_schedules["reconciler"]}
    fake = SimpleNamespace(temporal=temporal.model_copy(update={"system_schedules": schedules}))
    client = _client()

    with (
        patch("modules.backend.temporal.system_schedules.get_app_config", return_value=fake),
        pytest.raises(RuntimeError, match="bogus"),
    ):
        await register_system_schedules(client)
