"""Tests for MissionTeamService."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ConflictError
from modules.backend.models.mission import Mission, MissionMember, MissionMemberRole
from modules.backend.services.agent_catalog import AgentCatalogService
from modules.backend.services.mission_team import MissionTeamService
from tests.conftest import TEST_USER_ID


async def _seed_mission(db_session: AsyncSession) -> Mission:
    """Create a minimal mission for team tests."""
    from modules.backend.core.utils import utc_now

    mission = Mission(
        name="test-mission",
        description="Test mission",
        owner_id=TEST_USER_ID,
        status="active",
        default_roster="default",
    )
    db_session.add(mission)
    await db_session.flush()

    member = MissionMember(
        mission_id=mission.id,
        user_id=TEST_USER_ID,
        role=MissionMemberRole.OWNER,
    )
    db_session.add(member)
    await db_session.flush()

    return mission


async def _seed_catalog_agent(
    db_session: AsyncSession,
    agent_name: str = "vertical.software.quality.agent",
) -> str:
    """Create a catalog agent and return its ID."""
    svc = AgentCatalogService(db_session)
    entry = await svc.create_entry(
        agent_name=agent_name,
        agent_type="vertical",
        description="Test agent",
        model_config_json={"name": "anthropic:claude-haiku-4-5-20251001", "temperature": 0.0, "max_tokens": 4096},
    )
    return entry.id


@pytest.fixture(autouse=True)
async def _ensure_test_user(test_user):
    pass


@pytest.fixture
def service(db_session: AsyncSession) -> MissionTeamService:
    return MissionTeamService(db_session)


class TestAddAgent:
    @pytest.mark.asyncio
    async def test_add_agent(self, service, db_session):
        mission = await _seed_mission(db_session)
        agent_id = await _seed_catalog_agent(db_session)

        member = await service.add_agent(
            mission.id, agent_id, user_prompt="Focus on security",
        )
        assert member.mission_id == mission.id
        assert member.agent_catalog_id == agent_id
        assert member.user_prompt == "Focus on security"
        assert member.enabled is True

    @pytest.mark.asyncio
    async def test_duplicate_raises_conflict(self, service, db_session):
        mission = await _seed_mission(db_session)
        agent_id = await _seed_catalog_agent(db_session)

        await service.add_agent(mission.id, agent_id)
        with pytest.raises(ConflictError, match="already on this mission"):
            await service.add_agent(mission.id, agent_id)


class TestListTeam:
    @pytest.mark.asyncio
    async def test_list_enabled(self, service, db_session):
        mission = await _seed_mission(db_session)
        a1 = await _seed_catalog_agent(db_session, "a.one.agent")
        a2 = await _seed_catalog_agent(db_session, "b.two.agent")

        await service.add_agent(mission.id, a1)
        m2 = await service.add_agent(mission.id, a2)
        await service.toggle_enabled(m2.id, False)

        team = await service.list_team(mission.id, enabled_only=True)
        assert len(team) == 1
        assert team[0].agent_catalog_id == a1


class TestUpdateUserPrompt:
    @pytest.mark.asyncio
    async def test_prompt_update_increments_version(self, service, db_session):
        mission = await _seed_mission(db_session)
        agent_id = await _seed_catalog_agent(db_session)
        member = await service.add_agent(mission.id, agent_id)

        updated = await service.update_user_prompt(
            member.id, "New prompt", changed_by=TEST_USER_ID,
        )
        assert updated.user_prompt == "New prompt"
        assert updated.user_prompt_version == 2


class TestToggleEnabled:
    @pytest.mark.asyncio
    async def test_disable_and_enable(self, service, db_session):
        mission = await _seed_mission(db_session)
        agent_id = await _seed_catalog_agent(db_session)
        member = await service.add_agent(mission.id, agent_id)

        disabled = await service.toggle_enabled(member.id, False)
        assert disabled.enabled is False

        enabled = await service.toggle_enabled(member.id, True)
        assert enabled.enabled is True
