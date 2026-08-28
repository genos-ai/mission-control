"""Tests for mission workflow-schedule API endpoints (Plan 83 §7).

Mirrors the test_executions_api.py convention: a minimal FastAPI app with
just the router under test, db/user dependencies overridden, and the
service layer mocked — this exercises routing, the ApiResponse envelope,
and mission-access gating. Real-Postgres behaviour of the service itself
is already covered by tests/unit/backend/services/test_workflow_schedule.py
(P12).
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from modules.backend.api.v1.endpoints.missions_workflows import router
from modules.backend.core.exceptions import AuthorizationError


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(router, prefix="/missions")

    @app.exception_handler(AuthorizationError)
    async def forbidden_handler(request, exc):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    return app


@pytest.fixture
def mock_db_session():
    return AsyncMock()


class _StubUser:
    """Minimal authenticated user — role is irrelevant since
    require_mission_access is mocked directly per-test."""

    id = "user-1"
    system_role = "member"

    def has_role(self, role: str) -> bool:
        return False


@pytest.fixture
async def client(app, mock_db_session):
    from modules.backend.core.database import get_db_session
    from modules.backend.core.dependencies import get_current_user

    async def override_db():
        yield mock_db_session

    async def override_user():
        return _StubUser()

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_current_user] = override_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


def _mock_schedule(**overrides) -> MagicMock:
    now = datetime(2026, 8, 28, tzinfo=timezone.utc)
    schedule = MagicMock()
    defaults = {
        "id": "sched-1",
        "workflow_definition_id": "wf-1",
        "mission_id": "mission-1",
        "cron_expression": "0 9 * * *",
        "timezone": "UTC",
        "enabled": True,
        "description": "",
        "budget_per_run_usd": None,
        "max_iterations": None,
        "iteration_count": 0,
        "cooldown_seconds": 0,
        "last_fired_at": None,
        "next_fire_at": now,
        "created_by": "user:api",
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    for key, value in defaults.items():
        setattr(schedule, key, value)
    return schedule


@pytest.fixture(autouse=True)
def _allow_mission_access():
    """Default: require_mission_access passes. Overridden per-test for 403."""
    with patch(
        "modules.backend.api.v1.endpoints.missions_workflows.require_mission_access",
        new=AsyncMock(return_value=None),
    ):
        yield


class TestListMissionSchedules:
    @pytest.mark.asyncio
    async def test_list_returns_200_with_envelope(self, client):
        with patch(
            "modules.backend.services.workflow_schedule.WorkflowScheduleService",
        ) as MockService:
            instance = MockService.return_value
            instance.list_by_mission = AsyncMock(return_value=[_mock_schedule()])

            response = await client.get("/missions/mission-1/schedules")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["total"] == 1
        assert data["data"]["schedules"][0]["id"] == "sched-1"

    @pytest.mark.asyncio
    async def test_list_denied_for_non_member(self, client):
        with patch(
            "modules.backend.api.v1.endpoints.missions_workflows.require_mission_access",
            new=AsyncMock(side_effect=AuthorizationError("not a member")),
        ):
            response = await client.get("/missions/mission-1/schedules")

        assert response.status_code == 403


class TestCreateMissionSchedule:
    @pytest.mark.asyncio
    async def test_create_returns_created_schedule(self, client):
        with patch(
            "modules.backend.services.workflow_schedule.WorkflowScheduleService",
        ) as MockService:
            instance = MockService.return_value
            instance.create_schedule = AsyncMock(return_value=_mock_schedule())

            response = await client.post(
                "/missions/mission-1/schedules",
                json={
                    "workflow_definition_id": "wf-1",
                    "cron_expression": "0 9 * * *",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["id"] == "sched-1"
        assert data["data"]["cron_expression"] == "0 9 * * *"


class TestUpdateMissionSchedule:
    @pytest.mark.asyncio
    async def test_patch_disable_reflects_enabled_false(self, client):
        with patch(
            "modules.backend.services.workflow_schedule.WorkflowScheduleService",
        ) as MockService:
            instance = MockService.return_value
            instance.update_schedule = AsyncMock(return_value=_mock_schedule(enabled=False))

            response = await client.patch(
                "/missions/mission-1/schedules/sched-1",
                json={"enabled": False},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["enabled"] is False
        instance.update_schedule.assert_awaited_once_with("sched-1", enabled=False)


class TestDeleteMissionSchedule:
    @pytest.mark.asyncio
    async def test_delete_returns_deleted_id(self, client):
        with patch(
            "modules.backend.services.workflow_schedule.WorkflowScheduleService",
        ) as MockService:
            instance = MockService.return_value
            instance.delete_schedule = AsyncMock(return_value=None)

            response = await client.delete("/missions/mission-1/schedules/sched-1")

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["deleted"] == "sched-1"
