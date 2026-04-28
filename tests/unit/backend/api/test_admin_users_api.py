"""Tests for admin user management API endpoints.

Services are lazily imported inside endpoint functions, so we patch them
at their source modules rather than inside the admin_users endpoint module.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from modules.backend.core.database import get_db_session
from modules.backend.core.dependencies import require_admin
from tests.conftest import TEST_USER_ID, TEST_USER_ID_2

USER_SVC = "modules.backend.services.user.UserService"
AUTH_SVC = "modules.backend.services.auth.AuthService"
APP_CONFIG = "modules.backend.core.config.get_app_config"

NOW = datetime(2026, 3, 20, 12, 0, 0)


def _mock_user(**overrides):
    """Create a mock User ORM object."""
    defaults = dict(
        id=TEST_USER_ID,
        email="alice@example.com",
        display_name="Alice",
        system_role="user",
        is_active=True,
        is_service_account=False,
        last_login_at=None,
        current_mission_id=None,
        current_mission=None,
        created_at=NOW,
        updated_at=NOW,
    )
    defaults.update(overrides)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _mock_api_key(**overrides):
    """Create a mock ApiKey ORM object."""
    defaults = dict(
        id="key-1",
        name="dev-key",
        key_prefix="mc_abcde",
        user_id=TEST_USER_ID,
        expires_at=None,
        revoked_at=None,
        last_used_at=None,
        created_at=NOW,
    )
    defaults.update(overrides)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture
def app(mock_db):
    """Create a FastAPI app with admin user routes for testing."""
    from modules.backend.api.v1.endpoints import admin_users as admin_users_module
    from modules.backend.core.exception_handlers import register_exception_handlers

    _app = FastAPI()
    register_exception_handlers(_app)
    _app.include_router(admin_users_module.router, prefix="/admin/users")

    async def _always_admin():
        return MagicMock(
            id="test-admin", email="admin@test.com", system_role="admin",
            has_role=lambda r: True, is_active=True,
        )

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


class TestCreateUser:
    @pytest.mark.asyncio
    @patch(USER_SVC)
    async def test_create_user(self, MockUserSvc, client):
        user = _mock_user()
        MockUserSvc.return_value.create_user = AsyncMock(return_value=user)

        resp = await client.post("/admin/users/", json={
            "email": "alice@example.com",
            "display_name": "Alice",
            "password": "securepassword123",
            "system_role": "user",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["email"] == "alice@example.com"

    @pytest.mark.asyncio
    @patch(USER_SVC)
    async def test_create_user_conflict(self, MockUserSvc, client):
        from modules.backend.core.exceptions import ConflictError

        MockUserSvc.return_value.create_user = AsyncMock(
            side_effect=ConflictError("User could not be created"),
        )

        resp = await client.post("/admin/users/", json={
            "email": "alice@example.com",
            "display_name": "Alice",
        })
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_create_user_invalid_role(self, client):
        resp = await client.post("/admin/users/", json={
            "email": "alice@example.com",
            "display_name": "Alice",
            "system_role": "superadmin",
        })
        assert resp.status_code == 422


class TestListUsers:
    @pytest.mark.asyncio
    @patch(USER_SVC)
    async def test_list_users(self, MockUserSvc, client):
        users = [_mock_user(), _mock_user(id=TEST_USER_ID_2, email="bob@example.com")]
        MockUserSvc.return_value.list_users = AsyncMock(return_value=users)

        resp = await client.get("/admin/users/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["data"]) == 2

    @pytest.mark.asyncio
    @patch(USER_SVC)
    async def test_list_users_with_pagination(self, MockUserSvc, client):
        MockUserSvc.return_value.list_users = AsyncMock(return_value=[])

        resp = await client.get("/admin/users/?limit=10&offset=5")
        assert resp.status_code == 200
        MockUserSvc.return_value.list_users.assert_called_once()
        call_kwargs = MockUserSvc.return_value.list_users.call_args
        assert call_kwargs.kwargs["limit"] == 10
        assert call_kwargs.kwargs["offset"] == 5


class TestGetUser:
    @pytest.mark.asyncio
    @patch(USER_SVC)
    async def test_get_user(self, MockUserSvc, client):
        user = _mock_user()
        MockUserSvc.return_value.get_user = AsyncMock(return_value=user)

        resp = await client.get("/admin/users/user-1")
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == TEST_USER_ID

    @pytest.mark.asyncio
    @patch(USER_SVC)
    async def test_get_user_not_found(self, MockUserSvc, client):
        from modules.backend.core.exceptions import NotFoundError

        MockUserSvc.return_value.get_user = AsyncMock(
            side_effect=NotFoundError("User not found"),
        )

        resp = await client.get("/admin/users/nonexistent")
        assert resp.status_code == 404


class TestUpdateUser:
    @pytest.mark.asyncio
    @patch(USER_SVC)
    async def test_update_user(self, MockUserSvc, client):
        user = _mock_user(display_name="Alice Updated")
        MockUserSvc.return_value.update_user = AsyncMock(return_value=user)

        resp = await client.patch("/admin/users/user-1", json={
            "display_name": "Alice Updated",
        })
        assert resp.status_code == 200
        assert resp.json()["data"]["display_name"] == "Alice Updated"

    @pytest.mark.asyncio
    @patch(USER_SVC)
    async def test_update_user_role(self, MockUserSvc, client):
        user = _mock_user(system_role="admin")
        MockUserSvc.return_value.update_user = AsyncMock(return_value=user)

        resp = await client.patch("/admin/users/user-1", json={
            "system_role": "admin",
        })
        assert resp.status_code == 200
        assert resp.json()["data"]["system_role"] == "admin"


class TestDeactivateUser:
    @pytest.mark.asyncio
    @patch(USER_SVC)
    async def test_deactivate_user(self, MockUserSvc, client):
        MockUserSvc.return_value.deactivate_user = AsyncMock()

        resp = await client.delete("/admin/users/user-1")
        assert resp.status_code == 200
        assert resp.json()["data"]["message"] == "User deactivated"

    @pytest.mark.asyncio
    @patch(USER_SVC)
    async def test_deactivate_self_rejected(self, MockUserSvc, client):
        from modules.backend.core.exceptions import ValidationError

        MockUserSvc.return_value.deactivate_user = AsyncMock(
            side_effect=ValidationError("Cannot deactivate own account"),
        )

        resp = await client.delete("/admin/users/test-admin")
        assert resp.status_code == 400


class TestResetPassword:
    @pytest.mark.asyncio
    @patch(USER_SVC)
    async def test_reset_password(self, MockUserSvc, client):
        MockUserSvc.return_value.admin_reset_password = AsyncMock()

        resp = await client.post("/admin/users/user-1/reset-password", json={
            "new_password": "newsecurepassword123",
        })
        assert resp.status_code == 200
        assert resp.json()["data"]["message"] == "Password reset"

    @pytest.mark.asyncio
    async def test_reset_password_too_short(self, client):
        resp = await client.post("/admin/users/user-1/reset-password", json={
            "new_password": "short",
        })
        assert resp.status_code == 422


class TestApiKeyManagement:
    @pytest.mark.asyncio
    @patch(AUTH_SVC)
    async def test_create_api_key(self, MockAuthSvc, client):
        api_key = _mock_api_key()
        MockAuthSvc.return_value.create_api_key = AsyncMock(
            return_value=("mc_abcde_full_key_value", api_key),
        )

        resp = await client.post("/admin/users/user-1/api-keys", json={
            "name": "dev-key",
            "expires_in_days": 90,
        })
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["name"] == "dev-key"
        assert "key" in data

    @pytest.mark.asyncio
    @patch(AUTH_SVC)
    async def test_list_api_keys(self, MockAuthSvc, client):
        keys = [_mock_api_key(), _mock_api_key(id="key-2", name="ci-key")]
        MockAuthSvc.return_value.list_api_keys = AsyncMock(return_value=keys)

        resp = await client.get("/admin/users/user-1/api-keys")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 2

    @pytest.mark.asyncio
    @patch(AUTH_SVC)
    async def test_revoke_api_key(self, MockAuthSvc, client):
        MockAuthSvc.return_value.revoke_api_key = AsyncMock()

        resp = await client.delete("/admin/users/user-1/api-keys/key-1")
        assert resp.status_code == 200
        assert resp.json()["data"]["message"] == "API key revoked"

    @pytest.mark.asyncio
    @patch(AUTH_SVC)
    async def test_revoke_nonexistent_key(self, MockAuthSvc, client):
        from modules.backend.core.exceptions import NotFoundError

        MockAuthSvc.return_value.revoke_api_key = AsyncMock(
            side_effect=NotFoundError("API key not found"),
        )

        resp = await client.delete("/admin/users/user-1/api-keys/nope")
        assert resp.status_code == 404


class TestListRoles:
    @pytest.mark.asyncio
    @patch(APP_CONFIG)
    async def test_list_roles(self, mock_config, client):
        from modules.backend.core.config_schema import RoleSchema

        cfg = MagicMock()
        cfg.security.roles = {
            "viewer": RoleSchema(level=1, description="Read-only"),
            "user": RoleSchema(level=2, description="Standard"),
            "admin": RoleSchema(level=3, description="Full access"),
        }
        mock_config.return_value = cfg

        resp = await client.get("/admin/users/roles")
        assert resp.status_code == 200
        roles = resp.json()["data"]["roles"]
        assert "viewer" in roles
        assert "admin" in roles
        assert roles["admin"]["level"] == 3
