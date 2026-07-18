"""Plan 71: Drop the executions table.

All consumers have been migrated to execution_records. The executions
table is no longer written to or read from by any code path.

Safety: Run SELECT count(*) FROM executions WHERE status IN ('PENDING','RUNNING')
before deploying. If any rows are in-flight, wait for them to complete.

Revision ID: plan71_002
Revises: plan71_001
Create Date: 2026-05-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "plan71_002"
down_revision = "plan71_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("executions")


def downgrade() -> None:
    op.create_table(
        "executions",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("workflow_step_id", sa.String(100), nullable=True),
        sa.Column("mission_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("roster_ref", sa.String(100), nullable=False, server_default="default"),
        sa.Column("complexity_tier", sa.String(20), nullable=False, server_default="simple"),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("session_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("trigger_type", sa.String(50), nullable=False, server_default="on_demand"),
        sa.Column("triggered_by", sa.String(200), nullable=False),
        sa.Column("upstream_context", postgresql.JSON(), nullable=False, server_default="{}"),
        sa.Column("context", postgresql.JSON(), nullable=False, server_default="{}"),
        sa.Column("total_cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("cost_ceiling_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_data", postgresql.JSON(), nullable=True),
        sa.Column("execution_outcome", postgresql.JSON(), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("execution_environment", sa.String(20), nullable=False, server_default="local"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_executions_status", "executions", ["status"])
    op.create_index("ix_executions_workflow_run_id", "executions", ["workflow_run_id"])
    op.create_index("ix_executions_mission_id", "executions", ["mission_id"])
    op.create_index("ix_executions_session_id", "executions", ["session_id"])
