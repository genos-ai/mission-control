"""Mission lifecycle routes and execution cancel delegation (Plan 88 step 88.4.5).

The signed-in user (test_user) is a member of a mission owned by test_user_2.
Pause and resume need an operator (owner or maintainer); archive and unarchive
need the owner or an admin. Both Temporal gateways are mocked.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.models.mission import Mission, MissionMember, MissionMemberRole
from modules.backend.models.mission_run import MissionRunStatus, MissionRunStatusReason
from modules.backend.services.execution_persistence import ExecutionPersistenceService
from modules.backend.services.mission_run import MissionRunService
from modules.backend.temporal.schedule_gateway import TemporalScheduleGateway
from modules.backend.temporal.workflow_gateway import TemporalWorkflowGateway, WorkflowState
from tests.conftest import TEST_USER_ID, TEST_USER_ID_2
from tests.integration.backend.api.helpers import create_mission

pytestmark = pytest.mark.usefixtures("signed_in")


@pytest.fixture(autouse=True)
def temporal(monkeypatch) -> AsyncMock:
    schedules = AsyncMock()
    monkeypatch.setattr(TemporalScheduleGateway, "create", AsyncMock(return_value=schedules))
    workflows = AsyncMock()
    workflows.signal.return_value = WorkflowState.RUNNING
    monkeypatch.setattr(TemporalWorkflowGateway, "connect", AsyncMock(return_value=workflows))
    return workflows


async def _shared(db: AsyncSession, role: MissionMemberRole) -> Mission:
    mission = await create_mission(db, f"lifecycle-{role.value}", TEST_USER_ID_2)
    db.add(MissionMember(mission_id=mission.id, user_id=TEST_USER_ID, role=role))
    await db.flush()
    await db.refresh(mission, ["members"])
    return mission


async def test_viewer_cannot_pause(client, db_session, test_user, test_user_2):
    mission = await _shared(db_session, MissionMemberRole.VIEWER)

    resp = await client.post(f"/api/v1/missions/{mission.id}/pause")

    assert resp.status_code == 403, resp.text


async def test_maintainer_can_pause(client, db_session, test_user, test_user_2):
    mission = await _shared(db_session, MissionMemberRole.MAINTAINER)

    resp = await client.post(f"/api/v1/missions/{mission.id}/pause")

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "paused"
    assert data["paused_reason"] == "user"

    resp = await client.post(f"/api/v1/missions/{mission.id}/resume")

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "active"


async def test_maintainer_cannot_archive(client, db_session, test_user, test_user_2):
    mission = await _shared(db_session, MissionMemberRole.MAINTAINER)

    resp = await client.post(f"/api/v1/missions/{mission.id}/archive")

    assert resp.status_code == 403, resp.text


async def test_owner_archive_then_unarchive(client, db_session, test_user):
    mission = await create_mission(db_session, "lifecycle-owned", TEST_USER_ID)

    resp = await client.post(f"/api/v1/missions/{mission.id}/archive")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "archived"

    resp = await client.post(f"/api/v1/missions/{mission.id}/unarchive")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert (data["status"], data["paused_reason"]) == ("paused", "user")


async def test_execution_cancel_delegates_to_run(
    client, db_session, test_user, test_user_2, monkeypatch
):
    mission = await _shared(db_session, MissionMemberRole.MAINTAINER)
    record = SimpleNamespace(
        id="exec-1", mission_id=mission.id, mission_run_id="run-1", status="running"
    )
    monkeypatch.setattr(
        ExecutionPersistenceService, "get_execution", AsyncMock(return_value=record)
    )
    cancel_run = AsyncMock(
        return_value=SimpleNamespace(id="run-1", status=MissionRunStatus.RUNNING)
    )
    monkeypatch.setattr(MissionRunService, "cancel_run", cancel_run)

    resp = await client.post("/api/v1/executions/exec-1/cancel")

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["mission_run_id"] == "run-1"
    assert resp.json()["data"]["status"] == "running"
    cancel_run.assert_awaited_once_with(
        mission.id, "run-1", TEST_USER_ID, MissionRunStatusReason.CANCELLED_BY_USER
    )
