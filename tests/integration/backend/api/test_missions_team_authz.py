"""A team member can only be reached through the mission it belongs to.

The team endpoints check access to the mission in the URL, then act on a member by id.
Without a check that the member is on that mission, a user with access to mission A could
read, change or remove a member of mission B by putting B's member id under A's path.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.services.mission_team import MissionTeamService
from tests.conftest import TEST_USER_ID, TEST_USER_ID_2
from tests.integration.backend.api.helpers import add_team_member, create_mission

pytestmark = pytest.mark.usefixtures("signed_in")


@pytest.fixture
async def world(db_session: AsyncSession, test_user, test_user_2):
    """The caller (test_user) owns mission A; someone else owns mission B."""
    mission_a = await create_mission(db_session, "mission-a", TEST_USER_ID)
    mission_b = await create_mission(db_session, "mission-b", TEST_USER_ID_2)
    member_a = await add_team_member(db_session, mission_a, "vertical.authz.agent_a")
    member_b = await add_team_member(db_session, mission_b, "vertical.authz.agent_b")
    return mission_a, mission_b, member_a, member_b


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
