"""An SSE credential follows the session it was minted from, and an open stream follows it too.

Real database and real Redis. The user the fixtures create sits in the test transaction, which a
second session cannot see, so the code under test is handed the test session where production opens
its own.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.api.v1.endpoints import streams
from modules.backend.core.config import get_app_config
from modules.backend.core.dependencies import get_sse_session
from modules.backend.core.exceptions import AuthenticationError
from modules.backend.core.sse_guard import SESSION_ENDED_FRAME
from modules.backend.models.user import User
from modules.backend.services.auth import AuthService
from modules.backend.services.user import UserService
from tests.conftest import get_test_redis_url

PASSWORD = "test-password"
NEW_PASSWORD = "a-new-password-456"


@pytest.fixture
def sse_redis(redis: AsyncRedis, monkeypatch: pytest.MonkeyPatch) -> AsyncRedis:
    """Point the SSE token store at the test Redis database, which the redis fixture flushes."""
    monkeypatch.setattr("modules.backend.core.config.get_redis_url", get_test_redis_url)
    return redis


@pytest.fixture
def sse_db(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncSession:
    @asynccontextmanager
    async def scope() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr("modules.backend.core.dependencies.get_async_session", scope)
    monkeypatch.setattr("modules.backend.api.v1.endpoints.streams.get_async_session", scope)
    return db_session


async def _login(client: AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/auth/login", json={"email": "test@mission-control.dev", "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _mint_sse_token(client: AsyncClient, access_token: str) -> str:
    response = await client.post("/api/v1/auth/sse-token", headers=_bearer(access_token))
    assert response.status_code == 200, response.text
    return response.json()["data"]["token"]


# ---- A token minted before the session ended is refused after ----


async def test_sse_token_of_a_live_session_connects(
    client: AsyncClient, test_user: User, sse_redis: AsyncRedis, sse_db: AsyncSession
):
    tokens = await _login(client)
    sse_token = await _mint_sse_token(client, tokens["access_token"])

    session = await get_sse_session(token=sse_token, authorization=None)

    assert session.user.id == test_user.id
    assert session.identity.user_id == test_user.id


async def test_sse_token_minted_before_logout_is_refused_after(
    client: AsyncClient, test_user: User, sse_redis: AsyncRedis, sse_db: AsyncSession
):
    tokens = await _login(client)
    sse_token = await _mint_sse_token(client, tokens["access_token"])
    await client.post("/api/v1/auth/logout", headers=_bearer(tokens["access_token"]))

    with pytest.raises(AuthenticationError, match="Session ended"):
        await get_sse_session(token=sse_token, authorization=None)


async def test_sse_token_of_another_session_survives_logout(
    client: AsyncClient, test_user: User, sse_redis: AsyncRedis, sse_db: AsyncSession
):
    laptop = await _login(client)
    phone = await _login(client)
    sse_token = await _mint_sse_token(client, phone["access_token"])
    await client.post("/api/v1/auth/logout", headers=_bearer(laptop["access_token"]))

    session = await get_sse_session(token=sse_token, authorization=None)

    assert session.user.id == test_user.id


async def test_sse_token_minted_before_a_password_change_is_refused_after(
    client: AsyncClient, test_user: User, sse_redis: AsyncRedis, sse_db: AsyncSession
):
    tokens = await _login(client)
    sse_token = await _mint_sse_token(client, tokens["access_token"])
    await UserService(sse_db).change_password(test_user.id, PASSWORD, NEW_PASSWORD, test_user)

    with pytest.raises(AuthenticationError, match="Session ended"):
        await get_sse_session(token=sse_token, authorization=None)


# ---- A stream that is already open follows the session ----


@pytest.fixture
def fast_recheck(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-check every 0.1 s instead of the configured interval, through the real config object."""
    monkeypatch.setattr(get_app_config().security.sse, "session_recheck_seconds", 0.1)


async def _open_stream(
    client: AsyncClient, sse_db: AsyncSession
) -> tuple[dict, AsyncIterator[str]]:
    """A guarded stream, built by the endpoints' own guard, for a fresh login."""
    tokens = await _login(client)
    identity = await AuthService(sse_db).session_identity_of(tokens["access_token"])

    async def frames() -> AsyncIterator[str]:
        yield "event: connected\ndata: {}\n\n"
        await asyncio.sleep(3600)

    return tokens, streams._guarded(frames(), identity)


async def test_open_stream_closes_after_logout(
    client: AsyncClient, test_user: User, sse_db: AsyncSession, fast_recheck: None
):
    tokens, stream = await _open_stream(client, sse_db)
    assert (await stream.__anext__()).startswith("event: connected")

    # The stream is suspended between frames here, so the test and the guard never use the
    # database connection at the same time.
    await client.post("/api/v1/auth/logout", headers=_bearer(tokens["access_token"]))

    assert await asyncio.wait_for(stream.__anext__(), timeout=5) == SESSION_ENDED_FRAME
    with pytest.raises(StopAsyncIteration):
        await stream.__anext__()


async def test_open_stream_closes_after_a_password_change(
    client: AsyncClient, test_user: User, sse_db: AsyncSession, fast_recheck: None
):
    _, stream = await _open_stream(client, sse_db)
    await stream.__anext__()

    await UserService(sse_db).change_password(test_user.id, PASSWORD, NEW_PASSWORD, test_user)

    assert await asyncio.wait_for(stream.__anext__(), timeout=5) == SESSION_ENDED_FRAME


async def test_open_stream_of_another_session_stays_open(
    client: AsyncClient, test_user: User, sse_db: AsyncSession, fast_recheck: None
):
    _, stream = await _open_stream(client, sse_db)
    await stream.__anext__()
    other = await _login(client)

    await client.post("/api/v1/auth/logout", headers=_bearer(other["access_token"]))

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(stream.__anext__(), timeout=0.6)
