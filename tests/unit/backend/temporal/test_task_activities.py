"""Tests for execute_plan_task (Plan 88 step 88.2.4, contracts 3.1.9 and 3.3.5).

The DB session, RunTaskExecutionService, Redis, the event bus, the runtime
builder and run_single_task are patched; the activity's control flow runs for
real inside temporalio's ActivityEnvironment.
"""

import asyncio
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from temporalio.activity import ActivityCancellationDetails
from temporalio.testing import ActivityEnvironment

from modules.backend.core.config_schema import FailuresSchema
from modules.backend.core.exceptions import ExecutionEnvironmentError
from modules.backend.core.failure_classification import FailureClassifier
from modules.backend.events.mission_run_types import TaskFailedEvent
from modules.backend.schemas.execution_outcome import TaskResult, TaskStatus
from modules.backend.schemas.task_failure import FailureClass
from modules.backend.schemas.task_plan import TaskDefinition, TaskInputs
from modules.backend.services.run_task_execution import TaskClaim
from modules.backend.temporal.mission_run_models import ExecuteTaskInput, ExecuteTaskResult
from modules.backend.temporal.task_activities import execute_plan_task

_MOD = "modules.backend.temporal.task_activities"
MISSION_ID = "00000000-0000-0000-0000-000000000001"
RUN_ID = "00000000-0000-0000-0000-0000000000a1"
TASK_ID = "00000000-0000-0000-0000-0000000000b1"
SESSION_ID = "00000000-0000-0000-0000-0000000000c1"
KEY = f"{RUN_ID}:{TASK_ID}:0"


def _classifier() -> FailureClassifier:
    config = FailuresSchema.model_validate(
        {
            "evidence": {
                "max_message_chars": 500,
                "max_traceback_frames": 5,
                "max_summary_chars": 200,
            },
            "unknown_retryable": True,
            "supervisor": {"max_failure_digests": 5},
        }
    )
    return FailureClassifier(config, Path(__file__).resolve().parents[4] / "modules")


def _input(interval: float = 60) -> ExecuteTaskInput:
    return ExecuteTaskInput(
        mission_run_id=RUN_ID,
        task_id=TASK_ID,
        session_id=SESSION_ID,
        execution_record_id="rec-1",
        budget_headroom_usd=None,
        heartbeat_interval_seconds=interval,
    )


def _definition() -> TaskDefinition:
    return TaskDefinition(
        task_id=TASK_ID,
        agent="system.summarization.agent",
        agent_version="1.0.0",
        description="Summarise",
        instructions="Do it",
        inputs=TaskInputs(),
        dependencies=[],
    )


def _claim(outcome: str = "execute", stored: ExecuteTaskResult | None = None) -> TaskClaim:
    return TaskClaim(
        outcome=outcome,
        idempotency_key=KEY,
        task_definition=_definition() if outcome == "execute" else None,
        stored=stored,
        mission_id=MISSION_ID,
        execution_mode="local",
        mission_repo_root=None,
    )


def _recorded(status: str, *, replay: bool = False, failure_class: str | None = None):
    failed = status == "failed"
    return ExecuteTaskResult(
        task_id=TASK_ID,
        status=status,
        verification_failed=False,
        cost_usd=0.0,
        idempotent_replay=replay,
        failure_reason="summary" if failed else None,
        failure_origin="agent" if failed else None,
        failure_class=failure_class if failed else None,
        failure_fingerprint="f" * 64 if failed else None,
    )


def _failed_task_result() -> TaskResult:
    failure = _classifier().agent_outcome("system.summarization.agent", "agent said no")
    return TaskResult(
        task_id=TASK_ID,
        agent_name="system.summarization.agent",
        status=TaskStatus.FAILED,
        failure=failure,
    )


def _ok_task_result() -> TaskResult:
    return TaskResult(
        task_id=TASK_ID, agent_name="system.summarization.agent", status=TaskStatus.SUCCESS
    )


@contextmanager
def _patched(*, claim: TaskClaim, run_result=None, recorded=None, runtime_error=None):
    """Patch the activity's collaborators; yield the mocks the tests assert on."""

    @asynccontextmanager
    async def _session():
        yield SimpleNamespace()

    svc = MagicMock()
    svc.claim = AsyncMock(return_value=claim)
    svc.record = AsyncMock(return_value=recorded)
    svc.mark_cancelled = AsyncMock()
    bus = MagicMock(publish=AsyncMock())
    redis = MagicMock(aclose=AsyncMock())
    build = AsyncMock(side_effect=runtime_error, return_value=SimpleNamespace(context_curator=None))
    run = run_result if callable(run_result) else AsyncMock(return_value=run_result)
    with (
        patch(f"{_MOD}.get_async_session", _session),
        patch(f"{_MOD}.RunTaskExecutionService", return_value=svc),
        patch(f"{_MOD}.AsyncRedis.from_url", return_value=redis),
        patch(f"{_MOD}.get_redis_url", return_value="redis://test"),
        patch(f"{_MOD}.SessionEventBus", return_value=bus),
        patch(f"{_MOD}.build_dispatch_runtime", build),
        patch(f"{_MOD}.load_dependency_outputs", AsyncMock(return_value={})),
        patch(f"{_MOD}.run_single_task", run),
        patch(f"{_MOD}.get_failure_classifier", return_value=_classifier()),
    ):
        yield SimpleNamespace(svc=svc, bus=bus, redis=redis, build=build, run=run)


@pytest.mark.asyncio
async def test_replay_skips_agent():
    stored = _recorded("completed", replay=True)
    with _patched(claim=_claim("replay", stored)) as m:
        result = await ActivityEnvironment().run(execute_plan_task, _input())

    assert result == stored
    m.run.assert_not_awaited()
    m.svc.record.assert_not_awaited()
    m.bus.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_heartbeats_emitted():
    beats: list = []

    async def _slow_agent(**_kwargs):
        await asyncio.sleep(0.05)
        return _ok_task_result()

    env = ActivityEnvironment()
    env.on_heartbeat = lambda *details: beats.append(details)
    with _patched(claim=_claim(), run_result=_slow_agent, recorded=_recorded("completed")):
        await env.run(execute_plan_task, _input(interval=0.01))

    assert len(beats) >= 3
    assert all("phase" in details[0] for details in beats)
    assert {"claim", "agent"} <= {details[0]["phase"] for details in beats}


@pytest.mark.asyncio
async def test_cancel_marks_failed_and_reraises():
    started = asyncio.Event()

    async def _hanging_agent(**_kwargs):
        started.set()
        await asyncio.sleep(60)

    env = ActivityEnvironment()
    with _patched(claim=_claim(), run_result=_hanging_agent) as m:
        running = asyncio.ensure_future(env.run(execute_plan_task, _input()))
        await started.wait()
        env.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running

    m.svc.mark_cancelled.assert_awaited_once_with(RUN_ID, TASK_ID)
    m.svc.record.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["timed_out", "worker_shutdown"])
async def test_interrupt_leaves_task_running(reason):
    """Rule B: an attempt interrupted outside the workflow is re-executed, not failed."""
    started = asyncio.Event()

    async def _hanging_agent(**_kwargs):
        started.set()
        await asyncio.sleep(60)

    env = ActivityEnvironment()
    with _patched(claim=_claim(), run_result=_hanging_agent) as m:
        running = asyncio.ensure_future(env.run(execute_plan_task, _input()))
        await started.wait()
        env.cancel(ActivityCancellationDetails(**{reason: True}))
        with pytest.raises(asyncio.CancelledError):
            await running

    m.svc.mark_cancelled.assert_not_awaited()
    m.svc.record.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_failure_returns_failed_not_raises():
    recorded = _recorded("failed", failure_class="agent_reported_failure")
    with _patched(claim=_claim(), run_result=_failed_task_result(), recorded=recorded) as m:
        result = await ActivityEnvironment().run(execute_plan_task, _input())

    assert result.status == "failed"
    stored_json = m.svc.record.await_args.kwargs["task_result_json"]
    assert stored_json["status"] == "failed"
    assert stored_json["failure"]["failure_class"] == "agent_reported_failure"


@pytest.mark.asyncio
async def test_environment_error_fails_task_not_activity():
    recorded = _recorded("failed", failure_class="env_unavailable")
    with _patched(
        claim=_claim(),
        recorded=recorded,
        runtime_error=ExecutionEnvironmentError("no repo_root for container mode"),
    ) as m:
        result = await ActivityEnvironment().run(execute_plan_task, _input())

    assert result.status == "failed"
    assert result.failure_class == "env_unavailable"
    m.run.assert_not_awaited()
    stored_json = m.svc.record.await_args.kwargs["task_result_json"]
    assert stored_json["failure"]["failure_class"] == FailureClass.ENV_UNAVAILABLE.value


@pytest.mark.asyncio
async def test_task_failed_event_published_once():
    recorded = _recorded("failed", failure_class="agent_reported_failure")
    with _patched(claim=_claim(), run_result=_failed_task_result(), recorded=recorded) as m:
        await ActivityEnvironment().run(execute_plan_task, _input())

    m.bus.publish.assert_awaited_once()
    (event,) = m.bus.publish.await_args.args
    assert isinstance(event, TaskFailedEvent)
    assert event.mission_id == MISSION_ID
    assert event.mission_run_id == RUN_ID
    assert event.failure_class == "agent_reported_failure"

    replayed = _recorded("failed", replay=True, failure_class="agent_reported_failure")
    with _patched(claim=_claim(), run_result=_failed_task_result(), recorded=replayed) as m:
        await ActivityEnvironment().run(execute_plan_task, _input())

    m.bus.publish.assert_not_awaited()
