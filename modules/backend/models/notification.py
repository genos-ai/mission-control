"""
Notification Models (Plan 88, contract 3.1.10).

MissionNotificationRecipient: who receives which kinds for a mission, on
which channel. kinds is a JSONB list of NotificationKind values (lowercase).

NotificationDelivery: one row per (kind, subject, recipient, channel), keyed
by dedupe_key, for audit and idempotency. error is always written through
redact_secrets.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin
from modules.backend.models.user_channel_identity import ChannelKind


class NotificationKind(str, enum.Enum):
    """Events a recipient can subscribe to."""

    RUN_SUCCEEDED = "run_succeeded"
    RUN_FAILED = "run_failed"
    GATE_WAITING = "gate_waiting"
    GATE_ESCALATED = "gate_escalated"
    GATE_TIMEOUT_PAUSED = "gate_timeout_paused"
    BUDGET_PAUSED = "budget_paused"
    RUN_SKIPPED = "run_skipped"
    RUN_MISSED = "run_missed"


class NotificationDeliveryStatus(str, enum.Enum):
    """Outcome of one delivery attempt."""

    SENT = "sent"
    FAILED = "failed"
    SKIPPED_NO_IDENTITY = "skipped_no_identity"
    SKIPPED_DISABLED = "skipped_disabled"


class MissionNotificationRecipient(UUIDMixin, TimestampMixin, Base):
    """A user subscribed to a mission's notifications on one channel."""

    __tablename__ = "mission_notification_recipients"
    __table_args__ = (UniqueConstraint("mission_id", "user_id", "channel", name="uq_recipient"),)

    mission_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
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
    kinds: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        comment="NotificationKind values (lowercase).",
    )

    def __repr__(self) -> str:
        return (
            f"<MissionNotificationRecipient(id={self.id}, mission_id={self.mission_id}, "
            f"user_id={self.user_id}, channel={self.channel})>"
        )


class NotificationDelivery(UUIDMixin, TimestampMixin, Base):
    """Audit and idempotency record for one notification to one recipient."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        Index("ix_notification_deliveries_mission_created", "mission_id", "created_at"),
    )

    mission_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
    )
    mission_run_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("mission_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    kind: Mapped[NotificationKind] = mapped_column(
        Enum(NotificationKind, native_enum=False, length=32),
        nullable=False,
    )
    recipient_user_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel: Mapped[ChannelKind] = mapped_column(
        Enum(ChannelKind, native_enum=False, length=32),
        nullable=False,
    )
    dedupe_key: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        unique=True,
        comment="{kind_value}:{subject_id}:{recipient_user_id}:{channel_value}",
    )
    status: Mapped[NotificationDeliveryStatus] = mapped_column(
        Enum(NotificationDeliveryStatus, native_enum=False, length=32),
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    provider_message_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Always written through redact_secrets."
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<NotificationDelivery(id={self.id}, kind={self.kind}, "
            f"recipient_user_id={self.recipient_user_id}, status={self.status})>"
        )
