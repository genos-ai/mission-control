"""
Mission Plan Model (Plan 42, updated by Plan 72).

Persistent, long-lived plan per mission. A MissionPlan is a metadata
container — tasks live in the `tasks` table as first-class entities.

Plans survive runs — a single MissionPlan can be dispatched multiple times
with different subsets of approved tasks, and task state persists across
those runs.

Plan 72 changes:
  - Removed task_plan_json (tasks are in DB)
  - Removed PlanTaskState (merged into Task)
  - Removed PlanTaskStatus (moved to models/task.py as TaskStatus)
  - Added plan-level metadata: summary, estimated_cost_usd,
    estimated_duration, execution_hints_json
"""

import enum

from sqlalchemy import (
    Enum,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class MissionPlanStatus(str, enum.Enum):
    """Lifecycle status of a mission plan.

    ACTIVE    — the default. Plan accepts refinements, approvals, dispatch.
    PAUSED    — dispatch is blocked. Used to temporarily halt autonomous
                runs without destroying in-flight state.
    COMPLETED — user or agent declared the plan complete. No more dispatch.
                Kept for history; can be re-activated.
    ARCHIVED  — terminal. Read-only. Cleaned up by retention policy.
    """

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


# Gate modes — mirrors config/settings/gate.yaml values verbatim so
# MissionPlanService can pass this string straight to create_gate(mode_override=...).
# Plan 42 §10.4: autonomy is gate mode lifted to plan level.
VALID_GATE_MODES: frozenset[str] = frozenset({
    "off",
    "interactive",
    "ai_assisted",
    "autonomous",
})


class MissionPlan(UUIDMixin, TimestampMixin, Base):
    """A persistent, long-lived plan for a single mission.

    One row per mission (enforced by unique constraint). Tasks live in the
    `tasks` table as first-class entities (Plan 72). This model holds
    plan-level metadata, gate configuration, and budget tracking.
    """

    __tablename__ = "mission_plans"

    mission_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # ── Plan-level metadata (Plan 72) ──────────────────────────────────────

    summary: Mapped[str] = mapped_column(
        Text,
        default="",
        server_default="",
        nullable=False,
        comment="Plan summary from TaskPlan.summary",
    )

    estimated_cost_usd: Mapped[float] = mapped_column(
        Numeric(12, 6, asdecimal=False),
        default=0.0,
        server_default="0.0",
        nullable=False,
        comment="Estimated total cost from planning agent",
    )

    estimated_duration: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        comment="Estimated duration in seconds from planning agent",
    )

    execution_hints_json: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        server_default="{}",
        nullable=False,
        comment='{"min_success_threshold": 1.0, "critical_path": []}',
    )

    # ── Gate configuration ─────────────────────────────────────────────────

    gate_mode: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment=(
            "Autonomy mode: off, interactive, ai_assisted, autonomous. "
            "Inherits from missions.gate_mode at creation."
        ),
    )

    status: Mapped[str] = mapped_column(
        Enum(MissionPlanStatus, native_enum=False),
        default=MissionPlanStatus.ACTIVE,
        server_default=MissionPlanStatus.ACTIVE.name,
        nullable=False,
    )

    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
        comment="Bumped on each refinement.",
    )

    # ── Budget tracking ────────────────────────────────────────────────────

    budget_usd_ceiling: Mapped[float | None] = mapped_column(
        Numeric(12, 6, asdecimal=False),
        nullable=True,
        comment="Cumulative cap across all runs from this plan",
    )

    total_spent_usd: Mapped[float] = mapped_column(
        Numeric(12, 6, asdecimal=False),
        default=0.0,
        server_default="0.0",
        nullable=False,
        comment="Running total across all dispatched executions",
    )

    veto_window_sec: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment=(
            "For ai_assisted mode: seconds the user has to veto an "
            "auto-approved task before it queues. NULL = no window."
        ),
    )

    # ── Supervisor autonomy loop (Plan 51 Phase C) ─────────────────────────

    supervisor_iteration_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        comment=(
            "How many times the post-run supervisor has been invoked. "
            "Resets on user-initiated refine_plan or new plan creation."
        ),
    )

    max_supervisor_iterations: Mapped[int] = mapped_column(
        Integer,
        default=20,
        server_default="20",
        nullable=False,
        comment=(
            "Circuit breaker: if supervisor_iteration_count >= this, "
            "the supervisor short-circuits to ESCALATE without "
            "evaluating rules or calling Haiku."
        ),
    )

    # ── Relationships ──────────────────────────────────────────────────────

    tasks: Mapped[list["Task"]] = relationship(  # noqa: F821
        "Task",
        back_populates="plan",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Task.created_at",
    )

    def __repr__(self) -> str:
        return (
            f"<MissionPlan(id={self.id}, mission_id={self.mission_id}, "
            f"version={self.version}, status={self.status})>"
        )
