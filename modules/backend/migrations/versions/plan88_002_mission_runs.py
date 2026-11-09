"""mission_runs, mission_run_digests and run linking columns (Plan 88, 88.1.2)

Adds the per-mission run sequence counter, the mission_runs and
mission_run_digests tables, run attribution on tasks, execution_records,
task_executions, context_changes and llm_calls, and the failure columns on
tasks and task_executions (mapped from 88.2.3b). Drops the never-written
execution_records.parent_execution_record_id.

mission_runs.schedule_id has no FK here: mission_schedules arrives in plan88_003.

Revision ID: plan88_002
Revises: plan88_001
Create Date: 2026-11-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID

revision: str = "plan88_002"
down_revision: Union[str, None] = "plan88_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ACTIVE_STATUS_PREDICATE = "status IN ('PENDING','RUNNING','AWAITING_GATE','PAUSED')"
_EMPTY_OBJECT = sa.text("'{}'::jsonb")
_EMPTY_ARRAY = sa.text("'[]'::jsonb")
_UUID = PgUUID(as_uuid=False)
_MONEY = sa.Numeric(12, 6)
_FAILURE_TABLES = ("tasks", "task_executions")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    # 1. Run sequence counter.
    op.add_column(
        "missions",
        sa.Column("run_sequence_counter", sa.Integer(), server_default="0", nullable=False),
    )

    # 2. mission_runs (3.1.6).
    op.create_table(
        "mission_runs",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "mission_id", _UUID, sa.ForeignKey("missions.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "plan_id", _UUID, sa.ForeignKey("mission_plans.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("schedule_id", _UUID, nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(32), nullable=False),
        sa.Column(
            "triggered_by_user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "previous_run_id",
            _UUID,
            sa.ForeignKey("mission_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column(
            "workflow_definition_id",
            _UUID,
            sa.ForeignKey("workflow_definitions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("workflow_parameters", JSONB(), server_default=_EMPTY_OBJECT, nullable=False),
        sa.Column("status", sa.String(32), server_default="PENDING", nullable=False),
        sa.Column("status_reason", sa.String(40), nullable=True),
        sa.Column("status_detail", sa.Text(), nullable=True),
        sa.Column("gate_mode", sa.String(32), nullable=True),
        sa.Column("temporal_workflow_id", sa.String(200), nullable=True),
        sa.Column(
            "session_id", _UUID, sa.ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("context_version_start", sa.Integer(), nullable=True),
        sa.Column("context_version_end", sa.Integer(), nullable=True),
        sa.Column("iteration_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("budget_cap_usd", _MONEY, nullable=True),
        sa.Column("cost_usd", _MONEY, server_default="0", nullable=False),
        sa.Column("task_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completed_task_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_task_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("config_snapshot", JSONB(), server_default=_EMPTY_OBJECT, nullable=False),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cancel_requested_by_user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("cancel_reason", sa.String(40), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )

    # 3. Constraints and indexes. 4. schedule_id: index only, FK in plan88_003.
    op.create_unique_constraint(
        "uq_mission_runs_mission_sequence", "mission_runs", ["mission_id", "sequence"]
    )
    op.create_unique_constraint(
        "uq_mission_runs_schedule_slot", "mission_runs", ["schedule_id", "scheduled_for"]
    )
    op.create_unique_constraint(
        "uq_mission_runs_temporal_workflow_id", "mission_runs", ["temporal_workflow_id"]
    )
    op.create_index(
        "uq_mission_runs_one_active",
        "mission_runs",
        ["mission_id"],
        unique=True,
        postgresql_where=sa.text(_ACTIVE_STATUS_PREDICATE),
    )
    op.create_index(
        "ix_mission_runs_nonterminal",
        "mission_runs",
        ["status", "updated_at"],
        postgresql_where=sa.text(_ACTIVE_STATUS_PREDICATE),
    )
    op.create_index(
        "ix_mission_runs_mission_created",
        "mission_runs",
        ["mission_id", sa.text("created_at DESC")],
    )
    op.create_check_constraint(
        "ck_mission_runs_schedule_slot",
        "mission_runs",
        "(trigger = 'SCHEDULE') = (scheduled_for IS NOT NULL AND schedule_id IS NOT NULL)",
    )
    op.create_index("ix_mission_runs_schedule_id", "mission_runs", ["schedule_id"])

    # 5. mission_run_digests (3.1.7).
    op.create_table(
        "mission_run_digests",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "mission_run_id",
            _UUID,
            sa.ForeignKey("mission_runs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "mission_id", _UUID, sa.ForeignKey("missions.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("generator", sa.String(32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("outcomes", JSONB(), nullable=False),
        sa.Column("decisions", JSONB(), server_default=_EMPTY_ARRAY, nullable=False),
        sa.Column("open_items", JSONB(), server_default=_EMPTY_ARRAY, nullable=False),
        sa.Column("context_changes", JSONB(), server_default=_EMPTY_ARRAY, nullable=False),
        sa.Column("metrics", JSONB(), nullable=False),
        sa.Column("generation_cost_usd", _MONEY, server_default="0", nullable=False),
        *_timestamps(),
    )
    op.create_index(
        "ix_mission_run_digests_mission_created",
        "mission_run_digests",
        ["mission_id", sa.text("created_at DESC")],
    )

    # 6. Run linking columns (3.1.8).
    for table in ("tasks", "execution_records", "task_executions", "context_changes"):
        op.add_column(
            table,
            sa.Column(
                "mission_run_id",
                _UUID,
                sa.ForeignKey("mission_runs.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    op.add_column("task_executions", sa.Column("idempotency_key", sa.String(100), nullable=True))
    op.create_index("ix_tasks_run_status", "tasks", ["mission_run_id", "status"])
    op.create_index(
        "uq_execution_records_run",
        "execution_records",
        ["mission_run_id"],
        unique=True,
        postgresql_where=sa.text("mission_run_id IS NOT NULL"),
    )
    op.create_index("ix_task_executions_mission_run_id", "task_executions", ["mission_run_id"])
    op.create_unique_constraint(
        "uq_task_executions_idempotency_key", "task_executions", ["idempotency_key"]
    )
    op.create_index("ix_context_changes_mission_run_id", "context_changes", ["mission_run_id"])

    # 7. MCD version range reads key on context_id (legacy rows lack mission_id).
    op.create_index(
        "ix_context_changes_context_version", "context_changes", ["context_id", "version"]
    )

    # 7a. Failure columns, unmapped until 88.2.3b. No backfill.
    for table in _FAILURE_TABLES:
        op.add_column(table, sa.Column("failure_origin", sa.String(32), nullable=True))
        op.add_column(table, sa.Column("failure_class", sa.String(40), nullable=True))
        op.add_column(table, sa.Column("failure_fingerprint", sa.String(64), nullable=True))
    op.add_column("task_executions", sa.Column("failure_json", JSONB(), nullable=True))
    op.create_index(
        "ix_task_executions_failure_fingerprint", "task_executions", ["failure_fingerprint"]
    )

    # 8. LLM call attribution, no FK. ix_llm_calls_mission_created already
    # exists (revision composite_indexes), so it is not created here.
    op.add_column("llm_calls", sa.Column("mission_run_id", _UUID, nullable=True))
    op.add_column("llm_calls", sa.Column("task_id", _UUID, nullable=True))
    op.create_index("ix_llm_calls_mission_run_id", "llm_calls", ["mission_run_id"])
    op.create_index("ix_llm_calls_task_id", "llm_calls", ["task_id"])

    # 9. Drop the never-written re-plan link.
    op.drop_constraint(
        "execution_records_parent_execution_record_id_fkey", "execution_records", type_="foreignkey"
    )
    op.drop_column("execution_records", "parent_execution_record_id")


def downgrade() -> None:
    # 9.
    op.add_column(
        "execution_records",
        sa.Column("parent_execution_record_id", _UUID, nullable=True),
    )
    op.create_foreign_key(
        "execution_records_parent_execution_record_id_fkey",
        "execution_records",
        "execution_records",
        ["parent_execution_record_id"],
        ["id"],
    )
    op.create_index(
        "ix_execution_records_parent_execution_record_id",
        "execution_records",
        ["parent_execution_record_id"],
    )

    # 8.
    op.drop_index("ix_llm_calls_task_id", table_name="llm_calls")
    op.drop_index("ix_llm_calls_mission_run_id", table_name="llm_calls")
    op.drop_column("llm_calls", "task_id")
    op.drop_column("llm_calls", "mission_run_id")

    # 7a.
    op.drop_index("ix_task_executions_failure_fingerprint", table_name="task_executions")
    op.drop_column("task_executions", "failure_json")
    for table in _FAILURE_TABLES:
        op.drop_column(table, "failure_fingerprint")
        op.drop_column(table, "failure_class")
        op.drop_column(table, "failure_origin")

    # 7.
    op.drop_index("ix_context_changes_context_version", table_name="context_changes")

    # 6.
    op.drop_index("ix_context_changes_mission_run_id", table_name="context_changes")
    op.drop_constraint("uq_task_executions_idempotency_key", "task_executions", type_="unique")
    op.drop_index("ix_task_executions_mission_run_id", table_name="task_executions")
    op.drop_index("uq_execution_records_run", table_name="execution_records")
    op.drop_index("ix_tasks_run_status", table_name="tasks")
    op.drop_column("task_executions", "idempotency_key")
    for table in ("context_changes", "task_executions", "execution_records", "tasks"):
        op.drop_column(table, "mission_run_id")

    # 5 to 2. Dropping the tables drops their indexes and constraints.
    op.drop_table("mission_run_digests")
    op.drop_table("mission_runs")

    # 1.
    op.drop_column("missions", "run_sequence_counter")
