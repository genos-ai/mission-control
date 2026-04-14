"""Add execution_record_id FK to workflow_runs.

Links each WorkflowRun to a parent ExecutionRecord so workflow runs
appear in the Runs tab alongside single-agent executions.

Revision ID: workflow_run_exec_record
Revises: workflow_system_unique
"""

from alembic import op
import sqlalchemy as sa

revision = "workflow_run_exec_record"
down_revision = "workflow_system_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column(
            "execution_record_id",
            sa.String(36),
            sa.ForeignKey("execution_records.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "execution_record_id")
