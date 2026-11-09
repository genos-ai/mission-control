"""
Mission Schedule Model (Plan 88, contracts 3.1.5 and 3.2.3).

One row per recurring schedule of a mission. Postgres is the source of truth;
each row is mirrored to exactly one Temporal Schedule whose id is
``mission-schedule-{id}``. The cron is interpreted by Temporal, never locally.
"""

import enum
from datetime import datetime
from uuid import uuid7

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin

TEMPORAL_SCHEDULE_ID_PREFIX = "mission-schedule-"


class MissionScheduleKind(str, enum.Enum):
    """What a schedule starts. Immutable after create."""

    OBJECTIVE = "objective"
    WORKFLOW_DEFINITION = "workflow_definition"


class MissionScheduleStatus(str, enum.Enum):
    """Schedule lifecycle status (contract 3.2.3)."""

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class MissionScheduleCompletedReason(str, enum.Enum):
    """Why a schedule reached COMPLETED."""

    END_DATE_REACHED = "end_date_reached"
    MAX_RUNS_REACHED = "max_runs_reached"


class TemporalSyncState(str, enum.Enum):
    """Whether the Temporal Schedule matches the row."""

    PENDING = "pending"
    SYNCED = "synced"
    FAILED = "failed"


class MissionSchedule(UUIDMixin, TimestampMixin, Base):
    """A recurring schedule that starts mission runs through a Temporal Schedule."""

    __tablename__ = "mission_schedules"
    __table_args__ = (
        UniqueConstraint("mission_id", "name", name="uq_mission_schedules_mission_name"),
        UniqueConstraint("temporal_schedule_id", name="uq_mission_schedules_temporal_schedule_id"),
        Index("ix_mission_schedules_mission_status", "mission_id", "status"),
        CheckConstraint(
            "(kind = 'OBJECTIVE' AND objective_template IS NOT NULL "
            "AND workflow_definition_id IS NULL) OR "
            "(kind = 'WORKFLOW_DEFINITION' AND workflow_definition_id IS NOT NULL "
            "AND objective_template IS NULL)",
            name="ck_mission_schedules_target",
        ),
        CheckConstraint(
            "ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at",
            name="ck_mission_schedules_window",
        ),
        CheckConstraint(
            "max_runs IS NULL OR max_runs > 0",
            name="ck_mission_schedules_max_runs",
        ),
        CheckConstraint(
            "catch_up_window_seconds > 0",
            name="ck_mission_schedules_catch_up_window",
        ),
        CheckConstraint(
            "(status = 'COMPLETED') = (completed_reason IS NOT NULL)",
            name="ck_mission_schedules_completed_reason",
        ),
    )

    mission_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[MissionScheduleKind] = mapped_column(
        Enum(MissionScheduleKind, native_enum=False, length=32),
        nullable=False,
    )
    objective_template: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    cron_expression: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="5-field cron, interpreted by Temporal",
    )
    time_zone_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="IANA time zone name, validated with zoneinfo.ZoneInfo",
    )
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_runs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    catch_up_window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[MissionScheduleStatus] = mapped_column(
        Enum(MissionScheduleStatus, native_enum=False, length=32),
        default=MissionScheduleStatus.ACTIVE,
        server_default=MissionScheduleStatus.ACTIVE.name,
        nullable=False,
    )
    completed_reason: Mapped[MissionScheduleCompletedReason | None] = mapped_column(
        Enum(MissionScheduleCompletedReason, native_enum=False, length=32),
        nullable=True,
    )
    executed_run_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        comment="Counts claims that produced a run",
    )
    last_claimed_scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Missed-occurrence backfill watermark",
    )
    temporal_schedule_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Always mission-schedule-{id}; set from temporal_id at insert",
    )
    temporal_sync_state: Mapped[TemporalSyncState] = mapped_column(
        Enum(TemporalSyncState, native_enum=False, length=32),
        default=TemporalSyncState.PENDING,
        server_default=TemporalSyncState.PENDING.name,
        nullable=False,
    )
    temporal_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    temporal_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    tick_config_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="SHA-256 of the TickConfigSnapshot registered in Temporal",
    )
    created_by_user_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    @property
    def temporal_id(self) -> str:
        """The Temporal Schedule id for this row."""
        return f"{TEMPORAL_SCHEDULE_ID_PREFIX}{self.id}"

    def __repr__(self) -> str:
        return (
            f"<MissionSchedule(id={self.id}, mission_id={self.mission_id}, "
            f"name={self.name!r}, status={self.status})>"
        )


@event.listens_for(MissionSchedule, "before_insert")
def _set_temporal_schedule_id(_mapper, _connection, target: MissionSchedule) -> None:
    """Assign the id early so temporal_schedule_id can be derived from it."""
    if target.id is None:
        target.id = str(uuid7())
    target.temporal_schedule_id = target.temporal_id
