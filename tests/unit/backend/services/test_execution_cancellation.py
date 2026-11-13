"""Tests for ExecutionCancellationService (Plan 88, step 88.0.9).

Real db_session with rollback; only the Temporal gateway is faked.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ExternalServiceError, NotFoundError
from modules.backend.models.execution_record import ExecutionRecord, ExecutionRecordStatus
from modules.backend.models.mission import Mission, MissionStatus
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.models.workflow_run import WorkflowRun, WorkflowRunState
from modules.backend.services.execution_cancellation import ExecutionCancellationService
from modules.backend.temporal.workflow_gateway import WorkflowState

_CONNECT = "modules.backend.temporal.workflow_gateway.TemporalWorkflowGateway.connect"


def _gateway(state: WorkflowState = WorkflowState.RUNNING) -> MagicMock:
    gateway = MagicMock()
    gateway.cancel = AsyncMock(return_value=state)
    return gateway


async def _mission(db_session: AsyncSession, owner_id: str) -> Mission:
    mission = Mission(
        id=str(uuid4()),
        name=f"p88-cancel-{uuid4().hex[:8]}",
        description="Plan 88 cancellation test",
        owner_id=owner_id,
        status=MissionStatus.ACTIVE,
    )
    db_session.add(mission)
    await db_session.flush()
    db_session.add(
        MissionPlan(
            mission_id=mission.id,
            gate_mode=GateMode.MANUAL,
            budget_per_run_usd=5.0,
            budget_per_month_usd=100.0,
        )
    )
    await db_session.flush()
    return mission


async def _record(
    db_session: AsyncSession,
    mission_id: str,
    *,
    status: ExecutionRecordStatus = ExecutionRecordStatus.RUNNING,
    workflow_id: str | None = None,
) -> ExecutionRecord:
    record = ExecutionRecord(mission_id=mission_id, status=status, temporal_workflow_id=workflow_id)
    db_session.add(record)
    await db_session.flush()
    return record


async def _run(db_session: AsyncSession, mission_id: str, record_id: str) -> WorkflowRun:
    run = WorkflowRun(
        workflow_name="p88-test",
        workflow_version=1,
        mission_id=mission_id,
        status=WorkflowRunState.RUNNING,
        triggered_by="test",
        execution_record_id=record_id,
    )
    db_session.add(run)
    await db_session.flush()
    return run


@pytest.fixture
async def mission(db_session: AsyncSession, test_user) -> Mission:
    return await _mission(db_session, test_user.id)


async def test_cancel_execution_cancels_workflow_then_marks_cancelled(db_session, mission):
    workflow_id = f"execution-{uuid4()}"
    record = await _record(db_session, mission.id, workflow_id=workflow_id)
    gateway = _gateway()

    with patch(_CONNECT, AsyncMock(return_value=gateway)):
        row, changed, temporal_cancelled = await ExecutionCancellationService(
            db_session
        ).cancel_execution(record.id, user_id="u", reason="test")

    gateway.cancel.assert_awaited_once_with(workflow_id)
    assert changed is True
    assert temporal_cancelled is True
    assert row.status == ExecutionRecordStatus.CANCELLED


async def test_cancel_execution_not_found_workflow_still_marks_cancelled(db_session, mission):
    record = await _record(db_session, mission.id, workflow_id=f"execution-{uuid4()}")

    with patch(_CONNECT, AsyncMock(return_value=_gateway(WorkflowState.NOT_FOUND))):
        row, changed, _ = await ExecutionCancellationService(db_session).cancel_execution(
            record.id, user_id="u", reason="test"
        )

    assert changed is True
    assert row.status == ExecutionRecordStatus.CANCELLED


async def test_cancel_execution_temporal_unavailable_leaves_record_running(db_session, mission):
    record = await _record(db_session, mission.id, workflow_id=f"execution-{uuid4()}")
    record_id = record.id

    with patch(_CONNECT, AsyncMock(side_effect=ExternalServiceError("Temporal unavailable"))):
        with pytest.raises(ExternalServiceError):
            await ExecutionCancellationService(db_session).cancel_execution(
                record_id, user_id="u", reason="test"
            )

    await db_session.refresh(record)
    assert record.status == ExecutionRecordStatus.RUNNING


async def test_cancel_terminal_execution_noop_without_gateway_call(db_session, mission):
    record = await _record(
        db_session,
        mission.id,
        status=ExecutionRecordStatus.COMPLETED,
        workflow_id=f"execution-{uuid4()}",
    )
    connect = AsyncMock(return_value=_gateway())

    with patch(_CONNECT, connect):
        row, changed, temporal_cancelled = await ExecutionCancellationService(
            db_session
        ).cancel_execution(record.id, user_id="u", reason="test")

    connect.assert_not_awaited()
    assert (changed, temporal_cancelled) == (False, False)
    assert row.status == ExecutionRecordStatus.COMPLETED


async def test_cancel_workflow_run_cancels_linked_workflow(db_session, mission):
    workflow_id = f"run-workflow-{uuid4()}"
    record = await _record(db_session, mission.id, workflow_id=workflow_id)
    run = await _run(db_session, mission.id, record.id)
    gateway = _gateway()

    with patch(_CONNECT, AsyncMock(return_value=gateway)):
        row, changed, temporal_cancelled = await ExecutionCancellationService(
            db_session
        ).cancel_workflow_run(mission.id, run.id, user_id="u")

    gateway.cancel.assert_awaited_once_with(workflow_id)
    assert (changed, temporal_cancelled) == (True, True)
    assert row.status == WorkflowRunState.CANCELLED


async def test_cancel_workflow_run_other_mission_raises_not_found(db_session, mission, test_user):
    other = await _mission(db_session, test_user.id)
    record = await _record(db_session, mission.id, workflow_id=f"run-workflow-{uuid4()}")
    run = await _run(db_session, mission.id, record.id)
    connect = AsyncMock(return_value=_gateway())

    with patch(_CONNECT, connect):
        with pytest.raises(NotFoundError):
            await ExecutionCancellationService(db_session).cancel_workflow_run(
                other.id, run.id, user_id="u"
            )

    connect.assert_not_awaited()


async def test_cancel_execution_without_workflow_id_is_db_only(db_session, mission):
    record = await _record(db_session, mission.id, workflow_id=None)
    connect = AsyncMock(return_value=_gateway())

    with patch(_CONNECT, connect):
        row, changed, temporal_cancelled = await ExecutionCancellationService(
            db_session
        ).cancel_execution(record.id, user_id="u", reason="test")

    connect.assert_not_awaited()
    assert changed is True
    assert temporal_cancelled is False
    assert row.status == ExecutionRecordStatus.CANCELLED
