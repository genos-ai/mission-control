"""Tests for the RunNotifierService."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.backend.services.run_notifier import RunNotifierService


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.enabled = True
    config.notify_on_completion = True
    config.notify_on_failure = True
    config.budget_warning_threshold_pct = 80.0
    config.notify_channels = ["telegram"]
    return config


class TestNotifyRunCompleted:
    """Tests for notify_run_completed."""

    @pytest.mark.asyncio
    @patch("modules.backend.services.run_notifier.get_app_config")
    @patch("modules.backend.services.run_notifier._dispatch_to_channels", new_callable=AsyncMock)
    async def test_sends_completion(self, mock_dispatch, mock_config_fn, mock_config):
        mock_config_fn.return_value.notifications = mock_config

        await RunNotifierService.notify_run_completed(
            run_id="r-1",
            workflow_name="test.workflow",
            total_cost_usd=0.5,
            step_count=3,
        )

        mock_dispatch.assert_called_once()
        call_args = mock_dispatch.call_args[0]
        assert call_args[0] == ["telegram"]
        assert call_args[1] == "Workflow Completed"
        assert "test.workflow" in call_args[2]
        assert call_args[3] == "success"

    @pytest.mark.asyncio
    @patch("modules.backend.services.run_notifier.get_app_config")
    @patch("modules.backend.services.run_notifier._dispatch_to_channels", new_callable=AsyncMock)
    async def test_skips_when_disabled(self, mock_dispatch, mock_config_fn, mock_config):
        mock_config.enabled = False
        mock_config_fn.return_value.notifications = mock_config

        await RunNotifierService.notify_run_completed(
            run_id="r-1", workflow_name="w", total_cost_usd=0, step_count=1,
        )

        mock_dispatch.assert_not_called()

    @pytest.mark.asyncio
    @patch("modules.backend.services.run_notifier.get_app_config")
    @patch("modules.backend.services.run_notifier._dispatch_to_channels", new_callable=AsyncMock)
    async def test_skips_when_completion_notify_off(self, mock_dispatch, mock_config_fn, mock_config):
        mock_config.notify_on_completion = False
        mock_config_fn.return_value.notifications = mock_config

        await RunNotifierService.notify_run_completed(
            run_id="r-1", workflow_name="w", total_cost_usd=0, step_count=1,
        )

        mock_dispatch.assert_not_called()


class TestNotifyRunFailed:
    """Tests for notify_run_failed."""

    @pytest.mark.asyncio
    @patch("modules.backend.services.run_notifier.get_app_config")
    @patch("modules.backend.services.run_notifier._dispatch_to_channels", new_callable=AsyncMock)
    async def test_sends_failure(self, mock_dispatch, mock_config_fn, mock_config):
        mock_config_fn.return_value.notifications = mock_config

        await RunNotifierService.notify_run_failed(
            run_id="r-2",
            workflow_name="test.workflow",
            error="Step 'plan' failed",
        )

        mock_dispatch.assert_called_once()
        call_args = mock_dispatch.call_args[0]
        assert call_args[1] == "Workflow Failed"
        assert "Step 'plan' failed" in call_args[2]
        assert call_args[3] == "error"

    @pytest.mark.asyncio
    @patch("modules.backend.services.run_notifier.get_app_config")
    @patch("modules.backend.services.run_notifier._dispatch_to_channels", new_callable=AsyncMock)
    async def test_skips_when_failure_notify_off(self, mock_dispatch, mock_config_fn, mock_config):
        mock_config.notify_on_failure = False
        mock_config_fn.return_value.notifications = mock_config

        await RunNotifierService.notify_run_failed(
            run_id="r-2", workflow_name="w", error="boom",
        )

        mock_dispatch.assert_not_called()


class TestNotifyBudgetWarning:
    """Tests for notify_budget_warning."""

    @pytest.mark.asyncio
    @patch("modules.backend.services.run_notifier.get_app_config")
    @patch("modules.backend.services.run_notifier._dispatch_to_channels", new_callable=AsyncMock)
    async def test_sends_warning_above_threshold(self, mock_dispatch, mock_config_fn, mock_config):
        mock_config_fn.return_value.notifications = mock_config

        await RunNotifierService.notify_budget_warning(
            run_id="r-3",
            workflow_name="expensive.workflow",
            cost_usd=9.0,
            budget_usd=10.0,
            pct_used=90.0,
        )

        mock_dispatch.assert_called_once()
        call_args = mock_dispatch.call_args[0]
        assert call_args[1] == "Budget Warning"
        assert call_args[3] == "warning"

    @pytest.mark.asyncio
    @patch("modules.backend.services.run_notifier.get_app_config")
    @patch("modules.backend.services.run_notifier._dispatch_to_channels", new_callable=AsyncMock)
    async def test_skips_below_threshold(self, mock_dispatch, mock_config_fn, mock_config):
        mock_config_fn.return_value.notifications = mock_config

        await RunNotifierService.notify_budget_warning(
            run_id="r-3",
            workflow_name="cheap.workflow",
            cost_usd=1.0,
            budget_usd=10.0,
            pct_used=10.0,
        )

        mock_dispatch.assert_not_called()


class TestNotifyScheduleError:
    """Tests for notify_schedule_error."""

    @pytest.mark.asyncio
    @patch("modules.backend.services.run_notifier.get_app_config")
    @patch("modules.backend.services.run_notifier._dispatch_to_channels", new_callable=AsyncMock)
    async def test_sends_schedule_error(self, mock_dispatch, mock_config_fn, mock_config):
        mock_config_fn.return_value.notifications = mock_config

        await RunNotifierService.notify_schedule_error(
            schedule_id="s-1",
            error="Workflow definition not found",
        )

        mock_dispatch.assert_called_once()
        call_args = mock_dispatch.call_args[0]
        assert call_args[1] == "Schedule Error"
        assert call_args[3] == "error"
