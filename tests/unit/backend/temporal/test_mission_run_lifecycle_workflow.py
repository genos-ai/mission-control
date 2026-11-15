"""MissionRunWorkflow pause, resume and notifications (Plan 88 step 88.4.5, contract 3.3.3).

Runs the real workflow in a time-skipping Temporal environment on the
p88-lifecycle-signals branch. Every activity is a fake registered under the
real activity name; each appends (name, input) to ``_calls``.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import pytest
from temporalio import activity, workflow
from temporalio.client import WorkflowFailureError, WorkflowHandle
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

with workflow.unsafe.imports_passed_through():
    from modules.backend.temporal.mission_run_models import (
        ActivityPolicySnapshot,
        BeginRunInput,
        BeginRunResult,
        CompactContextInput,
        CompactContextResult,
        DigestResult,
        DirectorTurnInput,
        ExecuteTaskInput,
        ExecuteTaskResult,
        FinaliseRunInput,
        FinaliseRunResult,
        MissionRunWorkflowInput,
        NotificationRequest,
        PauseRequest,
        PlanRunInput,
        PlanRunResult,
        ResumeRequest,
        RetrySnapshot,
        RunBudgetCheck,
        RunConfigSnapshot,
        RunStatusUpdate,
        RunTaskGraph,
        SupervisorFollowupInput,
        WriteDigestInput,
    )
    from modules.backend.temporal.mission_run_workflow import MissionRunWorkflow
    from modules.backend.temporal.supervisor_activities import PostRunEvalInput, PostRunEvalResult

_SESSION_ID = "11111111-1111-1111-1111-111111111111"
_RECORD_ID = "22222222-2222-2222-2222-222222222222"


@dataclass
class _Fake:
    calls: list[tuple[str, object]] = field(default_factory=list)
    layers: list[list[str]] = field(default_factory=lambda: [["a", "b"], ["c"]])
    begin_release: asyncio.Event | None = None
    task_release: asyncio.Event | None = None
    block_forever: set[str] = field(default_factory=set)
    notification: NotificationRequest | None = None
    notify_error: bool = False

    def names(self) -> list[str]:
        return [n for n, _ in self.calls]

    def of(self, name: str) -> list:
        return [a for n, a in self.calls if n == name]


_fake = _Fake()


def _done(task_id: str) -> ExecuteTaskResult:
    return ExecuteTaskResult(
        task_id=task_id,
        status="completed",
        verification_failed=False,
        cost_usd=0.0,
        idempotent_replay=False,
        failure_reason=None,
        failure_origin=None,
        failure_class=None,
        failure_fingerprint=None,
    )


@activity.defn(name="begin_mission_run")
async def begin_fake(inp: BeginRunInput) -> BeginRunResult:
    _fake.calls.append(("begin", inp))
    if _fake.begin_release is not None:
        await _fake.begin_release.wait()
    return BeginRunResult(
        session_id=_SESSION_ID,
        execution_record_id=_RECORD_ID,
        context_version_start=0,
        gate_mode="autonomous",
        previous_run_id=None,
    )


@activity.defn(name="plan_mission_run")
async def plan_fake(inp: PlanRunInput) -> PlanRunResult:
    return PlanRunResult(task_ids=[], status="planned", detail=None)


@activity.defn(name="fetch_run_task_graph")
async def graph_fake(mission_run_id: str) -> RunTaskGraph:
    approved = sum(len(layer) for layer in _fake.layers)
    return RunTaskGraph(layers=_fake.layers, proposed=0, approved=approved, running=0)


@activity.defn(name="execute_plan_task")
async def execute_fake(inp: ExecuteTaskInput) -> ExecuteTaskResult:
    _fake.calls.append(("task_start", inp.task_id))
    if inp.task_id in _fake.block_forever:
        while True:
            activity.heartbeat()
            await asyncio.sleep(0.05)
    if _fake.task_release is not None and inp.task_id in ("a", "b"):
        await _fake.task_release.wait()
    _fake.calls.append(("task_done", inp.task_id))
    return _done(inp.task_id)


@activity.defn(name="set_mission_run_status")
async def status_fake(inp: RunStatusUpdate) -> None:
    _fake.calls.append(("status", (inp.status, inp.reason)))


@activity.defn(name="evaluate_post_run")
async def evaluate_fake(inp: PostRunEvalInput) -> PostRunEvalResult:
    return PostRunEvalResult(action="propose_complete", reason="because")


@activity.defn(name="fire_supervisor_followups")
async def followups_fake(inp: SupervisorFollowupInput) -> None:
    _fake.calls.append(("followups", inp.action))


@activity.defn(name="check_plan_active")
async def plan_active_fake(mission_id: str) -> bool:
    _fake.calls.append(("check_plan_active", mission_id))
    return True


@activity.defn(name="approve_run_proposed_tasks")
async def approve_fake(mission_run_id: str) -> int:
    return 0


@activity.defn(name="start_director_turn")
async def director_fake(inp: DirectorTurnInput) -> str:
    return "director-turn"


@activity.defn(name="compact_mission_context")
async def compact_fake(inp: CompactContextInput) -> CompactContextResult:
    _fake.calls.append(("compact", inp))
    return CompactContextResult(compacted=False, from_bytes=0, to_bytes=0)


@activity.defn(name="write_run_digest")
async def digest_fake(inp: WriteDigestInput) -> DigestResult:
    _fake.calls.append(("digest", inp))
    return DigestResult(digest_id=str(uuid.uuid4()), generator="deterministic")


@activity.defn(name="finalise_mission_run")
async def finalise_fake(inp: FinaliseRunInput) -> FinaliseRunResult:
    _fake.calls.append(("finalise", (inp.status, inp.reason)))
    return FinaliseRunResult(cost_usd=0.0, notification=_fake.notification)


@activity.defn(name="send_mission_notification")
async def notify_fake(req: NotificationRequest) -> list[str]:
    _fake.calls.append(("notify", req.kind))
    if _fake.notify_error:
        raise RuntimeError("telegram down")
    return []


@activity.defn(name="check_run_budget")
async def budget_fake(mission_run_id: str) -> RunBudgetCheck:
    """Ample headroom and no breach: the p88-budget-caps branch runs unchanged (88.4.6)."""
    return RunBudgetCheck(
        run_spent_usd=0.0,
        month_spent_usd=0.0,
        lifetime_spent_usd=0.0,
        headroom_usd=5.0,
        breach=None,
    )


_ACTIVITIES = [
    budget_fake,
    begin_fake,
    plan_fake,
    graph_fake,
    execute_fake,
    status_fake,
    evaluate_fake,
    followups_fake,
    plan_active_fake,
    approve_fake,
    director_fake,
    compact_fake,
    digest_fake,
    finalise_fake,
    notify_fake,
]


def _policy() -> ActivityPolicySnapshot:
    return ActivityPolicySnapshot(
        start_to_close_seconds=30,
        heartbeat_timeout_seconds=None,
        retry=RetrySnapshot(
            initial_interval_seconds=1,
            backoff_coefficient=1.0,
            maximum_interval_seconds=1,
            maximum_attempts=2,
        ),
    )


def _input(task_queue: str) -> MissionRunWorkflowInput:
    policy = _policy()
    config = RunConfigSnapshot(
        config_hash="test",
        task_queue=task_queue,
        persistence=policy,
        plan_run=policy,
        execute_task=policy,
        evaluate_gate=policy,
        evaluate_post_run=policy,
        director_turn=policy,
        write_digest=policy,
        notify=policy,
        gate_escalate_after_seconds=60,
        gate_pause_after_seconds=120,
        gate_points_enabled={},
        refine_wait_seconds=5,
        continue_as_new_after_iterations=10,
        max_parallel_tasks=2,
        max_run_duration_seconds=43200,
        task_heartbeat_interval_seconds=20,
        max_failure_digests=10,
    )
    return MissionRunWorkflowInput(
        mission_run_id=str(uuid.uuid4()),
        mission_id=str(uuid.uuid4()),
        plan_id=str(uuid.uuid4()),
        config=config,
    )


@pytest.fixture
async def env() -> AsyncIterator[WorkflowEnvironment]:
    global _fake
    _fake = _Fake()
    environment = await WorkflowEnvironment.start_time_skipping()
    try:
        yield environment
    finally:
        await environment.shutdown()


@asynccontextmanager
async def _started(env: WorkflowEnvironment) -> AsyncIterator[WorkflowHandle]:
    task_queue = f"mission-run-lifecycle-{uuid.uuid4().hex[:8]}"
    inp = _input(task_queue)
    async with Worker(
        env.client, task_queue=task_queue, workflows=[MissionRunWorkflow], activities=_ACTIVITIES
    ):
        yield await env.client.start_workflow(
            MissionRunWorkflow.run,
            inp,
            id=f"mission-run-{inp.mission_run_id}",
            task_queue=task_queue,
        )


async def _until(predicate: Callable[[], bool], timeout: float = 15.0) -> None:
    async def _poll() -> None:
        while not predicate():
            await asyncio.sleep(0.02)

    await asyncio.wait_for(_poll(), timeout=timeout)


_PAUSE = PauseRequest(requested_by_user_id=None, reason="user")
_RESUME = ResumeRequest(requested_by_user_id=None)


async def test_pause_waits_for_inflight_layer_then_pauses(env: WorkflowEnvironment):
    _fake.task_release = asyncio.Event()

    async with _started(env) as handle:
        await _until(lambda: _fake.names().count("task_start") == 2)
        await handle.signal(MissionRunWorkflow.request_pause, _PAUSE)
        _fake.task_release.set()
        await _until(lambda: ("status", ("paused", "user_pause")) in _fake.calls)
        names = _fake.names()
        paused_at = names.index("status")
        assert names[:paused_at].count("task_done") == 2
        assert "c" not in [a for n, a in _fake.calls if n == "task_start"]
        await handle.signal(MissionRunWorkflow.resume, _RESUME)
        assert await handle.result() == "succeeded"


async def test_resume_before_boundary_cancels_pause(env: WorkflowEnvironment):
    _fake.task_release = asyncio.Event()

    async with _started(env) as handle:
        await _until(lambda: _fake.names().count("task_start") == 2)
        await handle.signal(MissionRunWorkflow.request_pause, _PAUSE)
        await handle.signal(MissionRunWorkflow.resume, _RESUME)
        _fake.task_release.set()
        assert await handle.result() == "succeeded"

    assert _fake.of("status") == []
    assert sorted(_fake.of("task_done")[:2]) == ["a", "b"]
    assert _fake.of("task_done")[2:] == ["c"]


async def test_resume_continues_next_layer(env: WorkflowEnvironment):
    _fake.task_release = asyncio.Event()

    async with _started(env) as handle:
        await _until(lambda: _fake.names().count("task_start") == 2)
        await handle.signal(MissionRunWorkflow.request_pause, _PAUSE)
        _fake.task_release.set()
        await _until(lambda: ("status", ("paused", "user_pause")) in _fake.calls)
        await handle.signal(MissionRunWorkflow.resume, _RESUME)
        assert await handle.result() == "succeeded"

    names = [(n, a) for n, a in _fake.calls if n in ("status", "task_start")]
    assert names[-3:] == [
        ("status", ("paused", "user_pause")),
        ("status", ("running", None)),
        ("task_start", "c"),
    ]


async def test_signal_before_begin_completes(env: WorkflowEnvironment):
    _fake.begin_release = asyncio.Event()

    async with _started(env) as handle:
        await _until(lambda: "begin" in _fake.names())
        await handle.signal(MissionRunWorkflow.request_pause, _PAUSE)
        _fake.begin_release.set()
        await _until(lambda: ("status", ("paused", "user_pause")) in _fake.calls)
        assert "task_start" not in _fake.names()
        await handle.signal(MissionRunWorkflow.resume, _RESUME)
        assert await handle.result() == "succeeded"


async def test_cancel_runs_digest_then_finalise_cancelled(env: WorkflowEnvironment):
    _fake.block_forever = {"a", "b"}

    async with _started(env) as handle:
        await _until(lambda: _fake.names().count("task_start") == 2)
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await handle.result()

    tail = [n for n in _fake.names() if n in ("compact", "digest", "finalise")]
    assert tail == ["compact", "digest", "finalise"]
    assert _fake.of("digest")[0].force_deterministic is True
    assert _fake.of("finalise") == [("cancelled", None)]


async def test_run_end_notification_sent(env: WorkflowEnvironment):
    _fake.notification = NotificationRequest(
        kind="run_succeeded",
        mission_id=str(uuid.uuid4()),
        mission_run_id=str(uuid.uuid4()),
        gate_request_id=None,
        subject_id="run",
        payload={},
    )

    async with _started(env) as handle:
        assert await handle.result() == "succeeded"

    names = _fake.names()
    assert names[-2:] == ["finalise", "notify"]
    assert _fake.of("notify") == ["run_succeeded"]
    assert "check_plan_active" not in names


async def test_notify_failure_does_not_fail_run(env: WorkflowEnvironment):
    _fake.notify_error = True
    _fake.notification = NotificationRequest(
        kind="run_succeeded",
        mission_id=str(uuid.uuid4()),
        mission_run_id=str(uuid.uuid4()),
        gate_request_id=None,
        subject_id="run",
        payload={},
    )

    async with _started(env) as handle:
        assert await handle.result() == "succeeded"

    assert _fake.of("notify") == ["run_succeeded", "run_succeeded"]  # both attempts failed
