"""Add partial unique index for system workflow templates (mission_id IS NULL).

Prevents duplicate system template names while allowing the same name
across different missions (covered by the existing unique constraint).

Revision ID: workflow_system_unique
Revises: mission_events_001
"""

from alembic import op

revision = "workflow_system_unique"
down_revision = "mission_events_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_workflow_definitions_system_name",
        "workflow_definitions",
        ["name"],
        unique=True,
        postgresql_where="mission_id IS NULL",
    )


def downgrade() -> None:
    op.drop_index(
        "uq_workflow_definitions_system_name",
        table_name="workflow_definitions",
    )
