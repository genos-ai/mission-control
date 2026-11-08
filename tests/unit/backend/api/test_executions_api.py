"""Tests for execution API endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from modules.backend.api.v1.endpoints.executions import router
from modules.backend.core.exceptions import NotFoundError


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(router, prefix="/executions")

    @app.exception_handler(NotFoundError)
    async def not_found_handler(request, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    return app


@pytest.fixture
def mock_db_session():
    return AsyncMock()


class _StubAdminUser:
    """Minimal authenticated user — admin so execution access checks pass."""

    id = "admin-user"
    system_role = "admin"

    def has_role(self, role: str) -> bool:
        return True


@pytest.fixture
async def client(app, mock_db_session):
    from modules.backend.core.database import get_db_session
    from modules.backend.core.dependencies import get_current_user

    async def override_db():
        yield mock_db_session

    async def override_user():
        return _StubAdminUser()

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_current_user] = override_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


class TestListExecutions:
    @pytest.mark.asyncio
    async def test_list_executions_returns_200(self, client):
        with patch(
            "modules.backend.api.v1.endpoints.executions.ExecutionPersistenceService",
        ) as MockService:
            instance = MockService.return_value
            instance.list_executions = AsyncMock(return_value=([], 0))

            response = await client.get("/executions")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

    @pytest.mark.asyncio
    async def test_list_executions_with_filters(self, client):
        with patch(
            "modules.backend.api.v1.endpoints.executions.ExecutionPersistenceService",
        ) as MockService:
            instance = MockService.return_value
            instance.list_executions = AsyncMock(return_value=([], 0))

            response = await client.get(
                "/executions?status=completed&roster_name=research",
            )
            assert response.status_code == 200


class TestGetExecution:
    @pytest.mark.asyncio
    async def test_get_execution_not_found(self, client):
        with patch(
            "modules.backend.api.v1.endpoints.executions.ExecutionPersistenceService",
        ) as MockService:
            instance = MockService.return_value
            instance.get_execution = AsyncMock(return_value=None)

            response = await client.get("/executions/nonexistent")
            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_execution_found(self, client):
        mock_execution = MagicMock()
        mock_execution.id = "m-123"
        mock_execution.session_id = "s-123"
        mock_execution.roster_name = "default"
        mock_execution.status = "completed"
        mock_execution.total_cost_usd = 0.05
        mock_execution.started_at = "2026-03-06T00:00:00"
        mock_execution.completed_at = "2026-03-06T00:01:00"
        mock_execution.parent_execution_record_id = None
        mock_execution.created_at = "2026-03-06T00:00:00"
        mock_execution.updated_at = "2026-03-06T00:01:00"
        mock_execution.objective_statement = None
        mock_execution.objective_category = None
        mock_execution.task_plan_json = {}
        mock_execution.execution_outcome_json = {}
        mock_execution.planning_thinking_trace = None
        mock_execution.task_executions = []
        mock_execution.decisions = []
        mock_execution.task_type = None
        mock_execution.task_params = None
        mock_execution.temporal_workflow_id = None
        mock_execution.mission_id = None

        with patch(
            "modules.backend.api.v1.endpoints.executions.ExecutionPersistenceService",
        ) as MockService:
            instance = MockService.return_value
            instance.get_execution = AsyncMock(return_value=mock_execution)

            response = await client.get("/executions/m-123")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True


class TestGetExecutionCost:
    @pytest.mark.asyncio
    async def test_get_cost_breakdown(self, client):
        from modules.backend.schemas.execution_record import ExecutionCostBreakdown

        breakdown = ExecutionCostBreakdown(
            execution_id="m-123",
            total_cost_usd=0.10,
            task_costs=[],
            model_costs={},
            attempt_count=0,
            total_input_tokens=200,
            total_output_tokens=100,
        )

        with patch(
            "modules.backend.api.v1.endpoints.executions.ExecutionPersistenceService",
        ) as MockService:
            instance = MockService.return_value
            instance.get_execution = AsyncMock(
                return_value=MagicMock(mission_id=None),
            )
            instance.get_cost_breakdown = AsyncMock(return_value=breakdown)

            response = await client.get("/executions/m-123/cost")
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["total_cost_usd"] == 0.10


# ---- Plan 88 step 88.0.9: operator rule and removed legacy routes ----


async def _real_db_client(app: FastAPI, db_session, user):
    from modules.backend.core.database import get_db_session
    from modules.backend.core.dependencies import get_current_user

    async def override_db():
        yield db_session

    async def override_user():
        return user

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_current_user] = override_user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestCancelExecutionOperatorRule:
    @pytest.mark.asyncio
    async def test_cancel_execution_viewer_forbidden(self, db_session, test_user):
        from uuid import uuid4

        from modules.backend.core import security
        from modules.backend.core.exception_handlers import register_exception_handlers
        from modules.backend.models.execution_record import (
            ExecutionRecord,
            ExecutionRecordStatus,
        )
        from modules.backend.models.mission import (
            Mission,
            MissionMember,
            MissionMemberRole,
            MissionStatus,
        )
        from modules.backend.models.user import User

        viewer = User(
            id=str(uuid4()),
            email=f"p88-viewer-{uuid4().hex[:8]}@test.dev",
            display_name="Viewer",
            hashed_password=security.hash_password("viewer-password-123"),
            system_role="user",
            is_active=True,
        )
        mission = Mission(
            id=str(uuid4()),
            name=f"p88-viewer-{uuid4().hex[:8]}",
            description="Plan 88 viewer test",
            owner_id=test_user.id,
            status=MissionStatus.ACTIVE,
        )
        db_session.add_all([viewer, mission])
        await db_session.flush()
        record = ExecutionRecord(mission_id=mission.id, status=ExecutionRecordStatus.RUNNING)
        db_session.add_all(
            [
                MissionMember(
                    mission_id=mission.id, user_id=viewer.id, role=MissionMemberRole.VIEWER
                ),
                record,
            ]
        )
        await db_session.flush()

        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(router, prefix="/api/v1/executions")
        async with await _real_db_client(app, db_session, viewer) as ac:
            response = await ac.post(f"/api/v1/executions/{record.id}/cancel")

        assert response.status_code == 403
        await db_session.refresh(record)
        assert record.status == ExecutionRecordStatus.RUNNING


class TestLegacyWorkflowsMissionsRoutes:
    @pytest.mark.asyncio
    async def test_legacy_workflows_missions_routes_removed(self, mock_db_session):
        from modules.backend.api.v1 import router as api_v1_router
        from modules.backend.core.exception_handlers import register_exception_handlers

        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(api_v1_router, prefix="/api/v1")
        async with await _real_db_client(app, mock_db_session, _StubAdminUser()) as ac:
            responses = [
                await ac.post("/api/v1/workflows/missions", json={"objective": "x"}),
                await ac.get("/api/v1/workflows/missions"),
                await ac.get("/api/v1/workflows/missions/x"),
                await ac.post("/api/v1/workflows/missions/x/cancel"),
            ]

        codes = [r.status_code for r in responses]
        assert all(code in (404, 405) for code in codes), codes
