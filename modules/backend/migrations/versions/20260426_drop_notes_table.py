"""Drop legacy notes table.

The notes table was a BFF reference architecture artifact from early
development. It is not used by any service, endpoint, or agent.

Revision ID: drop_notes_table
Revises: varchar36_to_native_uuid
Create Date: 2026-04-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "drop_notes_table"
down_revision: Union[str, None] = "varchar36_to_native_uuid"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("notes")


def downgrade() -> None:
    op.create_table(
        "notes",
        sa.Column("id", sa.dialects.postgresql.UUID(), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("mission_id", sa.dialects.postgresql.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
