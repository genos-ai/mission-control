"""Per-task cost + duration metrics on plan_task_states
(Plan 46 Phase 2 work unit #2)

Adds ``cost_usd`` and ``duration_seconds`` columns to the
``plan_task_states`` table so the Plan tab's Done cards can render
``$X.XX · Ns`` without cracking open the full ExecutionOutcome JSON
on every card.

Both values are already produced per-task by the dispatch loop and
persisted to ``task_executions``; this migration denormalises them
onto ``plan_task_states`` so the Plan tab has a single-row read path.
Written at run completion by
``MissionPlanService._write_back_task_results``.

Defaults to 0.0 (not NULL) because:
  1. Terminal tasks always have a numeric value — a completed run
     always reports a cost and duration, even if the duration is
     approximate.
  2. Pre-run statuses (proposed/approved/queued) reasonably show
     "0.0" as "no cost incurred yet", which is correct.
  3. NULL-vs-zero distinction has no user-visible meaning here.

Revision ID: phase2_metrics
Revises: plan43_001
Create Date: 2026-04-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# Revision identifiers
revision: str = "phase2_metrics"
down_revision: Union[str, None] = "plan43_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(bind: sa.Connection, table: str, column: str) -> bool:
    cols = {c["name"] for c in inspect(bind).get_columns(table)}
    return column in cols


def upgrade() -> None:
    """Add cost_usd + duration_seconds to plan_task_states."""
    bind = op.get_bind()

    if not _has_column(bind, "plan_task_states", "cost_usd"):
        op.add_column(
            "plan_task_states",
            sa.Column(
                "cost_usd",
                sa.Float,
                nullable=False,
                server_default="0.0",
                comment=(
                    "Cost in USD for this task's most recent attempt. "
                    "Denormalised from task_executions at write-back "
                    "time by MissionPlanService._write_back_task_results "
                    "so the Plan tab can render $X.XX per card without "
                    "joining against task_executions."
                ),
            ),
        )

    if not _has_column(bind, "plan_task_states", "duration_seconds"):
        op.add_column(
            "plan_task_states",
            sa.Column(
                "duration_seconds",
                sa.Float,
                nullable=False,
                server_default="0.0",
                comment=(
                    "Wall-clock duration in seconds for this task's most "
                    "recent attempt. Same denormalisation rationale as "
                    "cost_usd."
                ),
            ),
        )


def downgrade() -> None:
    """Remove cost_usd + duration_seconds columns."""
    bind = op.get_bind()

    if _has_column(bind, "plan_task_states", "duration_seconds"):
        op.drop_column("plan_task_states", "duration_seconds")

    if _has_column(bind, "plan_task_states", "cost_usd"):
        op.drop_column("plan_task_states", "cost_usd")
