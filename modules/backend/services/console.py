"""
Mission Console Event Aggregator.

Subscribes to Redis Pub/Sub channels for all sessions in a mission,
merges them into a single async stream, and classifies each event
into a console category (execution, chat, system).

Used by the Mission Console SSE endpoint to provide a unified,
real-time view of everything happening inside a mission.
"""

import asyncio
import json
import re
import uuid
from collections.abc import AsyncIterator

from redis.asyncio import Redis
from sqlalchemy import select

from modules.backend.core.config import get_app_config
from modules.backend.core.database import get_async_session
from modules.backend.core.logging import get_logger
from modules.backend.events.types import deserialize_event, SessionEvent
from modules.backend.models.session import Session

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Category classification
# ---------------------------------------------------------------------------

_EXECUTION_PATTERN = re.compile(
    r"^(plan\.|agent\.|workflow\.|convergence\.|session\.cost\.)"
)
_CHAT_PATTERN = re.compile(
    r"^(assistant\.message\.delta|assistant\.message\.complete|user\.message\.)"
)


def classify_event(event_type: str) -> str:
    """Assign a console category to an event type.

    Returns:
        One of ``execution``, ``chat``, or ``system``.
    """
    if _EXECUTION_PATTERN.match(event_type):
        return "execution"
    if _CHAT_PATTERN.match(event_type):
        return "chat"
    return "system"


# ---------------------------------------------------------------------------
# MissionEventAggregator
# ---------------------------------------------------------------------------


class MissionEventAggregator:
    """Aggregate real-time events from every session in a mission.

    The aggregator:
    1. Queries the DB for all sessions belonging to a mission.
    2. Subscribes to the Redis Pub/Sub channel for each session.
    3. Merges all channels into a single ``asyncio.Queue``.
    4. Re-queries sessions every ``refresh_interval`` seconds to pick up
       new sessions that were created after the aggregator started.
    """

    def __init__(
        self,
        redis: Redis,
        mission_id: str,
        refresh_interval: float = 30.0,
    ) -> None:
        self._redis = redis
        self._mission_id = mission_id
        self._refresh_interval = refresh_interval

        self._prefix = get_app_config().events.channel_prefix
        self._queue: asyncio.Queue[SessionEvent] = asyncio.Queue()

        # Tracks which session IDs we are already subscribed to
        self._subscribed_ids: set[str] = set()
        # One pubsub per session subscription
        self._pubsubs: list = []
        # Background tasks for each subscription reader + the refresh loop
        self._tasks: list[asyncio.Task] = []
        self._stopped = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Bootstrap subscriptions and start the refresh loop."""
        await self._refresh_sessions()
        self._tasks.append(
            asyncio.create_task(self._refresh_loop(), name="console-refresh")
        )

    async def stop(self) -> None:
        """Cancel all background tasks and clean up subscriptions."""
        self._stopped = True
        for task in self._tasks:
            task.cancel()
        # Wait for tasks to actually finish (suppress CancelledError)
        await asyncio.gather(*self._tasks, return_exceptions=True)
        for ps in self._pubsubs:
            try:
                await ps.unsubscribe()
                await ps.close()
            except Exception:
                pass
        logger.debug(
            "MissionEventAggregator stopped",
            extra={"mission_id": self._mission_id},
        )

    async def __aiter__(self) -> AsyncIterator[dict]:
        """Yield enriched event dicts as they arrive."""
        while not self._stopped:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            payload = json.loads(event.model_dump_json())
            payload["category"] = classify_event(event.event_type)
            yield payload

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_session_ids(self) -> set[str]:
        """Query all session IDs belonging to this mission.

        Uses a short-lived session so long-running SSE streams do not hold a
        pool connection for their entire lifetime (only while this query runs).
        """
        async with get_async_session() as db:
            result = await db.execute(
                select(Session.id).where(Session.mission_id == self._mission_id)
            )
            return {row[0] for row in result.all()}

    async def _refresh_sessions(self) -> None:
        """Subscribe to any new sessions that appeared since last check."""
        current_ids = await self._get_session_ids()
        new_ids = current_ids - self._subscribed_ids
        for sid in new_ids:
            await self._subscribe_session(sid)
        if new_ids:
            logger.debug(
                "Console subscribed to new sessions",
                extra={
                    "mission_id": self._mission_id,
                    "new_session_count": len(new_ids),
                    "total_sessions": len(self._subscribed_ids),
                },
            )

    async def _subscribe_session(self, session_id: str) -> None:
        """Subscribe to a single session's Pub/Sub channel."""
        channel = f"{self._prefix}:{session_id}"
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        self._pubsubs.append(pubsub)
        self._subscribed_ids.add(session_id)

        task = asyncio.create_task(
            self._read_pubsub(pubsub, channel),
            name=f"console-sub-{session_id[:8]}",
        )
        self._tasks.append(task)

    async def _read_pubsub(self, pubsub, channel: str) -> None:
        """Read messages from a single Pub/Sub subscription and enqueue them."""
        try:
            while not self._stopped:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message is None:
                    await asyncio.sleep(0.01)
                    continue
                if message["type"] != "message":
                    continue

                try:
                    data = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    logger.warning(
                        "Invalid JSON in console event",
                        extra={"channel": channel},
                    )
                    continue

                event = deserialize_event(data)
                if event is not None:
                    await self._queue.put(event)
        except asyncio.CancelledError:
            pass

    async def _refresh_loop(self) -> None:
        """Periodically re-query sessions to pick up new ones."""
        try:
            while not self._stopped:
                await asyncio.sleep(self._refresh_interval)
                try:
                    await self._refresh_sessions()
                except Exception:
                    logger.warning(
                        "Console session refresh failed",
                        extra={"mission_id": self._mission_id},
                        exc_info=True,
                    )
        except asyncio.CancelledError:
            pass
