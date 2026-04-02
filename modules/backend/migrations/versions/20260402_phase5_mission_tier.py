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


# Revision identifiers
revision: str = "phase5_001"
down_revision: Union[str, None] = "325b823b2aaa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply migration."""
    # Phase 2: Mission tier
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
    op.drop_column("executions", "execution_environment")
    op.drop_column("missions", "execution_environment")
    op.drop_column("missions", "tier")
