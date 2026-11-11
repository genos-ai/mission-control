"""Tests for the shared Copilot client health check and restart (Plan 88 step 88.2.5).

A fake client stands in for ``copilot.CopilotClient``; the class-level client
state of ``CopilotModel`` is reset around every test.
"""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.exceptions import ModelHTTPError

from modules.backend.core.config import get_app_config
from modules.backend.core.copilot_model import CopilotModel


class _FakeClient:
    def __init__(
        self,
        *,
        state: str = "connected",
        authenticated: bool = True,
        ping_delay: float = 0.0,
    ) -> None:
        self.state = state
        self.authenticated = authenticated
        self.ping_delay = ping_delay
        self.ping = AsyncMock(side_effect=self._ping)
        self.force_stop = AsyncMock()

    async def _ping(self) -> SimpleNamespace:
        await asyncio.sleep(self.ping_delay)
        return SimpleNamespace(message="pong")

    def get_state(self) -> str:
        return self.state

    async def get_auth_status(self) -> SimpleNamespace:
        return SimpleNamespace(isAuthenticated=self.authenticated)


@pytest.fixture(autouse=True)
def _reset_shared_client():
    saved = (
        CopilotModel._client,
        CopilotModel._started,
        CopilotModel._lock,
        CopilotModel._last_health_check,
    )
    CopilotModel._client, CopilotModel._started = None, False
    CopilotModel._lock, CopilotModel._last_health_check = None, 0.0
    yield
    (
        CopilotModel._client,
        CopilotModel._started,
        CopilotModel._lock,
        CopilotModel._last_health_check,
    ) = saved


def _install(client: _FakeClient, *, last_check: float = 0.0) -> None:
    CopilotModel._client, CopilotModel._started = client, True
    CopilotModel._last_health_check = last_check


@pytest.mark.asyncio
async def test_no_client_is_noop():
    await CopilotModel.ensure_healthy()

    assert CopilotModel._client is None
    assert CopilotModel._last_health_check == 0.0


@pytest.mark.asyncio
async def test_skips_within_interval():
    client = _FakeClient(state="disconnected")
    _install(client, last_check=time.monotonic())

    await CopilotModel.ensure_healthy()

    client.ping.assert_not_awaited()
    client.force_stop.assert_not_awaited()
    assert CopilotModel._client is client


@pytest.mark.asyncio
async def test_restart_on_disconnected_state():
    client = _FakeClient(state="disconnected")
    _install(client)

    await CopilotModel.ensure_healthy()

    client.ping.assert_not_awaited()
    client.force_stop.assert_awaited_once()
    assert CopilotModel._client is None
    assert CopilotModel._started is False


@pytest.mark.asyncio
async def test_restart_on_ping_timeout(monkeypatch):
    cfg = get_app_config().providers.copilot_client
    fast = cfg.model_copy(update={"ping_timeout_seconds": 1})
    monkeypatch.setattr(
        "modules.backend.core.copilot_model.get_app_config",
        lambda: SimpleNamespace(providers=SimpleNamespace(copilot_client=fast)),
    )
    client = _FakeClient(ping_delay=5)
    _install(client)

    await CopilotModel.ensure_healthy()

    client.ping.assert_awaited_once()
    client.force_stop.assert_awaited_once()
    assert CopilotModel._client is None


@pytest.mark.asyncio
async def test_restart_on_ping_error():
    client = _FakeClient()
    client.ping = AsyncMock(side_effect=RuntimeError("Client not connected"))
    _install(client)

    await CopilotModel.ensure_healthy()

    client.force_stop.assert_awaited_once()
    assert CopilotModel._client is None


@pytest.mark.asyncio
async def test_restart_on_unauthenticated():
    client = _FakeClient(authenticated=False)
    _install(client)

    await CopilotModel.ensure_healthy()

    client.ping.assert_awaited_once()
    client.force_stop.assert_awaited_once()
    assert CopilotModel._client is None


@pytest.mark.asyncio
async def test_healthy_client_kept():
    client = _FakeClient()
    _install(client)

    await CopilotModel.ensure_healthy()

    client.ping.assert_awaited_once()
    client.force_stop.assert_not_awaited()
    assert CopilotModel._client is client
    assert CopilotModel._started is True
    assert CopilotModel._last_health_check > 0.0


@pytest.mark.asyncio
async def test_transient_error_resets_client():
    client = _FakeClient()
    _install(client)
    error = ModelHTTPError(status_code=503, model_name="test-model", body="upstream unavailable")
    model = CopilotModel(model_id="test-model")
    model._active_session = MagicMock(
        send_and_wait=AsyncMock(side_effect=error), disconnect=AsyncMock()
    )

    with pytest.raises(ModelHTTPError) as raised:
        await model._simple_request("hello")

    assert raised.value is error
    client.force_stop.assert_awaited_once()
    assert CopilotModel._client is None
    assert CopilotModel._started is False


@pytest.mark.asyncio
async def test_non_transient_error_keeps_client():
    client = _FakeClient()
    _install(client)
    model = CopilotModel(model_id="test-model")
    model._active_session = MagicMock(
        send_and_wait=AsyncMock(side_effect=Exception("tool schema rejected")),
        disconnect=AsyncMock(),
    )

    with pytest.raises(Exception, match="tool schema rejected"):
        await model._simple_request("hello")

    client.force_stop.assert_not_awaited()
    assert CopilotModel._client is client
