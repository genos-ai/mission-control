"""Session models — the transport primitive for persistent interaction context."""

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, JSON, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modules.backend.core.utils import utc_now
from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class SessionStatus(str, enum.Enum):
    """Session lifecycle states."""
    ACTIVE = "active"
    SUSPENDED = "suspended"       # Waiting for human/AI input or approval
    COMPLETED = "completed"
    EXPIRED = "expired"
    FAILED = "failed"


# Valid state transitions — terminal states have empty sets
VALID_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.ACTIVE: {
        SessionStatus.SUSPENDED,
        SessionStatus.COMPLETED,
        SessionStatus.FAILED,
        SessionStatus.EXPIRED,
    },
    SessionStatus.SUSPENDED: {
        SessionStatus.ACTIVE,
        SessionStatus.COMPLETED,
        SessionStatus.FAILED,
        SessionStatus.EXPIRED,
    },
    SessionStatus.COMPLETED: set(),
    SessionStatus.EXPIRED: set(),
    SessionStatus.FAILED: set(),
}


class Session(UUIDMixin, TimestampMixin, Base):
    """Persistent interaction context. Outlives any request, connection, or restart."""

    __tablename__ = "sessions"

    # Status
    status: Mapped[str] = mapped_column(
        Enum(SessionStatus, native_enum=False), nullable=False, default=SessionStatus.ACTIVE
    )

    # Identity
    user_id: Mapped[str | None] = mapped_column(PgUUID(as_uuid=False), nullable=True, index=True)
    mission_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False), nullable=True, index=True
    )  # Mission this session belongs to
    agent_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # Primary agent assigned

    # Context
    goal: Mapped[str | None] = mapped_column(
        String(2000), nullable=True
    )  # What this session is trying to achieve
    plan_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False), nullable=True
    )  # Active plan (Phase 5)
    session_metadata: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, default=dict
    )  # Extensible key-value pairs

    # Cost tracking
    total_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, default=0.0)
    cost_budget_usd: Mapped[float | None] = mapped_column(
        Numeric(12, 6), nullable=True
    )  # None = unlimited

    # Rolling summary — anchored compression for long sessions (Plan 57 Phase C)
    rolling_summary: Mapped[str] = mapped_column(
        Text, nullable=False, default=""
    )
    rolling_summary_anchor: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    rolling_summary_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    # Activity tracking
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )  # Auto-expire after inactivity

    # Relationships
    channels: Mapped[list["SessionChannel"]] = relationship(
        "SessionChannel", back_populates="session", lazy="selectin"
    )
    messages: Mapped[list["SessionMessage"]] = relationship(
        "SessionMessage", back_populates="session", lazy="noload"
    )

    __table_args__ = (
        Index("ix_sessions_user_status", "user_id", "status"),
        Index("ix_sessions_last_activity", "last_activity_at"),
        Index("ix_sessions_expires_at", "expires_at"),
    )

    @property
    def budget_remaining_usd(self) -> float | None:
        """Remaining budget, or None if no budget is set."""
        if self.cost_budget_usd is None:
            return None
        return max(0.0, self.cost_budget_usd - self.total_cost_usd)

    def __repr__(self) -> str:
        return f"<Session(id={self.id}, status={self.status})>"


class SessionChannel(UUIDMixin, Base):
    """Binds a session to a communication channel. One session, many channels."""

    __tablename__ = "session_channels"

    session_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False), ForeignKey("sessions.id"), nullable=False, index=True
    )
    channel_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # telegram, tui, web, cli, mcp, a2a
    channel_id: Mapped[str] = mapped_column(
        String(200), nullable=False
    )  # chat_id, connection_id, etc.
    bound_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationship
    session: Mapped["Session"] = relationship("Session", back_populates="channels")

    __table_args__ = (
        Index("ix_session_channels_session", "session_id", "is_active"),
        Index("ix_session_channels_channel", "channel_type", "channel_id"),
    )

    def __repr__(self) -> str:
        return f"<SessionChannel(session_id={self.session_id}, type={self.channel_type})>"


class SessionMessage(UUIDMixin, Base):
    """A single message in a session's conversation history.

    Persisted for the streaming mission control (Phase 3) and memory architecture.
    Not stored on the Session row — conversation history is always in this table.
    """

    __tablename__ = "session_messages"

    session_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False), ForeignKey("sessions.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # user, assistant, system, tool_call, tool_result
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sender_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # agent name or user ID

    # LLM metadata (populated for assistant messages)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)

    # Agent thinking (populated for assistant messages when thinking is enabled)
    thinking: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Tool correlation (populated for tool_call / tool_result messages)
    tool_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Streaming state — supports persist-first SSE (Plan 56 Phase A).
    # 'streaming' while the agent is generating, 'complete' when done,
    # 'failed' if the agent errored mid-stream.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="complete"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )

    # Relationship
    session: Mapped["Session"] = relationship("Session", back_populates="messages")

    __table_args__ = (
        Index("ix_session_messages_session_created", "session_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<SessionMessage(session_id={self.session_id}, role={self.role})>"
