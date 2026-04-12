"""Plan 51 Phase D — backfill mission.supervisor.agent into existing missions

One-time data migration. For every mission that doesn't already have
a ``mission_team_members`` row for ``mission.supervisor.agent``,
insert one. New missions get the supervisor automatically via
``_auto_assign_agents()`` which picks up all ``mission.*`` agents
from the catalog on mission creation.

Idempotent: safe to re-run. Uses INSERT ... WHERE NOT EXISTS so
duplicate rows are impossible even on concurrent execution.

Requires: the ``mission.supervisor.agent`` row to already exist in
``agent_catalog``. If the catalog hasn't been seeded yet (e.g.
running migrations before first boot), this migration is a no-op
and the backfill happens on the next boot via the seeder +
_auto_assign_agents flow.

Revision ID: plan51_003
Revises: plan51_002
Create Date: 2026-04-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision: str = "plan51_003"
down_revision: Union[str, None] = "plan51_002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SUPERVISOR_AGENT = "mission.supervisor.agent"


def upgrade() -> None:
    """Insert mission.supervisor.agent into mission_team_members for every existing mission."""
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("mission_team_members"):
        return
    if not inspector.has_table("agent_catalog"):
        return
    if not inspector.has_table("missions"):
        return

    # Find the catalog id for the supervisor agent.
    result = bind.execute(
        text(
            "SELECT id FROM agent_catalog WHERE agent_name = :name LIMIT 1"
        ),
        {"name": SUPERVISOR_AGENT},
    )
    row = result.fetchone()
    if row is None:
        # Catalog not yet seeded — no-op. The seeder + _auto_assign_agents
        # flow will handle it on next boot.
        return
    catalog_id = row[0]

    # Insert for every mission that doesn't already have the supervisor.
    bind.execute(
        text("""
            INSERT INTO mission_team_members (id, mission_id, agent_catalog_id,
                user_prompt_version, enabled, display_order, created_at, updated_at)
            SELECT
                lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' ||
                    substr(hex(randomblob(2)),2) || '-' ||
                    substr('89ab', abs(random()) % 4 + 1, 1) ||
                    substr(hex(randomblob(2)),2) || '-' ||
                    hex(randomblob(6))),
                m.id,
                :catalog_id,
                0,
                1,
                99,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM missions m
            WHERE NOT EXISTS (
                SELECT 1 FROM mission_team_members mtm
                WHERE mtm.mission_id = m.id
                AND mtm.agent_catalog_id = :catalog_id
            )
        """),
        {"catalog_id": catalog_id},
    )


def downgrade() -> None:
    """Remove the backfilled supervisor rows."""
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("mission_team_members"):
        return
    if not inspector.has_table("agent_catalog"):
        return

    result = bind.execute(
        text(
            "SELECT id FROM agent_catalog WHERE agent_name = :name LIMIT 1"
        ),
        {"name": SUPERVISOR_AGENT},
    )
    row = result.fetchone()
    if row is None:
        return

    bind.execute(
        text(
            "DELETE FROM mission_team_members WHERE agent_catalog_id = :catalog_id"
        ),
        {"catalog_id": row[0]},
    )
