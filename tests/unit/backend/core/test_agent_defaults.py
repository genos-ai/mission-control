"""Agent defaults come from config and schemas, and a missing config key fails at load."""

import pytest
from pydantic import ValidationError

from modules.backend.agents.mission_control.roster import (
    RosterConstraintsSchema,
    RosterModelSchema,
)
from modules.backend.core import agent_defaults
from modules.backend.core.config import get_app_config, get_mission_control_config
from modules.backend.schemas.agent_config import (
    AgentConfigSchema,
    AgentModelSchema,
    DispatchSchema,
    InvocationSchema,
)

DISPATCH = get_mission_control_config().dispatch


class TestFromConfig:
    def test_task_timeout(self):
        assert (
            agent_defaults.task_timeout_seconds()
            == get_app_config().application.timeouts.agent_task
        )

    def test_retry_budget(self):
        assert agent_defaults.retry_budget() == DISPATCH.default_retry_budget

    def test_max_budget(self):
        assert agent_defaults.max_budget_usd() == DISPATCH.default_max_budget_usd

    def test_max_input_length(self):
        assert agent_defaults.max_input_length() == DISPATCH.default_max_input_length

    def test_execution_mode(self):
        assert agent_defaults.execution_mode() == DISPATCH.default_execution_mode


class TestFromSchemas:
    def test_each_value_is_the_schema_default(self):
        assert agent_defaults.version() == AgentConfigSchema.model_fields["version"].default
        assert agent_defaults.engine() == AgentConfigSchema.model_fields["engine"].default
        assert agent_defaults.visibility() == AgentConfigSchema.model_fields["visibility"].default
        assert agent_defaults.invocation_tier() == InvocationSchema.model_fields["tier"].default
        assert agent_defaults.temperature() == AgentModelSchema.model_fields["temperature"].default
        assert agent_defaults.max_tokens() == AgentModelSchema.model_fields["max_tokens"].default


class TestDispatchRequiresEveryDefault:
    @pytest.mark.parametrize(
        "key",
        [
            "default_retry_budget",
            "default_max_budget_usd",
            "default_max_input_length",
            "default_execution_mode",
        ],
    )
    def test_a_missing_key_is_refused_by_name(self, key):
        fields = {k: v for k, v in DISPATCH.model_dump().items() if k != key}

        with pytest.raises(ValidationError, match=key):
            DispatchSchema(**fields)

    @pytest.mark.parametrize(
        ("key", "bad"),
        [
            ("default_max_budget_usd", 0),
            ("default_max_input_length", 0),
            ("default_execution_mode", ""),
        ],
    )
    def test_a_nonsense_value_is_refused(self, key, bad):
        with pytest.raises(ValidationError, match=key):
            DispatchSchema(**{**DISPATCH.model_dump(), key: bad})


class TestRoster:
    def test_constraints_default_to_the_configured_values(self):
        constraints = RosterConstraintsSchema()

        assert constraints.timeout_seconds == agent_defaults.task_timeout_seconds()
        assert constraints.cost_ceiling_usd == agent_defaults.max_budget_usd()
        assert constraints.retry_budget == agent_defaults.retry_budget()

    def test_a_model_defaults_to_the_schema_values(self):
        model = RosterModelSchema(name="p:m")

        assert model.temperature == agent_defaults.temperature()
        assert model.max_tokens == agent_defaults.max_tokens()
