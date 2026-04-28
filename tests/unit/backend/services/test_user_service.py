"""Tests for UserService.

Tests user CRUD, authorization enforcement, password management,
and account deactivation with API key cascade.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.backend.core.exceptions import (
    AuthorizationError,
    ConflictError,
    ValidationError,
)
from modules.backend.services.user import UserService
from tests.conftest import TEST_USER_ID, TEST_USER_ID_2


def _make_user(
    user_id: str = TEST_USER_ID,
    role: str = "admin",
    email: str = "admin@example.com",
    is_active: bool = True,
    hashed_password: str | None = "$2b$12$fakehash",
) -> MagicMock:
    """Create a mock User with config-driven has_role."""
    user = MagicMock()
    user.id = user_id
    user.email = email
    user.system_role = role
    user.is_active = is_active
    user.hashed_password = hashed_password
    user.has_role = MagicMock(
        side_effect=lambda minimum: {
            "viewer": 1, "user": 2, "admin": 3,
        }.get(role, 0) >= {"viewer": 1, "user": 2, "admin": 3}.get(minimum, 99)
    )
    return user


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
def service(mock_session):
    with patch("modules.backend.services.user.UserRepository") as MockUserRepo, \
         patch("modules.backend.services.user.ApiKeyRepository") as MockApiKeyRepo:
        svc = UserService(mock_session)
        svc.user_repo = MockUserRepo.return_value
        svc.api_key_repo = MockApiKeyRepo.return_value
        yield svc


class TestCreateUser:
    @pytest.mark.asyncio
    async def test_admin_creates_user(self, service):
        admin = _make_user(role="admin")
        service.user_repo.get_by_email = AsyncMock(return_value=None)
        new_user = _make_user(user_id=TEST_USER_ID_2, email="new@example.com", role="user")
        service.user_repo.create = AsyncMock(return_value=new_user)

        with patch("modules.backend.services.user.security.hash_password", return_value="hashed"):
            result = await service.create_user(
                email="new@example.com",
                display_name="New User",
                password="password123",
                system_role="user",
                is_service_account=False,
                requesting_user=admin,
            )

        assert result.email == "new@example.com"
        service.user_repo.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_admin_cannot_create(self, service):
        viewer = _make_user(role="viewer")

        with pytest.raises(AuthorizationError, match="Only admins"):
            await service.create_user(
                email="new@example.com",
                display_name="New",
                password="pw",
                system_role="user",
                is_service_account=False,
                requesting_user=viewer,
            )

    @pytest.mark.asyncio
    async def test_duplicate_email_raises_conflict(self, service):
        admin = _make_user(role="admin")
        service.user_repo.get_by_email = AsyncMock(
            return_value=_make_user(email="dup@example.com"),
        )

        with pytest.raises(ConflictError):
            await service.create_user(
                email="dup@example.com",
                display_name="Dup",
                password="pw",
                system_role="user",
                is_service_account=False,
                requesting_user=admin,
            )

    @pytest.mark.asyncio
    async def test_service_account_no_password(self, service):
        admin = _make_user(role="admin")
        service.user_repo.get_by_email = AsyncMock(return_value=None)
        svc_account = _make_user(user_id="svc-1", email="svc@example.com")
        service.user_repo.create = AsyncMock(return_value=svc_account)

        result = await service.create_user(
            email="svc@example.com",
            display_name="Bot",
            password=None,
            system_role="user",
            is_service_account=True,
            requesting_user=admin,
        )

        call_kwargs = service.user_repo.create.call_args.kwargs
        assert call_kwargs["hashed_password"] is None
        assert result is svc_account


class TestGetUser:
    @pytest.mark.asyncio
    async def test_admin_can_get_any_user(self, service):
        admin = _make_user(user_id="admin-1", role="admin")
        target = _make_user(user_id="target-1", role="user")
        service.user_repo.get_by_id = AsyncMock(return_value=target)

        result = await service.get_user("target-1", admin)
        assert result == target

    @pytest.mark.asyncio
    async def test_user_can_get_self(self, service):
        user = _make_user(user_id="self-1", role="user")
        service.user_repo.get_by_id = AsyncMock(return_value=user)

        result = await service.get_user("self-1", user)
        assert result == user

    @pytest.mark.asyncio
    async def test_user_cannot_get_other(self, service):
        user = _make_user(user_id="me", role="user")

        with pytest.raises(AuthorizationError):
            await service.get_user("other-user", user)


class TestListUsers:
    @pytest.mark.asyncio
    async def test_admin_can_list(self, service):
        admin = _make_user(role="admin")
        service.user_repo.list_all = AsyncMock(return_value=[admin])

        result = await service.list_users(admin)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_non_admin_denied(self, service):
        user = _make_user(role="user")

        with pytest.raises(AuthorizationError, match="Only admins"):
            await service.list_users(user)


class TestUpdateUser:
    @pytest.mark.asyncio
    async def test_admin_can_change_role(self, service):
        admin = _make_user(user_id="admin-1", role="admin")
        updated = _make_user(user_id="target", role="admin")
        service.user_repo.update = AsyncMock(return_value=updated)

        result = await service.update_user(
            "target", admin, system_role="admin",
        )
        assert result == updated

    @pytest.mark.asyncio
    async def test_user_can_update_own_display_name(self, service):
        user = _make_user(user_id="self-1", role="user")
        updated = _make_user(user_id="self-1", role="user")
        service.user_repo.update = AsyncMock(return_value=updated)

        result = await service.update_user(
            "self-1", user, display_name="New Name",
        )
        service.user_repo.update.assert_called_once_with(
            "self-1", display_name="New Name",
        )

    @pytest.mark.asyncio
    async def test_user_cannot_change_own_role(self, service):
        user = _make_user(user_id="self-1", role="user")

        with pytest.raises(AuthorizationError, match="Only admins"):
            await service.update_user(
                "self-1", user, system_role="admin",
            )

    @pytest.mark.asyncio
    async def test_user_cannot_update_other(self, service):
        user = _make_user(user_id="me", role="user")

        with pytest.raises(AuthorizationError, match="Cannot update"):
            await service.update_user(
                "other", user, display_name="Nope",
            )

    @pytest.mark.asyncio
    async def test_no_fields_returns_existing(self, service):
        user = _make_user(user_id="self-1", role="user")
        service.user_repo.get_by_id = AsyncMock(return_value=user)

        result = await service.update_user("self-1", user)
        assert result == user
        service.user_repo.update.assert_not_called()


class TestDeactivateUser:
    @pytest.mark.asyncio
    async def test_admin_deactivates_user_and_revokes_keys(self, service):
        admin = _make_user(user_id="admin-1", role="admin")
        deactivated = _make_user(user_id="target", is_active=False)
        service.user_repo.update = AsyncMock(return_value=deactivated)
        service.api_key_repo.revoke_all_by_user = AsyncMock(return_value=3)

        result = await service.deactivate_user("target", admin)

        assert result == deactivated
        service.user_repo.update.assert_called_once_with("target", is_active=False)
        service.api_key_repo.revoke_all_by_user.assert_called_once_with("target")

    @pytest.mark.asyncio
    async def test_non_admin_denied(self, service):
        user = _make_user(user_id="me", role="user")

        with pytest.raises(AuthorizationError, match="Only admins"):
            await service.deactivate_user("other", user)

    @pytest.mark.asyncio
    async def test_cannot_deactivate_self(self, service):
        admin = _make_user(user_id="admin-1", role="admin")

        with pytest.raises(ValidationError, match="Cannot deactivate own"):
            await service.deactivate_user("admin-1", admin)


class TestChangePassword:
    @pytest.mark.asyncio
    async def test_change_own_password(self, service):
        user = _make_user(user_id="me", role="user", hashed_password="$2b$12$oldhash")
        service.user_repo.get_by_id = AsyncMock(return_value=user)
        service.user_repo.update = AsyncMock()

        with patch("modules.backend.services.user.security.verify_password", return_value=True), \
             patch("modules.backend.services.user.security.hash_password", return_value="$2b$12$newhash"):
            await service.change_password("me", "oldpw", "newpw", user)

        service.user_repo.update.assert_called_once_with("me", hashed_password="$2b$12$newhash")

    @pytest.mark.asyncio
    async def test_wrong_old_password(self, service):
        user = _make_user(user_id="me", role="user", hashed_password="$2b$12$oldhash")
        service.user_repo.get_by_id = AsyncMock(return_value=user)

        with patch("modules.backend.services.user.security.verify_password", return_value=False):
            with pytest.raises(ValidationError, match="Current password is incorrect"):
                await service.change_password("me", "wrong", "newpw", user)

    @pytest.mark.asyncio
    async def test_cannot_change_other_password(self, service):
        user = _make_user(user_id="me", role="user")

        with pytest.raises(AuthorizationError, match="Can only change own"):
            await service.change_password("other", "old", "new", user)

    @pytest.mark.asyncio
    async def test_no_password_configured(self, service):
        user = _make_user(user_id="me", role="user", hashed_password=None)
        service.user_repo.get_by_id = AsyncMock(return_value=user)

        with pytest.raises(ValidationError, match="Password login not configured"):
            await service.change_password("me", "old", "new", user)


class TestAdminResetPassword:
    @pytest.mark.asyncio
    async def test_admin_resets_password(self, service):
        admin = _make_user(user_id="admin-1", role="admin")
        service.user_repo.update = AsyncMock()

        with patch("modules.backend.services.user.security.hash_password", return_value="$2b$12$reset"):
            await service.admin_reset_password("target", "newpw", admin)

        service.user_repo.update.assert_called_once_with(
            "target", hashed_password="$2b$12$reset",
        )

    @pytest.mark.asyncio
    async def test_non_admin_denied(self, service):
        user = _make_user(user_id="me", role="user")

        with pytest.raises(AuthorizationError, match="Only admins"):
            await service.admin_reset_password("target", "newpw", user)
