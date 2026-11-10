"""Unit tests for model resolution: registry lookup, builder dispatch and settings.

Runs against a fixture registry with made-up model names, so nothing here depends
on which models config/settings/models.yaml currently lists. Builders are replaced
with recorders so no SDK client or credential is created.
"""

from types import SimpleNamespace

import pytest

from modules.backend.core.config import get_app_config
from modules.backend.core.config_schema import ModelsSchema
from modules.backend.core.exceptions import ValidationError
from modules.backend.core.model_backends import (
    ANTHROPIC_MESSAGES,
    BACKENDS,
    COPILOT_SDK,
    OPENAI_CHAT,
)
from modules.backend.core.model_builder import _build_model, build_model_settings, resolve_model
from modules.backend.schemas.agent_config import AgentModelSchema

GPT = "foundry:gpt-fixture"
CLAUDE_ADAPTIVE = "foundry:claude-adaptive-fixture"
CLAUDE_BUDGET = "anthropic:claude-budget-fixture"
CLAUDE_PROMPTED = "foundry:claude-prompted-fixture"
COPILOT = "copilot:copilot-fixture"


@pytest.fixture(autouse=True)
def fixture_registry(monkeypatch):
    """Replace the registry and aliases with fixtures for the duration of a test."""
    models = ModelsSchema(
        aliases={"fast": CLAUDE_ADAPTIVE},
        registry={
            "foundry": {
                "gpt-fixture": {"protocol": OPENAI_CHAT},
                "claude-adaptive-fixture": {"protocol": ANTHROPIC_MESSAGES, "thinking": "adaptive"},
                "claude-prompted-fixture": {
                    "protocol": ANTHROPIC_MESSAGES,
                    "output_mode": "prompted",
                },
            },
            "anthropic": {"claude-budget-fixture": {"protocol": ANTHROPIC_MESSAGES}},
            "copilot": {"copilot-fixture": {"protocol": COPILOT_SDK}},
        },
    )
    monkeypatch.setattr(get_app_config(), "_models", models)


@pytest.fixture
def recorded(monkeypatch):
    """Replace every builder with one that records (provider, protocol, bare name, mode)."""
    calls: list[tuple[str, str, str, str]] = []

    def make(provider: str, protocol: str):
        def build(bare_name, output_mode):
            calls.append((provider, protocol, bare_name, output_mode))
            return f"{provider}/{protocol}/{bare_name}"

        return build

    for provider, protocols in BACKENDS.items():
        for protocol in protocols:
            monkeypatch.setitem(BACKENDS[provider], protocol, make(provider, protocol))
    return calls


class TestResolveModel:
    def test_registered_model_resolves_with_its_protocol_and_thinking_style(self):
        resolved = resolve_model(CLAUDE_ADAPTIVE)

        assert (resolved.provider, resolved.name, resolved.protocol, resolved.thinking) == (
            "foundry",
            "claude-adaptive-fixture",
            ANTHROPIC_MESSAGES,
            "adaptive",
        )

    def test_thinking_defaults_to_a_token_budget(self):
        assert resolve_model(CLAUDE_BUDGET).thinking == "budget"

    def test_one_provider_resolves_different_protocols_per_model(self):
        assert resolve_model(GPT).protocol == OPENAI_CHAT
        assert resolve_model(CLAUDE_ADAPTIVE).protocol == ANTHROPIC_MESSAGES

    def test_unregistered_model_is_refused_with_the_registered_list(self):
        with pytest.raises(ValidationError, match="not in the model registry") as raised:
            resolve_model("foundry:not-deployed")

        assert "gpt-fixture" in str(raised.value)

    def test_unknown_provider_is_refused_with_the_known_list(self):
        with pytest.raises(ValidationError, match="Unsupported model provider"):
            resolve_model("bedrock:anything")

    @pytest.mark.parametrize("bad", ["no-prefix", ":model", "provider:"])
    def test_malformed_name_is_refused(self, bad):
        with pytest.raises(ValidationError, match="not a 'provider:model'"):
            resolve_model(bad)


class TestBuildModelDispatch:
    def test_claude_on_foundry_is_built_over_the_messages_api(self, recorded):
        _build_model(CLAUDE_ADAPTIVE)

        assert recorded == [("foundry", ANTHROPIC_MESSAGES, "claude-adaptive-fixture", "tool")]

    def test_gpt_on_foundry_is_built_over_chat_completions(self, recorded):
        _build_model(GPT)

        assert recorded == [("foundry", OPENAI_CHAT, "gpt-fixture", "tool")]

    def test_alias_resolves_before_dispatch(self, recorded):
        _build_model("fast")

        assert recorded == [("foundry", ANTHROPIC_MESSAGES, "claude-adaptive-fixture", "tool")]

    def test_unregistered_model_never_reaches_a_builder(self, recorded):
        with pytest.raises(ValidationError, match="not in the model registry"):
            _build_model("foundry:not-deployed")

        assert recorded == []

    def test_native_output_is_refused_on_the_messages_api(self, recorded):
        model = AgentModelSchema(name=CLAUDE_ADAPTIVE, output_mode="native")

        with pytest.raises(ValidationError, match="output_mode='native'"):
            _build_model(model)

        assert recorded == []

    def test_native_output_is_accepted_over_chat_completions(self, recorded):
        _build_model(AgentModelSchema(name=GPT, output_mode="native"))

        assert recorded == [("foundry", OPENAI_CHAT, "gpt-fixture", "native")]


class TestOutputModeResolution:
    """Agent output_mode wins, else the registry's, whose schema default is 'tool'."""

    def test_registry_default_is_tool(self, recorded):
        _build_model(AgentModelSchema(name=CLAUDE_ADAPTIVE))

        assert recorded[0][3] == "tool"

    def test_registry_mode_applies_when_the_agent_sets_none(self, recorded):
        _build_model(AgentModelSchema(name=CLAUDE_PROMPTED))

        assert recorded[0][3] == "prompted"

    def test_registry_mode_applies_to_a_bare_string_model(self, recorded):
        _build_model(CLAUDE_PROMPTED)

        assert recorded[0][3] == "prompted"

    def test_agent_mode_overrides_the_registry(self, recorded):
        _build_model(AgentModelSchema(name=CLAUDE_PROMPTED, output_mode="tool"))

        assert recorded[0][3] == "tool"

    def test_agent_prompted_overrides_a_tool_registry_entry(self, recorded):
        _build_model(AgentModelSchema(name=CLAUDE_ADAPTIVE, output_mode="prompted"))

        assert recorded[0][3] == "prompted"

    def test_resolved_model_carries_the_registry_mode(self):
        assert resolve_model(CLAUDE_PROMPTED).output_mode == "prompted"
        assert resolve_model(GPT).output_mode == "tool"

    def test_prompted_is_refused_over_the_copilot_sdk(self, recorded):
        with pytest.raises(ValidationError, match="output_mode='prompted'"):
            _build_model(AgentModelSchema(name=COPILOT, output_mode="prompted"))

        assert recorded == []


def _agent(model: str, thinking_budget: dict | None = None, effort: str | None = None):
    return SimpleNamespace(
        model=model,
        cache_ttl="5m",
        thinking_budget=thinking_budget,
        max_tokens=None,
        effort=effort,
    )


class TestBuildModelSettings:
    def test_claude_on_foundry_gets_anthropic_settings(self):
        settings = build_model_settings(_agent(CLAUDE_ADAPTIVE))

        assert settings is not None
        assert settings["anthropic_cache"] is True

    def test_chat_completions_gets_none(self):
        assert build_model_settings(_agent(GPT)) is None

    def test_copilot_gets_none(self):
        assert build_model_settings(_agent(COPILOT)) is None

    def test_an_adaptive_model_gets_adaptive_thinking(self):
        settings = build_model_settings(_agent(CLAUDE_ADAPTIVE, {"max_thinking_tokens": 2000}))

        assert settings["anthropic_thinking"] == {"type": "adaptive"}

    def test_a_budget_model_keeps_an_explicit_token_budget(self):
        settings = build_model_settings(_agent(CLAUDE_BUDGET, {"max_thinking_tokens": 2000}))

        assert settings["anthropic_thinking"] == {"type": "enabled", "budget_tokens": 2000}
        assert settings["max_tokens"] > 2000

    def test_no_thinking_budget_means_no_thinking_setting(self):
        assert "anthropic_thinking" not in build_model_settings(_agent(CLAUDE_ADAPTIVE))

    def test_effort_is_sent_for_a_model_called_over_the_messages_api(self):
        settings = build_model_settings(_agent(CLAUDE_ADAPTIVE, effort="medium"))

        assert settings["anthropic_effort"] == "medium"

    def test_no_effort_means_no_effort_setting(self):
        assert "anthropic_effort" not in build_model_settings(_agent(CLAUDE_ADAPTIVE))

    def test_effort_does_not_apply_to_chat_completions(self):
        assert build_model_settings(_agent(GPT, effort="medium")) is None

    def test_thinking_and_effort_can_be_combined(self):
        settings = build_model_settings(
            _agent(CLAUDE_ADAPTIVE, {"max_thinking_tokens": 2000}, effort="medium")
        )

        assert settings["anthropic_thinking"] == {"type": "adaptive"}
        assert settings["anthropic_effort"] == "medium"
