"""Add tier column to missions

Phase 2 of Plan 37: Platform missions. Adds mission tier (user/platform)
to support admin-only platform missions with platform director access.

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


def downgrade() -> None:
    """Revert migration."""
    op.drop_column("missions", "tier")
