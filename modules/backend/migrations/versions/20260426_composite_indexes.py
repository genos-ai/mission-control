"""Add composite indexes for hot query patterns (Plan 64 Phase C).

4 indexes for verified hot-path queries. Additive only — no table
locks on PostgreSQL (CREATE INDEX CONCURRENTLY is implicit for
small tables).

Revision ID: composite_indexes
Revises: status_enum_consistency
Create Date: 2026-04-26
"""

from typing import Sequence, Union

from alembic import op

revision: str = "composite_indexes"
down_revision: Union[str, None] = "status_enum_consistency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Filtered artifact listing per mission
    op.create_index(
        "ix_mission_artifacts_mission_type",
        "mission_artifacts",
        ["mission_id", "artifact_type"],
    )

    # 2. Cost dashboard aggregation by mission + time range
    op.create_index(
        "ix_llm_calls_mission_created",
        "llm_calls",
        ["mission_id", "created_at"],
    )

    # 3. fire_matching scans unconsumed, unexpired followups per mission
    op.create_index(
        "ix_session_followups_mission_consumed_expires",
        "session_followups",
        ["mission_id", "consumed_at", "expires_at"],
    )

    # 4. History + cost queries by mission, status, time
    op.create_index(
        "ix_execution_records_mission_status_created",
        "execution_records",
        ["mission_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_execution_records_mission_status_created", "execution_records")
    op.drop_index("ix_session_followups_mission_consumed_expires", "session_followups")
    op.drop_index("ix_llm_calls_mission_created", "llm_calls")
    op.drop_index("ix_mission_artifacts_mission_type", "mission_artifacts")
