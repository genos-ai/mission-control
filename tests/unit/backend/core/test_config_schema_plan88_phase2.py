"""Plan 88 Phase 2 (88.2.1): run hard stop and Copilot client health config."""

import pytest
from pydantic import ValidationError

from modules.backend.core.config import get_app_config
from modules.backend.core.config_schema import MissionRunSchema, ProvidersSchema


def _mission_run_data() -> dict:
    return get_app_config().temporal.mission_run.model_dump()


def test_max_run_duration_loads_from_yaml() -> None:
    assert get_app_config().temporal.mission_run.max_run_duration_seconds == 43200


def test_max_run_duration_required() -> None:
    data = _mission_run_data()
    del data["max_run_duration_seconds"]
    with pytest.raises(ValidationError):
        MissionRunSchema(**data)


def test_max_run_duration_floor() -> None:
    data = _mission_run_data()
    data["max_run_duration_seconds"] = 599
    with pytest.raises(ValidationError):
        MissionRunSchema(**data)


def test_copilot_client_required() -> None:
    with pytest.raises(ValidationError):
        ProvidersSchema()


def test_copilot_client_loads_from_yaml() -> None:
    assert get_app_config().providers.copilot_client.ping_timeout_seconds == 10


def test_provider_names_exclude_client_settings() -> None:
    names = ProvidersSchema.provider_names()
    assert "copilot_client" not in names
    assert {"anthropic", "openai", "foundry", "foundry_project"} <= names


def test_auth_for_ignores_client_settings() -> None:
    providers = get_app_config().providers
    assert providers.auth_for("copilot_client") is None
    assert providers.auth_for("anthropic") is providers.anthropic


async def test_list_providers_excludes_copilot_client(monkeypatch) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from modules.backend.services.model_provider import ModelProviderService

    service = ModelProviderService(MagicMock())
    monkeypatch.setattr(service, "_agents_by_model", AsyncMock(return_value=({}, [])))
    listing = await service.list_providers()
    names = {p.provider for p in listing.providers}
    assert "copilot_client" not in names
    assert "anthropic" in names
