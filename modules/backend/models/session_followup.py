"""
Session Followup Model (Plan 51 Phase A).

Generic wake-on-event primitive. A `session_followups` row is an
agent's **declared intent to continue the conversation** when a
specific event occurs — the agent says "I'll check back when the
dispatched run completes" and registers a row here; when the
triggering event fires, the `SessionFollowupService` renders the
prompt template against the event payload and spawns a fresh turn
for the agent in the same session.

This is the foundation for Plan 51's autonomy loop (the post-run
supervisor and the Director's proactive chat updates both consume
it), but it is deliberately **generic**: any agent can register a
followup for any event type, not just autonomy-loop events.

Ownership chain:
  - ``session_id`` is the hard owner. Deleting the session cascades
    the followup — orphaned followups for a closed session are
    useless noise.
  - ``mission_id`` is denormalised for efficient filtering when
    fire_matching scans followups for a mission-scoped event.

Consumption semantics:
  - ``consumed_at`` is non-NULL once the followup has fired
    ``max_fires`` times. A consumed row stays in the table as audit
    trail — the stall detector and cost accountant read history.
  - ``cooldown_seconds`` rate-limits re-fires for ``max_fires > 1``
    followups (future use — v1 only uses ``max_fires = 1``).
  - ``expires_at`` is a hard TTL — followups older than this are
    ignored even if ``consumed_at`` is NULL. Prevents a forgotten
    "I'll check back" from firing weeks later against stale state.

See ``docs/97-plans/51-plan-autonomy-loop-supervisor.md`` §5 Phase A
for the full design rationale.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class SessionFollowup(UUIDMixin, TimestampMixin, Base):
    """A registered "wake me on this event" intent.

    Agents schedule these via the ``schedule_followup`` tool (Plan 51
    §5 Phase A). The ``SessionFollowupService.fire_matching(event)``
    entry point finds all matching rows for an incoming event and
    spawns a fresh agent turn for each.
    """

    __tablename__ = "session_followups"

    session_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Session that owns the followup. Cascade on delete.",
    )
    mission_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        nullable=True,
        index=True,
        comment=(
            "Denormalised mission filter. Not a hard FK — sessions "
            "already own their mission_id; this is a query shortcut "
            "so fire_matching can filter by mission without joining."
        ),
    )

    # Trigger specification. An agent says "wake me when one of these
    # event_types arrives AND the filter matches the event payload".
    # trigger_event_types is a JSON array of strings; trigger_filter
    # is a dict of {event_field: expected_value} matched literally.
    trigger_event_types: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        comment=(
            "JSON array of event_type strings the followup subscribes "
            "to. e.g. ['mission_plan.run.completed']."
        ),
    )
    trigger_filter: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment=(
            "Optional literal-match filter against the event payload. "
            "e.g. {'mission_id': '...'} fires only for that mission. "
            "NULL means match any event of the declared types."
        ),
    )

    # What to do when the trigger fires. The prompt_template is
    # rendered against the event payload via str.format_map before
    # being passed to the agent as the message of the fresh turn.
    prompt_template: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment=(
            "Prompt to send to the agent when the followup fires. "
            "Rendered via str.format_map(event_dict) so it can "
            "reference event fields like {execution_record_id}."
        ),
    )
    created_by_agent: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment=(
            "Which agent scheduled this followup. Used by the stall "
            "detector and the cost accountant. Also surfaced in the "
            "'Pending followups' UI strip so users can see who's "
            "watching."
        ),
    )

    # Lifecycle fields.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        comment=(
            "Hard TTL. A followup older than this is ignored by "
            "fire_matching even if not yet consumed. Cleanup job "
            "can prune rows where expires_at < now."
        ),
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment=(
            "Set when the followup has fired max_fires times. Row "
            "stays in the table as audit trail — the supervisor "
            "iteration counter reads history from here."
        ),
    )
    cooldown_seconds: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        comment=(
            "Minimum seconds between fires for max_fires > 1. v1 "
            "uses max_fires = 1 so this is reserved."
        ),
    )
    max_fires: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
        comment=(
            "How many times this followup can fire before being "
            "consumed. Defaults to 1 — one-shot. Higher values are "
            "opt-in and require cooldown_seconds > 0."
        ),
    )
    fire_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        comment="How many times this followup has fired so far.",
    )
    failure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment=(
            "If the followup's agent turn failed, the error message "
            "is stored here. Not NULL implies the followup attempted "
            "to fire but the agent errored — operator can inspect."
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<SessionFollowup(id={self.id!r}, session={self.session_id!r}, "
            f"agent={self.created_by_agent!r}, "
            f"triggers={self.trigger_event_types!r}, "
            f"fires={self.fire_count}/{self.max_fires})>"
        )
