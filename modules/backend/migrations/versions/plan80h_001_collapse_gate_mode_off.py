"""collapse gate_mode 'off' into 'autonomous'

Every conditional in the codebase grouped 'off' with 'autonomous', so the
two values are functionally identical for the mission/plan gate_mode
field. This migration rewrites existing rows to 'autonomous' and the
application code no longer accepts 'off' as a valid value.

Downgrade is a no-op — once collapsed, we cannot tell which rows were
originally 'off' versus 'autonomous'.

Revision ID: plan80h_001
Revises: plan80g_002
Create Date: 2026-05-24
"""

from typing import Sequence, Union

from alembic import op


revision: str = "plan80h_001"
down_revision: Union[str, None] = "plan80g_002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE mission_plans SET gate_mode = 'autonomous' "
        "WHERE gate_mode = 'off'"
    )
    op.execute(
        "UPDATE missions SET gate_mode = 'autonomous' "
        "WHERE gate_mode = 'off'"
    )


def downgrade() -> None:
    # No-op: the collapse is one-way. Rows that were 'off' are now
    # indistinguishable from rows that were already 'autonomous'.
    pass
