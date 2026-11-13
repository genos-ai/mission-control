"""Notification recipients, deliveries, channel identities and action tokens (Plan 88, 88.4.3)

Creates the four tables in contracts 3.1.10: user_channel_identities (with
nullable verified_at and external_username), action_tokens,
mission_notification_recipients and notification_deliveries. Backfills one
TELEGRAM recipient per mission for its owner. The join on users skips owners
that are not user ids, without a cast error.

Downgrade drops the four tables.

Revision ID: plan88_007
Revises: plan88_006
Create Date: 2026-11-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID

revision: str = "plan88_007"
down_revision: Union[str, None] = "plan88_006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_KINDS_JSON = '["run_succeeded", "run_failed", "gate_waiting", "gate_escalated", "gate_timeout_paused", "budget_paused", "run_skipped", "run_missed"]'  # notifications.default_kinds at plan88_007  # noqa: E501

_UUID = PgUUID(as_uuid=False)
_TS = sa.DateTime(timezone=True)


def _id_and_timestamps() -> list[sa.Column]:
    return [
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("created_at", _TS, nullable=False),
        sa.Column("updated_at", _TS, nullable=False),
    ]


def _user_fk(column: str) -> sa.Column:
    return sa.Column(column, _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "user_channel_identities",
        *_id_and_timestamps(),
        _user_fk("user_id"),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("external_username", sa.String(64), nullable=True),
        sa.Column("verified_at", _TS, nullable=True),
        sa.UniqueConstraint("channel", "external_id", name="uq_channel_identity_external"),
        sa.UniqueConstraint("user_id", "channel", name="uq_channel_identity_user"),
    )

    op.create_table(
        "action_tokens",
        *_id_and_timestamps(),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.CHAR(64), nullable=False, unique=True),
        _user_fk("user_id"),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column(
            "gate_request_id",
            _UUID,
            sa.ForeignKey("gate_requests.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("channel_message_ref", sa.String(100), nullable=True),
        sa.Column("expires_at", _TS, nullable=False),
        sa.Column("consumed_at", _TS, nullable=True),
        sa.Column("consumed_action", sa.String(32), nullable=True),
        sa.Column("consumed_ref", sa.String(100), nullable=True, unique=True),
        sa.CheckConstraint(
            "(purpose = 'GATE_DECISION') = (gate_request_id IS NOT NULL)",
            name="ck_action_tokens_gate_purpose",
        ),
    )
    op.create_index("ix_action_tokens_expires_at", "action_tokens", ["expires_at"])

    op.create_table(
        "mission_notification_recipients",
        *_id_and_timestamps(),
        sa.Column(
            "mission_id",
            _UUID,
            sa.ForeignKey("missions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        _user_fk("user_id"),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("kinds", JSONB, nullable=False),
        sa.UniqueConstraint("mission_id", "user_id", "channel", name="uq_recipient"),
    )

    op.create_table(
        "notification_deliveries",
        *_id_and_timestamps(),
        sa.Column(
            "mission_id",
            _UUID,
            sa.ForeignKey("missions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mission_run_id",
            _UUID,
            sa.ForeignKey("mission_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        _user_fk("recipient_user_id"),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("provider_message_ref", sa.String(100), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("sent_at", _TS, nullable=True),
    )
    op.create_index(
        "ix_notification_deliveries_mission_created",
        "notification_deliveries",
        ["mission_id", "created_at"],
    )

    # Owner recipient per mission; owners that are not user ids are skipped by the join.
    op.get_bind().execute(
        sa.text(
            "INSERT INTO mission_notification_recipients "
            "(id, mission_id, user_id, channel, kinds, created_at, updated_at) "
            "SELECT gen_random_uuid(), m.id, u.id, 'TELEGRAM', CAST(:kinds AS jsonb), now(), now() "
            "FROM missions m JOIN users u ON u.id::text = m.owner_id "
            "ON CONFLICT ON CONSTRAINT uq_recipient DO NOTHING"
        ),
        {"kinds": DEFAULT_KINDS_JSON},
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_deliveries_mission_created",
        table_name="notification_deliveries",
    )
    op.drop_table("notification_deliveries")
    op.drop_table("mission_notification_recipients")
    op.drop_index("ix_action_tokens_expires_at", table_name="action_tokens")
    op.drop_table("action_tokens")
    op.drop_table("user_channel_identities")
