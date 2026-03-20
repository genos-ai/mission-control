"""Tests for ExecutionsSchema config loading."""

import pytest

from modules.backend.core.config_schema import ExecutionsSchema


class TestExecutionsConfig:
    def test_defaults(self):
        config = ExecutionsSchema()
        assert config.retention_days == 0
        assert config.default_page_size == 20
        assert config.max_page_size == 100
        assert config.persist_thinking_trace is True
        assert config.persist_verification_details is True
        assert config.max_thinking_trace_length == 50000
        assert config.max_task_output_size_bytes == 1_048_576

    def test_strict_rejects_unknown(self):
        with pytest.raises(Exception):
            ExecutionsSchema(unknown_field="oops")

    def test_custom_values(self):
        config = ExecutionsSchema(
            retention_days=90,
            default_page_size=50,
            persist_thinking_trace=False,
        )
        assert config.retention_days == 90
        assert config.default_page_size == 50
        assert config.persist_thinking_trace is False
