"""Phase 3: Add users and api_keys tables.

Revision ID: phase3_001
Revises: phase2_002
Create Date: 2026-03-21
"""

from alembic import op
import sqlalchemy as sa
from uuid import uuid4

from modules.backend.core.utils import utc_now

revision = "phase3_001"
down_revision = "phase2_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create users table
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("hashed_password", sa.String(length=200), nullable=True),
        sa.Column("system_role", sa.String(length=20), nullable=False, server_default="user"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_service_account", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_system_role", "users", ["system_role"])

    # 2. Create api_keys table
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("key_prefix", sa.String(length=8), nullable=False),
        sa.Column("hashed_key", sa.String(length=200), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("scopes", sa.JSON(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_api_keys_user_name"),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])
    op.create_index("ix_api_keys_key_prefix", "api_keys", ["key_prefix"])

    # 3. Data migration: create placeholder users for existing mission_members
    conn = op.get_bind()
    now = utc_now()

    # Find distinct user_ids from mission_members
    member_rows = conn.execute(
        sa.text("SELECT DISTINCT user_id FROM mission_members WHERE user_id IS NOT NULL AND TRIM(user_id) != ''")
    ).fetchall()

    # Find distinct owner_ids from missions
    owner_rows = conn.execute(
        sa.text("SELECT DISTINCT owner_id FROM missions WHERE owner_id IS NOT NULL AND TRIM(owner_id) != ''")
    ).fetchall()

    # Collect all unique identifiers
    all_identifiers = set()
    for row in member_rows:
        all_identifiers.add(row[0])
    for row in owner_rows:
        all_identifiers.add(row[0])

    # Delete invalid mission_members (empty/whitespace user_id)
    invalid_count = conn.execute(
        sa.text("SELECT COUNT(*) FROM mission_members WHERE user_id IS NULL OR TRIM(user_id) = ''")
    ).scalar()
    if invalid_count and invalid_count > 0:
        conn.execute(
            sa.text("DELETE FROM mission_members WHERE user_id IS NULL OR TRIM(user_id) = ''")
        )

    # Insert placeholder users and build a mapping
    identifier_to_uuid = {}
    for identifier in all_identifiers:
        user_uuid = str(uuid4())
        identifier_to_uuid[identifier] = user_uuid
        conn.execute(
            sa.text(
                "INSERT INTO users (id, email, display_name, system_role, is_active, is_service_account, created_at, updated_at) "
                "VALUES (:id, :email, :display_name, :role, :active, :svc, :created, :updated)"
            ),
            {
                "id": user_uuid,
                "email": f"{identifier}@placeholder.local",
                "display_name": identifier,
                "role": "user",
                "active": True,
                "svc": False,
                "created": now,
                "updated": now,
            },
        )

    # Update mission_members.user_id to point to new UUIDs
    for old_id, new_uuid in identifier_to_uuid.items():
        conn.execute(
            sa.text("UPDATE mission_members SET user_id = :new_id WHERE user_id = :old_id"),
            {"new_id": new_uuid, "old_id": old_id},
        )

    # Update missions.owner_id similarly
    for old_id, new_uuid in identifier_to_uuid.items():
        conn.execute(
            sa.text("UPDATE missions SET owner_id = :new_id WHERE owner_id = :old_id"),
            {"new_id": new_uuid, "old_id": old_id},
        )

    # 4. Add FK constraint on mission_members.user_id
    # First, alter column length from String(200) to String(36)
    op.alter_column("mission_members", "user_id", type_=sa.String(length=36), existing_nullable=False)
    op.create_foreign_key(
        "fk_mission_members_user_id",
        "mission_members",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    # 1. Drop FK constraint
    op.drop_constraint("fk_mission_members_user_id", "mission_members", type_="foreignkey")
    op.alter_column("mission_members", "user_id", type_=sa.String(length=200), existing_nullable=False)

    # 2. Drop api_keys table
    op.drop_index("ix_api_keys_key_prefix", table_name="api_keys")
    op.drop_index("ix_api_keys_user_id", table_name="api_keys")
    op.drop_table("api_keys")

    # 3. Drop users table
    op.drop_index("ix_users_system_role", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
