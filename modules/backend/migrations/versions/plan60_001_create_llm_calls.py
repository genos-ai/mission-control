"""create llm_calls table

Revision ID: plan60_001
Revises: 01e82767c1b6
Create Date: 2026-04-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "plan60_001"
down_revision: Union[str, None] = "01e82767c1b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create llm_calls table for per-request cost tracking (Plan 60 §0.3)."""
    op.create_table(
        "llm_calls",
        # PK + timestamps
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        # Context
        sa.Column("session_id", sa.String(36), nullable=True),
        sa.Column("mission_id", sa.String(36), nullable=True),
        sa.Column("execution_record_id", sa.String(36), nullable=True),
        sa.Column("agent_name", sa.String(200), nullable=False),
        sa.Column("agent_role", sa.String(50), nullable=False),
        # Model
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        # Token breakdown
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_write_5m_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_write_1h_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("thinking_tokens", sa.Integer(), nullable=False, server_default="0"),
        # Cost
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        # Performance
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(100), nullable=True),
        # Tool context
        sa.Column("tool_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_schema_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    # Indexes for dashboard queries
    op.create_index("ix_llm_calls_session_id", "llm_calls", ["session_id"])
    op.create_index("ix_llm_calls_mission_id", "llm_calls", ["mission_id"])
    op.create_index("ix_llm_calls_agent_name", "llm_calls", ["agent_name"])
    op.create_index("ix_llm_calls_model", "llm_calls", ["model"])
    op.create_index("ix_llm_calls_created_at", "llm_calls", ["created_at"])


def downgrade() -> None:
    """Drop llm_calls table."""
    op.drop_table("llm_calls")
