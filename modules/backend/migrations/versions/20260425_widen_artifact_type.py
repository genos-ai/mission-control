"""Widen artifact_type column and fix synthesizer artifact_type.

Revision ID: widen_artifact_type
Revises: add_produces_artifact
Create Date: 2026-04-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "widen_artifact_type"
down_revision: Union[str, None] = "add_produces_artifact"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Widen artifact_type from String(20) to String(50)
    op.alter_column(
        "mission_artifacts",
        "artifact_type",
        type_=sa.String(50),
        existing_type=sa.String(20),
    )
    # Fix synthesizer artifact_type in catalog
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE agent_catalog "
            "SET artifact_type = 'research_report' "
            "WHERE agent_name = 'research.synthesizer.agent'"
        ),
    )


def downgrade() -> None:
    op.alter_column(
        "mission_artifacts",
        "artifact_type",
        type_=sa.String(20),
        existing_type=sa.String(50),
    )
