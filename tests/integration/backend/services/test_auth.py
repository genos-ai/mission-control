"""Integration tests for AuthService — real database, no mocks."""

from datetime import timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import AuthenticationError
from modules.backend.core.utils import utc_now
from modules.backend.models.user import User
from modules.backend.repositories.revoked_session import RevokedSessionRepository
from modules.backend.services.auth import AuthService


class TestLogin:
    async def test_login_success(self, db_session: AsyncSession, regular_user: User):
        service = AuthService(db_session)
        result = await service.login("user@test.dev", "user-password-123")

        assert "access_token" in result
        assert "refresh_token" in result
        assert result["user"].id == regular_user.id

    async def test_login_wrong_password(self, db_session: AsyncSession, regular_user: User):
        service = AuthService(db_session)
        with pytest.raises(AuthenticationError):
            await service.login("user@test.dev", "wrong-password")

    async def test_login_nonexistent_email(self, db_session: AsyncSession):
        service = AuthService(db_session)
        with pytest.raises(AuthenticationError):
            await service.login("nobody@test.dev", "any-password")

    async def test_login_inactive_user(self, db_session: AsyncSession, inactive_user: User):
        service = AuthService(db_session)
        with pytest.raises(AuthenticationError):
            await service.login("inactive@test.dev", "inactive-pass-123")

    async def test_login_no_password_set(self, db_session: AsyncSession):
        """Service accounts have no password — login should fail."""
        from uuid import UUID, uuid5

        svc_id = str(uuid5(UUID("00000000-0000-0000-0000-000000000000"), "user:svc-account"))
        user = User(
            id=svc_id,
            email="svc@test.dev",
            display_name="Service Account",
            hashed_password=None,
            system_role="user",
            is_active=True,
            is_service_account=True,
        )
        db_session.add(user)
        await db_session.flush()

        service = AuthService(db_session)
        with pytest.raises(AuthenticationError):
            await service.login("svc@test.dev", "any-password")


class TestTokenRefresh:
    async def test_refresh_token_roundtrip(self, db_session: AsyncSession, regular_user: User):
        service = AuthService(db_session)
        login_result = await service.login("user@test.dev", "user-password-123")

        refresh_result = await service.refresh_token(login_result["refresh_token"])

        assert "access_token" in refresh_result
        assert "refresh_token" in refresh_result
        # New tokens should be different from original
        assert refresh_result["access_token"] != login_result["access_token"]

    async def test_refresh_with_access_token_fails(
        self, db_session: AsyncSession, regular_user: User
    ):
        """Access tokens must not be usable as refresh tokens."""
        service = AuthService(db_session)
        login_result = await service.login("user@test.dev", "user-password-123")

        with pytest.raises(AuthenticationError):
            await service.refresh_token(login_result["access_token"])

    async def test_refresh_with_garbage_token_fails(self, db_session: AsyncSession):
        service = AuthService(db_session)
        with pytest.raises(AuthenticationError):
            await service.refresh_token("not-a-real-token")


class TestLogout:
    async def test_logout_commits_the_revocation(
        self, db_session: AsyncSession, regular_user: User
    ):
        """The test session joins an outer transaction that is rolled back, so a commit is
        invisible to a second connection. The session's commit event is what proves the
        revocation is made durable before logout answers."""
        service = AuthService(db_session)
        tokens = await service.login("user@test.dev", "user-password-123")
        commits: list[bool] = []
        event.listen(db_session.sync_session, "after_commit", lambda _session: commits.append(True))

        await service.logout(tokens["access_token"])

        assert commits == [True]

    async def test_logout_ends_the_access_token(self, db_session: AsyncSession, regular_user: User):
        service = AuthService(db_session)
        tokens = await service.login("user@test.dev", "user-password-123")
        assert (await service.resolve_jwt(tokens["access_token"])).id == regular_user.id

        await service.logout(tokens["access_token"])

        with pytest.raises(AuthenticationError, match="Session ended"):
            await service.resolve_jwt(tokens["access_token"])

    async def test_logout_ends_every_refresh_token_of_the_session(
        self, db_session: AsyncSession, regular_user: User
    ):
        """A refresh token copied before a later refresh must die with the session too."""
        service = AuthService(db_session)
        first = await service.login("user@test.dev", "user-password-123")
        second = await service.refresh_token(first["refresh_token"])
        third = await service.refresh_token(second["refresh_token"])

        await service.logout(third["access_token"])

        for refresh_token in (first, second, third):
            with pytest.raises(AuthenticationError, match="Session ended"):
                await service.refresh_token(refresh_token["refresh_token"])

    async def test_logout_leaves_other_sessions_of_the_user_signed_in(
        self, db_session: AsyncSession, regular_user: User
    ):
        service = AuthService(db_session)
        laptop = await service.login("user@test.dev", "user-password-123")
        phone = await service.login("user@test.dev", "user-password-123")

        await service.logout(laptop["access_token"])

        assert (await service.resolve_jwt(phone["access_token"])).id == regular_user.id
        assert "access_token" in await service.refresh_token(phone["refresh_token"])

    async def test_logout_rejects_a_refresh_token(
        self, db_session: AsyncSession, regular_user: User
    ):
        service = AuthService(db_session)
        tokens = await service.login("user@test.dev", "user-password-123")

        with pytest.raises(AuthenticationError, match="Invalid token type"):
            await service.logout(tokens["refresh_token"])

        assert (await service.resolve_jwt(tokens["access_token"])).id == regular_user.id

    async def test_revoking_twice_changes_nothing(
        self, db_session: AsyncSession, regular_user: User
    ):
        repo = RevokedSessionRepository(db_session)
        session_id = "0192f3a4-0000-7000-8000-0000000000aa"
        expires_at = utc_now() + timedelta(days=7)

        await repo.revoke(session_id, regular_user.id, expires_at)
        await repo.revoke(session_id, regular_user.id, expires_at)

        assert await repo.is_revoked(session_id)

    async def test_purge_deletes_only_expired_revocations(
        self, db_session: AsyncSession, regular_user: User
    ):
        repo = RevokedSessionRepository(db_session)
        expired = "0192f3a4-0000-7000-8000-0000000000e1"
        live = "0192f3a4-0000-7000-8000-0000000000e2"
        await repo.revoke(expired, regular_user.id, utc_now() - timedelta(minutes=1))
        await repo.revoke(live, regular_user.id, utc_now() + timedelta(days=1))

        deleted = await AuthService(db_session).purge_expired_revocations()

        assert deleted == 1
        assert not await repo.is_revoked(expired)
        assert await repo.is_revoked(live)


class TestApiKeys:
    async def test_create_and_resolve_api_key(self, db_session: AsyncSession, regular_user: User):
        service = AuthService(db_session)

        full_key, api_key = await service.create_api_key(
            regular_user.id,
            "test-key",
            None,
            regular_user,
        )

        assert full_key.startswith("app_")
        assert api_key.name == "test-key"
        assert api_key.user_id == regular_user.id

        # Resolve the key back to a user
        resolved_user = await service.resolve_api_key(full_key)
        assert resolved_user.id == regular_user.id

    async def test_resolve_invalid_api_key(self, db_session: AsyncSession):
        service = AuthService(db_session)
        with pytest.raises(AuthenticationError):
            await service.resolve_api_key("mc_bogus_key_value")

    async def test_list_api_keys(self, db_session: AsyncSession, regular_user: User):
        service = AuthService(db_session)
        await service.create_api_key(regular_user.id, "key-1", None, regular_user)
        await service.create_api_key(regular_user.id, "key-2", None, regular_user)

        keys = await service.list_api_keys(regular_user.id, regular_user)
        assert len(keys) == 2
        names = {k.name for k in keys}
        assert names == {"key-1", "key-2"}

    async def test_revoke_api_key(self, db_session: AsyncSession, regular_user: User):
        service = AuthService(db_session)
        full_key, api_key = await service.create_api_key(
            regular_user.id,
            "revoke-me",
            None,
            regular_user,
        )

        await service.revoke_api_key(api_key.id, regular_user)

        # Revoked key should no longer resolve
        with pytest.raises(AuthenticationError):
            await service.resolve_api_key(full_key)
