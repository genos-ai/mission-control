"""Add 5 missing FK constraints on bare UUID columns.

These columns stored UUIDs but had no FK constraint — referential
integrity was not enforced by the database. Adding constraints now
that all columns are native PostgreSQL UUID type.

Orphaned references (sessions deleted but execution records remain)
are NULLed before constraints are added.

Revision ID: add_missing_fk_constraints
Revises: drop_notes_table
Create Date: 2026-04-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "add_missing_fk_constraints"
down_revision: Union[str, None] = "plan45_workflow_graph"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# New FK constraints to add
NEW_FKS = [
    {
        "constraint": "executions_workflow_run_id_fkey",
        "table": "executions",
        "column": "workflow_run_id",
        "target_table": "workflow_runs",
        "target_column": "id",
        "ondelete": "SET NULL",
    },
    {
        "constraint": "workflow_runs_session_id_fkey",
        "table": "workflow_runs",
        "column": "session_id",
        "target_table": "sessions",
        "target_column": "id",
        "ondelete": "SET NULL",
    },
    {
        "constraint": "executions_session_id_fkey",
        "table": "executions",
        "column": "session_id",
        "target_table": "sessions",
        "target_column": "id",
        "ondelete": "SET NULL",
    },
    {
        "constraint": "execution_records_session_id_fkey",
        "table": "execution_records",
        "column": "session_id",
        "target_table": "sessions",
        "target_column": "id",
        "ondelete": "SET NULL",
    },
    {
        "constraint": "context_changes_mission_id_fkey",
        "table": "context_changes",
        "column": "mission_id",
        "target_table": "missions",
        "target_column": "id",
        "ondelete": "CASCADE",
    },
]


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Make session_id columns nullable FIRST (before orphan cleanup)
    op.alter_column("execution_records", "session_id", nullable=True)
    op.alter_column("executions", "session_id", nullable=True)

    # 2. Clean orphaned references before adding constraints.
    # Table/column names below come from the static NEW_FKS constant defined
    # in this file, never external input.
    for fk in NEW_FKS:
        conn.execute(
            sa.text(  # nosec B608
                f"UPDATE \"{fk['table']}\" SET \"{fk['column']}\" = NULL "
                f"WHERE \"{fk['column']}\" IS NOT NULL "
                f"AND NOT EXISTS ("
                f"  SELECT 1 FROM \"{fk['target_table']}\" "
                f"  WHERE \"{fk['target_table']}\".\"{fk['target_column']}\" = "
                f"  \"{fk['table']}\".\"{fk['column']}\""
                f")"
            )
        )

    # 3. Add FK constraints
    for fk in NEW_FKS:
        op.create_foreign_key(
            fk["constraint"],
            fk["table"],
            fk["target_table"],
            [fk["column"]],
            [fk["target_column"]],
            ondelete=fk["ondelete"],
        )


def downgrade() -> None:
    for fk in NEW_FKS:
        op.drop_constraint(fk["constraint"], fk["table"], type_="foreignkey")

    # Restore NOT NULL on session_id columns
    op.alter_column("execution_records", "session_id", nullable=False)
    op.alter_column("executions", "session_id", nullable=False)
