"""Tests for CLI admin command action handlers.

Tests the async _action_* functions in admin_cmds.py with mocked services.
These validate the business logic dispatching, not Click wiring.

Note: action handlers use local imports inside function bodies, so we
patch at the source module (e.g., modules.backend.core.config) rather
than at the consumer module.
"""

import json
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.backend.core.config_schema import RoleSchema


@pytest.fixture
def cli_logger():
    return MagicMock()


@pytest.fixture
def mock_console():
    """Capture console output via a patched get_console."""
    console = MagicMock()
    console.file = StringIO()
    with patch("modules.clients.cli.admin_cmds.get_console", return_value=console):
        yield console


class TestActionMetrics:
    @pytest.mark.asyncio
    async def test_metrics_human_format(self, cli_logger, mock_console):
        from modules.clients.cli.admin_cmds import _action_metrics

        overview = {
            "counts": {"missions": 3, "sessions": 10, "executions": 5},
            "total_cost_usd": 1.2345,
        }
        mock_svc = MagicMock()
        mock_svc.get_overview = AsyncMock(return_value=overview)

        with patch("modules.backend.services.platform_metrics.PlatformMetricsService") as MockCls:
            MockCls.factory.return_value.__aenter__ = AsyncMock(return_value=mock_svc)
            MockCls.factory.return_value.__aexit__ = AsyncMock()
            await _action_metrics(cli_logger, output_format="human")

        mock_console.print.assert_called()

    @pytest.mark.asyncio
    async def test_metrics_json_format(self, cli_logger, mock_console):
        from modules.clients.cli.admin_cmds import _action_metrics

        overview = {
            "counts": {"missions": 3},
            "total_cost_usd": 0.5,
        }
        mock_svc = MagicMock()
        mock_svc.get_overview = AsyncMock(return_value=overview)

        with patch("modules.backend.services.platform_metrics.PlatformMetricsService") as MockCls:
            MockCls.factory.return_value.__aenter__ = AsyncMock(return_value=mock_svc)
            MockCls.factory.return_value.__aexit__ = AsyncMock()
            await _action_metrics(cli_logger, output_format="json")

        mock_console.print_json.assert_called_once()


class TestActionRoles:
    @pytest.mark.asyncio
    async def test_roles_human_format(self, cli_logger, mock_console):
        from modules.clients.cli.admin_cmds import _action_roles

        mock_config = MagicMock()
        mock_config.security.roles = {
            "viewer": RoleSchema(level=1, description="Read-only"),
            "admin": RoleSchema(level=3, description="Full access"),
        }

        with patch("modules.backend.core.config.get_app_config", return_value=mock_config):
            await _action_roles(cli_logger, output_format="human")

        mock_console.print.assert_called()

    @pytest.mark.asyncio
    async def test_roles_json_format(self, cli_logger, mock_console):
        from modules.clients.cli.admin_cmds import _action_roles

        mock_config = MagicMock()
        mock_config.security.roles = {
            "viewer": RoleSchema(level=1, description="Read-only"),
            "admin": RoleSchema(level=3, description="Full access"),
        }

        with patch("modules.backend.core.config.get_app_config", return_value=mock_config):
            await _action_roles(cli_logger, output_format="json")

        mock_console.print_json.assert_called_once()
        call_arg = mock_console.print_json.call_args[0][0]
        data = json.loads(call_arg)
        assert data["viewer"]["level"] == 1
        assert data["admin"]["level"] == 3


class TestActionUserRoles:
    @pytest.mark.asyncio
    async def test_user_roles_empty(self, cli_logger, mock_console):
        from modules.clients.cli.admin_cmds import _action_user_roles

        mock_config = MagicMock()
        mock_config.security.user_roles = {}

        with patch("modules.backend.core.config.get_app_config", return_value=mock_config):
            await _action_user_roles(cli_logger, output_format="human")

        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("No user role" in s for s in printed)

    @pytest.mark.asyncio
    async def test_user_roles_with_entries(self, cli_logger, mock_console):
        from modules.clients.cli.admin_cmds import _action_user_roles

        mock_config = MagicMock()
        mock_config.security.user_roles = {"123456": "admin", "789": "user"}

        with patch("modules.backend.core.config.get_app_config", return_value=mock_config):
            await _action_user_roles(cli_logger, output_format="json")

        mock_console.print_json.assert_called_once()


class TestActionConfig:
    @pytest.mark.asyncio
    async def test_config_renders(self, cli_logger, mock_console):
        from modules.clients.cli.admin_cmds import _action_config

        mock_config = MagicMock()
        mock_config.application.name = "mission-control"
        mock_config.application.version = "1.0.0"
        mock_config.application.environment = "test"
        mock_config.application.debug = False
        mock_config.workflows.max_steps_per_workflow = 10
        mock_config.workflows.default_budget_usd = 5.0
        mock_config.workflows.max_budget_usd = 50.0
        mock_config.workflows.max_concurrent_missions = 3
        mock_config.workflows.max_scheduled_runs_per_day = 50

        with patch("modules.backend.core.config.get_app_config", return_value=mock_config):
            await _action_config(cli_logger, output_format="json")

        mock_console.print_json.assert_called_once()
        data = json.loads(mock_console.print_json.call_args[0][0])
        assert data["application"]["name"] == "mission-control"


class TestActionHealth:
    @staticmethod
    def _mock_report(components):
        """Build a mock HealthReport from (name, status, latency_ms) tuples."""
        from modules.backend.services.health import ComponentStatus, HealthReport

        comp_objs = [
            ComponentStatus(name=n, status=s, latency_ms=lat, error=err)
            for n, s, lat, err in components
        ]
        degraded = any(c.status not in ("healthy", "not_configured") for c in comp_objs)
        return HealthReport(
            overall_status="degraded" if degraded else "healthy",
            components=comp_objs,
        )

    @pytest.mark.asyncio
    async def test_health_all_healthy(self, cli_logger, mock_console):
        from modules.clients.cli.admin_cmds import _action_health

        report = self._mock_report([
            ("database", "healthy", 5, None),
            ("redis", "healthy", 2, None),
        ])

        with patch("modules.backend.services.health.HealthCheckService") as MockCls:
            MockCls.return_value.check_readiness = AsyncMock(return_value=report)
            await _action_health(cli_logger, output_format="human")

        printed = " ".join(str(call) for call in mock_console.print.call_args_list)
        assert "healthy" in printed

    @pytest.mark.asyncio
    async def test_health_json_format(self, cli_logger, mock_console):
        from modules.clients.cli.admin_cmds import _action_health

        report = self._mock_report([
            ("database", "healthy", None, None),
            ("redis", "error", None, "timeout"),
        ])

        with patch("modules.backend.services.health.HealthCheckService") as MockCls:
            MockCls.return_value.check_readiness = AsyncMock(return_value=report)
            await _action_health(cli_logger, output_format="json")

        mock_console.print_json.assert_called_once()
        data = json.loads(mock_console.print_json.call_args[0][0])
        assert data["database"]["status"] == "healthy"
        assert data["redis"]["status"] == "error"

    @pytest.mark.asyncio
    async def test_health_degraded(self, cli_logger, mock_console):
        from modules.clients.cli.admin_cmds import _action_health

        report = self._mock_report([
            ("database", "unhealthy", None, "connection refused"),
            ("redis", "healthy", 2, None),
        ])

        with patch("modules.backend.services.health.HealthCheckService") as MockCls:
            MockCls.return_value.check_readiness = AsyncMock(return_value=report)
            await _action_health(cli_logger, output_format="human")

        printed = " ".join(str(call) for call in mock_console.print.call_args_list)
        assert "unhealthy" in printed


class TestDispatchRouter:
    def test_unknown_action_exits(self, cli_logger, mock_console):
        from modules.clients.cli.admin_cmds import run_admin_cmd

        with pytest.raises(SystemExit):
            run_admin_cmd(cli_logger, "nonexistent-action")

        printed = " ".join(str(call) for call in mock_console.print.call_args_list)
        assert "Unknown" in printed

    def test_known_action_dispatches(self, cli_logger):
        from modules.clients.cli.admin_cmds import run_admin_cmd

        with patch("modules.clients.cli.admin_cmds._action_roles", new_callable=AsyncMock) as mock_fn:
            run_admin_cmd(cli_logger, "roles", output_format="human")

        mock_fn.assert_called_once()
