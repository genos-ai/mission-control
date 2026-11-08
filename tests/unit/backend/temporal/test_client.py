"""Tests for Temporal client factory — feature flag gating.

Mocks only get_app_config (config loading, not infra we operate).
Uses real TemporalSchema instances.
"""

from unittest.mock import MagicMock, patch

import pytest

from modules.backend.core.config import get_app_config
from modules.backend.core.config_schema import TemporalSchema
from modules.backend.temporal.client import get_temporal_config


def _plan88_blocks() -> dict:
    """Plan 88 required TemporalSchema blocks, taken from the repo temporal.yaml."""
    return get_app_config().temporal.model_dump(
        include={"mission_run", "reconciler", "system_schedules"}
    )


def _mock_app_config(enabled: bool = False, **overrides) -> MagicMock:
    config = MagicMock()
    if enabled and "server_url" not in overrides:
        overrides["server_url"] = "temporal.test:7233"
    config.temporal = TemporalSchema(enabled=enabled, **_plan88_blocks(), **overrides)
    return config


class TestGetTemporalConfig:
    def test_raises_when_not_enabled(self):
        with patch(
            "modules.backend.temporal.client.get_app_config",
            return_value=_mock_app_config(enabled=False),
        ):
            with pytest.raises(RuntimeError, match="not enabled"):
                get_temporal_config()

    def test_returns_config_when_enabled(self):
        with patch(
            "modules.backend.temporal.client.get_app_config",
            return_value=_mock_app_config(enabled=True),
        ):
            config = get_temporal_config()
            assert config.enabled is True
            assert config.server_url == "temporal.test:7233"
            assert config.task_queue == "agent-missions"

    def test_custom_config_values(self):
        with patch(
            "modules.backend.temporal.client.get_app_config",
            return_value=_mock_app_config(
                enabled=True,
                task_queue="custom-queue",
                namespace="production",
            ),
        ):
            config = get_temporal_config()
            assert config.task_queue == "custom-queue"
            assert config.namespace == "production"
