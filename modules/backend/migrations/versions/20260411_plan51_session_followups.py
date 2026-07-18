"""Session followups — Plan 51 Phase A

Creates the ``session_followups`` table that backs Plan 51's generic
wake-on-event primitive. An agent declares "I'll check back when
event X arrives" by inserting a row here; the
``SessionFollowupService.fire_matching(event)`` entry point finds
matching rows on each emitted event and spawns a fresh agent turn
for each match.

The primitive itself is deliberately **not** autonomy-loop-specific —
any agent can use it for any event type. Phase A ships the table +
service + schedule_followup tool. Later phases wire production
consumers: Phase C (post-run gate checkpoint) emits
``mission_plan.run.completed`` and calls ``fire_matching`` from
``MissionPlanService.dispatch_approved``; Phase E (Director followup
integration) registers Director followups on
``mission_plan.supervisor_decision``.

See ``docs/97-plans/51-plan-autonomy-loop-supervisor.md`` §5 Phase A
for the full design rationale including reset/cooldown semantics.

Revision ID: plan51_001
Revises: phase2_metrics
Create Date: 2026-04-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# Revision identifiers
revision: str = "plan51_001"
down_revision: Union[str, None] = "phase2_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind: sa.Connection, table: str) -> bool:
    return inspect(bind).has_table(table)


def upgrade() -> None:
    """Create the session_followups table."""
    bind = op.get_bind()

    if _table_exists(bind, "session_followups"):
        return

    op.create_table(
        "session_followups",
        sa.Column("id", sa.String(36), primary_key=True),
        # Hard owner: when the session is deleted, its followups go
        # with it. A followup registered against a closed session is
        # useless and would just sit in the table forever.
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
            comment="Session that owns the followup. Cascade on delete.",
        ),
        # Denormalised mission filter — sessions already carry
        # mission_id, but filtering followups by mission_id directly
        # is the common query shape for autonomy loop events, so we
        # keep a copy to avoid a session join.
        sa.Column(
            "mission_id",
            sa.String(36),
            nullable=True,
            index=True,
            comment=(
                "Denormalised mission filter. Not a hard FK — sessions "
                "already own their mission_id; this is a query shortcut."
            ),
        ),
        # Trigger specification. JSON array of event_type strings +
        # optional literal-match filter against the event payload.
        sa.Column(
            "trigger_event_types",
            sa.JSON,
            nullable=False,
            comment=(
                "JSON array of event_type strings the followup "
                "subscribes to. e.g. ['mission_plan.run.completed']."
            ),
        ),
        sa.Column(
            "trigger_filter",
            sa.JSON,
            nullable=True,
            comment=(
                "Optional literal-match filter against the event "
                "payload. NULL means match any event of the declared "
                "types."
            ),
        ),
        # What to do when the trigger fires. The template is rendered
        # via str.format_map(event_dict) so it can reference event
        # fields like {execution_record_id}.
        sa.Column(
            "prompt_template",
            sa.Text,
            nullable=False,
            comment=(
                "Prompt to send to the agent when the followup fires. "
                "Rendered via str.format_map against the event payload."
            ),
        ),
        sa.Column(
            "created_by_agent",
            sa.String(200),
            nullable=False,
            comment="Agent that scheduled this followup.",
        ),
        # Lifecycle.
        sa.Column(
            "expires_at",
            sa.DateTime,
            nullable=False,
            index=True,
            comment="Hard TTL — followups older than this are ignored.",
        ),
        sa.Column(
            "consumed_at",
            sa.DateTime,
            nullable=True,
            comment=(
                "Set when the followup has fired max_fires times. " "Row stays as audit trail."
            ),
        ),
        sa.Column(
            "cooldown_seconds",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment=(
                "Minimum seconds between fires when max_fires > 1. "
                "v1 uses max_fires = 1 so this is reserved."
            ),
        ),
        sa.Column(
            "max_fires",
            sa.Integer,
            nullable=False,
            server_default="1",
            comment=(
                "How many times this followup can fire before being "
                "consumed. Defaults to 1 — one-shot."
            ),
        ),
        sa.Column(
            "fire_count",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment="How many times this followup has fired so far.",
        ),
        sa.Column(
            "failure_reason",
            sa.Text,
            nullable=True,
            comment=(
                "Error message if the followup's agent turn failed. "
                "Non-NULL implies the followup attempted to fire but "
                "the agent errored."
            ),
        ),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    """Drop session_followups."""
    bind = op.get_bind()
    if _table_exists(bind, "session_followups"):
        op.drop_table("session_followups")
