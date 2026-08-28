"""Replace system account string IDs with proper UUIDs.

System accounts (system:cli, system:workflow, system:scheduler) were
created with string IDs instead of UUIDs. This migration replaces them
with deterministic UUID v5 values so the users table can eventually
migrate to native PostgreSQL UUID type.

Also updates non-FK columns that store these IDs (missions.owner_id).

Revision ID: system_account_uuids
Revises: widen_artifact_type
Create Date: 2026-04-26
"""

from typing import Sequence, Union
from uuid import UUID, uuid5

import sqlalchemy as sa
from alembic import op

revision: str = "system_account_uuids"
down_revision: Union[str, None] = "widen_artifact_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Deterministic UUIDs — same namespace and names as models/base.py
SYSTEM_NAMESPACE = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")

ID_MAP = {
    "system:cli": str(uuid5(SYSTEM_NAMESPACE, "system:cli")),
    "system:workflow": str(uuid5(SYSTEM_NAMESPACE, "system:workflow")),
    "system:scheduler": str(uuid5(SYSTEM_NAMESPACE, "system:scheduler")),
}

# Tables with FK constraints referencing users.id
FK_CONSTRAINTS = [
    {
        "table": "api_keys",
        "column": "user_id",
        "constraint": "api_keys_user_id_fkey",
        "ondelete": "CASCADE",
    },
    {
        "table": "mission_members",
        "column": "user_id",
        "constraint": "fk_mission_members_user_id",
        "ondelete": "RESTRICT",
    },
    {
        "table": "plan_task_states",
        "column": "approved_by_user_id",
        "constraint": "plan_task_states_approved_by_user_id_fkey",
        "ondelete": "RESTRICT",
    },
]


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Drop FK constraints that reference users.id
    for fk in FK_CONSTRAINTS:
        op.drop_constraint(fk["constraint"], fk["table"], type_="foreignkey")

    # 2. Update users.id from string to UUID
    for old_id, new_id in ID_MAP.items():
        # Update the PK
        conn.execute(
            sa.text("UPDATE users SET id = :new_id WHERE id = :old_id"),
            {"new_id": new_id, "old_id": old_id},
        )

        # Update FK columns. table/column come from the static FK_CONSTRAINTS
        # constant above, never external input.
        for fk in FK_CONSTRAINTS:
            conn.execute(
                sa.text(  # nosec B608
                    f"UPDATE {fk['table']} SET {fk['column']} = :new_id "
                    f"WHERE {fk['column']} = :old_id"
                ),
                {"new_id": new_id, "old_id": old_id},
            )

        # Update non-FK columns that store system IDs
        conn.execute(
            sa.text("UPDATE missions SET owner_id = :new_id WHERE owner_id = :old_id"),
            {"new_id": new_id, "old_id": old_id},
        )
        conn.execute(
            sa.text(
                "UPDATE workflow_schedules SET created_by = :new_id " "WHERE created_by = :old_id"
            ),
            {"new_id": new_id, "old_id": old_id},
        )

    # 3. Update email addresses for cleanliness
    for old_id, new_id in ID_MAP.items():
        display_name = old_id.replace("system:", "").replace("_", "-")
        conn.execute(
            sa.text("UPDATE users SET email = :email WHERE id = :uid"),
            {"email": f"{display_name}-runner@system.local", "uid": new_id},
        )

    # 4. Re-add FK constraints
    for fk in FK_CONSTRAINTS:
        op.create_foreign_key(
            fk["constraint"],
            fk["table"],
            "users",
            [fk["column"]],
            ["id"],
            ondelete=fk["ondelete"],
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Reverse: UUID back to string IDs
    reverse_map = {v: k for k, v in ID_MAP.items()}

    for fk in FK_CONSTRAINTS:
        op.drop_constraint(fk["constraint"], fk["table"], type_="foreignkey")

    for new_id, old_id in reverse_map.items():
        conn.execute(
            sa.text("UPDATE users SET id = :old_id WHERE id = :new_id"),
            {"old_id": old_id, "new_id": new_id},
        )
        # table/column come from the static FK_CONSTRAINTS constant above,
        # never external input.
        for fk in FK_CONSTRAINTS:
            conn.execute(
                sa.text(  # nosec B608
                    f"UPDATE {fk['table']} SET {fk['column']} = :old_id "
                    f"WHERE {fk['column']} = :new_id"
                ),
                {"old_id": old_id, "new_id": new_id},
            )
        conn.execute(
            sa.text("UPDATE missions SET owner_id = :old_id WHERE owner_id = :new_id"),
            {"old_id": old_id, "new_id": new_id},
        )
        conn.execute(
            sa.text(
                "UPDATE workflow_schedules SET created_by = :old_id " "WHERE created_by = :new_id"
            ),
            {"old_id": old_id, "new_id": new_id},
        )

    for fk in FK_CONSTRAINTS:
        op.create_foreign_key(
            fk["constraint"],
            fk["table"],
            "users",
            [fk["column"]],
            ["id"],
            ondelete=fk["ondelete"],
        )
