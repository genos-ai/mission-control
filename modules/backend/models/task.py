"""
Task Model (Plan 72).

First-class task entity. Merges TaskDefinition (from JSON) with PlanTaskState
(shadow table) into a single source of truth. Tasks are the operational
primitive of Mission Control: the planner produces them, the dispatcher
iterates them, the Kanban shows them, agents execute them, verification
gates them.

Task identity is UUID — stable across refinements, no version prefixes.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin
from modules.backend.schemas.task_failure import FailureClass, FailureOrigin


class TaskStatus(str, enum.Enum):
    """Task lifecycle status (Plan 72).

    Renamed from PlanTaskStatus. Same values, same DB representation.

    Transitions:
        proposed  -> approved | cancelled
        approved  -> queued | cancelled
        queued    -> running
        running   -> completed | failed | skipped
        failed    -> approved | skipped (retry, or a gate skip)
    """

    PROPOSED = "proposed"
    APPROVED = "approved"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


VALID_TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PROPOSED: frozenset({TaskStatus.APPROVED, TaskStatus.CANCELLED}),
    TaskStatus.APPROVED: frozenset({TaskStatus.QUEUED, TaskStatus.CANCELLED}),
    TaskStatus.QUEUED: frozenset({TaskStatus.RUNNING, TaskStatus.FAILED}),
    TaskStatus.RUNNING: frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED}),
    TaskStatus.FAILED: frozenset({TaskStatus.APPROVED, TaskStatus.SKIPPED}),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.SKIPPED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}

TERMINAL_TASK_STATUSES: frozenset[TaskStatus] = frozenset(
    {
        TaskStatus.COMPLETED,
        TaskStatus.SKIPPED,
        TaskStatus.CANCELLED,
    }
)


class Task(UUIDMixin, TimestampMixin, Base):
    """First-class task entity (Plan 72).

    Merges TaskDefinition (schema) + PlanTaskState (shadow table) into one
    relational row. UUID is the sole identity — stable across refinements.
    """

    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_mission_id_status", "mission_id", "status"),
        Index("ix_tasks_plan_id_status", "plan_id", "status"),
        Index("ix_tasks_plan_id_created_at", "plan_id", "created_at"),
        Index("ix_tasks_run_status", "mission_run_id", "status"),
    )

    # ── Scope ──────────────────────────────────────────────────────────────

    mission_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        comment=(
            "Denormalized from plan -> mission for cross-plan queries. "
            "Application-level enforcement ensures consistency with "
            "mission_plans.mission_id via TaskRepository.create()."
        ),
    )

    plan_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("mission_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    mission_run_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("mission_runs.id", ondelete="SET NULL"),
        nullable=True,
        comment="Run that owns the task; NULL means backlog, not yet dispatched (Plan 88)",
    )

    # ── Definition (from TaskDefinition schema) ────────────────────────────

    agent: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Agent name from the roster",
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Human-readable task description (primary Kanban label)",
    )

    instructions: Mapped[str] = mapped_column(
        Text,
        default="",
        server_default="",
        nullable=False,
        comment="Detailed instructions for the executing agent",
    )

    inputs_json: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        server_default="{}",
        nullable=False,
        comment='{"static": {}, "from_upstream": {}, "file_manifest": null}',
    )

    verification_json: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        server_default="{}",
        nullable=False,
        comment='{"tier_1": {}, "tier_2": {}, "tier_3": {}}',
    )

    constraints_json: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        server_default="{}",
        nullable=False,
        comment='{"timeout_override_seconds": null, "priority": "normal"}',
    )

    domain_tags: Mapped[list] = mapped_column(
        JSON,
        default=list,
        server_default="[]",
        nullable=False,
        comment="Domain tags for structured history queries",
    )

    # ── State (merged from PlanTaskState) ──────────────────────────────────

    status: Mapped[str] = mapped_column(
        Enum(TaskStatus, native_enum=False),
        default=TaskStatus.PROPOSED,
        server_default=TaskStatus.PROPOSED.name,
        nullable=False,
    )

    approved_by_user_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )

    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )

    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── Result (denormalized for Kanban rendering) ─────────────────────────

    result_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Brief outcome written after execution completes",
    )

    failure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Why the task failed (if applicable)",
    )

    # Classification of the current attempt's failure (Plan 88, contracts 3.1.8 and 3.8.6).
    failure_origin: Mapped[FailureOrigin | None] = mapped_column(
        Enum(FailureOrigin, native_enum=False, length=32),
        nullable=True,
    )
    failure_class: Mapped[FailureClass | None] = mapped_column(
        Enum(FailureClass, native_enum=False, length=40),
        nullable=True,
    )
    failure_fingerprint: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    cost_usd: Mapped[float] = mapped_column(
        Numeric(12, 6, asdecimal=False),
        default=0.0,
        server_default="0.0",
        nullable=False,
    )

    duration_seconds: Mapped[float] = mapped_column(
        Numeric(12, 6, asdecimal=False),
        default=0.0,
        server_default="0.0",
        nullable=False,
    )

    # ── Relationships ──────────────────────────────────────────────────────

    dependencies: Mapped[list["TaskDependency"]] = relationship(
        "TaskDependency",
        foreign_keys="TaskDependency.task_id",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    dependents: Mapped[list["TaskDependency"]] = relationship(
        "TaskDependency",
        foreign_keys="TaskDependency.depends_on_id",
        back_populates="depends_on_task",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    plan: Mapped["MissionPlan"] = relationship(  # noqa: F821
        "MissionPlan",
        back_populates="tasks",
        lazy="noload",
    )

    def transition_status(self, target: TaskStatus) -> None:
        """Transition to a new status with state machine validation.

        Raises ValueError if the transition is not allowed.
        """
        current = self.status if isinstance(self.status, TaskStatus) else TaskStatus(self.status)
        allowed = VALID_TASK_TRANSITIONS.get(current, frozenset())
        if target not in allowed:
            raise ValueError(
                f"Invalid task transition: {current.value} -> {target.value}. "
                f"Allowed: {sorted(s.value for s in allowed) or 'none (terminal)'}"
            )
        self.status = target

    def __repr__(self) -> str:
        return (
            f"<Task(id={self.id}, plan_id={self.plan_id}, "
            f"agent={self.agent!r}, status={self.status})>"
        )


class TaskDependency(UUIDMixin, Base):
    """DAG edge between tasks (Plan 72).

    Replaces the `dependencies: list[str]` field in TaskDefinition JSON.
    Proper relational representation enables DB-native DAG queries.
    """

    __tablename__ = "task_dependencies"
    __table_args__ = (
        UniqueConstraint("task_id", "depends_on_id", name="uq_task_dep_edge"),
        CheckConstraint("task_id != depends_on_id", name="ck_task_dep_no_self"),
        Index("ix_task_dependencies_task_id", "task_id"),
        Index("ix_task_dependencies_depends_on_id", "depends_on_id"),
    )

    task_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )

    depends_on_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Relationships
    task: Mapped["Task"] = relationship(
        "Task",
        foreign_keys=[task_id],
        back_populates="dependencies",
    )

    depends_on_task: Mapped["Task"] = relationship(
        "Task",
        foreign_keys=[depends_on_id],
        back_populates="dependents",
    )

    def __repr__(self) -> str:
        return f"<TaskDependency(task={self.task_id} -> depends_on={self.depends_on_id})>"
