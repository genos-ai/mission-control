"""Convert started_at/completed_at from String to DateTime.

execution_records and task_executions stored timestamps as VARCHAR(30)
strings. Convert to proper TIMESTAMP columns so datetime arithmetic
works without parsing.

Revision ID: fix_timestamps
Revises: plan51_004
"""

from alembic import op

revision = "fix_timestamps"
down_revision = "plan51_004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # execution_records: started_at, completed_at
    op.execute(
        "ALTER TABLE execution_records "
        "ALTER COLUMN started_at TYPE TIMESTAMP USING started_at::timestamp"
    )
    op.execute(
        "ALTER TABLE execution_records "
        "ALTER COLUMN completed_at TYPE TIMESTAMP USING completed_at::timestamp"
    )

    # task_executions: started_at, completed_at
    op.execute(
        "ALTER TABLE task_executions "
        "ALTER COLUMN started_at TYPE TIMESTAMP USING started_at::timestamp"
    )
    op.execute(
        "ALTER TABLE task_executions "
        "ALTER COLUMN completed_at TYPE TIMESTAMP USING completed_at::timestamp"
    )


def downgrade() -> None:
    for table in ("execution_records", "task_executions"):
        op.execute(
            f"ALTER TABLE {table} "
            "ALTER COLUMN started_at TYPE VARCHAR(30) USING started_at::varchar"
        )
        op.execute(
            f"ALTER TABLE {table} "
            "ALTER COLUMN completed_at TYPE VARCHAR(30) USING completed_at::varchar"
        )
