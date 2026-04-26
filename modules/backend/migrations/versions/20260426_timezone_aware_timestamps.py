"""Convert all timestamp columns to timezone-aware (Plan 64 Phase I).

All timestamps were stored as naive 'timestamp without time zone'.
The application always uses UTC (via utc_now()), but the DB column
type didn't enforce it. Converting to 'timestamp with time zone'
makes timezone handling explicit and prevents ambiguity.

Existing values are interpreted as UTC during conversion.

Revision ID: timezone_aware_timestamps
Revises: composite_indexes
Create Date: 2026-04-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "timezone_aware_timestamps"
down_revision: Union[str, None] = "composite_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Every 'timestamp without time zone' column in the DB.
COLUMNS = [
    ("agent_catalog", "created_at"),
    ("agent_catalog", "updated_at"),
    ("api_keys", "created_at"),
    ("api_keys", "expires_at"),
    ("api_keys", "last_used_at"),
    ("api_keys", "revoked_at"),
    ("api_keys", "updated_at"),
    ("context_changes", "created_at"),
    ("context_changes", "updated_at"),
    ("context_milestones", "created_at"),
    ("context_milestones", "updated_at"),
    ("embeddings", "created_at"),
    ("execution_decisions", "created_at"),
    ("execution_decisions", "updated_at"),
    ("execution_environments", "created_at"),
    ("execution_environments", "updated_at"),
    ("execution_records", "completed_at"),
    ("execution_records", "created_at"),
    ("execution_records", "started_at"),
    ("execution_records", "updated_at"),
    ("executions", "completed_at"),
    ("executions", "created_at"),
    ("executions", "started_at"),
    ("executions", "updated_at"),
    ("llm_calls", "created_at"),
    ("llm_calls", "updated_at"),
    ("milestone_summaries", "created_at"),
    ("milestone_summaries", "updated_at"),
    ("mission_artifacts", "created_at"),
    ("mission_artifacts", "updated_at"),
    ("mission_contexts", "created_at"),
    ("mission_contexts", "updated_at"),
    ("mission_decisions", "created_at"),
    ("mission_decisions", "updated_at"),
    ("mission_events", "created_at"),
    ("mission_events", "updated_at"),
    ("mission_intents", "created_at"),
    ("mission_intents", "updated_at"),
    ("mission_learnings", "created_at"),
    ("mission_learnings", "promoted_at"),
    ("mission_learnings", "updated_at"),
    ("mission_members", "created_at"),
    ("mission_members", "updated_at"),
    ("mission_plans", "created_at"),
    ("mission_plans", "updated_at"),
    ("mission_team_members", "created_at"),
    ("mission_team_members", "updated_at"),
    ("missions", "created_at"),
    ("missions", "updated_at"),
    ("plan_task_states", "approved_at"),
    ("plan_task_states", "created_at"),
    ("plan_task_states", "last_attempt_at"),
    ("plan_task_states", "updated_at"),
    ("plan_task_states", "veto_expires_at"),
    ("prompt_versions", "created_at"),
    ("prompt_versions", "updated_at"),
    ("session_channels", "bound_at"),
    ("session_followups", "consumed_at"),
    ("session_followups", "created_at"),
    ("session_followups", "expires_at"),
    ("session_followups", "updated_at"),
    ("session_messages", "created_at"),
    ("session_messages", "updated_at"),
    ("sessions", "created_at"),
    ("sessions", "expires_at"),
    ("sessions", "last_activity_at"),
    ("sessions", "updated_at"),
    ("task_attempts", "created_at"),
    ("task_attempts", "updated_at"),
    ("task_executions", "completed_at"),
    ("task_executions", "created_at"),
    ("task_executions", "started_at"),
    ("task_executions", "updated_at"),
    ("users", "created_at"),
    ("users", "last_login_at"),
    ("users", "updated_at"),
    ("workflow_definitions", "created_at"),
    ("workflow_definitions", "updated_at"),
    ("workflow_runs", "completed_at"),
    ("workflow_runs", "created_at"),
    ("workflow_runs", "started_at"),
    ("workflow_runs", "updated_at"),
    ("workflow_schedules", "created_at"),
    ("workflow_schedules", "updated_at"),
]


def upgrade() -> None:
    conn = op.get_bind()
    for table, column in COLUMNS:
        conn.execute(sa.text(
            f'ALTER TABLE "{table}" ALTER COLUMN "{column}" '
            f"TYPE timestamptz USING \"{column}\" AT TIME ZONE 'UTC'"
        ))


def downgrade() -> None:
    conn = op.get_bind()
    for table, column in COLUMNS:
        conn.execute(sa.text(
            f'ALTER TABLE "{table}" ALTER COLUMN "{column}" '
            f"TYPE timestamp USING \"{column}\" AT TIME ZONE 'UTC'"
        ))
