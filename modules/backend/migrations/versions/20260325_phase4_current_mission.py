"""Phase 4: Add current_mission_id to users table.

Revision ID: phase4_001
Revises: phase3_001
Create Date: 2026-03-25
"""

from alembic import op
import sqlalchemy as sa

revision = "phase4_001"
down_revision = "phase3_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("current_mission_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        "fk_users_current_mission_id",
        "users",
        "missions",
        ["current_mission_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_users_current_mission_id", "users", ["current_mission_id"])


def downgrade() -> None:
    op.drop_index("ix_users_current_mission_id", table_name="users")
    op.drop_constraint("fk_users_current_mission_id", "users", type_="foreignkey")
    op.drop_column("users", "current_mission_id")
