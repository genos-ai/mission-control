"""
Human Input Request Model.

Tracks pending, completed, and timed-out human input requests created
by HumanInputWorkflow nodes. Each row maps 1:1 to a Temporal
HumanInputWorkflow instance via temporal_workflow_id for Signal routing.
"""

import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class HumanInputRequestStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class HumanInputRequest(UUIDMixin, TimestampMixin, Base):
    """A durable human input request linked to a Temporal workflow."""

    __tablename__ = "human_input_requests"

    workflow_run_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    mission_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("missions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    session_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    temporal_workflow_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Temporal workflow ID for Signal routing",
    )
    prompt_message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(
        String(50),
        default="telegram",
        nullable=False,
    )
    choices_json: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        Enum(HumanInputRequestStatus, native_enum=False),
        default=HumanInputRequestStatus.PENDING,
        nullable=False,
        index=True,
    )
    response: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    responder_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    timeout_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<HumanInputRequest(id={self.id}, step={self.step_id!r}, " f"status={self.status})>"
