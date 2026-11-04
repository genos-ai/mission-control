"""POST /auth/logout ends the session behind the bearer token, through the real endpoints."""

from httpx import AsyncClient

from modules.backend.models.user import User


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
