"""
User Service.

Handles user CRUD, authorization enforcement, and password management.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core import security
from modules.backend.core.exceptions import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from modules.backend.models.user import User
from modules.backend.repositories.api_key import ApiKeyRepository
from modules.backend.repositories.user import UserRepository
from modules.backend.services.base import BaseService


class UserService(BaseService):
    """User management service with authorization enforcement."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.user_repo = UserRepository(session)
        self.api_key_repo = ApiKeyRepository(session)

    @staticmethod
    @asynccontextmanager
    async def factory() -> AsyncGenerator["UserService", None]:
        """Create a UserService with its own DB session."""
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            yield UserService(db)
            await db.commit()

    async def create_user(
        self,
        email: str,
        display_name: str,
        password: str | None,
        system_role: str,
        is_service_account: bool,
        requesting_user: User,
    ) -> User:
        """Create a new user. Admin only."""
        if not requesting_user.has_role("admin"):
            raise AuthorizationError("Only admins can create users")

        existing = await self.user_repo.get_by_email(email)
        if existing is not None:
            raise ConflictError("User could not be created")

        hashed_password = None
        if password:
            hashed_password = await asyncio.to_thread(security.hash_password, password)

        user = await self.user_repo.create(
            email=email,
            display_name=display_name,
            hashed_password=hashed_password,
            system_role=system_role,
            is_service_account=is_service_account,
        )

        self._log_operation(
            "user_created",
            user_id=user.id,
            email=email,
            requesting_user_id=requesting_user.id,
        )

        return user

    async def get_user(self, user_id: str, requesting_user: User) -> User:
        """Get a user by ID. Self or admin."""
        self._require_owner_or_admin(user_id, requesting_user, "view other users")
        return await self.user_repo.get_by_id(user_id)

    async def list_users(
        self,
        requesting_user: User,
        limit: int = 50,
        offset: int = 0,
    ) -> list[User]:
        """List all users. Admin only."""
        if not requesting_user.has_role("admin"):
            raise AuthorizationError("Only admins can list users")
        return await self.user_repo.list_all(limit, offset)

    async def update_user(
        self,
        user_id: str,
        requesting_user: User,
        display_name: str | None = None,
        system_role: str | None = None,
        is_active: bool | None = None,
    ) -> User:
        """Update a user. Admin can update any field; non-admin can only update own display_name."""
        is_admin = requesting_user.has_role("admin")
        is_self = requesting_user.id == user_id

        if not is_admin and not is_self:
            raise AuthorizationError("Cannot update other users")

        if not is_admin and (system_role is not None or is_active is not None):
            raise AuthorizationError("Only admins can change role or active status")

        kwargs = {}
        if display_name is not None:
            kwargs["display_name"] = display_name
        if system_role is not None:
            kwargs["system_role"] = system_role
        if is_active is not None:
            kwargs["is_active"] = is_active

        if not kwargs:
            return await self.user_repo.get_by_id(user_id)

        user = await self.user_repo.update(user_id, **kwargs)

        self._log_operation(
            "user_updated",
            user_id=user_id,
            fields=list(kwargs.keys()),
            requesting_user_id=requesting_user.id,
        )

        return user

    async def deactivate_user(
        self, user_id: str, requesting_user: User,
    ) -> User:
        """Deactivate a user and revoke all their API keys. Admin only."""
        if not requesting_user.has_role("admin"):
            raise AuthorizationError("Only admins can deactivate users")

        if requesting_user.id == user_id:
            raise ValidationError("Cannot deactivate own account")

        user = await self.user_repo.update(user_id, is_active=False)
        revoked_count = await self.api_key_repo.revoke_all_by_user(user_id)

        self._log_operation(
            "user_deactivated",
            user_id=user_id,
            keys_revoked=revoked_count,
            requesting_user_id=requesting_user.id,
        )

        return user

    async def change_password(
        self,
        user_id: str,
        old_password: str,
        new_password: str,
        requesting_user: User,
    ) -> None:
        """Change own password. Self only."""
        if requesting_user.id != user_id:
            raise AuthorizationError("Can only change own password")

        user = await self.user_repo.get_by_id(user_id)

        if not user.hashed_password:
            raise ValidationError("Password login not configured for this account")

        valid = await asyncio.to_thread(
            security.verify_password, old_password, user.hashed_password,
        )
        if not valid:
            raise ValidationError("Current password is incorrect")

        new_hash = await asyncio.to_thread(security.hash_password, new_password)
        await self.user_repo.update(user_id, hashed_password=new_hash)

        self._log_operation("password_changed", user_id=user_id)

    async def admin_reset_password(
        self,
        user_id: str,
        new_password: str,
        requesting_user: User,
    ) -> None:
        """Admin reset of another user's password."""
        if not requesting_user.has_role("admin"):
            raise AuthorizationError("Only admins can reset passwords")

        new_hash = await asyncio.to_thread(security.hash_password, new_password)
        await self.user_repo.update(user_id, hashed_password=new_hash)

        self._log_operation(
            "password_reset_by_admin",
            user_id=user_id,
            requesting_user_id=requesting_user.id,
        )

    async def set_current_mission(
        self,
        user_id: str,
        mission_id: str | None,
        requesting_user: User,
    ) -> User:
        """Set or clear the user's current mission.

        Self or admin only. Validates mission exists and is active.
        Pass mission_id=None to clear.
        """
        self._require_owner_or_admin(user_id, requesting_user, "set current mission")

        if mission_id is not None:
            from modules.backend.repositories.mission import MissionRepository

            mission_repo = MissionRepository(self._session)
            mission = await mission_repo.get_by_id_or_none(mission_id)
            if mission is None:
                raise NotFoundError("Mission not found")
            if mission.status != "active":
                raise ValidationError("Cannot select a non-active mission")

        user = await self.user_repo.update(user_id, current_mission_id=mission_id)

        self._log_operation(
            "current_mission_set",
            user_id=user_id,
            mission_id=mission_id,
        )

        return user
