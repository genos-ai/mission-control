"""Tests for PromptVersionRepository."""

from uuid import UUID, uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.repositories.prompt_version import PromptVersionRepository
from tests.conftest import TEST_USER_ID

_TEST_NS = UUID("00000000-0000-0000-0000-000000000000")
_AGENT_001 = str(uuid5(_TEST_NS, "entity:agent-001"))
_AGENT_X = str(uuid5(_TEST_NS, "entity:agent-x"))
_AGENT_Y = str(uuid5(_TEST_NS, "entity:agent-y"))
_MEMBER_001 = str(uuid5(_TEST_NS, "entity:member-001"))
_NIL_UUID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def repo(db_session: AsyncSession) -> PromptVersionRepository:
    return PromptVersionRepository(db_session)


class TestCreateVersion:
    @pytest.mark.asyncio
    async def test_auto_increments_version(self, repo):
        v1 = await repo.create_version(
            entity_type="agent_catalog",
            entity_id=_AGENT_001,
            prompt_type="system",
            content="Version 1 prompt",
            changed_by=TEST_USER_ID,
        )
        assert v1.version == 1

        v2 = await repo.create_version(
            entity_type="agent_catalog",
            entity_id=_AGENT_001,
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
            "agent_catalog",
            _AGENT_001,
            "system",
            "v1",
            "admin",
        )
        await repo.create_version(
            "agent_catalog",
            _AGENT_001,
            "system",
            "v2",
            "admin",
        )

        v1_other = await repo.create_version(
            "mission_team_member",
            _MEMBER_001,
            "user",
            "v1",
            "admin",
        )
        assert v1_other.version == 1


class TestGetLatest:
    @pytest.mark.asyncio
    async def test_returns_latest(self, repo):
        await repo.create_version(
            "agent_catalog",
            _AGENT_X,
            "system",
            "old",
            "admin",
        )
        await repo.create_version(
            "agent_catalog",
            _AGENT_X,
            "system",
            "new",
            "admin",
        )
        latest = await repo.get_latest("agent_catalog", _AGENT_X)
        assert latest is not None
        assert latest.content == "new"
        assert latest.version == 2

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown(self, repo):
        result = await repo.get_latest("agent_catalog", _NIL_UUID)
        assert result is None


class TestListVersions:
    @pytest.mark.asyncio
    async def test_newest_first(self, repo):
        for i in range(3):
            await repo.create_version(
                "agent_catalog",
                _AGENT_Y,
                "system",
                f"v{i+1}",
                "admin",
            )
        versions = await repo.list_versions("agent_catalog", _AGENT_Y)
        assert len(versions) == 3
        assert versions[0].version == 3
        assert versions[2].version == 1
