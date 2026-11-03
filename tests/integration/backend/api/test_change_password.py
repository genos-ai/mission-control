"""POST /auth/change-password ends every session of the user, through the real endpoints."""

from httpx import AsyncClient

from modules.backend.models.user import User

NEW_PASSWORD = "a-new-password-456"


async def _login(client: AsyncClient, password: str) -> dict:
    response = await client.post(
        "/api/v1/auth/login", json={"email": "test@mission-control.dev", "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_change_password_ends_this_and_every_other_session(
    client: AsyncClient, test_user: User
):
    laptop = await _login(client, "test-password")
    phone = await _login(client, "test-password")

    response = await client.post(
        "/api/v1/auth/change-password",
        headers=_bearer(laptop["access_token"]),
        json={"old_password": "test-password", "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 200, response.text

    for tokens in (laptop, phone):
        me = await client.get("/api/v1/auth/me", headers=_bearer(tokens["access_token"]))
        assert me.status_code == 401
        refresh = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert refresh.status_code == 401

    fresh = await _login(client, NEW_PASSWORD)
    me = await client.get("/api/v1/auth/me", headers=_bearer(fresh["access_token"]))
    assert me.status_code == 200


async def test_wrong_current_password_leaves_sessions_alone(client: AsyncClient, test_user: User):
    tokens = await _login(client, "test-password")

    response = await client.post(
        "/api/v1/auth/change-password",
        headers=_bearer(tokens["access_token"]),
        json={"old_password": "not-the-password", "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 400, response.text

    me = await client.get("/api/v1/auth/me", headers=_bearer(tokens["access_token"]))
    assert me.status_code == 200
