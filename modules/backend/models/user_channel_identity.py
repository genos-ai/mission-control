"""
User Channel Identity Model (Plan 88, contract 3.1.10).

Binds a platform user to an external channel account (a Telegram user id).
Linking is two-step: redeem inserts the row with verified_at NULL, and the
user confirms it from the web or mc. Only verified rows resolve for delivery
or for decisions.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class ChannelKind(str, enum.Enum):
    """External channels a user can link and receive notifications on."""

    TELEGRAM = "telegram"


class UserChannelIdentity(UUIDMixin, TimestampMixin, Base):
    """A user's account on an external channel."""

    __tablename__ = "user_channel_identities"
    __table_args__ = (
        UniqueConstraint("channel", "external_id", name="uq_channel_identity_external"),
        UniqueConstraint("user_id", "channel", name="uq_channel_identity_user"),
    )

    user_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel: Mapped[ChannelKind] = mapped_column(
        Enum(ChannelKind, native_enum=False, length=32),
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Telegram from_user.id as a decimal string.",
    )
    external_username: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="Telegram @username at redeem time, shown for confirmation.",
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="NULL until the user confirms the link.",
    )

    def __repr__(self) -> str:
        return (
            f"<UserChannelIdentity(id={self.id}, user_id={self.user_id}, "
            f"channel={self.channel}, verified={self.verified_at is not None})>"
        )
