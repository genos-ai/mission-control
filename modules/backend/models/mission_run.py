"""
Mission Run Model (Plan 88, contracts 3.1.6 and 3.2.1).

One row per occurrence of mission work, kept permanently. Every row, including
SKIPPED and MISSED, consumes one number from missions.run_sequence_counter.
Status transitions go through MissionRun.transition_status only.
"""

import enum
from datetime import datetime

from sqlalchemy import (
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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.core.exceptions import MissionRunStateError
from modules.backend.core.utils import utc_now
from modules.backend.models.base import Base, TimestampMixin, UUIDMixin
from modules.backend.models.mission_plan import GateMode


class MissionRunTrigger(str, enum.Enum):
    """What started a run."""

    SCHEDULE = "schedule"
    MANUAL = "manual"
    DIRECTOR = "director"


class MissionRunStatus(str, enum.Enum):
    """Run lifecycle status (contract 3.2.1)."""

    PENDING = "pending"
    RUNNING = "running"
    AWAITING_GATE = "awaiting_gate"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BUDGET_STOPPED = "budget_stopped"
    SKIPPED = "skipped"
    MISSED = "missed"


class MissionRunStatusReason(str, enum.Enum):
    """Why a run reached its status (contract 3.1.2)."""

    OBJECTIVE_MET = "objective_met"
    NO_FURTHER_WORK = "no_further_work"
    SUPERVISOR_ESCALATED = "supervisor_escalated"
    TASK_FAILURES = "task_failures"
    PLANNING_FAILED = "planning_failed"
    GATE_REJECTED = "gate_rejected"
    INVALID_GATE_MODE = "invalid_gate_mode"
    CANCELLED_BY_USER = "cancelled_by_user"
    MISSION_ARCHIVED = "mission_archived"
    BUDGET_RUN_CAP = "budget_run_cap"
    BUDGET_MONTHLY_CAP = "budget_monthly_cap"
    BUDGET_LIFETIME_CAP = "budget_lifetime_cap"
    START_FAILED = "start_failed"
    ORPHANED_WORKFLOW_CLOSED = "orphaned_workflow_closed"
    ORPHANED_WORKFLOW_NOT_FOUND = "orphaned_workflow_not_found"
    USER_PAUSE = "user_pause"
    GATE_TIMEOUT = "gate_timeout"
    OVERLAP = "overlap"
    MISSION_NOT_ACTIVE = "mission_not_active"
    SCHEDULE_NOT_ACTIVE = "schedule_not_active"
    MAX_RUNS_REACHED = "max_runs_reached"
    BUDGET_CAP_REACHED = "budget_cap_reached"
    OUTSIDE_CATCHUP_WINDOW = "outside_catchup_window"
    SUPERSEDED = "superseded"
    NOT_FIRED = "not_fired"
    MAX_DURATION_EXCEEDED = "max_duration_exceeded"


ACTIVE_RUN_STATUSES: frozenset[MissionRunStatus] = frozenset(
    {
        MissionRunStatus.PENDING,
        MissionRunStatus.RUNNING,
        MissionRunStatus.AWAITING_GATE,
        MissionRunStatus.PAUSED,
    }
)

TERMINAL_RUN_STATUSES: frozenset[MissionRunStatus] = frozenset(
    {
        MissionRunStatus.SUCCEEDED,
        MissionRunStatus.FAILED,
        MissionRunStatus.CANCELLED,
        MissionRunStatus.BUDGET_STOPPED,
        MissionRunStatus.SKIPPED,
        MissionRunStatus.MISSED,
    }
)

# Contract 3.2.1. SKIPPED and MISSED are only ever inserted, never entered.
VALID_RUN_TRANSITIONS: dict[MissionRunStatus, frozenset[MissionRunStatus]] = {
    MissionRunStatus.PENDING: frozenset(
        {MissionRunStatus.RUNNING, MissionRunStatus.FAILED, MissionRunStatus.CANCELLED}
    ),
    MissionRunStatus.RUNNING: frozenset(
        {
            MissionRunStatus.AWAITING_GATE,
            MissionRunStatus.PAUSED,
            MissionRunStatus.SUCCEEDED,
            MissionRunStatus.FAILED,
            MissionRunStatus.BUDGET_STOPPED,
            MissionRunStatus.CANCELLED,
        }
    ),
    MissionRunStatus.AWAITING_GATE: frozenset(
        {
            MissionRunStatus.RUNNING,
            MissionRunStatus.PAUSED,
            MissionRunStatus.CANCELLED,
            MissionRunStatus.FAILED,
        }
    ),
    MissionRunStatus.PAUSED: frozenset(
        {MissionRunStatus.RUNNING, MissionRunStatus.CANCELLED, MissionRunStatus.FAILED}
    ),
    MissionRunStatus.SUCCEEDED: frozenset(),
    MissionRunStatus.FAILED: frozenset(),
    MissionRunStatus.CANCELLED: frozenset(),
    MissionRunStatus.BUDGET_STOPPED: frozenset(),
    MissionRunStatus.SKIPPED: frozenset(),
    MissionRunStatus.MISSED: frozenset(),
}

# SQL predicate over stored enum NAMES for the partial indexes on active runs.
_ACTIVE_STATUS_PREDICATE = "status IN ('PENDING','RUNNING','AWAITING_GATE','PAUSED')"


class MissionRun(UUIDMixin, TimestampMixin, Base):
    """One occurrence of mission work."""

    __tablename__ = "mission_runs"
    __table_args__ = (
        UniqueConstraint("mission_id", "sequence", name="uq_mission_runs_mission_sequence"),
        UniqueConstraint("schedule_id", "scheduled_for", name="uq_mission_runs_schedule_slot"),
        UniqueConstraint("temporal_workflow_id", name="uq_mission_runs_temporal_workflow_id"),
        Index(
            "uq_mission_runs_one_active",
            "mission_id",
            unique=True,
            postgresql_where=text(_ACTIVE_STATUS_PREDICATE),
        ),
        Index(
            "ix_mission_runs_nonterminal",
            "status",
            "updated_at",
            postgresql_where=text(_ACTIVE_STATUS_PREDICATE),
        ),
        Index("ix_mission_runs_mission_created", "mission_id", text("created_at DESC")),
        CheckConstraint(
            "(trigger = 'SCHEDULE') = (scheduled_for IS NOT NULL AND schedule_id IS NOT NULL)",
            name="ck_mission_runs_schedule_slot",
        ),
    )

    mission_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("mission_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The FK was added by plan88_003, after mission_schedules existed.
    schedule_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey(
            "mission_schedules.id",
            ondelete="SET NULL",
            name="fk_mission_runs_schedule_id",
        ),
        nullable=True,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger: Mapped[MissionRunTrigger] = mapped_column(
        Enum(MissionRunTrigger, native_enum=False, length=32),
        nullable=False,
    )
    triggered_by_user_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    previous_run_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("mission_runs.id", ondelete="SET NULL"),
        nullable=True,
        comment="Latest earlier run that has a digest",
    )
    objective: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Rendered objective; NULL means a backlog dispatch",
    )
    workflow_definition_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("workflow_definitions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    workflow_parameters: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    status: Mapped[MissionRunStatus] = mapped_column(
        Enum(MissionRunStatus, native_enum=False, length=32),
        default=MissionRunStatus.PENDING,
        server_default=MissionRunStatus.PENDING.name,
        nullable=False,
    )
    status_reason: Mapped[MissionRunStatusReason | None] = mapped_column(
        Enum(MissionRunStatusReason, native_enum=False, length=40),
        nullable=True,
    )
    status_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    gate_mode: Mapped[GateMode | None] = mapped_column(
        Enum(GateMode, native_enum=False, length=32),
        nullable=True,
        comment="Snapshot taken at begin_mission_run",
    )
    temporal_workflow_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        comment="mission_run_workflow_id(id); NULL for SKIPPED and MISSED",
    )
    session_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    context_version_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_version_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    iteration_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    budget_cap_usd: Mapped[float | None] = mapped_column(
        Numeric(12, 6, asdecimal=False),
        nullable=True,
    )
    cost_usd: Mapped[float] = mapped_column(
        Numeric(12, 6, asdecimal=False),
        default=0.0,
        server_default="0",
        nullable=False,
    )
    task_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    completed_task_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    failed_task_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    config_snapshot: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cancel_requested_by_user_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    cancel_reason: Mapped[MissionRunStatusReason | None] = mapped_column(
        Enum(MissionRunStatusReason, native_enum=False, length=40),
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def end_reason(
        self,
        status: MissionRunStatus,
        reason: MissionRunStatusReason | None,
    ) -> MissionRunStatusReason | None:
        """The reason a run ending in ``status`` records.

        A CANCELLED end takes the stored ``cancel_reason`` (who asked for the
        cancel) over the caller's reason; every other end keeps ``reason``.
        Finalise and the run digest both resolve the reason through this rule.
        """
        if status == MissionRunStatus.CANCELLED and self.cancel_reason is not None:
            return MissionRunStatusReason(self.cancel_reason)
        return reason

    def transition_status(
        self,
        target: MissionRunStatus,
        reason: MissionRunStatusReason | None,
        detail: str | None,
    ) -> None:
        """Move to ``target`` per VALID_RUN_TRANSITIONS.

        Raises MissionRunStateError when the transition is not allowed.
        """
        current = MissionRunStatus(self.status)
        if target not in VALID_RUN_TRANSITIONS[current]:
            raise MissionRunStateError(
                f"Invalid mission run transition: {current.value} -> {target.value} "
                f"(run {self.id})"
            )
        now = utc_now()
        if current is MissionRunStatus.PENDING and target is MissionRunStatus.RUNNING:
            self.started_at = now
        if target in TERMINAL_RUN_STATUSES:
            self.ended_at = now
        self.status = target
        self.status_reason = reason
        self.status_detail = detail

    def __repr__(self) -> str:
        return (
            f"<MissionRun(id={self.id}, mission_id={self.mission_id}, "
            f"sequence={self.sequence}, status={self.status})>"
        )
