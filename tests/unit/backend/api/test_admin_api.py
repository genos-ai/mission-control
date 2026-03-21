"""Tests for admin API endpoints.

Services are lazily imported inside endpoint functions, so we patch them
at their source modules rather than inside the admin endpoint module.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from modules.backend.core.dependencies import require_admin
from modules.backend.core.database import get_db_session

CATALOG_SVC = "modules.backend.services.agent_catalog.AgentCatalogService"
METRICS_SVC = "modules.backend.services.platform_metrics.PlatformMetricsService"
PV_REPO = "modules.backend.repositories.prompt_version.PromptVersionRepository"
SEED_FN = "modules.backend.services.catalog_seeder.seed_catalog"
APP_CONFIG = "modules.backend.core.config.get_app_config"
CHECK_DB = "modules.backend.api.health.check_database"
CHECK_REDIS = "modules.backend.api.health.check_redis"


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture
def app(mock_db):
    """Create a FastAPI app with admin routes for testing."""
    from modules.backend.api.v1.endpoints import admin as admin_module

    _app = FastAPI()
    _app.include_router(admin_module.router, prefix="/admin")

    async def _always_admin():
        return "admin"

    async def _mock_db_session():
        return mock_db

    _app.dependency_overrides[require_admin] = _always_admin
    _app.dependency_overrides[get_db_session] = _mock_db_session
    return _app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestCatalogCRUD:
    @pytest.mark.asyncio
    @patch(CATALOG_SVC)
    async def test_list_catalog(self, MockCatalog, client):
        mock_entry = MagicMock(
            id="id-1", agent_name="test.agent", agent_type="vertical",
            version="1.0.0", description="Test", enabled=True,
            visibility="public", tools=[], keywords=[],
        )
        MockCatalog.return_value.list_catalog = AsyncMock(return_value=[mock_entry])

        resp = await client.get("/admin/catalog?enabled_only=false")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["count"] == 1

    @pytest.mark.asyncio
    @patch(CATALOG_SVC)
    async def test_create_catalog_entry(self, MockCatalog, client):
        mock_entry = MagicMock(id="id-2", agent_name="new.agent")
        MockCatalog.return_value.create_entry = AsyncMock(return_value=mock_entry)

        resp = await client.post("/admin/catalog", json={
            "agent_name": "new.agent",
            "agent_type": "vertical",
            "description": "A new agent",
        })
        assert resp.status_code == 200
        assert resp.json()["data"]["agent_name"] == "new.agent"

    @pytest.mark.asyncio
    @patch(CATALOG_SVC)
    async def test_update_catalog_entry(self, MockCatalog, client):
        mock_entry = MagicMock(id="id-1", agent_name="test.agent")
        MockCatalog.return_value.update_entry = AsyncMock(return_value=mock_entry)

        resp = await client.patch("/admin/catalog/test.agent", json={
            "description": "Updated",
        })
        assert resp.status_code == 200
        assert "description" in resp.json()["data"]["updated_fields"]

    @pytest.mark.asyncio
    @patch(CATALOG_SVC)
    async def test_update_no_fields(self, MockCatalog, client):
        resp = await client.patch("/admin/catalog/test.agent", json={})
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    @pytest.mark.asyncio
    @patch(CATALOG_SVC)
    async def test_delete_catalog_entry(self, MockCatalog, client):
        mock_entry = MagicMock(id="id-1", agent_name="test.agent")
        MockCatalog.return_value.get_by_name = AsyncMock(return_value=mock_entry)

        resp = await client.delete("/admin/catalog/test.agent")
        assert resp.status_code == 200
        assert resp.json()["data"]["deleted"] == "test.agent"


class TestSystemPromptEditor:
    @pytest.mark.asyncio
    @patch(CATALOG_SVC)
    async def test_update_prompt(self, MockCatalog, client):
        mock_entry = MagicMock(agent_name="test.agent", system_prompt="new prompt here")
        MockCatalog.return_value.update_system_prompt = AsyncMock(return_value=mock_entry)

        resp = await client.put("/admin/catalog/test.agent/prompt", json={
            "content": "new prompt here",
            "change_reason": "testing",
        })
        assert resp.status_code == 200
        assert resp.json()["data"]["prompt_length"] == len("new prompt here")

    @pytest.mark.asyncio
    @patch(PV_REPO)
    @patch(CATALOG_SVC)
    async def test_prompt_history(self, MockCatalog, MockPVRepo, client):
        mock_entry = MagicMock(id="id-1", agent_name="test.agent")
        MockCatalog.return_value.get_by_name = AsyncMock(return_value=mock_entry)
        MockPVRepo.return_value.list_versions = AsyncMock(return_value=[])

        resp = await client.get("/admin/catalog/test.agent/prompt-history")
        assert resp.status_code == 200
        assert resp.json()["data"]["versions"] == []


class TestPlatformMetrics:
    @pytest.mark.asyncio
    @patch(METRICS_SVC)
    async def test_overview(self, MockMetrics, client):
        MockMetrics.return_value.get_overview = AsyncMock(return_value={
            "counts": {"missions": 5, "sessions": 10},
            "total_cost_usd": 1.23,
            "generated_at": "2026-03-20T00:00:00",
        })

        resp = await client.get("/admin/metrics/overview")
        assert resp.status_code == 200
        assert resp.json()["data"]["counts"]["missions"] == 5

    @pytest.mark.asyncio
    @patch(METRICS_SVC)
    async def test_costs(self, MockMetrics, client):
        MockMetrics.return_value.get_cost_summary = AsyncMock(return_value={
            "by_agent": [{"agent_name": "a", "runs": 1, "total_cost_usd": 0.5}],
            "by_status": [],
            "generated_at": "2026-03-20T00:00:00",
        })

        resp = await client.get("/admin/metrics/costs")
        assert resp.status_code == 200
        assert len(resp.json()["data"]["by_agent"]) == 1

    @pytest.mark.asyncio
    @patch(METRICS_SVC)
    async def test_agent_utilisation(self, MockMetrics, client):
        MockMetrics.return_value.get_agent_utilisation = AsyncMock(return_value=[
            {"agent_name": "x", "total_runs": 3, "total_cost_usd": 0.3},
        ])

        resp = await client.get("/admin/metrics/agents")
        assert resp.status_code == 200
        assert len(resp.json()["data"]["agents"]) == 1

    @pytest.mark.asyncio
    @patch(METRICS_SVC)
    async def test_activity(self, MockMetrics, client):
        MockMetrics.return_value.get_recent_activity = AsyncMock(return_value={
            "recent_executions": [],
            "recent_workflow_runs": [],
        })

        resp = await client.get("/admin/metrics/activity")
        assert resp.status_code == 200


class TestSystemOps:
    @pytest.mark.asyncio
    @patch(APP_CONFIG)
    async def test_view_config(self, mock_config, client):
        cfg = MagicMock()
        cfg.application.name = "mission-control"
        cfg.application.version = "1.0.0"
        cfg.application.environment = "development"
        cfg.application.debug = True
        cfg.workflows.max_steps_per_workflow = 10
        cfg.workflows.default_budget_usd = 5.0
        cfg.workflows.max_budget_usd = 50.0
        cfg.workflows.max_concurrent_missions = 3
        cfg.workflows.max_scheduled_runs_per_day = 50
        cfg.workflows.schedule_evaluation_interval_seconds = 60
        cfg.sessions.default_ttl_hours = 24
        cfg.sessions.default_cost_budget_usd = 5.0
        cfg.sessions.max_cost_budget_usd = 50.0
        cfg.notifications.enabled = True
        cfg.notifications.notify_on_completion = True
        cfg.notifications.notify_on_failure = True
        cfg.notifications.budget_warning_threshold_pct = 80.0
        cfg.features.gateway_enabled = False
        cfg.features.agent_coordinator_enabled = True
        cfg.features.mcp_enabled = False
        cfg.features.events_publish_enabled = True
        mock_config.return_value = cfg

        resp = await client.get("/admin/config")
        assert resp.status_code == 200
        assert resp.json()["data"]["application"]["name"] == "mission-control"

    @pytest.mark.asyncio
    @patch(CHECK_REDIS)
    @patch(CHECK_DB)
    async def test_health_check(self, mock_db, mock_redis, client):
        mock_db.return_value = {"status": "healthy", "latency_ms": 5}
        mock_redis.return_value = {"status": "healthy", "latency_ms": 2}

        resp = await client.post("/admin/system/health")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["status"] == "healthy"
        assert data["checks"]["database"]["status"] == "healthy"

    @pytest.mark.asyncio
    @patch(CHECK_REDIS)
    @patch(CHECK_DB)
    async def test_health_check_degraded(self, mock_db, mock_redis, client):
        mock_db.return_value = {"status": "error", "error": "connection refused"}
        mock_redis.return_value = {"status": "healthy", "latency_ms": 2}

        resp = await client.post("/admin/system/health")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "degraded"


class TestRoleManagement:
    @pytest.mark.asyncio
    @patch(APP_CONFIG)
    async def test_list_roles(self, mock_config, client):
        from modules.backend.core.config_schema import RoleSchema
        cfg = MagicMock()
        cfg.security.roles = {
            "viewer": RoleSchema(level=1, description="Read-only"),
            "admin": RoleSchema(level=3, description="Full"),
        }
        mock_config.return_value = cfg

        resp = await client.get("/admin/roles")
        assert resp.status_code == 200
        roles = resp.json()["data"]["roles"]
        assert "viewer" in roles
        assert roles["admin"]["level"] == 3

    @pytest.mark.asyncio
    @patch(APP_CONFIG)
    async def test_list_user_roles(self, mock_config, client):
        cfg = MagicMock()
        cfg.security.user_roles = {"user123": "admin"}
        mock_config.return_value = cfg

        resp = await client.get("/admin/users/roles")
        assert resp.status_code == 200
        assert resp.json()["data"]["user_roles"]["user123"] == "admin"


class TestSeedCatalog:
    @pytest.mark.asyncio
    @patch(SEED_FN)
    @patch(CATALOG_SVC)
    async def test_seed(self, MockCatalog, mock_seed, client):
        mock_seed.return_value = {"seeded": 5, "skipped": 0, "errors": 0}

        resp = await client.post("/admin/seed-catalog?force=false")
        assert resp.status_code == 200
        assert resp.json()["data"]["seeded"] == 5
