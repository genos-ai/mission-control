"""SSE endpoints must hand their database connection back before streaming starts.

A stream stays open for as long as the client does. If it kept a pooled
connection for that time, the pool (pool_size + max_overflow) would cap the
number of concurrent streams across all users and starve ordinary requests.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.backend.api.v1.endpoints import streams

ENDPOINTS = "modules.backend.api.v1.endpoints.streams"


class _SessionScope:
    """Stand-in for get_async_session that records whether the scope is still open."""

    def __init__(self) -> None:
        self.open = False

    @asynccontextmanager
    async def __call__(self):
        self.open = True
        try:
            yield MagicMock()
        finally:
            self.open = False


async def test_mission_stream_releases_session_before_returning_response():
    scope = _SessionScope()
    seen_open_during_check: list[bool] = []

    async def check(db, mission_id, user):
        seen_open_during_check.append(scope.open)

    with (
        patch(f"{ENDPOINTS}.get_async_session", new=scope),
        patch(f"{ENDPOINTS}._require_mission_access", new=check),
    ):
        response = await streams.stream_mission_events("mission-1", MagicMock())

    assert seen_open_during_check == [True]
    assert scope.open is False
    assert response.media_type == "text/event-stream"


async def test_run_stream_releases_session_before_returning_response():
    scope = _SessionScope()
    session_service = MagicMock()
    session_service.get_session = AsyncMock(return_value=MagicMock(mission_id="mission-1"))

    with (
        patch(f"{ENDPOINTS}.get_async_session", new=scope),
        patch(f"{ENDPOINTS}._require_session_access", new=AsyncMock()),
        patch(f"{ENDPOINTS}.SessionService", return_value=session_service),
    ):
        response = await streams.stream_run_events(
            "11111111-1111-4111-8111-111111111111", MagicMock()
        )

    assert scope.open is False
    assert response.media_type == "text/event-stream"


async def test_access_denied_still_releases_session():
    scope = _SessionScope()

    with (
        patch(f"{ENDPOINTS}.get_async_session", new=scope),
        patch(
            f"{ENDPOINTS}._require_mission_access",
            new=AsyncMock(side_effect=streams.AuthorizationError("no")),
        ),
    ):
        with pytest.raises(streams.AuthorizationError):
            await streams.stream_mission_events("mission-1", MagicMock())

    assert scope.open is False


def _dependency_calls(call) -> set:
    """Every callable FastAPI would resolve for an endpoint, from its dependency tree."""
    from fastapi.dependencies.utils import get_dependant

    found: set = set()

    def walk(dependant) -> None:
        for sub in dependant.dependencies:
            found.add(sub.call)
            walk(sub)

    walk(get_dependant(path="/stream", call=call))
    return found


def test_endpoints_do_not_depend_on_the_request_scoped_session():
    """get_db_session anywhere in an endpoint's dependency tree (directly, through DbSession under
    any parameter name, or through SseUser) would pin a connection for the whole stream."""
    from modules.backend.core.database import get_db_session

    for fn in (
        streams.stream_run_events,
        streams.stream_notifications,
        streams.stream_mission_events,
    ):
        assert get_db_session not in _dependency_calls(fn), fn.__name__
