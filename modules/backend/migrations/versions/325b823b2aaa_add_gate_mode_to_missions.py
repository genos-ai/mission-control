"""Add gate_mode to missions

Revision ID: 325b823b2aaa
Revises: phase4_001
Create Date: 2026-03-26 06:07:49.799356+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers
revision: str = "325b823b2aaa"
down_revision: Union[str, None] = "phase4_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply migration."""
    op.add_column(
        "missions",
        sa.Column(
            "gate_mode",
            sa.String(length=20),
            nullable=True,
            comment="Default gate mode: interactive, manual, ai_assisted, autonomous",
        ),
    )


def downgrade() -> None:
    """Revert migration."""
    op.drop_column("missions", "gate_mode")
