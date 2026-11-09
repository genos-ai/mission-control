"""mission_schedules replaces workflow_schedules (Plan 88, 88.1.3)

Creates mission_schedules (contract 3.1.5), adds the deferred FK
mission_runs.schedule_id -> mission_schedules.id, migrates every
workflow_schedules row into a WORKFLOW_DEFINITION schedule and drops
workflow_schedules. Migrated rows are PAUSED (or COMPLETED when their
iterations are exhausted, or ARCHIVED when their time zone is invalid), so the
owner resumes them under the new time-zone semantics. description and
budget_per_run_usd have no successor and are dropped (P3).

The upgrade aborts, writing nothing, when any row's creator cannot be resolved
to an existing user.

Revision ID: plan88_003
Revises: plan88_002
Create Date: 2026-11-09
"""

import re
from typing import Sequence, Union
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from modules.backend.core.logging import get_logger

revision: str = "plan88_003"
down_revision: Union[str, None] = "plan88_002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = get_logger(__name__)

DEFAULT_CATCH_UP_WINDOW_SECONDS = (
    21600  # missions.recurrence.default_catch_up_window_seconds at plan88_003
)

_UUID = PgUUID(as_uuid=False)
_CREATED_BY_PATTERN = re.compile(r"^user:([0-9a-f-]{36})$")
_PG_CREATED_BY_PATTERN = "^user:([0-9a-f-]{36})$"

# A row whose creator cannot be resolved: created_by does not name an existing
# user, and the mission owner is not an existing user either.
_UNRESOLVABLE_CREATORS_SQL = sa.text(
    "SELECT ws.id FROM workflow_schedules ws JOIN missions m ON m.id = ws.mission_id "
    "WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.id::text = "
    f"substring(ws.created_by from '{_PG_CREATED_BY_PATTERN}')) "
    "AND NOT EXISTS (SELECT 1 FROM users u WHERE u.id::text = m.owner_id) "
    "ORDER BY ws.id"
)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def _valid_time_zone(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def _create_mission_schedules() -> None:
    op.create_table(
        "mission_schedules",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "mission_id",
            _UUID,
            sa.ForeignKey("missions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("objective_template", sa.Text(), nullable=True),
        sa.Column(
            "workflow_definition_id",
            _UUID,
            sa.ForeignKey("workflow_definitions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "workflow_parameters",
            JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("cron_expression", sa.String(100), nullable=False),
        sa.Column("time_zone_name", sa.String(64), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_runs", sa.Integer(), nullable=True),
        sa.Column("catch_up_window_seconds", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), server_default="ACTIVE", nullable=False),
        sa.Column("completed_reason", sa.String(32), nullable=True),
        sa.Column("executed_run_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_claimed_scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("temporal_schedule_id", sa.String(200), nullable=False),
        sa.Column(
            "temporal_sync_state",
            sa.String(32),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("temporal_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("temporal_sync_error", sa.Text(), nullable=True),
        sa.Column("tick_config_hash", sa.String(64), nullable=True),
        sa.Column(
            "created_by_user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        *_timestamps(),
        sa.UniqueConstraint("mission_id", "name", name="uq_mission_schedules_mission_name"),
        sa.UniqueConstraint(
            "temporal_schedule_id", name="uq_mission_schedules_temporal_schedule_id"
        ),
        sa.CheckConstraint(
            "(kind = 'OBJECTIVE' AND objective_template IS NOT NULL "
            "AND workflow_definition_id IS NULL) OR "
            "(kind = 'WORKFLOW_DEFINITION' AND workflow_definition_id IS NOT NULL "
            "AND objective_template IS NULL)",
            name="ck_mission_schedules_target",
        ),
        sa.CheckConstraint(
            "ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at",
            name="ck_mission_schedules_window",
        ),
        sa.CheckConstraint(
            "max_runs IS NULL OR max_runs > 0", name="ck_mission_schedules_max_runs"
        ),
        sa.CheckConstraint(
            "catch_up_window_seconds > 0", name="ck_mission_schedules_catch_up_window"
        ),
        sa.CheckConstraint(
            "(status = 'COMPLETED') = (completed_reason IS NOT NULL)",
            name="ck_mission_schedules_completed_reason",
        ),
    )
    op.create_index("ix_mission_schedules_mission_id", "mission_schedules", ["mission_id"])
    op.create_index(
        "ix_mission_schedules_mission_status",
        "mission_schedules",
        ["mission_id", "status"],
    )


def _resolve_creator(created_by: str, owner_id: str, user_ids: set[str]) -> str:
    match = _CREATED_BY_PATTERN.match(created_by)
    if match and match.group(1) in user_ids:
        return match.group(1)
    return owner_id


def _migrate_rows(bind: sa.engine.Connection) -> None:
    rows = (
        bind.execute(
            sa.text(
                "SELECT ws.*, m.owner_id FROM workflow_schedules ws "
                "JOIN missions m ON m.id = ws.mission_id ORDER BY ws.created_at"
            )
        )
        .mappings()
        .all()
    )
    user_ids = {str(r[0]) for r in bind.execute(sa.text("SELECT id FROM users"))}
    insert = sa.text(
        "INSERT INTO mission_schedules (id, mission_id, name, kind, workflow_definition_id, "
        "workflow_parameters, cron_expression, time_zone_name, max_runs, "
        "catch_up_window_seconds, status, completed_reason, executed_run_count, "
        "temporal_schedule_id, temporal_sync_state, temporal_sync_error, "
        "created_by_user_id, created_at, updated_at) "
        "VALUES (:id, :mission_id, :name, 'WORKFLOW_DEFINITION', :workflow_definition_id, "
        "'{}'::jsonb, :cron_expression, :time_zone_name, :max_runs, "
        ":catch_up_window_seconds, :status, :completed_reason, :executed_run_count, "
        ":temporal_schedule_id, 'PENDING', :temporal_sync_error, "
        ":created_by_user_id, now(), now())"
    )
    for row in rows:
        new_id = str(uuid4())
        max_iterations = row["max_iterations"]
        iteration_count = row["iteration_count"]
        completed_reason = None
        sync_error = None
        time_zone_name = row["timezone"]
        if not _valid_time_zone(time_zone_name):
            status = "ARCHIVED"
            sync_error = f"plan88_003: invalid time zone {time_zone_name}"
            time_zone_name = "UTC"
        elif max_iterations is not None and iteration_count >= max_iterations:
            status = "COMPLETED"
            completed_reason = "MAX_RUNS_REACHED"
        else:
            status = "PAUSED"
        executed = (
            iteration_count if max_iterations is None else min(iteration_count, max_iterations)
        )
        bind.execute(
            insert,
            {
                "id": new_id,
                "mission_id": str(row["mission_id"]),
                "name": f"wf-{str(row['id'])[:8]}",
                "workflow_definition_id": str(row["workflow_definition_id"]),
                "cron_expression": row["cron_expression"],
                "time_zone_name": time_zone_name,
                "max_runs": max_iterations,
                "catch_up_window_seconds": DEFAULT_CATCH_UP_WINDOW_SECONDS,
                "status": status,
                "completed_reason": completed_reason,
                "executed_run_count": executed,
                "temporal_schedule_id": f"mission-schedule-{new_id}",
                "temporal_sync_error": sync_error,
                "created_by_user_id": _resolve_creator(
                    row["created_by"], row["owner_id"], user_ids
                ),
            },
        )
    logger.info("plan88_003: workflow schedules migrated", extra={"row_count": len(rows)})

    dropped_budgets = sum(1 for r in rows if r["budget_per_run_usd"] is not None)
    if dropped_budgets:
        logger.warning(
            "plan88_003: budget_per_run_usd dropped from migrated schedules",
            extra={"row_count": dropped_budgets},
        )


def upgrade() -> None:
    bind = op.get_bind()

    # 1. mission_schedules (3.1.5).
    _create_mission_schedules()

    # 2. Deferred FK from plan88_002.
    op.create_foreign_key(
        "fk_mission_runs_schedule_id",
        "mission_runs",
        "mission_schedules",
        ["schedule_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 3. Creator pre-check: abort before writing any row.
    unresolvable = [str(r[0]) for r in bind.execute(_UNRESOLVABLE_CREATORS_SQL)]
    if unresolvable:
        raise RuntimeError(
            "plan88_003: workflow_schedules rows with no resolvable creator "
            f"(created_by is not an existing user and the mission owner is not a user): "
            f"{', '.join(unresolvable)}"
        )

    # 4. Data migration.
    _migrate_rows(bind)

    # 5.
    op.drop_table("workflow_schedules")


def downgrade() -> None:
    # 6. workflow_schedules as the old model defined it, empty.
    op.create_table(
        "workflow_schedules",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "workflow_definition_id",
            _UUID,
            sa.ForeignKey("workflow_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mission_id",
            _UUID,
            sa.ForeignKey("missions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cron_expression", sa.String(100), nullable=False),
        sa.Column("timezone", sa.String(50), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("budget_per_run_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("max_iterations", sa.Integer(), nullable=True),
        sa.Column("iteration_count", sa.Integer(), nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_fire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(200), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "workflow_definition_id",
            "mission_id",
            "cron_expression",
            name="uq_schedule_definition_mission_cron",
        ),
    )
    op.create_index(
        "ix_workflow_schedules_workflow_definition_id",
        "workflow_schedules",
        ["workflow_definition_id"],
    )
    op.create_index("ix_workflow_schedules_mission_id", "workflow_schedules", ["mission_id"])
    op.create_index("ix_workflow_schedules_enabled", "workflow_schedules", ["enabled"])

    op.drop_constraint("fk_mission_runs_schedule_id", "mission_runs", type_="foreignkey")
    op.drop_table("mission_schedules")
