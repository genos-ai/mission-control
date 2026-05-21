"""
Mission Plan Daemon — heartbeat publisher.

Background asyncio task that publishes a liveness heartbeat to Redis
so the admin daemon-status endpoint can report whether the backend
process is alive.

Dispatch logic has been removed — autonomous plan dispatch is handled
exclusively by Temporal workflows (MissionRunWorkflow). The daemon
exists solely for the heartbeat and as a startup hook.

Config gate: off by default. Explicitly enable in features.yaml:
    experimental_mission_plan_daemon_enabled: true
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from redis.asyncio import Redis as AsyncRedis

from modules.backend.core.config import get_redis_url
from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now

logger = get_logger(__name__)

# Default poll interval for heartbeat publishing.
_DEFAULT_POLL_INTERVAL_SEC = 5.0

# Heartbeat key the daemon writes every tick (Plan 46 Phase 1 #3).
HEARTBEAT_KEY = "mission_plan_daemon:heartbeat"
_HEARTBEAT_TTL_SEC = 20


class MissionPlanDaemon:
    """Background asyncio task that publishes a liveness heartbeat.

    Instantiated at FastAPI startup, runs until shutdown. Dispatch is
    handled by Temporal — this task only publishes heartbeats so the
    admin status endpoint can report process liveness.
    """

    def __init__(
        self,
        *,
        redis_url: str | None = None,
        poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SEC,
    ) -> None:
        self._redis_url = redis_url or get_redis_url()
        self._poll_interval = poll_interval_seconds
        self._redis: AsyncRedis | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._tick_count: int = 0
        self._last_tick_error: str | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        """Create the background task. Safe to call only once per instance."""
        if self._task is not None:
            logger.warning("MissionPlanDaemon already started — ignoring")
            return
        self._redis = AsyncRedis.from_url(self._redis_url)
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_forever(), name="mission_plan_daemon")
        logger.info(
            "MissionPlanDaemon started (heartbeat only)",
            extra={"poll_interval_sec": self._poll_interval},
        )

    async def stop(self) -> None:
        """Signal shutdown and wait for the task to drain."""
        if self._task is None:
            return
        logger.info("MissionPlanDaemon stopping")
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=10.0)
        except asyncio.TimeoutError:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("daemon task raised during cancellation", exc_info=True)
        finally:
            if self._redis is not None:
                await self._redis.aclose()
                self._redis = None
            self._task = None
            logger.info("MissionPlanDaemon stopped")

    # ── Heartbeat loop ────────────────────────────────────────────────

    async def _run_forever(self) -> None:
        """Publish heartbeat every poll_interval."""
        while not self._stop_event.is_set():
            try:
                await self._publish_heartbeat()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._last_tick_error = f"{type(exc).__name__}: {exc}"

            self._tick_count += 1
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._poll_interval,
                )
                return
            except asyncio.TimeoutError:
                continue

    async def _publish_heartbeat(self) -> None:
        """Write the heartbeat payload to Redis with a short TTL."""
        if self._redis is None:
            return
        payload = {
            "timestamp": utc_now().isoformat(),
            "tick_count": self._tick_count,
            "poll_interval_sec": self._poll_interval,
            "last_error": self._last_tick_error,
        }
        try:
            await self._redis.set(
                HEARTBEAT_KEY,
                json.dumps(payload),
                ex=_HEARTBEAT_TTL_SEC,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "MissionPlanDaemon heartbeat publish failed",
                extra={"error": str(exc)},
            )


# ── Module-level singleton for lifespan integration ───────────────────────


_daemon: MissionPlanDaemon | None = None


def get_daemon() -> MissionPlanDaemon | None:
    """Return the currently-running daemon instance, or None."""
    return _daemon


async def start_daemon(**kwargs: Any) -> MissionPlanDaemon:
    """Create + start the process-wide daemon instance."""
    global _daemon
    if _daemon is not None:
        logger.warning("start_daemon called but daemon already running")
        return _daemon
    _daemon = MissionPlanDaemon(**kwargs)
    await _daemon.start()
    return _daemon


async def stop_daemon() -> None:
    """Gracefully stop the process-wide daemon instance."""
    global _daemon
    if _daemon is None:
        return
    await _daemon.stop()
    _daemon = None


# ── Heartbeat reader (Plan 46 Phase 1 #3) ─────────────────────────────────


async def get_heartbeat(redis: AsyncRedis) -> dict[str, Any] | None:
    """Read the most recent daemon heartbeat payload from Redis."""
    raw = await redis.get(HEARTBEAT_KEY)
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)
