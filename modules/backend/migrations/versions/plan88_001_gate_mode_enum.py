"""gate mode becomes the GateMode enum on mission_plans (Plan 88, 88.1.0)

The plan's gate mode is the single source: missions.gate_mode is folded into
mission_plans.gate_mode and dropped, every mission gets a plan, values outside
the four modes (including workflow_managed and NULL) fail closed to MANUAL, and
the column stores the enum NAME (uppercase), NOT NULL. The AI_ASSISTED veto
window columns (mission_plans.veto_window_sec, tasks.veto_expires_at) go.

Revision ID: plan88_001
Revises: plan87_002
Create Date: 2026-11-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from modules.backend.core.logging import get_logger

revision: str = "plan88_001"
down_revision: Union[str, None] = "plan87_002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = get_logger(__name__)


def upgrade() -> None:
    bind = op.get_bind()

    # 1. A plan with no mode inherits the mission's mode.
    bind.execute(
        sa.text(
            "UPDATE mission_plans p SET gate_mode = m.gate_mode "
            "FROM missions m WHERE p.mission_id = m.id AND p.gate_mode IS NULL"
        )
    )

    # 2. Every mission has a plan.
    bind.execute(
        sa.text(
            "INSERT INTO mission_plans "
            "(id, mission_id, gate_mode, status, version, total_spent_usd, "
            "budget_usd_ceiling, created_at, updated_at) "
            "SELECT gen_random_uuid(), m.id, m.gate_mode, 'ACTIVE', 1, 0, "
            "m.budget_ceiling_usd, now(), now() "
            "FROM missions m "
            "WHERE NOT EXISTS (SELECT 1 FROM mission_plans p WHERE p.mission_id = m.id)"
        )
    )

    # 3. NULL, workflow_managed and any unknown value fail closed to manual.
    result = bind.execute(
        sa.text(
            "UPDATE mission_plans SET gate_mode = 'manual' "
            "WHERE gate_mode IS NULL "
            "OR gate_mode NOT IN ('interactive', 'manual', 'ai_assisted', 'autonomous')"
        )
    )
    logger.info(
        "plan88_001: gate modes set to manual (fail closed)", extra={"row_count": result.rowcount}
    )

    # 4. Enum(native_enum=False) stores the NAME.
    bind.execute(sa.text("UPDATE mission_plans SET gate_mode = upper(gate_mode)"))

    # 5. Widen and require.
    op.alter_column(
        "mission_plans",
        "gate_mode",
        existing_type=sa.String(length=20),
        type_=sa.String(length=32),
        nullable=False,
    )

    # 6. Drop the superseded columns.
    op.drop_column("missions", "gate_mode")
    op.drop_column("mission_plans", "veto_window_sec")
    op.drop_column("tasks", "veto_expires_at")


def downgrade() -> None:
    # Reverses 6 to 4 structurally. Plans inserted by step 2 are kept.
    op.add_column("tasks", sa.Column("veto_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("mission_plans", sa.Column("veto_window_sec", sa.Integer(), nullable=True))
    op.add_column("missions", sa.Column("gate_mode", sa.String(length=20), nullable=True))
    op.alter_column(
        "mission_plans",
        "gate_mode",
        existing_type=sa.String(length=32),
        type_=sa.String(length=20),
        nullable=True,
    )
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE mission_plans SET gate_mode = lower(gate_mode)"))
    bind.execute(
        sa.text(
            "UPDATE missions m SET gate_mode = p.gate_mode "
            "FROM mission_plans p WHERE p.mission_id = m.id"
        )
    )
