"""Events that end every session of a user at once — real database, no mocks."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import AuthenticationError
from modules.backend.models.user import User
from modules.backend.services.auth import AuthService
from modules.backend.services.user import UserService

OLD_PASSWORD = "user-password-123"
NEW_PASSWORD = "a-new-password-456"


async def _two_sessions(service: AuthService) -> list[dict]:
    return [await service.login("user@test.dev", OLD_PASSWORD) for _ in range(2)]


async def _assert_every_token_ended(service: AuthService, sessions: list[dict]) -> None:
    for tokens in sessions:
        with pytest.raises(AuthenticationError, match="Session ended"):
            await service.resolve_jwt(tokens["access_token"])
        with pytest.raises(AuthenticationError, match="Session ended"):
            await service.refresh_token(tokens["refresh_token"])


async def test_password_change_ends_every_session(db_session: AsyncSession, regular_user: User):
    auth = AuthService(db_session)
    sessions = await _two_sessions(auth)
    assert (await auth.resolve_jwt(sessions[0]["access_token"])).id == regular_user.id

    await UserService(db_session).change_password(
        regular_user.id, OLD_PASSWORD, NEW_PASSWORD, regular_user
    )

    await _assert_every_token_ended(auth, sessions)
    fresh = await auth.login("user@test.dev", NEW_PASSWORD)
    assert (await auth.resolve_jwt(fresh["access_token"])).id == regular_user.id
    assert (await auth.refresh_token(fresh["refresh_token"]))["access_token"]


async def test_admin_reset_ends_every_session(
    db_session: AsyncSession, regular_user: User, admin_user: User
):
    auth = AuthService(db_session)
    sessions = await _two_sessions(auth)

    await UserService(db_session).admin_reset_password(regular_user.id, NEW_PASSWORD, admin_user)

    await _assert_every_token_ended(auth, sessions)


async def test_reactivating_a_deactivated_user_does_not_bring_old_sessions_back(
    db_session: AsyncSession, regular_user: User, admin_user: User
):
    auth = AuthService(db_session)
    users = UserService(db_session)
    sessions = await _two_sessions(auth)

    await users.deactivate_user(regular_user.id, admin_user)
    await users.update_user(regular_user.id, admin_user, is_active=True)

    await _assert_every_token_ended(auth, sessions)


async def test_deactivation_through_update_ends_sessions_too(
    db_session: AsyncSession, regular_user: User, admin_user: User
):
    auth = AuthService(db_session)
    users = UserService(db_session)
    sessions = await _two_sessions(auth)

    await users.update_user(regular_user.id, admin_user, is_active=False)
    await users.update_user(regular_user.id, admin_user, is_active=True)

    await _assert_every_token_ended(auth, sessions)


async def test_other_users_keep_their_sessions(
    db_session: AsyncSession, regular_user: User, admin_user: User
):
    auth = AuthService(db_session)
    admin_session = await auth.login("admin@test.dev", "admin-password-123")

    await UserService(db_session).change_password(
        regular_user.id, OLD_PASSWORD, NEW_PASSWORD, regular_user
    )

    assert (await auth.resolve_jwt(admin_session["access_token"])).id == admin_user.id
    assert (await auth.refresh_token(admin_session["refresh_token"]))["access_token"]
