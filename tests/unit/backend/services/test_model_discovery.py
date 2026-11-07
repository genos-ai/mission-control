"""Unit tests for model discovery: configuration checks and the registry comparison.

The Azure call itself needs a login and network, so it is exercised by running
`admin.py catalog discover --provider foundry`.
"""

from datetime import datetime, timezone

import pytest

from modules.backend.core.config_schema import ProviderAuthSchema
from modules.backend.core.exceptions import ValidationError
from modules.backend.core.model_discovery import (
    DISCOVERABLE_PROVIDERS,
    anthropic_aliases,
    discover_foundry_deployments,
    discover_models,
)
from modules.backend.schemas.model_provider import DiscoveredModel
from modules.backend.services.model_provider import ModelProviderService


def _discovered(name: str) -> DiscoveredModel:
    return DiscoveredModel(
        name=name, model=name, format="OpenAI", version="1", sku="Standard", state="Succeeded"
    )


class TestFoundryConfiguration:
    async def test_missing_resource_location_is_named_in_the_error(self):
        config = ProviderAuthSchema(auth_mode="entra", subscription_id="sub")

        with pytest.raises(ValidationError) as raised:
            await discover_foundry_deployments(config)

        assert "resource_group" in str(raised.value)
        assert "account_name" in str(raised.value)
        assert "subscription_id" not in str(raised.value)


class TestDiscoverModels:
    def test_foundry_is_discoverable(self):
        assert "foundry" in DISCOVERABLE_PROVIDERS

    def test_anthropic_is_discoverable(self):
        assert "anthropic" in DISCOVERABLE_PROVIDERS

    async def test_unsupported_provider_is_refused_with_the_supported_list(self):
        with pytest.raises(ValidationError, match="not supported for 'copilot'"):
            await discover_models("copilot")


class TestAnthropicAliases:
    def test_dated_snapshot_has_its_undated_alias(self):
        assert anthropic_aliases("claude-haiku-4-5-20251001") == ["claude-haiku-4-5"]

    def test_undated_id_has_no_alias(self):
        assert anthropic_aliases("claude-opus-4-6") == []

    def test_version_digits_are_not_mistaken_for_a_date(self):
        assert anthropic_aliases("claude-3-5-sonnet") == []


class TestCompareDiscovery:
    def test_deployed_and_registered_model_carries_its_agents(self):
        result = ModelProviderService.compare_discovery(
            "foundry",
            [_discovered("gpt-5.4")],
            registered=["gpt-5.4"],
            agents_by_model={"foundry:gpt-5.4": ["b.agent", "a.agent"]},
        )

        (model,) = result.models
        assert model.registered is True
        assert model.agents == ["a.agent", "b.agent"]
        assert result.not_deployed == []

    def test_deployed_but_unregistered_model_is_flagged(self):
        result = ModelProviderService.compare_discovery(
            "foundry", [_discovered("new-model")], registered=[], agents_by_model={}
        )

        assert result.models[0].registered is False
        assert result.models[0].agents == []

    def test_registered_but_not_deployed_model_is_reported_with_its_agents(self):
        result = ModelProviderService.compare_discovery(
            "foundry",
            [_discovered("gpt-5.4")],
            registered=["gpt-5.4", "retired-model"],
            agents_by_model={"foundry:retired-model": ["broken.agent"]},
        )

        (gone,) = result.not_deployed
        assert gone.name == "retired-model"
        assert gone.agents == ["broken.agent"]

    def test_agents_on_other_providers_are_not_attributed(self):
        result = ModelProviderService.compare_discovery(
            "foundry",
            [_discovered("gpt-5.4")],
            registered=["gpt-5.4"],
            agents_by_model={"copilot:gpt-5.4": ["other.agent"]},
        )

        assert result.models[0].agents == []


class TestCompareDiscoveryWithAliases:
    """Anthropic lists dated ids; the registry and agents use the undated alias."""

    @staticmethod
    def _dated(name: str, alias: str) -> DiscoveredModel:
        return DiscoveredModel(
            name=name,
            model="Claude",
            format="Anthropic",
            version=None,
            sku=None,
            state=None,
            aliases=[alias],
        )

    def test_registry_alias_matches_the_dated_id(self):
        result = ModelProviderService.compare_discovery(
            "anthropic",
            [self._dated("claude-haiku-4-5-20251001", "claude-haiku-4-5")],
            registered=["claude-haiku-4-5"],
            agents_by_model={},
        )

        assert result.models[0].registered is True
        assert result.not_deployed == []

    def test_agents_using_the_alias_count_toward_the_dated_id(self):
        result = ModelProviderService.compare_discovery(
            "anthropic",
            [self._dated("claude-haiku-4-5-20251001", "claude-haiku-4-5")],
            registered=["claude-haiku-4-5"],
            agents_by_model={
                "anthropic:claude-haiku-4-5": ["alias.agent"],
                "anthropic:claude-haiku-4-5-20251001": ["dated.agent"],
            },
        )

        assert result.models[0].agents == ["alias.agent", "dated.agent"]

    def test_registered_alias_with_no_matching_snapshot_is_not_deployed(self):
        result = ModelProviderService.compare_discovery(
            "anthropic",
            [self._dated("claude-haiku-4-5-20251001", "claude-haiku-4-5")],
            registered=["claude-opus-4-6"],
            agents_by_model={"anthropic:claude-opus-4-6": ["opus.agent"]},
        )

        assert [(m.name, m.agents) for m in result.not_deployed] == [
            ("claude-opus-4-6", ["opus.agent"])
        ]


class TestAnthropicListing:
    """Maps the SDK's own ModelInfo type, so an SDK change shows up here."""

    def test_sdk_model_info_maps_to_a_discovered_model(self):
        from anthropic.types import ModelInfo

        from modules.backend.core.model_discovery import to_discovered_anthropic_model

        info = ModelInfo(
            id="claude-haiku-4-5-20251001",
            display_name="Claude Haiku 4.5",
            created_at=datetime(2025, 10, 1, tzinfo=timezone.utc),
            type="model",
        )

        model = to_discovered_anthropic_model(info)

        assert model.name == "claude-haiku-4-5-20251001"
        assert model.model == "Claude Haiku 4.5"
        assert model.created == "2025-10-01"
        assert model.aliases == ["claude-haiku-4-5"]
        assert model.format == "Anthropic"


def _deployment(name: str, fmt: str) -> DiscoveredModel:
    return DiscoveredModel(
        name=name, model=name, format=fmt, version="1", sku="GlobalStandard", state="Succeeded"
    )


FORMATS = {"Anthropic": "anthropic_messages", "OpenAI": "openai_chat", "DeepSeek": "openai_chat"}


class TestFindProtocolMismatches:
    def test_claude_filed_under_openai_chat_is_reported_with_its_agents(self):
        result = ModelProviderService.find_protocol_mismatches(
            "foundry",
            [_deployment("claude-x", "Anthropic")],
            registered_protocols={"claude-x": "openai_chat"},
            deployment_protocols=FORMATS,
            agents_by_model={"foundry:claude-x": ["b.agent", "a.agent"]},
        )

        (wrong,) = result
        assert wrong.name == "claude-x"
        assert wrong.registered == "openai_chat"
        assert wrong.expected == "anthropic_messages"
        assert wrong.agents == ["a.agent", "b.agent"]

    def test_gpt_filed_under_anthropic_messages_is_reported(self):
        result = ModelProviderService.find_protocol_mismatches(
            "foundry",
            [_deployment("gpt-x", "OpenAI")],
            registered_protocols={"gpt-x": "anthropic_messages"},
            deployment_protocols=FORMATS,
            agents_by_model={},
        )

        assert [(m.name, m.expected) for m in result] == [("gpt-x", "openai_chat")]

    def test_matching_protocols_report_nothing(self):
        result = ModelProviderService.find_protocol_mismatches(
            "foundry",
            [_deployment("claude-x", "Anthropic"), _deployment("deepseek-x", "DeepSeek")],
            registered_protocols={"claude-x": "anthropic_messages", "deepseek-x": "openai_chat"},
            deployment_protocols=FORMATS,
            agents_by_model={},
        )

        assert result == []

    def test_deployments_that_are_not_registered_are_ignored(self):
        result = ModelProviderService.find_protocol_mismatches(
            "foundry",
            [_deployment("claude-x", "Anthropic")],
            registered_protocols={},
            deployment_protocols=FORMATS,
            agents_by_model={},
        )

        assert result == []

    def test_a_format_with_no_mapping_is_not_guessed_at(self):
        result = ModelProviderService.find_protocol_mismatches(
            "foundry",
            [_deployment("mystery-x", "Acme")],
            registered_protocols={"mystery-x": "anthropic_messages"},
            deployment_protocols=FORMATS,
            agents_by_model={},
        )

        assert result == []

    def test_a_registry_entry_using_the_undated_alias_is_checked(self):
        deployed = DiscoveredModel(
            name="claude-x-20251001",
            model="Claude X",
            format="Anthropic",
            version=None,
            sku=None,
            state=None,
            aliases=["claude-x"],
        )

        result = ModelProviderService.find_protocol_mismatches(
            "anthropic",
            [deployed],
            registered_protocols={"claude-x": "openai_chat"},
            deployment_protocols=FORMATS,
            agents_by_model={},
        )

        assert [m.name for m in result] == ["claude-x"]


class TestFindUnmappedFormats:
    def test_formats_without_a_mapping_are_listed_once_each(self):
        result = ModelProviderService.find_unmapped_formats(
            [_deployment("a", "Acme"), _deployment("b", "Acme"), _deployment("c", "OpenAI")],
            FORMATS,
        )

        assert result == ["Acme"]

    def test_fully_mapped_formats_report_nothing(self):
        assert (
            ModelProviderService.find_unmapped_formats([_deployment("a", "OpenAI")], FORMATS) == []
        )
