"""Unit tests for credential_status: presence is reported, the value never is."""

from modules.backend.core.config import get_app_config
from modules.backend.core.model_providers import credential_status


def test_provider_without_a_providers_yaml_entry_is_not_checked():
    assert not hasattr(get_app_config().providers, "copilot")
    assert credential_status("copilot") == "not_checked"


def test_entra_provider_is_not_checked():
    assert get_app_config().providers.foundry.auth_mode == "entra"
    assert credential_status("foundry") == "not_checked"


def test_api_key_provider_is_missing_without_its_env_var(monkeypatch):
    env_var = get_app_config().providers.openai.env_var
    monkeypatch.delenv(env_var, raising=False)

    assert credential_status("openai") == "missing"


def test_api_key_provider_is_present_with_its_env_var(monkeypatch):
    env_var = get_app_config().providers.openai.env_var
    monkeypatch.setenv(env_var, "set-by-test")

    assert credential_status("openai") == "present"
