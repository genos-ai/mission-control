"""create gate_requests table

API-backed gate mode: parks the dispatch / wave engine / autonomy loop at
each gate point until a CLI / UI client POSTs a decision. Pattern mirrors
human_input_requests (Plan 45) — a pending row + Temporal-style wait,
unblocked by an HTTP POST that writes the decision back.

Revision ID: plan80g_001
Revises: plan75_001
Create Date: 2026-05-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "plan80g_001"
down_revision: Union[str, None] = "plan75_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.dialects.postgresql import UUID as PgUUID

    op.create_table(
        "gate_requests",
        sa.Column("id", PgUUID(as_uuid=False), primary_key=True),
        sa.Column(
            "mission_id", PgUUID(as_uuid=False),
            sa.ForeignKey("missions.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "plan_id", PgUUID(as_uuid=False),
            sa.ForeignKey("mission_plans.id", ondelete="SET NULL"),
            nullable=True, index=True,
        ),
        sa.Column("gate_type", sa.String(50), nullable=False, index=True),
        sa.Column("context_json", JSONB(), nullable=False),
        sa.Column(
            "status", sa.String(20), nullable=False,
            server_default="PENDING", index=True,
        ),
        sa.Column("decision_json", JSONB(), nullable=True),
        sa.Column(
            "decided_by_user_id", PgUUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timed_out_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_gate_requests_mission_status",
        "gate_requests", ["mission_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_gate_requests_mission_status", table_name="gate_requests")
    op.drop_table("gate_requests")
