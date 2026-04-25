"""Drop research_reports table — deliverables go to mission_artifacts.

Revision ID: drop_research_reports
Revises: copilot_switch_001
Create Date: 2026-04-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "drop_research_reports"
down_revision: Union[str, None] = "copilot_switch_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop research_reports — never populated, replaced by mission_artifacts."""
    op.drop_table("research_reports")


def downgrade() -> None:
    """Recreate research_reports table."""
    op.create_table(
        "research_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("mission_id", sa.String(36), nullable=False, index=True),
        sa.Column("execution_id", sa.String(36), nullable=True, index=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("report_markdown", sa.Text(), nullable=False, server_default=""),
        sa.Column("report_structured", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("sources", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("citation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verification_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
