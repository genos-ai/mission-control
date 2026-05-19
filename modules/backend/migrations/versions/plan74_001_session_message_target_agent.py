"""Add target_agent column to session_messages.

Stores which agent a user message was directed at in shared sessions (Plan 74).
Enables per-agent message filtering: when viewing Agent A's chat, only user
messages directed at Agent A (plus Agent A's responses) are shown.

NULL = legacy message (shown in all agent views for backward compatibility).

Revision ID: plan74_001
Revises: workflow_parameters_001
Create Date: 2026-05-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "plan74_001"
down_revision: Union[str, None] = "workflow_parameters_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "session_messages",
        sa.Column("target_agent", sa.String(100), nullable=True),
    )
    op.create_index(
        "ix_session_messages_target_agent",
        "session_messages",
        ["target_agent"],
    )


def downgrade() -> None:
    op.drop_index("ix_session_messages_target_agent", table_name="session_messages")
    op.drop_column("session_messages", "target_agent")
