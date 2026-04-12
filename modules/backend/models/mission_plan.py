"""
Mission Plan Models (Plan 42).

Persistent, long-lived plans per mission. A MissionPlan holds a living
`TaskPlan` (the existing schemas/task_plan.py::TaskPlan shape) as its body
and tracks per-task cross-run status via PlanTaskState.

Plans survive runs — a single MissionPlan can be dispatched multiple times
with different subsets of approved tasks, and task state persists across
those runs. This is the backend for the Plan tab's long-lived backlog view
introduced by Plan 41 and specified by Plan 42.

Schema reference: Plan 42 §2.1 (tables), §2.3 (task state machine),
§10.1 (handle_mission contract), §10.4 (refinement agent: Planning Agent).
"""

import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.sqlite import JSON
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


class PlanTaskStatus(str, enum.Enum):
    """Per-task cross-run state (Plan 42 §2.3).

    Transitions:
        proposed  → approved | cancelled
        approved  → queued | cancelled
        queued    → running
        running   → completed | failed | skipped
        failed    → approved        (via retry)
    """

    PROPOSED = "proposed"
    APPROVED = "approved"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


# Terminal states — not reachable by further transitions except retry (failed)
TERMINAL_PLAN_TASK_STATUSES: frozenset[PlanTaskStatus] = frozenset({
    PlanTaskStatus.COMPLETED,
    PlanTaskStatus.SKIPPED,
    PlanTaskStatus.CANCELLED,
})


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

    One row per mission (enforced by unique constraint). Holds a live
    `TaskPlan` JSON body that gets refined over time by the Director via
    the Planning Agent. Tasks inside the body are tracked as PlanTaskState
    rows keyed by their string `task_id`.

    See Plan 42 §2.1 for schema and §2.3 for state machine rationale.
    """

    __tablename__ = "mission_plans"

    mission_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    task_plan_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment=(
            "Live TaskPlan serialized as JSON. NULL until the first "
            "refinement. Same shape as execution_records.task_plan_json."
        ),
    )

    gate_mode: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment=(
            "Autonomy mode: off, interactive, ai_assisted, autonomous. "
            "Inherits from missions.gate_mode at creation."
        ),
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default=MissionPlanStatus.ACTIVE.value,
        server_default=MissionPlanStatus.ACTIVE.value,
        nullable=False,
    )

    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
        comment="Bumped on each refinement. Plan 42 §2.5.",
    )

    budget_usd_ceiling: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Cumulative cap across all runs from this plan",
    )

    total_spent_usd: Mapped[float] = mapped_column(
        Float,
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

    # Supervisor autonomy loop counters (Plan 51 Phase C).
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

    # Relationships
    task_states: Mapped[list["PlanTaskState"]] = relationship(
        "PlanTaskState",
        back_populates="plan",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<MissionPlan(id={self.id}, mission_id={self.mission_id}, "
            f"version={self.version}, status={self.status})>"
        )


class PlanTaskState(UUIDMixin, TimestampMixin, Base):
    """Per-task state tracking for tasks inside a MissionPlan's TaskPlan body.

    The `task_id` is a *string* key into the TaskPlan JSON — not a database
    foreign key. Tasks live inside `task_plan_json`, not in their own table
    (Plan 42 §2.1 — avoids duplicating the rich TaskDefinition schema).

    A row exists for every task present in the plan's current `task_plan_json`.
    On refinement, surviving task_ids keep their existing state rows; removed
    task_ids get cancelled (Plan 42 §10.3 clean-slate fallback); new task_ids
    get fresh `proposed` rows.
    """

    __tablename__ = "plan_task_states"
    __table_args__ = (
        UniqueConstraint(
            "mission_plan_id", "task_id",
            name="uq_plan_task_states_plan_task",
        ),
    )

    mission_plan_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("mission_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    task_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="String task_id inside task_plan_json — not a DB FK",
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default=PlanTaskStatus.PROPOSED.value,
        server_default=PlanTaskStatus.PROPOSED.value,
        nullable=False,
    )

    # Approval metadata
    approved_by_user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
    )

    # Execution linkage (set when the task actually runs)
    execution_record_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("execution_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_execution_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("task_executions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Run lifecycle
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False,
    )

    # Veto window (ai_assisted mode)
    veto_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
    )

    # Denormalized run result (for quick Plan tab rendering without joins)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Denormalized metrics from task_executions for Done-card rendering
    # (Plan 46 Phase 2 work unit #2). Written at run completion by
    # MissionPlanService._write_back_task_results. Defaults to 0.0 —
    # pre-run statuses legitimately show "no cost incurred yet".
    cost_usd: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0.0", nullable=False,
    )
    duration_seconds: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0.0", nullable=False,
    )

    # Relationships
    plan: Mapped["MissionPlan"] = relationship(
        "MissionPlan", back_populates="task_states",
    )

    def __repr__(self) -> str:
        return (
            f"<PlanTaskState(plan={self.mission_plan_id}, "
            f"task_id={self.task_id!r}, status={self.status})>"
        )
