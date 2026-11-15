"""MissionRunService.cancel_run and begin's cancel check (Plan 88 step 88.4.5).

Real db_session; TemporalWorkflowGateway is an AsyncMock.
"""

from unittest.mock import AsyncMock

import pytest

from modules.backend.core.exceptions import (
    ExternalServiceError,
    NotFoundError,
    RunStartRejectedError,
)
from modules.backend.core.utils import utc_now
from modules.backend.models.mission_run import (
    MissionRun,
    MissionRunStatus,
    MissionRunStatusReason,
)
from modules.backend.services.mission_run import MissionRunService
from modules.backend.temporal.workflow_gateway import TemporalWorkflowGateway, WorkflowState
from modules.backend.temporal.workflow_ids import mission_run_workflow_id
from tests.unit.backend.services import budget_fixtures as bf

USER_CANCEL = MissionRunStatusReason.CANCELLED_BY_USER


class _Bus:
    async def publish(self, event) -> None:
        return None

    async def publish_to_mission(self, mission_id: str, event) -> None:
        return None


@pytest.fixture
def gateway(monkeypatch) -> AsyncMock:
    fake = AsyncMock()
    fake.cancel.return_value = WorkflowState.RUNNING
    monkeypatch.setattr(TemporalWorkflowGateway, "connect", AsyncMock(return_value=fake))
    return fake


def _svc(db) -> MissionRunService:
    return MissionRunService(db, _Bus())


async def _row(db, run_id: str) -> MissionRun:
    return await db.get(MissionRun, run_id, populate_existing=True)


async def test_cancel_terminal_is_noop(db_session, test_user, gateway):
    mission_id, plan_id = await bf.mission_with_plan(db_session, test_user.id)
    run_id = await bf.run(db_session, mission_id, plan_id, status=MissionRunStatus.SUCCEEDED)

    run = await _svc(db_session).cancel_run(mission_id, run_id, test_user.id, USER_CANCEL)

    assert run.status == MissionRunStatus.SUCCEEDED
    assert run.cancel_requested_at is None
    gateway.cancel.assert_not_awaited()


async def test_cancel_other_missions_run_404(db_session, test_user, gateway):
    mission_id, plan_id = await bf.mission_with_plan(db_session, test_user.id)
    other_id, _ = await bf.mission_with_plan(db_session, test_user.id)
    run_id = await bf.run(db_session, mission_id, plan_id)

    with pytest.raises(NotFoundError):
        await _svc(db_session).cancel_run(other_id, run_id, test_user.id, USER_CANCEL)

    gateway.cancel.assert_not_awaited()


async def test_cancel_pending_not_found_transitions_cancelled(db_session, test_user, gateway):
    gateway.cancel.return_value = WorkflowState.NOT_FOUND
    mission_id, plan_id = await bf.mission_with_plan(db_session, test_user.id)
    run_id = await bf.run(db_session, mission_id, plan_id, status=MissionRunStatus.PENDING)

    run = await _svc(db_session).cancel_run(mission_id, run_id, test_user.id, USER_CANCEL)

    assert run.status == MissionRunStatus.CANCELLED
    assert run.status_reason == USER_CANCEL
    assert run.status_detail == "cancelled before start"


async def test_cancel_pending_unstarted_run_goes_through_workflow(db_session, test_user, gateway):
    mission_id, plan_id = await bf.mission_with_plan(db_session, test_user.id)
    run_id = await bf.run(db_session, mission_id, plan_id, status=MissionRunStatus.PENDING)

    run = await _svc(db_session).cancel_run(mission_id, run_id, test_user.id, USER_CANCEL)

    assert run.status == MissionRunStatus.PENDING
    assert run.started_at is None
    assert run.cancel_requested_at is not None
    assert run.cancel_requested_by_user_id == test_user.id
    assert run.cancel_reason == USER_CANCEL
    gateway.cancel.assert_awaited_once_with(mission_run_workflow_id(run_id))


async def test_cancel_running_calls_handle_cancel(db_session, test_user, gateway):
    mission_id, plan_id = await bf.mission_with_plan(db_session, test_user.id)
    run_id = await bf.run(db_session, mission_id, plan_id)

    run = await _svc(db_session).cancel_run(mission_id, run_id, test_user.id, USER_CANCEL)

    gateway.cancel.assert_awaited_once_with(mission_run_workflow_id(run_id))
    assert run.status == MissionRunStatus.RUNNING
    assert run.cancel_reason == USER_CANCEL


async def test_cancel_keeps_first_request(db_session, test_user, gateway):
    mission_id, plan_id = await bf.mission_with_plan(db_session, test_user.id)
    run_id = await bf.run(db_session, mission_id, plan_id)
    svc = _svc(db_session)
    await svc.cancel_run(mission_id, run_id, test_user.id, MissionRunStatusReason.MISSION_ARCHIVED)

    run = await svc.cancel_run(mission_id, run_id, test_user.id, USER_CANCEL)

    assert run.cancel_reason == MissionRunStatusReason.MISSION_ARCHIVED


async def test_temporal_unreachable_keeps_request_and_raises(db_session, test_user, gateway):
    gateway.cancel.side_effect = ExternalServiceError("Temporal unavailable")
    mission_id, plan_id = await bf.mission_with_plan(db_session, test_user.id)
    run_id = await bf.run(db_session, mission_id, plan_id)

    with pytest.raises(ExternalServiceError):
        await _svc(db_session).cancel_run(mission_id, run_id, test_user.id, USER_CANCEL)

    run = await _row(db_session, run_id)
    assert run.status == MissionRunStatus.RUNNING
    assert run.cancel_requested_at is not None
    assert run.cancel_reason == USER_CANCEL


async def test_begin_honours_cancel_requested(db_session, test_user, gateway):
    mission_id, plan_id = await bf.mission_with_plan(db_session, test_user.id)
    run_id = await bf.run(db_session, mission_id, plan_id, status=MissionRunStatus.PENDING)
    run = await _row(db_session, run_id)
    run.cancel_requested_at = utc_now()
    run.cancel_requested_by_user_id = test_user.id
    run.cancel_reason = USER_CANCEL
    await db_session.flush()

    with pytest.raises(RunStartRejectedError, match="cancelled before start"):
        await _svc(db_session).begin(run_id)

    run = await _row(db_session, run_id)
    assert run.status == MissionRunStatus.CANCELLED
    assert run.status_reason == USER_CANCEL
