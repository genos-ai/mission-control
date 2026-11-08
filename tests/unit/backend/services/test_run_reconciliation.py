"""Plan 88 step 88.0.10: RunReconciliationService (real db_session, fake gateway).

The service clock is frozen in 2001 and every test row is backdated against
it, so the shared database's own in-flight rows (all newer than the cutoff)
are never candidates and the counters cover only the rows a test creates.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ExternalServiceError
from modules.backend.models.execution_record import ExecutionRecord, ExecutionRecordStatus
from modules.backend.models.mission import Mission
from modules.backend.models.task import Task, TaskStatus
from modules.backend.models.workflow_run import WorkflowRun, WorkflowRunState
from modules.backend.repositories.task import TaskRepository
from modules.backend.repositories.workflow_run import WorkflowRunRepository
from modules.backend.services.mission_plan import MissionPlanService
from modules.backend.services.run_reconciliation import RunReconciliationService
from modules.backend.temporal.workflow_gateway import WorkflowState

NOW = datetime(2001, 1, 1, tzinfo=UTC)
GRACE = 600
OLD = NOW - timedelta(seconds=700)


class FakeGateway:
    """Records state() calls; unknown workflow ids resolve CLOSED."""

    def __init__(
        self,
        states: dict[str, WorkflowState] | None = None,
        *,
        error: Exception | None = None,
        on_state: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self.states = states or {}
        self.calls: list[str] = []
        self._error = error
        self._on_state = on_state

    async def state(self, workflow_id: str) -> WorkflowState:
        self.calls.append(workflow_id)
        if self._error is not None:
            raise self._error
        if self._on_state is not None:
            await self._on_state(workflow_id)
        return self.states.get(workflow_id, WorkflowState.CLOSED)


@pytest.fixture(autouse=True)
def frozen_clock():
    with patch("modules.backend.services.run_reconciliation.utc_now", return_value=NOW):
        yield


async def _reconcile(db: AsyncSession, gateway: FakeGateway):
    service = RunReconciliationService(db, gateway, None)  # type: ignore[arg-type]
    return await service.reconcile(GRACE)


async def _mission_plan(db: AsyncSession, owner_id: str) -> tuple[str, str]:
    mission = Mission(
        id=str(uuid.uuid4()),
        name=f"test-{uuid.uuid4().hex[:8]}",
        description="Test mission for run reconciliation",
        owner_id=owner_id,
    )
    db.add(mission)
    await db.flush()
    plan = await MissionPlanService(db).get_or_create_plan(mission.id)
    return mission.id, plan.id


async def _task(
    db: AsyncSession,
    mission_id: str,
    plan_id: str,
    status: TaskStatus = TaskStatus.RUNNING,
    updated_at: datetime = OLD,
) -> Task:
    task = await TaskRepository(db).create_task(
        plan_id=plan_id,
        mission_id=mission_id,
        agent="system.summarization.agent",
        description="In-flight task",
        instructions="Do the thing",
        status=status,
    )
    task.updated_at = updated_at
    await db.flush()
    return task


async def _record(
    db: AsyncSession,
    mission_id: str,
    *,
    temporal_workflow_id: str | None,
    workflow_run_id: str | None = None,
    status: ExecutionRecordStatus = ExecutionRecordStatus.RUNNING,
    updated_at: datetime = OLD,
) -> ExecutionRecord:
    rec = ExecutionRecord(
        status=status,
        mission_id=mission_id,
        temporal_workflow_id=temporal_workflow_id,
        workflow_run_id=workflow_run_id,
        updated_at=updated_at,
    )
    db.add(rec)
    await db.flush()
    return rec


async def _run(
    db: AsyncSession,
    mission_id: str,
    *,
    record_workflow_id: str | None,
    status: WorkflowRunState = WorkflowRunState.RUNNING,
    updated_at: datetime = NOW,
) -> WorkflowRun:
    """A workflow run whose parent execution record carries ``record_workflow_id``.

    The record is COMPLETED and recent, so it is never itself a candidate.
    """
    rec = await _record(
        db,
        mission_id,
        temporal_workflow_id=record_workflow_id,
        status=ExecutionRecordStatus.COMPLETED,
        updated_at=NOW,
    )
    run = WorkflowRun(
        workflow_name="test.workflow",
        workflow_version=1,
        status=status,
        triggered_by="user:test",
        mission_id=mission_id,
        execution_record_id=rec.id,
        updated_at=updated_at,
    )
    db.add(run)
    await db.flush()
    return run


async def _status(db: AsyncSession, row) -> str:
    await db.refresh(row)
    return row.status


# ── Tasks ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_running_workflow_leaves_tasks_untouched(db_session: AsyncSession, test_user):
    mission_id, plan_id = await _mission_plan(db_session, test_user.id)
    task = await _task(db_session, mission_id, plan_id)
    gateway = FakeGateway({f"mission-run-{plan_id}": WorkflowState.RUNNING})

    stats = await _reconcile(db_session, gateway)

    assert await _status(db_session, task) == TaskStatus.RUNNING
    assert stats.left_running == 1
    assert stats.failed_tasks == 0


@pytest.mark.asyncio
async def test_closed_workflow_fails_running_and_queued_tasks(db_session: AsyncSession, test_user):
    mission_id, plan_id = await _mission_plan(db_session, test_user.id)
    running = await _task(db_session, mission_id, plan_id, TaskStatus.RUNNING)
    queued = await _task(db_session, mission_id, plan_id, TaskStatus.QUEUED)
    gateway = FakeGateway({f"mission-run-{plan_id}": WorkflowState.CLOSED})

    stats = await _reconcile(db_session, gateway)

    for task in (running, queued):
        assert await _status(db_session, task) == TaskStatus.FAILED
        assert task.failure_reason.startswith("orphaned: workflow mission-run-")
        assert task.last_attempt_at == NOW
    assert stats.failed_tasks == 2


@pytest.mark.asyncio
async def test_not_found_workflow_fails_tasks(db_session: AsyncSession, test_user):
    mission_id, plan_id = await _mission_plan(db_session, test_user.id)
    task = await _task(db_session, mission_id, plan_id)
    gateway = FakeGateway({f"mission-run-{plan_id}": WorkflowState.NOT_FOUND})

    stats = await _reconcile(db_session, gateway)

    assert await _status(db_session, task) == TaskStatus.FAILED
    assert task.failure_reason.endswith("not_found")
    assert stats.failed_tasks == 1


@pytest.mark.asyncio
async def test_rows_inside_grace_untouched(db_session: AsyncSession, test_user):
    mission_id, plan_id = await _mission_plan(db_session, test_user.id)
    recent = NOW - timedelta(seconds=60)
    task = await _task(db_session, mission_id, plan_id, updated_at=recent)
    rec = await _record(
        db_session, mission_id, temporal_workflow_id="execution-recent", updated_at=recent
    )
    gateway = FakeGateway()

    stats = await _reconcile(db_session, gateway)

    assert await _status(db_session, task) == TaskStatus.RUNNING
    assert await _status(db_session, rec) == ExecutionRecordStatus.RUNNING
    assert stats.examined_tasks == 0
    assert stats.examined_execution_records == 0
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_task_owned_by_live_workflow_run_untouched(db_session: AsyncSession, test_user):
    mission_id, plan_id = await _mission_plan(db_session, test_user.id)
    task = await _task(db_session, mission_id, plan_id)
    await _run(db_session, mission_id, record_workflow_id="run-workflow-x")
    gateway = FakeGateway(
        {
            f"mission-run-{plan_id}": WorkflowState.CLOSED,
            "run-workflow-x": WorkflowState.RUNNING,
        }
    )

    stats = await _reconcile(db_session, gateway)

    assert await _status(db_session, task) == TaskStatus.RUNNING
    assert stats.left_running == 1


@pytest.mark.asyncio
async def test_task_owned_by_awaiting_input_workflow_run_untouched(
    db_session: AsyncSession, test_user
):
    mission_id, plan_id = await _mission_plan(db_session, test_user.id)
    task = await _task(db_session, mission_id, plan_id)
    await _run(
        db_session,
        mission_id,
        record_workflow_id="run-workflow-awaiting",
        status=WorkflowRunState.AWAITING_INPUT,
    )
    gateway = FakeGateway({f"mission-run-{plan_id}": WorkflowState.CLOSED})

    await _reconcile(db_session, gateway)

    assert await _status(db_session, task) == TaskStatus.RUNNING
    assert "run-workflow-awaiting" not in gateway.calls


@pytest.mark.asyncio
async def test_task_owned_by_in_process_workflow_run_untouched(db_session: AsyncSession, test_user):
    mission_id, plan_id = await _mission_plan(db_session, test_user.id)
    task = await _task(db_session, mission_id, plan_id)
    await _run(db_session, mission_id, record_workflow_id=None)
    gateway = FakeGateway({f"mission-run-{plan_id}": WorkflowState.CLOSED})

    stats = await _reconcile(db_session, gateway)

    assert await _status(db_session, task) == TaskStatus.RUNNING
    assert stats.left_in_process == 1


# ── Execution records ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_in_process_record_without_ids_untouched(db_session: AsyncSession, test_user):
    mission_id, _ = await _mission_plan(db_session, test_user.id)
    rec = await _record(
        db_session,
        mission_id,
        temporal_workflow_id=None,
        updated_at=NOW - timedelta(seconds=3600),
    )
    gateway = FakeGateway()

    stats = await _reconcile(db_session, gateway)

    assert await _status(db_session, rec) == ExecutionRecordStatus.RUNNING
    assert stats.examined_execution_records == 0
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_execution_record_with_running_workflow_untouched(
    db_session: AsyncSession, test_user
):
    mission_id, _ = await _mission_plan(db_session, test_user.id)
    rec = await _record(db_session, mission_id, temporal_workflow_id="execution-a")
    gateway = FakeGateway({"execution-a": WorkflowState.RUNNING})

    stats = await _reconcile(db_session, gateway)

    assert await _status(db_session, rec) == ExecutionRecordStatus.RUNNING
    assert stats.failed_execution_records == 0


@pytest.mark.asyncio
async def test_execution_record_with_closed_workflow_failed(db_session: AsyncSession, test_user):
    mission_id, _ = await _mission_plan(db_session, test_user.id)
    rec = await _record(db_session, mission_id, temporal_workflow_id="execution-a")
    gateway = FakeGateway({"execution-a": WorkflowState.CLOSED})

    stats = await _reconcile(db_session, gateway)

    assert await _status(db_session, rec) == ExecutionRecordStatus.FAILED
    assert rec.completed_at == NOW
    assert stats.failed_execution_records == 1


@pytest.mark.asyncio
async def test_step_record_follows_its_workflow_run(db_session: AsyncSession, test_user):
    mission_id, _ = await _mission_plan(db_session, test_user.id)
    run = await _run(db_session, mission_id, record_workflow_id="run-workflow-x")
    step = await _record(db_session, mission_id, temporal_workflow_id=None, workflow_run_id=run.id)
    gateway = FakeGateway({"run-workflow-x": WorkflowState.CLOSED})

    await _reconcile(db_session, gateway)

    assert await _status(db_session, step) == ExecutionRecordStatus.FAILED
    assert gateway.calls.count("run-workflow-x") == 1


# ── Workflow runs ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_workflow_run_with_in_process_record_never_selected(
    db_session: AsyncSession, test_user
):
    mission_id, _ = await _mission_plan(db_session, test_user.id)
    old = NOW - timedelta(seconds=3600)
    run = await _run(db_session, mission_id, record_workflow_id=None, updated_at=old)

    selected = await WorkflowRunRepository(db_session).list_in_flight_older_than(
        NOW - timedelta(seconds=GRACE)
    )
    stats = await _reconcile(db_session, FakeGateway())

    assert run.id not in {r.id for r in selected}
    assert await _status(db_session, run) == WorkflowRunState.RUNNING
    assert stats.examined_workflow_runs == 0


@pytest.mark.asyncio
async def test_workflow_run_awaiting_input_never_selected(db_session: AsyncSession, test_user):
    mission_id, _ = await _mission_plan(db_session, test_user.id)
    run = await _run(
        db_session,
        mission_id,
        record_workflow_id="run-workflow-awaiting",
        status=WorkflowRunState.AWAITING_INPUT,
        updated_at=NOW - timedelta(seconds=3600),
    )

    stats = await _reconcile(db_session, FakeGateway())

    assert await _status(db_session, run) == WorkflowRunState.AWAITING_INPUT
    assert stats.examined_workflow_runs == 0


# ── Failure modes and mechanics ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_temporal_unavailable_raises_and_writes_nothing(db_session: AsyncSession, test_user):
    mission_id, plan_id = await _mission_plan(db_session, test_user.id)
    task = await _task(db_session, mission_id, plan_id)
    rec = await _record(db_session, mission_id, temporal_workflow_id="execution-a")
    run = await _run(db_session, mission_id, record_workflow_id="run-workflow-x", updated_at=OLD)
    gateway = FakeGateway(error=ExternalServiceError("Temporal unavailable"))

    with pytest.raises(ExternalServiceError):
        await _reconcile(db_session, gateway)

    assert await _status(db_session, task) == TaskStatus.RUNNING
    assert await _status(db_session, rec) == ExecutionRecordStatus.RUNNING
    assert await _status(db_session, run) == WorkflowRunState.RUNNING


@pytest.mark.asyncio
async def test_state_cached_per_workflow_id(db_session: AsyncSession, test_user):
    mission_id, plan_id = await _mission_plan(db_session, test_user.id)
    for _ in range(3):
        await _task(db_session, mission_id, plan_id)
    gateway = FakeGateway({f"mission-run-{plan_id}": WorkflowState.RUNNING})

    await _reconcile(db_session, gateway)

    assert gateway.calls == [f"mission-run-{plan_id}"]


@pytest.mark.asyncio
async def test_reconcile_returns_no_schedule_sync(db_session: AsyncSession, test_user):
    stats = await _reconcile(db_session, FakeGateway())

    assert stats.schedule_sync is None


@pytest.mark.asyncio
async def test_row_progressed_between_resolve_and_write_skipped(
    db_session: AsyncSession, test_user
):
    mission_id, plan_id = await _mission_plan(db_session, test_user.id)
    task = await _task(db_session, mission_id, plan_id)

    async def complete_task(_: str) -> None:
        task.status = TaskStatus.COMPLETED
        await db_session.flush()

    gateway = FakeGateway({f"mission-run-{plan_id}": WorkflowState.CLOSED}, on_state=complete_task)

    stats = await _reconcile(db_session, gateway)

    assert await _status(db_session, task) == TaskStatus.COMPLETED
    assert stats.failed_tasks == 0
