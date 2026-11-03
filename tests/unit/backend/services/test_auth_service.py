"""Tests for AuthService.

Tests login, JWT/API-key resolution, token refresh, key management,
and legacy key fallback.
"""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.backend.core.config import get_app_config
from modules.backend.core.exceptions import AuthenticationError, AuthorizationError
from modules.backend.core.utils import utc_now
from modules.backend.services.auth import AuthService
from tests.conftest import TEST_USER_ID

SESSION_ID = "0192f3a4-0000-7000-8000-000000000001"


def _make_user(
    user_id: str = TEST_USER_ID,
    role: str = "user",
    email: str = "test@example.com",
    is_active: bool = True,
    hashed_password: str | None = "$2b$12$fakehash",
) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.email = email
    user.system_role = role
    user.is_active = is_active
    user.hashed_password = hashed_password
    user.has_role = MagicMock(
        side_effect=lambda minimum: {
            "viewer": 1,
            "user": 2,
            "admin": 3,
        }.get(role, 0)
        >= {"viewer": 1, "user": 2, "admin": 3}.get(minimum, 99)
    )
    return user


def _make_api_key(
    key_id: str = "key-1",
    user_id: str = TEST_USER_ID,
    user: MagicMock | None = None,
    hashed_key: str = "$2b$12$hashedkey",
) -> MagicMock:
    key = MagicMock()
    key.id = key_id
    key.user_id = user_id
    key.hashed_key = hashed_key
    key.user = user
    return key


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
def service(mock_session):
    with (
        patch("modules.backend.services.auth.UserRepository") as MockUserRepo,
        patch("modules.backend.services.auth.ApiKeyRepository") as MockApiKeyRepo,
        patch("modules.backend.services.auth.RevokedSessionRepository") as MockRevokedRepo,
    ):
        svc = AuthService(mock_session)
        svc.user_repo = MockUserRepo.return_value
        svc.api_key_repo = MockApiKeyRepo.return_value
        svc.revoked_session_repo = MockRevokedRepo.return_value
        svc.revoked_session_repo.is_revoked = AsyncMock(return_value=False)
        yield svc


class TestLogin:
    @pytest.mark.asyncio
    async def test_successful_login(self, service):
        user = _make_user()
        service.user_repo.get_by_email = AsyncMock(return_value=user)
        service.user_repo.update_last_login = AsyncMock()

        with (
            patch("modules.backend.services.auth.security.verify_password", return_value=True),
            patch(
                "modules.backend.services.auth.security.create_access_token",
                return_value="access-jwt",
            ),
            patch(
                "modules.backend.services.auth.security.create_refresh_token",
                return_value="refresh-jwt",
            ),
        ):
            result = await service.login("test@example.com", "password123")

        assert result["access_token"] == "access-jwt"
        assert result["refresh_token"] == "refresh-jwt"
        assert result["user"] == user
        service.user_repo.update_last_login.assert_called_once_with(user.id)

    @pytest.mark.asyncio
    async def test_login_puts_one_session_id_in_both_tokens(self, service):
        service.user_repo.get_by_email = AsyncMock(return_value=_make_user())
        service.user_repo.update_last_login = AsyncMock()

        with (
            patch("modules.backend.services.auth.security.verify_password", return_value=True),
            patch(
                "modules.backend.services.auth.security.create_access_token", return_value="a"
            ) as access,
            patch(
                "modules.backend.services.auth.security.create_refresh_token", return_value="r"
            ) as refresh,
        ):
            await service.login("test@example.com", "password123")

        access_sid = access.call_args.args[0]["sid"]
        assert access_sid and access_sid == refresh.call_args.args[0]["sid"]

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, service):
        service.user_repo.get_by_email = AsyncMock(return_value=None)

        with pytest.raises(AuthenticationError, match="Invalid credentials"):
            await service.login("nope@example.com", "pw")

    @pytest.mark.asyncio
    async def test_login_inactive_user(self, service):
        user = _make_user(is_active=False)
        service.user_repo.get_by_email = AsyncMock(return_value=user)

        with pytest.raises(AuthenticationError, match="Invalid credentials"):
            await service.login("test@example.com", "pw")

    @pytest.mark.asyncio
    async def test_login_no_password_set(self, service):
        user = _make_user(hashed_password=None)
        service.user_repo.get_by_email = AsyncMock(return_value=user)

        with pytest.raises(AuthenticationError, match="Invalid credentials"):
            await service.login("test@example.com", "pw")

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, service):
        user = _make_user()
        service.user_repo.get_by_email = AsyncMock(return_value=user)

        with patch("modules.backend.services.auth.security.verify_password", return_value=False):
            with pytest.raises(AuthenticationError, match="Invalid credentials"):
                await service.login("test@example.com", "wrong")


class TestRefreshToken:
    @pytest.mark.asyncio
    async def test_successful_refresh(self, service):
        user = _make_user()
        service.user_repo.get_active = AsyncMock(return_value=user)

        with (
            patch(
                "modules.backend.services.auth.security.decode_token",
                return_value={"type": "refresh", "sub": TEST_USER_ID, "sid": SESSION_ID},
            ),
            patch(
                "modules.backend.services.auth.security.create_access_token",
                return_value="new-access",
            ),
            patch(
                "modules.backend.services.auth.security.create_refresh_token",
                return_value="new-refresh",
            ),
        ):
            result = await service.refresh_token("old-refresh-token")

        assert result["access_token"] == "new-access"
        assert result["refresh_token"] == "new-refresh"

    @pytest.mark.asyncio
    async def test_refresh_keeps_the_session_id(self, service):
        service.user_repo.get_active = AsyncMock(return_value=_make_user())

        with (
            patch(
                "modules.backend.services.auth.security.decode_token",
                return_value={"type": "refresh", "sub": TEST_USER_ID, "sid": SESSION_ID},
            ),
            patch(
                "modules.backend.services.auth.security.create_access_token", return_value="a"
            ) as access,
            patch(
                "modules.backend.services.auth.security.create_refresh_token", return_value="r"
            ) as refresh,
        ):
            await service.refresh_token("old-refresh-token")

        assert access.call_args.args[0]["sid"] == SESSION_ID
        assert refresh.call_args.args[0]["sid"] == SESSION_ID

    @pytest.mark.asyncio
    async def test_refresh_of_a_revoked_session_fails(self, service):
        service.revoked_session_repo.is_revoked = AsyncMock(return_value=True)

        with patch(
            "modules.backend.services.auth.security.decode_token",
            return_value={"type": "refresh", "sub": TEST_USER_ID, "sid": SESSION_ID},
        ):
            with pytest.raises(AuthenticationError, match="Session ended"):
                await service.refresh_token("token")

        service.revoked_session_repo.is_revoked.assert_awaited_once_with(SESSION_ID)

    @pytest.mark.asyncio
    async def test_refresh_token_without_session_id_fails(self, service):
        """Tokens minted before sessions existed cannot be revoked, so they are refused."""
        with patch(
            "modules.backend.services.auth.security.decode_token",
            return_value={"type": "refresh", "sub": TEST_USER_ID},
        ):
            with pytest.raises(AuthenticationError, match="Invalid token"):
                await service.refresh_token("token")

    @pytest.mark.asyncio
    async def test_refresh_with_access_token_type_fails(self, service):
        with patch(
            "modules.backend.services.auth.security.decode_token",
            return_value={"type": "access", "sub": TEST_USER_ID, "sid": SESSION_ID},
        ):
            with pytest.raises(AuthenticationError, match="Invalid token type"):
                await service.refresh_token("access-token-not-refresh")

    @pytest.mark.asyncio
    async def test_refresh_missing_sub_fails(self, service):
        with patch(
            "modules.backend.services.auth.security.decode_token", return_value={"type": "refresh"}
        ):
            with pytest.raises(AuthenticationError, match="Invalid token"):
                await service.refresh_token("bad-token")

    @pytest.mark.asyncio
    async def test_refresh_inactive_user_fails(self, service):
        service.user_repo.get_active = AsyncMock(return_value=None)

        with patch(
            "modules.backend.services.auth.security.decode_token",
            return_value={"type": "refresh", "sub": TEST_USER_ID, "sid": SESSION_ID},
        ):
            with pytest.raises(AuthenticationError, match="User not found or inactive"):
                await service.refresh_token("token")


class TestResolveApiKey:
    @pytest.mark.asyncio
    async def test_valid_key_resolves(self, service):
        user = _make_user()
        key = _make_api_key(user=user)
        service.api_key_repo.get_by_prefix = AsyncMock(return_value=[key])
        service.api_key_repo.update_last_used = AsyncMock()

        with patch("modules.backend.services.auth.security.verify_api_key", return_value=True):
            result = await service.resolve_api_key("app_test1234rest_of_key")

        assert result == user
        service.api_key_repo.update_last_used.assert_called_once_with(key.id)

    @pytest.mark.asyncio
    async def test_short_key_rejected(self, service):
        with pytest.raises(AuthenticationError, match="Invalid API key"):
            await service.resolve_api_key("short")

    @pytest.mark.asyncio
    async def test_no_matching_prefix(self, service):
        service.api_key_repo.get_by_prefix = AsyncMock(return_value=[])

        with pytest.raises(AuthenticationError, match="Invalid API key"):
            await service.resolve_api_key("app_nomatch_rest_of_key")

    @pytest.mark.asyncio
    async def test_bcrypt_mismatch(self, service):
        key = _make_api_key(user=_make_user())
        service.api_key_repo.get_by_prefix = AsyncMock(return_value=[key])

        with patch("modules.backend.services.auth.security.verify_api_key", return_value=False):
            with pytest.raises(AuthenticationError, match="Invalid API key"):
                await service.resolve_api_key("app_test1234rest_of_key")

    @pytest.mark.asyncio
    async def test_deactivated_user_rejected(self, service):
        user = _make_user(is_active=False)
        key = _make_api_key(user=user)
        service.api_key_repo.get_by_prefix = AsyncMock(return_value=[key])

        with patch("modules.backend.services.auth.security.verify_api_key", return_value=True):
            with pytest.raises(AuthenticationError, match="Account deactivated"):
                await service.resolve_api_key("app_test1234rest_of_key")


class TestResolveJwt:
    @pytest.mark.asyncio
    async def test_valid_access_token(self, service):
        user = _make_user()
        service.user_repo.get_active = AsyncMock(return_value=user)

        with patch(
            "modules.backend.services.auth.security.decode_token",
            return_value={"type": "access", "sub": TEST_USER_ID, "sid": SESSION_ID},
        ):
            result = await service.resolve_jwt("valid-jwt")

        assert result == user

    @pytest.mark.asyncio
    async def test_revoked_session_rejected(self, service):
        service.revoked_session_repo.is_revoked = AsyncMock(return_value=True)

        with patch(
            "modules.backend.services.auth.security.decode_token",
            return_value={"type": "access", "sub": TEST_USER_ID, "sid": SESSION_ID},
        ):
            with pytest.raises(AuthenticationError, match="Session ended"):
                await service.resolve_jwt("token")

    @pytest.mark.asyncio
    async def test_token_without_session_id_rejected(self, service):
        with patch(
            "modules.backend.services.auth.security.decode_token",
            return_value={"type": "access", "sub": TEST_USER_ID},
        ):
            with pytest.raises(AuthenticationError, match="Invalid token"):
                await service.resolve_jwt("token")

    @pytest.mark.asyncio
    async def test_refresh_token_rejected(self, service):
        with patch(
            "modules.backend.services.auth.security.decode_token",
            return_value={"type": "refresh", "sub": TEST_USER_ID, "sid": SESSION_ID},
        ):
            with pytest.raises(AuthenticationError, match="Invalid token type"):
                await service.resolve_jwt("refresh-not-access")

    @pytest.mark.asyncio
    async def test_inactive_user_rejected(self, service):
        service.user_repo.get_active = AsyncMock(return_value=None)

        with patch(
            "modules.backend.services.auth.security.decode_token",
            return_value={"type": "access", "sub": TEST_USER_ID, "sid": SESSION_ID},
        ):
            with pytest.raises(AuthenticationError, match="User not found or inactive"):
                await service.resolve_jwt("token")


class TestLogout:
    @pytest.mark.asyncio
    async def test_logout_revokes_the_session_and_commits(self, service, mock_session):
        service.revoked_session_repo.revoke = AsyncMock()

        with patch(
            "modules.backend.services.auth.security.decode_token",
            return_value={"type": "access", "sub": TEST_USER_ID, "sid": SESSION_ID},
        ):
            await service.logout("access-jwt")

        session_id, user_id, expires_at = service.revoked_session_repo.revoke.call_args.args
        assert (session_id, user_id) == (SESSION_ID, TEST_USER_ID)
        refresh_days = get_app_config().security.jwt.refresh_token_expire_days
        expected = utc_now() + timedelta(days=refresh_days)
        assert abs(expires_at - expected) < timedelta(seconds=5)
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_logout_with_a_refresh_token_fails(self, service, mock_session):
        service.revoked_session_repo.revoke = AsyncMock()

        with patch(
            "modules.backend.services.auth.security.decode_token",
            return_value={"type": "refresh", "sub": TEST_USER_ID, "sid": SESSION_ID},
        ):
            with pytest.raises(AuthenticationError, match="Invalid token type"):
                await service.logout("refresh-jwt")

        service.revoked_session_repo.revoke.assert_not_awaited()
        mock_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_logout_of_an_ended_session_fails(self, service):
        service.revoked_session_repo.is_revoked = AsyncMock(return_value=True)

        with patch(
            "modules.backend.services.auth.security.decode_token",
            return_value={"type": "access", "sub": TEST_USER_ID, "sid": SESSION_ID},
        ):
            with pytest.raises(AuthenticationError, match="Session ended"):
                await service.logout("access-jwt")


class TestCreateApiKey:
    @pytest.mark.asyncio
    async def test_owner_creates_key(self, service):
        user = _make_user(user_id=TEST_USER_ID, role="user")
        mock_key = _make_api_key()
        service.api_key_repo.create = AsyncMock(return_value=mock_key)

        with patch(
            "modules.backend.services.auth.security.generate_api_key",
            return_value=("app_fullkey1234rest", "$2b$12$hashed"),
        ):
            full_key, api_key = await service.create_api_key(
                user_id=TEST_USER_ID,
                name="my-key",
                expires_in_days=30,
                requesting_user=user,
            )

        assert full_key == "app_fullkey1234rest"
        assert api_key == mock_key
        create_kwargs = service.api_key_repo.create.call_args.kwargs
        assert create_kwargs["key_prefix"] == "app_full"
        assert create_kwargs["expires_at"] is not None

    @pytest.mark.asyncio
    async def test_admin_creates_key_for_other(self, service):
        admin = _make_user(user_id="admin-1", role="admin")
        mock_key = _make_api_key(user_id="other-1")
        service.api_key_repo.create = AsyncMock(return_value=mock_key)

        with patch(
            "modules.backend.services.auth.security.generate_api_key",
            return_value=("app_key12345rest", "$2b$12$hashed"),
        ):
            full_key, _ = await service.create_api_key(
                user_id="other-1",
                name="admin-created",
                expires_in_days=None,
                requesting_user=admin,
            )

        create_kwargs = service.api_key_repo.create.call_args.kwargs
        assert create_kwargs["expires_at"] is None

    @pytest.mark.asyncio
    async def test_non_owner_non_admin_denied(self, service):
        user = _make_user(user_id="me", role="user")

        with pytest.raises(AuthorizationError):
            await service.create_api_key(
                user_id="other",
                name="nope",
                expires_in_days=30,
                requesting_user=user,
            )


class TestRevokeApiKey:
    @pytest.mark.asyncio
    async def test_owner_revokes(self, service):
        user = _make_user(user_id=TEST_USER_ID, role="user")
        key = _make_api_key(user_id=TEST_USER_ID)
        revoked_key = _make_api_key(user_id=TEST_USER_ID)
        service.api_key_repo.get_by_id = AsyncMock(return_value=key)
        service.api_key_repo.revoke = AsyncMock(return_value=revoked_key)

        result = await service.revoke_api_key("key-1", user)
        assert result == revoked_key

    @pytest.mark.asyncio
    async def test_non_owner_non_admin_denied(self, service):
        user = _make_user(user_id="me", role="user")
        key = _make_api_key(user_id="other")
        service.api_key_repo.get_by_id = AsyncMock(return_value=key)

        with pytest.raises(AuthorizationError):
            await service.revoke_api_key("key-1", user)


class TestResolveLegacyKey:
    @pytest.mark.asyncio
    async def test_matching_legacy_key(self, service):
        admin = _make_user(user_id="admin-1", role="admin")
        service.user_repo.list_all = AsyncMock(return_value=[admin])

        mock_settings = MagicMock()
        mock_settings.admin_api_key = "legacy-secret"

        with patch("modules.backend.core.config.get_settings", return_value=mock_settings):
            result = await service.resolve_legacy_key("legacy-secret")

        assert result == admin

    @pytest.mark.asyncio
    async def test_non_matching_legacy_key(self, service):
        mock_settings = MagicMock()
        mock_settings.admin_api_key = "legacy-secret"

        with patch("modules.backend.core.config.get_settings", return_value=mock_settings):
            result = await service.resolve_legacy_key("wrong-key")

        assert result is None

    @pytest.mark.asyncio
    async def test_no_legacy_key_configured(self, service):
        mock_settings = MagicMock()
        mock_settings.admin_api_key = None

        with patch("modules.backend.core.config.get_settings", return_value=mock_settings):
            result = await service.resolve_legacy_key("any-key")

        assert result is None

    @pytest.mark.asyncio
    async def test_no_admin_user_exists(self, service):
        service.user_repo.list_all = AsyncMock(return_value=[])

        mock_settings = MagicMock()
        mock_settings.admin_api_key = "legacy-secret"

        with patch("modules.backend.core.config.get_settings", return_value=mock_settings):
            result = await service.resolve_legacy_key("legacy-secret")

        assert result is None
