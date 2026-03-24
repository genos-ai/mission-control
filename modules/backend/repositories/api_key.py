"""
API Key Repository.

Data access layer for ApiKey model.
"""

from sqlalchemy import select, update
from sqlalchemy.orm import joinedload

from modules.backend.core.utils import utc_now
from modules.backend.models.api_key import ApiKey
from modules.backend.repositories.base import BaseRepository


class ApiKeyRepository(BaseRepository[ApiKey]):
    """Repository for ApiKey CRUD and queries."""

    model = ApiKey

    async def get_by_prefix(self, prefix: str) -> list[ApiKey]:
        """Get active, non-revoked, non-expired keys matching a prefix.

        Eagerly loads the .user relationship to avoid N+1 queries
        during bcrypt verification.
        """
        now = utc_now()
        stmt = (
            select(ApiKey)
            .options(joinedload(ApiKey.user))
            .where(
                ApiKey.key_prefix == prefix,
                ApiKey.revoked_at.is_(None),
                (ApiKey.expires_at.is_(None)) | (ApiKey.expires_at > now),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def list_by_user(self, user_id: str) -> list[ApiKey]:
        """List all keys (including revoked) for a user."""
        stmt = (
            select(ApiKey)
            .where(ApiKey.user_id == user_id)
            .order_by(ApiKey.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def revoke(self, key_id: str) -> ApiKey:
        """Revoke a key by setting revoked_at."""
        key = await self.get_by_id(key_id)
        key.revoked_at = utc_now()
        await self.session.flush()
        await self.session.refresh(key)
        return key

    async def revoke_all_by_user(self, user_id: str) -> int:
        """Revoke all active keys for a user. Returns count of revoked keys."""
        now = utc_now()
        stmt = (
            update(ApiKey)
            .where(
                ApiKey.user_id == user_id,
                ApiKey.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount

    async def update_last_used(self, key_id: str) -> None:
        """Update the last_used_at timestamp."""
        stmt = (
            update(ApiKey)
            .where(ApiKey.id == key_id)
            .values(last_used_at=utc_now())
        )
        await self.session.execute(stmt)
        await self.session.flush()
