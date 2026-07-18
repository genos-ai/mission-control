"""add session_id to gate_requests

Per P15 (session is the transport primitive), every gate fires within
an execution session. Plumbing session_id into the GateContext also
unlocks event-bus emission keyed on the session.

Revision ID: plan80g_002
Revises: plan80g_001
Create Date: 2026-05-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "plan80g_002"
down_revision: Union[str, None] = "plan80g_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from sqlalchemy.dialects.postgresql import UUID as PgUUID

    op.add_column(
        "gate_requests",
        sa.Column(
            "session_id",
            PgUUID(as_uuid=False),
            sa.ForeignKey("sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_gate_requests_session_id",
        "gate_requests",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_gate_requests_session_id", table_name="gate_requests")
    op.drop_column("gate_requests", "session_id")
