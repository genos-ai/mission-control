"""Phase 2: Schema expansion — agent catalog, mission teams, workflow definitions, prompt versions.

Revision ID: phase2_001
Revises: None
Create Date: 2026-03-20
"""

from alembic import op
import sqlalchemy as sa

revision = "phase2_001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- 1. Add brief column to missions table --
    op.add_column(
        "missions",
        sa.Column("brief", sa.Text(), nullable=True,
                  comment="Strategic directive that agents read to understand their purpose"),
    )

    # -- 2. Create agent_catalog table --
    op.create_table(
        "agent_catalog",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("agent_name", sa.String(length=200), nullable=False),
        sa.Column("agent_type", sa.String(length=50), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False, server_default="1.0.0"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("model_config_json", sa.JSON(), nullable=False),
        sa.Column("tools", sa.JSON(), nullable=False),
        sa.Column("scope", sa.JSON(), nullable=False),
        sa.Column("interface", sa.JSON(), nullable=True),
        sa.Column("constraints", sa.JSON(), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("visibility", sa.String(length=20), nullable=False, server_default="public"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_agent_catalog_agent_name", "agent_catalog", ["agent_name"], unique=True)
    op.create_index("ix_agent_catalog_agent_type", "agent_catalog", ["agent_type"])
    op.create_index("ix_agent_catalog_enabled", "agent_catalog", ["enabled"])
    op.create_index("ix_agent_catalog_visibility", "agent_catalog", ["visibility"])

    # -- 3. Create mission_team_members table --
    op.create_table(
        "mission_team_members",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("mission_id", sa.String(length=36), sa.ForeignKey("missions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_catalog_id", sa.String(length=36), sa.ForeignKey("agent_catalog.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_prompt", sa.Text(), nullable=True),
        sa.Column("user_prompt_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("custom_constraints", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("mission_id", "agent_catalog_id", name="uq_mission_team_mission_agent"),
    )
    op.create_index("ix_mission_team_members_mission_id", "mission_team_members", ["mission_id"])
    op.create_index("ix_mission_team_members_agent_catalog_id", "mission_team_members", ["agent_catalog_id"])

    # -- 4. Create workflow_definitions table --
    op.create_table(
        "workflow_definitions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("mission_id", sa.String(length=36), sa.ForeignKey("missions.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("objective", sa.JSON(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("trigger_config", sa.JSON(), nullable=False),
        sa.Column("budget_config", sa.JSON(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("designed_by", sa.String(length=200), nullable=True),
        sa.Column("locked_at", sa.String(length=30), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("mission_id", "name", name="uq_workflow_definitions_mission_name"),
    )
    op.create_index("ix_workflow_definitions_mission_id", "workflow_definitions", ["mission_id"])

    # -- 5. Create prompt_versions table --
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("prompt_type", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("changed_by", sa.String(length=200), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_prompt_versions_entity_lookup",
        "prompt_versions",
        ["entity_type", "entity_id", "version"],
    )


def downgrade() -> None:
    op.drop_table("prompt_versions")
    op.drop_table("workflow_definitions")
    op.drop_table("mission_team_members")
    op.drop_table("agent_catalog")
    op.drop_column("missions", "brief")
