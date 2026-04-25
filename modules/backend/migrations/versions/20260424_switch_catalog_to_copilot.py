"""Switch agent_catalog model configs from anthropic: to copilot: provider.

Revision ID: copilot_switch_001
Revises: plan40_001
Create Date: 2026-04-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "copilot_switch_001"
down_revision: Union[str, None] = "plan40_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Model name mappings: old Anthropic → new Copilot
_REPLACEMENTS = [
    ("anthropic:claude-haiku-4-5-20251001", "copilot:claude-haiku-4.5"),
    ("anthropic:claude-sonnet-4-6", "copilot:claude-sonnet-4.6"),
    ("anthropic:claude-sonnet-4-20250514", "copilot:claude-sonnet-4.6"),
    ("anthropic:claude-opus-4-6", "copilot:claude-opus-4.6"),
]


def upgrade() -> None:
    """Update model_config_json->>'name' from anthropic: to copilot: prefixes.

    Column is json (not jsonb), so we use CAST() function syntax instead
    of PostgreSQL :: operator to avoid asyncpg parameter binding conflicts.
    """
    conn = op.get_bind()
    for old_name, new_name in _REPLACEMENTS:
        conn.execute(
            sa.text(
                "UPDATE agent_catalog "
                "SET model_config_json = CAST(jsonb_set("
                "  CAST(model_config_json AS jsonb), '{name}', "
                "  CAST(:new_val AS jsonb)"
                ") AS json) "
                "WHERE model_config_json->>'name' = :old_name"
            ),
            {"old_name": old_name, "new_val": f'"{new_name}"'},
        )


def downgrade() -> None:
    """Revert copilot: prefixes back to anthropic: prefixes."""
    conn = op.get_bind()
    for old_name, new_name in _REPLACEMENTS:
        conn.execute(
            sa.text(
                "UPDATE agent_catalog "
                "SET model_config_json = CAST(jsonb_set("
                "  CAST(model_config_json AS jsonb), '{name}', "
                "  CAST(:old_val AS jsonb)"
                ") AS json) "
                "WHERE model_config_json->>'name' = :new_name"
            ),
            {"old_val": f'"{old_name}"', "new_name": new_name},
        )
