"""Tests for user-based auth dependencies (get_current_user, require_admin)."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.backend.core.config_schema import RoleSchema
from modules.backend.core.dependencies import get_current_user, get_sse_session, require_admin
from modules.backend.core.exceptions import AuthenticationError, AuthorizationError
from modules.backend.models.user import User
from modules.backend.services.auth import SessionIdentity


def _make_user(role: str = "admin", is_active: bool = True) -> User:
    """Create a mock User object for testing."""
    user = MagicMock(spec=User)
    user.id = "test-user-id"
    user.email = "test@example.com"
    user.system_role = role
    user.is_active = is_active
    user.has_role = MagicMock(
        side_effect=lambda minimum: {
            "viewer": 1,
            "user": 2,
            "admin": 3,
        }.get(role, 0)
        >= {"viewer": 1, "user": 2, "admin": 3}.get(minimum, 99)
    )
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
                request=MagicMock(),
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
                request=MagicMock(),
                db=MagicMock(),
                authorization=None,
                api_key="app_test-key-12345",
            )
        assert result == user

    @pytest.mark.asyncio
    async def test_legacy_key_fallback(self):
        """Legacy ADMIN_API_KEY should fall back to resolve_legacy_key,
        but only when features.legacy_admin_key_enabled is on."""
        user = _make_user("admin")
        mock_auth_service = MagicMock()
        mock_auth_service.resolve_api_key = AsyncMock(side_effect=AuthenticationError("Invalid"))
        mock_auth_service.resolve_legacy_key = AsyncMock(return_value=user)

        fake_config = MagicMock()
        fake_config.features.legacy_admin_key_enabled = True

        with (
            patch("modules.backend.services.auth.AuthService", return_value=mock_auth_service),
            patch("modules.backend.core.config.get_app_config", return_value=fake_config),
        ):
            result = await get_current_user(
                request=MagicMock(),
                db=MagicMock(),
                authorization=None,
                api_key="legacy-admin-key",
            )
        assert result == user

    @pytest.mark.asyncio
    async def test_legacy_key_blocked_when_flag_disabled(self):
        """When legacy_admin_key_enabled is off (the default), the legacy
        fallback must not even be attempted."""
        user = _make_user("admin")
        mock_auth_service = MagicMock()
        mock_auth_service.resolve_api_key = AsyncMock(side_effect=AuthenticationError("Invalid"))
        mock_auth_service.resolve_legacy_key = AsyncMock(return_value=user)

        fake_config = MagicMock()
        fake_config.features.legacy_admin_key_enabled = False

        with (
            patch("modules.backend.services.auth.AuthService", return_value=mock_auth_service),
            patch("modules.backend.core.config.get_app_config", return_value=fake_config),
        ):
            with pytest.raises(AuthenticationError):
                await get_current_user(
                    request=MagicMock(),
                    db=MagicMock(),
                    authorization=None,
                    api_key="legacy-admin-key",
                )
        mock_auth_service.resolve_legacy_key.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_credentials_raises(self):
        """No auth headers should raise AuthenticationError."""
        with pytest.raises(AuthenticationError):
            await get_current_user(
                request=MagicMock(),
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
                    request=MagicMock(),
                    db=MagicMock(),
                    authorization=None,
                    api_key="bad-key",
                )


class _SessionScope:
    """Stand-in for get_async_session that records whether the scope is still open."""

    def __init__(self) -> None:
        self.open = False

    @asynccontextmanager
    async def __call__(self):
        self.open = True
        try:
            yield MagicMock()
        finally:
            self.open = False


class TestGetCurrentUserSse:
    """Tests for get_sse_session, in particular the fail-closed
    behaviour when the Redis-backed SSE token lookup itself errors out
    (must not be treated the same as token-not-found)."""

    @pytest.mark.asyncio
    async def test_redis_error_fails_closed(self):
        """A Redis error during the token lookup must raise, not fall
        back to treating the token as a raw JWT."""
        mock_redis = MagicMock()
        mock_redis.getdel = AsyncMock(side_effect=ConnectionError("redis unreachable"))
        mock_redis.aclose = AsyncMock()

        mock_auth_service = MagicMock()
        mock_auth_service.resolve_jwt_session = AsyncMock(
            return_value=(_make_user("admin"), MagicMock())
        )

        with (
            patch("redis.asyncio.Redis.from_url", return_value=mock_redis),
            patch("modules.backend.services.auth.AuthService", return_value=mock_auth_service),
            patch("modules.backend.core.dependencies.get_async_session", new=_SessionScope()),
        ):
            with pytest.raises(AuthenticationError):
                await get_sse_session(token="some-token", authorization=None)
        mock_auth_service.resolve_jwt_session.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_token_not_found_falls_back_to_jwt(self):
        """A clean Redis miss (token absent, no error) still falls back
        to treating the token value as a raw JWT."""
        mock_redis = MagicMock()
        mock_redis.getdel = AsyncMock(return_value=None)
        mock_redis.aclose = AsyncMock()

        user = _make_user("admin")
        identity = SessionIdentity(user_id=user.id, session_id="sid-1", token_version=0)
        mock_auth_service = MagicMock()
        mock_auth_service.resolve_jwt_session = AsyncMock(return_value=(user, identity))
        scope = _SessionScope()

        with (
            patch("redis.asyncio.Redis.from_url", return_value=mock_redis),
            patch("modules.backend.services.auth.AuthService", return_value=mock_auth_service),
            patch("modules.backend.core.dependencies.get_async_session", new=scope),
        ):
            result = await get_sse_session(token="raw-jwt", authorization=None)
        assert result.user == user
        assert result.identity == identity
        # A stream can stay open for hours: the connection must be back in the pool by now.
        assert scope.open is False

    @pytest.mark.asyncio
    async def test_session_released_when_authentication_fails(self):
        """The connection is also returned when no credentials are supplied."""
        scope = _SessionScope()
        with patch("modules.backend.core.dependencies.get_async_session", new=scope):
            with pytest.raises(AuthenticationError):
                await get_sse_session(token=None, authorization=None)
        assert scope.open is False


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
