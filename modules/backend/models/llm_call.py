"""Per-request LLM call tracking for cost attribution (Plan 60).

Each row represents a single API call to an LLM provider. Agent runs
that involve tool loops produce multiple rows. This is the source of
truth for token economics — all dashboard queries read from here.
"""

from sqlalchemy import Float, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class LlmCall(UUIDMixin, TimestampMixin, Base):
    """A single LLM API call with full token breakdown."""

    __tablename__ = "llm_calls"

    # Context
    session_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        nullable=True,
        index=True,
    )
    mission_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        nullable=True,
        index=True,
    )
    execution_record_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        nullable=True,
    )
    agent_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        index=True,
    )
    agent_role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    # Model
    model: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    # Token breakdown
    input_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Uncached input tokens only",
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    cache_read_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Tokens served from cache (0.1x input price)",
    )
    cache_write_5m_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Tokens written to 5-minute cache (1.25x input price)",
    )
    cache_write_1h_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Tokens written to 1-hour cache (2x input price)",
    )
    thinking_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Extended thinking tokens (billed at output rate)",
    )

    # Cost
    cost_usd: Mapped[float] = mapped_column(
        Numeric(12, 6, asdecimal=False),
        default=0.0,
        nullable=False,
    )

    # Performance
    latency_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    request_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Anthropic request ID for debugging",
    )

    # Tool context
    tool_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Number of tools in this request's schema",
    )
    tool_schema_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Estimated tokens consumed by tool definitions",
    )


# Timeline queries filter by created_at — TimestampMixin doesn't add an index.
Index("ix_llm_calls_created_at", LlmCall.created_at)
