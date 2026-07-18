"""Standardise timestamp columns: VARCHAR(30) → DateTime.

WorkflowRun and Execution used VARCHAR(30) for started_at/completed_at
while ExecutionRecord used DateTime. Standardise to DateTime everywhere
so callers don't need to know which model uses which type.

Existing ISO string data is converted via PostgreSQL CAST.

Revision ID: standardise_timestamps
Revises: workflow_run_exec_record
"""

import sqlalchemy as sa
from alembic import op

revision = "standardise_timestamps"
down_revision = "workflow_run_exec_record"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # workflow_runs: VARCHAR(30) → TIMESTAMP
    for col in ("started_at", "completed_at"):
        op.execute(
            f"ALTER TABLE workflow_runs "
            f"ALTER COLUMN {col} TYPE TIMESTAMP WITHOUT TIME ZONE "
            f"USING {col}::TIMESTAMP WITHOUT TIME ZONE"
        )

    # executions: VARCHAR(30) → TIMESTAMP
    for col in ("started_at", "completed_at"):
        op.execute(
            f"ALTER TABLE executions "
            f"ALTER COLUMN {col} TYPE TIMESTAMP WITHOUT TIME ZONE "
            f"USING {col}::TIMESTAMP WITHOUT TIME ZONE"
        )


def downgrade() -> None:
    for col in ("started_at", "completed_at"):
        op.execute(
            f"ALTER TABLE workflow_runs "
            f"ALTER COLUMN {col} TYPE VARCHAR(30) "
            f"USING {col}::VARCHAR(30)"
        )
    for col in ("started_at", "completed_at"):
        op.execute(
            f"ALTER TABLE executions "
            f"ALTER COLUMN {col} TYPE VARCHAR(30) "
            f"USING {col}::VARCHAR(30)"
        )
