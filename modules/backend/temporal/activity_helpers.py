"""
Shared helpers for Temporal activities.

Keeps activity modules thin by extracting common patterns
(error emission, session creation, etc.) into one place.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from temporalio import activity

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class HeartbeatState:
    """The phase heartbeat_every reports; the caller may change it while the block runs."""

    phase: str


@asynccontextmanager
async def heartbeat_every(interval_seconds: float, *, phase: str) -> AsyncIterator[HeartbeatState]:
    """Heartbeat {"phase": state.phase} on entry and then every interval_seconds.

    Callers pass the interval (temporal.mission_run.task_heartbeat_interval_seconds,
    read by the activity or carried in its input); workflows never read config.
    The beating task is cancelled on exit.
    """
    state = HeartbeatState(phase=phase)

    async def _beat() -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            activity.heartbeat({"phase": state.phase})

    activity.heartbeat({"phase": state.phase})
    beat = asyncio.create_task(_beat())
    try:
        yield state
    finally:
        beat.cancel()


async def emit_activity_error(
    mission_id: str,
    source: str,
    message: str,
) -> None:
    """Best-effort error event so the console shows activity failures.

    Opens a short-lived Redis connection, publishes a SystemEvent, and
    closes. Swallows all exceptions — this must never mask the real error.
    """
    try:
        import uuid

        from redis.asyncio import Redis as AsyncRedis

        from modules.backend.core.config import get_redis_url
        from modules.backend.events.bus import SessionEventBus
        from modules.backend.events.types import SystemEvent

        redis = AsyncRedis.from_url(get_redis_url())
        try:
            bus = SessionEventBus(redis, mission_id=mission_id)
            await bus.publish_to_mission(
                mission_id,
                SystemEvent(
                    session_id=uuid.uuid4(),
                    source=source,
                    level="error",
                    message=message[:300],
                    mission_id=mission_id,
                ),
            )
        finally:
            await redis.aclose()
    except Exception:
        logger.debug("Failed to emit activity error event (non-fatal)", exc_info=True)
