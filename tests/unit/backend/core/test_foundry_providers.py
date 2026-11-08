"""Unit tests for the Foundry client factories: endpoints, client types and auth modes.

The endpoint paths come from the foundry block under test, never from code. No
request is made; these check how the clients are configured.
"""

import pytest
from anthropic import AsyncAnthropicFoundry

from modules.backend.core import model_providers
from modules.backend.core.config import get_app_config
from modules.backend.core.config_schema import ProviderAuthSchema
from modules.backend.core.model_backends import ANTHROPIC_MESSAGES, OPENAI_CHAT
from modules.backend.core.model_providers import OPENAI_RESPONSES

BASE_URL = "https://example-resource.openai.azure.com/"
PATHS = {OPENAI_CHAT: "/chat-path/", ANTHROPIC_MESSAGES: "/messages-path"}


class _FakeCredential:
    async def get_token(self, *scopes, **kwargs):  # pragma: no cover - never called
        raise AssertionError("no token should be requested while building the client")


@pytest.fixture
def foundry_config(monkeypatch):
    """Point the provider at a throwaway foundry block with a fake credential."""

    def apply(**overrides):
        config = ProviderAuthSchema(
            **{
                "auth_mode": "entra",
                "base_url": BASE_URL,
                "scope": "https://ai.azure.com/.default",
                "endpoint_paths": PATHS,
                **overrides,
            }
        )
        monkeypatch.setattr(
            model_providers,
            "_get_provider_config",
            lambda: type("P", (), {"foundry": config})(),
        )
        monkeypatch.setattr(model_providers, "get_foundry_credential", lambda: _FakeCredential())
        return config

    return apply


class TestEndpoint:
    def test_base_url_and_path_are_joined_with_one_slash_each_side(self, foundry_config):
        config = foundry_config()

        assert (
            model_providers._foundry_endpoint(config, ANTHROPIC_MESSAGES)
            == "https://example-resource.openai.azure.com/messages-path/"
        )
        assert (
            model_providers._foundry_endpoint(config, OPENAI_CHAT)
            == "https://example-resource.openai.azure.com/chat-path/"
        )

    def test_a_protocol_with_no_path_is_refused(self, foundry_config):
        config = foundry_config(endpoint_paths={OPENAI_CHAT: "/chat-path/"})

        with pytest.raises(ValueError, match=f"endpoint_paths.{ANTHROPIC_MESSAGES}"):
            model_providers._foundry_endpoint(config, ANTHROPIC_MESSAGES)

    def test_missing_base_url_is_refused(self, foundry_config):
        config = foundry_config(base_url=None)

        with pytest.raises(ValueError, match="base_url"):
            model_providers._foundry_endpoint(config, OPENAI_CHAT)


class TestAnthropicProvider:
    def test_entra_client_targets_the_configured_messages_path(self, foundry_config):
        foundry_config()

        client = model_providers.get_foundry_anthropic_provider().client

        assert isinstance(client, AsyncAnthropicFoundry)
        assert str(client.base_url) == "https://example-resource.openai.azure.com/messages-path/"

    def test_the_shipped_foundry_block_builds_a_client_at_its_configured_path(self):
        config = get_app_config().providers.foundry
        path = config.endpoint_paths[ANTHROPIC_MESSAGES]

        client = model_providers.get_foundry_anthropic_provider().client

        assert str(client.base_url) == f"{config.base_url.rstrip('/')}/{path.strip('/')}/"

    def test_api_key_mode_needs_its_env_var(self, foundry_config, monkeypatch):
        foundry_config(auth_mode="api_key", env_var="FOUNDRY_TEST_KEY", scope=None)
        monkeypatch.delenv("FOUNDRY_TEST_KEY", raising=False)

        with pytest.raises(ValueError, match="FOUNDRY_TEST_KEY"):
            model_providers.get_foundry_anthropic_provider()

    def test_api_key_mode_builds_a_client_when_the_key_is_set(self, foundry_config, monkeypatch):
        foundry_config(auth_mode="api_key", env_var="FOUNDRY_TEST_KEY", scope=None)
        monkeypatch.setenv("FOUNDRY_TEST_KEY", "set-by-test")

        client = model_providers.get_foundry_anthropic_provider().client

        assert isinstance(client, AsyncAnthropicFoundry)

    def test_entra_mode_needs_a_scope(self, foundry_config):
        foundry_config(scope=None)

        with pytest.raises(ValueError, match="scope"):
            model_providers.get_foundry_anthropic_provider()

    def test_unsupported_auth_mode_is_refused(self, foundry_config):
        foundry_config(auth_mode="codex_oauth")

        with pytest.raises(ValueError, match="not supported"):
            model_providers.get_foundry_anthropic_provider()


class TestChatProvider:
    def test_client_targets_the_configured_chat_path(self, foundry_config):
        foundry_config()

        client = model_providers.get_foundry_provider().client

        assert str(client.base_url) == "https://example-resource.openai.azure.com/chat-path/"

    def test_a_missing_chat_path_is_refused(self, foundry_config):
        foundry_config(endpoint_paths={ANTHROPIC_MESSAGES: "/messages-path"})

        with pytest.raises(ValueError, match=f"endpoint_paths.{OPENAI_CHAT}"):
            model_providers.get_foundry_provider()


PROJECT_URL = "https://example-account.services.ai.azure.com/api/projects/example-project"


@pytest.fixture
def project_config(monkeypatch):
    """Point the project provider at a throwaway foundry_project block."""

    def apply(**overrides):
        config = ProviderAuthSchema(
            **{
                "auth_mode": "entra",
                "base_url": PROJECT_URL,
                "scope": "https://ai.azure.com/.default",
                "endpoint_paths": {OPENAI_RESPONSES: "/responses-path/"},
                **overrides,
            }
        )
        monkeypatch.setattr(
            model_providers,
            "_get_provider_config",
            lambda: type("P", (), {"foundry_project": config})(),
        )
        monkeypatch.setattr(model_providers, "get_foundry_credential", lambda: _FakeCredential())
        return config

    return apply


class TestProjectProvider:
    def test_client_targets_the_configured_responses_path(self, project_config):
        project_config()

        client = model_providers.get_foundry_project_provider()

        assert str(client.base_url) == f"{PROJECT_URL}/responses-path/"

    def test_the_shipped_project_block_builds_a_client_at_its_configured_path(self):
        config = get_app_config().providers.foundry_project
        path = config.endpoint_paths[OPENAI_RESPONSES]

        client = model_providers.get_foundry_project_provider()

        assert str(client.base_url) == f"{config.base_url.rstrip('/')}/{path.strip('/')}/"

    def test_a_missing_responses_path_is_refused(self, project_config):
        project_config(endpoint_paths={})

        with pytest.raises(ValueError, match=f"endpoint_paths.{OPENAI_RESPONSES}"):
            model_providers.get_foundry_project_provider()

    def test_a_missing_base_url_is_refused_and_names_the_provider(self, project_config):
        project_config(base_url=None)

        with pytest.raises(ValueError, match="foundry_project provider requires base_url"):
            model_providers.get_foundry_project_provider()

    def test_entra_mode_needs_a_scope(self, project_config):
        project_config(scope=None)

        with pytest.raises(ValueError, match="scope"):
            model_providers.get_foundry_project_provider()

    def test_the_responses_key_is_not_a_model_registry_protocol(self):
        from modules.backend.core.model_backends import BACKENDS

        assert all(OPENAI_RESPONSES not in protocols for protocols in BACKENDS.values())
