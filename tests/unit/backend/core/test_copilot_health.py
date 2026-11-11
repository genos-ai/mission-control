"""Tests for the shared Copilot client health check and restart (Plan 88 step 88.2.5).

A fake client stands in for ``copilot.CopilotClient``; the class-level client
state of ``CopilotModel`` is reset around every test.
"""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from copilot._jsonrpc import JsonRpcError, ProcessExitedError
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.tools import ToolDefinition

from modules.backend.core.config import get_app_config
from modules.backend.core.copilot_model import CopilotModel
from modules.backend.core.exceptions import TransientProviderError


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


def _model_on(client: _FakeClient, session: MagicMock) -> CopilotModel:
    model = CopilotModel(model_id="test-model")
    model._active_session, model._session_client = session, client
    return model


@pytest.mark.asyncio
async def test_transient_error_resets_client():
    """The CLI process dying mid-request resets the shared client (send_and_wait path)."""
    client = _FakeClient()
    _install(client)
    error = ProcessExitedError("CLI process exited with code 1")
    model = _model_on(
        client, MagicMock(send_and_wait=AsyncMock(side_effect=error), disconnect=AsyncMock())
    )

    with pytest.raises(TransientProviderError) as raised:
        await model._simple_request("hello")

    assert raised.value.__cause__ is error
    client.force_stop.assert_awaited_once()
    assert CopilotModel._client is None
    assert CopilotModel._started is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        ProcessExitedError("CLI process exited with code 1"),
        BrokenPipeError("Broken pipe"),
        EOFError("Unexpected end of stream while reading JSON-RPC message"),
    ],
)
async def test_transient_error_on_send_resets_client(error):
    """The tool path's send() hitting a dead transport resets the shared client."""
    client = _FakeClient()
    session = MagicMock(send=AsyncMock(side_effect=error), disconnect=AsyncMock())
    client.create_session = AsyncMock(return_value=session)
    _install(client)
    model = CopilotModel(model_id="test-model")
    tool = ToolDefinition(
        name="lookup", parameters_json_schema={"type": "object", "properties": {}}
    )

    with pytest.raises(TransientProviderError) as raised:
        await model._handle_new_turn(
            [ModelRequest(parts=[UserPromptPart(content="hello")])],
            ModelRequestParameters(function_tools=[tool]),
        )

    assert raised.value.__cause__ is error
    client.force_stop.assert_awaited_once()
    session.disconnect.assert_awaited_once()
    assert CopilotModel._client is None
    assert model._active_session is None


@pytest.mark.asyncio
async def test_transient_error_on_replaced_client_keeps_replacement():
    """A late failure from a session on a dead client does not stop its replacement."""
    dead, replacement = _FakeClient(), _FakeClient()
    _install(replacement)
    model = _model_on(
        dead,
        MagicMock(
            send_and_wait=AsyncMock(side_effect=ProcessExitedError("exited")),
            disconnect=AsyncMock(),
        ),
    )

    with pytest.raises(TransientProviderError):
        await model._simple_request("hello")

    dead.force_stop.assert_not_awaited()
    replacement.force_stop.assert_not_awaited()
    assert CopilotModel._client is replacement


@pytest.mark.asyncio
async def test_jsonrpc_error_response_keeps_client():
    """An error response from a live CLI is not transport loss."""
    client = _FakeClient()
    _install(client)
    error = JsonRpcError(-32602, "Invalid params")
    model = _model_on(
        client, MagicMock(send_and_wait=AsyncMock(side_effect=error), disconnect=AsyncMock())
    )

    with pytest.raises(JsonRpcError):
        await model._simple_request("hello")

    client.force_stop.assert_not_awaited()
    assert CopilotModel._client is client


@pytest.mark.asyncio
async def test_non_transient_error_keeps_client():
    client = _FakeClient()
    _install(client)
    model = _model_on(
        client,
        MagicMock(
            send_and_wait=AsyncMock(side_effect=Exception("tool schema rejected")),
            disconnect=AsyncMock(),
        ),
    )

    with pytest.raises(Exception, match="tool schema rejected"):
        await model._simple_request("hello")

    client.force_stop.assert_not_awaited()
    assert CopilotModel._client is client
