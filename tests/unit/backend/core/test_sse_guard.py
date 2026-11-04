"""The SSE session guard closes a stream whose session ended, and cleans up its source."""

import asyncio
from collections.abc import AsyncIterator

import pytest

from modules.backend.core.sse_guard import (
    ACCESS_REVOKED_FRAME,
    SESSION_ENDED_FRAME,
    StreamEnd,
    close_when_invalid,
)

INTERVAL = 0.05


class _Source:
    """An async generator source that records whether its cleanup ran."""

    def __init__(self, frames: list[str], then_wait: bool = True) -> None:
        self.frames = frames
        self.then_wait = then_wait
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[str]:
        try:
            for frame in self.frames:
                yield frame
            if self.then_wait:
                await asyncio.sleep(3600)
        finally:
            self.closed = True


def _ok_for(checks: int, then: StreamEnd = StreamEnd.SESSION_ENDED):
    """A check that answers None `checks` times, then `then`; records every call."""
    calls: list[float] = []

    async def check() -> StreamEnd | None:
        calls.append(asyncio.get_running_loop().time())
        return None if len(calls) <= checks else then

    return check, calls


async def _collect(stream: AsyncIterator[str]) -> list[str]:
    return [frame async for frame in stream]


async def test_relays_frames_and_ends_when_the_source_ends():
    source = _Source(["a", "b"], then_wait=False)
    still_valid, _ = _ok_for(checks=100)

    frames = await _collect(close_when_invalid(source.__aiter__(), still_valid, INTERVAL))

    assert frames == ["a", "b"]
    assert source.closed


async def test_a_silent_stream_is_closed_when_the_session_ends():
    source = _Source(["connected"])
    still_valid, calls = _ok_for(checks=1)

    frames = await asyncio.wait_for(
        _collect(close_when_invalid(source.__aiter__(), still_valid, INTERVAL)), timeout=5
    )

    assert frames == ["connected", SESSION_ENDED_FRAME]
    assert len(calls) == 2
    assert source.closed, "the source's own cleanup (Redis connection) must run"


async def test_a_busy_stream_is_still_checked():
    """Frames arriving faster than the interval never let a wait time out; the check must run
    on the clock anyway."""

    class Busy:
        closed = False

        async def __aiter__(self) -> AsyncIterator[str]:
            try:
                while True:
                    await asyncio.sleep(0.005)
                    yield "tick"
            finally:
                Busy.closed = True

    still_valid, calls = _ok_for(checks=0)

    frames = await asyncio.wait_for(
        _collect(close_when_invalid(Busy().__aiter__(), still_valid, INTERVAL)), timeout=5
    )

    assert frames[-1] == SESSION_ENDED_FRAME
    assert len(calls) == 1
    assert Busy.closed


async def test_checks_are_spaced_by_the_interval():
    source = _Source(["connected"])
    still_valid, calls = _ok_for(checks=2)

    await asyncio.wait_for(
        _collect(close_when_invalid(source.__aiter__(), still_valid, INTERVAL)), timeout=5
    )

    assert len(calls) == 3
    assert all(later - earlier >= INTERVAL * 0.9 for earlier, later in zip(calls, calls[1:]))


async def test_an_error_while_checking_closes_the_stream_and_propagates():
    source = _Source(["connected"])

    async def broken() -> StreamEnd | None:
        raise ConnectionError("database unreachable")

    with pytest.raises(ConnectionError):
        await asyncio.wait_for(
            _collect(close_when_invalid(source.__aiter__(), broken, INTERVAL)), timeout=5
        )

    assert source.closed


async def test_a_client_that_leaves_closes_the_source():
    source = _Source(["connected"])
    still_valid, _ = _ok_for(checks=100)
    stream = close_when_invalid(source.__aiter__(), still_valid, INTERVAL)

    assert await stream.__anext__() == "connected"
    await stream.aclose()

    assert source.closed


async def test_losing_access_ends_the_stream_with_its_own_event():
    """A user who kept their session but lost access to what they stream is told why."""
    source = _Source(["connected"])
    check, _ = _ok_for(checks=1, then=StreamEnd.ACCESS_REVOKED)

    frames = await asyncio.wait_for(
        _collect(close_when_invalid(source.__aiter__(), check, INTERVAL)), timeout=5
    )

    assert frames == ["connected", ACCESS_REVOKED_FRAME]
    assert ACCESS_REVOKED_FRAME != SESSION_ENDED_FRAME
    assert "event: access_revoked" in ACCESS_REVOKED_FRAME
    assert source.closed
