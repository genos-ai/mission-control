"""Widen workflow_runs.status from varchar(9) to varchar(20).

The column was created before AWAITING_INPUT (14 chars) was added to
WorkflowRunState. Enum(native_enum=False) stores by NAME, so the column
must accommodate the longest name.

Revision ID: plan75_001
"""

from alembic import op
import sqlalchemy as sa

revision: str = "plan75_001"
down_revision: str = "plan74_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "workflow_runs",
        "status",
        type_=sa.String(20),
        existing_type=sa.String(9),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "workflow_runs",
        "status",
        type_=sa.String(9),
        existing_type=sa.String(20),
        existing_nullable=False,
    )
