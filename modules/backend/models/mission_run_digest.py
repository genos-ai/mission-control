"""
Mission Run Digest Model (Plan 88, contract 3.1.7).

One digest per run that reached RUNNING, kept permanently. Written from
Phase 3; the table exists from plan88_002.
"""

import enum

from sqlalchemy import Enum, ForeignKey, Index, Integer, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class DigestGenerator(str, enum.Enum):
    """Who wrote the digest."""

    AGENT = "agent"
    DETERMINISTIC = "deterministic"


class MissionRunDigest(UUIDMixin, TimestampMixin, Base):
    """Compact record of what a run did, read by later runs."""

    __tablename__ = "mission_run_digests"
    __table_args__ = (
        Index("ix_mission_run_digests_mission_created", "mission_id", text("created_at DESC")),
    )

    mission_run_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("mission_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    mission_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    generator: Mapped[DigestGenerator] = mapped_column(
        Enum(DigestGenerator, native_enum=False, length=32),
        nullable=False,
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    outcomes: Mapped[list] = mapped_column(JSONB, nullable=False)
    decisions: Mapped[list] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False
    )
    open_items: Mapped[list] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False
    )
    context_changes: Mapped[list] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False
    )
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False)
    generation_cost_usd: Mapped[float] = mapped_column(
        Numeric(12, 6, asdecimal=False),
        default=0.0,
        server_default="0",
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<MissionRunDigest(id={self.id}, mission_run_id={self.mission_run_id}, "
            f"generator={self.generator})>"
        )
