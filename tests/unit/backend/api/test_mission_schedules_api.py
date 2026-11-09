"""Tests for mission workflow-schedule API endpoints (Plan 83 §7).

Mirrors the test_executions_api.py convention: a minimal FastAPI app with
just the router under test, db/user dependencies overridden, and the
service layer mocked — this exercises routing, the ApiResponse envelope,
and mission-access gating. Real-Postgres behaviour of the service itself
is already covered by tests/unit/backend/services/test_workflow_schedule.py
(P12).

The Plan 88 step 88.0.11 tests at the end use a real db_session with rollback,
the real service and the real exception handlers, so scoping and the operator
rule are exercised end to end.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from modules.backend.api.v1.endpoints.missions_workflows import router
from modules.backend.core import security
from modules.backend.core.exception_handlers import register_exception_handlers
from modules.backend.core.exceptions import AuthorizationError
from modules.backend.models.mission import Mission, MissionMember, MissionMemberRole, MissionStatus
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.models.user import User
from modules.backend.models.workflow_definition import WorkflowDefinition
from modules.backend.models.workflow_schedule import WorkflowSchedule
from modules.backend.services.workflow_schedule import WorkflowScheduleService


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


@pytest.fixture
def _allow_mission_access():
    """Mocked-service tests: the access checks pass. Overridden per-test for 403."""
    with (
        patch(
            "modules.backend.api.v1.endpoints.missions_workflows.require_mission_access",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "modules.backend.api.v1.endpoints.missions_workflows.require_mission_operator",
            new=AsyncMock(return_value=None),
        ),
    ):
        yield


@pytest.mark.usefixtures("_allow_mission_access")
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


@pytest.mark.usefixtures("_allow_mission_access")
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


@pytest.mark.usefixtures("_allow_mission_access")
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
        instance.update_schedule.assert_awaited_once_with("mission-1", "sched-1", enabled=False)


@pytest.mark.usefixtures("_allow_mission_access")
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


# ---- Plan 88 step 88.0.11: scoping and operator rule (real DB) ----


def _user(label: str) -> User:
    return User(
        id=str(uuid4()),
        email=f"p88-sched-{label}-{uuid4().hex[:8]}@test.dev",
        display_name=label,
        hashed_password=security.hash_password("schedule-password-123"),
        system_role="user",
        is_active=True,
    )


async def _mission_with_schedule(db_session, owner: User) -> tuple[Mission, WorkflowSchedule]:
    mission = Mission(
        id=str(uuid4()),
        name=f"p88-sched-{uuid4().hex[:8]}",
        description="Plan 88 schedule test",
        owner_id=owner.id,
        status=MissionStatus.ACTIVE,
    )
    db_session.add(mission)
    await db_session.flush()
    db_session.add(MissionPlan(mission_id=mission.id, gate_mode=GateMode.MANUAL))
    wf = WorkflowDefinition(
        mission_id=mission.id,
        name="p88-sched-workflow",
        description="Test workflow",
        objective={"statement": "test", "category": "code"},
        steps=[{"id": "s1", "capability": "code.quality"}],
        trigger_config={"type": "schedule"},
        budget_config={"max_cost_usd": 10.0},
    )
    db_session.add(wf)
    await db_session.flush()
    schedule = await WorkflowScheduleService(db_session).create_schedule(
        workflow_definition_id=wf.id,
        mission_id=mission.id,
        cron_expression="0 5 * * *",
        created_by="user:test",
    )
    return mission, schedule


async def _add_member(db_session, mission: Mission, user: User, role: MissionMemberRole) -> None:
    db_session.add(MissionMember(mission_id=mission.id, user_id=user.id, role=role))
    await db_session.flush()


def _real_client(db_session, user: User) -> AsyncClient:
    from modules.backend.core.database import get_db_session
    from modules.backend.core.dependencies import get_current_user

    real_app = FastAPI()
    register_exception_handlers(real_app)
    real_app.include_router(router, prefix="/api/v1/missions")

    async def override_db():
        yield db_session

    async def override_user():
        return user

    real_app.dependency_overrides[get_db_session] = override_db
    real_app.dependency_overrides[get_current_user] = override_user
    return AsyncClient(transport=ASGITransport(app=real_app), base_url="http://test")


@pytest.mark.asyncio
async def test_patch_other_missions_schedule_returns_404(db_session):
    owner_a, owner_b = _user("owner-a"), _user("owner-b")
    db_session.add_all([owner_a, owner_b])
    await db_session.flush()
    mission_a, _ = await _mission_with_schedule(db_session, owner_a)
    _, schedule_b = await _mission_with_schedule(db_session, owner_b)

    async with _real_client(db_session, owner_a) as ac:
        response = await ac.patch(
            f"/api/v1/missions/{mission_a.id}/schedules/{schedule_b.id}",
            json={"enabled": False},
        )

    assert response.status_code == 404
    await db_session.refresh(schedule_b)
    assert schedule_b.enabled is True


@pytest.mark.asyncio
async def test_delete_other_missions_schedule_returns_404_and_row_survives(db_session):
    owner_a, owner_b = _user("owner-a"), _user("owner-b")
    db_session.add_all([owner_a, owner_b])
    await db_session.flush()
    mission_a, _ = await _mission_with_schedule(db_session, owner_a)
    mission_b, schedule_b = await _mission_with_schedule(db_session, owner_b)

    async with _real_client(db_session, owner_a) as ac:
        response = await ac.delete(f"/api/v1/missions/{mission_a.id}/schedules/{schedule_b.id}")

    assert response.status_code == 404
    survivor = await WorkflowScheduleService(db_session).get_schedule(mission_b.id, schedule_b.id)
    assert survivor.id == schedule_b.id


@pytest.mark.asyncio
async def test_viewer_cannot_create_patch_or_delete(db_session):
    owner, viewer = _user("owner"), _user("viewer")
    db_session.add_all([owner, viewer])
    await db_session.flush()
    mission, schedule = await _mission_with_schedule(db_session, owner)
    await _add_member(db_session, mission, viewer, MissionMemberRole.VIEWER)
    base = f"/api/v1/missions/{mission.id}/schedules"

    async with _real_client(db_session, viewer) as ac:
        created = await ac.post(
            base,
            json={
                "workflow_definition_id": schedule.workflow_definition_id,
                "cron_expression": "0 9 * * *",
            },
        )
        patched = await ac.patch(f"{base}/{schedule.id}", json={"enabled": False})
        deleted = await ac.delete(f"{base}/{schedule.id}")

    assert created.status_code == 403
    assert patched.status_code == 403
    assert deleted.status_code == 403
    await db_session.refresh(schedule)
    assert schedule.enabled is True


@pytest.mark.asyncio
async def test_maintainer_can_patch(db_session):
    owner, maintainer = _user("owner"), _user("maintainer")
    db_session.add_all([owner, maintainer])
    await db_session.flush()
    mission, schedule = await _mission_with_schedule(db_session, owner)
    await _add_member(db_session, mission, maintainer, MissionMemberRole.MAINTAINER)

    async with _real_client(db_session, maintainer) as ac:
        response = await ac.patch(
            f"/api/v1/missions/{mission.id}/schedules/{schedule.id}",
            json={"enabled": False},
        )

    assert response.status_code == 200
    assert response.json()["data"]["enabled"] is False
