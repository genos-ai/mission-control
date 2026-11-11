"""Tests for TemporalWorkflowGateway (Plan 88 step 88.0.3).

The Temporal client is the external boundary and is mocked; the gateway's
state mapping and cancel/terminate guards are exercised for real.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from modules.backend.core.exceptions import ExternalServiceError
from modules.backend.temporal.workflow_gateway import TemporalWorkflowGateway, WorkflowState

WORKFLOW_ID = "mission-run-0b8f7a52-2c1e-4b55-9d4a-3f0f5d7b9e11"


def _gateway(
    status: WorkflowExecutionStatus | None = None, error: RPCError | None = None
) -> tuple[TemporalWorkflowGateway, MagicMock]:
    handle = MagicMock()
    if error is not None:
        handle.describe = AsyncMock(side_effect=error)
    else:
        handle.describe = AsyncMock(return_value=SimpleNamespace(status=status))
    handle.cancel = AsyncMock()
    handle.terminate = AsyncMock()
    client = MagicMock()
    client.get_workflow_handle = MagicMock(return_value=handle)
    return TemporalWorkflowGateway(client), handle


def _rpc_error(status: RPCStatusCode) -> RPCError:
    return RPCError("rpc failed", status, b"")


async def test_state_running():
    gateway, _ = _gateway(status=WorkflowExecutionStatus.RUNNING)
    assert await gateway.state(WORKFLOW_ID) == WorkflowState.RUNNING


@pytest.mark.parametrize(
    "status",
    [
        WorkflowExecutionStatus.COMPLETED,
        WorkflowExecutionStatus.FAILED,
        WorkflowExecutionStatus.CANCELED,
        WorkflowExecutionStatus.TERMINATED,
        WorkflowExecutionStatus.TIMED_OUT,
    ],
)
async def test_state_closed_for_completed_failed_cancelled_terminated_timed_out(status):
    gateway, _ = _gateway(status=status)
    assert await gateway.state(WORKFLOW_ID) == WorkflowState.CLOSED


async def test_state_not_found_on_rpc_not_found():
    gateway, _ = _gateway(error=_rpc_error(RPCStatusCode.NOT_FOUND))
    assert await gateway.state(WORKFLOW_ID) == WorkflowState.NOT_FOUND


async def test_state_raises_external_service_error_on_unavailable():
    gateway, _ = _gateway(error=_rpc_error(RPCStatusCode.UNAVAILABLE))
    with pytest.raises(ExternalServiceError):
        await gateway.state(WORKFLOW_ID)


async def test_cancel_noop_when_closed():
    gateway, handle = _gateway(status=WorkflowExecutionStatus.COMPLETED)
    assert await gateway.cancel(WORKFLOW_ID) == WorkflowState.CLOSED
    handle.cancel.assert_not_awaited()


async def test_cancel_running_returns_pre_cancel_state():
    gateway, handle = _gateway(status=WorkflowExecutionStatus.RUNNING)
    assert await gateway.cancel(WORKFLOW_ID) == WorkflowState.RUNNING
    handle.cancel.assert_awaited_once()


async def test_terminate_passes_reason():
    gateway, handle = _gateway(status=WorkflowExecutionStatus.RUNNING)
    assert await gateway.terminate(WORKFLOW_ID, reason="mission deleted") == WorkflowState.RUNNING
    handle.terminate.assert_awaited_once_with(reason="mission deleted")


async def test_connect_wraps_runtime_error():
    with patch(
        "modules.backend.temporal.workflow_gateway.get_temporal_client",
        AsyncMock(side_effect=RuntimeError("Temporal is not enabled")),
    ):
        with pytest.raises(ExternalServiceError):
            await TemporalWorkflowGateway.connect()


async def test_fetch_history_reports_running():
    gateway, handle = _gateway(status=WorkflowExecutionStatus.RUNNING)
    history = object()
    handle.fetch_history = AsyncMock(return_value=history)

    assert await gateway.fetch_history(WORKFLOW_ID, run_id="run-1") == (history, True)
    gateway._client.get_workflow_handle.assert_called_once_with(WORKFLOW_ID, run_id="run-1")


async def test_fetch_history_reports_closed():
    gateway, handle = _gateway(status=WorkflowExecutionStatus.COMPLETED)
    handle.fetch_history = AsyncMock(return_value=object())

    _, running = await gateway.fetch_history(WORKFLOW_ID, run_id=None)
    assert running is False


async def test_fetch_history_wraps_rpc_error():
    gateway, _ = _gateway(error=_rpc_error(RPCStatusCode.NOT_FOUND))
    with pytest.raises(ExternalServiceError):
        await gateway.fetch_history(WORKFLOW_ID, run_id=None)
