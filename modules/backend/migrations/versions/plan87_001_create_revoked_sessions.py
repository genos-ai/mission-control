"""create revoked_sessions

Logout used to clear client state only, so a copied refresh token stayed valid
until it expired (7 days). Tokens now carry a session id (`sid`); logout stores
it here and token verification rejects it, which ends every access and refresh
token minted from that login, including earlier refreshes.

Rows are deleted once their `expires_at` passes (the daily cleanup).

Revision ID: plan87_001
Revises: strip_supervisor_decision_meta
Create Date: 2026-11-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "plan87_001"
down_revision: Union[str, None] = "strip_supervisor_decision_meta"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "revoked_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_revoked_sessions_user_id", "revoked_sessions", ["user_id"])
    op.create_index("ix_revoked_sessions_expires_at", "revoked_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_revoked_sessions_expires_at", table_name="revoked_sessions")
    op.drop_index("ix_revoked_sessions_user_id", table_name="revoked_sessions")
    op.drop_table("revoked_sessions")
