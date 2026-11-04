"""
SSE session guard.

A stream authenticates and is authorised once, when it opens, and can then stay open for hours.
The guard re-checks on a timer, so a stream whose session has ended (logout, password change,
deactivation) or whose user has lost access to what it streams closes instead of delivering events
indefinitely.
"""

import asyncio
import enum
import json
from collections.abc import AsyncIterator, Awaitable, Callable

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


class StreamEnd(str, enum.Enum):
    """Why an open stream is closed. The value is the SSE event the client receives."""

    SESSION_ENDED = "session_ended"
    ACCESS_REVOKED = "access_revoked"


def _frame(end: StreamEnd) -> str:
    return f"event: {end.value}\ndata: {json.dumps({'reason': end.value})}\n\n"


SESSION_ENDED_FRAME = _frame(StreamEnd.SESSION_ENDED)
ACCESS_REVOKED_FRAME = _frame(StreamEnd.ACCESS_REVOKED)


async def close_when_invalid(
    source: AsyncIterator[str],
    check: Callable[[], Awaitable[StreamEnd | None]],
    interval_seconds: float,
) -> AsyncIterator[str]:
    """Relay the frames of ``source``; every ``interval_seconds`` call ``check``.

    ``check`` answers None while the stream may continue, or the reason it must end; the matching
    frame is emitted once and the stream stops. ``source`` is always closed on the way out, so its
    own cleanup (Redis connections, subscriptions) runs. An error in ``check`` propagates and
    closes the stream: a stream that cannot be checked is not treated as allowed.
    """
    loop = asyncio.get_running_loop()
    next_check = loop.time() + interval_seconds
    pending = asyncio.ensure_future(source.__anext__())
    try:
        while True:
            done, _ = await asyncio.wait({pending}, timeout=max(0.0, next_check - loop.time()))

            # Checked on the clock, not only on silence: a busy stream never times out.
            if loop.time() >= next_check:
                next_check = loop.time() + interval_seconds
                ended = await check()
                if ended is not None:
                    logger.info("Closing SSE stream", extra={"reason": ended.value})
                    yield _frame(ended)
                    return

            if pending in done:
                try:
                    frame = pending.result()
                except StopAsyncIteration:
                    return
                pending = asyncio.ensure_future(source.__anext__())
                yield frame
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        aclose = getattr(source, "aclose", None)
        if aclose is not None:
            await aclose()
