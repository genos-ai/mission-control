"""MissionRunWorkflow budget points and the budget stop (Plan 88 step 88.4.6, contract 3.3.3).

Runs the real workflow in a time-skipping Temporal environment on the
p88-budget-caps branch. Every activity is a fake registered under the real
activity name; each appends (name, input) to ``_fake.calls``. check_run_budget
returns the scripted checks in order; the last one repeats.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import pytest
from temporalio import activity, workflow
from temporalio.client import WorkflowHandle
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
        PauseForRunInput,
        PlanRunInput,
        PlanRunResult,
        RetrySnapshot,
        RunBudgetCheck,
        RunConfigSnapshot,
        RunStatusUpdate,
        RunTaskGraph,
        SupervisorFollowupInput,
        WriteDigestInput,
    )
    from modules.backend.temporal.mission_run_workflow import MissionRunWorkflow
    from modules.backend.temporal.supervisor_activities import (
        PostRunEvalInput,
        PostRunEvalResult,
    )


def _check(headroom_usd: float = 5.0, breach: str | None = None) -> RunBudgetCheck:
    return RunBudgetCheck(
        run_spent_usd=0.0,
        month_spent_usd=0.0,
        lifetime_spent_usd=0.0,
        headroom_usd=headroom_usd,
        breach=breach,
    )


@dataclass
class _Fake:
    calls: list[tuple[str, object]] = field(default_factory=list)
    layers: list[list[str]] = field(default_factory=lambda: [["a", "b"]])
    checks: list[RunBudgetCheck] = field(default_factory=lambda: [_check()])
    exceeded: set[str] = field(default_factory=set)
    hold: dict[str, asyncio.Event] = field(default_factory=dict)
    notify_error: bool = False

    def names(self) -> list[str]:
        return [n for n, _ in self.calls]

    def of(self, name: str) -> list:
        return [a for n, a in self.calls if n == name]


_fake = _Fake()


def _result(task_id: str) -> ExecuteTaskResult:
    if task_id in _fake.exceeded:
        return ExecuteTaskResult(
            task_id=task_id,
            status="failed",
            verification_failed=False,
            cost_usd=0.5,
            idempotent_replay=False,
            failure_reason="budget_exceeded",
            failure_origin="control",
            failure_class="budget_exceeded",
            failure_fingerprint="f" * 64,
        )
    return ExecuteTaskResult(
        task_id=task_id,
        status="completed",
        verification_failed=False,
        cost_usd=0.1,
        idempotent_replay=False,
        failure_reason=None,
        failure_origin=None,
        failure_class=None,
        failure_fingerprint=None,
    )


@activity.defn(name="begin_mission_run")
async def begin_fake(inp: BeginRunInput) -> BeginRunResult:
    _fake.calls.append(("begin", inp))
    return BeginRunResult(
        session_id=str(uuid.uuid4()),
        execution_record_id=str(uuid.uuid4()),
        context_version_start=0,
        gate_mode="autonomous",
        previous_run_id=None,
    )


@activity.defn(name="plan_mission_run")
async def plan_fake(inp: PlanRunInput) -> PlanRunResult:
    _fake.calls.append(("plan", inp))
    return PlanRunResult(task_ids=[], status="planned", detail=None)


@activity.defn(name="fetch_run_task_graph")
async def graph_fake(mission_run_id: str) -> RunTaskGraph:
    approved = sum(len(layer) for layer in _fake.layers)
    return RunTaskGraph(layers=_fake.layers, proposed=0, approved=approved, running=0)


@activity.defn(name="check_run_budget")
async def budget_fake(mission_run_id: str) -> RunBudgetCheck:
    _fake.calls.append(("check_run_budget", mission_run_id))
    return _fake.checks.pop(0) if len(_fake.checks) > 1 else _fake.checks[0]


@activity.defn(name="execute_plan_task")
async def execute_fake(inp: ExecuteTaskInput) -> ExecuteTaskResult:
    _fake.calls.append(("task_start", inp))
    hold = _fake.hold.get(inp.task_id)
    if hold is not None:
        await hold.wait()
    _fake.calls.append(("task_done", inp.task_id))
    return _result(inp.task_id)


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
    notification = NotificationRequest(
        kind="budget_paused" if inp.status == "budget_stopped" else "run_succeeded",
        mission_id=str(uuid.uuid4()),
        mission_run_id=inp.mission_run_id,
        gate_request_id=None,
        subject_id=inp.mission_run_id,
        payload={},
    )
    return FinaliseRunResult(cost_usd=0.0, notification=notification)


@activity.defn(name="pause_mission_for_run")
async def pause_fake(inp: PauseForRunInput) -> None:
    _fake.calls.append(("pause", inp.reason))


@activity.defn(name="send_mission_notification")
async def notify_fake(req: NotificationRequest) -> list[str]:
    _fake.calls.append(("notify", (req.kind, req.payload)))
    if _fake.notify_error:
        raise RuntimeError("telegram down")
    return []


_ACTIVITIES = [
    begin_fake,
    plan_fake,
    graph_fake,
    budget_fake,
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
    pause_fake,
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


def _input(task_queue: str, max_parallel_tasks: int) -> MissionRunWorkflowInput:
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
        max_parallel_tasks=max_parallel_tasks,
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
async def _started(
    env: WorkflowEnvironment, max_parallel_tasks: int = 2
) -> AsyncIterator[WorkflowHandle]:
    task_queue = f"mission-run-budget-{uuid.uuid4().hex[:8]}"
    inp = _input(task_queue, max_parallel_tasks)
    async with Worker(
        env.client,
        task_queue=task_queue,
        workflows=[MissionRunWorkflow],
        activities=_ACTIVITIES,
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


async def test_breach_before_layer_stops_without_dispatch(env: WorkflowEnvironment):
    _fake.checks = [_check(), _check(headroom_usd=0.0, breach="budget_monthly_cap")]

    async with _started(env) as handle:
        assert await handle.result() == "budget_stopped"

    assert _fake.of("task_start") == []
    assert _fake.of("finalise") == [("budget_stopped", "budget_monthly_cap")]
    assert _fake.of("pause") == ["budget_monthly_cap"]


async def test_breach_before_planning_spends_nothing(env: WorkflowEnvironment):
    _fake.checks = [_check(headroom_usd=0.0, breach="budget_lifetime_cap")]

    async with _started(env) as handle:
        assert await handle.result() == "budget_stopped"

    assert _fake.of("plan") == []
    assert _fake.of("task_start") == []
    assert _fake.of("finalise") == [("budget_stopped", "budget_lifetime_cap")]


async def test_breach_mid_layer_waits_inflight_then_budget_stopped(
    env: WorkflowEnvironment,
):
    _fake.exceeded = {"a"}
    _fake.hold = {"b": asyncio.Event()}
    _fake.checks = [_check(), _check(headroom_usd=2.0), _check(headroom_usd=0.0)]

    async with _started(env) as handle:
        await _until(lambda: "a" in _fake.of("task_done"))
        await asyncio.sleep(0.2)
        assert _fake.of("finalise") == []  # b is still in flight
        _fake.hold["b"].set()
        assert await handle.result() == "budget_stopped"

    names = _fake.names()
    assert names.index("finalise") > max(i for i, n in enumerate(names) if n == "task_done")
    # The run is under every cap, yet a task exhausted its share: the run cap stops it.
    assert _fake.of("finalise") == [("budget_stopped", "budget_run_cap")]
    assert _fake.of("followups") == []  # no supervisor after a budget stop


async def test_breach_calls_digest_then_finalise_then_pause_then_notify(
    env: WorkflowEnvironment,
):
    _fake.checks = [_check(), _check(headroom_usd=0.0, breach="budget_run_cap")]

    async with _started(env) as handle:
        assert await handle.result() == "budget_stopped"

    assert _fake.names()[-5:] == ["compact", "digest", "finalise", "pause", "notify"]
    digest = _fake.of("digest")[0]
    assert (digest.status, digest.reason, digest.force_deterministic) == (
        "budget_stopped",
        "budget_run_cap",
        True,
    )
    # One BUDGET_PAUSED, after the pause; finalise's own notification is not sent.
    assert _fake.of("notify") == [("budget_paused", {"cap": "budget_run_cap"})]


async def test_headroom_split_across_parallel_batch(env: WorkflowEnvironment):
    _fake.layers = [["a", "b", "c"]]
    _fake.checks = [_check(), _check(headroom_usd=3.0)]

    async with _started(env, max_parallel_tasks=3) as handle:
        assert await handle.result() == "succeeded"

    assert sorted(i.budget_headroom_usd for i in _fake.of("task_start")) == [
        1.0,
        1.0,
        1.0,
    ]


async def test_budget_notify_failure_does_not_fail_run(env: WorkflowEnvironment):
    _fake.checks = [_check(), _check(headroom_usd=0.0, breach="budget_run_cap")]
    _fake.notify_error = True

    async with _started(env) as handle:
        assert await handle.result() == "budget_stopped"

    assert _fake.names().count("notify") == 2  # every attempt raised (maximum_attempts=2)
    assert _fake.of("pause") == ["budget_run_cap"]
