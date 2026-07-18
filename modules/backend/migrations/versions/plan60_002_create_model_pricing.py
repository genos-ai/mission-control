"""create model_pricing table with seed data

Revision ID: plan60_002
Revises: plan60_001
Create Date: 2026-04-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "plan60_002"
down_revision: Union[str, None] = "plan60_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create model_pricing table and seed with April 2026 prices (Plan 60 §0.4)."""
    op.create_table(
        "model_pricing",
        sa.Column("model", sa.String(100), primary_key=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_per_mtok_input", sa.Float(), nullable=False),
        sa.Column("price_per_mtok_output", sa.Float(), nullable=False),
        sa.Column("price_per_mtok_cache_write_5m", sa.Float(), nullable=True),
        sa.Column("price_per_mtok_cache_write_1h", sa.Float(), nullable=True),
        sa.Column("price_per_mtok_cache_read", sa.Float(), nullable=True),
    )

    # Seed with April 2026 Anthropic list prices.
    # Model names use the anthropic: prefix to match llm_calls.model values.
    op.execute("""
        INSERT INTO model_pricing
            (model, effective_from, effective_to,
             price_per_mtok_input, price_per_mtok_output,
             price_per_mtok_cache_write_5m, price_per_mtok_cache_write_1h,
             price_per_mtok_cache_read)
        VALUES
            ('anthropic:claude-opus-4-7',
             '2026-04-16', '9999-12-31', 5.00, 25.00, 6.25, 10.00, 0.50),
            ('anthropic:claude-opus-4-6',
             '2025-06-01', '9999-12-31', 15.00, 75.00, 18.75, 30.00, 1.50),
            ('anthropic:claude-sonnet-4-6',
             '2026-02-01', '9999-12-31', 3.00, 15.00, 3.75, 6.00, 0.30),
            ('anthropic:claude-haiku-4-5-20251001',
             '2025-10-01', '9999-12-31', 1.00, 5.00, 1.25, 2.00, 0.10)
        """)


def downgrade() -> None:
    """Drop model_pricing table."""
    op.drop_table("model_pricing")
