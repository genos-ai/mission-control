"""
Workflow Run Model.

A WorkflowRun tracks a single execution of a workflow definition.
It owns zero-or-more step executions (linked via execution_records).
"""

import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class WorkflowRunState(str, enum.Enum):
    """Workflow run lifecycle status."""

    PENDING = "pending"
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowRun(UUIDMixin, TimestampMixin, Base):
    """A single execution of a workflow."""

    __tablename__ = "workflow_runs"

    workflow_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        index=True,
    )
    workflow_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    mission_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("missions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        Enum(WorkflowRunState, native_enum=False),
        default=WorkflowRunState.PENDING,
        nullable=False,
        index=True,
    )
    session_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    trigger_type: Mapped[str] = mapped_column(
        String(50),
        default="on_demand",
        nullable=False,
    )
    triggered_by: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    context: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    total_cost_usd: Mapped[float] = mapped_column(
        Numeric(12, 6, asdecimal=False),
        default=0.0,
        nullable=False,
    )
    budget_usd: Mapped[float | None] = mapped_column(
        Numeric(12, 6, asdecimal=False),
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_data: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )
    result_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    execution_record_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("execution_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Parent ExecutionRecord — makes workflow runs visible in Runs tab",
    )

    def __repr__(self) -> str:
        return (
            f"<WorkflowRun(id={self.id}, workflow={self.workflow_name!r}, "
            f"status={self.status})>"
        )
