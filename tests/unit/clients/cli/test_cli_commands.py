"""Tests for CLI command wiring.

Tests that Click commands parse options correctly, dispatch to the right
handler modules, and show help when invoked without required args.
Uses CliRunner so no real services are called.
"""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def _patch_cli_context():
    """Patch CliContext so Click commands don't trigger real logging/config."""
    with patch("admin.CliContext") as MockCtx:
        ctx = MagicMock()
        ctx.logger = MagicMock()
        ctx.output_format = "human"
        MockCtx.return_value = ctx
        yield ctx


class TestRootGroup:
    def test_help_shows_usage(self, runner):
        from admin import admin_cli as cli

        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Mission Control" in result.output

    def test_no_args_shows_help(self, runner):
        from admin import admin_cli as cli

        result = runner.invoke(cli, [])
        assert result.exit_code == 0
        assert "Mission Control" in result.output

    def test_verbose_flag_accepted(self, runner):
        from admin import admin_cli as cli

        result = runner.invoke(cli, ["-v", "--help"])
        assert result.exit_code == 0

    def test_output_format_flag(self, runner):
        from admin import admin_cli as cli

        result = runner.invoke(cli, ["-o", "json", "--help"])
        assert result.exit_code == 0


class TestSimpleCommands:
    def test_health_dispatches(self, runner):
        from admin import admin_cli as cli

        with patch("modules.clients.cli.health.check_health") as mock_fn:
            result = runner.invoke(cli, ["health"])
        mock_fn.assert_called_once()
        assert result.exit_code == 0

    def test_config_dispatches(self, runner):
        from admin import admin_cli as cli

        with patch("modules.clients.cli.config_display.show_config") as mock_fn:
            result = runner.invoke(cli, ["config"])
        mock_fn.assert_called_once()
        assert result.exit_code == 0

    def test_info_dispatches(self, runner):
        from admin import admin_cli as cli

        with patch("modules.clients.cli.info.show_info") as mock_fn:
            result = runner.invoke(cli, ["info"])
        mock_fn.assert_called_once()
        assert result.exit_code == 0


class TestMissionGroup:
    def test_mission_help(self, runner):
        from admin import admin_cli as cli

        result = runner.invoke(cli, ["mission", "--help"])
        assert result.exit_code == 0
        assert "create" in result.output
        assert "list" in result.output
        assert "detail" in result.output
        assert "archive" in result.output

    def test_mission_no_subcommand_shows_help(self, runner):
        from admin import admin_cli as cli

        result = runner.invoke(cli, ["mission"])
        assert result.exit_code == 0
        assert "create" in result.output

    def test_mission_create_dispatches(self, runner):
        from admin import admin_cli as cli

        with patch("modules.clients.cli.mission_cmds.run_mission") as mock_fn:
            result = runner.invoke(
                cli,
                [
                    "mission",
                    "create",
                    "--name",
                    "test-mission",
                    "--description",
                    "A test",
                ],
            )
        mock_fn.assert_called_once()
        call_kwargs = mock_fn.call_args
        assert call_kwargs[0][1] == "create"  # action arg
        assert call_kwargs[1]["name"] == "test-mission"
        assert result.exit_code == 0

    def test_mission_list_dispatches(self, runner):
        from admin import admin_cli as cli

        with patch("modules.clients.cli.mission_cmds.run_mission") as mock_fn:
            result = runner.invoke(cli, ["mission", "list"])
        mock_fn.assert_called_once()
        assert mock_fn.call_args[0][1] == "list"
        assert result.exit_code == 0

    def test_mission_archive_without_id(self, runner):
        from admin import admin_cli as cli

        result = runner.invoke(cli, ["mission", "archive"])
        # MISSION_ID is optional (uses current mission), so this dispatches
        assert "mission" in result.output.lower() or result.exit_code == 0


class TestAdminGroup:
    def test_admin_help(self, runner):
        from admin import admin_cli as cli

        result = runner.invoke(cli, ["admin", "--help"])
        assert result.exit_code == 0
        assert "metrics" in result.output
        assert "bootstrap-user" in result.output
        assert "roles" in result.output

    def test_admin_metrics_dispatches(self, runner):
        from admin import admin_cli as cli

        with patch("modules.clients.cli.admin_cmds.run_admin_cmd") as mock_fn:
            result = runner.invoke(cli, ["admin", "metrics"])
        mock_fn.assert_called_once()
        assert mock_fn.call_args[0][1] == "metrics"
        assert result.exit_code == 0

    def test_admin_roles_dispatches(self, runner):
        from admin import admin_cli as cli

        with patch("modules.clients.cli.admin_cmds.run_admin_cmd") as mock_fn:
            result = runner.invoke(cli, ["admin", "roles"])
        mock_fn.assert_called_once()
        assert mock_fn.call_args[0][1] == "roles"

    def test_admin_bootstrap_user_dispatches(self, runner):
        from admin import admin_cli as cli

        with patch("modules.clients.cli.admin_cmds.run_admin_cmd") as mock_fn:
            result = runner.invoke(
                cli,
                [
                    "admin",
                    "bootstrap-user",
                    "--email",
                    "admin@test.com",
                    "--password",
                    "supersecretpw123",
                ],
            )
        mock_fn.assert_called_once()
        assert mock_fn.call_args[0][1] == "bootstrap-user"
        assert mock_fn.call_args[1]["email"] == "admin@test.com"
        assert result.exit_code == 0

    def test_admin_bootstrap_requires_email(self, runner):
        from admin import admin_cli as cli

        result = runner.invoke(cli, ["admin", "bootstrap-user"])
        assert result.exit_code != 0
        assert "email" in result.output.lower() or "required" in result.output.lower()

    def test_admin_reset_password_dispatches(self, runner):
        from admin import admin_cli as cli

        with patch("modules.clients.cli.admin_cmds.run_admin_cmd") as mock_fn:
            result = runner.invoke(
                cli,
                [
                    "admin",
                    "reset-password",
                    "--email",
                    "user@test.com",
                    "--password",
                    "newpassword123",
                ],
            )
        mock_fn.assert_called_once()
        assert mock_fn.call_args[0][1] == "reset-password"
        assert mock_fn.call_args[1]["email"] == "user@test.com"

    def test_admin_update_prompt_requires_agent(self, runner):
        from admin import admin_cli as cli

        result = runner.invoke(cli, ["admin", "update-prompt", "--content", "hello"])
        assert result.exit_code != 0

    def test_admin_toggle_agent_dispatches(self, runner):
        from admin import admin_cli as cli

        with patch("modules.clients.cli.admin_cmds.run_admin_cmd") as mock_fn:
            result = runner.invoke(
                cli,
                [
                    "admin",
                    "toggle-agent",
                    "--agent",
                    "test.agent",
                ],
            )
        mock_fn.assert_called_once()
        assert mock_fn.call_args[0][1] == "toggle-agent"
        assert mock_fn.call_args[1]["agent_name"] == "test.agent"


class TestExecutionGroup:
    def test_execution_help(self, runner):
        from admin import admin_cli as cli

        result = runner.invoke(cli, ["execution", "--help"])
        assert result.exit_code == 0
        assert "run" in result.output
        assert "list" in result.output

    def test_execution_list_dispatches(self, runner):
        from admin import admin_cli as cli

        with patch("modules.clients.cli.execution_cmds.run_execution") as mock_fn:
            result = runner.invoke(cli, ["execution", "list"])
        mock_fn.assert_called_once()
        assert result.exit_code == 0


class TestWorkflowGroup:
    def test_workflow_help(self, runner):
        from admin import admin_cli as cli

        result = runner.invoke(cli, ["workflow", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "run" in result.output


class TestDbGroup:
    def test_db_help(self, runner):
        from admin import admin_cli as cli

        result = runner.invoke(cli, ["db", "--help"])
        assert result.exit_code == 0
        assert "stats" in result.output
        assert "clear" in result.output


class TestMigrateGroup:
    def test_migrate_help(self, runner):
        from admin import admin_cli as cli

        result = runner.invoke(cli, ["migrate", "--help"])
        assert result.exit_code == 0
