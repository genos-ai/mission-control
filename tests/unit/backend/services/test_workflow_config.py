"""
Tests for WorkflowsSchema configuration.

Pure Pydantic schema tests — no mocks, no infrastructure.
"""

import pytest

from modules.backend.core.config_schema import WorkflowsSchema


class TestWorkflowsSchema:
    def test_defaults(self):
        config = WorkflowsSchema()
        assert config.workflows_dir == "config/workflow_templates"
        assert config.max_steps_per_workflow == 20
        assert config.max_context_size_bytes == 1_048_576
        assert config.default_step_timeout_seconds == 600
        assert config.default_budget_usd == 10.00
        assert config.max_budget_usd == 100.00
        assert config.max_concurrent_missions == 10
        assert config.enable_workflow_matching is True

    def test_strict_rejects_unknown_fields(self):
        with pytest.raises(Exception):
            WorkflowsSchema(unknown_field="oops")

    def test_custom_values(self):
        config = WorkflowsSchema(
            workflows_dir="custom/workflows",
            max_steps_per_workflow=50,
            max_budget_usd=500.0,
            enable_workflow_matching=False,
        )
        assert config.workflows_dir == "custom/workflows"
        assert config.max_steps_per_workflow == 50
        assert config.max_budget_usd == 500.0
        assert config.enable_workflow_matching is False
