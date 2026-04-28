"""
Workflow Schedule Model.

Cron-based execution configuration for workflow definitions.
Each row links a workflow definition to a schedule with budget controls,
iteration limits, and enable/disable state.

The scheduler service reads enabled schedules, evaluates cron expressions,
and creates WorkflowRuns when they fire.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class WorkflowSchedule(UUIDMixin, TimestampMixin, Base):
    """A cron-based execution schedule for a workflow definition."""

    __tablename__ = "workflow_schedules"
    __table_args__ = (
        UniqueConstraint(
            "workflow_definition_id",
            "mission_id",
            "cron_expression",
            name="uq_schedule_definition_mission_cron",
        ),
    )

    workflow_definition_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("workflow_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mission_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Denormalised from workflow_definitions for query convenience",
    )
    cron_expression: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="Standard 5-field cron: minute hour day month weekday",
    )
    timezone: Mapped[str] = mapped_column(
        String(50), nullable=False, default="UTC",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True,
    )
    description: Mapped[str] = mapped_column(
        Text, nullable=False, default="",
    )
    budget_per_run_usd: Mapped[float | None] = mapped_column(
        Numeric(12, 6, asdecimal=False), nullable=True,
        comment="USD ceiling per individual run triggered by this schedule",
    )
    max_iterations: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="Total runs this schedule may create (NULL = unlimited within platform cap)",
    )
    iteration_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="How many runs this schedule has created so far",
    )
    cooldown_seconds: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Minimum seconds between consecutive runs (prevents rapid-fire)",
    )
    last_fired_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
        comment="UTC datetime of the last time this schedule created a run",
    )
    next_fire_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
        comment="Precomputed UTC datetime of the next expected fire time",
    )
    created_by: Mapped[str] = mapped_column(
        String(200), nullable=False,
        comment="user:<id> or system",
    )

    def __repr__(self) -> str:
        return (
            f"<WorkflowSchedule(workflow={self.workflow_definition_id}, "
            f"cron={self.cron_expression!r}, enabled={self.enabled})>"
        )
