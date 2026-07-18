"""Plan 51 — widen execution_decisions.decision_type to VARCHAR(30)

The column was created as VARCHAR(8) by the original migration (the
longest existing DecisionType value was "escalate" = 8 chars). Plan
51 Phase C added POST_RUN_SUPERVISOR = "post_run_supervisor" (19
chars) which doesn't fit. Widen to VARCHAR(30) with headroom for
future decision types.

Revision ID: plan51_004
Revises: plan51_003
Create Date: 2026-04-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "plan51_004"
down_revision: Union[str, None] = "plan51_003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "execution_decisions",
        "decision_type",
        type_=sa.String(30),
        existing_type=sa.String(8),
    )


def downgrade() -> None:
    op.alter_column(
        "execution_decisions",
        "decision_type",
        type_=sa.String(8),
        existing_type=sa.String(30),
    )
