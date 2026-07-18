"""
User Repository.

Data access layer for User model.
"""

from sqlalchemy import select

from modules.backend.core.utils import utc_now
from modules.backend.models.user import User
from modules.backend.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Repository for User CRUD and queries."""

    model = User

    async def get_by_email(self, email: str) -> User | None:
        """Get a user by email address."""
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_active(self, user_id: str) -> User | None:
        """Get a user by ID, only if active."""
        result = await self.session.execute(
            select(User).where(User.id == user_id, User.is_active == True)  # noqa: E712
        )
        return result.scalar_one_or_none()

    async def list_all(
        self,
        limit: int,
        offset: int,
        role_filter: str | None = None,
    ) -> list[User]:
        """List users with optional role filter."""
        stmt = select(User)
        if role_filter:
            stmt = stmt.where(User.system_role == role_filter)
        stmt = stmt.order_by(User.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_last_login(self, user_id: str) -> None:
        """Update the last_login_at timestamp."""
        user = await self.get_by_id(user_id)
        user.last_login_at = utc_now()
        await self.session.flush()
        await self.session.refresh(user)
