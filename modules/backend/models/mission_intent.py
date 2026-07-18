"""
Mission Intent Model.

Event-sourced intent revisions. Append-only — each row is a revision.
Current intent = most recent row for a mission_id.
"""

import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.core.utils import utc_now
from modules.backend.models.base import Base, UUIDMixin


class IntentSource(str, enum.Enum):
    """How the intent revision was captured."""

    USER_CHAT = "user_chat"
    USER_CLI = "user_cli"
    DIRECTOR_INFERRED = "director_inferred"
    SYSTEM = "system"


class MissionIntent(UUIDMixin, Base):
    """A single intent revision for a mission.

    Append-only — does not inherit TimestampMixin (no updated_at needed).
    Current intent is the most recent row (ORDER BY created_at DESC LIMIT 1).

    The ``scope`` field captures what's in/out of scope as a structured
    JSON object: ``{"in": ["auth refactor", "tests"], "out": ["frontend"]}``.
    """

    __tablename__ = "mission_intents"

    mission_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    intent: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    intent_summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    scope: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    revised_from: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("mission_intents.id"),
        nullable=True,
    )
    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    session_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    def __repr__(self) -> str:
        return (
            f"<MissionIntent(mission={self.mission_id}, "
            f"source={self.source}, summary={self.intent_summary!r:.40})>"
        )
