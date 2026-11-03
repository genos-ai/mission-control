"""add users.token_version

Tokens carry the user's token version (`tv`); a token whose version differs from the
user's current one is refused. A password change, an admin reset and a deactivation raise
it, which ends every existing session of that user. Sessions cannot be listed, so a
per-session revocation row (plan87_001) cannot do this.

Revision ID: plan87_002
Revises: plan87_001
Create Date: 2026-11-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "plan87_002"
down_revision: Union[str, None] = "plan87_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
