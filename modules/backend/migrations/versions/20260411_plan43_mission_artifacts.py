"""Mission artifacts (Plan 43 Phase A)

Creates the ``mission_artifacts`` table that backs Plan 43's durable
artifact storage. Before this migration, agent-produced artifacts
(reports, findings, code, summaries) were emitted as
``MissionArtifactFoundEvent`` SSE events and kept only in the
frontend's in-memory Zustand store — they vanished on page refresh
or backend restart. This table persists them so a returning user can
see what an overnight autonomous run produced.

See ``docs/97-plans/43-plan-persistent-mission-artifacts.md`` for the
full design rationale (§3.1 schema, §3.2 model shape, §3.6 dual-write
lifecycle with the existing live-preview SSE event).

Revision ID: plan43_001
Revises: plan42_001
Create Date: 2026-04-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# Revision identifiers
revision: str = "plan43_001"
down_revision: Union[str, None] = "plan42_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind: sa.Connection, table: str) -> bool:
    return inspect(bind).has_table(table)


def upgrade() -> None:
    """Create the mission_artifacts table."""
    bind = op.get_bind()

    if _table_exists(bind, "mission_artifacts"):
        return

    op.create_table(
        "mission_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        # Ownership chain. The mission is the hard owner — a deleted
        # mission cascades. execution_record_id and task_execution_id
        # are SET NULL on delete so artifacts survive archival of the
        # specific run/task they originated from (the user cares
        # about the artifact, not which run row it was linked to).
        sa.Column(
            "mission_id",
            sa.String(36),
            sa.ForeignKey("missions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
            comment="Hard owner of the artifact. Mission delete cascades.",
        ),
        sa.Column(
            "execution_record_id",
            sa.String(36),
            sa.ForeignKey("execution_records.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
            comment=(
                "Run that produced this artifact. NULL if the run was "
                "archived or the artifact was created outside the dispatch "
                "loop (reserved for future non-task sources)."
            ),
        ),
        sa.Column(
            "task_execution_id",
            sa.String(36),
            sa.ForeignKey("task_executions.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
            comment="Specific task_execution row within the run, if applicable.",
        ),
        # Denormalised producer id — string key, not a hard FK, same
        # convention as plan_task_states.task_id.
        sa.Column(
            "agent_id",
            sa.String(200),
            nullable=False,
            server_default="",
            comment="Agent name that produced the artifact (denormalised).",
        ),
        # Typed shape. Enforced in the application layer via
        # models.mission_artifact::VALID_ARTIFACT_TYPES; we could add a
        # CHECK constraint here but it would couple the migration to the
        # enum and make future additions require a migration too.
        sa.Column(
            "artifact_type",
            sa.String(20),
            nullable=False,
            server_default="report",
            comment=(
                "report | finding | code | data | file. Matches the "
                "MissionArtifactFoundEvent event shape. v1 only ever "
                "writes 'report'; other types are reserved for future "
                "emission sites (structured findings from security agents, "
                "etc)."
            ),
        ),
        sa.Column(
            "title",
            sa.String(500),
            nullable=False,
            comment="Human-readable title, typically '<agent-name> — result'.",
        ),
        sa.Column(
            "content_type",
            sa.String(20),
            nullable=False,
            server_default="markdown",
            comment="text | markdown | json | code",
        ),
        sa.Column(
            "language",
            sa.String(50),
            nullable=True,
            comment="Language hint for code artifacts (python, typescript, ...).",
        ),
        # Content. Text-only in v1; storage_url is the v2 extension
        # point for file artifacts (blob / filesystem / object store
        # decision deferred per Plan 43 §3.7 until a real use case
        # emerges).
        sa.Column(
            "content_text",
            sa.Text,
            nullable=True,
            comment=(
                "Full artifact content. TEXT (unlimited) so the DB does "
                "not cap what the emission site writes. The API applies "
                "limits on read, not here."
            ),
        ),
        sa.Column(
            "storage_url",
            sa.String(1000),
            nullable=True,
            comment=(
                "Reserved for v2 file-artifact storage. NULL in v1. "
                "Form to be determined (blob storage URL, object-store "
                "path, or filesystem pointer) — see Plan 43 §3.7."
            ),
        ),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    """Drop mission_artifacts."""
    bind = op.get_bind()
    if _table_exists(bind, "mission_artifacts"):
        op.drop_table("mission_artifacts")
