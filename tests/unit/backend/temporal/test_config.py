"""Tests for TemporalSchema configuration.

Pure Pydantic schema tests — no mocks, no infrastructure.
"""

import pytest

from modules.backend.core.config import get_app_config
from modules.backend.core.config_schema import TemporalSchema


def _plan88_blocks() -> dict:
    """Plan 88 required TemporalSchema blocks, taken from the repo temporal.yaml."""
    return get_app_config().temporal.model_dump(
        include={"mission_run", "reconciler", "system_schedules"}
    )


class TestTemporalSchema:
    def test_defaults(self):
        config = TemporalSchema(**_plan88_blocks())
        assert config.enabled is False
        assert config.server_url is None
        assert config.namespace == "default"
        assert config.task_queue == "agent-missions"
        assert config.approval_timeout_seconds == 14400
        assert config.escalation_timeout_seconds == 86400
        assert config.notification_timeout_seconds == 30

    def test_strict_rejects_unknown_fields(self):
        with pytest.raises(Exception):
            TemporalSchema(unknown_field="oops")

    def test_enabled_requires_explicit_server_url(self):
        with pytest.raises(ValueError, match="server_url must be explicitly configured"):
            TemporalSchema(enabled=True, **_plan88_blocks())

    def test_disabled_allows_none_server_url(self):
        config = TemporalSchema(enabled=False, **_plan88_blocks())
        assert config.server_url is None

    def test_custom_values(self):
        config = TemporalSchema(
            **_plan88_blocks(),
            enabled=True,
            server_url="temporal.prod:7233",
            task_queue="production-missions",
        )
        assert config.enabled is True
        assert config.server_url == "temporal.prod:7233"
        assert config.task_queue == "production-missions"
