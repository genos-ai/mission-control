"""
Session Followup Repository (Plan 51 Phase A).

Data access for ``SessionFollowup``. Thin — all business logic
(template rendering, agent turn spawning, fire accounting) lives in
``SessionFollowupService``. This layer just owns the queries.

The hot path is ``find_matching`` — called by the service on every
emitted event to locate pending followups. The query is carefully
shaped to avoid scanning consumed/expired rows and to let the caller
filter by mission_id.
"""

from datetime import datetime

from sqlalchemy import and_, or_, select

from modules.backend.core.utils import utc_now
from modules.backend.models.session_followup import SessionFollowup
from modules.backend.repositories.base import BaseRepository


class SessionFollowupRepository(BaseRepository[SessionFollowup]):
    """Repository for SessionFollowup CRUD + trigger matching."""

    model = SessionFollowup

    async def find_matching(
        self,
        *,
        event_type: str,
        mission_id: str | None = None,
        session_id: str | None = None,
    ) -> list[SessionFollowup]:
        """Find pending followups that match an incoming event.

        A row matches when ALL of the following hold:

        - ``consumed_at`` IS NULL — the followup has not yet been
          fully consumed (fired ``max_fires`` times).
        - ``expires_at`` > now — the followup is still within its
          TTL window.
        - ``trigger_event_types`` JSON array contains ``event_type``.
        - If ``mission_id`` is provided, the followup's ``mission_id``
          equals it OR is NULL (followups with NULL mission_id match
          any mission — reserved for cross-mission agents, not used
          in v1).
        - If ``session_id`` is provided, the followup's ``session_id``
          equals it. Used for targeted re-evaluation (e.g. Phase E's
          Director subscribes to supervisor decisions for a specific
          session).

        ``trigger_filter`` matching against the event payload is done
        in the service layer (Python-side) rather than SQL — the
        filter is a dict and the matching is simple equality, so
        keeping it in Python avoids awkward JSON-in-SQL logic.

        Args:
            event_type: The ``event_type`` string of the incoming event.
            mission_id: Optional mission filter.
            session_id: Optional session filter.

        Returns:
            List of matching ``SessionFollowup`` rows, oldest first
            (so FIFO firing is predictable for multi-match events).
        """
        now = utc_now()

        # SQL-level filter only on scalar columns — JSON array
        # containment is portable but awkward across SQLite/Postgres,
        # so we narrow by consumed/expired at the DB and do the
        # trigger_event_types contains-check in Python afterwards.
        # At followup cardinality (tens, not millions) this is fine.
        conditions = [
            SessionFollowup.consumed_at.is_(None),
            SessionFollowup.expires_at > now,
        ]
        if mission_id is not None:
            conditions.append(
                or_(
                    SessionFollowup.mission_id == mission_id,
                    SessionFollowup.mission_id.is_(None),
                )
            )
        if session_id is not None:
            conditions.append(SessionFollowup.session_id == session_id)

        stmt = (
            select(SessionFollowup)
            .where(and_(*conditions))
            .order_by(SessionFollowup.created_at.asc())
        )
        result = await self.session.execute(stmt)
        rows = list(result.scalars().all())

        # Python-side trigger_event_types filter — check each row's
        # JSON array contains the event_type. This is O(matched rows)
        # and happens after the SQL-level filter, so it only scans
        # the narrow candidate set.
        return [
            row for row in rows
            if event_type in (row.trigger_event_types or [])
        ]

    async def list_for_session(
        self,
        session_id: str,
        *,
        include_consumed: bool = False,
    ) -> list[SessionFollowup]:
        """List followups for a session, newest first.

        Used by the "Pending followups" UI strip so the user can see
        what agents are watching and cancel them if needed.
        """
        conditions = [SessionFollowup.session_id == session_id]
        if not include_consumed:
            conditions.append(SessionFollowup.consumed_at.is_(None))

        stmt = (
            select(SessionFollowup)
            .where(and_(*conditions))
            .order_by(SessionFollowup.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_active_for_session(self, session_id: str) -> int:
        """Count unconsumed, unexpired followups for a session.

        Used by the per-session cap guardrail — a confused agent
        shouldn't be able to register 50 followups on one session.
        """
        now = utc_now()
        stmt = (
            select(SessionFollowup)
            .where(
                SessionFollowup.session_id == session_id,
                SessionFollowup.consumed_at.is_(None),
                SessionFollowup.expires_at > now,
            )
        )
        result = await self.session.execute(stmt)
        return len(list(result.scalars().all()))

    async def mark_fired(
        self,
        followup_id: str,
        *,
        fired_at: datetime | None = None,
    ) -> SessionFollowup:
        """Increment fire_count and stamp consumed_at if max_fires reached.

        Returns the updated row. Callers use this after a successful
        agent turn spawn.
        """
        row = await self.get_by_id(followup_id)
        row.fire_count = (row.fire_count or 0) + 1
        if row.fire_count >= row.max_fires:
            row.consumed_at = fired_at or utc_now()
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def mark_failed(
        self,
        followup_id: str,
        *,
        reason: str,
    ) -> SessionFollowup:
        """Record that a followup's spawn attempt failed.

        Sets ``failure_reason`` and stamps ``consumed_at`` to prevent
        retry storms. An operator can unset ``consumed_at`` manually
        if they want to retry.
        """
        row = await self.get_by_id(followup_id)
        row.failure_reason = reason
        row.consumed_at = utc_now()
        await self.session.flush()
        await self.session.refresh(row)
        return row
