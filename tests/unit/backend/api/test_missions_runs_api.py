"""Tests for the mission run API (Plan 88 step 88.1.12).

httpx.AsyncClient against the missions router with the real exception handlers.
MissionRunService is mocked; the operator rule runs for real over a mocked
MissionService.get_mission and membership lookup.
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
from modules.backend.core.exceptions import ConflictError, NotFoundError
from modules.backend.models.mission import MissionMemberRole
from modules.backend.models.mission_plan import GateMode
from modules.backend.models.mission_run import (
    MissionRunStatus,
    MissionRunStatusReason,
    MissionRunTrigger,
)
from modules.backend.schemas.mission_run import MissionRunDetailResponse, MissionRunResponse

ENDPOINT = "modules.backend.api.v1.endpoints.missions_runs"
RUN_SVC = f"{ENDPOINT}.MissionRunService"
GET_MISSION = "modules.backend.services.mission.MissionService.get_mission"
GET_MEMBERSHIP = "modules.backend.repositories.mission.MissionMemberRepository.get_membership"

OWNER_ID = str(uuid4())
MISSION_ID = str(uuid4())
NOW = datetime(2027, 1, 4, 6, 0, tzinfo=UTC)


def _run(sequence: int = 1, **overrides) -> SimpleNamespace:
    values = {
        "id": str(uuid4()),
        "mission_id": MISSION_ID,
        "plan_id": str(uuid4()),
        "schedule_id": None,
        "sequence": sequence,
        "trigger": MissionRunTrigger.MANUAL,
        "triggered_by_user_id": OWNER_ID,
        "scheduled_for": None,
        "previous_run_id": None,
        "objective": "Summarise the week",
        "workflow_definition_id": None,
        "workflow_parameters": {},
        "status": MissionRunStatus.PENDING,
        "status_reason": None,
        "status_detail": None,
        "gate_mode": GateMode.AUTONOMOUS,
        "temporal_workflow_id": f"mission-run-{uuid4()}",
        "session_id": None,
        "context_version_start": None,
        "context_version_end": None,
        "iteration_count": 0,
        "budget_cap_usd": None,
        "cost_usd": 0.0,
        "task_count": 0,
        "completed_task_count": 0,
        "failed_task_count": 0,
        "config_snapshot": {},
        "cancel_requested_at": None,
        "cancel_requested_by_user_id": None,
        "cancel_reason": None,
        "started_at": None,
        "ended_at": None,
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
    for name in ("start_run", "list_runs", "get_run_detail", "cancel_run"):
        setattr(instance, name, AsyncMock())
    with (
        patch(RUN_SVC, return_value=instance),
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
    return f"/api/v1/missions/{MISSION_ID}/runs{suffix}"


@pytest.mark.asyncio
async def test_start_run_passes_objective(client, svc):
    svc.start_run.return_value = _run()
    response = await client.post(_url(), json={"objective": "Summarise the week"})
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "pending"
    svc.start_run.assert_awaited_once_with(
        MISSION_ID,
        trigger=MissionRunTrigger.MANUAL,
        objective="Summarise the week",
        user_id=OWNER_ID,
        session_id=None,
    )


@pytest.mark.asyncio
async def test_start_run_conflict_409(client, svc):
    svc.start_run.side_effect = ConflictError("run #3 is active")
    response = await client.post(_url(), json={"objective": "Summarise the week"})
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_get_by_sequence(client, svc):
    run = _run(sequence=7)
    svc.get_run_detail.return_value = MissionRunDetailResponse(
        run=MissionRunResponse.model_validate(run),
        execution_record_id=None,
        digest=None,
        tasks=[],
    )
    response = await client.get(_url("/7"))
    assert response.status_code == 200
    svc.get_run_detail.assert_awaited_once_with(MISSION_ID, "7")
    data = response.json()["data"]
    assert data["run"]["sequence"] == 7
    assert data["execution_record_id"] is None
    assert data["digest"] is None
    assert data["tasks"] == []
    assert "gates" not in data


@pytest.mark.asyncio
async def test_list_paginates_next_before_sequence(client, svc):
    svc.list_runs.return_value = [_run(sequence=s) for s in (9, 8)]
    response = await client.get(_url("?limit=2"))
    assert response.status_code == 200
    assert response.json()["data"]["next_before_sequence"] == 8
    svc.list_runs.assert_awaited_once_with(MISSION_ID, statuses=None, limit=2, before_sequence=None)

    svc.list_runs.return_value = [_run(sequence=7)]
    response = await client.get(_url("?limit=2&before_sequence=8"))
    assert response.json()["data"]["next_before_sequence"] is None
    svc.list_runs.assert_awaited_with(MISSION_ID, statuses=None, limit=2, before_sequence=8)

    await client.get(_url())
    assert svc.list_runs.await_args.kwargs["limit"] == 50


@pytest.mark.asyncio
async def test_list_status_filter_takes_values(client, svc):
    svc.list_runs.return_value = []
    response = await client.get(_url("?status=running&status=paused"))
    assert response.status_code == 200
    assert svc.list_runs.await_args.kwargs["statuses"] == [
        MissionRunStatus.RUNNING,
        MissionRunStatus.PAUSED,
    ]

    response = await client.get(_url("?status=RUNNING"))
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_cancel_requires_operator(client, svc, current_user):
    current_user["user"] = _user(str(uuid4()))
    with patch(
        GET_MEMBERSHIP, new=AsyncMock(return_value=MagicMock(role=MissionMemberRole.VIEWER))
    ):
        response = await client.post(_url(f"/{uuid4()}/cancel"))
    assert response.status_code == 403
    svc.cancel_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_passes_cancelled_by_user(client, svc):
    run = _run(cancel_reason=MissionRunStatusReason.CANCELLED_BY_USER)
    svc.cancel_run.return_value = run
    response = await client.post(_url(f"/{run.id}/cancel"))
    assert response.status_code == 200
    svc.cancel_run.assert_awaited_once_with(
        MISSION_ID, run.id, OWNER_ID, reason=MissionRunStatusReason.CANCELLED_BY_USER
    )
    assert response.json()["data"]["cancel_reason"] == "cancelled_by_user"


@pytest.mark.asyncio
async def test_cancel_other_missions_run_404(client, svc):
    svc.cancel_run.side_effect = NotFoundError("Run not found in mission")
    response = await client.post(_url(f"/{uuid4()}/cancel"))
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_run_objective_route_removed(client, svc):
    response = await client.post(
        f"/api/v1/missions/{MISSION_ID}/plan/run-objective", json={"objective": "anything"}
    )
    assert response.status_code == 404
