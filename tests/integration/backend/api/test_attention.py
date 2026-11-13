"""GET /attention: what needs a person across the missions the caller can see.

A gate request and a human-input request are an item each. Proposed and failed tasks are one
item per mission, with a count. Only the caller's missions are covered, every list is fetched
for all of them at once, and the backend writes the titles and the links.
"""

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.dependencies import get_current_user
from modules.backend.models.mission import (
    Mission,
    MissionMember,
    MissionMemberRole,
    MissionStatus,
    MissionTier,
)
from modules.backend.models.mission_plan import GateMode
from modules.backend.models.task import TaskStatus
from tests.conftest import TEST_USER_ID, TEST_USER_ID_2
from tests.integration.backend.api.helpers import (
    create_gate_request,
    create_human_input,
    create_mission,
    create_tasks,
    set_plan,
)

pytestmark = pytest.mark.usefixtures("signed_in")

URL = "/api/v1/attention"


@pytest.fixture
async def world(db_session: AsyncSession, test_user, test_user_2):
    """The caller (test_user) and what is waiting on each mission."""
    db = db_session

    # A: owned by the caller. Interactive plan: 3 tasks to approve, 2 failed, a gate and a question.
    a = await create_mission(db, "mission-a", TEST_USER_ID)
    plan_a = await set_plan(db, a, GateMode.INTERACTIVE)
    await create_tasks(db, plan_a, TaskStatus.PROPOSED, 3)
    await create_tasks(db, plan_a, TaskStatus.FAILED, 2)
    await create_gate_request(db, a, plan_a, gate_type="post_run")
    await create_human_input(db, a, "Approve publishing the brief?")

    # B: owned by the caller. The plan auto-approves, so its proposed tasks need nobody.
    # One failure does.
    b = await create_mission(db, "mission-b", TEST_USER_ID)
    plan_b = await set_plan(db, b, GateMode.AUTONOMOUS)
    await create_tasks(db, plan_b, TaskStatus.PROPOSED, 4)
    await create_tasks(db, plan_b, TaskStatus.FAILED, 1)

    # D: someone else's. The caller must never see it.
    d = await create_mission(db, "mission-d", TEST_USER_ID_2)
    plan_d = await set_plan(db, d, GateMode.INTERACTIVE)
    await create_tasks(db, plan_d, TaskStatus.FAILED, 7)
    await create_gate_request(db, d, plan_d)

    # E: someone else's, but the caller is a member.
    e = await create_mission(db, "mission-e", TEST_USER_ID_2)
    db.add(MissionMember(mission_id=e.id, user_id=TEST_USER_ID, role=MissionMemberRole.VIEWER))
    await db.flush()
    plan_e = await set_plan(db, e, GateMode.MANUAL)
    await create_tasks(db, plan_e, TaskStatus.PROPOSED, 1)

    # F: an archived mission of the caller's, G: one of the caller's on the platform tier.
    f = await create_mission(db, "mission-f", TEST_USER_ID)
    f.status = MissionStatus.ARCHIVED
    await create_tasks(db, await set_plan(db, f, GateMode.INTERACTIVE), TaskStatus.FAILED, 3)
    g = await create_mission(db, "mission-g", TEST_USER_ID)
    g.tier = MissionTier.platform
    await create_tasks(db, await set_plan(db, g, GateMode.INTERACTIVE), TaskStatus.FAILED, 3)
    await db.flush()
    return {m.name: m for m in (a, b, d, e, f, g)}


async def _get(client) -> dict:
    resp = await client.get(URL)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _items(data: dict, mission: Mission, kind: str) -> list[dict]:
    return [i for i in data["items"] if i["mission_id"] == str(mission.id) and i["kind"] == kind]


class TestEachKind:
    @pytest.mark.asyncio
    async def test_a_gate_request_is_an_item(self, client, world):
        (item,) = _items(await _get(client), world["mission-a"], "gate")
        assert item["detail"] == "post run"
        assert item["count"] == 1
        assert item["href"] == f"/missions/{world['mission-a'].id}/overview"

    @pytest.mark.asyncio
    async def test_a_human_input_request_is_an_item(self, client, world):
        (item,) = _items(await _get(client), world["mission-a"], "human_input")
        assert item["detail"] == "Approve publishing the brief?"
        assert item["href"] == f"/missions/{world['mission-a'].id}/workflows"

    @pytest.mark.asyncio
    async def test_proposed_tasks_are_one_item_per_mission_with_a_count(self, client, world):
        (item,) = _items(await _get(client), world["mission-a"], "task_approval")
        assert item["count"] == 3
        assert item["title"] == "3 tasks awaiting approval"
        assert item["href"] == f"/missions/{world['mission-a'].id}/plan"

    @pytest.mark.asyncio
    async def test_failed_tasks_are_one_item_per_mission_with_a_count(self, client, world):
        (item,) = _items(await _get(client), world["mission-a"], "retry")
        assert item["count"] == 2
        assert item["title"] == "2 tasks failed"

    @pytest.mark.asyncio
    async def test_a_single_task_is_singular(self, client, world):
        (item,) = _items(await _get(client), world["mission-b"], "retry")
        assert item["title"] == "1 task failed"


class TestWhatIsLeftOut:
    @pytest.mark.asyncio
    async def test_proposed_tasks_in_an_auto_approving_plan_need_nobody(self, client, world):
        assert _items(await _get(client), world["mission-b"], "task_approval") == []

    @pytest.mark.asyncio
    async def test_an_archived_mission_is_left_out(self, client, world):
        data = await _get(client)
        assert not [i for i in data["items"] if i["mission_id"] == str(world["mission-f"].id)]

    @pytest.mark.asyncio
    async def test_a_platform_mission_is_left_out_for_a_regular_user(self, client, world):
        data = await _get(client)
        assert not [i for i in data["items"] if i["mission_id"] == str(world["mission-g"].id)]


class TestWhoSeesWhat:
    @pytest.mark.asyncio
    async def test_another_users_mission_is_never_included(self, client, world):
        data = await _get(client)
        assert not [i for i in data["items"] if i["mission_id"] == str(world["mission-d"].id)]
        assert str(world["mission-d"].id) not in data["pending_counts"]

    @pytest.mark.asyncio
    async def test_a_mission_the_caller_is_a_member_of_is_included(self, client, world):
        (item,) = _items(await _get(client), world["mission-e"], "task_approval")
        assert item["count"] == 1

    @pytest.mark.asyncio
    async def test_an_admin_sees_every_open_mission(self, client, world, test_user_2):
        test_user_2.system_role = "admin"
        client.app.dependency_overrides[get_current_user] = lambda: test_user_2

        data = await _get(client)

        seen = {i["mission_id"] for i in data["items"]}
        for name in ("mission-a", "mission-b", "mission-d", "mission-e", "mission-g"):
            assert str(world[name].id) in seen, name
        assert str(world["mission-f"].id) not in seen  # still not archived ones

    @pytest.mark.asyncio
    async def test_sign_in_is_required(self, client, world):
        client.app.dependency_overrides.pop(get_current_user, None)
        assert (await client.get(URL)).status_code == 401


class TestShape:
    @pytest.mark.asyncio
    async def test_blocking_items_come_first(self, client, world):
        kinds = [i["kind"] for i in (await _get(client))["items"]]
        order = {"gate": 0, "human_input": 1, "task_approval": 2, "retry": 3}
        assert kinds == sorted(kinds, key=order.__getitem__)

    @pytest.mark.asyncio
    async def test_pending_counts_are_items_per_mission(self, client, world):
        counts = (await _get(client))["pending_counts"]
        assert counts[str(world["mission-a"].id)] == 4  # gate + input + approval + failures
        assert counts[str(world["mission-b"].id)] == 1  # failures only
        assert counts[str(world["mission-e"].id)] == 1
        assert str(world["mission-f"].id) not in counts

    @pytest.mark.asyncio
    async def test_each_item_names_its_mission(self, client, world):
        (item,) = _items(await _get(client), world["mission-b"], "retry")
        assert item["mission_name"] == "mission-b"


class TestOneQueryPerKind:
    @pytest.mark.asyncio
    async def test_the_lists_are_fetched_for_all_missions_at_once(self, client, world, db_session):
        statements: list[str] = []
        engine = db_session.get_bind()
        target = engine.sync_engine if hasattr(engine, "sync_engine") else engine

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement.lower())

        event.listen(target, "before_cursor_execute", record)
        try:
            await _get(client)
        finally:
            event.remove(target, "before_cursor_execute", record)

        assert sum("from gate_requests" in s for s in statements) == 1
        assert sum("from human_input_requests" in s for s in statements) == 1
        # one grouped query for proposed tasks, one for failed: not one per mission
        assert sum("from tasks" in s and "group by" in s for s in statements) == 2


class TestThePerMissionListsStillScoped:
    """The gate and human-input lists the missions pages use now take lists of missions."""

    @pytest.mark.asyncio
    async def test_pending_gates_of_one_mission_only(self, client, world):
        resp = await client.get(f"/api/v1/missions/{world['mission-a'].id}/gates/pending")
        assert resp.status_code == 200
        ids = {g["mission_id"] for g in resp.json()["data"]["gates"]}
        assert ids == {str(world["mission-a"].id)}

    @pytest.mark.asyncio
    async def test_pending_human_input_of_one_mission_only(self, client, world):
        resp = await client.get(f"/api/v1/missions/{world['mission-a'].id}/human-input/pending")
        assert resp.status_code == 200
        prompts = [r["prompt_message"] for r in resp.json()["data"]["requests"]]
        assert prompts == ["Approve publishing the brief?"]
