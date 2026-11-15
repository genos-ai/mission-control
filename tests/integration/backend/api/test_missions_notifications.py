"""Mission notification recipient endpoints (Plan 88 step 88.4.4, contract 3.5.3).

The signed-in user is test_user. GET needs mission access; POST and DELETE need
the mission owner. A recipient must be the owner or a member, and a recipient
is scoped by mission (3.0.2).
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config import get_app_config
from modules.backend.models.mission import Mission, MissionMember, MissionMemberRole
from modules.backend.models.notification import MissionNotificationRecipient
from modules.backend.models.user_channel_identity import ChannelKind
from tests.conftest import TEST_USER_ID, TEST_USER_ID_2
from tests.integration.backend.api.helpers import create_mission

pytestmark = pytest.mark.usefixtures("signed_in")

USER_2_EMAIL = "test2@mission-control.dev"


def _path(mission: Mission) -> str:
    return f"/api/v1/missions/{mission.id}/notification-recipients"


async def _member(db: AsyncSession, mission: Mission, user_id: str, role: MissionMemberRole):
    db.add(MissionMember(mission_id=mission.id, user_id=user_id, role=role))
    await db.flush()
    await db.refresh(mission, ["members"])


async def _recipient(db: AsyncSession, mission: Mission, user_id: str) -> str:
    recipient = MissionNotificationRecipient(
        mission_id=mission.id,
        user_id=user_id,
        channel=ChannelKind.TELEGRAM,
        kinds=["run_failed"],
    )
    db.add(recipient)
    await db.flush()
    return recipient.id


async def test_add_recipient_non_member_rejected(client, db_session, test_user, test_user_2):
    mission = await create_mission(db_session, "notify-non-member", TEST_USER_ID)

    resp = await client.post(
        _path(mission), json={"user_email": USER_2_EMAIL, "channel": "telegram"}
    )

    assert resp.status_code == 400, resp.text
    assert "owner or a mission member" in resp.json()["error"]["message"]


async def test_add_recipient_by_email(client, db_session, test_user, test_user_2):
    mission = await create_mission(db_session, "notify-by-email", TEST_USER_ID)
    await _member(db_session, mission, TEST_USER_ID_2, MissionMemberRole.VIEWER)

    resp = await client.post(
        _path(mission), json={"user_email": USER_2_EMAIL, "channel": "telegram"}
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["user_id"] == TEST_USER_ID_2
    assert data["user_email"] == USER_2_EMAIL
    assert data["channel"] == "telegram"
    assert data["kinds"] == list(get_app_config().notifications.default_kinds)

    listed = (await client.get(_path(mission))).json()["data"]["recipients"]
    assert [r["user_email"] for r in listed] == [USER_2_EMAIL]

    again = await client.post(
        _path(mission), json={"user_email": USER_2_EMAIL, "channel": "telegram"}
    )
    assert again.status_code == 409, again.text

    unknown = await client.post(
        _path(mission),
        json={"user_email": "nobody@mission-control.dev", "channel": "telegram"},
    )
    assert unknown.status_code == 404, unknown.text


async def test_remove_recipient_owner_only(client, db_session, test_user, test_user_2):
    mission = await create_mission(db_session, "notify-owner-only", TEST_USER_ID_2)
    await _member(db_session, mission, TEST_USER_ID, MissionMemberRole.MAINTAINER)
    rid = await _recipient(db_session, mission, TEST_USER_ID_2)

    listed = await client.get(_path(mission))
    assert listed.status_code == 200, listed.text
    assert [r["id"] for r in listed.json()["data"]["recipients"]] == [rid]

    delete = await client.delete(f"{_path(mission)}/{rid}")
    assert delete.status_code == 403, delete.text
    add = await client.post(
        _path(mission),
        json={"user_email": "test@mission-control.dev", "channel": "telegram"},
    )
    assert add.status_code == 403, add.text


async def test_remove_other_missions_recipient_404(client, db_session, test_user):
    mine = await create_mission(db_session, "notify-scope-a", TEST_USER_ID)
    other = await create_mission(db_session, "notify-scope-b", TEST_USER_ID)
    other_rid = await _recipient(db_session, other, TEST_USER_ID)

    resp = await client.delete(f"{_path(mine)}/{other_rid}")
    assert resp.status_code == 404, resp.text

    ok = await client.delete(f"{_path(other)}/{other_rid}")
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"] == {"id": other_rid}
    assert (await client.get(_path(other))).json()["data"]["recipients"] == []


async def test_kinds_accept_lowercase_values(client, db_session, test_user):
    mission = await create_mission(db_session, "notify-kinds", TEST_USER_ID)
    body = {"user_email": "test@mission-control.dev", "channel": "telegram"}

    upper = await client.post(_path(mission), json=body | {"kinds": ["RUN_FAILED"]})
    assert upper.status_code == 422, upper.text

    resp = await client.post(_path(mission), json=body | {"kinds": ["run_failed", "gate_waiting"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["kinds"] == ["run_failed", "gate_waiting"]
