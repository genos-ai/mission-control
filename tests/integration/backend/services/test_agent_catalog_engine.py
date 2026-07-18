"""
Integration tests for AgentCatalogService — engine/effort fields (Plan 55).

Tests that the catalog service correctly persists and updates the engine
and effort columns introduced by Plan 55. Also tests the prompt loader.
Uses a real in-memory SQLite database, no mocks.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.services.agent_catalog import AgentCatalogService


class TestCreateEntryEngine:
    """Tests for engine/effort on create_entry."""

    async def test_create_with_default_engine(self, db_session: AsyncSession):
        service = AgentCatalogService(db_session)
        entry = await service.create_entry(
            agent_name="test.default_engine.agent",
            agent_type="vertical",
            description="Agent with default engine",
        )

        assert entry.engine == "pydantic_ai"
        assert entry.effort is None

    async def test_create_with_claude_code_engine(self, db_session: AsyncSession):
        service = AgentCatalogService(db_session)
        entry = await service.create_entry(
            agent_name="test.claude_code.agent",
            agent_type="vertical",
            description="Agent with Claude Code engine",
            engine="claude_code",
            effort="high",
        )

        assert entry.engine == "claude_code"
        assert entry.effort == "high"

    async def test_create_with_codex_engine(self, db_session: AsyncSession):
        service = AgentCatalogService(db_session)
        entry = await service.create_entry(
            agent_name="test.codex.agent",
            agent_type="vertical",
            description="Agent with Codex engine",
            engine="codex",
        )

        assert entry.engine == "codex"
        assert entry.effort is None

    async def test_create_with_effort_only(self, db_session: AsyncSession):
        service = AgentCatalogService(db_session)
        entry = await service.create_entry(
            agent_name="test.effort_only.agent",
            agent_type="vertical",
            description="Agent with effort but default engine",
            effort="medium",
        )

        assert entry.engine == "pydantic_ai"
        assert entry.effort == "medium"


class TestUpdateEntryEngine:
    """Tests for updating engine/effort via update_entry."""

    async def test_update_engine_pydantic_to_claude_code(
        self,
        db_session: AsyncSession,
    ):
        service = AgentCatalogService(db_session)
        await service.create_entry(
            agent_name="test.update_engine.agent",
            agent_type="vertical",
            description="Agent to update engine",
        )

        updated = await service.update_entry(
            "test.update_engine.agent",
            engine="claude_code",
        )

        assert updated.engine == "claude_code"

    async def test_update_effort_independently(
        self,
        db_session: AsyncSession,
    ):
        service = AgentCatalogService(db_session)
        await service.create_entry(
            agent_name="test.update_effort.agent",
            agent_type="vertical",
            description="Agent to update effort",
            engine="claude_code",
        )

        updated = await service.update_entry(
            "test.update_effort.agent",
            effort="low",
        )

        assert updated.effort == "low"
        # Engine should remain unchanged
        assert updated.engine == "claude_code"

    async def test_update_engine_and_effort_together(
        self,
        db_session: AsyncSession,
    ):
        service = AgentCatalogService(db_session)
        await service.create_entry(
            agent_name="test.update_both.agent",
            agent_type="vertical",
            description="Agent to update both fields",
        )

        updated = await service.update_entry(
            "test.update_both.agent",
            engine="copilot",
            effort="high",
        )

        assert updated.engine == "copilot"
        assert updated.effort == "high"

    async def test_read_back_after_update(
        self,
        db_session: AsyncSession,
    ):
        """Verify the update persists through a re-read."""
        service = AgentCatalogService(db_session)
        await service.create_entry(
            agent_name="test.readback.agent",
            agent_type="vertical",
            description="Agent for read-back test",
            engine="pydantic_ai",
        )

        await service.update_entry(
            "test.readback.agent",
            engine="claude_code",
            effort="high",
        )

        entry = await service.get_by_name("test.readback.agent")
        assert entry.engine == "claude_code"
        assert entry.effort == "high"


class TestPromptLoader:
    """Tests for load_agent_system_prompt helper."""

    def test_load_mission_director_prompt(self):
        from modules.backend.agents.mission_control.helpers.prompt_builder import (
            load_agent_system_prompt,
        )

        content = load_agent_system_prompt("mission.director.agent")
        assert len(content) > 0
        assert isinstance(content, str)

    def test_load_nonexistent_agent_returns_empty(self):
        from modules.backend.agents.mission_control.helpers.prompt_builder import (
            load_agent_system_prompt,
        )

        content = load_agent_system_prompt("nonexistent.agent")
        assert content == ""
