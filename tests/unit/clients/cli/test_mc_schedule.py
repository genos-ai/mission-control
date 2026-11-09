"""`mc schedule` (Plan 88 step 88.1.13, contracts 3.5.4): thin client over the schedule API."""

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import patch

from click.testing import CliRunner

from modules.clients.cli.mc_groups.schedule import schedule

MISSION_ID = "22222222-2222-2222-2222-222222222222"
SCHEDULE_ID = "33333333-3333-3333-3333-333333333333"
WORKFLOW_ID = "44444444-4444-4444-4444-444444444444"


class FakeApi:
    """Answers GET by exact path from `routes`, records every call; any other path fails."""

    def __init__(self, routes: dict[str, Any] | None = None, reply: Any = None):
        self.routes = routes or {}
        self.reply = reply if reply is not None else {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def get_current_mission_id(self) -> str:
        return MISSION_ID

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append(("GET", path, {"params": params}))
        if path not in self.routes:
            raise AssertionError(f"unexpected GET {path}")
        return self.routes[path]

    async def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        self.calls.append(("POST", path, {"body": body}))
        return self.reply

    async def patch(self, path: str, body: dict[str, Any] | None = None) -> Any:
        self.calls.append(("PATCH", path, {"body": body}))
        return self.reply

    async def delete(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append(("DELETE", path, {"params": params}))
        return self.reply

    def last(self, method: str) -> tuple[str, dict[str, Any]]:
        matches = [(path, kw) for m, path, kw in self.calls if m == method]
        assert matches, f"no {method} call"
        return matches[-1]


def patch_api(module: str, api: FakeApi):
    """Patch `api_client` in a click group module to yield `api`."""

    @asynccontextmanager
    async def _client():
        yield api

    return patch(f"{module}.api_client", _client)


def _schedule(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": SCHEDULE_ID,
        "name": "daily",
        "kind": "objective",
        "status": "active",
        "objective_template": "Check {mission_name}",
        "workflow_definition_id": None,
        "workflow_parameters": {},
        "cron_expression": "0 6 * * *",
        "time_zone_name": "Europe/London",
        "max_runs": None,
        "executed_run_count": 0,
        "catch_up_window_seconds": 21600,
        "temporal_schedule_id": f"mission-schedule-{SCHEDULE_ID}",
        "temporal_sync_state": "synced",
        "temporal_sync_error": None,
        "next_fire_times": [],
    }
    row.update(overrides)
    return row


def _invoke(api: FakeApi, args: list[str]):
    with patch_api("modules.clients.cli.mc_groups.schedule", api):
        return CliRunner().invoke(schedule, args)


def test_create_objective_payload():
    api = FakeApi(reply=_schedule())
    result = _invoke(
        api,
        [
            "create",
            "daily",
            "--cron",
            "0 6 * * *",
            "--tz",
            "Europe/London",
            "--objective",
            "Check {mission_name}",
            "--catch-up-window",
            "6h",
        ],
    )

    assert result.exit_code == 0, result.output
    path, kwargs = api.last("POST")
    assert path == f"/missions/{MISSION_ID}/schedules"
    assert kwargs["body"] == {
        "name": "daily",
        "kind": "objective",
        "objective_template": "Check {mission_name}",
        "cron_expression": "0 6 * * *",
        "time_zone_name": "Europe/London",
        "catch_up_window_seconds": 21600,
    }


def test_create_workflow_resolves_name_and_params():
    api = FakeApi(
        routes={
            f"/missions/{MISSION_ID}/workflows": {
                "workflows": [
                    {"id": "55555555-5555-5555-5555-555555555555", "name": "audit-v2"},
                    {"id": WORKFLOW_ID, "name": "audit"},
                ]
            }
        },
        reply=_schedule(kind="workflow_definition"),
    )
    result = _invoke(
        api,
        [
            "create",
            "weekly",
            "--cron",
            "0 9 * * 1",
            "--tz",
            "UTC",
            "--workflow",
            "audit",
            "--param",
            "depth=2",
            "--param",
            "scope=src/a=b",
        ],
    )

    assert result.exit_code == 0, result.output
    _, kwargs = api.last("POST")
    body = kwargs["body"]
    assert body["kind"] == "workflow_definition"
    assert body["workflow_definition_id"] == WORKFLOW_ID
    assert body["workflow_parameters"] == {"depth": "2", "scope": "src/a=b"}
    assert "objective_template" not in body


def test_unknown_name_exits_1():
    api = FakeApi(
        routes={f"/missions/{MISSION_ID}/schedules": {"schedules": [_schedule(name="daily")]}}
    )
    result = _invoke(api, ["pause", "nightly"])

    assert result.exit_code == 1
    assert "Schedule 'nightly' not found" in result.output
    _, kwargs = api.last("GET")
    assert kwargs["params"] == {"include_archived": "true"}
    assert not [c for c in api.calls if c[0] == "POST"]


def test_show_prints_sync_failed():
    failed = _schedule(
        temporal_sync_state="failed",
        temporal_sync_error="temporal unavailable",
        next_fire_times=["2027-07-05T05:00:00Z"],
    )
    api = FakeApi(
        routes={
            f"/missions/{MISSION_ID}/schedules": {"schedules": [failed]},
            f"/missions/{MISSION_ID}/schedules/{SCHEDULE_ID}": failed,
        }
    )
    result = _invoke(api, ["show", "daily"])

    assert result.exit_code == 0, result.output
    assert "failed" in result.output
    assert "temporal unavailable" in result.output
    assert "2027-07-05T05:00:00Z" in result.output


def test_edit_sends_only_given_flags():
    api = FakeApi(
        routes={f"/missions/{MISSION_ID}/schedules": {"schedules": [_schedule()]}},
        reply=_schedule(),
    )
    result = _invoke(api, ["edit", "daily", "--cron", "30 6 * * *"])

    assert result.exit_code == 0, result.output
    path, kwargs = api.last("PATCH")
    assert path == f"/missions/{MISSION_ID}/schedules/{SCHEDULE_ID}"
    assert kwargs["body"] == {"cron_expression": "30 6 * * *"}


def test_bad_catch_up_window_rejected():
    api = FakeApi()
    result = _invoke(
        api,
        [
            "create",
            "d",
            "--cron",
            "0 6 * * *",
            "--tz",
            "UTC",
            "--objective",
            "x",
            "--catch-up-window",
            "6 hours",
        ],
    )

    assert result.exit_code != 0
    assert not api.calls
