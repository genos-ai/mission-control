"""Add status and updated_at columns to session_messages for persist-first SSE.

Plan 56 Phase A: Incremental response persistence. The status column tracks
whether a message is still streaming ('streaming'), complete ('complete'),
or errored ('failed'). The updated_at column records when content was last
flushed during streaming.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260414_msg_status"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "session_messages",
        sa.Column("status", sa.String(20), nullable=False, server_default="complete"),
    )
    op.add_column(
        "session_messages",
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("session_messages", "updated_at")
    op.drop_column("session_messages", "status")
