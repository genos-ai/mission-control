"""Convert all monetary Float columns to Numeric(12,6).

IEEE 754 floats cause rounding errors in cumulative cost accounting.
Numeric(12,6) gives exact decimal arithmetic up to $999,999.999999.

Revision ID: float_to_numeric_monetary
Revises: add_missing_fk_constraints
Create Date: 2026-04-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "float_to_numeric_monetary"
down_revision: Union[str, None] = "add_missing_fk_constraints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Every Float column that stores monetary values or cost-sensitive data.
# Format: (table, column)
MONETARY_COLUMNS = [
    # execution.py
    ("workflow_runs", "total_cost_usd"),
    ("workflow_runs", "budget_usd"),
    ("executions", "total_cost_usd"),
    ("executions", "cost_ceiling_usd"),
    # execution_record.py
    ("execution_records", "total_cost_usd"),
    ("task_executions", "cost_usd"),
    ("task_attempts", "cost_usd"),
    # mission.py
    ("missions", "budget_ceiling_usd"),
    # mission_plan.py
    ("mission_plans", "budget_usd_ceiling"),
    ("mission_plans", "total_spent_usd"),
    ("plan_task_states", "cost_usd"),
    ("plan_task_states", "duration_seconds"),
    # llm_call.py
    ("llm_calls", "cost_usd"),
    # model_pricing.py
    ("model_pricing", "price_per_mtok_input"),
    ("model_pricing", "price_per_mtok_output"),
    ("model_pricing", "price_per_mtok_cache_write_5m"),
    ("model_pricing", "price_per_mtok_cache_write_1h"),
    ("model_pricing", "price_per_mtok_cache_read"),
    # session.py
    ("sessions", "total_cost_usd"),
    ("sessions", "cost_budget_usd"),
    ("session_messages", "cost_usd"),
    # mission_learning.py
    ("mission_learnings", "confidence"),
    # workflow_schedule.py
    ("workflow_schedules", "budget_per_run_usd"),
]


def upgrade() -> None:
    for table, column in MONETARY_COLUMNS:
        op.alter_column(
            table, column,
            type_=sa.Numeric(12, 6),
            existing_type=sa.Float(),
            existing_nullable=True,
        )


def downgrade() -> None:
    for table, column in MONETARY_COLUMNS:
        op.alter_column(
            table, column,
            type_=sa.Float(),
            existing_type=sa.Numeric(12, 6),
            existing_nullable=True,
        )
