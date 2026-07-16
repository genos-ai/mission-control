"""Tests for the `mc schedule` CLI group (Plan 83).

`mc schedule` is a strict thin client — every command goes through the
REST API via CliApiClient with zero backend-service imports. These tests
verify (1) command wiring / dispatch with a mocked API client (P11: no
real services, no LLM), and (2) the thin-client contract statically.

The backend REST endpoints and WorkflowScheduleService lifecycle are
covered separately against real Postgres
(tests/unit/backend/services/test_workflow_schedule.py).
"""

from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

# A full UUID short-circuits resolve_short_id (no list call needed).
FULL_ID = "11111111-1111-1111-1111-111111111111"
MISSION_ID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def fake_api():
    """A CliApiClient stand-in whose HTTP methods are AsyncMocks."""
    api = AsyncMock()
    api.get = AsyncMock(return_value={"schedules": [], "total": 0})
    api.post = AsyncMock(
        return_value={
            "id": FULL_ID,
            "cron_expression": "0 9 * * *",
            "next_fire_at": "2026-07-05T09:00:00",
        }
    )
    api.patch = AsyncMock(return_value={"id": FULL_ID, "enabled": False})
    api.delete = AsyncMock(return_value={"deleted": FULL_ID})
    return api


@pytest.fixture
def patched_mc(fake_api):
    """Patch mc.api_client (async ctx-mgr) + mc.require_mission for wiring tests."""

    @asynccontextmanager
    async def _fake_client(*_a, **_k):
        yield fake_api

    with (
        patch("mc.api_client", _fake_client),
        patch("mc.require_mission", AsyncMock(return_value=MISSION_ID)),
    ):
        yield fake_api


# =============================================================================
# Wiring / help
# =============================================================================


class TestScheduleGroupWiring:
    def test_group_registered_with_all_subcommands(self, runner):
        from mc import mc

        result = runner.invoke(mc, ["schedule", "--help"])
        assert result.exit_code == 0
        for sub in ("list", "create", "enable", "disable", "delete"):
            assert sub in result.output

    def test_create_help_lists_flags(self, runner):
        from mc import mc

        result = runner.invoke(mc, ["schedule", "create", "--help"])
        assert result.exit_code == 0
        for flag in ("--workflow", "--cron", "--budget", "--max-iterations", "--cooldown"):
            assert flag in result.output


# =============================================================================
# Dispatch — each command calls the right REST method
# =============================================================================


class TestScheduleDispatch:
    def test_list_empty(self, runner, patched_mc):
        from mc import mc

        result = runner.invoke(mc, ["schedule", "list"])
        assert result.exit_code == 0
        assert "No schedules" in result.output
        patched_mc.get.assert_awaited_once()

    def test_list_json(self, runner, patched_mc):
        from mc import mc

        result = runner.invoke(mc, ["schedule", "list", "--json"])
        assert result.exit_code == 0
        assert '"schedules"' in result.output

    def test_create_posts_and_omits_none(self, runner, patched_mc):
        from mc import mc

        result = runner.invoke(
            mc,
            ["schedule", "create", "--workflow", "wf-1", "--cron", "0 9 * * *"],
        )
        assert result.exit_code == 0
        patched_mc.post.assert_awaited_once()
        _, kwargs = patched_mc.post.call_args
        body = kwargs["body"]
        assert body["workflow_definition_id"] == "wf-1"
        assert body["cron_expression"] == "0 9 * * *"
        # Optional numeric fields omitted (backend schema is extra="forbid").
        assert "budget_per_run_usd" not in body
        assert "max_iterations" not in body

    def test_create_includes_optional_values(self, runner, patched_mc):
        from mc import mc

        result = runner.invoke(
            mc,
            [
                "schedule",
                "create",
                "--workflow",
                "wf-1",
                "--cron",
                "0 9 * * *",
                "--budget",
                "5.0",
                "--max-iterations",
                "3",
                "--description",
                "nightly",
            ],
        )
        assert result.exit_code == 0
        _, kwargs = patched_mc.post.call_args
        body = kwargs["body"]
        assert body["budget_per_run_usd"] == 5.0
        assert body["max_iterations"] == 3
        assert body["description"] == "nightly"

    def test_enable_patches_enabled_true(self, runner, patched_mc):
        from mc import mc

        result = runner.invoke(mc, ["schedule", "enable", FULL_ID])
        assert result.exit_code == 0
        _, kwargs = patched_mc.patch.call_args
        assert kwargs["body"] == {"enabled": True}

    def test_disable_patches_enabled_false(self, runner, patched_mc):
        from mc import mc

        result = runner.invoke(mc, ["schedule", "disable", FULL_ID])
        assert result.exit_code == 0
        _, kwargs = patched_mc.patch.call_args
        assert kwargs["body"] == {"enabled": False}

    def test_delete_calls_delete(self, runner, patched_mc):
        from mc import mc

        result = runner.invoke(mc, ["schedule", "delete", FULL_ID])
        assert result.exit_code == 0
        patched_mc.delete.assert_awaited_once()
        assert FULL_ID in patched_mc.delete.call_args.args[0]


# =============================================================================
# Thin-client contract (rule 008.x)
# =============================================================================


def test_no_backend_service_imports():
    """mc_schedule.py must not import backend services (thin-client rule 008.x)."""
    src = Path("modules/clients/cli/mc_schedule.py").read_text()
    assert "modules.backend.services" not in src
    assert "modules.backend" not in src
