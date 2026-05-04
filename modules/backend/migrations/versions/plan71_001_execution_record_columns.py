"""Plan 71: Add workflow step tracking columns to execution_records.

Adds workflow_run_id, workflow_step_id, execution_environment, and
cost_ceiling_usd so execution_records can fully replace the executions
table for workflow step tracking.

Revision ID: plan71_001
Revises: plan60_002
Create Date: 2026-05-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "plan71_001"
down_revision = "schedule_timestamps_to_datetime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "execution_records",
        sa.Column(
            "workflow_run_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"),
            nullable=True,
            comment="Parent workflow run (null for non-workflow executions)",
        ),
    )
    op.create_index(
        "ix_execution_records_workflow_run_id",
        "execution_records",
        ["workflow_run_id"],
    )

    op.add_column(
        "execution_records",
        sa.Column(
            "workflow_step_id",
            sa.String(100),
            nullable=True,
            comment="Step ID within the workflow definition",
        ),
    )

    op.add_column(
        "execution_records",
        sa.Column(
            "execution_environment",
            sa.String(20),
            nullable=True,
            comment="Execution environment: local, worktree, container",
        ),
    )

    op.add_column(
        "execution_records",
        sa.Column(
            "cost_ceiling_usd",
            sa.Numeric(12, 6, asdecimal=False),
            nullable=True,
            comment="Per-step budget cap",
        ),
    )


def downgrade() -> None:
    op.drop_column("execution_records", "cost_ceiling_usd")
    op.drop_column("execution_records", "execution_environment")
    op.drop_column("execution_records", "workflow_step_id")
    op.drop_index("ix_execution_records_workflow_run_id", table_name="execution_records")
    op.drop_column("execution_records", "workflow_run_id")
