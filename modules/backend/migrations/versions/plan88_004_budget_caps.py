"""Budget caps and ledger aggregates (Plan 88, 88.4.1)

mission_plans gains per-run and per-month caps (backfilled from the module
constants below, then NOT NULL) and renames budget_usd_ceiling to
budget_lifetime_usd, nulling non-positive values. mission_plans.total_spent_usd
and missions.budget_ceiling_usd are dropped: llm_calls is the ledger. Active
runs get their run cap snapshot. llm_call_daily_aggregates is created so that
BudgetService can sum it unconditionally (rows arrive with 88.5.3).

Downgrade is structural only; dropped spend and ceiling values are not restored.

Revision ID: plan88_004
Revises: plan88_003a
Create Date: 2026-11-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PgUUID

revision: str = "plan88_004"
down_revision: Union[str, None] = "plan88_003a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_PER_RUN_USD = 5.00  # missions.budgets.default_per_run_usd at plan88_004
DEFAULT_PER_MONTH_USD = 100.00  # missions.budgets.default_per_month_usd at plan88_004

_MONEY = sa.Numeric(12, 6)
_ACTIVE_STATUSES = "('PENDING','RUNNING','AWAITING_GATE','PAUSED')"
_PLAN_CHECKS = (
    ("ck_mission_plans_per_run_pos", "budget_per_run_usd > 0"),
    ("ck_mission_plans_per_month_pos", "budget_per_month_usd > 0"),
    ("ck_mission_plans_month_ge_run", "budget_per_month_usd >= budget_per_run_usd"),
)


def upgrade() -> None:
    # 1. Per-run and per-month caps, backfilled from the constants.
    op.add_column("mission_plans", sa.Column("budget_per_run_usd", _MONEY, nullable=True))
    op.add_column("mission_plans", sa.Column("budget_per_month_usd", _MONEY, nullable=True))
    op.get_bind().execute(
        sa.text(
            "UPDATE mission_plans SET budget_per_run_usd = :run, budget_per_month_usd = :month"
        ),
        {"run": DEFAULT_PER_RUN_USD, "month": DEFAULT_PER_MONTH_USD},
    )
    op.alter_column("mission_plans", "budget_per_run_usd", nullable=False)
    op.alter_column("mission_plans", "budget_per_month_usd", nullable=False)

    # 2. Cap checks.
    for name, condition in _PLAN_CHECKS:
        op.create_check_constraint(name, "mission_plans", condition)

    # 3. Lifetime cap: rename, null non-positive values, check.
    op.alter_column("mission_plans", "budget_usd_ceiling", new_column_name="budget_lifetime_usd")
    op.execute("UPDATE mission_plans SET budget_lifetime_usd = NULL WHERE budget_lifetime_usd <= 0")
    op.create_check_constraint(
        "ck_mission_plans_lifetime_pos",
        "mission_plans",
        "budget_lifetime_usd IS NULL OR budget_lifetime_usd > 0",
    )

    # 4. The second ledgers go.
    op.drop_column("mission_plans", "total_spent_usd")
    op.drop_column("missions", "budget_ceiling_usd")

    # 5. Run cap snapshot for active runs.
    op.execute(
        "UPDATE mission_runs r SET budget_cap_usd = p.budget_per_run_usd "
        "FROM mission_plans p "
        "WHERE r.plan_id = p.id AND r.budget_cap_usd IS NULL "
        f"AND r.status IN {_ACTIVE_STATUSES}"
    )

    # 6. Ledger aggregates (3.1.11).
    op.create_table(
        "llm_call_daily_aggregates",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("mission_id", PgUUID(as_uuid=False), nullable=True),
        sa.Column("agent_name", sa.String(200), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("call_count", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cache_read_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cache_write_5m_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cache_write_1h_tokens", sa.BigInteger(), nullable=False),
        sa.Column("thinking_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(14, 6), nullable=False),
        sa.UniqueConstraint(
            "day",
            "mission_id",
            "agent_name",
            "model",
            "provider",
            name="uq_llm_daily",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index("ix_llm_daily_mission_day", "llm_call_daily_aggregates", ["mission_id", "day"])


def downgrade() -> None:
    op.drop_index("ix_llm_daily_mission_day", table_name="llm_call_daily_aggregates")
    op.drop_table("llm_call_daily_aggregates")

    op.add_column("missions", sa.Column("budget_ceiling_usd", _MONEY, nullable=True))
    op.add_column("mission_plans", sa.Column("total_spent_usd", _MONEY, nullable=True))

    op.drop_constraint("ck_mission_plans_lifetime_pos", "mission_plans", type_="check")
    op.alter_column("mission_plans", "budget_lifetime_usd", new_column_name="budget_usd_ceiling")

    for name, _condition in reversed(_PLAN_CHECKS):
        op.drop_constraint(name, "mission_plans", type_="check")
    op.drop_column("mission_plans", "budget_per_month_usd")
    op.drop_column("mission_plans", "budget_per_run_usd")
