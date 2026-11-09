"""POST /missions requires a gate mode (Plan 88 step 88.1.0)."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from modules.backend.api.v1.endpoints.missions import router
from modules.backend.core.exception_handlers import register_exception_handlers


@pytest.mark.asyncio
async def test_create_requires_gate_mode(db_session, test_user):
    from modules.backend.core.database import get_db_session
    from modules.backend.core.dependencies import get_current_user

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v1/missions")

    async def override_db():
        yield db_session

    async def override_user():
        return test_user

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_current_user] = override_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/missions",
            json={
                "name": "gate-mode-required",
                "description": "No gate mode",
                "owner_id": test_user.id,
            },
        )

    assert response.status_code == 422
    assert "gate_mode" in response.text
