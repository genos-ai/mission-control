"""
Mission Console Service.

The Console is a chronological event log for a mission. Its single
source of truth is the `mission_events` table — one query, sorted
by timestamp, no deduplication.

To add a new event type to the Console, add it to `persist_event_types`
in config/settings/events.yaml. Nothing else needed.

See ADR-004 (Unified Async Architecture) for the design rationale.
"""

import json
import re
import uuid

from sqlalchemy import text

from modules.backend.core.logging import get_logger
from modules.backend.events.types import SessionEvent

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Category classification
# ---------------------------------------------------------------------------

_EXECUTION_PATTERN = re.compile(
    r"^(plan\.|agent\.|workflow\.|convergence\.|execution\.|task\.)"
)
_CHAT_PATTERN = re.compile(
    r"^(user\.message\.|assistant\.message\.|agent\.response\.complete)"
)


async def get_console_history(
    db_session,
    mission_id: str,
    limit: int = 500,
) -> list[dict]:
    """Query mission_events for the Console timeline.

    Single source, single query, sorted by timestamp descending.
    """
    result = await db_session.execute(
        text(
            """SELECT id, event_type, source, created_at, data
               FROM mission_events
               WHERE mission_id = :mid
               ORDER BY created_at DESC
               LIMIT :lim"""
        ),
        {"mid": mission_id, "lim": limit},
    )

    timeline: list[dict] = []
    for row in result.fetchall():
        event_data = json.loads(row[4]) if isinstance(row[4], str) else (row[4] or {})
        event_type = row[1]
        timeline.append({
            "event_id": str(row[0]),
            "event_type": event_type,
            "category": classify_event(event_type),
            "timestamp": row[3].isoformat() if row[3] else None,
            "source": row[2] or "",
            "data": event_data,
        })

    return timeline


def classify_event(event_type: str) -> str:
    """Assign a console category to an event type.

    Returns:
        One of ``execution``, ``chat``, or ``system``.
    """
    if _CHAT_PATTERN.match(event_type):
        return "chat"
    if _EXECUTION_PATTERN.match(event_type):
        return "execution"
    return "system"


def format_event_for_sse(event: SessionEvent) -> dict:
    """Wrap a SessionEvent into the SSE wire format the frontend expects.

    Produces the same shape as get_console_history so SSE and history
    share a single wire format.
    """
    flat = json.loads(event.model_dump_json())
    event_type = flat.pop("event_type", "")
    return {
        "event_id": flat.pop("event_id", str(uuid.uuid4())),
        "event_type": event_type,
        "category": classify_event(event_type),
        "timestamp": flat.pop("timestamp", None),
        "source": flat.pop("source", ""),
        "data": flat,
    }
