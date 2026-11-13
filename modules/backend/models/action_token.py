"""
Action Token Model (Plan 88, contract 3.1.10).

Single-use, expiring tokens carried by a channel button (gate Approve and
Reject) or a link code. Only the SHA-256 hex of the raw token is stored.
consumed_ref (the Telegram callback_query.id) is UNIQUE, which blocks replay.
"""

import enum
from datetime import datetime

from sqlalchemy import CHAR, CheckConstraint, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin
from modules.backend.models.user_channel_identity import ChannelKind

# consumed_action written by ActionTokenRepository.consume_siblings for the other
# tokens of a gate once one of them is used.
SUPERSEDED_ACTION = "SUPERSEDED"


class ActionTokenPurpose(str, enum.Enum):
    """What a token authorises."""

    GATE_DECISION = "gate_decision"
    CHANNEL_LINK = "channel_link"


class ActionToken(UUIDMixin, TimestampMixin, Base):
    """A single-use token bound to one user and one channel."""

    __tablename__ = "action_tokens"
    __table_args__ = (
        CheckConstraint(
            "(purpose = 'GATE_DECISION') = (gate_request_id IS NOT NULL)",
            name="ck_action_tokens_gate_purpose",
        ),
    )

    purpose: Mapped[ActionTokenPurpose] = mapped_column(
        Enum(ActionTokenPurpose, native_enum=False, length=32),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(
        CHAR(64),
        nullable=False,
        unique=True,
        comment="SHA-256 hex of the raw token; the raw token is never stored.",
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
    gate_request_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("gate_requests.id", ondelete="CASCADE"),
        nullable=True,
    )
    channel_message_ref: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment='"{chat_id}:{message_id}" so the message can be edited after the decision.',
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    consumed_ref: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        unique=True,
        comment="Telegram callback_query.id; UNIQUE gives replay protection.",
    )

    def __repr__(self) -> str:
        return (
            f"<ActionToken(id={self.id}, purpose={self.purpose}, user_id={self.user_id}, "
            f"consumed={self.consumed_at is not None})>"
        )
