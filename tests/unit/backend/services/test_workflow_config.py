"""
Tests for WorkflowsSchema configuration.

Pure Pydantic schema tests — no mocks, no infrastructure.
"""

import pytest

from modules.backend.core.config_schema import WorkflowsSchema


class TestWorkflowsSchema:
    def test_defaults(self):
        config = WorkflowsSchema(default_step_model="quick")
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
            WorkflowsSchema(default_step_model="quick", unknown_field="oops")

    def test_custom_values(self):
        config = WorkflowsSchema(
            default_step_model="quick",
            workflows_dir="custom/workflows",
            max_steps_per_workflow=50,
            max_budget_usd=500.0,
            enable_workflow_matching=False,
        )
        assert config.workflows_dir == "custom/workflows"
        assert config.max_steps_per_workflow == 50
        assert config.max_budget_usd == 500.0
        assert config.enable_workflow_matching is False

    def test_default_step_model_has_no_code_default(self):
        # The model new steps start with is a deployment choice made in workflows.yaml.
        with pytest.raises(Exception, match="default_step_model"):
            WorkflowsSchema()

    def test_default_step_model_cannot_be_empty(self):
        with pytest.raises(Exception, match="default_step_model"):
            WorkflowsSchema(default_step_model="")


class TestDefaultStepModelIsAnAlias:
    """The shipped config names an alias that models.yaml defines."""

    def test_shipped_config_loads_and_names_a_known_alias(self):
        from modules.backend.core.config import AppConfig

        config = AppConfig()
        assert config.workflows.default_step_model in config.models.aliases

    def test_an_unknown_alias_fails_the_load(self, monkeypatch):
        from modules.backend.core import config as config_module

        real = config_module.load_yaml_config

        def patched(filename):
            raw = real(filename)
            if filename == "workflows.yaml":
                raw = {**raw, "default_step_model": "no-such-alias"}
            return raw

        monkeypatch.setattr(config_module, "load_yaml_config", patched)
        with pytest.raises(ValueError, match="no-such-alias"):
            config_module.AppConfig()
