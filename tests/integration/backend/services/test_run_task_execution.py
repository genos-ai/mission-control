"""RunTaskExecutionService (Plan 88 step 88.2.4, contracts 3.1.9 and 3.8.6).

Real database with committed rows; TemporalWorkflowGateway is an AsyncMock.
Each service call runs in its own session, as the execute_plan_task activity does.
"""

import hashlib
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modules.backend.core.exceptions import (
    ExecutionEnvironmentError,
    MissionRunStateError,
    NotFoundError,
)
from modules.backend.core.failure_classification import (
    WorkflowStepFailedError,
    get_failure_classifier,
)
from modules.backend.models.execution_record import TaskExecution
from modules.backend.models.llm_call import LlmCall
from modules.backend.models.mission import Mission
from modules.backend.models.mission_context import ContextChange
from modules.backend.models.mission_plan import MissionPlan
from modules.backend.models.mission_run import (
    MissionRunStatus,
    MissionRunStatusReason,
    MissionRunTrigger,
)
from modules.backend.models.task import Task, TaskStatus
from modules.backend.models.user import User
from modules.backend.repositories.task import TaskRepository
from modules.backend.schemas.execution_outcome import TaskResult
from modules.backend.schemas.execution_outcome import TaskStatus as OutcomeStatus
from modules.backend.schemas.task_failure import (
    FailureClass,
    FailureEvidence,
    FailureOrigin,
    TaskFailure,
)
from modules.backend.services.mission_context import MissionContextManager
from modules.backend.services.mission_run import MissionRunService
from modules.backend.services.run_task_execution import RunTaskExecutionService
from modules.backend.services.workflow_run import WorkflowRunService
from modules.backend.temporal.workflow_gateway import TemporalWorkflowGateway
from tests.integration.backend.services.test_mission_schedule_service import RecordingBus

Factory = async_sessionmaker[AsyncSession]
AGENT = "system.summarization.agent"


@pytest.fixture
def gateway(monkeypatch) -> AsyncMock:
    fake = AsyncMock()
    monkeypatch.setattr(TemporalWorkflowGateway, "connect", AsyncMock(return_value=fake))
    return fake


@pytest.fixture
def app_sessions(monkeypatch, db_session_factory):
    """Route get_async_session (used by WorkflowRunService helpers) to the test database."""

    @asynccontextmanager
    async def _session():
        async with db_session_factory() as session:
            yield session

    monkeypatch.setattr("modules.backend.core.database.get_async_session", _session)


class _Run:
    """A RUNNING mission run with its mission, plan and ExecutionRecord."""

    def __init__(self, user: User, mission: Mission, plan: MissionPlan, run_id: str, record: str):
        self.user, self.mission, self.plan = user, mission, plan
        self.id, self.execution_record_id = run_id, record


async def _begun_run(factory: Factory, committed_owner) -> _Run:
    user, mission, plan = await committed_owner()
    async with factory() as session:
        run = await MissionRunService(session, RecordingBus()).start_run(
            mission.id,
            trigger=MissionRunTrigger.MANUAL,
            objective=None,
            user_id=user.id,
            session_id=None,
        )
    async with factory() as session:
        begun = await MissionRunService(session, RecordingBus()).begin(run.id)
    return _Run(user, mission, plan, run.id, begun.execution_record_id)


async def _task(factory: Factory, run: _Run, status: TaskStatus, *, in_run: bool = True) -> str:
    async with factory() as session:
        task = await TaskRepository(session).create_task(
            plan_id=run.plan.id,
            mission_id=run.mission.id,
            agent=AGENT,
            description=f"{status.value} task",
            instructions="Do it",
            status=status,
            mission_run_id=run.id if in_run else None,
        )
        await session.commit()
        return task.id


async def _get(factory: Factory, task_id: str) -> Task:
    async with factory() as session:
        return await session.get(Task, task_id)


async def _claim(factory: Factory, run_id: str, task_id: str):
    async with factory() as session:
        return await RunTaskExecutionService(session).claim(run_id, task_id)


async def _record(factory: Factory, run: _Run, task_id: str, key: str, result: TaskResult):
    async with factory() as session:
        return await RunTaskExecutionService(session).record(
            mission_run_id=run.id,
            task_id=task_id,
            idempotency_key=key,
            execution_record_id=run.execution_record_id,
            task_result_json=result.model_dump(mode="json"),
        )


async def _resolve(factory: Factory, run_id: str, task_id: str, action: str) -> None:
    async with factory() as session:
        await RunTaskExecutionService(session).resolve_failed(run_id, task_id, action)


async def _executions(factory: Factory, key: str) -> list[TaskExecution]:
    async with factory() as session:
        stmt = select(TaskExecution).where(TaskExecution.idempotency_key == key)
        return list((await session.execute(stmt)).scalars().all())


def _success(task_id: str, **kwargs) -> TaskResult:
    return TaskResult(
        task_id=task_id,
        agent_name=AGENT,
        status=OutcomeStatus.SUCCESS,
        cost_usd=0.25,
        duration_seconds=1.5,
        **kwargs,
    )


def _dependency_failure() -> TaskFailure:
    """A PLATFORM / PLATFORM_DEPENDENCY_MISSING record, shaped as from_exception builds it."""
    cls = FailureClass.PLATFORM_DEPENDENCY_MISSING
    return TaskFailure(
        origin=FailureOrigin.PLATFORM,
        failure_class=cls,
        fingerprint=hashlib.sha256(f"platform|{cls.value}|nosuchpkg".encode()).hexdigest(),
        summary=f"{cls.value}: No module named 'nosuchpkg'",
        retryable=False,
        evidence=FailureEvidence(
            exception_type="ModuleNotFoundError",
            message="No module named 'nosuchpkg'",
            traceback_tail=["backend/tools/example.py:run"],
            module_name="nosuchpkg",
        ),
    )


def _failed(task_id: str, failure: TaskFailure | None = None) -> TaskResult:
    return TaskResult(
        task_id=task_id,
        agent_name=AGENT,
        status=OutcomeStatus.FAILED,
        cost_usd=0.1,
        failure=failure or get_failure_classifier().agent_outcome(AGENT, "agent said no"),
    )


async def _claimed_failure(factory: Factory, run: _Run, failure: TaskFailure | None = None):
    task_id = await _task(factory, run, TaskStatus.APPROVED)
    claim = await _claim(factory, run.id, task_id)
    recorded = await _record(
        factory, run, task_id, claim.idempotency_key, _failed(task_id, failure)
    )
    return task_id, claim, recorded


# ── claim ─────────────────────────────────────────────────────────────────


async def test_claim_completed_task_replays(db_session_factory, gateway, committed_owner) -> None:
    run = await _begun_run(db_session_factory, committed_owner)
    task_id = await _task(db_session_factory, run, TaskStatus.APPROVED)
    claim = await _claim(db_session_factory, run.id, task_id)
    await _record(db_session_factory, run, task_id, claim.idempotency_key, _success(task_id))
    async with db_session_factory() as session:
        await session.execute(
            text("DELETE FROM task_executions WHERE idempotency_key = :k"),
            {"k": claim.idempotency_key},
        )
        await session.commit()
        before = await session.scalar(select(func.count()).select_from(LlmCall))

    replay = await _claim(db_session_factory, run.id, task_id)

    assert replay.outcome == "replay"
    assert replay.stored.idempotent_replay is True
    async with db_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(LlmCall)) == before


async def test_claim_existing_key_replays(db_session_factory, gateway, committed_owner) -> None:
    run = await _begun_run(db_session_factory, committed_owner)
    task_id = await _task(db_session_factory, run, TaskStatus.APPROVED)
    claim = await _claim(db_session_factory, run.id, task_id)
    await _record(db_session_factory, run, task_id, claim.idempotency_key, _success(task_id))
    async with db_session_factory() as session:
        await session.execute(
            text("UPDATE tasks SET status = 'RUNNING' WHERE id = :id"), {"id": task_id}
        )
        await session.commit()

    replay = await _claim(db_session_factory, run.id, task_id)

    assert replay.outcome == "replay"
    assert replay.stored.status == "completed"
    assert replay.stored.idempotent_replay is True


async def test_claim_running_reexecutes_same_key(
    db_session_factory, gateway, committed_owner
) -> None:
    run = await _begun_run(db_session_factory, committed_owner)
    task_id = await _task(db_session_factory, run, TaskStatus.RUNNING)

    claim = await _claim(db_session_factory, run.id, task_id)

    assert claim.outcome == "execute"
    assert claim.idempotency_key.endswith(":0")
    assert claim.task_definition.task_id == task_id
    assert (claim.execution_mode, claim.mission_repo_root) == ("local", None)


async def test_claim_approved_moves_to_running(
    db_session_factory, gateway, committed_owner
) -> None:
    run = await _begun_run(db_session_factory, committed_owner)
    task_id = await _task(db_session_factory, run, TaskStatus.APPROVED)

    await _claim(db_session_factory, run.id, task_id)

    task = await _get(db_session_factory, task_id)
    assert task.status == TaskStatus.RUNNING
    assert task.last_attempt_at is not None


async def test_claim_other_runs_task_raises(db_session_factory, gateway, committed_owner) -> None:
    run = await _begun_run(db_session_factory, committed_owner)
    other = await _begun_run(db_session_factory, committed_owner)
    task_id = await _task(db_session_factory, other, TaskStatus.APPROVED)

    with pytest.raises(MissionRunStateError):
        await _claim(db_session_factory, run.id, task_id)


# ── record ────────────────────────────────────────────────────────────────


async def test_record_atomic(db_session_factory, gateway, committed_owner, monkeypatch) -> None:
    run = await _begun_run(db_session_factory, committed_owner)
    task_id = await _task(db_session_factory, run, TaskStatus.APPROVED)
    claim = await _claim(db_session_factory, run.id, task_id)
    monkeypatch.setattr(
        MissionContextManager, "apply_updates", AsyncMock(side_effect=RuntimeError("boom"))
    )
    result = _success(task_id, context_updates=[{"op": "add", "path": "notes.a", "value": 1}])

    with pytest.raises(RuntimeError, match="boom"):
        await _record(db_session_factory, run, task_id, claim.idempotency_key, result)

    assert await _executions(db_session_factory, claim.idempotency_key) == []
    task = await _get(db_session_factory, task_id)
    assert task.status == TaskStatus.RUNNING
    assert task.cost_usd == 0


async def test_record_duplicate_returns_first(db_session_factory, gateway, committed_owner) -> None:
    run = await _begun_run(db_session_factory, committed_owner)
    task_id = await _task(db_session_factory, run, TaskStatus.APPROVED)
    claim = await _claim(db_session_factory, run.id, task_id)

    first = await _record(
        db_session_factory, run, task_id, claim.idempotency_key, _success(task_id)
    )
    second = await _record(
        db_session_factory, run, task_id, claim.idempotency_key, _success(task_id)
    )

    assert len(await _executions(db_session_factory, claim.idempotency_key)) == 1
    assert first.idempotent_replay is False
    assert second.idempotent_replay is True
    assert (second.status, second.cost_usd) == (first.status, first.cost_usd)


async def test_record_writes_result_summary_json(
    db_session_factory, gateway, committed_owner
) -> None:
    run = await _begun_run(db_session_factory, committed_owner)
    task_id = await _task(db_session_factory, run, TaskStatus.APPROVED)
    claim = await _claim(db_session_factory, run.id, task_id)
    output = {"summary": "done", "items": [1, 2]}

    await _record(
        db_session_factory,
        run,
        task_id,
        claim.idempotency_key,
        _success(task_id, output_reference=output),
    )

    task = await _get(db_session_factory, task_id)
    assert task.status == TaskStatus.COMPLETED
    assert json.loads(task.result_summary) == output
    assert (task.cost_usd, task.duration_seconds) == (0.25, 1.5)


async def test_record_context_changes_carry_run_id(
    db_session_factory, gateway, committed_owner
) -> None:
    run = await _begun_run(db_session_factory, committed_owner)
    async with db_session_factory() as session:
        await MissionContextManager(session).create_context(run.mission.id, "m", "d")
        await session.commit()
    task_id = await _task(db_session_factory, run, TaskStatus.APPROVED)
    claim = await _claim(db_session_factory, run.id, task_id)
    update = {"op": "add", "path": "notes.finding", "value": "x", "reason": "test"}

    await _record(
        db_session_factory,
        run,
        task_id,
        claim.idempotency_key,
        _success(task_id, context_updates=[update]),
    )

    async with db_session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(ContextChange).where(ContextChange.path == "notes.finding")
                )
            )
            .scalars()
            .all()
        )
        rows = [r for r in rows if r.task_id == task_id]
    assert len(rows) == 1
    assert rows[0].mission_run_id == run.id


async def test_replay_status_is_lowercase_value(
    db_session_factory, gateway, committed_owner
) -> None:
    run = await _begun_run(db_session_factory, committed_owner)
    task_id = await _task(db_session_factory, run, TaskStatus.COMPLETED)

    replay = await _claim(db_session_factory, run.id, task_id)

    assert replay.outcome == "replay"
    assert replay.stored.status == "completed"


async def test_record_failed_writes_failure_columns(
    db_session_factory, gateway, committed_owner
) -> None:
    run = await _begun_run(db_session_factory, committed_owner)
    failure = _dependency_failure()
    assert (failure.origin, failure.failure_class) == (
        FailureOrigin.PLATFORM,
        FailureClass.PLATFORM_DEPENDENCY_MISSING,
    )

    task_id, claim, recorded = await _claimed_failure(db_session_factory, run, failure)

    assert recorded.status == "failed"
    assert recorded.failure_class == "platform_dependency_missing"
    task = await _get(db_session_factory, task_id)
    assert task.failure_reason == failure.summary
    assert task.failure_origin == FailureOrigin.PLATFORM
    assert task.failure_class == FailureClass.PLATFORM_DEPENDENCY_MISSING
    assert task.failure_fingerprint == failure.fingerprint
    (row,) = await _executions(db_session_factory, claim.idempotency_key)
    assert row.failure_class == FailureClass.PLATFORM_DEPENDENCY_MISSING
    assert row.failure_fingerprint == failure.fingerprint
    assert row.failure_json["summary"] == failure.summary
    async with db_session_factory() as session:
        stored = await session.scalar(
            text("SELECT failure_class FROM tasks WHERE id = :id"), {"id": task_id}
        )
    assert stored == "PLATFORM_DEPENDENCY_MISSING"


async def test_failed_replay_returns_failure_fields(
    db_session_factory, gateway, committed_owner
) -> None:
    run = await _begun_run(db_session_factory, committed_owner)
    task_id, claim, recorded = await _claimed_failure(db_session_factory, run)

    replay = await _record(
        db_session_factory, run, task_id, claim.idempotency_key, _failed(task_id)
    )

    assert replay.idempotent_replay is True
    assert replay.failure_class == recorded.failure_class
    assert replay.failure_fingerprint == recorded.failure_fingerprint
    assert replay.failure_reason == recorded.failure_reason


# ── resolve_failed and mark_cancelled ─────────────────────────────────────


async def test_retry_increments_once(db_session_factory, gateway, committed_owner) -> None:
    run = await _begun_run(db_session_factory, committed_owner)
    task_id, _, _ = await _claimed_failure(db_session_factory, run)

    await _resolve(db_session_factory, run.id, task_id, "retry")

    task = await _get(db_session_factory, task_id)
    assert task.retry_count == 1
    assert task.status == TaskStatus.APPROVED
    claim = await _claim(db_session_factory, run.id, task_id)
    assert claim.idempotency_key.endswith(":1")


async def test_skip_failed_task(db_session_factory, gateway, committed_owner) -> None:
    run = await _begun_run(db_session_factory, committed_owner)
    task_id, _, _ = await _claimed_failure(db_session_factory, run)

    await _resolve(db_session_factory, run.id, task_id, "skip")

    assert (await _get(db_session_factory, task_id)).status == TaskStatus.SKIPPED


async def test_resolve_other_runs_task_404(db_session_factory, gateway, committed_owner) -> None:
    run = await _begun_run(db_session_factory, committed_owner)
    other = await _begun_run(db_session_factory, committed_owner)
    task_id, _, _ = await _claimed_failure(db_session_factory, other)

    with pytest.raises(NotFoundError):
        await _resolve(db_session_factory, run.id, task_id, "retry")


async def test_retry_keeps_attempt_failure(db_session_factory, gateway, committed_owner) -> None:
    run = await _begun_run(db_session_factory, committed_owner)
    task_id, claim, recorded = await _claimed_failure(db_session_factory, run)

    await _resolve(db_session_factory, run.id, task_id, "retry")

    task = await _get(db_session_factory, task_id)
    assert (task.failure_reason, task.failure_origin) == (None, None)
    assert (task.failure_class, task.failure_fingerprint) == (None, None)
    (row,) = await _executions(db_session_factory, claim.idempotency_key)
    assert row.failure_class == FailureClass.AGENT_REPORTED_FAILURE
    assert row.failure_fingerprint == recorded.failure_fingerprint
    assert row.failure_json is not None


async def test_skip_clears_failure_columns(db_session_factory, gateway, committed_owner) -> None:
    run = await _begun_run(db_session_factory, committed_owner)
    task_id, _, _ = await _claimed_failure(db_session_factory, run)

    await _resolve(db_session_factory, run.id, task_id, "skip")

    task = await _get(db_session_factory, task_id)
    assert task.failure_reason is None
    assert task.failure_origin is None
    assert task.failure_class is None
    assert task.failure_fingerprint is None


async def test_mark_cancelled_is_control_cancelled(
    db_session_factory, gateway, committed_owner
) -> None:
    run = await _begun_run(db_session_factory, committed_owner)
    task_id = await _task(db_session_factory, run, TaskStatus.APPROVED)
    await _claim(db_session_factory, run.id, task_id)

    async with db_session_factory() as session:
        await RunTaskExecutionService(session).mark_cancelled(run.id, task_id)

    task = await _get(db_session_factory, task_id)
    assert task.status == TaskStatus.FAILED
    assert task.failure_reason == "cancelled"
    async with db_session_factory() as session:
        origin, cls = (
            await session.execute(
                text("SELECT failure_origin, failure_class FROM tasks WHERE id = :id"),
                {"id": task_id},
            )
        ).one()
    assert (origin, cls) == ("CONTROL", "CANCELLED")


# ── every FAILED task carries a class ─────────────────────────────────────


async def test_no_failed_task_without_class(
    db_session_factory, gateway, committed_owner, app_sessions
) -> None:
    factory = db_session_factory
    # One success, one failure and one cancellation through the activity path.
    run = await _begun_run(factory, committed_owner)
    ok = await _task(factory, run, TaskStatus.APPROVED)
    ok_claim = await _claim(factory, run.id, ok)
    await _record(factory, run, ok, ok_claim.idempotency_key, _success(ok))
    await _claimed_failure(factory, run)
    cancelled = await _task(factory, run, TaskStatus.APPROVED)
    await _claim(factory, run.id, cancelled)
    async with factory() as session:
        await RunTaskExecutionService(session).mark_cancelled(run.id, cancelled)

    # A run ended by finalise with a QUEUED task (RUN_ABORTED).
    aborted = await _begun_run(factory, committed_owner)
    queued = await _task(factory, aborted, TaskStatus.QUEUED)
    async with factory() as session:
        await MissionRunService(session, RecordingBus()).finalise(
            aborted.id, MissionRunStatus.FAILED, MissionRunStatusReason.TASK_FAILURES, None
        )

    # An orphaned run failed by the reconciler's finalise (ORPHANED).
    orphan = await _begun_run(factory, committed_owner)
    running = await _task(factory, orphan, TaskStatus.RUNNING)
    async with factory() as session:
        await MissionRunService(session, RecordingBus()).finalise(
            orphan.id,
            MissionRunStatus.FAILED,
            MissionRunStatusReason.ORPHANED_WORKFLOW_CLOSED,
            "workflow closed without finalising",
        )

    # A failed WorkflowRun step, and a container step on a mission without
    # repo_root (ENV_UNAVAILABLE) failing the run's remaining tasks.
    wf = await _begun_run(factory, committed_owner)
    step_task = await _task(factory, wf, TaskStatus.RUNNING, in_run=False)
    remaining = await _task(factory, wf, TaskStatus.RUNNING, in_run=False)
    env_failure = get_failure_classifier().from_exception(
        ExecutionEnvironmentError("container mode requires mission.repo_root")
    )
    async with factory() as session:
        svc = WorkflowRunService(session)
        await svc._sync_plan_task_states(
            wf.plan.id,
            wf.mission.id,
            [("step-1", TaskStatus.FAILED)],
            "00000000-0000-0000-0000-000000000000",
            failures={"step-1": _dependency_failure()},
            step_task_map={"step-1": step_task},
        )
        error = WorkflowStepFailedError(env_failure, "step failed: environment")
        await svc._fail_remaining_plan_tasks(
            wf.mission.id, "00000000-0000-0000-0000-000000000000", str(error), error.failure
        )

    mission_ids = [r.mission.id for r in (run, aborted, orphan, wf)]
    async with factory() as session:
        unclassified = await session.scalar(
            select(func.count())
            .select_from(Task)
            .where(
                Task.mission_id.in_(mission_ids),
                Task.status == TaskStatus.FAILED,
                Task.failure_class.is_(None),
            )
        )
        failed = await session.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.mission_id.in_(mission_ids), Task.status == TaskStatus.FAILED)
        )
    assert unclassified == 0
    assert failed == 6
    assert (await _get(factory, queued)).failure_class == FailureClass.RUN_ABORTED
    assert (await _get(factory, running)).failure_class == FailureClass.ORPHANED
    assert (await _get(factory, step_task)).failure_class == (
        FailureClass.PLATFORM_DEPENDENCY_MISSING
    )
    assert (await _get(factory, remaining)).failure_class == FailureClass.ENV_UNAVAILABLE
