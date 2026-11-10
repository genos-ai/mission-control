"""Unit tests for the backend table and the registry and provider schemas checked against it."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from modules.backend.core.config import get_app_config
from modules.backend.core.config_schema import ModelsSchema, ProvidersSchema
from modules.backend.core.model_backends import (
    ANTHROPIC_MESSAGES,
    BACKENDS,
    COPILOT_SDK,
    OPENAI_CHAT,
)


def _models(**fields) -> ModelsSchema:
    """A ModelsSchema with the required aliases left empty; these tests are about the registry."""
    return ModelsSchema(aliases={}, **fields)


class TestBackendTable:
    def test_every_entry_is_a_callable_builder(self):
        for provider, protocols in BACKENDS.items():
            for protocol, builder in protocols.items():
                assert callable(builder), f"{provider}/{protocol}"

    def test_a_provider_can_serve_more_than_one_protocol(self):
        assert any(len(protocols) > 1 for protocols in BACKENDS.values())

    def test_the_shipped_registry_only_uses_supported_pairs(self):
        for provider, models in get_app_config().models.registry.items():
            for model, spec in models.items():
                assert spec.protocol in BACKENDS[provider], f"{provider}:{model}"

    def test_the_shipped_provider_config_only_names_supported_protocols(self):
        for provider in BACKENDS:
            block = getattr(get_app_config().providers, provider, None)
            if block is None:  # e.g. copilot signs in through its own SDK
                continue
            for protocol in [*block.endpoint_paths, *block.deployment_protocols.values()]:
                assert protocol in BACKENDS[provider], f"{provider}: {protocol}"


class TestRegistrySchema:
    def test_each_model_carries_its_protocol_and_thinking_style(self):
        models = _models(
            registry={
                "foundry": {
                    "gpt-a": {"protocol": OPENAI_CHAT},
                    "claude-a": {"protocol": ANTHROPIC_MESSAGES, "thinking": "adaptive"},
                },
                "copilot": {"copilot-a": {"protocol": COPILOT_SDK}},
            }
        )

        assert models.spec_of("foundry", "gpt-a").protocol == OPENAI_CHAT
        assert models.spec_of("foundry", "claude-a").thinking == "adaptive"
        assert models.models_of("foundry") == ["gpt-a", "claude-a"]
        assert models.models_by_provider() == {
            "foundry": ["gpt-a", "claude-a"],
            "copilot": ["copilot-a"],
        }

    def test_thinking_defaults_to_a_token_budget(self):
        models = _models(registry={"anthropic": {"c": {"protocol": ANTHROPIC_MESSAGES}}})

        assert models.spec_of("anthropic", "c").thinking == "budget"

    def test_an_unregistered_model_or_provider_has_no_spec(self):
        models = _models(registry={"foundry": {"gpt-a": {"protocol": OPENAI_CHAT}}})

        assert models.spec_of("foundry", "unknown") is None
        assert models.spec_of("anthropic", "gpt-a") is None
        assert models.models_of("anthropic") == []

    def test_unknown_provider_is_rejected(self):
        with pytest.raises(PydanticValidationError, match="unknown provider 'bedrock'"):
            _models(registry={"bedrock": {"x": {"protocol": OPENAI_CHAT}}})

    def test_protocol_the_provider_does_not_support_is_rejected(self):
        with pytest.raises(PydanticValidationError, match="unknown protocol 'copilot_sdk'"):
            _models(registry={"foundry": {"x": {"protocol": COPILOT_SDK}}})

    def test_thinking_on_a_protocol_that_ignores_it_is_rejected(self):
        with pytest.raises(PydanticValidationError, match="'thinking' applies only to"):
            _models(registry={"foundry": {"x": {"protocol": OPENAI_CHAT, "thinking": "adaptive"}}})

    def test_an_unknown_thinking_style_is_rejected(self):
        with pytest.raises(PydanticValidationError):
            _models(
                registry={"anthropic": {"x": {"protocol": ANTHROPIC_MESSAGES, "thinking": "max"}}}
            )

    def test_output_mode_defaults_to_tool(self):
        models = _models(registry={"foundry": {"gpt-a": {"protocol": OPENAI_CHAT}}})

        assert models.spec_of("foundry", "gpt-a").output_mode == "tool"

    @pytest.mark.parametrize(
        ("provider", "protocol", "mode"),
        [
            ("foundry", ANTHROPIC_MESSAGES, "prompted"),
            ("anthropic", ANTHROPIC_MESSAGES, "prompted"),
            ("foundry", OPENAI_CHAT, "prompted"),
            ("foundry", OPENAI_CHAT, "native"),
            ("copilot", COPILOT_SDK, "tool"),
        ],
    )
    def test_output_mode_the_protocol_supports_is_accepted(self, provider, protocol, mode):
        models = _models(registry={provider: {"m": {"protocol": protocol, "output_mode": mode}}})

        assert models.spec_of(provider, "m").output_mode == mode

    @pytest.mark.parametrize(
        ("provider", "protocol", "mode"),
        [
            ("foundry", ANTHROPIC_MESSAGES, "native"),
            ("copilot", COPILOT_SDK, "prompted"),
            ("copilot", COPILOT_SDK, "native"),
        ],
    )
    def test_output_mode_the_protocol_cannot_honour_is_rejected(self, provider, protocol, mode):
        with pytest.raises(PydanticValidationError, match=f"output_mode='{mode}'"):
            _models(registry={provider: {"m": {"protocol": protocol, "output_mode": mode}}})

    def test_an_unknown_output_mode_is_rejected(self):
        with pytest.raises(PydanticValidationError):
            _models(registry={"foundry": {"m": {"protocol": OPENAI_CHAT, "output_mode": "json"}}})

    def test_shipped_sonnet_5_5_uses_prompted_output(self):
        # Foundry claude-sonnet-5-5 answers HTTP 400 to a forced tool choice.
        spec = get_app_config().models.spec_of("foundry", "claude-sonnet-5-5")

        assert spec is not None and spec.output_mode == "prompted"

    def test_an_unknown_key_on_a_model_is_rejected(self):
        with pytest.raises(PydanticValidationError):
            _models(registry={"foundry": {"x": {"protocol": OPENAI_CHAT, "colour": "red"}}})

    @pytest.mark.parametrize(
        "old_shape",
        [
            {"foundry": ["gpt-a"]},
            {"foundry": {OPENAI_CHAT: ["gpt-a"]}},
        ],
    )
    def test_earlier_registry_shapes_are_rejected(self, old_shape):
        with pytest.raises(PydanticValidationError):
            _models(registry=old_shape)


class TestProvidersSchema:
    def test_an_endpoint_path_for_an_unknown_protocol_is_rejected(self):
        with pytest.raises(PydanticValidationError, match="unknown protocol 'nope'"):
            ProvidersSchema(foundry={"endpoint_paths": {"nope": "/x"}})

    def test_a_deployment_format_mapped_to_an_unknown_protocol_is_rejected(self):
        with pytest.raises(PydanticValidationError, match="unknown protocol 'nope'"):
            ProvidersSchema(foundry={"deployment_protocols": {"Acme": "nope"}})

    def test_known_protocols_are_accepted(self):
        providers = ProvidersSchema(
            foundry={
                "endpoint_paths": {OPENAI_CHAT: "/a/", ANTHROPIC_MESSAGES: "/b"},
                "deployment_protocols": {"Acme": OPENAI_CHAT},
            }
        )

        assert providers.foundry.endpoint_paths[ANTHROPIC_MESSAGES] == "/b"
