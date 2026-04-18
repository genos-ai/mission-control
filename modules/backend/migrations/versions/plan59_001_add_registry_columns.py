"""Add registry-critical columns to agent_catalog

Revision ID: plan59_001
Revises: e9ab4bbdf568
Create Date: 2026-04-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'plan59_001'
down_revision: Union[str, None] = 'e9ab4bbdf568'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add columns needed for DB-first agent registry."""
    op.add_column('agent_catalog', sa.Column(
        'invocation_tier', sa.String(length=20), nullable=False,
        server_default='user',
        comment='Invocation tier: user, platform, system',
    ))
    op.add_column('agent_catalog', sa.Column(
        'invocation_required_role', sa.String(length=20), nullable=True,
        comment='Required role for invocation (e.g. admin)',
    ))
    op.add_column('agent_catalog', sa.Column(
        'execution_mode', sa.String(length=20), nullable=False,
        server_default='standard',
        comment='Execution mode: standard, local, worktree, container',
    ))
    op.add_column('agent_catalog', sa.Column(
        'thinking_budget_json', sa.JSON(), nullable=True,
        comment='Extended thinking config JSON',
    ))
    op.add_column('agent_catalog', sa.Column(
        'max_input_length', sa.Integer(), nullable=False,
        server_default='32000',
        comment='Maximum input length in characters',
    ))
    op.add_column('agent_catalog', sa.Column(
        'max_budget_usd', sa.Float(), nullable=False,
        server_default='1.0',
        comment='Per-agent budget ceiling in USD',
    ))


def downgrade() -> None:
    """Remove registry columns."""
    op.drop_column('agent_catalog', 'max_budget_usd')
    op.drop_column('agent_catalog', 'max_input_length')
    op.drop_column('agent_catalog', 'thinking_budget_json')
    op.drop_column('agent_catalog', 'execution_mode')
    op.drop_column('agent_catalog', 'invocation_required_role')
    op.drop_column('agent_catalog', 'invocation_tier')
