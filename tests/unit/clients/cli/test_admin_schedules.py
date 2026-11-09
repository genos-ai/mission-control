"""admin schedules sync (Plan 88 step 88.1.13): MissionScheduleService in-process, no HTTP."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from modules.backend.temporal.mission_run_models import ScheduleSyncStats


def _service(stats: ScheduleSyncStats) -> MagicMock:
    svc = MagicMock()
    svc.sync_all = AsyncMock(return_value=stats)
    svc.sync_mission = AsyncMock(return_value=stats)
    return svc


def _patch_service(svc: MagicMock):
    @asynccontextmanager
    async def _schedule_service():
        yield svc, MagicMock()

    return patch(
        "modules.backend.temporal.mission_schedule_activities.schedule_service",
        _schedule_service,
    )


def _no_http():
    return patch(
        "modules.clients.cli.api_client.CliApiClient._request",
        AsyncMock(side_effect=AssertionError("admin schedules sync made an HTTP call")),
    )


def test_admin_schedules_sync_calls_service_in_process():
    from admin import admin_cli

    svc = _service(ScheduleSyncStats(synced=3, failed=1, deleted_orphans=2, completed=4))
    with _patch_service(svc), _no_http() as request:
        result = CliRunner().invoke(admin_cli, ["schedules", "sync"])

    assert result.exit_code == 0, result.output
    svc.sync_all.assert_awaited_once_with()
    svc.sync_mission.assert_not_awaited()
    request.assert_not_awaited()
    for value in ("3", "1", "2", "4"):
        assert value in result.output


def test_admin_schedules_sync_one_mission():
    from admin import admin_cli

    svc = _service(ScheduleSyncStats(synced=1, failed=0, deleted_orphans=0, completed=0))
    with _patch_service(svc), _no_http():
        result = CliRunner().invoke(admin_cli, ["schedules", "sync", "--mission", "m-1"])

    assert result.exit_code == 0, result.output
    svc.sync_mission.assert_awaited_once_with("m-1")
    svc.sync_all.assert_not_awaited()
