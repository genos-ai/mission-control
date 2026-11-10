"""Every per-agent model setting round-trips through the agent catalog.

YAML -> seeder -> catalog row -> registry config / roster -> built model, and
PATCH /admin/catalog through the service, which checks output_mode against the
model's protocol. Before this, the catalog kept only name, temperature and
max_tokens, so output_mode and betas validated in YAML and were then dropped.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from modules.backend.agents.mission_control.roster import RosterModelSchema
from modules.backend.core.agent_registry import _db_row_to_config
from modules.backend.core.database import get_db_session
from modules.backend.core.dependencies import require_admin
from modules.backend.core.exceptions import ValidationError
from modules.backend.core.model_builder import (
    build_model_settings,
    effective_output_mode,
    resolve_model,
)
from modules.backend.schemas.agent_config import AgentConfigSchema, AgentModelSchema
from modules.backend.services.agent_catalog import AgentCatalogService, validated_model_config
from modules.backend.services.catalog_seeder import _extract_model_config

# Registry entries (config/settings/models.yaml): an anthropic_messages model whose
# registry mode is the default 'tool', and an openai_chat one.
CLAUDE = "foundry:claude-haiku-5-5"
GPT = "foundry:gpt-5-mini"

YAML_AGENT = {
    "agent_name": "test.model_settings.agent",
    "agent_type": "vertical",
    "description": "An agent with every model setting",
    "enabled": True,
    "model": {
        "name": CLAUDE,
        "temperature": 0.3,
        "max_tokens": 2048,
        "output_mode": "prompted",
        "betas": ["structured-outputs-2025-11-13"],
    },
    "max_input_length": 1000,
    "max_budget_usd": 0.1,
    "execution": {"mode": "local"},
}


def _row(model_config_json: dict) -> SimpleNamespace:
    """A catalog row as the registry reads it."""
    return SimpleNamespace(
        agent_name="test.model_settings.agent",
        agent_type="vertical",
        description="An agent with every model setting",
        enabled=True,
        model_config_json=model_config_json,
        keywords=[],
        tools=[],
        max_input_length=1000,
        max_budget_usd=0.1,
        execution_mode="local",
        invocation_tier="user",
        invocation_required_role=None,
        scope={"read": [], "write": []},
        interface=None,
        version="1.0.0",
        chat_enabled=False,
        thinking_budget_json=None,
        engine="pydantic_ai",
        effort=None,
        produces_artifact=False,
        artifact_type=None,
        system_prompt="",
    )


def _seeded_row() -> SimpleNamespace:
    return _row(_extract_model_config(AgentConfigSchema(**YAML_AGENT).model))


class TestSeedToRuntime:
    def test_output_mode_and_betas_survive_seeder_row_and_registry(self):
        model = _db_row_to_config(_seeded_row()).model

        assert isinstance(model, AgentModelSchema)
        assert model == AgentModelSchema(**YAML_AGENT["model"])

    def test_the_agent_mode_beats_the_registry_mode_at_build_time(self):
        model = _db_row_to_config(_seeded_row()).model
        resolved = resolve_model(CLAUDE)

        assert resolved.output_mode == "tool"
        assert effective_output_mode(model, resolved) == "prompted"

    def test_betas_reach_the_model_settings(self):
        settings = build_model_settings(_db_row_to_config(_seeded_row()))

        assert settings["anthropic_betas"] == ["structured-outputs-2025-11-13"]

    def test_the_roster_carries_every_setting(self):
        roster_model = RosterModelSchema.from_catalog(_seeded_row().model_config_json)

        assert roster_model.output_mode == "prompted"
        assert roster_model.betas == ["structured-outputs-2025-11-13"]


class TestRowsSeededBeforeTheFix:
    LEGACY = {"name": CLAUDE, "temperature": 0.0, "max_tokens": 4096}

    def test_absent_keys_leave_output_mode_to_the_registry(self):
        model = _db_row_to_config(_row(dict(self.LEGACY))).model

        assert model.output_mode is None
        assert model.betas == []
        assert effective_output_mode(model, resolve_model(CLAUDE)) == "tool"

    def test_a_null_value_counts_as_absent(self):
        model = _db_row_to_config(_row({**self.LEGACY, "output_mode": None})).model

        assert model.output_mode is None

    def test_the_roster_reads_a_legacy_row_too(self):
        assert RosterModelSchema.from_catalog(dict(self.LEGACY)).output_mode is None


class TestValidatedModelConfig:
    def test_a_mode_the_protocol_honours_is_kept(self):
        stored = validated_model_config({"name": CLAUDE, "output_mode": "prompted"})

        assert stored["output_mode"] == "prompted"

    @pytest.mark.parametrize(("name", "mode"), [(CLAUDE, "native"), (GPT, "bogus")])
    def test_a_mode_the_model_cannot_honour_is_refused(self, name, mode):
        with pytest.raises(ValidationError):
            validated_model_config({"name": name, "output_mode": mode})

    def test_native_on_openai_chat_is_accepted(self):
        assert validated_model_config({"name": GPT, "output_mode": "native"})["output_mode"] == (
            "native"
        )

    def test_an_unknown_key_is_refused(self):
        with pytest.raises(ValidationError, match="model_config_json"):
            validated_model_config({"name": CLAUDE, "outputmode": "prompted"})

    def test_clearing_output_mode_with_null_drops_the_key(self):
        assert "output_mode" not in validated_model_config({"name": CLAUDE, "output_mode": None})


@pytest.fixture
def service(db_session) -> AgentCatalogService:
    return AgentCatalogService(db_session)


@pytest.fixture
async def client(db_session):
    from modules.backend.api.v1.endpoints import admin as admin_module
    from modules.backend.core.exception_handlers import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_module.router, prefix="/admin")

    async def _admin():
        return MagicMock(id="test-admin", has_role=lambda r: True, is_active=True)

    async def _db():
        return db_session

    app.dependency_overrides[require_admin] = _admin
    app.dependency_overrides[get_db_session] = _db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _create(service: AgentCatalogService) -> None:
    await service.create_entry(
        agent_name="test.model_settings.agent",
        agent_type="vertical",
        description="An agent with every model setting",
        model_config_json={"name": CLAUDE, "temperature": 0.0, "max_tokens": 4096},
    )


class TestPatchCatalog:
    @pytest.mark.asyncio
    async def test_patch_stores_output_mode_and_betas(self, service, client):
        await _create(service)

        resp = await client.patch(
            "/admin/catalog/test.model_settings.agent",
            json={
                "model_config_json": {
                    "name": CLAUDE,
                    "output_mode": "prompted",
                    "betas": ["b1"],
                }
            },
        )

        assert resp.status_code == 200
        entry = await service.get_by_name("test.model_settings.agent")
        assert entry.model_config_json["output_mode"] == "prompted"
        assert entry.model_config_json["betas"] == ["b1"]
        assert _db_row_to_config(entry).model.output_mode == "prompted"

    @pytest.mark.asyncio
    async def test_patch_refuses_a_mode_the_protocol_cannot_honour(self, service, client):
        await _create(service)

        resp = await client.patch(
            "/admin/catalog/test.model_settings.agent",
            json={"model_config_json": {"name": CLAUDE, "output_mode": "native"}},
        )

        assert resp.status_code == 400
        assert "output_mode='native'" in resp.text
        entry = await service.get_by_name("test.model_settings.agent")
        assert "output_mode" not in entry.model_config_json
