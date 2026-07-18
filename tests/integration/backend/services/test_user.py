"""Integration tests for UserService — real database, no mocks."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import AuthorizationError, NotFoundError, ValidationError
from modules.backend.models.mission import Mission
from modules.backend.models.user import User
from modules.backend.services.user import UserService


class TestGetUser:
    async def test_get_own_profile(self, db_session: AsyncSession, regular_user: User):
        service = UserService(db_session)
        result = await service.get_user(regular_user.id, regular_user)
        assert result.id == regular_user.id
        assert result.email == "user@test.dev"

    async def test_admin_can_get_any_user(
        self,
        db_session: AsyncSession,
        admin_user: User,
        regular_user: User,
    ):
        service = UserService(db_session)
        result = await service.get_user(regular_user.id, admin_user)
        assert result.id == regular_user.id

    async def test_user_cannot_get_other_user(
        self,
        db_session: AsyncSession,
        regular_user: User,
        admin_user: User,
    ):
        service = UserService(db_session)
        with pytest.raises(AuthorizationError):
            await service.get_user(admin_user.id, regular_user)


class TestGetUserByIdOrNone:
    async def test_returns_user(self, db_session: AsyncSession, regular_user: User):
        service = UserService(db_session)
        result = await service.get_user_by_id_or_none(regular_user.id)
        assert result is not None
        assert result.id == regular_user.id

    async def test_returns_none_for_missing(self, db_session: AsyncSession):
        service = UserService(db_session)
        result = await service.get_user_by_id_or_none("00000000-0000-0000-0000-000000000000")
        assert result is None


class TestGetCurrentMissionId:
    async def test_returns_none_when_no_mission_set(
        self,
        db_session: AsyncSession,
        regular_user: User,
    ):
        service = UserService(db_session)
        result = await service.get_current_mission_id(regular_user.id)
        assert result is None

    async def test_returns_mission_id_when_set(
        self,
        db_session: AsyncSession,
        regular_user: User,
        test_mission: Mission,
    ):
        service = UserService(db_session)
        await service.set_current_mission(
            regular_user.id,
            test_mission.id,
            regular_user,
        )
        result = await service.get_current_mission_id(regular_user.id)
        assert result == test_mission.id

    async def test_returns_none_for_nonexistent_user(self, db_session: AsyncSession):
        service = UserService(db_session)
        result = await service.get_current_mission_id("00000000-0000-0000-0000-000000000000")
        assert result is None


class TestSetCurrentMission:
    async def test_set_and_clear(
        self,
        db_session: AsyncSession,
        regular_user: User,
        test_mission: Mission,
    ):
        service = UserService(db_session)

        # Set
        user = await service.set_current_mission(
            regular_user.id,
            test_mission.id,
            regular_user,
        )
        assert user.current_mission_id == test_mission.id

        # Clear
        user = await service.set_current_mission(
            regular_user.id,
            None,
            regular_user,
        )
        assert user.current_mission_id is None

    async def test_cannot_select_archived_mission(
        self,
        db_session: AsyncSession,
        regular_user: User,
        archived_mission: Mission,
    ):
        service = UserService(db_session)
        with pytest.raises(ValidationError):
            await service.set_current_mission(
                regular_user.id,
                archived_mission.id,
                regular_user,
            )

    async def test_cannot_select_nonexistent_mission(
        self,
        db_session: AsyncSession,
        regular_user: User,
    ):
        service = UserService(db_session)
        with pytest.raises(NotFoundError):
            await service.set_current_mission(
                regular_user.id,
                "00000000-0000-0000-0000-000000000000",
                regular_user,
            )

    async def test_user_cannot_set_other_users_mission(
        self,
        db_session: AsyncSession,
        regular_user: User,
        admin_user: User,
        test_mission: Mission,
    ):
        service = UserService(db_session)
        with pytest.raises(AuthorizationError):
            await service.set_current_mission(
                admin_user.id,
                test_mission.id,
                regular_user,
            )


class TestUpdateUser:
    async def test_user_updates_own_display_name(
        self,
        db_session: AsyncSession,
        regular_user: User,
    ):
        service = UserService(db_session)
        updated = await service.update_user(
            regular_user.id,
            regular_user,
            display_name="New Name",
        )
        assert updated.display_name == "New Name"

    async def test_user_cannot_change_own_role(
        self,
        db_session: AsyncSession,
        regular_user: User,
    ):
        service = UserService(db_session)
        with pytest.raises(AuthorizationError):
            await service.update_user(
                regular_user.id,
                regular_user,
                system_role="admin",
            )

    async def test_admin_can_change_role(
        self,
        db_session: AsyncSession,
        admin_user: User,
        regular_user: User,
    ):
        service = UserService(db_session)
        updated = await service.update_user(
            regular_user.id,
            admin_user,
            system_role="admin",
        )
        assert updated.system_role == "admin"


class TestChangePassword:
    async def test_change_own_password(
        self,
        db_session: AsyncSession,
        regular_user: User,
    ):
        service = UserService(db_session)
        await service.change_password(
            regular_user.id,
            "user-password-123",
            "new-password-456",
            regular_user,
        )

        # Verify old password no longer works by checking the hash changed
        from sqlalchemy import select

        from modules.backend.core import security

        refreshed = (
            await db_session.execute(select(User).where(User.id == regular_user.id))
        ).scalar_one()
        assert security.verify_password("new-password-456", refreshed.hashed_password)

    async def test_wrong_old_password_fails(
        self,
        db_session: AsyncSession,
        regular_user: User,
    ):
        service = UserService(db_session)
        with pytest.raises(ValidationError, match="incorrect"):
            await service.change_password(
                regular_user.id,
                "wrong-old-pass",
                "new-pass",
                regular_user,
            )

    async def test_cannot_change_other_users_password(
        self,
        db_session: AsyncSession,
        regular_user: User,
        admin_user: User,
    ):
        service = UserService(db_session)
        with pytest.raises(AuthorizationError):
            await service.change_password(
                admin_user.id,
                "any",
                "any",
                regular_user,
            )


class TestDeactivateUser:
    async def test_admin_deactivates_user(
        self,
        db_session: AsyncSession,
        admin_user: User,
        regular_user: User,
    ):
        service = UserService(db_session)
        deactivated = await service.deactivate_user(regular_user.id, admin_user)
        assert deactivated.is_active is False

    async def test_user_cannot_deactivate(
        self,
        db_session: AsyncSession,
        regular_user: User,
        admin_user: User,
    ):
        service = UserService(db_session)
        with pytest.raises(AuthorizationError):
            await service.deactivate_user(admin_user.id, regular_user)

    async def test_cannot_deactivate_self(
        self,
        db_session: AsyncSession,
        admin_user: User,
    ):
        service = UserService(db_session)
        with pytest.raises(ValidationError):
            await service.deactivate_user(admin_user.id, admin_user)
