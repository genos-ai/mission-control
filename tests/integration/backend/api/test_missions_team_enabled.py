"""PATCH /missions/{id}/team/{member_id}/enabled turns a team member on or off.

A disabled member stays on the team, but the roster that dispatch builds (and the default
team listing) leave it out until it is enabled again.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.services.mission_team import MissionTeamService
from tests.conftest import TEST_USER_ID, TEST_USER_ID_2
from tests.integration.backend.api.helpers import add_team_member, create_mission

pytestmark = pytest.mark.usefixtures("signed_in")


@pytest.fixture
async def world(db_session: AsyncSession, test_user, test_user_2):
    """The caller owns mission A; someone else owns mission B. Each has one member."""
    mission_a = await create_mission(db_session, "mission-a", TEST_USER_ID)
    mission_b = await create_mission(db_session, "mission-b", TEST_USER_ID_2)
    member_a = await add_team_member(db_session, mission_a, "vertical.enabled.agent_a")
    member_b = await add_team_member(db_session, mission_b, "vertical.enabled.agent_b")
    return mission_a, mission_b, member_a, member_b


def _url(mission_id, member_id) -> str:
    return f"/api/v1/missions/{mission_id}/team/{member_id}/enabled"


async def _roster_ids(db: AsyncSession, mission_id) -> list[str]:
    """Who dispatch would use: enabled members only."""
    return [
        str(m.id) for m in await MissionTeamService(db).list_team(mission_id, enabled_only=True)
    ]


class TestToggling:
    @pytest.mark.asyncio
    async def test_disabling_removes_the_member_from_the_roster(self, client, world, db_session):
        mission_a, _, member_a, _ = world
        assert await _roster_ids(db_session, mission_a.id) == [str(member_a.id)]

        resp = await client.patch(_url(mission_a.id, member_a.id), json={"enabled": False})

        assert resp.status_code == 200
        assert resp.json()["data"]["enabled"] is False
        assert await _roster_ids(db_session, mission_a.id) == []

    @pytest.mark.asyncio
    async def test_a_disabled_member_is_still_on_the_team(self, client, world, db_session):
        mission_a, _, member_a, _ = world
        await client.patch(_url(mission_a.id, member_a.id), json={"enabled": False})

        everyone = await MissionTeamService(db_session).list_team(mission_a.id, enabled_only=False)

        assert [str(m.id) for m in everyone] == [str(member_a.id)]

    @pytest.mark.asyncio
    async def test_enabling_restores_the_member(self, client, world, db_session):
        mission_a, _, member_a, _ = world
        await client.patch(_url(mission_a.id, member_a.id), json={"enabled": False})

        resp = await client.patch(_url(mission_a.id, member_a.id), json={"enabled": True})

        assert resp.status_code == 200
        assert resp.json()["data"]["enabled"] is True
        assert await _roster_ids(db_session, mission_a.id) == [str(member_a.id)]

    @pytest.mark.asyncio
    async def test_the_team_endpoint_can_still_list_a_disabled_member(self, client, world):
        mission_a, _, member_a, _ = world
        await client.patch(_url(mission_a.id, member_a.id), json={"enabled": False})

        resp = await client.get(f"/api/v1/missions/{mission_a.id}/team?enabled_only=false")

        assert resp.status_code == 200
        entries = resp.json()["data"]["team_members"]
        assert any(str(e["id"]) == str(member_a.id) and e["enabled"] is False for e in entries)

    @pytest.mark.asyncio
    async def test_the_default_team_listing_hides_a_disabled_member(self, client, world):
        mission_a, _, member_a, _ = world
        await client.patch(_url(mission_a.id, member_a.id), json={"enabled": False})

        resp = await client.get(f"/api/v1/missions/{mission_a.id}/team")

        assert resp.json()["data"]["team_members"] == []


class TestScope:
    @pytest.mark.asyncio
    async def test_a_member_of_another_mission_is_a_404_and_unchanged(
        self, client, world, db_session
    ):
        mission_a, mission_b, _, member_b = world

        resp = await client.patch(_url(mission_a.id, member_b.id), json={"enabled": False})

        assert resp.status_code == 404
        assert await _roster_ids(db_session, mission_b.id) == [str(member_b.id)]

    @pytest.mark.asyncio
    async def test_a_mission_the_caller_cannot_access_is_refused(self, client, world, db_session):
        _, mission_b, _, member_b = world

        resp = await client.patch(_url(mission_b.id, member_b.id), json={"enabled": False})

        assert resp.status_code == 403
        assert await _roster_ids(db_session, mission_b.id) == [str(member_b.id)]


class TestRequest:
    @pytest.mark.asyncio
    async def test_enabled_must_be_a_boolean(self, client, world):
        mission_a, _, member_a, _ = world
        resp = await client.patch(_url(mission_a.id, member_a.id), json={"enabled": "maybe"})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_unknown_fields_are_rejected(self, client, world):
        mission_a, _, member_a, _ = world
        resp = await client.patch(
            _url(mission_a.id, member_a.id), json={"enabled": False, "role": "admin"}
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_the_body_is_required(self, client, world):
        mission_a, _, member_a, _ = world
        resp = await client.patch(_url(mission_a.id, member_a.id), json={})
        assert resp.status_code == 422
