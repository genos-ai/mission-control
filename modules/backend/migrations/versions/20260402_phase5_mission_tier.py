"""Add tier and execution_environment columns (Plan 37 Phases 2-3)

Adds mission tier (user/platform) for platform missions and
execution_environment columns to both missions and executions
for the three-tier isolation model.

Revision ID: phase5_001
Revises: 325b823b2aaa
Create Date: 2026-04-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# Revision identifiers
revision: str = "phase5_001"
down_revision: Union[str, None] = "325b823b2aaa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(bind: sa.Connection, table: str) -> set[str]:
    return {c["name"] for c in inspect(bind).get_columns(table)}


def upgrade() -> None:
    """Apply migration."""
    bind = op.get_bind()
    mission_cols = _column_names(bind, "missions")
    execution_cols = _column_names(bind, "executions")

    # Phase 2: Mission tier
    if "tier" not in mission_cols:
        op.add_column(
            "missions",
            sa.Column(
                "tier",
                sa.String(20),
                nullable=False,
                server_default="user",
                comment="Mission tier: user (standard) or platform (admin-only)",
            ),
        )

    # Phase 3: Execution environment on missions (default for executions)
    if "execution_environment" not in mission_cols:
        op.add_column(
            "missions",
            sa.Column(
                "execution_environment",
                sa.String(20),
                nullable=True,
                comment="Default execution environment: local, worktree, container. NULL = local.",
            ),
        )

    # Phase 3: Execution environment on executions (per-execution override)
    if "execution_environment" not in execution_cols:
        op.add_column(
            "executions",
            sa.Column(
                "execution_environment",
                sa.String(20),
                nullable=False,
                server_default="local",
                comment="Execution environment: local, worktree, container",
            ),
        )


def downgrade() -> None:
    """Revert migration."""
    bind = op.get_bind()
    mission_cols = _column_names(bind, "missions")
    execution_cols = _column_names(bind, "executions")

    if "execution_environment" in execution_cols:
        op.drop_column("executions", "execution_environment")
    if "execution_environment" in mission_cols:
        op.drop_column("missions", "execution_environment")
    if "tier" in mission_cols:
        op.drop_column("missions", "tier")
