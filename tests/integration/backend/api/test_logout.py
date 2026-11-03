"""POST /auth/logout ends the session behind the bearer token, through the real endpoints."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.dependencies import get_current_user_sse
from modules.backend.core.exceptions import AuthenticationError
from modules.backend.models.user import User
from tests.conftest import get_test_redis_url


async def _login(client: AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "test@mission-control.dev", "password": "test-password"},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_logout_ends_access_and_refresh_tokens(client: AsyncClient, test_user: User):
    tokens = await _login(client)
    me = await client.get("/api/v1/auth/me", headers=_bearer(tokens["access_token"]))
    assert me.status_code == 200

    response = await client.post("/api/v1/auth/logout", headers=_bearer(tokens["access_token"]))
    assert response.status_code == 200
    assert response.json()["success"] is True

    after = await client.get("/api/v1/auth/me", headers=_bearer(tokens["access_token"]))
    assert after.status_code == 401
    refresh = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refresh.status_code == 401


async def test_logout_of_an_ended_session_is_unauthorised(client: AsyncClient, test_user: User):
    tokens = await _login(client)
    await client.post("/api/v1/auth/logout", headers=_bearer(tokens["access_token"]))

    again = await client.post("/api/v1/auth/logout", headers=_bearer(tokens["access_token"]))

    assert again.status_code == 401


async def test_logout_requires_authentication(client: AsyncClient):
    response = await client.post("/api/v1/auth/logout")

    assert response.status_code == 401


@pytest.fixture
def sse_redis(redis: AsyncRedis, monkeypatch: pytest.MonkeyPatch) -> AsyncRedis:
    """Point the SSE token store at the test Redis database, which the redis fixture flushes."""
    monkeypatch.setattr("modules.backend.core.config.get_redis_url", get_test_redis_url)
    return redis


@pytest.fixture
def sse_session(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncSession:
    """Hand the SSE dependency the test session.

    The user the fixtures create sits in the test transaction, which a second session cannot
    see, so the dependency cannot open its own as it does in production.
    """

    @asynccontextmanager
    async def scope() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr("modules.backend.core.dependencies.get_async_session", scope)
    return db_session


async def _mint_sse_token(client: AsyncClient, access_token: str) -> str:
    response = await client.post("/api/v1/auth/sse-token", headers=_bearer(access_token))
    assert response.status_code == 200, response.text
    return response.json()["data"]["token"]


async def test_sse_token_of_a_live_session_connects(
    client: AsyncClient, test_user: User, sse_redis: AsyncRedis, sse_session: AsyncSession
):
    tokens = await _login(client)
    sse_token = await _mint_sse_token(client, tokens["access_token"])

    user = await get_current_user_sse(token=sse_token, authorization=None)

    assert user.id == test_user.id


async def test_sse_token_minted_before_logout_is_refused_after(
    client: AsyncClient, test_user: User, sse_redis: AsyncRedis, sse_session: AsyncSession
):
    tokens = await _login(client)
    sse_token = await _mint_sse_token(client, tokens["access_token"])
    await client.post("/api/v1/auth/logout", headers=_bearer(tokens["access_token"]))

    with pytest.raises(AuthenticationError, match="Session ended"):
        await get_current_user_sse(token=sse_token, authorization=None)


async def test_sse_token_of_another_session_survives_logout(
    client: AsyncClient, test_user: User, sse_redis: AsyncRedis, sse_session: AsyncSession
):
    laptop = await _login(client)
    phone = await _login(client)
    sse_token = await _mint_sse_token(client, phone["access_token"])
    await client.post("/api/v1/auth/logout", headers=_bearer(laptop["access_token"]))

    user = await get_current_user_sse(token=sse_token, authorization=None)

    assert user.id == test_user.id
