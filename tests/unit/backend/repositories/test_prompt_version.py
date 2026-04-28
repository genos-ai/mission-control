"""Tests for PromptVersionRepository."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.repositories.prompt_version import PromptVersionRepository
from tests.conftest import TEST_USER_ID


@pytest.fixture
def repo(db_session: AsyncSession) -> PromptVersionRepository:
    return PromptVersionRepository(db_session)


class TestCreateVersion:
    @pytest.mark.asyncio
    async def test_auto_increments_version(self, repo):
        v1 = await repo.create_version(
            entity_type="agent_catalog",
            entity_id="agent-001",
            prompt_type="system",
            content="Version 1 prompt",
            changed_by=TEST_USER_ID,
        )
        assert v1.version == 1

        v2 = await repo.create_version(
            entity_type="agent_catalog",
            entity_id="agent-001",
            prompt_type="system",
            content="Version 2 prompt",
            changed_by=TEST_USER_ID,
            change_reason="Added context",
        )
        assert v2.version == 2
        assert v2.change_reason == "Added context"

    @pytest.mark.asyncio
    async def test_independent_version_streams(self, repo):
        """Different entities have independent version sequences."""
        await repo.create_version(
            "agent_catalog", "agent-001", "system", "v1", "admin",
        )
        await repo.create_version(
            "agent_catalog", "agent-001", "system", "v2", "admin",
        )

        v1_other = await repo.create_version(
            "mission_team_member", "member-001", "user", "v1", "admin",
        )
        assert v1_other.version == 1


class TestGetLatest:
    @pytest.mark.asyncio
    async def test_returns_latest(self, repo):
        await repo.create_version(
            "agent_catalog", "agent-x", "system", "old", "admin",
        )
        await repo.create_version(
            "agent_catalog", "agent-x", "system", "new", "admin",
        )
        latest = await repo.get_latest("agent_catalog", "agent-x")
        assert latest is not None
        assert latest.content == "new"
        assert latest.version == 2

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown(self, repo):
        result = await repo.get_latest("agent_catalog", "nonexistent")
        assert result is None


class TestListVersions:
    @pytest.mark.asyncio
    async def test_newest_first(self, repo):
        for i in range(3):
            await repo.create_version(
                "agent_catalog", "agent-y", "system", f"v{i+1}", "admin",
            )
        versions = await repo.list_versions("agent_catalog", "agent-y")
        assert len(versions) == 3
        assert versions[0].version == 3
        assert versions[2].version == 1
