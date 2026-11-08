"""The retry budget has one default, in config, and agents may override it.

No test here repeats the configured number; each reads it from the same config the
code does.
"""

import pytest
from pydantic import ValidationError

from modules.backend.agents.mission_control.roster import RosterConstraintsSchema
from modules.backend.core.config import get_mission_control_config
from modules.backend.schemas.agent_config import AgentConfigSchema, DispatchSchema

DEFAULT = get_mission_control_config().dispatch.default_retry_budget

MINIMAL_AGENT = {
    "agent_name": "test.retry.agent",
    "agent_type": "vertical",
    "description": "A test agent",
    "enabled": True,
    "model": "foundry:gpt-fixture",
    "max_input_length": 1000,
    "max_budget_usd": 0.1,
    "execution": {"mode": "local"},
}


DISPATCH = get_mission_control_config().dispatch.model_dump()


def _dispatch(**overrides) -> DispatchSchema:
    """A DispatchSchema built from the shipped values, with ``overrides`` applied."""
    return DispatchSchema(**{**DISPATCH, **overrides})


class TestDispatchConfig:
    def test_the_shipped_config_sets_a_default(self):
        assert isinstance(DEFAULT, int)
        assert DEFAULT >= 0

    def test_the_default_is_required_not_assumed(self):
        fields = {k: v for k, v in DISPATCH.items() if k != "default_retry_budget"}

        with pytest.raises(ValidationError, match="default_retry_budget"):
            DispatchSchema(**fields)

    def test_a_negative_default_is_rejected(self):
        with pytest.raises(ValidationError, match="default_retry_budget"):
            _dispatch(default_retry_budget=-1)


class TestAgentRetryBudget:
    def test_an_agent_that_sets_none_leaves_it_unset(self):
        assert AgentConfigSchema(**MINIMAL_AGENT).retry_budget is None

    def test_an_agent_can_set_its_own(self):
        assert AgentConfigSchema(**MINIMAL_AGENT, retry_budget=DEFAULT + 4).retry_budget == (
            DEFAULT + 4
        )

    def test_zero_retries_is_allowed(self):
        assert AgentConfigSchema(**MINIMAL_AGENT, retry_budget=0).retry_budget == 0

    def test_a_negative_budget_is_rejected(self):
        with pytest.raises(ValidationError):
            AgentConfigSchema(**MINIMAL_AGENT, retry_budget=-1)


class TestRosterConstraints:
    def test_the_roster_default_is_the_configured_one(self):
        assert RosterConstraintsSchema().retry_budget == DEFAULT

    def test_an_explicit_value_wins(self):
        assert RosterConstraintsSchema(retry_budget=DEFAULT + 1).retry_budget == DEFAULT + 1
