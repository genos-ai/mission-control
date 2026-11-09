"""Tests for the mission schedule API (Plan 88 step 88.1.12).

httpx.AsyncClient against the missions router with the real exception handlers.
MissionScheduleService and the schedule gateway are mocked; the operator rule runs
for real over a mocked MissionService.get_mission and membership lookup.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from modules.backend.core.database import get_db_session
from modules.backend.core.dependencies import get_current_user, get_event_bus
from modules.backend.core.exceptions import NotFoundError
from modules.backend.models.mission import MissionMemberRole
from modules.backend.models.mission_schedule import (
    MissionScheduleKind,
    MissionScheduleStatus,
    TemporalSyncState,
)

ENDPOINT = "modules.backend.api.v1.endpoints.missions_schedules"
SCHEDULE_SVC = f"{ENDPOINT}.MissionScheduleService"
GATEWAY_CREATE = f"{ENDPOINT}.TemporalScheduleGateway.create"
GET_MISSION = "modules.backend.services.mission.MissionService.get_mission"
GET_MEMBERSHIP = "modules.backend.repositories.mission.MissionMemberRepository.get_membership"

OWNER_ID = str(uuid4())
MISSION_ID = str(uuid4())
NOW = datetime(2027, 1, 4, 6, 0, tzinfo=UTC)

CREATE_BODY = {
    "name": "daily-brief",
    "kind": "objective",
    "objective_template": "Summarise {scheduled_for}",
    "cron_expression": "0 6 * * *",
    "time_zone_name": "Europe/London",
}


def _schedule(**overrides) -> SimpleNamespace:
    values = {
        "id": str(uuid4()),
        "mission_id": MISSION_ID,
        "name": "daily-brief",
        "kind": MissionScheduleKind.OBJECTIVE,
        "objective_template": "Summarise {scheduled_for}",
        "workflow_definition_id": None,
        "workflow_parameters": {},
        "cron_expression": "0 6 * * *",
        "time_zone_name": "Europe/London",
        "starts_at": None,
        "ends_at": None,
        "max_runs": None,
        "catch_up_window_seconds": 3600,
        "status": MissionScheduleStatus.ACTIVE,
        "completed_reason": None,
        "executed_run_count": 0,
        "last_claimed_scheduled_for": None,
        "temporal_schedule_id": f"mission-schedule-{uuid4()}",
        "temporal_sync_state": TemporalSyncState.SYNCED,
        "temporal_synced_at": NOW,
        "temporal_sync_error": None,
        "tick_config_hash": "abc",
        "created_by_user_id": OWNER_ID,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _user(user_id: str) -> MagicMock:
    return MagicMock(id=user_id, has_role=lambda role: False, is_active=True)


@pytest.fixture
def current_user():
    return {"user": _user(OWNER_ID)}


@pytest.fixture
def svc():
    instance = MagicMock()
    for name in (
        "create_schedule",
        "get_schedule",
        "list_schedules",
        "update_schedule",
        "pause_schedule",
        "resume_schedule",
        "archive_schedule",
        "next_fire_times",
    ):
        setattr(instance, name, AsyncMock())
    with (
        patch(SCHEDULE_SVC, return_value=instance),
        patch(GATEWAY_CREATE, new=AsyncMock(return_value=MagicMock())),
        patch(GET_MISSION, new=AsyncMock(return_value=SimpleNamespace(owner_id=OWNER_ID))),
    ):
        yield instance


@pytest.fixture
async def client(current_user):
    from modules.backend.api.v1.endpoints.missions import router
    from modules.backend.core.exception_handlers import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v1/missions")

    async def override_db():
        yield AsyncMock()

    async def override_user():
        return current_user["user"]

    async def override_bus():
        yield MagicMock()

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_event_bus] = override_bus
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _url(suffix: str = "") -> str:
    return f"/api/v1/missions/{MISSION_ID}/schedules{suffix}"


@pytest.mark.asyncio
async def test_create_requires_operator(client, svc, current_user):
    svc.create_schedule.return_value = _schedule()
    member = _user(str(uuid4()))
    current_user["user"] = member

    with patch(
        GET_MEMBERSHIP, new=AsyncMock(return_value=MagicMock(role=MissionMemberRole.VIEWER))
    ):
        response = await client.post(_url(), json=CREATE_BODY)
    assert response.status_code == 403
    svc.create_schedule.assert_not_awaited()

    with patch(
        GET_MEMBERSHIP, new=AsyncMock(return_value=MagicMock(role=MissionMemberRole.MAINTAINER))
    ):
        response = await client.post(_url(), json=CREATE_BODY)
    assert response.status_code == 201
    svc.create_schedule.assert_awaited_once()
    assert svc.create_schedule.await_args.args[2] == member.id


@pytest.mark.asyncio
async def test_create_sync_failed_still_201(client, svc):
    svc.create_schedule.return_value = _schedule(
        temporal_sync_state=TemporalSyncState.FAILED, temporal_sync_error="unavailable"
    )
    response = await client.post(_url(), json=CREATE_BODY)
    assert response.status_code == 201
    assert response.json()["data"]["temporal_sync_state"] == "failed"


@pytest.mark.asyncio
async def test_get_schedule_of_other_mission_404(client, svc):
    svc.get_schedule.side_effect = NotFoundError("Schedule not found in mission")
    response = await client.get(_url(f"/{uuid4()}"))
    assert response.status_code == 404
    svc.next_fire_times.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_schedule_includes_next_fire_times(client, svc):
    schedule = _schedule()
    svc.get_schedule.return_value = schedule
    svc.next_fire_times.return_value = [NOW]
    response = await client.get(_url(f"/{schedule.id}"))
    assert response.status_code == 200
    svc.get_schedule.assert_awaited_once_with(MISSION_ID, schedule.id)
    svc.next_fire_times.assert_awaited_once_with(schedule, 5)
    assert response.json()["data"]["next_fire_times"] == ["2027-01-04T06:00:00Z"]


@pytest.mark.asyncio
async def test_patch_rejects_kind(client, svc):
    response = await client.patch(_url(f"/{uuid4()}"), json={"kind": "workflow_definition"})
    assert response.status_code == 422
    svc.update_schedule.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_returns_archived(client, svc):
    schedule = _schedule(status=MissionScheduleStatus.ARCHIVED)
    svc.archive_schedule.return_value = schedule
    response = await client.delete(_url(f"/{schedule.id}"))
    assert response.status_code == 200
    svc.archive_schedule.assert_awaited_once_with(MISSION_ID, schedule.id, OWNER_ID)
    assert response.json()["data"]["status"] == "archived"


@pytest.mark.asyncio
async def test_list_excludes_archived_by_default(client, svc):
    svc.list_schedules.return_value = [_schedule()]
    response = await client.get(_url())
    assert response.status_code == 200
    svc.list_schedules.assert_awaited_once_with(MISSION_ID, include_archived=False)
    assert response.json()["data"]["schedules"][0]["next_fire_times"] == []

    await client.get(_url("?include_archived=true"))
    svc.list_schedules.assert_awaited_with(MISSION_ID, include_archived=True)


@pytest.mark.asyncio
async def test_pause_and_resume_call_service(client, svc):
    schedule = _schedule()
    svc.pause_schedule.return_value = schedule
    svc.resume_schedule.return_value = schedule
    assert (await client.post(_url(f"/{schedule.id}/pause"))).status_code == 200
    assert (await client.post(_url(f"/{schedule.id}/resume"))).status_code == 200
    svc.pause_schedule.assert_awaited_once_with(MISSION_ID, schedule.id, OWNER_ID)
    svc.resume_schedule.assert_awaited_once_with(MISSION_ID, schedule.id, OWNER_ID)


@pytest.mark.asyncio
async def test_responses_use_api_envelope(client, svc):
    schedule = _schedule()
    svc.list_schedules.return_value = [schedule]
    svc.get_schedule.return_value = schedule
    svc.next_fire_times.return_value = []
    svc.update_schedule.return_value = schedule
    for response in (
        await client.get(_url()),
        await client.get(_url(f"/{schedule.id}")),
        await client.patch(_url(f"/{schedule.id}"), json={"max_runs": 3}),
    ):
        body = response.json()
        assert body["success"] is True
        assert "data" in body
        assert "request_id" in body["metadata"]


@pytest.mark.asyncio
async def test_enum_fields_lowercase(client, svc):
    schedule = _schedule()
    svc.get_schedule.return_value = schedule
    svc.next_fire_times.return_value = []
    data = (await client.get(_url(f"/{schedule.id}"))).json()["data"]
    assert data["status"] == "active"
    assert data["kind"] == "objective"
    assert data["temporal_sync_state"] == "synced"
