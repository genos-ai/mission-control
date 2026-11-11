"""MissionRunWorkflow (Plan 88 steps 88.1.8 and 88.2.6, contract 3.3.3).

Runs the real workflow in a time-skipping Temporal environment. Every activity
is a fake registered under the real activity name; the fakes read their script
from the module-level ``_fake`` and record what the workflow sent them.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import pytest
from temporalio import activity, workflow
from temporalio.client import WorkflowExecutionStatus, WorkflowFailureError, WorkflowHandle
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

# The workflow sandbox re-imports this module; pass application imports through,
# as every workflow module in modules/backend/temporal does.
with workflow.unsafe.imports_passed_through():
    from modules.backend.temporal.mission_run_models import (
        ActivityPolicySnapshot,
        BeginRunInput,
        BeginRunResult,
        DirectorTurnInput,
        ExecuteTaskInput,
        ExecuteTaskResult,
        FinaliseRunInput,
        FinaliseRunResult,
        MissionRunWorkflowInput,
        MissionRunWorkflowStatus,
        PlanRunInput,
        PlanRunResult,
        RefinementOutcome,
        RetrySnapshot,
        RunConfigSnapshot,
        RunTaskGraph,
        SupervisorFollowupInput,
        TasksApprovedSignal,
    )
    from modules.backend.temporal.mission_run_workflow import MissionRunWorkflow
    from modules.backend.temporal.supervisor_activities import PostRunEvalInput, PostRunEvalResult

_SESSION_ID = "11111111-1111-1111-1111-111111111111"
_RECORD_ID = "22222222-2222-2222-2222-222222222222"


@dataclass
class _Fake:
    begin_error: Exception | None = None
    begin_release: asyncio.Event | None = None
    plan_result: PlanRunResult = field(
        default_factory=lambda: PlanRunResult(task_ids=["t1"], status="planned", detail=None)
    )
    graphs: list[RunTaskGraph] = field(default_factory=list)
    graph_started: asyncio.Event = field(default_factory=asyncio.Event)
    graph_release: asyncio.Event | None = None
    graph_calls: int = 0
    execute_failures: int = 0
    execute_attempts: int = 0
    execute_started: asyncio.Event = field(default_factory=asyncio.Event)
    execute_block: bool = False
    actions: list[str] = field(default_factory=list)
    finalised: list[FinaliseRunInput] = field(default_factory=list)
    director_prompts: list[str] = field(default_factory=list)
    director_started: asyncio.Event = field(default_factory=asyncio.Event)


_fake = _Fake()


def _graph(proposed: int, approved: int) -> RunTaskGraph:
    layers = [["t1"]] if approved else []
    return RunTaskGraph(layers=layers, proposed=proposed, approved=approved, running=0)


@activity.defn(name="begin_mission_run")
async def begin_fake(inp: BeginRunInput) -> BeginRunResult:
    if _fake.begin_release is not None:
        await _fake.begin_release.wait()
    if _fake.begin_error is not None:
        raise _fake.begin_error
    return BeginRunResult(
        session_id=_SESSION_ID,
        execution_record_id=_RECORD_ID,
        context_version_start=0,
        gate_mode="autonomous",
        previous_run_id=None,
    )


@activity.defn(name="plan_mission_run")
async def plan_fake(inp: PlanRunInput) -> PlanRunResult:
    return _fake.plan_result


@activity.defn(name="fetch_run_task_graph")
async def graph_fake(mission_run_id: str) -> RunTaskGraph:
    _fake.graph_calls += 1
    first = _fake.graph_calls == 1
    graph = _fake.graphs.pop(0) if len(_fake.graphs) > 1 else _fake.graphs[0]
    if first and _fake.graph_release is not None:
        _fake.graph_started.set()
        await _fake.graph_release.wait()
    return graph


@activity.defn(name="execute_plan_task")
async def execute_fake(inp: ExecuteTaskInput) -> ExecuteTaskResult:
    _fake.execute_attempts += 1
    _fake.execute_started.set()
    if _fake.execute_block:
        while True:
            activity.heartbeat()
            await asyncio.sleep(0.05)
    if _fake.execute_attempts <= _fake.execute_failures:
        raise RuntimeError("transient")
    return ExecuteTaskResult(
        task_id=inp.task_id,
        status="completed",
        verification_failed=False,
        cost_usd=0.0,
        idempotent_replay=False,
        failure_reason=None,
        failure_origin=None,
        failure_class=None,
        failure_fingerprint=None,
    )


@activity.defn(name="evaluate_post_run")
async def evaluate_fake(inp: PostRunEvalInput) -> PostRunEvalResult:
    action = _fake.actions.pop(0) if len(_fake.actions) > 1 else _fake.actions[0]
    return PostRunEvalResult(action=action, reason="because")


@activity.defn(name="fire_supervisor_followups")
async def followups_fake(inp: SupervisorFollowupInput) -> None:
    return None


@activity.defn(name="check_plan_active")
async def plan_active_fake(mission_id: str) -> bool:
    return True


@activity.defn(name="approve_run_proposed_tasks")
async def approve_fake(mission_run_id: str) -> int:
    return 0


@activity.defn(name="start_director_turn")
async def director_fake(inp: DirectorTurnInput) -> str:
    _fake.director_prompts.append(inp.prompt)
    _fake.director_started.set()
    return "director-turn"


@activity.defn(name="finalise_mission_run")
async def finalise_fake(inp: FinaliseRunInput) -> FinaliseRunResult:
    _fake.finalised.append(inp)
    return FinaliseRunResult(cost_usd=0.0, notification=None)


_ACTIVITIES = [
    begin_fake,
    plan_fake,
    graph_fake,
    execute_fake,
    evaluate_fake,
    followups_fake,
    plan_active_fake,
    approve_fake,
    director_fake,
    finalise_fake,
]


def _policy(max_attempts: int = 3) -> ActivityPolicySnapshot:
    return ActivityPolicySnapshot(
        start_to_close_seconds=30,
        heartbeat_timeout_seconds=None,
        retry=RetrySnapshot(
            initial_interval_seconds=1,
            backoff_coefficient=1.0,
            maximum_interval_seconds=1,
            maximum_attempts=max_attempts,
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
        max_parallel_tasks=1,
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
    task_queue = f"mission-run-test-{uuid.uuid4().hex[:8]}"
    inp = _input(task_queue)
    async with Worker(
        env.client, task_queue=task_queue, workflows=[MissionRunWorkflow], activities=_ACTIVITIES
    ):
        handle = await env.client.start_workflow(
            MissionRunWorkflow.run,
            inp,
            id=f"mission-run-{inp.mission_run_id}",
            task_queue=task_queue,
        )
        yield handle


def _ends(*expected: tuple[str, str | None]) -> None:
    assert [(f.status, f.reason) for f in _fake.finalised] == list(expected)


async def test_begin_plan_execute_propose_complete_succeeds(env: WorkflowEnvironment):
    _fake.graphs = [_graph(0, 1)]
    _fake.actions = ["propose_complete"]

    async with _started(env) as handle:
        assert await handle.result() == "succeeded"

    _ends(("succeeded", "objective_met"))
    assert _fake.finalised[0].detail == "because"
    assert len(_fake.director_prompts) == 1


async def test_invalid_gate_mode_returns_failed_without_finalise(env: WorkflowEnvironment):
    _fake.begin_error = ApplicationError(
        "gate mode interactive cannot run", type="RunStartRejectedError", non_retryable=True
    )

    async with _started(env) as handle:
        assert await handle.result() == "failed"

    assert _fake.finalised == []


async def test_owner_rejected_returns_failed_without_finalise(env: WorkflowEnvironment):
    _fake.begin_error = ApplicationError(
        "owner not a platform user", type="RunStartRejectedError", non_retryable=True
    )

    async with _started(env) as handle:
        assert await handle.result() == "failed"

    assert _fake.finalised == []


async def test_planning_failed_finalises(env: WorkflowEnvironment):
    _fake.plan_result = PlanRunResult(task_ids=[], status="failed", detail="no planner")

    async with _started(env) as handle:
        assert await handle.result() == "failed"

    _ends(("failed", "planning_failed"))
    assert _fake.finalised[0].detail == "no planner"


async def test_no_tasks_finalises_no_further_work(env: WorkflowEnvironment):
    _fake.graphs = [_graph(0, 0)]

    async with _started(env) as handle:
        assert await handle.result() == "succeeded"

    _ends(("succeeded", "no_further_work"))


async def test_waits_for_tasks_approved_signal(env: WorkflowEnvironment):
    _fake.graphs = [_graph(1, 0), _graph(0, 1)]
    _fake.actions = ["propose_complete"]

    with env.auto_time_skipping_disabled():
        async with _started(env) as handle:
            for _ in range(100):
                state = await handle.query(MissionRunWorkflow.get_run_state)
                if state.phase == "awaiting_gate":
                    break
                await asyncio.sleep(0.05)
            assert state.phase == "awaiting_gate"
            await asyncio.sleep(0.2)
            assert _fake.graph_calls == 1
            assert _fake.execute_attempts == 0

            await handle.signal(MissionRunWorkflow.tasks_approved, TasksApprovedSignal(["t1"]))
            assert await handle.result() == "succeeded"

    assert _fake.graph_calls == 2
    _ends(("succeeded", "objective_met"))


async def test_signal_before_begin_completes(env: WorkflowEnvironment):
    _fake.begin_release = asyncio.Event()
    _fake.graphs = [_graph(0, 1)]
    _fake.actions = ["propose_complete"]

    with env.auto_time_skipping_disabled():
        async with _started(env) as handle:
            await handle.signal(MissionRunWorkflow.tasks_approved, TasksApprovedSignal(["t1"]))
            state = await handle.query(MissionRunWorkflow.get_run_state)
            assert state.phase == "planning"

            _fake.begin_release.set()
            assert await handle.result() == "succeeded"

    _ends(("succeeded", "objective_met"))


async def test_signal_during_graph_fetch_not_lost(env: WorkflowEnvironment):
    _fake.graph_release = asyncio.Event()
    _fake.graphs = [_graph(1, 0), _graph(0, 1)]
    _fake.actions = ["propose_complete"]

    with env.auto_time_skipping_disabled():
        async with _started(env) as handle:
            await asyncio.wait_for(_fake.graph_started.wait(), timeout=10)
            await handle.signal(MissionRunWorkflow.tasks_approved, TasksApprovedSignal(["t1"]))
            _fake.graph_release.set()
            assert await handle.result() == "succeeded"

    assert _fake.graph_calls == 2
    _ends(("succeeded", "objective_met"))


async def test_refine_without_new_tasks_escalates(env: WorkflowEnvironment):
    _fake.graphs = [_graph(0, 1), _graph(0, 0)]
    _fake.actions = ["advance_refine"]

    async with _started(env) as handle:
        assert await handle.result() == "failed"

    _ends(("failed", "supervisor_escalated"))
    assert _fake.finalised[0].detail == (
        "refine produced no tasks: no refinement_complete signal within 5s"
    )


async def test_refine_turn_signalled_without_new_tasks_fails(env: WorkflowEnvironment):
    # A refine turn that ends without calling refine_plan (or errors) still
    # signals refinement_complete; the signal must not count as a refine.
    _fake.graphs = [_graph(0, 1), _graph(0, 0)]
    _fake.actions = ["advance_refine"]

    with env.auto_time_skipping_disabled():
        async with _started(env) as handle:
            await asyncio.wait_for(_fake.director_started.wait(), timeout=10)
            await handle.signal(MissionRunWorkflow.refinement_complete)
            assert await asyncio.wait_for(handle.result(), timeout=4) == "failed"

    _ends(("failed", "supervisor_escalated"))
    assert _fake.finalised[0].detail == (
        "refine produced no tasks: Director turn ended without an outcome"
    )


async def test_refine_turn_outcome_is_the_end_detail_cause(env: WorkflowEnvironment):
    # The refinement_complete payload carries why the turn added nothing:
    # the turn's error, else the Director's reply (which relays a failed refine).
    _fake.graphs = [_graph(0, 1), _graph(0, 0)]
    _fake.actions = ["advance_refine"]

    with env.auto_time_skipping_disabled():
        async with _started(env) as handle:
            await asyncio.wait_for(_fake.director_started.wait(), timeout=10)
            await handle.signal(
                MissionRunWorkflow.refinement_complete,
                RefinementOutcome(error=None, reply="Plan refinement failed: planner timed out"),
            )
            assert await asyncio.wait_for(handle.result(), timeout=4) == "failed"

    _ends(("failed", "supervisor_escalated"))
    assert _fake.finalised[0].detail == (
        "refine produced no tasks: Director turn ended without new tasks; "
        "Director replied: Plan refinement failed: planner timed out"
    )


async def test_cancel_finalises_cancelled(env: WorkflowEnvironment):
    _fake.graphs = [_graph(0, 1)]
    _fake.execute_block = True

    with env.auto_time_skipping_disabled():
        async with _started(env) as handle:
            await asyncio.wait_for(_fake.execute_started.wait(), timeout=10)
            await handle.cancel()
            with pytest.raises(WorkflowFailureError):
                await handle.result()
            assert (await handle.describe()).status == WorkflowExecutionStatus.CANCELED

    _ends(("cancelled", None))
    assert _fake.finalised[0].detail is None


async def test_get_run_state_query(env: WorkflowEnvironment):
    _fake.graphs = [_graph(0, 1)]
    _fake.actions = ["propose_complete"]

    async with _started(env) as handle:
        await handle.result()
        state = await handle.query(MissionRunWorkflow.get_run_state)

    assert state == MissionRunWorkflowStatus(
        mission_run_id=state.mission_run_id,
        iteration=1,
        phase="finalising",
        pending_gate_id=None,
        pause_requested=False,
        last_supervisor_action="propose_complete",
    )
    assert handle.id == f"mission-run-{state.mission_run_id}"


async def test_execute_task_policy_applied(env: WorkflowEnvironment):
    _fake.graphs = [_graph(0, 1)]
    _fake.actions = ["propose_complete"]
    _fake.execute_failures = 2

    async with _started(env) as handle:
        assert await handle.result() == "succeeded"

    assert _fake.execute_attempts == 3
    _ends(("succeeded", "objective_met"))
