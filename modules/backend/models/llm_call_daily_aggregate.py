"""Daily LLM ledger aggregates (Plan 88 contracts 3.1.11).

One row per (UTC day, mission, agent, model, provider). Written only by the
retention rollup (88.5.3); ``BudgetService`` adds these sums to the raw
``llm_calls`` sums for monthly and lifetime spend. No UUIDMixin: a BIGSERIAL
key plus ``created_at``.
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base


class LlmCallDailyAggregate(Base):
    """Rolled-up LLM spend and tokens for one day and attribution key."""

    __tablename__ = "llm_call_daily_aggregates"
    __table_args__ = (
        UniqueConstraint(
            "day",
            "mission_id",
            "agent_name",
            "model",
            "provider",
            name="uq_llm_daily",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_llm_daily_mission_day", "mission_id", "day"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    mission_id: Mapped[str | None] = mapped_column(PgUUID(as_uuid=False), nullable=True)
    agent_name: Mapped[str] = mapped_column(String(200), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    call_count: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cache_read_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cache_write_5m_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cache_write_1h_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    thinking_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Numeric(14, 6, asdecimal=False), nullable=False)
