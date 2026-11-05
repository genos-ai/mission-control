"""Who may read a mission's costs, through the real endpoint and database.

An unknown mission is a 404 for everyone, admins included: an admin would otherwise be shown an
all-zero cost breakdown for a mission that does not exist.
"""

import uuid

import pytest
from httpx import AsyncClient

from modules.backend.core.dependencies import get_current_user
from modules.backend.models.mission import Mission, MissionMember, MissionMemberRole
from tests.conftest import TEST_USER_ID, TEST_USER_ID_2
from tests.integration.backend.api.helpers import create_mission


@pytest.fixture
async def mission_of_user_2(db_session, test_user, test_user_2):
    mission = await create_mission(db_session, "costs-access", TEST_USER_ID_2)
    return mission.id


async def _costs(client: AsyncClient, mission_id: str):
    return await client.get(f"/api/v1/missions/{mission_id}/costs")


async def test_owner_reads_the_costs(client: AsyncClient, test_user_2, mission_of_user_2):
    client.app.dependency_overrides[get_current_user] = lambda: test_user_2
    try:
        response = await _costs(client, mission_of_user_2)
    finally:
        client.app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200, response.text
    assert response.json()["data"]["mission_id"] == mission_of_user_2


async def test_member_reads_the_costs(
    client: AsyncClient, db_session, signed_in, mission_of_user_2
):
    db_session.add(
        MissionMember(
            mission_id=mission_of_user_2, user_id=TEST_USER_ID, role=MissionMemberRole.VIEWER
        )
    )
    await db_session.flush()
    # The members as a fresh request would load them.
    mission = await db_session.get(Mission, mission_of_user_2)
    await db_session.refresh(mission, ["members"])

    assert (await _costs(client, mission_of_user_2)).status_code == 200


async def test_stranger_is_refused(client: AsyncClient, signed_in, mission_of_user_2):
    assert (await _costs(client, mission_of_user_2)).status_code == 403


async def test_admin_reads_the_costs_of_a_mission_they_are_not_in(
    client: AsyncClient, test_user, mission_of_user_2
):
    test_user.system_role = "admin"
    client.app.dependency_overrides[get_current_user] = lambda: test_user
    try:
        response = await _costs(client, mission_of_user_2)
    finally:
        client.app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200, response.text


@pytest.mark.parametrize("role", ["user", "admin"])
async def test_unknown_mission_is_a_404_for_everyone(client: AsyncClient, test_user, role):
    test_user.system_role = role
    client.app.dependency_overrides[get_current_user] = lambda: test_user
    try:
        response = await _costs(client, str(uuid.uuid4()))
    finally:
        client.app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 404, response.text
