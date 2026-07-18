"""Add engine and effort columns to agent_catalog

Revision ID: e9ab4bbdf568
Revises: plan57_001
Create Date: 2026-04-18 13:09:34.532962+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers
revision: str = "e9ab4bbdf568"
down_revision: Union[str, None] = "plan57_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add engine and effort columns to agent_catalog."""
    op.add_column(
        "agent_catalog",
        sa.Column(
            "engine",
            sa.String(length=20),
            nullable=False,
            server_default="pydantic_ai",
            comment="Execution engine: pydantic_ai, claude_code, codex, copilot",
        ),
    )
    op.add_column(
        "agent_catalog",
        sa.Column(
            "effort",
            sa.String(length=10),
            nullable=True,
            comment="Effort level for CLI engines (low/medium/high)",
        ),
    )
    # Also add the schedule unique constraint from Plan 38
    op.create_unique_constraint(
        "uq_schedule_definition_mission_cron",
        "workflow_schedules",
        ["workflow_definition_id", "mission_id", "cron_expression"],
    )


def downgrade() -> None:
    """Remove engine and effort columns."""
    op.drop_constraint("uq_schedule_definition_mission_cron", "workflow_schedules", type_="unique")
    op.drop_column("agent_catalog", "effort")
    op.drop_column("agent_catalog", "engine")
