"""
Revoked Session Repository.

Data access layer for RevokedSession model.
"""

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from modules.backend.core.utils import utc_now
from modules.backend.models.revoked_session import RevokedSession
from modules.backend.repositories.base import BaseRepository


class RevokedSessionRepository(BaseRepository[RevokedSession]):
    """Repository for ended sessions."""

    model = RevokedSession

    async def revoke(self, session_id: str, user_id: str, expires_at: datetime) -> None:
        """Record a session as ended. Revoking an already revoked session changes nothing."""
        stmt = (
            pg_insert(RevokedSession)
            .values(id=session_id, user_id=user_id, revoked_at=utc_now(), expires_at=expires_at)
            .on_conflict_do_nothing(index_elements=[RevokedSession.id])
        )
        await self.session.execute(stmt)

    async def is_revoked(self, session_id: str) -> bool:
        """Whether the session was ended by logout."""
        result = await self.session.execute(
            select(RevokedSession.id).where(RevokedSession.id == session_id)
        )
        return result.scalar_one_or_none() is not None

    async def delete_expired(self) -> int:
        """Delete rows whose tokens have all expired. Returns the number deleted."""
        result = await self.session.execute(
            delete(RevokedSession).where(RevokedSession.expires_at < utc_now())
        )
        return result.rowcount
