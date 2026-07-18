"""Plan 51 Phase C — execution_records task counts + mission_plans supervisor counters

Two additive schema changes for the post-run gate checkpoint:

1. ``execution_records.completed_task_count`` + ``failed_task_count`` (INT,
   default 0) — denormalised from ``outcome.task_results`` at write-back
   time. The stall breaker reads these directly and
   ``MissionPlanRunCompletedEvent`` carries the same values.

2. ``mission_plans.supervisor_iteration_count`` (INT, default 0) +
   ``max_supervisor_iterations`` (INT, default 20) — the iteration
   counter and circuit breaker ceiling for the autonomy loop. The
   counter resets on user-initiated ``refine_plan``; the ceiling is
   user-configurable per mission.

All columns are NOT NULL with server_default so existing rows backfill
cleanly. No data migration needed — zero is the correct initial value
for all four columns on existing rows.

Revision ID: plan51_002
Revises: plan51_001
Create Date: 2026-04-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "plan51_002"
down_revision: Union[str, None] = "plan51_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(bind: sa.Connection, table: str, column: str) -> bool:
    cols = {c["name"] for c in inspect(bind).get_columns(table)}
    return column in cols


def upgrade() -> None:
    bind = op.get_bind()

    # execution_records: denormalised task counts
    if not _column_exists(bind, "execution_records", "completed_task_count"):
        op.add_column(
            "execution_records",
            sa.Column(
                "completed_task_count",
                sa.Integer,
                nullable=False,
                server_default="0",
                comment="Count of tasks with status SUCCESS in this run.",
            ),
        )
    if not _column_exists(bind, "execution_records", "failed_task_count"):
        op.add_column(
            "execution_records",
            sa.Column(
                "failed_task_count",
                sa.Integer,
                nullable=False,
                server_default="0",
                comment="Count of tasks with status FAILED in this run.",
            ),
        )

    # mission_plans: supervisor autonomy loop counters
    if not _column_exists(bind, "mission_plans", "supervisor_iteration_count"):
        op.add_column(
            "mission_plans",
            sa.Column(
                "supervisor_iteration_count",
                sa.Integer,
                nullable=False,
                server_default="0",
                comment=(
                    "How many times the post-run supervisor has been invoked. "
                    "Resets on user-initiated refine_plan or new plan creation."
                ),
            ),
        )
    if not _column_exists(bind, "mission_plans", "max_supervisor_iterations"):
        op.add_column(
            "mission_plans",
            sa.Column(
                "max_supervisor_iterations",
                sa.Integer,
                nullable=False,
                server_default="20",
                comment=(
                    "Circuit breaker: if supervisor_iteration_count >= this, "
                    "the supervisor short-circuits to ESCALATE."
                ),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    for table, col in [
        ("execution_records", "completed_task_count"),
        ("execution_records", "failed_task_count"),
        ("mission_plans", "supervisor_iteration_count"),
        ("mission_plans", "max_supervisor_iterations"),
    ]:
        if _column_exists(bind, table, col):
            op.drop_column(table, col)
