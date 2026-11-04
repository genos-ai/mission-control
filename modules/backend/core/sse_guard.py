"""
SSE session guard.

A stream authenticates once, when it opens, and can then stay open for hours. The guard
re-validates the credential on a timer so a stream whose session has ended (logout, password
change, deactivation) closes instead of delivering events indefinitely.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

SESSION_ENDED_FRAME = f"event: session_ended\ndata: {json.dumps({'reason': 'session_ended'})}\n\n"


async def close_when_invalid(
    source: AsyncIterator[str],
    still_valid: Callable[[], Awaitable[bool]],
    interval_seconds: float,
) -> AsyncIterator[str]:
    """Relay the frames of ``source``; every ``interval_seconds`` call ``still_valid``.

    When it answers False, emit one ``session_ended`` frame and stop. ``source`` is always closed
    on the way out, so its own cleanup (Redis connections, subscriptions) runs. An error in
    ``still_valid`` propagates and closes the stream: a credential that cannot be checked is not
    treated as good.
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
                if not await still_valid():
                    logger.info("Closing SSE stream: its session has ended")
                    yield SESSION_ENDED_FRAME
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
