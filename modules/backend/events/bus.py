"""
Mission Event Bus.

Redis Pub/Sub wrapper for real-time event delivery. All events for a
mission publish to a single channel: mission_events:{mission_id}.

Events whose type is in the persist_event_types config are also
written to the mission_events DB table for historical display.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator

from redis.asyncio import Redis

from modules.backend.core.config import get_app_config
from modules.backend.core.logging import get_logger
from modules.backend.events.types import SessionEvent, deserialize_event

logger = get_logger(__name__)

# Loaded once at import — the set of event types to persist to DB.
_persist_types: set[str] | None = None


def _get_persist_types() -> set[str]:
    global _persist_types
    if _persist_types is None:
        _persist_types = set(get_app_config().events.persist_event_types)
    return _persist_types


class SessionEventBus:
    """Publish and subscribe to real-time mission events via Redis Pub/Sub.

    All events go to mission_events:{mission_id}. Events whose type is
    in persist_event_types are also written to the mission_events DB
    table for historical narrative display.
    """

    def __init__(self, redis: Redis, mission_id: str | None = None) -> None:
        self._redis = redis
        self._mission_id = mission_id

    def _channel(self, mission_id: str) -> str:
        return f"mission_events:{mission_id}"

    async def publish(self, event: SessionEvent) -> None:
        """Publish to Redis + persist to DB if configured."""
        if not self._mission_id:
            logger.warning(
                "SessionEventBus.publish() called without mission_id — event dropped",
                extra={"event_type": event.event_type},
            )
            return

        # Redis Pub/Sub — real-time delivery
        channel = self._channel(self._mission_id)
        payload = event.model_dump_json()
        await self._redis.publish(channel, payload)

        # DB persistence — append to mission_events table
        if event.event_type in _get_persist_types():
            await self._persist_event(self._mission_id, event)

    async def publish_to_mission(self, mission_id: str, event: SessionEvent) -> None:
        """Publish to a specific mission's channel + persist."""
        channel = self._channel(mission_id)
        payload = event.model_dump_json()
        await self._redis.publish(channel, payload)

        if event.event_type in _get_persist_types():
            await self._persist_event(mission_id, event)

    async def _persist_event(self, mission_id: str, event: SessionEvent) -> None:
        """Write event to mission_events table. Best-effort — never blocks."""
        try:
            from modules.backend.core.database import get_async_session

            async with get_async_session() as db:
                from sqlalchemy import text

                await db.execute(
                    text(
                        "INSERT INTO mission_events "
                        "(id, mission_id, session_id, event_type, timestamp, source, data) "
                        "VALUES (:id, :mid, :sid, :etype, :ts, :src, :data)"
                    ),
                    {
                        "id": str(event.event_id),
                        "mid": mission_id,
                        "sid": str(event.session_id),
                        "etype": event.event_type,
                        "ts": event.timestamp.isoformat()
                            if hasattr(event.timestamp, "isoformat")
                            else str(event.timestamp),
                        "src": getattr(event, "agent_id", None)
                            or getattr(event, "source", ""),
                        "data": event.model_dump_json(),
                    },
                )
                await db.commit()
        except Exception:
            logger.debug("Event persistence failed (non-fatal)", exc_info=True)

    async def subscribe_mission(self, mission_id: str) -> AsyncIterator[SessionEvent]:
        """Subscribe to all events for a mission."""
        channel = self._channel(mission_id)
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        logger.debug("Subscribed to mission channel", extra={"channel": channel})

        try:
            while True:
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
                    logger.warning("Invalid JSON in event", extra={"channel": channel})
                    continue

                event = deserialize_event(data)
                if event is not None:
                    yield event
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
            logger.debug("Unsubscribed from mission channel", extra={"channel": channel})

    async def subscribe_mission_filtered(
        self, mission_id: str, session_id: uuid.UUID,
    ) -> AsyncIterator[SessionEvent]:
        """Subscribe to a mission channel, yielding only events for one session."""
        target = str(session_id)
        async for event in self.subscribe_mission(mission_id):
            if str(event.session_id) == target:
                yield event
