"""
Persisted mission events.

Append-only log of narrative-relevant events for a mission. Written
by SessionEventBus.publish() for event types in the persist set.
Read by the /narrative endpoint for historical timeline display.
"""

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class MissionEvent(UUIDMixin, TimestampMixin, Base):
    """A single persisted event in a mission's timeline."""

    __tablename__ = "mission_events"

    mission_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    timestamp: Mapped[str] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        default="",
    )
    data: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    def __repr__(self) -> str:
        return f"<MissionEvent(mission={self.mission_id[:8]}, " f"type={self.event_type!r})>"
