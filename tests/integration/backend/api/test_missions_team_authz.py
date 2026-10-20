"""A team member can only be reached through the mission it belongs to.

The team endpoints check access to the mission in the URL, then act on a member by id.
Without a check that the member is on that mission, a user with access to mission A could
read, change or remove a member of mission B by putting B's member id under A's path.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.dependencies import get_current_user
from modules.backend.models.mission import Mission, MissionMember, MissionMemberRole
from modules.backend.services.agent_catalog import AgentCatalogService
from modules.backend.services.mission_team import MissionTeamService
from tests.conftest import TEST_USER_ID, TEST_USER_ID_2


async def _mission(db: AsyncSession, name: str, owner_id: str) -> Mission:
    mission = Mission(
        name=name, description=name, owner_id=owner_id, status="active", default_roster="default"
    )
    db.add(mission)
    await db.flush()
    db.add(MissionMember(mission_id=mission.id, user_id=owner_id, role=MissionMemberRole.OWNER))
    await db.flush()
    await db.refresh(
        mission, ["members"]
    )  # the access check reads it; the real query loads it eagerly
    return mission


async def _member(db: AsyncSession, mission: Mission, agent_name: str):
    entry = await AgentCatalogService(db).create_entry(
        agent_name=agent_name,
        agent_type="vertical",
        description="Test agent",
        model_config_json={
            "name": "anthropic:claude-haiku-4-5-20251001",
            "temperature": 0.0,
            "max_tokens": 4096,
        },
    )
    return await MissionTeamService(db).add_agent(
        mission.id, str(entry.id), user_prompt="original prompt"
    )


@pytest.fixture
async def world(db_session: AsyncSession, test_user, test_user_2):
    """The caller (test_user) owns mission A; someone else owns mission B."""
    mission_a = await _mission(db_session, "mission-a", TEST_USER_ID)
    mission_b = await _mission(db_session, "mission-b", TEST_USER_ID_2)
    member_a = await _member(db_session, mission_a, "vertical.authz.agent_a")
    member_b = await _member(db_session, mission_b, "vertical.authz.agent_b")
    return mission_a, mission_b, member_a, member_b


@pytest.fixture(autouse=True)
def _acting_as_test_user(client: AsyncClient, test_user):
    client.app.dependency_overrides[get_current_user] = lambda: test_user
    yield
    client.app.dependency_overrides.pop(get_current_user, None)


def _url(mission_id: str, member_id: str, suffix: str = "") -> str:
    return f"/api/v1/missions/{mission_id}/team/{member_id}{suffix}"


class TestMemberOfAnotherMission:
    """Mission A is the caller's; the member is on mission B."""

    @pytest.mark.asyncio
    async def test_prompt_history_is_not_readable(self, client, world):
        mission_a, _, _, member_b = world
        resp = await client.get(_url(mission_a.id, member_b.id, "/prompt-history"))
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_prompt_cannot_be_changed(self, client, world, db_session):
        mission_a, _, _, member_b = world
        resp = await client.put(
            _url(mission_a.id, member_b.id, "/prompt"),
            json={"content": "injected", "changed_by": "attacker"},
        )
        assert resp.status_code == 404
        await db_session.refresh(member_b)
        assert member_b.user_prompt == "original prompt"

    @pytest.mark.asyncio
    async def test_constraints_cannot_be_changed(self, client, world, db_session):
        mission_a, _, _, member_b = world
        resp = await client.patch(
            _url(mission_a.id, member_b.id, "/constraints"), json={"research_depth": "injected"}
        )
        assert resp.status_code == 404
        await db_session.refresh(member_b)
        assert "injected" not in str(member_b.custom_constraints)

    @pytest.mark.asyncio
    async def test_member_cannot_be_removed(self, client, world, db_session):
        mission_a, mission_b, _, member_b = world
        resp = await client.delete(_url(mission_a.id, member_b.id))
        assert resp.status_code == 404
        team = await MissionTeamService(db_session).list_team(mission_b.id)
        assert [str(m.id) for m in team] == [str(member_b.id)]

    @pytest.mark.asyncio
    async def test_unknown_member_answers_the_same_as_another_missions_member(self, client, world):
        mission_a, *_ = world
        resp = await client.get(
            _url(mission_a.id, "00000000-0000-0000-0000-000000000000", "/prompt-history")
        )
        assert resp.status_code == 404


class TestOwnMember:
    """The same calls through the member's own mission still work."""

    @pytest.mark.asyncio
    async def test_prompt_history_is_readable(self, client, world):
        mission_a, _, member_a, _ = world
        resp = await client.get(_url(mission_a.id, member_a.id, "/prompt-history"))
        assert resp.status_code == 200
        assert resp.json()["data"]["member_id"] == str(member_a.id)

    @pytest.mark.asyncio
    async def test_prompt_can_be_changed(self, client, world):
        mission_a, _, member_a, _ = world
        resp = await client.put(
            _url(mission_a.id, member_a.id, "/prompt"),
            json={"content": "new prompt", "changed_by": "tester"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["user_prompt"] == "new prompt"

    @pytest.mark.asyncio
    async def test_constraints_can_be_changed(self, client, world):
        mission_a, _, member_a, _ = world
        resp = await client.patch(
            _url(mission_a.id, member_a.id, "/constraints"), json={"research_depth": "deep"}
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_member_can_be_removed(self, client, world):
        mission_a, _, member_a, _ = world
        resp = await client.delete(_url(mission_a.id, member_a.id))
        assert resp.status_code == 200


class TestMissionWithoutAccess:
    """Access to the mission itself is still required (unchanged)."""

    @pytest.mark.asyncio
    async def test_other_missions_member_through_its_own_mission_is_refused(self, client, world):
        _, mission_b, _, member_b = world
        resp = await client.get(_url(mission_b.id, member_b.id, "/prompt-history"))
        assert resp.status_code == 403
