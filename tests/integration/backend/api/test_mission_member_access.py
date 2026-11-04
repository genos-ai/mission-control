"""A mission member who is not the owner can pass the mission access checks.

Each request gets a fresh session, so `mission.members` is never already loaded
when the check runs. The test expires the mission to match that.
"""

import pytest

from modules.backend.core.dependencies import require_mission_access
from modules.backend.core.exceptions import AuthorizationError
from modules.backend.models.mission import MissionMember, MissionMemberRole
from tests.conftest import TEST_USER_ID, TEST_USER_ID_2
from tests.integration.backend.api.helpers import create_mission

CHECKS = {
    "require_mission_access": lambda db, mission_id, user: require_mission_access(
        db, mission_id, user
    ),
}


@pytest.fixture
async def shared_mission(db_session, test_user, test_user_2):
    """A mission owned by user 2, with user 1 as a viewer member."""
    mission = await create_mission(db_session, "member-access", TEST_USER_ID_2)
    db_session.add(
        MissionMember(mission_id=mission.id, user_id=TEST_USER_ID, role=MissionMemberRole.VIEWER)
    )
    await db_session.flush()
    mission_id = mission.id
    db_session.expire(mission)
    return mission_id


@pytest.mark.parametrize("name", CHECKS)
async def test_member_who_is_not_the_owner_is_allowed(name, db_session, test_user, shared_mission):
    await CHECKS[name](db_session, shared_mission, test_user)


@pytest.mark.parametrize("name", CHECKS)
async def test_user_who_is_neither_owner_nor_member_is_denied(
    name, db_session, test_user, shared_mission
):
    from modules.backend.models.user import User

    stranger = User(id="00000000-0000-4000-8000-0000000000aa", system_role="user", is_active=True)
    with pytest.raises(AuthorizationError):
        await CHECKS[name](db_session, shared_mission, stranger)
