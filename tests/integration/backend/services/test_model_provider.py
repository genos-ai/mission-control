"""
Integration tests for ModelProviderService.

Real database and the real models.yaml / providers.yaml. Ping tests cover
selection and validation only: a live provider call needs credentials and
network, so those are exercised by running `admin.py catalog ping`.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config import get_app_config
from modules.backend.core.config_schema import ProvidersSchema
from modules.backend.core.exceptions import ValidationError
from modules.backend.services.agent_catalog import AgentCatalogService
from modules.backend.services.model_provider import ModelProviderService


def _registry_model() -> str:
    """A qualified model that is in the registry, taken from the real config."""
    registry = get_app_config().models.models_by_provider()
    provider = sorted(registry)[0]
    return f"{provider}:{registry[provider][0]}"


async def _add_agent(db: AsyncSession, name: str, model_config: dict) -> None:
    await AgentCatalogService(db).create_entry(
        agent_name=name,
        agent_type="vertical",
        description="provider listing test",
        model_config_json=model_config,
    )


def _find_model(listing, qualified_name: str):
    for provider in listing.providers:
        for model in provider.models:
            if model.qualified_name == qualified_name:
                return model
    return None


class TestListProviders:
    async def test_every_registry_model_is_listed_as_registered(self, db_session: AsyncSession):
        listing = await ModelProviderService(db_session).list_providers()

        for provider, models in get_app_config().models.models_by_provider().items():
            for name in models:
                found = _find_model(listing, f"{provider}:{name}")
                assert found is not None, f"{provider}:{name} missing from the listing"
                assert found.registered is True

    async def test_providers_without_models_are_still_listed(self, db_session: AsyncSession):
        listing = await ModelProviderService(db_session).list_providers()

        names = {p.provider for p in listing.providers}
        assert ProvidersSchema.provider_names() <= names
        assert "copilot_client" not in names

    async def test_agent_using_a_model_is_attributed_to_it(self, db_session: AsyncSession):
        model = _registry_model()
        await _add_agent(db_session, "test.provider_listing.agent", {"name": model})

        listing = await ModelProviderService(db_session).list_providers()

        assert "test.provider_listing.agent" in _find_model(listing, model).agents

    async def test_agent_on_an_unregistered_model_is_flagged(self, db_session: AsyncSession):
        provider = sorted(get_app_config().models.registry)[0]
        unregistered = f"{provider}:not-a-real-model"
        await _add_agent(db_session, "test.unregistered.agent", {"name": unregistered})

        listing = await ModelProviderService(db_session).list_providers()

        found = _find_model(listing, unregistered)
        assert found is not None
        assert found.registered is False
        assert found.agents == ["test.unregistered.agent"]

    async def test_agent_naming_an_alias_counts_toward_the_aliased_model(
        self, db_session: AsyncSession
    ):
        alias, target = next(iter(get_app_config().models.aliases.items()))
        await _add_agent(db_session, "test.alias_agent.agent", {"name": alias})

        listing = await ModelProviderService(db_session).list_providers()

        found = _find_model(listing, target)
        assert "test.alias_agent.agent" in found.agents
        assert alias in found.aliases

    async def test_agent_without_a_model_name_is_reported(self, db_session: AsyncSession):
        # The service refuses a model block without a name, so corrupt the row directly.
        await _add_agent(db_session, "test.no_model.agent", {"name": _registry_model()})
        row = await AgentCatalogService(db_session).get_by_name("test.no_model.agent")
        row.model_config_json = {"temperature": 0.0}
        await db_session.flush()

        listing = await ModelProviderService(db_session).list_providers()

        assert "test.no_model.agent" in listing.agents_without_model

    async def test_agent_naming_an_unknown_alias_fails_loudly(self, db_session: AsyncSession):
        await _add_agent(db_session, "test.bad_alias.agent", {"name": "no-such-alias"})

        with pytest.raises(ValidationError, match="no-such-alias"):
            await ModelProviderService(db_session).list_providers()


class TestPingSelection:
    async def test_nothing_selected_is_refused(self, db_session: AsyncSession):
        with pytest.raises(ValidationError, match="Select at least one model"):
            await ModelProviderService(db_session).ping(models=[], providers=[], all_models=False)

    async def test_unknown_provider_is_refused(self, db_session: AsyncSession):
        with pytest.raises(ValidationError, match="not-a-provider"):
            await ModelProviderService(db_session).ping(
                models=[], providers=["not-a-provider"], all_models=False
            )

    async def test_unregistered_model_is_refused(self, db_session: AsyncSession):
        provider = sorted(get_app_config().models.registry)[0]
        with pytest.raises(ValidationError, match="not in the model registry"):
            await ModelProviderService(db_session).ping(
                models=[f"{provider}:not-a-real-model"], providers=[], all_models=False
            )

    async def test_model_without_a_provider_prefix_or_alias_is_refused(
        self, db_session: AsyncSession
    ):
        with pytest.raises(ValidationError, match="Unknown model alias"):
            await ModelProviderService(db_session).ping(
                models=["gpt"], providers=[], all_models=False
            )

    async def test_one_bad_model_stops_the_whole_selection(self, db_session: AsyncSession):
        """Nothing is called when any selected model is invalid."""
        provider = sorted(get_app_config().models.registry)[0]
        with pytest.raises(ValidationError):
            await ModelProviderService(db_session).ping(
                models=[_registry_model(), f"{provider}:not-a-real-model"],
                providers=[],
                all_models=False,
            )


class TestPlanSwitch:
    """set-provider planning, against the real registry (anthropic, copilot, foundry)."""

    async def test_names_differing_only_in_punctuation_map_automatically(
        self, db_session: AsyncSession
    ):
        await _add_agent(db_session, "test.switch_a.agent", {"name": "copilot:claude-opus-4.6"})

        changes = await ModelProviderService(db_session).plan_switch(
            provider="anthropic", model_map={}
        )

        assert [(c.agent_name, c.new_model) for c in changes] == [
            ("test.switch_a.agent", "anthropic:claude-opus-4-6")
        ]

    async def test_other_config_survives_and_only_the_name_changes(self, db_session: AsyncSession):
        await _add_agent(
            db_session,
            "test.switch_cfg.agent",
            {"name": "copilot:claude-haiku-4.5", "temperature": 0.2, "max_tokens": 777},
        )

        (change,) = await ModelProviderService(db_session).plan_switch(
            provider="anthropic", model_map={}
        )

        assert change.new_config == {
            "name": "anthropic:claude-haiku-4-5",
            "temperature": 0.2,
            "max_tokens": 777,
        }

    async def test_agents_already_on_the_provider_are_left_alone(self, db_session: AsyncSession):
        await _add_agent(db_session, "test.switch_same.agent", {"name": "copilot:claude-opus-4.6"})

        changes = await ModelProviderService(db_session).plan_switch(
            provider="copilot", model_map={}
        )

        assert changes == []

    async def test_cross_family_without_a_map_is_refused_and_lists_every_gap(
        self, db_session: AsyncSession
    ):
        await _add_agent(db_session, "test.gap_a.agent", {"name": "copilot:claude-opus-4.6"})
        await _add_agent(db_session, "test.gap_b.agent", {"name": "copilot:claude-haiku-4.5"})

        with pytest.raises(ValidationError) as raised:
            await ModelProviderService(db_session).plan_switch(provider="foundry", model_map={})

        message = str(raised.value)
        assert "test.gap_a.agent" in message and "test.gap_b.agent" in message
        assert "nothing was changed" in message

    async def test_map_keys_match_ignoring_punctuation(self, db_session: AsyncSession):
        await _add_agent(db_session, "test.map_a.agent", {"name": "copilot:claude-opus-4.6"})

        (change,) = await ModelProviderService(db_session).plan_switch(
            provider="foundry", model_map={"claude-opus-4-6": "gpt-5.4"}
        )

        assert change.new_model == "foundry:gpt-5.4"

    async def test_one_unmappable_agent_blocks_the_whole_switch(self, db_session: AsyncSession):
        await _add_agent(db_session, "test.ok.agent", {"name": "copilot:claude-opus-4.6"})
        await _add_agent(db_session, "test.stuck.agent", {"name": "copilot:claude-haiku-4.5"})

        with pytest.raises(ValidationError, match="test.stuck.agent"):
            await ModelProviderService(db_session).plan_switch(
                provider="foundry", model_map={"claude-opus-4-6": "gpt-5.4"}
            )

    async def test_an_output_mode_the_target_cannot_honour_blocks_the_whole_switch(
        self, db_session: AsyncSession
    ):
        """Caught at planning, so PATCH never refuses an agent mid-switch."""
        await _add_agent(db_session, "test.mode_ok.agent", {"name": "foundry:gpt-5-mini"})
        await _add_agent(
            db_session,
            "test.mode_native.agent",
            {"name": "foundry:gpt-5.4", "output_mode": "native"},
        )

        with pytest.raises(ValidationError) as raised:
            await ModelProviderService(db_session).plan_switch(
                provider="anthropic",
                model_map={"gpt-5-mini": "claude-haiku-4-5", "gpt-5.4": "claude-opus-4-6"},
            )

        message = str(raised.value)
        assert "test.mode_native.agent" in message and "output_mode" in message
        assert "test.mode_ok.agent:" not in message

    async def test_agent_naming_an_alias_is_refused(self, db_session: AsyncSession):
        alias = next(iter(get_app_config().models.aliases))
        await _add_agent(db_session, "test.switch_alias.agent", {"name": alias})

        with pytest.raises(ValidationError, match="catalog aliases set"):
            await ModelProviderService(db_session).plan_switch(provider="copilot", model_map={})

    async def test_unknown_provider_is_refused(self, db_session: AsyncSession):
        with pytest.raises(ValidationError, match="not-a-provider"):
            await ModelProviderService(db_session).plan_switch(
                provider="not-a-provider", model_map={}
            )

    async def test_map_target_outside_the_registry_is_refused(self, db_session: AsyncSession):
        with pytest.raises(ValidationError, match="not a foundry registry model"):
            await ModelProviderService(db_session).plan_switch(
                provider="foundry", model_map={"claude-opus-4-6": "gpt-99"}
            )


class TestParseModelMap:
    def test_pairs_are_parsed(self):
        assert ModelProviderService.parse_model_map("a=b, c = d") == {"a": "b", "c": "d"}

    def test_empty_is_an_empty_map(self):
        assert ModelProviderService.parse_model_map(None) == {}

    @pytest.mark.parametrize("raw", ["a", "a=", "=b", "a=b,c"])
    def test_malformed_entries_are_refused(self, raw):
        with pytest.raises(ValidationError, match="Malformed model map entry"):
            ModelProviderService.parse_model_map(raw)
