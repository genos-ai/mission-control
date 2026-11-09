"""admin reconcile run (Plan 88 step 88.1.10a): renders ReconcileStats in-process."""

from unittest.mock import AsyncMock, patch

from click.testing import CliRunner

from modules.backend.temporal.mission_run_models import ReconcileStats


def _stats() -> ReconcileStats:
    return ReconcileStats(
        examined_tasks=5,
        examined_execution_records=2,
        examined_workflow_runs=1,
        failed_tasks=0,
        failed_execution_records=1,
        failed_workflow_runs=0,
        left_running=3,
        left_in_process=2,
        schedule_sync=None,
        examined_mission_runs=7,
        failed_mission_runs=4,
    )


def test_admin_reconcile_run_renders_stats():
    from admin import admin_cli

    with patch(
        "modules.clients.cli.admin_groups.reconcile._reconcile",
        AsyncMock(return_value=_stats()),
    ) as reconcile:
        result = CliRunner().invoke(admin_cli, ["reconcile", "run"])

    assert result.exit_code == 0, result.output
    reconcile.assert_awaited_once()
    assert "Mission runs" in result.output
    assert "7" in result.output
    assert "4" in result.output
    assert "Left running: 3" in result.output
    assert "Left in-process: 2" in result.output
