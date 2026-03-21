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


@pytest.fixture
async def client(app, mock_db_session):
    from modules.backend.core.database import get_db_session

    async def override_db():
        yield mock_db_session

    app.dependency_overrides[get_db_session] = override_db
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
            instance.get_cost_breakdown = AsyncMock(return_value=breakdown)

            response = await client.get("/executions/m-123/cost")
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["total_cost_usd"] == 0.10
