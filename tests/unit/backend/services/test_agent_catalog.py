"""Tests for AgentCatalogService."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ConflictError, NotFoundError
from modules.backend.services.agent_catalog import AgentCatalogService


@pytest.fixture
def service(db_session: AsyncSession) -> AgentCatalogService:
    return AgentCatalogService(db_session)


async def _create_agent(service: AgentCatalogService, **overrides):
    """Helper to create a catalog entry."""
    defaults = {
        "agent_name": "vertical.software.quality.agent",
        "agent_type": "vertical",
        "description": "Evaluates code quality",
        "model_config_json": {"name": "anthropic:claude-haiku-4-5-20251001", "temperature": 0.0, "max_tokens": 4096},
    }
    defaults.update(overrides)
    return await service.create_entry(**defaults)


class TestCreateEntry:
    @pytest.mark.asyncio
    async def test_creates_agent(self, service):
        entry = await _create_agent(service)
        assert entry.agent_name == "vertical.software.quality.agent"
        assert entry.agent_type == "vertical"
        assert entry.enabled is True
        assert entry.visibility == "public"

    @pytest.mark.asyncio
    async def test_duplicate_name_raises_conflict(self, service):
        await _create_agent(service)
        with pytest.raises(ConflictError, match="already exists"):
            await _create_agent(service)

    @pytest.mark.asyncio
    async def test_custom_fields(self, service):
        entry = await _create_agent(
            service,
            agent_name="platform.health.agent",
            agent_type="system",
            tools=["health_check", "ping"],
            keywords=["health", "monitoring"],
            visibility="system",
            constraints={"timeout_seconds": 30, "cost_ceiling_usd": 0.1},
        )
        assert entry.agent_type == "system"
        assert entry.visibility == "system"
        assert entry.tools == ["health_check", "ping"]
        assert entry.keywords == ["health", "monitoring"]
        assert entry.constraints["timeout_seconds"] == 30


class TestGetByName:
    @pytest.mark.asyncio
    async def test_found(self, service):
        await _create_agent(service)
        result = await service.get_by_name("vertical.software.quality.agent")
        assert result.agent_name == "vertical.software.quality.agent"

    @pytest.mark.asyncio
    async def test_not_found(self, service):
        with pytest.raises(NotFoundError, match="not found in catalog"):
            await service.get_by_name("nonexistent.agent")

    @pytest.mark.asyncio
    async def test_or_none_returns_none(self, service):
        result = await service.get_by_name_or_none("nonexistent.agent")
        assert result is None


class TestListCatalog:
    @pytest.mark.asyncio
    async def test_list_enabled(self, service):
        await _create_agent(service, agent_name="a.b.agent")
        await _create_agent(service, agent_name="c.d.agent", enabled=False)
        results = await service.list_catalog(enabled_only=True)
        names = [r.agent_name for r in results]
        assert "a.b.agent" in names
        assert "c.d.agent" not in names

    @pytest.mark.asyncio
    async def test_list_by_type(self, service):
        await _create_agent(service, agent_name="v.one.agent", agent_type="vertical")
        await _create_agent(service, agent_name="h.two.agent", agent_type="horizontal")
        verticals = await service.list_by_type("vertical")
        assert all(a.agent_type == "vertical" for a in verticals)


class TestSearchByKeyword:
    @pytest.mark.asyncio
    async def test_keyword_match(self, service):
        await _create_agent(
            service,
            agent_name="software.quality.agent",
            keywords=["code", "quality", "review"],
        )
        results = await service.search_by_keyword("quality review")
        assert len(results) >= 1
        assert results[0].agent_name == "software.quality.agent"

    @pytest.mark.asyncio
    async def test_no_match(self, service):
        await _create_agent(service, keywords=["code"])
        results = await service.search_by_keyword("unrelated")
        assert len(results) == 0


class TestUpdateEntry:
    @pytest.mark.asyncio
    async def test_update_fields(self, service):
        await _create_agent(service)
        updated = await service.update_entry(
            "vertical.software.quality.agent",
            description="Updated description",
        )
        assert updated.description == "Updated description"


class TestIsEmpty:
    @pytest.mark.asyncio
    async def test_empty_catalog(self, service):
        assert await service.is_catalog_empty() is True

    @pytest.mark.asyncio
    async def test_non_empty_catalog(self, service):
        await _create_agent(service)
        assert await service.is_catalog_empty() is False
