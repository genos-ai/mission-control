"""Create context_milestones table.

Missing migration for ContextMilestone model (Plan 18).
The model existed but the table was never created.

Revision ID: plan18_milestones
Revises: plan51_widen_decision_type
"""

from alembic import op
import sqlalchemy as sa

revision = "plan18_milestones"
down_revision = "plan51_004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "context_milestones",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column(
            "mission_id",
            sa.String(36),
            sa.ForeignKey("missions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("version_snapshot", sa.Integer, nullable=False),
        sa.Column("context_snapshot", sa.JSON, nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("context_milestones")
