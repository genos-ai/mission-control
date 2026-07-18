"""
API Key Model.

Per-user, named, revocable API keys with optional expiry.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modules.backend.core.utils import utc_now
from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class ApiKey(UUIDMixin, TimestampMixin, Base):
    """An API key belonging to a user."""

    __tablename__ = "api_keys"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_api_keys_user_name"),)

    user_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    key_prefix: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        index=True,
    )
    hashed_key: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    scopes: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="api_keys",
    )

    @property
    def is_active(self) -> bool:
        """Return True if this key is not revoked and not expired."""
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and self.expires_at <= utc_now():
            return False
        return True

    def __repr__(self) -> str:
        return f"<ApiKey(id={self.id}, name={self.name!r}, " f"prefix={self.key_prefix})>"
