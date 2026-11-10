"""output_mode on an agent's model block: optional, and only where the provider can honour it."""

import pytest
from pydantic import ValidationError

from modules.backend.schemas.agent_config import AgentConfigSchema, AgentModelSchema

MINIMAL_AGENT = {
    "agent_name": "test.output_mode.agent",
    "agent_type": "vertical",
    "description": "A test agent",
    "enabled": True,
    "max_input_length": 1000,
    "max_budget_usd": 0.1,
    "execution": {"mode": "local"},
}


def _agent(model: str, output_mode: str | None = None) -> AgentConfigSchema:
    block = {"name": model} if output_mode is None else {"name": model, "output_mode": output_mode}
    return AgentConfigSchema(**MINIMAL_AGENT, model=block)


class TestAgentOutputMode:
    def test_unset_means_the_registry_decides(self):
        assert AgentModelSchema(name="foundry:x").output_mode is None

    @pytest.mark.parametrize(
        ("model", "mode"),
        [
            ("foundry:claude-x", "prompted"),
            ("anthropic:claude-x", "prompted"),
            ("openai:gpt-x", "prompted"),
            ("foundry:gpt-x", "native"),
            ("copilot:claude-x", "tool"),
        ],
    )
    def test_a_mode_the_provider_can_honour_is_accepted(self, model, mode):
        assert _agent(model, mode).model.output_mode == mode

    @pytest.mark.parametrize(
        ("model", "mode"),
        [
            ("anthropic:claude-x", "native"),
            ("copilot:claude-x", "native"),
            ("copilot:claude-x", "prompted"),
        ],
    )
    def test_a_mode_the_provider_cannot_honour_is_rejected(self, model, mode):
        with pytest.raises(ValidationError, match=f"output_mode='{mode}'"):
            _agent(model, mode)

    def test_an_unknown_mode_is_rejected(self):
        with pytest.raises(ValidationError):
            AgentModelSchema(name="foundry:x", output_mode="json")
