"""Add task_type, task_params, temporal_workflow_id to execution_records.

Plan 56 Phase B: Extends ExecutionRecord to track background tasks forked
from Director tools (design_workflow, run_objective, run_workflow). One table
for "something ran", not two.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260414_bg_task"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "execution_records",
        sa.Column("task_type", sa.String(100), nullable=True, index=True),
    )
    op.add_column(
        "execution_records",
        sa.Column("task_params", sa.JSON(), nullable=True),
    )
    op.add_column(
        "execution_records",
        sa.Column("temporal_workflow_id", sa.String(200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("execution_records", "temporal_workflow_id")
    op.drop_column("execution_records", "task_params")
    op.drop_column("execution_records", "task_type")
