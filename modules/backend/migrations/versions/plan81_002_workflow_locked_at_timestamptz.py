"""workflow_definitions.locked_at -> timestamptz

The original phase-2 schema created `workflow_definitions.locked_at`
as `String(30)` (see 20260320_phase2_schema_expansion.py). The Plan 64
timezone-aware migration (20260426_timezone_aware_timestamps.py) swept
the codebase to `timestamptz` but missed this one column. As a result:

- The model was declared `Mapped[datetime | None]` with no explicit
  type, so SQLAlchemy generated bind parameters as
  `TIMESTAMP WITHOUT TIME ZONE` — incompatible with tz-aware values
  from `utc_now()`.
- `WorkflowDefinitionService.lock_workflow` papered over the model
  bug with `utc_now().replace(microsecond=0, tzinfo=None)` — making
  it work for the lock path only.
- `workflow_design.update_workflow` (the architect's save path) used
  the natural `utc_now()` and crashed with
  "can't subtract offset-naive and offset-aware datetimes".

This migration aligns the column with the rest of the schema. It is
idempotent: handles both the original `character varying(30)` state
and the partially-migrated `timestamp without time zone` state, and
is a no-op if the column is already `timestamp with time zone` (as
the dev DB happened to be after an out-of-band ALTER that left no
migration trail).

Revision ID: plan81_002
Revises: plan81_001
Create Date: 2026-05-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "plan81_002"
down_revision: Union[str, None] = "plan81_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("""
        DO $$
        DECLARE
            current_type text;
        BEGIN
            SELECT data_type INTO current_type
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name   = 'workflow_definitions'
              AND column_name  = 'locked_at';

            IF current_type = 'character varying' THEN
                ALTER TABLE workflow_definitions
                    ALTER COLUMN locked_at TYPE timestamptz
                    USING NULLIF(locked_at, '')::timestamptz;
            ELSIF current_type = 'timestamp without time zone' THEN
                ALTER TABLE workflow_definitions
                    ALTER COLUMN locked_at TYPE timestamptz
                    USING locked_at AT TIME ZONE 'UTC';
            END IF;
        END $$;
    """))


def downgrade() -> None:
    # Revert to naive timestamp (the type at the point this migration ran
    # in environments where it actually did something). String(30) is not
    # restored — that representation was never desirable.
    op.execute(sa.text("""
        ALTER TABLE workflow_definitions
            ALTER COLUMN locked_at TYPE timestamp
            USING locked_at AT TIME ZONE 'UTC';
    """))
