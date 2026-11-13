"""Durable gate request columns (Plan 88, 88.4.3)

gate_requests gains the run link (mission_run_id, FK mission_runs ON DELETE
CASCADE, indexed), task_id, the escalation and pause timestamps, the decision
channel and the AI recommendation (contracts 3.1.8). status widens to
VARCHAR(32) for ESCALATED. Legacy PENDING and TIMED_OUT rows with no run can
never be decided, so they become CANCELLED.

Downgrade is structural only; ESCALATED rows return to PENDING so the narrower
column holds them, and cancelled legacy rows stay cancelled.

Revision ID: plan88_006
Revises: plan88_005
Create Date: 2026-11-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID

revision: str = "plan88_006"
down_revision: Union[str, None] = "plan88_005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RUN_FK = "gate_requests_mission_run_id_fkey"  # the PostgreSQL default name, as create_all makes it
_RUN_INDEX = "ix_gate_requests_mission_run_id"
_TIMESTAMPS = ("escalate_at", "pause_at", "escalated_at")


def upgrade() -> None:
    # 1. Run link and durable-gate columns (3.1.8).
    op.add_column(
        "gate_requests",
        sa.Column("mission_run_id", PgUUID(as_uuid=False), nullable=True),
    )
    op.create_foreign_key(
        _RUN_FK,
        "gate_requests",
        "mission_runs",
        ["mission_run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(_RUN_INDEX, "gate_requests", ["mission_run_id"])
    op.add_column("gate_requests", sa.Column("task_id", PgUUID(as_uuid=False), nullable=True))
    for column in _TIMESTAMPS:
        op.add_column(
            "gate_requests",
            sa.Column(column, sa.DateTime(timezone=True), nullable=True),
        )
    op.add_column("gate_requests", sa.Column("decision_channel", sa.String(32), nullable=True))
    op.add_column("gate_requests", sa.Column("ai_recommendation_json", JSONB, nullable=True))

    # 2. Room for ESCALATED.
    op.alter_column(
        "gate_requests",
        "status",
        type_=sa.String(32),
        existing_type=sa.String(20),
        existing_nullable=False,
    )

    # 3. Legacy undecided rows have no run and can never be decided.
    op.execute(
        "UPDATE gate_requests SET status = 'CANCELLED' "
        "WHERE status IN ('PENDING','TIMED_OUT') AND mission_run_id IS NULL"
    )


def downgrade() -> None:
    op.execute("UPDATE gate_requests SET status = 'PENDING' WHERE status = 'ESCALATED'")
    op.alter_column(
        "gate_requests",
        "status",
        type_=sa.String(20),
        existing_type=sa.String(32),
        existing_nullable=False,
    )
    op.drop_column("gate_requests", "ai_recommendation_json")
    op.drop_column("gate_requests", "decision_channel")
    for column in reversed(_TIMESTAMPS):
        op.drop_column("gate_requests", column)
    op.drop_column("gate_requests", "task_id")
    op.drop_index(_RUN_INDEX, table_name="gate_requests")
    op.drop_constraint(_RUN_FK, "gate_requests", type_="foreignkey")
    op.drop_column("gate_requests", "mission_run_id")
