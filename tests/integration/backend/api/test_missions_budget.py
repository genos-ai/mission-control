"""GET and PUT /missions/{id}/budget (Plan 88 step 88.4.1).

The signed-in user (test_user) is a member of a mission owned by test_user_2:
any member reads the budget; only an owner or maintainer replaces the caps.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.models.mission import Mission, MissionMember, MissionMemberRole
from tests.conftest import TEST_USER_ID, TEST_USER_ID_2
from tests.integration.backend.api.helpers import create_mission, record_spend

pytestmark = pytest.mark.usefixtures("signed_in")

CAPS = {"per_run_usd": 2.0, "per_month_usd": 20.0, "lifetime_usd": 200.0}


async def _shared(db: AsyncSession, role: MissionMemberRole) -> Mission:
    """A mission owned by user 2 with the signed-in user as a ``role`` member.

    The members collection is reloaded so the access check sees the new
    member, as a fresh request session would.
    """
    mission = await create_mission(db, f"budget-{role.value}", TEST_USER_ID_2)
    db.add(MissionMember(mission_id=mission.id, user_id=TEST_USER_ID, role=role))
    await db.flush()
    await db.refresh(mission, ["members"])
    return mission


async def test_get_budget_member_ok(client, db_session, test_user, test_user_2):
    mission = await _shared(db_session, MissionMemberRole.VIEWER)
    await record_spend(db_session, mission, 1.5, 0.5)

    resp = await client.get(f"/api/v1/missions/{mission.id}/budget")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert (data["per_run_usd"], data["per_month_usd"], data["lifetime_usd"]) == (5.0, 100.0, None)
    assert data["month_spent_usd"] == pytest.approx(2.0)
    assert data["lifetime_spent_usd"] == pytest.approx(2.0)
    assert data["active_run_spent_usd"] == 0.0
    assert data["breach"] is None


async def test_put_budget_viewer_forbidden(client, db_session, test_user, test_user_2):
    mission = await _shared(db_session, MissionMemberRole.VIEWER)

    resp = await client.put(f"/api/v1/missions/{mission.id}/budget", json=CAPS)

    assert resp.status_code == 403, resp.text


async def test_put_budget_maintainer_ok_envelope(client, db_session, test_user, test_user_2):
    mission = await _shared(db_session, MissionMemberRole.MAINTAINER)

    resp = await client.put(f"/api/v1/missions/{mission.id}/budget", json=CAPS)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert (data["per_run_usd"], data["per_month_usd"], data["lifetime_usd"]) == (2.0, 20.0, 200.0)


async def test_put_budget_invalid_caps_rejected(client, db_session, test_user, test_user_2):
    mission = await _shared(db_session, MissionMemberRole.MAINTAINER)

    resp = await client.put(
        f"/api/v1/missions/{mission.id}/budget",
        json={"per_run_usd": 10.0, "per_month_usd": 5.0, "lifetime_usd": None},
    )

    assert resp.status_code in (400, 422), resp.text


async def test_breach_serialised_lowercase(client, db_session, test_user, test_user_2):
    mission = await _shared(db_session, MissionMemberRole.VIEWER)
    await record_spend(db_session, mission, 150.0)

    resp = await client.get(f"/api/v1/missions/{mission.id}/budget")

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["breach"] == "budget_monthly_cap"
