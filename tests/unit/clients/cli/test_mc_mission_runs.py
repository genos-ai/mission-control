"""`mc runs`, `mc workflow-runs`, `mc run` and `mc tree` (Plan 88 step 88.1.13)."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

from click.testing import CliRunner

from modules.backend.core.config import get_app_config
from modules.clients.cli.mc_groups.runs import runs
from tests.unit.clients.cli.test_mc_schedule import MISSION_ID, FakeApi, patch_api

RUN_ID = "66666666-6666-6666-6666-666666666666"
PROJECT_ROOT = Path(__file__).resolve().parents[4]


def _run(**overrides):
    row = {
        "id": RUN_ID,
        "sequence": 37,
        "status": "running",
        "status_reason": None,
        "trigger": "schedule",
        "objective": "Check p88-live",
        "scheduled_for": "2027-07-05T05:00:00Z",
        "started_at": "2027-07-05T05:00:02Z",
        "cost_usd": 0.0123,
        "task_count": 1,
        "completed_task_count": 0,
        "failed_task_count": 0,
        "temporal_workflow_id": f"mission-run-{RUN_ID}",
    }
    row.update(overrides)
    return row


def _invoke(api: FakeApi, args: list[str]):
    with patch_api("modules.clients.cli.mc_groups.runs", api):
        return CliRunner().invoke(runs, args)


def _list_api() -> FakeApi:
    return FakeApi(
        routes={
            f"/missions/{MISSION_ID}/runs": {
                "runs": [_run()],
                "next_before_sequence": None,
            }
        }
    )


def test_runs_list_sends_configured_limit_when_omitted():
    api = _list_api()
    with patch.object(get_app_config().cli.mc, "runs_list_limit", 7):
        result = _invoke(api, ["list"])

    assert result.exit_code == 0, result.output
    path, kwargs = api.last("GET")
    assert path == f"/missions/{MISSION_ID}/runs"
    assert kwargs["params"]["limit"] == 7


def test_runs_list_sends_explicit_limit():
    api = _list_api()
    result = _invoke(api, ["list", "--limit", "5", "--status", "missed", "--status", "skipped"])

    assert result.exit_code == 0, result.output
    _, kwargs = api.last("GET")
    assert kwargs["params"] == {"limit": 5, "status": ["missed", "skipped"]}
    assert "37" in result.output


def test_runs_show_by_sequence():
    api = FakeApi(
        routes={
            f"/missions/{MISSION_ID}/runs/37": {
                "run": _run(),
                "digest": None,
                "tasks": [
                    {
                        "id": "t1",
                        "agent": "research.agent",
                        "description": "Look things up",
                        "status": "running",
                        "failure_reason": None,
                        "cost_usd": 0.01,
                    }
                ],
            }
        }
    )
    result = _invoke(api, ["show", "37"])

    assert result.exit_code == 0, result.output
    assert "Run #37" in result.output
    assert "research.agent" in result.output


def test_runs_digest_none_prints_no_digest_yet():
    api = FakeApi(
        routes={
            f"/missions/{MISSION_ID}/runs/37": {
                "run": _run(),
                "digest": None,
                "tasks": [],
            }
        }
    )
    result = _invoke(api, ["digest", "37"])

    assert result.exit_code == 0, result.output
    assert "No digest yet" in result.output


def test_runs_cancel_resolves_sequence_to_id():
    api = FakeApi(
        routes={
            f"/missions/{MISSION_ID}/runs/37": {
                "run": _run(),
                "digest": None,
                "tasks": [],
            }
        },
        reply=_run(),
    )
    result = _invoke(api, ["cancel", "37"])

    assert result.exit_code == 0, result.output
    path, _ = api.last("POST")
    assert path == f"/missions/{MISSION_ID}/runs/{RUN_ID}/cancel"


def test_workflow_runs_group_exists():
    from mc import mc

    assert "workflow-runs" in mc.commands
    assert set(mc.commands["workflow-runs"].commands) == {"list", "show", "cancel"}
    assert mc.commands["runs"] is runs


def test_mc_run_posts_runs_endpoint():
    from mc import mc

    api = FakeApi(routes={"/workflows": {"workflows": []}}, reply=_run(sequence=12))
    with (
        patch_api("mc", api),
        patch("modules.clients.cli.mc_run._stream_plan_progress", AsyncMock()) as stream,
    ):
        result = CliRunner().invoke(mc, ["run", "--objective", "audit the auth module"])

    assert result.exit_code == 0, result.output
    path, kwargs = api.last("POST")
    assert path == f"/missions/{MISSION_ID}/runs"
    assert kwargs["body"] == {"objective": "audit the auth module"}
    assert "Run #12 started" in result.output
    stream.assert_awaited_once()


def test_mc_run_rejects_deleted_options():
    from mc import mc

    for option in (["--gate", "manual"], ["--budget", "1"], ["--step"]):
        result = CliRunner().invoke(mc, ["run", "--objective", "x", *option])
        assert result.exit_code == 2, option


def test_tree_lists_new_groups():
    result = subprocess.run(
        [sys.executable, "mc.py", "tree"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "COLUMNS": "250"},
    )

    assert result.returncode == 0, result.stderr
    for text in ("schedule", "runs", "workflow-runs", "edit NAME"):
        assert text in result.stdout, text
