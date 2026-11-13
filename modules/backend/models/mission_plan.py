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

from sqlalchemy import JSON, CheckConstraint, Enum, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class GateMode(str, enum.Enum):
    """Plan gate mode (Plan 88 contracts 3.1.2).

    Stored by NAME (uppercase) in ``mission_plans.gate_mode``; the lowercase
    value is the wire format and matches config/settings/gate.yaml.
    """

    INTERACTIVE = "interactive"
    MANUAL = "manual"
    AI_ASSISTED = "ai_assisted"
    AUTONOMOUS = "autonomous"


# Gate modes in which proposed tasks are approved without a person. AI_ASSISTED
# means the AI recommends and a human decides, so it is not listed here.
AUTO_APPROVE_GATE_MODES: frozenset[GateMode] = frozenset({GateMode.AUTONOMOUS})


class MissionPlan(UUIDMixin, TimestampMixin, Base):
    """A persistent, long-lived plan for a single mission.

    One row per mission (enforced by unique constraint). Tasks live in the
    `tasks` table as first-class entities (Plan 72). This model holds
    plan-level metadata, gate configuration and the budget caps.
    """

    __tablename__ = "mission_plans"
    __table_args__ = (
        CheckConstraint("budget_per_run_usd > 0", name="ck_mission_plans_per_run_pos"),
        CheckConstraint("budget_per_month_usd > 0", name="ck_mission_plans_per_month_pos"),
        CheckConstraint(
            "budget_per_month_usd >= budget_per_run_usd", name="ck_mission_plans_month_ge_run"
        ),
        CheckConstraint(
            "budget_lifetime_usd IS NULL OR budget_lifetime_usd > 0",
            name="ck_mission_plans_lifetime_pos",
        ),
    )

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

    gate_mode: Mapped[GateMode] = mapped_column(
        Enum(GateMode, native_enum=False, length=32),
        nullable=False,
        comment="Autonomy mode. Set by MissionService.create_mission.",
    )

    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
        comment="Bumped on each refinement.",
    )

    # ── Budget caps (Plan 88 contracts 3.1.4; spend lives in the llm_calls ledger) ──

    budget_per_run_usd: Mapped[float] = mapped_column(
        Numeric(12, 6, asdecimal=False),
        nullable=False,
        comment="Cap on one run's spend; snapshotted into mission_runs.budget_cap_usd at begin",
    )

    budget_per_month_usd: Mapped[float] = mapped_column(
        Numeric(12, 6, asdecimal=False),
        nullable=False,
        comment="Cap on spend per UTC calendar month",
    )

    budget_lifetime_usd: Mapped[float | None] = mapped_column(
        Numeric(12, 6, asdecimal=False),
        nullable=True,
        comment="Optional cap on lifetime spend; NULL means no lifetime cap",
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
            f"version={self.version}, gate_mode={self.gate_mode})>"
        )
