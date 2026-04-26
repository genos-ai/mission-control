"""ALTER all varchar(36) columns to native PostgreSQL UUID type.

Every ID column in the system was stored as varchar(36) with UUID v4
string values. This migration converts them to native PostgreSQL UUID
type for better storage efficiency (16 bytes vs 37 bytes), native
indexing, and type safety.

Strategy: drop all FK constraints, ALTER every column in one pass,
re-create FK constraints. All values are already valid UUIDs
(verified by pre-migration audit).

Revision ID: varchar36_to_native_uuid
Revises: system_account_uuids
Create Date: 2026-04-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "varchar36_to_native_uuid"
down_revision: Union[str, None] = "system_account_uuids"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Every FK constraint referencing a varchar(36) column ──────────
# Format: (constraint_name, source_table, source_column, target_table, target_column, ondelete)

FK_CONSTRAINTS = [
    ("api_keys_user_id_fkey", "api_keys", "user_id", "users", "id", "CASCADE"),
    ("context_changes_context_id_fkey", "context_changes", "context_id", "mission_contexts", "id", None),
    ("context_milestones_mission_id_fkey", "context_milestones", "mission_id", "missions", "id", None),
    ("embeddings_mission_id_fkey", "embeddings", "mission_id", "missions", "id", "CASCADE"),
    ("execution_decisions_execution_record_id_fkey", "execution_decisions", "execution_record_id", "execution_records", "id", None),
    ("execution_environments_mission_id_fkey", "execution_environments", "mission_id", "missions", "id", "CASCADE"),
    ("execution_records_mission_id_fkey", "execution_records", "mission_id", "missions", "id", "SET NULL"),
    ("execution_records_parent_execution_record_id_fkey", "execution_records", "parent_execution_record_id", "execution_records", "id", "SET NULL"),
    ("executions_mission_id_fkey", "executions", "mission_id", "missions", "id", "SET NULL"),
    ("milestone_summaries_mission_id_fkey", "milestone_summaries", "mission_id", "missions", "id", None),
    ("mission_artifacts_execution_record_id_fkey", "mission_artifacts", "execution_record_id", "execution_records", "id", "SET NULL"),
    ("mission_artifacts_mission_id_fkey", "mission_artifacts", "mission_id", "missions", "id", "CASCADE"),
    ("mission_artifacts_task_execution_id_fkey", "mission_artifacts", "task_execution_id", "task_executions", "id", "SET NULL"),
    ("mission_contexts_mission_id_fkey", "mission_contexts", "mission_id", "missions", "id", "CASCADE"),
    ("mission_decisions_mission_id_fkey", "mission_decisions", "mission_id", "missions", "id", None),
    ("mission_events_mission_id_fkey", "mission_events", "mission_id", "missions", "id", "CASCADE"),
    ("mission_intents_mission_id_fkey", "mission_intents", "mission_id", "missions", "id", None),
    ("mission_intents_revised_from_fkey", "mission_intents", "revised_from", "mission_intents", "id", None),
    ("mission_intents_session_id_fkey", "mission_intents", "session_id", "sessions", "id", None),
    ("mission_learnings_contradicts_id_fkey", "mission_learnings", "contradicts_id", "mission_learnings", "id", None),
    ("mission_learnings_mission_id_fkey", "mission_learnings", "mission_id", "missions", "id", "CASCADE"),
    ("mission_members_mission_id_fkey", "mission_members", "mission_id", "missions", "id", "CASCADE"),
    ("fk_mission_members_user_id", "mission_members", "user_id", "users", "id", "RESTRICT"),
    ("mission_plans_mission_id_fkey", "mission_plans", "mission_id", "missions", "id", "CASCADE"),
    ("mission_team_members_agent_catalog_id_fkey", "mission_team_members", "agent_catalog_id", "agent_catalog", "id", "CASCADE"),
    ("mission_team_members_mission_id_fkey", "mission_team_members", "mission_id", "missions", "id", "CASCADE"),
    ("plan_task_states_approved_by_user_id_fkey", "plan_task_states", "approved_by_user_id", "users", "id", "RESTRICT"),
    ("plan_task_states_execution_record_id_fkey", "plan_task_states", "execution_record_id", "execution_records", "id", "SET NULL"),
    ("plan_task_states_mission_plan_id_fkey", "plan_task_states", "mission_plan_id", "mission_plans", "id", "CASCADE"),
    ("plan_task_states_task_execution_id_fkey", "plan_task_states", "task_execution_id", "task_executions", "id", "SET NULL"),
    ("session_channels_session_id_fkey", "session_channels", "session_id", "sessions", "id", None),
    ("session_followups_session_id_fkey", "session_followups", "session_id", "sessions", "id", None),
    ("session_messages_session_id_fkey", "session_messages", "session_id", "sessions", "id", None),
    ("task_attempts_task_execution_id_fkey", "task_attempts", "task_execution_id", "task_executions", "id", None),
    ("task_executions_execution_record_id_fkey", "task_executions", "execution_record_id", "execution_records", "id", None),
    ("fk_users_current_mission_id", "users", "current_mission_id", "missions", "id", "SET NULL"),
    ("workflow_definitions_mission_id_fkey", "workflow_definitions", "mission_id", "missions", "id", None),
    ("workflow_runs_execution_record_id_fkey", "workflow_runs", "execution_record_id", "execution_records", "id", "SET NULL"),
    ("workflow_runs_mission_id_fkey", "workflow_runs", "mission_id", "missions", "id", "SET NULL"),
    ("workflow_schedules_mission_id_fkey", "workflow_schedules", "mission_id", "missions", "id", None),
    ("workflow_schedules_workflow_definition_id_fkey", "workflow_schedules", "workflow_definition_id", "workflow_definitions", "id", None),
]

# ── Every varchar(36) column to convert ───────────────────────────
# Format: (table_name, column_name)

# Every varchar column storing UUIDs (both varchar and varchar(36)).
# Derived from DB introspection — includes unbounded varchar PKs
# that UUIDMixin created without an explicit String(36) type.
COLUMNS = [
    ("agent_catalog", "id"),
    ("api_keys", "id"),
    ("api_keys", "user_id"),
    ("context_changes", "context_id"),
    ("context_changes", "execution_id"),
    ("context_changes", "id"),
    ("context_changes", "mission_id"),
    ("context_milestones", "id"),
    ("context_milestones", "mission_id"),
    ("embeddings", "id"),
    ("embeddings", "mission_id"),
    ("embeddings", "source_id"),
    ("execution_decisions", "execution_record_id"),
    ("execution_decisions", "id"),
    ("execution_environments", "id"),
    ("execution_environments", "mission_id"),
    ("execution_records", "id"),
    ("execution_records", "mission_id"),
    ("execution_records", "parent_execution_record_id"),
    ("execution_records", "session_id"),
    ("executions", "id"),
    ("executions", "mission_id"),
    ("executions", "session_id"),
    ("executions", "workflow_run_id"),
    ("llm_calls", "execution_record_id"),
    ("llm_calls", "id"),
    ("llm_calls", "mission_id"),
    ("llm_calls", "session_id"),
    ("milestone_summaries", "id"),
    ("milestone_summaries", "mission_id"),
    ("mission_artifacts", "execution_record_id"),
    ("mission_artifacts", "id"),
    ("mission_artifacts", "mission_id"),
    ("mission_artifacts", "task_execution_id"),
    ("mission_contexts", "id"),
    ("mission_contexts", "mission_id"),
    ("mission_decisions", "execution_id"),
    ("mission_decisions", "id"),
    ("mission_decisions", "mission_id"),
    ("mission_events", "id"),
    ("mission_events", "mission_id"),
    ("mission_events", "session_id"),
    ("mission_intents", "id"),
    ("mission_intents", "mission_id"),
    ("mission_intents", "revised_from"),
    ("mission_intents", "session_id"),
    ("mission_learnings", "contradicts_id"),
    ("mission_learnings", "id"),
    ("mission_learnings", "mission_id"),
    ("mission_members", "id"),
    ("mission_members", "mission_id"),
    ("mission_members", "user_id"),
    ("mission_plans", "id"),
    ("mission_plans", "mission_id"),
    ("mission_team_members", "agent_catalog_id"),
    ("mission_team_members", "id"),
    ("mission_team_members", "mission_id"),
    ("missions", "id"),
    ("plan_task_states", "approved_by_user_id"),
    ("plan_task_states", "execution_record_id"),
    ("plan_task_states", "id"),
    ("plan_task_states", "mission_plan_id"),
    ("plan_task_states", "task_execution_id"),
    ("prompt_versions", "entity_id"),
    ("prompt_versions", "id"),
    ("session_channels", "id"),
    ("session_channels", "session_id"),
    ("session_followups", "id"),
    ("session_followups", "mission_id"),
    ("session_followups", "session_id"),
    ("session_messages", "id"),
    ("session_messages", "session_id"),
    ("sessions", "id"),
    ("sessions", "mission_id"),
    ("sessions", "plan_id"),
    ("sessions", "user_id"),
    ("task_attempts", "id"),
    ("task_attempts", "task_execution_id"),
    ("task_executions", "execution_id"),
    ("task_executions", "execution_record_id"),
    ("task_executions", "id"),
    ("users", "current_mission_id"),
    ("users", "id"),
    ("workflow_definitions", "id"),
    ("workflow_definitions", "mission_id"),
    ("workflow_runs", "execution_record_id"),
    ("workflow_runs", "id"),
    ("workflow_runs", "mission_id"),
    ("workflow_runs", "session_id"),
    ("workflow_schedules", "id"),
    ("workflow_schedules", "mission_id"),
    ("workflow_schedules", "workflow_definition_id"),
]


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Drop ALL FK constraints
    for constraint_name, source_table, *_ in FK_CONSTRAINTS:
        op.drop_constraint(constraint_name, source_table, type_="foreignkey")

    # 2. Clean up empty strings in nullable columns (legacy data)
    #    Empty strings can't be cast to UUID — set them to NULL.
    for table, column in COLUMNS:
        conn.execute(sa.text(
            f"UPDATE \"{table}\" SET \"{column}\" = NULL "
            f"WHERE \"{column}\" = ''"
        ))

    # 3. ALTER every varchar(36) column to UUID
    for table, column in COLUMNS:
        conn.execute(sa.text(
            f'ALTER TABLE "{table}" '
            f'ALTER COLUMN "{column}" TYPE uuid '
            f'USING CASE WHEN "{column}" IS NULL THEN NULL '
            f"ELSE \"{column}\"::uuid END"
        ))

    # 4. Re-create all FK constraints
    for constraint_name, source_table, source_col, target_table, target_col, ondelete in FK_CONSTRAINTS:
        kwargs = {}
        if ondelete:
            kwargs["ondelete"] = ondelete
        op.create_foreign_key(
            constraint_name,
            source_table,
            target_table,
            [source_col],
            [target_col],
            **kwargs,
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Reverse: UUID back to varchar(36)
    for constraint_name, source_table, *_ in FK_CONSTRAINTS:
        op.drop_constraint(constraint_name, source_table, type_="foreignkey")

    for table, column in COLUMNS:
        conn.execute(sa.text(
            f'ALTER TABLE "{table}" '
            f'ALTER COLUMN "{column}" TYPE varchar(36) USING "{column}"::text'
        ))

    for constraint_name, source_table, source_col, target_table, target_col, ondelete in FK_CONSTRAINTS:
        kwargs = {}
        if ondelete:
            kwargs["ondelete"] = ondelete
        op.create_foreign_key(
            constraint_name,
            source_table,
            target_table,
            [source_col],
            [target_col],
            **kwargs,
        )
