"""Add parameters column to workflow_definitions.

Stores typed user-facing input parameters (WorkflowParameterSchema[])
that are shown in a form before workflow execution. Values merge into
context as context_overrides at run time.

Revision ID: workflow_parameters_001
Revises: plan72_001
Create Date: 2026-05-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "workflow_parameters_001"
down_revision: Union[str, None] = "plan72_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflow_definitions",
        sa.Column(
            "parameters",
            sa.JSON(),
            nullable=False,
            server_default="[]",
            comment="WorkflowParameterSchema[]: typed user-facing inputs shown before run",
        ),
    )


def downgrade() -> None:
    op.drop_column("workflow_definitions", "parameters")
