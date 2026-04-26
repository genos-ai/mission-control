"""create human_input_requests table

Revision ID: plan45_001
Revises: plan40_001
Create Date: 2026-04-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "plan45_001"
down_revision: Union[str, None] = "timezone_aware_timestamps"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create human_input_requests table (Plan 45 Phase 4)."""
    from sqlalchemy.dialects.postgresql import UUID as PgUUID

    op.create_table(
        "human_input_requests",
        sa.Column("id", PgUUID(as_uuid=False), primary_key=True),
        sa.Column("workflow_run_id", PgUUID(as_uuid=False), sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("step_id", sa.String(100), nullable=False),
        sa.Column("mission_id", PgUUID(as_uuid=False), sa.ForeignKey("missions.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("session_id", PgUUID(as_uuid=False), sa.ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("temporal_workflow_id", sa.String(200), nullable=False),
        sa.Column("prompt_message", sa.Text(), nullable=False),
        sa.Column("channel", sa.String(50), nullable=False, server_default="telegram"),
        sa.Column("choices_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING", index=True),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("responder_id", sa.String(200), nullable=True),
        sa.Column("timeout_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    """Drop human_input_requests table."""
    op.drop_table("human_input_requests")
