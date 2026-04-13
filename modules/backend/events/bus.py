"""
Mission Event Bus.

Redis Pub/Sub wrapper for real-time event delivery. All events for a
mission publish to a single channel: mission_events:{mission_id}.

One channel per mission. No per-session channels. The frontend
Stream/Narrative/Runs tabs all subscribe to the mission channel.
Session-scoped views filter by session_id client-side or server-side.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator

from redis.asyncio import Redis

from modules.backend.core.logging import get_logger
from modules.backend.events.types import SessionEvent, deserialize_event

logger = get_logger(__name__)


class SessionEventBus:
    """Publish and subscribe to real-time mission events via Redis Pub/Sub.

    All events go to mission_events:{mission_id}. The bus requires a
    mission_id at construction time so every publish() call knows which
    channel to use.

    For callers that don't have a mission_id (e.g. crash recovery
    publishing to a known mission), use publish_to_mission() directly.
    """

    def __init__(self, redis: Redis, mission_id: str | None = None) -> None:
        self._redis = redis
        self._mission_id = mission_id

    def _channel(self, mission_id: str) -> str:
        return f"mission_events:{mission_id}"

    async def publish(self, event: SessionEvent) -> None:
        """Publish an event to the mission channel.

        Uses the mission_id set at construction. Falls back to a
        session-specific channel if no mission_id was set (shouldn't
        happen in normal operation — log a warning).
        """
        if not self._mission_id:
            logger.warning(
                "SessionEventBus.publish() called without mission_id — event dropped",
                extra={"event_type": event.event_type},
            )
            return

        channel = self._channel(self._mission_id)
        payload = event.model_dump_json()
        await self._redis.publish(channel, payload)

    async def publish_to_mission(self, mission_id: str, event: SessionEvent) -> None:
        """Publish an event to a specific mission's channel.

        Use this when you know the mission_id but it differs from the
        one set at construction (e.g. crash recovery iterating over
        multiple missions).
        """
        channel = self._channel(mission_id)
        payload = event.model_dump_json()
        await self._redis.publish(channel, payload)

    async def subscribe_mission(self, mission_id: str) -> AsyncIterator[SessionEvent]:
        """Subscribe to all events for a mission.

        Yields events as they arrive. Cleans up the subscription on exit.
        """
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
