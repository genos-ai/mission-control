"""
Session Followup Service (Plan 51 Phase A).

Generic wake-on-event primitive. Two public entry points:

- ``schedule_followup(...)`` — called by an agent tool when the
  agent wants to continue the conversation on a future event.
  Validates inputs, enforces the per-session cap, writes a row.

- ``fire_matching(event, *, agent_turn_runner)`` — called
  **in-process** by event emitters after they publish an event.
  Finds matching followups, renders the prompt template against
  the event payload, invokes the caller-supplied ``agent_turn_runner``
  for each match, stamps ``fire_count`` + ``consumed_at``, and
  publishes ``SessionFollowupFiredEvent`` for audit.

Design notes:

- **In-process, not Pub/Sub.** See
  ``docs/97-plans/51-plan-autonomy-loop-supervisor.md`` §5 Phase A
  ("Transport decision"). The autonomy feedback loop runs inside
  the same process that emitted the event, so a direct method call
  is simpler, deterministic, and testable without Pub/Sub timing.

- **Caller owns the agent turn.** The service doesn't import
  ``mission_control.handle`` directly. Instead the caller passes an
  ``agent_turn_runner`` callable: a small adapter that takes
  ``(session_id, mission_id, prompt)`` and actually runs the turn.
  This keeps the service decoupled from the dispatch layer and makes
  testing cheap — the verification script injects a fake runner
  that just records calls.

- **Trigger filter is Python-side.** SQL narrows on scalar fields
  (consumed/expired), Python narrows on JSON fields
  (trigger_event_types contains + trigger_filter literal-match).
  Followup cardinality is tens, not millions, so the Python pass is
  negligible and portable across SQLite/Postgres.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ValidationError
from modules.backend.core.logging import get_logger
from modules.backend.core.protocols import EventBusProtocol, NoOpEventBus
from modules.backend.core.utils import utc_now
from modules.backend.events.types import SessionFollowupFiredEvent
from modules.backend.models.session_followup import SessionFollowup
from modules.backend.repositories.session_followup import SessionFollowupRepository
from modules.backend.services.base import BaseService

logger = get_logger(__name__)


# Per-session cap: a confused agent shouldn't be able to register
# 50 followups on one session. 5 is generous for the autonomy loop
# (one run-completion + one budget-warning + headroom).
MAX_ACTIVE_FOLLOWUPS_PER_SESSION = 5

# Default expiry window if the caller doesn't specify one. 24 hours
# is long enough for overnight autonomous loops but short enough
# that forgotten "I'll check back" followups don't fire weeks later
# against stale state.
DEFAULT_EXPIRES_IN_SECONDS = 24 * 60 * 60


# Type alias for the caller-supplied agent turn runner. Takes the
# session to wake, the mission context, and the rendered prompt;
# returns an awaitable that resolves when the turn completes (or
# errors). The service doesn't care about the return value — the
# agent's events flow through the event bus independently.
AgentTurnRunner = Callable[
    [str, str, str],  # (session_id, mission_id, prompt)
    Awaitable[None],
]


class SessionFollowupService(BaseService):
    """Orchestrates wake-on-event followups.

    v1 scope (Plan 51 Phase A):
        - Validated ``schedule_followup``
        - ``fire_matching`` with in-process agent turn dispatch
        - Per-session cap + expiry TTL + failure recording

    Not yet:
        - Cross-process wake via Redis PSUBSCRIBE (deferred, see
          §5 Phase A transport decision)
        - Multi-fire followups with cooldown (columns exist, v1
          uses ``max_fires = 1`` exclusively)
        - Cleanup job for expired rows (v1 leaves them as audit
          trail; a cron can prune later)
    """

    def __init__(
        self,
        session: AsyncSession,
        event_bus: EventBusProtocol | None = None,
    ) -> None:
        super().__init__(session)
        self._repo = SessionFollowupRepository(session)
        self._event_bus: EventBusProtocol = event_bus or NoOpEventBus()

    async def _emit_fired(
        self,
        row: SessionFollowup,
        *,
        trigger_event_type: str,
        success: bool,
        failure_reason: str | None = None,
    ) -> None:
        """Publish a ``SessionFollowupFiredEvent`` for audit.

        Best-effort: a Redis blip must not fail the followup firing
        path. We log and continue. The authoritative state lives on
        the ``session_followups`` row itself; the event is just the
        fan-out signal for log consumers.
        """
        if not row.mission_id:
            # Fired event is a mission-channel event. A followup
            # without mission_id has nowhere to publish — just skip.
            # The row itself is still updated as the source of truth.
            return
        event = SessionFollowupFiredEvent(
            session_id=uuid.UUID(row.session_id),
            source="session_followup_service",
            followup_id=row.id,
            mission_id=row.mission_id,
            trigger_event_type=trigger_event_type,
            created_by_agent=row.created_by_agent,
            success=success,
            failure_reason=failure_reason or "",
        )
        try:
            await self._event_bus.publish_to_mission(row.mission_id, event)
        except Exception as exc:  # noqa: BLE001
            # best-effort — this IS the event-emission path; there is
            # nowhere further to escalate to.
            self._logger.warning(
                "Failed to publish SessionFollowupFiredEvent",
                extra={
                    "followup_id": row.id,
                    "mission_id": row.mission_id,
                    "error": str(exc),
                },
            )

    # ── Schedule ─────────────────────────────────────────────────────────

    async def schedule_followup(
        self,
        *,
        session_id: str,
        mission_id: str | None,
        trigger_event_types: list[str],
        prompt_template: str,
        created_by_agent: str,
        trigger_filter: dict[str, Any] | None = None,
        expires_in_seconds: int = DEFAULT_EXPIRES_IN_SECONDS,
        max_fires: int = 1,
        cooldown_seconds: int = 0,
    ) -> SessionFollowup:
        """Register a new followup.

        Raises ``ValidationError`` for:
            - empty ``trigger_event_types``
            - empty or whitespace-only ``prompt_template``
            - empty ``created_by_agent``
            - ``expires_in_seconds`` <= 0
            - ``max_fires`` < 1
            - ``max_fires`` > 1 with ``cooldown_seconds`` <= 0
              (rate-limited multi-fire followups must declare a cooldown)
            - per-session cap exceeded
            - ``max_fires > 1`` (v1 intentionally rejects — the column
              exists for the future, but wiring, tests, and guardrails
              are not yet in place for multi-fire followups)
        """
        # Input validation — fail fast with a clear error, don't
        # trust callers (including agents).
        if not trigger_event_types:
            raise ValidationError("trigger_event_types must be non-empty")
        if not isinstance(trigger_event_types, list) or not all(
            isinstance(t, str) and t for t in trigger_event_types
        ):
            raise ValidationError("trigger_event_types must be a list of non-empty strings")
        if not prompt_template or not prompt_template.strip():
            raise ValidationError("prompt_template is required")
        if not created_by_agent or not created_by_agent.strip():
            raise ValidationError("created_by_agent is required")
        if expires_in_seconds <= 0:
            raise ValidationError("expires_in_seconds must be positive")
        if max_fires < 1:
            raise ValidationError("max_fires must be >= 1")
        if max_fires > 1:
            # v1 scope cut — multi-fire followups have cooldown +
            # cost accounting concerns that Phase A intentionally
            # defers. Unblock by tightening the guardrail in a
            # follow-up, don't sneak it in here.
            raise ValidationError("max_fires > 1 is not yet supported (Plan 51 Phase A v1)")
        if cooldown_seconds < 0:
            raise ValidationError("cooldown_seconds must be >= 0")

        # Per-session cap — defends the DB against a runaway agent
        # that schedules one followup per turn for hours.
        active = await self._repo.count_active_for_session(session_id)
        if active >= MAX_ACTIVE_FOLLOWUPS_PER_SESSION:
            raise ValidationError(
                f"Session {session_id} already has {active} active "
                f"followups (cap: {MAX_ACTIVE_FOLLOWUPS_PER_SESSION})"
            )

        expires_at = utc_now() + timedelta(seconds=expires_in_seconds)

        followup = await self._repo.create(
            session_id=session_id,
            mission_id=mission_id,
            trigger_event_types=list(trigger_event_types),
            trigger_filter=trigger_filter,
            prompt_template=prompt_template.strip(),
            created_by_agent=created_by_agent.strip(),
            expires_at=expires_at,
            max_fires=max_fires,
            cooldown_seconds=cooldown_seconds,
        )
        self._log_operation(
            "SessionFollowup scheduled",
            followup_id=followup.id,
            session_id=session_id,
            mission_id=mission_id,
            agent=created_by_agent,
            triggers=trigger_event_types,
            expires_at=expires_at.isoformat(),
        )
        return followup

    # ── Fire ─────────────────────────────────────────────────────────────

    async def fire_matching(
        self,
        event: Any,
        *,
        agent_turn_runner: AgentTurnRunner,
    ) -> list[SessionFollowup]:
        """Find followups matching ``event`` and fire each one.

        Iterates matches FIFO (oldest first). For each match:

        1. Render ``prompt_template`` via ``str.format_map`` against
           the event's payload dict.
        2. Invoke ``agent_turn_runner(session_id, mission_id, prompt)``.
        3. On success: increment ``fire_count`` and stamp ``consumed_at``
           if ``fire_count >= max_fires``. Since v1 caps
           ``max_fires = 1`` this always consumes on first fire.
        4. On failure: record ``failure_reason`` and stamp
           ``consumed_at`` to prevent reentrant storms.

        The caller supplies ``agent_turn_runner`` so the service stays
        decoupled from the dispatch layer. Production callers thread
        through a small adapter that calls ``mission_control.handle``;
        tests inject a fake runner that records invocations.

        Returns the list of followups that were fired (or attempted to
        fire and failed). Used by tests + audit logging.

        This method never raises — individual followup failures are
        recorded on the row, not bubbled. Raising would give one
        failing followup the power to prevent later followups from
        running, which is the wrong failure mode for a fan-out event
        handler.
        """
        event_type = getattr(event, "event_type", None) or (
            event.get("event_type") if isinstance(event, dict) else None
        )
        if not event_type:
            logger.warning(
                "fire_matching called with event lacking event_type",
                extra={
                    "event_type": type(event).__name__,
                    "mission_id": getattr(event, "mission_id", None),
                },
            )
            return []

        # Extract the event payload as a dict for template rendering
        # and filter matching. Pydantic models expose model_dump();
        # plain dicts pass through; others are rejected with a log
        # line (not an exception — we're in a fan-out handler).
        if hasattr(event, "model_dump"):
            payload: dict[str, Any] = event.model_dump()
        elif isinstance(event, dict):
            payload = dict(event)
        else:
            logger.warning(
                "fire_matching called with non-dict, non-model event",
                extra={"event_type": event_type, "mission_id": getattr(event, "mission_id", None)},
            )
            return []

        mission_id = payload.get("mission_id")

        # Narrow by consumed/expired at SQL level, then filter by
        # trigger_event_types in Python (JSON array containment is
        # awkward across SQLite/Postgres).
        candidates = await self._repo.find_matching(
            event_type=event_type,
            mission_id=mission_id if isinstance(mission_id, str) else None,
        )

        # Apply trigger_filter literal-match in Python. Each
        # followup's filter is a dict of {event_field: expected};
        # the followup matches only if every declared field equals
        # the event's value for that field. Unknown fields (not in
        # payload) never match.
        fired: list[SessionFollowup] = []
        for row in candidates:
            if row.trigger_filter:
                if not _filter_matches(row.trigger_filter, payload):
                    continue

            # Render the prompt template. Using format_map with a
            # defensive default: missing keys render as "" rather
            # than raising KeyError — agents that reference a field
            # the event doesn't carry get a degraded but non-crashing
            # prompt.
            try:
                rendered = row.prompt_template.format_map(_SafeDict(payload))
            except Exception as exc:
                logger.warning(
                    "Followup prompt template render failed",
                    extra={"followup_id": row.id, "error": str(exc), "mission_id": row.mission_id},
                )
                failed_row = await self._repo.mark_failed(
                    row.id,
                    reason=f"template render error: {exc}",
                )
                fired.append(failed_row)
                await self._emit_fired(
                    failed_row,
                    trigger_event_type=event_type,
                    success=False,
                    failure_reason=f"template render error: {exc}",
                )
                continue

            # Spawn the agent turn. Any exception from the runner
            # is recorded on the row — we don't bubble it so sibling
            # followups can still fire.
            try:
                await agent_turn_runner(
                    row.session_id,
                    row.mission_id or "",
                    rendered,
                )
            except Exception as exc:
                logger.error(
                    "Followup agent turn failed",
                    extra={
                        "followup_id": row.id,
                        "session_id": row.session_id,
                        "agent": row.created_by_agent,
                        "error": str(exc),
                        "mission_id": row.mission_id,
                    },
                    exc_info=True,
                )
                failed_row = await self._repo.mark_failed(
                    row.id,
                    reason=f"agent turn error: {exc}",
                )
                fired.append(failed_row)
                await self._emit_fired(
                    failed_row,
                    trigger_event_type=event_type,
                    success=False,
                    failure_reason=f"agent turn error: {exc}",
                )
                continue

            # Success — count the fire and consume if limit reached.
            updated = await self._repo.mark_fired(row.id)
            fired.append(updated)
            self._log_operation(
                "SessionFollowup fired",
                followup_id=updated.id,
                session_id=updated.session_id,
                agent=updated.created_by_agent,
                event_type=event_type,
                fire_count=updated.fire_count,
                max_fires=updated.max_fires,
            )
            await self._emit_fired(
                updated,
                trigger_event_type=event_type,
                success=True,
            )

        return fired

    # ── Read / admin ─────────────────────────────────────────────────────

    async def list_for_session(
        self,
        session_id: str,
        *,
        include_consumed: bool = False,
    ) -> list[SessionFollowup]:
        """List followups for a session. Used by the 'Pending followups' UI strip."""
        return await self._repo.list_for_session(
            session_id,
            include_consumed=include_consumed,
        )

    async def cancel(self, followup_id: str, *, reason: str) -> SessionFollowup:
        """User-initiated cancellation.

        Stamps ``consumed_at`` with a ``failure_reason`` prefixed by
        'cancelled:' so audit queries can distinguish user cancels
        from agent errors.
        """
        row = await self._repo.get_by_id(followup_id)
        row.consumed_at = utc_now()
        row.failure_reason = f"cancelled: {reason}"
        await self._session.flush()
        await self._session.refresh(row)
        self._log_operation(
            "SessionFollowup cancelled",
            followup_id=row.id,
            session_id=row.session_id,
            reason=reason,
        )
        return row


# ── Internal helpers ─────────────────────────────────────────────────────


class _SafeDict(dict):
    """Dict subclass that returns an empty string for missing keys.

    Used with ``str.format_map`` so prompt templates that reference
    event fields the payload doesn't carry render to ``""`` instead
    of raising ``KeyError``. Agents get a degraded-but-valid prompt
    rather than a template failure.
    """

    def __missing__(self, key: str) -> str:
        return ""


def _filter_matches(filter_dict: dict[str, Any], payload: dict[str, Any]) -> bool:
    """Return True iff every key in ``filter_dict`` equals the
    corresponding key in ``payload``.

    Missing payload keys never match (the follow-up's filter declared
    a field the event doesn't carry → the followup is not for this
    event). Equality is ``==``, no coercion.
    """
    for key, expected in filter_dict.items():
        if payload.get(key) != expected:
            return False
    return True
