"""Create mission_events table for persisted narrative events.

Revision ID: mission_events_001
Revises: fix_timestamps
"""

import sqlalchemy as sa
from alembic import op

revision = "mission_events_001"
down_revision = "fix_timestamps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mission_events",
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
        sa.Column("session_id", sa.String(36), nullable=True, index=True),
        sa.Column("event_type", sa.String(100), nullable=False, index=True),
        sa.Column("timestamp", sa.String(30), nullable=False),
        sa.Column("source", sa.String(200), nullable=False, server_default=""),
        sa.Column("data", sa.JSON, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("mission_events")
