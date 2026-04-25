"""Add produces_artifact and artifact_type to agent_catalog.

Revision ID: add_produces_artifact
Revises: drop_research_reports
Create Date: 2026-04-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "add_produces_artifact"
down_revision: Union[str, None] = "drop_research_reports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_catalog",
        sa.Column("produces_artifact", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "agent_catalog",
        sa.Column("artifact_type", sa.String(50), nullable=True),
    )
    # Set the synthesizer agent to produce artifacts
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE agent_catalog "
            "SET produces_artifact = true, artifact_type = 'research_report' "
            "WHERE agent_name = 'research.synthesizer.agent'"
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_catalog", "artifact_type")
    op.drop_column("agent_catalog", "produces_artifact")
