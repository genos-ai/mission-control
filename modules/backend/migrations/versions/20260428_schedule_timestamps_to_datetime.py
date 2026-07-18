"""Convert workflow_schedules.last_fired_at and next_fire_at from varchar to timestamptz.

These columns were created as String(30) storing ISO-formatted strings,
but should be proper DateTime(timezone=True) columns consistent with every
other timestamp in the schema (Plan 64 Phase I). Existing ISO strings are
cast to timestamptz, interpreted as UTC.

Revision ID: schedule_timestamps_to_datetime
Revises: plan45_001
Create Date: 2026-04-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "schedule_timestamps_to_datetime"
down_revision: Union[str, None] = "plan45_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Cast existing ISO strings to timestamptz, interpreting as UTC.
    # NULLs pass through unchanged.
    for column in ("last_fired_at", "next_fire_at"):
        conn.execute(
            sa.text(
                f"ALTER TABLE workflow_schedules "
                f'ALTER COLUMN "{column}" TYPE timestamptz '
                f"USING \"{column}\"::timestamp AT TIME ZONE 'UTC'"
            )
        )


def downgrade() -> None:
    conn = op.get_bind()

    for column in ("last_fired_at", "next_fire_at"):
        conn.execute(
            sa.text(
                f"ALTER TABLE workflow_schedules "
                f'ALTER COLUMN "{column}" TYPE varchar(30) '
                f"USING to_char(\"{column}\" AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS')"
            )
        )
