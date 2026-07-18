"""Plan 57 Phase A — Knowledge platform foundation.

Creates mission_intents, mission_learnings, and embeddings tables.
Adds rolling summary columns to sessions.
Creates GIN indexes on JSONB columns for existing tables.

The HNSW index on embeddings is NOT created here — it should be
created via a separate script after initial data population to
avoid slow builds on bulk backfill.

Revision ID: plan57_001
Revises: 20260414_bg_task
"""

import sqlalchemy as sa
from alembic import op

revision = "plan57_001"
down_revision = "20260414_bg_task"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- pgvector extension (required for Postgres) ----
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ---- mission_intents (append-only, event-sourced) ----
    op.create_table(
        "mission_intents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.Column(
            "mission_id",
            sa.String(36),
            sa.ForeignKey("missions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("intent", sa.Text, nullable=False),
        sa.Column("intent_summary", sa.Text, nullable=False),
        sa.Column("scope", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column(
            "revised_from",
            sa.String(36),
            sa.ForeignKey("mission_intents.id"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("agent_id", sa.String(200), nullable=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_mission_intents_mission_created",
        "mission_intents",
        ["mission_id", sa.text("created_at DESC")],
    )

    # ---- mission_learnings ----
    op.create_table(
        "mission_learnings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column(
            "mission_id",
            sa.String(36),
            sa.ForeignKey("missions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("recommendation", sa.Text, nullable=False),
        sa.Column("evidence", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("domain_tags", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("agent_names", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("occurrence_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("platform_promoted", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("promoted_at", sa.DateTime, nullable=True),
        sa.Column("promoted_by", sa.String(200), nullable=True),
        sa.Column(
            "contradicts_id",
            sa.String(36),
            sa.ForeignKey("mission_learnings.id"),
            nullable=True,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
    )
    op.create_index("ix_mission_learnings_mission", "mission_learnings", ["mission_id"])
    op.create_index(
        "ix_mission_learnings_platform",
        "mission_learnings",
        ["platform_promoted", "status"],
    )
    op.create_index(
        "ix_mission_learnings_kind_status",
        "mission_learnings",
        ["kind", "status"],
    )

    # GIN index on domain_tags (Postgres only — cast to jsonb for GIN support)
    if conn.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_mission_learnings_tags "
            "ON mission_learnings USING GIN ((domain_tags::jsonb))"
        )

    # ---- embeddings (generic, cross-type) ----
    embedding_columns = [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_table", sa.String(64), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column(
            "mission_id",
            sa.String(36),
            sa.ForeignKey("missions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    ]

    # Add the vector column — pgvector required on Postgres, text on SQLite
    if conn.dialect.name == "postgresql":
        from pgvector.sqlalchemy import Vector

        embedding_columns.append(
            sa.Column("embedding_data", Vector(1536), nullable=True),
        )
    else:
        embedding_columns.append(
            sa.Column("embedding_data", sa.Text, nullable=True),
        )

    op.create_table("embeddings", *embedding_columns)
    op.create_index("ix_embeddings_source", "embeddings", ["source_table", "source_id"])
    op.create_index("ix_embeddings_mission", "embeddings", ["mission_id"])
    op.create_unique_constraint(
        "uq_embeddings_source_version",
        "embeddings",
        ["source_table", "source_id", "version"],
    )
    # NOTE: HNSW index on embedding_data is created post-backfill
    # via: CREATE INDEX ix_embeddings_hnsw ON embeddings USING hnsw (embedding_data vector_cosine_ops);

    # ---- sessions: add rolling summary columns ----
    op.add_column(
        "sessions", sa.Column("rolling_summary", sa.Text, server_default="", nullable=False)
    )
    op.add_column(
        "sessions",
        sa.Column("rolling_summary_anchor", sa.Integer, server_default="0", nullable=False),
    )
    op.add_column(
        "sessions",
        sa.Column("rolling_summary_version", sa.Integer, server_default="0", nullable=False),
    )

    # ---- GIN indexes on existing JSONB columns (Postgres only) ----
    if conn.dialect.name == "postgresql":
        # milestone_summaries.domain_tags
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_milestone_summaries_tags "
            "ON milestone_summaries USING GIN ((domain_tags::jsonb))"
        )


def downgrade() -> None:
    # Drop new columns
    op.drop_column("sessions", "rolling_summary_version")
    op.drop_column("sessions", "rolling_summary_anchor")
    op.drop_column("sessions", "rolling_summary")

    # Drop new tables (reverse order of creation)
    op.drop_table("embeddings")
    op.drop_table("mission_learnings")
    op.drop_table("mission_intents")
