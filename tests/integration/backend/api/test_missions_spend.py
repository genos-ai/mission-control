"""Every mission response carries `spent_usd`: the sum of the mission's recorded LLM calls.

It is the figure the Costs tab shows, taken in one aggregate query however many missions
are listed. A mission with no recorded calls reports 0.0, never null.
"""

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import TEST_USER_ID
from tests.integration.backend.api.helpers import create_mission, record_spend

pytestmark = pytest.mark.usefixtures("signed_in")


@pytest.fixture
async def missions(db_session: AsyncSession, test_user):
    spent = await create_mission(db_session, "spent", TEST_USER_ID)
    idle = await create_mission(db_session, "idle", TEST_USER_ID)
    other = await create_mission(db_session, "other", TEST_USER_ID)
    await record_spend(db_session, spent, 0.25, 0.5, 0.125)
    await record_spend(db_session, other, 4.0)
    return spent, idle, other


class TestSpendInTheResponses:
    @pytest.mark.asyncio
    async def test_get_returns_the_sum_of_the_missions_calls(self, client, missions):
        spent, _, _ = missions
        resp = await client.get(f"/api/v1/missions/{spent.id}")
        assert resp.status_code == 200
        assert resp.json()["data"]["spent_usd"] == pytest.approx(0.875)

    @pytest.mark.asyncio
    async def test_a_mission_with_no_calls_is_zero_not_null(self, client, missions):
        _, idle, _ = missions
        resp = await client.get(f"/api/v1/missions/{idle.id}")
        assert resp.json()["data"]["spent_usd"] == 0.0

    @pytest.mark.asyncio
    async def test_list_returns_each_missions_own_spend(self, client, missions):
        spent, idle, other = missions
        resp = await client.get("/api/v1/missions")
        by_id = {m["id"]: m["spent_usd"] for m in resp.json()["data"]["missions"]}
        assert by_id[str(spent.id)] == pytest.approx(0.875)
        assert by_id[str(idle.id)] == 0.0
        assert by_id[str(other.id)] == pytest.approx(4.0)

    @pytest.mark.asyncio
    async def test_update_returns_the_spend(self, client, missions):
        spent, _, _ = missions
        resp = await client.patch(f"/api/v1/missions/{spent.id}", json={"description": "renamed"})
        assert resp.status_code == 200
        assert resp.json()["data"]["spent_usd"] == pytest.approx(0.875)

    @pytest.mark.asyncio
    async def test_create_returns_zero_spend(self, client, test_user):
        resp = await client.post(
            "/api/v1/missions",
            json={"name": "brand-new", "description": "a new mission", "owner_id": TEST_USER_ID},
        )
        assert resp.status_code in (200, 201), resp.text
        assert resp.json()["data"]["spent_usd"] == 0.0

    @pytest.mark.asyncio
    async def test_spend_ignores_other_missions_calls(self, client, missions):
        _, idle, _ = missions
        resp = await client.get(f"/api/v1/missions/{idle.id}")
        assert resp.json()["data"]["spent_usd"] == 0.0


class TestOneAggregateQuery:
    @pytest.mark.asyncio
    async def test_listing_missions_runs_a_single_spend_query(self, client, missions, db_session):
        statements: list[str] = []
        engine = db_session.get_bind()

        def count(conn, cursor, statement, parameters, context, executemany):
            if "llm_calls" in statement:
                statements.append(statement)

        event.listen(
            engine.sync_engine if hasattr(engine, "sync_engine") else engine,
            "before_cursor_execute",
            count,
        )
        try:
            resp = await client.get("/api/v1/missions")
        finally:
            event.remove(
                engine.sync_engine if hasattr(engine, "sync_engine") else engine,
                "before_cursor_execute",
                count,
            )

        assert resp.status_code == 200
        assert len(resp.json()["data"]["missions"]) >= 3
        assert len(statements) == 1, statements
        assert "group by" in statements[0].lower()
