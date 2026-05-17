"""Plan 72: Promote Task to first-class entity.

Creates the `tasks` and `task_dependencies` tables.
Migrates data from `mission_plans.task_plan_json` and `plan_task_states`
into the new tables. Adds plan-level metadata columns to `mission_plans`.
Drops `plan_task_states` and removes `task_plan_json` columns.

Run scripts/validate_task_migration.py BEFORE this migration to audit
data integrity. This migration handles corrupt/orphaned records gracefully
(sets FK to NULL, logs warning) but the validation script catches issues
upfront.

Revision ID: plan72_001
Revises: plan71_002
Create Date: 2026-05-17
"""

import json
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID

revision = "plan72_001"
down_revision = "plan71_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Create new tables ───────────────────────────────────────────────

    op.create_table(
        "tasks",
        sa.Column("id", PgUUID(as_uuid=False), primary_key=True),
        sa.Column("mission_id", PgUUID(as_uuid=False),
                  sa.ForeignKey("missions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_id", PgUUID(as_uuid=False),
                  sa.ForeignKey("mission_plans.id", ondelete="CASCADE"), nullable=False, index=True),
        # Definition
        sa.Column("agent", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("instructions", sa.Text, nullable=False, server_default=""),
        sa.Column("inputs_json", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("verification_json", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("constraints_json", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("domain_tags", sa.JSON, nullable=False, server_default="[]"),
        # State
        sa.Column("status", sa.String(20), nullable=False, server_default="PROPOSED"),
        sa.Column("approved_by_user_id", PgUUID(as_uuid=False),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("veto_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        # Result
        sa.Column("result_summary", sa.Text, nullable=True),
        sa.Column("failure_reason", sa.Text, nullable=True),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0.0"),
        sa.Column("duration_seconds", sa.Numeric(12, 6), nullable=False, server_default="0.0"),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )

    op.create_index("ix_tasks_mission_id_status", "tasks", ["mission_id", "status"])
    op.create_index("ix_tasks_plan_id_status", "tasks", ["plan_id", "status"])
    op.create_index("ix_tasks_plan_id_created_at", "tasks", ["plan_id", "created_at"])

    op.create_table(
        "task_dependencies",
        sa.Column("id", PgUUID(as_uuid=False), primary_key=True),
        sa.Column("task_id", PgUUID(as_uuid=False),
                  sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("depends_on_id", PgUUID(as_uuid=False),
                  sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("task_id", "depends_on_id", name="uq_task_dep_edge"),
        sa.CheckConstraint("task_id != depends_on_id", name="ck_task_dep_no_self"),
    )

    op.create_index("ix_task_dependencies_task_id", "task_dependencies", ["task_id"])
    op.create_index("ix_task_dependencies_depends_on_id", "task_dependencies", ["depends_on_id"])

    # ── 2. Add plan-level metadata columns to mission_plans ────────────────

    op.add_column("mission_plans", sa.Column(
        "summary", sa.Text, nullable=False, server_default=""))
    op.add_column("mission_plans", sa.Column(
        "estimated_cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0.0"))
    op.add_column("mission_plans", sa.Column(
        "estimated_duration", sa.Integer, nullable=False, server_default="0"))
    op.add_column("mission_plans", sa.Column(
        "execution_hints_json", sa.JSON, nullable=False, server_default="{}"))

    # ── 3. Add task_id FK to mission_artifacts ─────────────────────────────

    op.add_column("mission_artifacts", sa.Column(
        "task_id", PgUUID(as_uuid=False),
        sa.ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True))

    # ── 4. Data migration ──────────────────────────────────────────────────

    conn = op.get_bind()

    # Migrate plans with task_plan_json
    plans = conn.execute(sa.text(
        "SELECT id, mission_id, task_plan_json, version "
        "FROM mission_plans WHERE task_plan_json IS NOT NULL"
    )).fetchall()

    for plan in plans:
        plan_id = plan[0]
        mission_id = plan[1]
        task_plan_raw = plan[2]

        # Parse JSON (may already be dict from psycopg)
        if isinstance(task_plan_raw, str):
            try:
                task_plan = json.loads(task_plan_raw)
            except (json.JSONDecodeError, TypeError):
                # Corrupt JSON — skip this plan, log via print (Alembic)
                print(f"  WARNING: Corrupt task_plan_json in plan {plan_id}, skipping")
                continue
        else:
            task_plan = task_plan_raw

        if not task_plan or "tasks" not in task_plan:
            continue

        # Update plan-level metadata
        summary = task_plan.get("summary", "")
        est_cost = task_plan.get("estimated_cost_usd", 0.0)
        est_dur = task_plan.get("estimated_duration_seconds", 0)
        hints = task_plan.get("execution_hints", {})

        conn.execute(sa.text(
            "UPDATE mission_plans SET summary = :summary, "
            "estimated_cost_usd = :cost, estimated_duration = :dur, "
            "execution_hints_json = :hints WHERE id = :plan_id"
        ), {
            "summary": summary or "",
            "cost": est_cost or 0.0,
            "dur": est_dur or 0,
            "hints": json.dumps(hints) if isinstance(hints, dict) else "{}",
            "plan_id": plan_id,
        })

        # Build string-key -> UUID mapping for this plan
        key_to_uuid: dict[str, str] = {}
        tasks_data = task_plan["tasks"]

        for task_def in tasks_data:
            old_task_id = task_def.get("task_id", "")
            new_uuid = str(uuid4())
            key_to_uuid[old_task_id] = new_uuid

            # Extract fields
            agent = task_def.get("agent", "unknown")
            description = task_def.get("description", "")
            instructions = task_def.get("instructions", "")
            inputs = task_def.get("inputs", {})
            verification = task_def.get("verification", {})
            constraints = task_def.get("constraints", {})
            domain_tags = task_def.get("domain_tags", [])

            # Look up corresponding PlanTaskState for status
            state_row = conn.execute(sa.text(
                "SELECT status, approved_by_user_id, approved_at, "
                "veto_expires_at, retry_count, last_attempt_at, "
                "result_summary, failure_reason, cost_usd, duration_seconds "
                "FROM plan_task_states "
                "WHERE mission_plan_id = :plan_id AND task_id = :task_id"
            ), {"plan_id": plan_id, "task_id": old_task_id}).fetchone()

            if state_row:
                status = state_row[0] or "PROPOSED"
                approved_by = state_row[1]
                approved_at = state_row[2]
                veto_expires = state_row[3]
                retry_count = state_row[4] or 0
                last_attempt = state_row[5]
                result_summary = state_row[6]
                failure_reason = state_row[7]
                cost_usd = state_row[8] or 0.0
                duration_secs = state_row[9] or 0.0
            else:
                status = "PROPOSED"
                approved_by = None
                approved_at = None
                veto_expires = None
                retry_count = 0
                last_attempt = None
                result_summary = None
                failure_reason = None
                cost_usd = 0.0
                duration_secs = 0.0

            conn.execute(sa.text(
                "INSERT INTO tasks (id, mission_id, plan_id, agent, description, "
                "instructions, inputs_json, verification_json, constraints_json, "
                "domain_tags, status, approved_by_user_id, approved_at, "
                "veto_expires_at, retry_count, last_attempt_at, "
                "result_summary, failure_reason, cost_usd, duration_seconds, "
                "created_at, updated_at) "
                "VALUES (:id, :mission_id, :plan_id, :agent, :description, "
                ":instructions, :inputs_json, :verification_json, :constraints_json, "
                ":domain_tags, :status, :approved_by, :approved_at, "
                ":veto_expires, :retry_count, :last_attempt, "
                ":result_summary, :failure_reason, :cost_usd, :duration_secs, "
                "NOW(), NOW())"
            ), {
                "id": new_uuid,
                "mission_id": mission_id,
                "plan_id": plan_id,
                "agent": agent,
                "description": description,
                "instructions": instructions or "",
                "inputs_json": json.dumps(inputs) if isinstance(inputs, dict) else "{}",
                "verification_json": json.dumps(verification) if isinstance(verification, dict) else "{}",
                "constraints_json": json.dumps(constraints) if isinstance(constraints, dict) else "{}",
                "domain_tags": json.dumps(domain_tags) if isinstance(domain_tags, list) else "[]",
                "status": status,
                "approved_by": approved_by,
                "approved_at": approved_at,
                "veto_expires": veto_expires,
                "retry_count": retry_count,
                "last_attempt": last_attempt,
                "result_summary": result_summary,
                "failure_reason": failure_reason,
                "cost_usd": cost_usd,
                "duration_secs": duration_secs,
            })

        # Create dependency edges
        for task_def in tasks_data:
            old_task_id = task_def.get("task_id", "")
            task_uuid = key_to_uuid.get(old_task_id)
            if not task_uuid:
                continue
            for dep_key in task_def.get("dependencies", []):
                dep_uuid = key_to_uuid.get(dep_key)
                if dep_uuid:
                    conn.execute(sa.text(
                        "INSERT INTO task_dependencies (id, task_id, depends_on_id) "
                        "VALUES (:id, :task_id, :dep_id)"
                    ), {
                        "id": str(uuid4()),
                        "task_id": task_uuid,
                        "dep_id": dep_uuid,
                    })

        # Backfill task_executions.task_id (string -> UUID)
        # For each task_execution referencing this plan's old task_ids
        for old_key, new_uuid in key_to_uuid.items():
            conn.execute(sa.text(
                "UPDATE task_executions SET task_id = :new_id "
                "WHERE task_id = :old_id AND execution_record_id IN "
                "(SELECT id FROM execution_records WHERE mission_id = :mission_id)"
            ), {"new_id": new_uuid, "old_id": old_key, "mission_id": mission_id})

            # Backfill execution_decisions.task_id
            conn.execute(sa.text(
                "UPDATE execution_decisions SET task_id = :new_id "
                "WHERE task_id = :old_id AND execution_record_id IN "
                "(SELECT id FROM execution_records WHERE mission_id = :mission_id)"
            ), {"new_id": new_uuid, "old_id": old_key, "mission_id": mission_id})

            # Backfill context_changes.task_id
            conn.execute(sa.text(
                "UPDATE context_changes SET task_id = :new_id "
                "WHERE task_id = :old_id"
            ), {"new_id": new_uuid, "old_id": old_key})

    # ── 5. Alter FK columns to UUID type ───────────────────────────────────
    # First make task_id nullable on all tables (some have NOT NULL constraint)
    for table in ("task_executions", "execution_decisions", "context_changes"):
        op.alter_column(table, "task_id", nullable=True)

    # NULL out any task_id values that weren't backfilled to UUIDs.
    # Without this, the ::uuid cast below will crash on old-format
    # strings like "v1-task-001" from orphaned/deleted plans.
    _uuid_pattern = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    for table in ("task_executions", "execution_decisions", "context_changes"):
        conn.execute(sa.text(
            f"UPDATE {table} SET task_id = NULL "
            f"WHERE task_id IS NOT NULL AND task_id !~ :pattern"
        ), {"pattern": _uuid_pattern})

    # For task_executions: alter column type
    op.alter_column("task_executions", "task_id",
                    type_=PgUUID(as_uuid=False),
                    nullable=True,
                    postgresql_using="task_id::uuid")

    # Add FK constraint
    op.create_foreign_key(
        "fk_task_executions_task_id",
        "task_executions", "tasks",
        ["task_id"], ["id"],
        ondelete="SET NULL",
    )

    # For execution_decisions: alter column type
    op.alter_column("execution_decisions", "task_id",
                    type_=PgUUID(as_uuid=False),
                    nullable=True,
                    postgresql_using="task_id::uuid")

    op.create_foreign_key(
        "fk_execution_decisions_task_id",
        "execution_decisions", "tasks",
        ["task_id"], ["id"],
        ondelete="SET NULL",
    )

    # For context_changes: alter column type
    op.alter_column("context_changes", "task_id",
                    type_=PgUUID(as_uuid=False),
                    nullable=True,
                    postgresql_using="task_id::uuid")

    op.create_foreign_key(
        "fk_context_changes_task_id",
        "context_changes", "tasks",
        ["task_id"], ["id"],
        ondelete="SET NULL",
    )

    # ── 6. Drop old tables and columns ─────────────────────────────────────

    op.drop_table("plan_task_states")
    op.drop_column("mission_plans", "task_plan_json")
    op.drop_column("execution_records", "task_plan_json")


def downgrade() -> None:
    # Re-add dropped columns
    op.add_column("execution_records", sa.Column(
        "task_plan_json", sa.JSON, nullable=True))
    op.add_column("mission_plans", sa.Column(
        "task_plan_json", sa.JSON, nullable=True))

    # Re-create plan_task_states
    op.create_table(
        "plan_task_states",
        sa.Column("id", PgUUID(as_uuid=False), primary_key=True),
        sa.Column("mission_plan_id", PgUUID(as_uuid=False),
                  sa.ForeignKey("mission_plans.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("task_id", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PROPOSED"),
        sa.Column("approved_by_user_id", PgUUID(as_uuid=False), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_record_id", PgUUID(as_uuid=False), nullable=True),
        sa.Column("task_execution_id", PgUUID(as_uuid=False), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("veto_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_summary", sa.Text, nullable=True),
        sa.Column("failure_reason", sa.Text, nullable=True),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0.0"),
        sa.Column("duration_seconds", sa.Numeric(12, 6), nullable=False, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("mission_plan_id", "task_id",
                            name="uq_plan_task_states_plan_task"),
    )

    # Drop FK constraints on altered columns
    op.drop_constraint("fk_context_changes_task_id", "context_changes", type_="foreignkey")
    op.drop_constraint("fk_execution_decisions_task_id", "execution_decisions", type_="foreignkey")
    op.drop_constraint("fk_task_executions_task_id", "task_executions", type_="foreignkey")

    # Revert column types to String
    op.alter_column("context_changes", "task_id",
                    type_=sa.String(100), nullable=True)
    op.alter_column("execution_decisions", "task_id",
                    type_=sa.String(200), nullable=True)
    op.alter_column("task_executions", "task_id",
                    type_=sa.String(200), nullable=False)

    # Drop task_id from mission_artifacts
    op.drop_column("mission_artifacts", "task_id")

    # Drop plan-level metadata columns
    op.drop_column("mission_plans", "execution_hints_json")
    op.drop_column("mission_plans", "estimated_duration")
    op.drop_column("mission_plans", "estimated_cost_usd")
    op.drop_column("mission_plans", "summary")

    # Drop new tables
    op.drop_table("task_dependencies")
    op.drop_table("tasks")
