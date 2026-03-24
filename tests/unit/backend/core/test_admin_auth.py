"""Tests for user-based auth dependencies (get_current_user, require_admin)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.backend.core.config_schema import RoleSchema
from modules.backend.core.dependencies import get_current_user, require_admin
from modules.backend.core.exceptions import AuthenticationError, AuthorizationError
from modules.backend.models.user import User


def _make_user(role: str = "admin", is_active: bool = True) -> User:
    """Create a mock User object for testing."""
    user = MagicMock(spec=User)
    user.id = "test-user-id"
    user.email = "test@example.com"
    user.system_role = role
    user.is_active = is_active
    user.has_role = MagicMock(side_effect=lambda minimum: {
        "viewer": 1, "user": 2, "admin": 3,
    }.get(role, 0) >= {"viewer": 1, "user": 2, "admin": 3}.get(minimum, 99))
    return user


def _mock_roles():
    return {
        "viewer": RoleSchema(level=1, description="Read-only"),
        "user": RoleSchema(level=2, description="Standard access"),
        "admin": RoleSchema(level=3, description="Full access"),
    }


class TestGetCurrentUser:
    """Tests for get_current_user dependency."""

    @pytest.mark.asyncio
    async def test_jwt_bearer_resolves_user(self):
        """JWT Bearer token should resolve to a user."""
        user = _make_user("admin")
        mock_auth_service = MagicMock()
        mock_auth_service.resolve_jwt = AsyncMock(return_value=user)

        with patch("modules.backend.services.auth.AuthService", return_value=mock_auth_service):
            result = await get_current_user(
                db=MagicMock(),
                authorization="Bearer some-jwt-token",
                api_key=None,
            )
        assert result == user

    @pytest.mark.asyncio
    async def test_api_key_resolves_user(self):
        """X-API-Key header should resolve to a user."""
        user = _make_user("user")
        mock_auth_service = MagicMock()
        mock_auth_service.resolve_api_key = AsyncMock(return_value=user)

        with patch("modules.backend.services.auth.AuthService", return_value=mock_auth_service):
            result = await get_current_user(
                db=MagicMock(),
                authorization=None,
                api_key="app_test-key-12345",
            )
        assert result == user

    @pytest.mark.asyncio
    async def test_legacy_key_fallback(self):
        """Legacy ADMIN_API_KEY should fall back to resolve_legacy_key."""
        user = _make_user("admin")
        mock_auth_service = MagicMock()
        mock_auth_service.resolve_api_key = AsyncMock(side_effect=AuthenticationError("Invalid"))
        mock_auth_service.resolve_legacy_key = AsyncMock(return_value=user)

        with patch("modules.backend.services.auth.AuthService", return_value=mock_auth_service):
            result = await get_current_user(
                db=MagicMock(),
                authorization=None,
                api_key="legacy-admin-key",
            )
        assert result == user

    @pytest.mark.asyncio
    async def test_no_credentials_raises(self):
        """No auth headers should raise AuthenticationError."""
        with pytest.raises(AuthenticationError):
            await get_current_user(
                db=MagicMock(),
                authorization=None,
                api_key=None,
            )

    @pytest.mark.asyncio
    async def test_invalid_api_key_and_no_legacy_raises(self):
        """Invalid API key with no legacy fallback should raise."""
        mock_auth_service = MagicMock()
        mock_auth_service.resolve_api_key = AsyncMock(side_effect=AuthenticationError("Invalid"))
        mock_auth_service.resolve_legacy_key = AsyncMock(return_value=None)

        with patch("modules.backend.services.auth.AuthService", return_value=mock_auth_service):
            with pytest.raises(AuthenticationError):
                await get_current_user(
                    db=MagicMock(),
                    authorization=None,
                    api_key="bad-key",
                )


class TestRequireAdmin:
    """Tests for the require_admin dependency."""

    @pytest.mark.asyncio
    async def test_admin_passes(self):
        """Admin user should pass."""
        user = _make_user("admin")
        result = await require_admin(user=user)
        assert result == user

    @pytest.mark.asyncio
    async def test_viewer_denied(self):
        """Viewer user should be denied."""
        user = _make_user("viewer")
        with pytest.raises(AuthorizationError):
            await require_admin(user=user)

    @pytest.mark.asyncio
    async def test_user_role_denied(self):
        """Standard user should be denied admin access."""
        user = _make_user("user")
        with pytest.raises(AuthorizationError):
            await require_admin(user=user)
