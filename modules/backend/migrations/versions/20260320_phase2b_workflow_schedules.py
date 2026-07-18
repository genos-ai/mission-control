"""Phase 2b: Add workflow_schedules table.

Revision ID: phase2_002
Revises: phase2_001
Create Date: 2026-03-20
"""

import sqlalchemy as sa
from alembic import op

revision = "phase2_002"
down_revision = "phase2_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_schedules",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "workflow_definition_id",
            sa.String(length=36),
            sa.ForeignKey("workflow_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mission_id",
            sa.String(length=36),
            sa.ForeignKey("missions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cron_expression", sa.String(length=100), nullable=False),
        sa.Column("timezone", sa.String(length=50), nullable=False, server_default="UTC"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("budget_per_run_usd", sa.Float(), nullable=True),
        sa.Column("max_iterations", sa.Integer(), nullable=True),
        sa.Column("iteration_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_fired_at", sa.String(length=30), nullable=True),
        sa.Column("next_fire_at", sa.String(length=30), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_workflow_schedules_workflow_def_id", "workflow_schedules", ["workflow_definition_id"]
    )
    op.create_index("ix_workflow_schedules_mission_id", "workflow_schedules", ["mission_id"])
    op.create_index("ix_workflow_schedules_enabled", "workflow_schedules", ["enabled"])


def downgrade() -> None:
    op.drop_table("workflow_schedules")
