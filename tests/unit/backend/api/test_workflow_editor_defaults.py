"""GET /workflows/editor-defaults: the model alias new workflow steps start with."""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from modules.backend.core.config import get_app_config
from modules.backend.core.dependencies import get_current_user


@pytest.fixture
def app():
    from modules.backend.api.v1.endpoints import workflows as workflows_module
    from modules.backend.core.exception_handlers import register_exception_handlers

    _app = FastAPI()
    register_exception_handlers(_app)
    _app.include_router(workflows_module.router, prefix="/workflows")
    return _app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def signed_in(app):
    app.dependency_overrides[get_current_user] = lambda: MagicMock(
        id="u1", system_role="user", is_active=True
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.usefixtures("signed_in")
class TestEditorDefaults:
    @pytest.mark.asyncio
    async def test_returns_the_configured_alias(self, client):
        resp = await client.get("/workflows/editor-defaults")

        assert resp.status_code == 200
        assert resp.json()["data"]["step_model"] == get_app_config().workflows.default_step_model

    @pytest.mark.asyncio
    async def test_the_alias_is_one_the_runtime_can_resolve(self, client):
        resp = await client.get("/workflows/editor-defaults")

        assert resp.json()["data"]["step_model"] in get_app_config().models.aliases

    @pytest.mark.asyncio
    async def test_the_path_is_not_taken_for_a_workflow_name(self, client):
        # "/{workflow_name}" is declared too; this route must win for this path.
        resp = await client.get("/workflows/editor-defaults")

        assert resp.status_code != 404


@pytest.mark.asyncio
async def test_requires_a_signed_in_user(client):
    resp = await client.get("/workflows/editor-defaults")

    assert resp.status_code == 401
