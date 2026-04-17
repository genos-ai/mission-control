"""
Mission Intent Model.

Event-sourced intent revisions. Append-only — each row is a revision.
Current intent = most recent row for a mission_id.
"""

import enum

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class IntentSource(str, enum.Enum):
    """How the intent revision was captured."""

    USER_CHAT = "user_chat"
    USER_CLI = "user_cli"
    DIRECTOR_INFERRED = "director_inferred"
    SYSTEM = "system"


class MissionIntent(UUIDMixin, Base):
    """A single intent revision for a mission.

    The table is append-only. Current intent is the most recent row
    (ORDER BY created_at DESC LIMIT 1) for a given mission_id.

    The ``scope`` field captures what's in/out of scope as a structured
    JSON object: ``{"in": ["auth refactor", "tests"], "out": ["frontend"]}``.
    """

    __tablename__ = "mission_intents"

    mission_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    intent: Mapped[str] = mapped_column(
        Text, nullable=False,
    )
    intent_summary: Mapped[str] = mapped_column(
        Text, nullable=False,
    )
    scope: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False,
    )
    source: Mapped[str] = mapped_column(
        String(32), nullable=False,
    )
    revised_from: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("mission_intents.id"),
        nullable=True,
    )
    reason: Mapped[str] = mapped_column(
        Text, nullable=False,
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
    )
    session_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # created_at from TimestampMixin — no updated_at needed (append-only)

    def __repr__(self) -> str:
        return (
            f"<MissionIntent(mission={self.mission_id}, "
            f"source={self.source}, summary={self.intent_summary!r:.40})>"
        )


# Override TimestampMixin's updated_at — intents are append-only
MissionIntent.updated_at = mapped_column(  # type: ignore[assignment]
    nullable=True, default=None, use_existing_column=True,
)
