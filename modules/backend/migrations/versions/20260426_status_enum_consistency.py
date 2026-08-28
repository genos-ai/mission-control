"""Standardise status columns to Enum(native_enum=False).

mission_plans.status, plan_task_states.status, and sessions.status
stored lowercase values via String(20). All other status columns use
Enum(native_enum=False) which stores uppercase NAME. This migration
uppercases the values and converts the column type.

Revision ID: status_enum_consistency
Revises: float_to_numeric_monetary
Create Date: 2026-04-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "status_enum_consistency"
down_revision: Union[str, None] = "float_to_numeric_monetary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Value mappings: lowercase value → uppercase NAME
MISSION_PLAN_STATUS = {
    "active": "ACTIVE",
    "paused": "PAUSED",
    "completed": "COMPLETED",
    "archived": "ARCHIVED",
}

PLAN_TASK_STATUS = {
    "proposed": "PROPOSED",
    "approved": "APPROVED",
    "queued": "QUEUED",
    "running": "RUNNING",
    "completed": "COMPLETED",
    "done": "COMPLETED",  # alias
    "failed": "FAILED",
    "skipped": "SKIPPED",
    "cancelled": "CANCELLED",
}

SESSION_STATUS = {
    "active": "ACTIVE",
    "completed": "COMPLETED",
    "expired": "EXPIRED",
    "archived": "ARCHIVED",
}

# Also fix session_messages.status (String(20), stores "complete"/"error")
MESSAGE_STATUS = {
    "complete": "COMPLETE",
    "error": "ERROR",
    "streaming": "STREAMING",
}


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Uppercase existing values
    for table, col, mapping in [
        ("mission_plans", "status", MISSION_PLAN_STATUS),
        ("plan_task_states", "status", PLAN_TASK_STATUS),
        ("sessions", "status", SESSION_STATUS),
        ("session_messages", "status", MESSAGE_STATUS),
    ]:
        for old_val, new_val in mapping.items():
            # table/col are literals from the static list above, never external input.
            conn.execute(
                sa.text(f'UPDATE "{table}" SET "{col}" = :new WHERE "{col}" = :old'),  # nosec B608
                {"old": old_val, "new": new_val},
            )

    # 2. Update server_default to uppercase
    op.alter_column("mission_plans", "status", server_default="ACTIVE")
    op.alter_column("plan_task_states", "status", server_default="PROPOSED")


def downgrade() -> None:
    conn = op.get_bind()

    # Reverse: uppercase → lowercase
    for table, col, mapping in [
        ("mission_plans", "status", MISSION_PLAN_STATUS),
        ("plan_task_states", "status", PLAN_TASK_STATUS),
        ("sessions", "status", SESSION_STATUS),
        ("session_messages", "status", MESSAGE_STATUS),
    ]:
        for old_val, new_val in mapping.items():
            # table/col are literals from the static list above, never external input.
            conn.execute(
                sa.text(f'UPDATE "{table}" SET "{col}" = :old WHERE "{col}" = :new'),  # nosec B608
                {"old": old_val, "new": new_val},
            )

    op.alter_column("mission_plans", "status", server_default="active")
    op.alter_column("plan_task_states", "status", server_default="proposed")
