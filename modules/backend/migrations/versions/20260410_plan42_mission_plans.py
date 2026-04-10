"""Mission plans + plan task states (Plan 42 Phase 1)

Creates the two tables that back Plan 42's long-lived mission backlog:

    mission_plans      — one row per mission, holds the live TaskPlan JSON
                         + gate_mode + status + budget ceiling + cumulative
                         spend + veto window configuration
    plan_task_states   — per-task cross-run status keyed by (plan_id, task_id)
                         where task_id is the string key inside the
                         TaskPlan JSON (not a DB FK)

Plan 42 §2.1 + §10.7 for schema rationale.

Revision ID: plan42_001
Revises: phase5_001
Create Date: 2026-04-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# Revision identifiers
revision: str = "plan42_001"
down_revision: Union[str, None] = "phase5_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind: sa.Connection, table: str) -> bool:
    return inspect(bind).has_table(table)


def upgrade() -> None:
    """Create mission_plans and plan_task_states tables."""
    bind = op.get_bind()

    if not _table_exists(bind, "mission_plans"):
        op.create_table(
            "mission_plans",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "mission_id",
                sa.String(36),
                sa.ForeignKey("missions.id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
                index=True,
                comment="One plan per mission — enforced by unique constraint",
            ),
            sa.Column(
                "task_plan_json",
                sa.JSON,
                nullable=True,
                comment=(
                    "Live TaskPlan (schemas/task_plan.py::TaskPlan) serialized "
                    "as JSON. NULL until first refinement. Same shape as "
                    "execution_records.task_plan_json — this is the living "
                    "draft, that is the frozen post-run snapshot."
                ),
            ),
            sa.Column(
                "gate_mode",
                sa.String(20),
                nullable=True,
                comment=(
                    "Autonomy mode: off, interactive, ai_assisted, autonomous. "
                    "Inherits from missions.gate_mode at creation; can be "
                    "changed per-plan without affecting the mission default."
                ),
            ),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="active",
                comment="active | paused | completed | archived",
            ),
            sa.Column(
                "version",
                sa.Integer,
                nullable=False,
                server_default="1",
                comment=(
                    "Bumped each time task_plan_json is replaced by refinement. "
                    "Plan 42 §2.5 audit trail (Option A)."
                ),
            ),
            sa.Column(
                "budget_usd_ceiling",
                sa.Float,
                nullable=True,
                comment="Cumulative cap across all runs dispatched from this plan",
            ),
            sa.Column(
                "total_spent_usd",
                sa.Float,
                nullable=False,
                server_default="0.0",
                comment=(
                    "Running total across all executions dispatched from this "
                    "plan. Updated by MissionPlanService after each run. "
                    "Plan 42 §10.7 cumulative budget enforcement."
                ),
            ),
            sa.Column(
                "veto_window_sec",
                sa.Integer,
                nullable=True,
                comment=(
                    "When non-null and gate_mode=ai_assisted, Director-auto-"
                    "approved tasks wait this many seconds before queueing "
                    "so the user can veto. NULL = no veto window."
                ),
            ),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
        )

    if not _table_exists(bind, "plan_task_states"):
        op.create_table(
            "plan_task_states",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "mission_plan_id",
                sa.String(36),
                sa.ForeignKey("mission_plans.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "task_id",
                sa.String(200),
                nullable=False,
                comment=(
                    "String task_id from the TaskPlan JSON. Not a DB FK — "
                    "tasks live inside task_plan_json, not in their own table."
                ),
            ),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="proposed",
                comment=(
                    "proposed | approved | queued | running | completed | "
                    "failed | skipped | cancelled. See Plan 42 §2.3 state machine."
                ),
            ),
            sa.Column(
                "approved_by_user_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="RESTRICT"),
                nullable=True,
                comment="User who approved this task (NULL until approved)",
            ),
            sa.Column(
                "approved_at",
                sa.DateTime,
                nullable=True,
            ),
            sa.Column(
                "execution_record_id",
                sa.String(36),
                sa.ForeignKey("execution_records.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
                comment="Run that executed this task (NULL until executed)",
            ),
            sa.Column(
                "task_execution_id",
                sa.String(36),
                sa.ForeignKey("task_executions.id", ondelete="SET NULL"),
                nullable=True,
                comment="Specific task_execution row within the run",
            ),
            sa.Column(
                "last_attempt_at",
                sa.DateTime,
                nullable=True,
            ),
            sa.Column(
                "retry_count",
                sa.Integer,
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "veto_expires_at",
                sa.DateTime,
                nullable=True,
                comment=(
                    "For ai_assisted mode: when the auto-approval veto window "
                    "closes. NULL = no active window."
                ),
            ),
            sa.Column(
                "result_summary",
                sa.Text,
                nullable=True,
                comment="Short human summary denormalized from the task execution",
            ),
            sa.Column(
                "failure_reason",
                sa.Text,
                nullable=True,
            ),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint(
                "mission_plan_id",
                "task_id",
                name="uq_plan_task_states_plan_task",
            ),
        )
        # Composite index for the Plan tab's grouped-by-status query
        op.create_index(
            "ix_plan_task_states_plan_status",
            "plan_task_states",
            ["mission_plan_id", "status"],
        )


def downgrade() -> None:
    """Drop plan_task_states and mission_plans."""
    bind = op.get_bind()

    if _table_exists(bind, "plan_task_states"):
        op.drop_index(
            "ix_plan_task_states_plan_status",
            table_name="plan_task_states",
        )
        op.drop_table("plan_task_states")

    if _table_exists(bind, "mission_plans"):
        op.drop_table("mission_plans")
