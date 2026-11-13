"""Mission lifecycle columns; plan status removed (Plan 88, 88.4.2)

missions gains paused_reason, paused_at and paused_by_user_id. Missions that
are already PAUSED get reason USER, then ck_missions_pause_consistent ties the
reason to the PAUSED status. mission_plans loses status (missions.status is the
only lifecycle) and the supervisor iteration columns (the count lives on
mission_runs.iteration_count; the cap is gone, decision 12).

Downgrade is structural only; the restored mission_plans.status is ACTIVE for
every row and the restored iteration columns carry their old defaults.

Revision ID: plan88_005
Revises: plan88_004
Create Date: 2026-11-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PgUUID

revision: str = "plan88_005"
down_revision: Union[str, None] = "plan88_004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PAUSE_CHECK = "ck_missions_pause_consistent"
_PAUSED_BY_FK = (
    "missions_paused_by_user_id_fkey"  # the PostgreSQL default name, as create_all makes it
)


def upgrade() -> None:
    # 1. Pause columns on missions.
    op.add_column("missions", sa.Column("paused_reason", sa.String(32), nullable=True))
    op.add_column("missions", sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("missions", sa.Column("paused_by_user_id", PgUUID(as_uuid=False), nullable=True))
    op.create_foreign_key(
        _PAUSED_BY_FK, "missions", "users", ["paused_by_user_id"], ["id"], ondelete="SET NULL"
    )

    # 2. Backfill, then the consistency check.
    op.execute(
        "UPDATE missions SET paused_reason = 'USER', paused_at = now() WHERE status = 'PAUSED'"
    )
    op.create_check_constraint(
        _PAUSE_CHECK, "missions", "(status = 'PAUSED') = (paused_reason IS NOT NULL)"
    )

    # 3. The plan's own lifecycle and the supervisor iteration columns go.
    op.drop_column("mission_plans", "status")
    op.drop_column("mission_plans", "supervisor_iteration_count")
    op.drop_column("mission_plans", "max_supervisor_iterations")


def downgrade() -> None:
    op.add_column(
        "mission_plans",
        sa.Column("max_supervisor_iterations", sa.Integer(), server_default="20", nullable=False),
    )
    op.add_column(
        "mission_plans",
        sa.Column("supervisor_iteration_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "mission_plans",
        sa.Column("status", sa.String(9), server_default="ACTIVE", nullable=False),
    )
    # Keep an emergency stop in force across rollback: pre-88.4.2 code reads plan status.
    op.execute(
        "UPDATE mission_plans p SET status = 'PAUSED' "
        "FROM missions m WHERE m.id = p.mission_id AND m.status = 'PAUSED'"
    )

    op.drop_constraint(_PAUSE_CHECK, "missions", type_="check")
    op.drop_constraint(_PAUSED_BY_FK, "missions", type_="foreignkey")
    op.drop_column("missions", "paused_by_user_id")
    op.drop_column("missions", "paused_at")
    op.drop_column("missions", "paused_reason")
