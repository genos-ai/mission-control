"""Time-bounded per-model pricing for cost attribution (Plan 60).

Each row is valid from effective_from to effective_to. When Anthropic
changes prices, insert a new row with the old row's effective_to set
to the change date. Old rows stay for historical cost accuracy.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base

# Sentinel for "current" pricing — avoids PostgreSQL-specific 'infinity'.
FAR_FUTURE = datetime(9999, 12, 31, tzinfo=timezone.utc)


class ModelPricing(Base):
    """Time-bounded pricing for a specific model."""

    __tablename__ = "model_pricing"

    model: Mapped[str] = mapped_column(
        String(100), primary_key=True,
    )
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True,
    )
    effective_to: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=FAR_FUTURE,
    )
    price_per_mtok_input: Mapped[float] = mapped_column(
        Float, nullable=False,
    )
    price_per_mtok_output: Mapped[float] = mapped_column(
        Float, nullable=False,
    )
    price_per_mtok_cache_write_5m: Mapped[float | None] = mapped_column(
        Float, nullable=True,
    )
    price_per_mtok_cache_write_1h: Mapped[float | None] = mapped_column(
        Float, nullable=True,
    )
    price_per_mtok_cache_read: Mapped[float | None] = mapped_column(
        Float, nullable=True,
    )
