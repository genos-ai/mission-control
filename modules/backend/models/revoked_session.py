"""
Revoked Session Model.

A login mints a session id (the `sid` claim) that every token refreshed from it
carries forward. Logout stores that id here, and token verification rejects it.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.core.utils import utc_now
from modules.backend.models.base import Base, UUIDMixin


class RevokedSession(UUIDMixin, Base):
    """A session that was ended by logout. `id` is the session id carried in the JWTs."""

    __tablename__ = "revoked_sessions"

    user_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    # After this instant every token minted from the session has expired, so the row
    # can no longer change an outcome and is safe to delete.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
