"""add cache_ttl to agent_catalog

Revision ID: 01e82767c1b6
Revises: plan59_001
Create Date: 2026-04-19 07:56:44.607115+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers
revision: str = "01e82767c1b6"
down_revision: Union[str, None] = "plan59_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add cache_ttl column to agent_catalog (Plan 60 §0.2)."""
    op.add_column(
        "agent_catalog",
        sa.Column(
            "cache_ttl",
            sa.String(length=10),
            nullable=True,
            comment="Cache TTL for Anthropic prompt caching: 5m or 1h (None = cost.yaml default)",
        ),
    )


def downgrade() -> None:
    """Remove cache_ttl column from agent_catalog."""
    op.drop_column("agent_catalog", "cache_ttl")
