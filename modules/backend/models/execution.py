"""
Execution Model.

An execution is a discrete objective with bounded scope. When created by a
Workflow, each execution has its own roster, complexity tier, and upstream
context. The Execution instantiates Mission Control with these parameters.

Executions created by Workflows have a workflow_run_id linking them to
their parent WorkflowRun. Ad-hoc executions (from direct API calls) have
no workflow_run_id.
"""

import enum

from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class ExecutionEnvironment(str, enum.Enum):
    """Execution environment mode.

    Graduated isolation hierarchy:
        local     — in-process, FileScope isolation only (default)
        worktree  — git branch + separate working directory (future)
        container — Docker namespace isolation with full runtime
    """

    LOCAL = "local"
    WORKTREE = "worktree"
    CONTAINER = "container"


class ExecutionState(str, enum.Enum):
    """Execution lifecycle status.

    Transitions:
        pending -> running (execution started)
        running -> completed (all tasks done)
        running -> failed (unrecoverable error)
        running -> cancelled (user cancelled)
        pending -> cancelled (cancelled before start)
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


VALID_EXECUTION_TRANSITIONS: dict[ExecutionState, set[ExecutionState]] = {
    ExecutionState.PENDING: {ExecutionState.RUNNING, ExecutionState.CANCELLED},
    ExecutionState.RUNNING: {
        ExecutionState.COMPLETED,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
    },
    ExecutionState.COMPLETED: set(),
    ExecutionState.FAILED: set(),
    ExecutionState.CANCELLED: set(),
}


class WorkflowRunState(str, enum.Enum):
    """Workflow run lifecycle status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowRun(UUIDMixin, TimestampMixin, Base):
    """A single execution of a workflow."""

    __tablename__ = "workflow_runs"

    workflow_name: Mapped[str] = mapped_column(
        String(200), nullable=False, index=True,
    )
    workflow_version: Mapped[int] = mapped_column(
        Integer, nullable=False,
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
    session_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False), nullable=False, index=True,
    )
    trigger_type: Mapped[str] = mapped_column(
        String(50), default="on_demand", nullable=False,
    )
    triggered_by: Mapped[str] = mapped_column(
        String(200), nullable=False,
    )
    context: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False,
    )
    total_cost_usd: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False,
    )
    budget_usd: Mapped[float | None] = mapped_column(
        Float, nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
    )
    error_data: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
    )
    result_summary: Mapped[str | None] = mapped_column(
        Text, nullable=True,
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


class Execution(UUIDMixin, TimestampMixin, Base):
    """A runtime execution — a discrete objective with bounded scope."""

    __tablename__ = "executions"

    workflow_run_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False), nullable=True, index=True,
    )
    workflow_step_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
    )
    mission_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("missions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    objective: Mapped[str] = mapped_column(
        Text, nullable=False,
    )
    roster_ref: Mapped[str] = mapped_column(
        String(100), default="default", nullable=False,
    )
    complexity_tier: Mapped[str] = mapped_column(
        String(20), default="simple", nullable=False,
    )
    status: Mapped[str] = mapped_column(
        Enum(ExecutionState, native_enum=False),
        default=ExecutionState.PENDING,
        nullable=False,
        index=True,
    )
    session_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False), nullable=False, index=True,
    )
    trigger_type: Mapped[str] = mapped_column(
        String(50), default="on_demand", nullable=False,
    )
    triggered_by: Mapped[str] = mapped_column(
        String(200), nullable=False,
    )
    upstream_context: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False,
    )
    context: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False,
    )
    total_cost_usd: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False,
    )
    cost_ceiling_usd: Mapped[float | None] = mapped_column(
        Float, nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
    )
    error_data: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
    )
    execution_outcome: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
    )
    result_summary: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    execution_environment: Mapped[str] = mapped_column(
        String(20), default="local", nullable=False, server_default="local",
        comment="Execution environment: local, worktree, container",
    )

    def __repr__(self) -> str:
        return (
            f"<Execution(id={self.id}, objective={self.objective[:50]!r}, "
            f"status={self.status}, roster={self.roster_ref})>"
        )
