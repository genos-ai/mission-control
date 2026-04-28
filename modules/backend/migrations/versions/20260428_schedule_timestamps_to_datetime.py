"""Convert workflow_schedules.last_fired_at and next_fire_at from varchar to timestamp.

These columns were created as String(30) storing ISO-formatted strings,
but should be proper DateTime columns consistent with the rest of the schema.
The timezone-aware timestamps migration (Plan 64) missed them because they
were varchar, not timestamp. Existing ISO strings are cast to timestamp.

Revision ID: schedule_timestamps_to_datetime
Revises: plan45_001
Create Date: 2026-04-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "schedule_timestamps_to_datetime"
down_revision: Union[str, None] = "plan45_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Cast existing ISO strings to timestamp. NULLs pass through unchanged.
    for column in ("last_fired_at", "next_fire_at"):
        conn.execute(sa.text(
            f'ALTER TABLE workflow_schedules '
            f'ALTER COLUMN "{column}" TYPE timestamp '
            f'USING "{column}"::timestamp'
        ))


def downgrade() -> None:
    conn = op.get_bind()

    for column in ("last_fired_at", "next_fire_at"):
        conn.execute(sa.text(
            f'ALTER TABLE workflow_schedules '
            f'ALTER COLUMN "{column}" TYPE varchar(30) '
            f"USING to_char(\"{column}\", 'YYYY-MM-DD\"T\"HH24:MI:SS')"
        ))
