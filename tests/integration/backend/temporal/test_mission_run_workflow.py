"""MissionRunWorkflow layers, durable WAIT, hard stop and continue-as-new (Plan 88 88.2.6, 88.2.7).

Runs the real workflow in a time-skipping Temporal environment with stub
activities (mission_run_stubs). The worker uses UnsandboxedWorkflowRunner so a
monkeypatched MissionRunWorkflow._gate takes effect.
"""

import asyncio
import dataclasses
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from temporalio import workflow
from temporalio.client import WorkflowHandle
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from modules.backend.core.utils import utc_now
from modules.backend.temporal.config_snapshots import build_run_config_snapshot
from modules.backend.temporal.mission_run_models import (
    ExecuteTaskInput,
    ExecuteTaskResult,
    MissionRunWorkflowInput,
    MissionRunWorkflowState,
    PendingGate,
    TasksApprovedSignal,
)
from modules.backend.temporal.mission_run_workflow import MissionRunWorkflow
from tests.integration.backend.temporal import mission_run_stubs as stubs
from tests.integration.backend.temporal.mission_run_stubs import (
    completed,
    failed,
    graph,
    non_retryable,
)


@pytest.fixture
async def env() -> AsyncIterator[WorkflowEnvironment]:
    stubs.reset()
    environment = await WorkflowEnvironment.start_time_skipping()
    try:
        yield environment
    finally:
        await environment.shutdown()


def _input(task_queue: str, **config) -> MissionRunWorkflowInput:
    snapshot = dataclasses.replace(build_run_config_snapshot(), task_queue=task_queue, **config)
    return MissionRunWorkflowInput(
        mission_run_id=str(uuid.uuid4()),
        mission_id=str(uuid.uuid4()),
        plan_id=str(uuid.uuid4()),
        config=snapshot,
    )


@asynccontextmanager
async def _started(
    env: WorkflowEnvironment,
    state: MissionRunWorkflowState | None = None,
    **config,
) -> AsyncIterator[WorkflowHandle]:
    task_queue = f"mission-run-it-{uuid.uuid4().hex[:8]}"
    inp = dataclasses.replace(_input(task_queue, **config), state=state)
    async with Worker(
        env.client,
        task_queue=task_queue,
        workflows=[MissionRunWorkflow],
        activities=stubs.ACTIVITIES,
        workflow_runner=UnsandboxedWorkflowRunner(),
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


def _ends(status: str, reason: str | None) -> None:
    assert [(f.status, f.reason) for f in stubs.calls("finalise_mission_run")] == [(status, reason)]


def _patch_gate(monkeypatch, decide: Callable[[MissionRunWorkflow, str, str | None], str]) -> None:
    async def _gate(self: MissionRunWorkflow, gate_point: str, task_id: str | None) -> str:
        return decide(self, gate_point, task_id)

    monkeypatch.setattr(MissionRunWorkflow, "_gate", _gate)


def _executed() -> list[str]:
    return [inp.task_id for inp in stubs.calls("execute_plan_task")]


# ── Layers ────────────────────────────────────────────────────────────────


async def test_one_activity_per_task(env: WorkflowEnvironment):
    stubs.SCRIPT.graphs = [graph(["a", "b"], ["c"])]
    stubs.SCRIPT.actions = ["propose_complete"]

    async with _started(env) as handle:
        assert await handle.result() == "succeeded"

    assert sorted(_executed()) == ["a", "b", "c"]
    assert _executed()[-1] == "c"


async def test_parallelism_bounded(env: WorkflowEnvironment):
    stubs.SCRIPT.graphs = [graph(["a", "b", "c", "d", "e"])]
    stubs.SCRIPT.actions = ["propose_complete"]
    stubs.SCRIPT.task_delay_seconds = 0.1

    async with _started(env, max_parallel_tasks=2) as handle:
        assert await handle.result() == "succeeded"

    assert len(_executed()) == 5
    assert stubs.SCRIPT.max_running == 2


async def test_activity_options_from_snapshot(env: WorkflowEnvironment):
    stubs.SCRIPT.graphs = [graph(["a"])]
    stubs.SCRIPT.actions = ["propose_complete"]

    async with _started(env) as handle:
        await handle.result()

    assert stubs.SCRIPT.activity_timeouts == [(timedelta(seconds=60), timedelta(seconds=3600))]


async def test_activity_failure_ends_task_failures(env: WorkflowEnvironment):
    stubs.SCRIPT.graphs = [graph(["a", "b"])]
    stubs.SCRIPT.task_errors = {"a": non_retryable("worker lost the database")}
    stubs.SCRIPT.task_delay_seconds = 0.2

    async with _started(env, max_parallel_tasks=2) as handle:
        assert await handle.result() == "failed"

    _ends("failed", "task_failures")
    names = [name for name, _ in stubs.CALLS]
    assert names.index("execute_plan_task_done") < names.index("finalise_mission_run")
    assert stubs.calls("execute_plan_task_done") == ["b"]
    assert stubs.calls("evaluate_post_run") == []


async def test_supervisor_input_from_task_results(env: WorkflowEnvironment):
    stubs.SCRIPT.graphs = [graph(["a", "b"])]
    stubs.SCRIPT.actions = ["propose_complete"]
    stubs.SCRIPT.task_results = {
        "a": [completed("a", cost_usd=0.5)],
        "b": [failed("b", cost_usd=0.25, reason="boom", fingerprint="f1")],
    }

    async with _started(env) as handle:
        await handle.result()

    [followup] = stubs.calls("fire_supervisor_followups")
    assert followup.wave_status == "failed"
    assert followup.wave_cost_usd == 0.75
    assert followup.failure_reason == "boom"


async def test_refine_prompt_lists_failures(env: WorkflowEnvironment):
    stubs.SCRIPT.graphs = [graph(["a"])]
    stubs.SCRIPT.actions = ["advance_refine", "propose_complete"]
    stubs.SCRIPT.task_results = {"a": [failed("a")]}

    async with _started(env) as handle:
        assert await handle.result() == "succeeded"

    refine_prompt = stubs.calls("start_director_turn")[0].prompt
    assert "[agent/agent_reported_failure] x1 task a: boom" in refine_prompt


# ── verification_failed seam ──────────────────────────────────────────────


async def test_verification_failed_seam_continue_leaves_failed(
    env: WorkflowEnvironment,
):
    stubs.SCRIPT.graphs = [graph(["a"])]
    stubs.SCRIPT.actions = ["propose_complete"]
    stubs.SCRIPT.task_results = {"a": [failed("a", verification_failed=True)]}

    async with _started(env) as handle:
        assert await handle.result() == "succeeded"

    assert stubs.calls("resolve_failed_task") == []
    assert len(stubs.calls("evaluate_post_run")) == 1
    assert stubs.calls("fire_supervisor_followups")[0].wave_status == "failed"


async def test_verification_failed_retry_reruns_once(env: WorkflowEnvironment, monkeypatch):
    _patch_gate(
        monkeypatch,
        lambda _, point, __: "retry" if point == "verification_failed" else "continue",
    )
    stubs.SCRIPT.graphs = [graph(["a"])]
    stubs.SCRIPT.actions = ["propose_complete"]
    stubs.SCRIPT.task_results = {"a": [failed("a", verification_failed=True), completed("a")]}

    async with _started(env) as handle:
        assert await handle.result() == "succeeded"

    assert [(r.task_id, r.action) for r in stubs.calls("resolve_failed_task")] == [("a", "retry")]
    assert _executed() == ["a", "a"]
    assert stubs.calls("fire_supervisor_followups")[0].wave_status == "completed"


async def test_verification_failed_skip(env: WorkflowEnvironment, monkeypatch):
    _patch_gate(
        monkeypatch,
        lambda _, point, __: "skip" if point == "verification_failed" else "continue",
    )
    stubs.SCRIPT.graphs = [graph(["a"])]
    stubs.SCRIPT.actions = ["propose_complete"]
    stubs.SCRIPT.task_results = {"a": [failed("a", verification_failed=True)]}

    async with _started(env) as handle:
        assert await handle.result() == "succeeded"

    assert [(r.task_id, r.action) for r in stubs.calls("resolve_failed_task")] == [("a", "skip")]
    assert _executed() == ["a"]


async def test_skip_clears_failure_fields(env: WorkflowEnvironment, monkeypatch):
    stored: list[ExecuteTaskResult] = []

    def decide(wf: MissionRunWorkflow, point: str, _task_id: str | None) -> str:
        if point == "post_layer":
            stored.extend(wf._wave_results.values())
        return "skip" if point == "verification_failed" else "continue"

    _patch_gate(monkeypatch, decide)
    stubs.SCRIPT.graphs = [graph(["a"])]
    stubs.SCRIPT.actions = ["propose_complete"]
    stubs.SCRIPT.task_results = {"a": [failed("a", verification_failed=True)]}

    async with _started(env) as handle:
        await handle.result()

    [result] = stored
    assert result.status == "skipped"
    assert (
        result.failure_origin,
        result.failure_class,
        result.failure_fingerprint,
    ) == (
        None,
        None,
        None,
    )
    assert stubs.calls("fire_supervisor_followups")[0].failure_reason is None


async def test_gate_abort_cancels_run(env: WorkflowEnvironment, monkeypatch):
    _patch_gate(
        monkeypatch,
        lambda _, point, __: "abort" if point == "post_layer" else "continue",
    )
    stubs.SCRIPT.graphs = [graph(["a"])]

    async with _started(env) as handle:
        assert await handle.result() == "cancelled"

    _ends("cancelled", "gate_rejected")
    assert stubs.calls("finalise_mission_run")[0].detail == "aborted at post_layer"


# ── Durable WAIT and the hard stop ────────────────────────────────────────


async def test_wait_is_durable_and_free(env: WorkflowEnvironment):
    stubs.SCRIPT.graphs = [graph(["a"])]
    stubs.SCRIPT.actions = ["wait", "propose_complete"]

    async with _started(env) as handle:
        await _until(lambda: len(stubs.calls("check_plan_active")) == 1)
        assert (await handle.query(MissionRunWorkflow.get_run_state)).iteration == 1
        await env.sleep(timedelta(hours=3))
        assert len(stubs.calls("fetch_run_task_graph")) == 1
        stubs.CALLS.append(("signal", None))
        await handle.signal(MissionRunWorkflow.tasks_approved, TasksApprovedSignal(["a"]))
        assert await handle.result() == "succeeded"
        state = await handle.query(MissionRunWorkflow.get_run_state)

    names = [name for name, _ in stubs.CALLS]
    fetches = [i for i, name in enumerate(names) if name == "fetch_run_task_graph"]
    assert len(fetches) == 2
    assert fetches[1] > names.index("signal")
    assert state.iteration == 2
    _ends("succeeded", "objective_met")


async def test_signal_during_execution_satisfies_wait(env: WorkflowEnvironment):
    release = asyncio.Event()

    async def hold_first(inp: ExecuteTaskInput) -> None:
        if len(stubs.calls("execute_plan_task")) == 1:
            await release.wait()

    stubs.SCRIPT.graphs = [graph(["a"])]
    stubs.SCRIPT.actions = ["wait", "propose_complete"]
    stubs.SCRIPT.task_hook = hold_first

    async with _started(env) as handle:
        await _until(lambda: len(stubs.calls("execute_plan_task")) == 1)
        await handle.signal(MissionRunWorkflow.tasks_approved, TasksApprovedSignal(["a"]))
        release.set()
        assert await handle.result() == "succeeded"

    assert len(stubs.calls("fetch_run_task_graph")) == 2
    _ends("succeeded", "objective_met")


async def test_wait_times_out_to_max_duration(env: WorkflowEnvironment):
    stubs.SCRIPT.graphs = [graph(["a"])]
    stubs.SCRIPT.actions = ["wait"]

    async with _started(env) as handle:
        assert await handle.result() == "failed"

    _ends("failed", "max_duration_exceeded")
    assert len(stubs.calls("evaluate_post_run")) == 1


async def test_approval_wait_excluded_from_duration(env: WorkflowEnvironment):
    stubs.SCRIPT.graphs = [graph(proposed=1), graph(["a"])]
    stubs.SCRIPT.actions = ["propose_complete"]

    async with _started(env) as handle:
        await _until(lambda: len(stubs.calls("fetch_run_task_graph")) == 1)
        for _ in range(100):
            if (await handle.query(MissionRunWorkflow.get_run_state)).phase == "awaiting_gate":
                break
            await asyncio.sleep(0.02)
        await env.sleep(timedelta(hours=13))
        await handle.signal(MissionRunWorkflow.tasks_approved, TasksApprovedSignal(["a"]))
        assert await handle.result() == "succeeded"

    assert _executed() == ["a"]
    _ends("succeeded", "objective_met")


async def test_duration_exhausted_stops_before_next_chunk(env: WorkflowEnvironment):
    stubs.SCRIPT.graphs = [graph(["a"])]
    state = MissionRunWorkflowState(
        iteration=0,
        session_id=stubs.SESSION_ID,
        execution_record_id=stubs.RECORD_ID,
        context_version_start=0,
        run_started_at=utc_now() - timedelta(hours=13),
        excluded_wait_seconds=0,
        pending_gate=None,
        last_supervisor_action=None,
        approved_seq=0,
        pause_requested=False,
        paused=False,
        decision=None,
        last_can_iteration=0,
    )

    async with _started(env, state=state) as handle:
        assert await handle.result() == "failed"

    assert _executed() == []
    _ends("failed", "max_duration_exceeded")


async def test_no_iteration_cap(env: WorkflowEnvironment):
    stubs.SCRIPT.graphs = [graph(["a"])]
    stubs.SCRIPT.actions = ["advance_approved"] * 40 + ["propose_complete"]

    async with _started(env, continue_as_new_after_iterations=1000) as handle:
        assert await handle.result() == "succeeded"

    _ends("succeeded", "objective_met")
    assert stubs.calls("evaluate_post_run")[-1].supervisor_iteration_count == 40


async def test_zero_completion_waves_counted_per_wave(env: WorkflowEnvironment):
    """One early success, then failing waves: the count the stall rule reads climbs."""
    stubs.SCRIPT.graphs = [graph(["a"])]
    stubs.SCRIPT.actions = ["advance_approved"] * 3 + ["escalate"]
    stubs.SCRIPT.task_results = {"a": [completed("a")] + [failed("a")] * 3}

    async with _started(env) as handle:
        assert await handle.result() == "failed"

    _ends("failed", "supervisor_escalated")
    waves = [inp.zero_completion_waves for inp in stubs.calls("evaluate_post_run")]
    assert waves == [0, 1, 2, 3]


async def test_get_run_state_query(env: WorkflowEnvironment):
    stubs.SCRIPT.graphs = [graph(["a"])]
    stubs.SCRIPT.actions = ["wait", "propose_complete"]

    async with _started(env) as handle:
        await _until(lambda: len(stubs.calls("check_plan_active")) == 1)
        state = await handle.query(MissionRunWorkflow.get_run_state)
        await handle.signal(MissionRunWorkflow.tasks_approved, TasksApprovedSignal(["a"]))
        await handle.result()

    assert state.phase == "supervising"
    assert state.pending_gate_id is None
    assert state.last_supervisor_action == "wait"


# ── Continue-as-new (88.2.7) ──────────────────────────────────────────────


async def _run_ids(env: WorkflowEnvironment, handle: WorkflowHandle) -> list[str]:
    """Every run of the workflow id, oldest first, following the continue-as-new chain."""
    latest = (await env.client.get_workflow_handle(handle.id).describe()).run_id
    chain = [latest]
    while True:
        history = await env.client.get_workflow_handle(handle.id, run_id=chain[0]).fetch_history()
        started = history.events[0].workflow_execution_started_event_attributes
        if not started.continued_execution_run_id:
            return chain
        chain.insert(0, started.continued_execution_run_id)


async def _history_sizes(
    env: WorkflowEnvironment, workflow_id: str, run_ids: list[str]
) -> list[int]:
    sizes = []
    for run_id in run_ids:
        history = await env.client.get_workflow_handle(workflow_id, run_id=run_id).fetch_history()
        sizes.append(len(history.events))
    return sizes


async def test_continue_as_new_every_n(env: WorkflowEnvironment):
    stubs.SCRIPT.graphs = [graph(["a"])]
    stubs.SCRIPT.actions = ["advance_approved"] * 6 + ["propose_complete"]

    async with _started(env, continue_as_new_after_iterations=3) as handle:
        assert await handle.result() == "succeeded"
        run_ids = await _run_ids(env, handle)
        sizes = await _history_sizes(env, handle.id, run_ids)

    assert len(run_ids) == 3  # the run id changed twice
    assert run_ids[0] == handle.first_execution_run_id
    assert all(size < 2000 for size in sizes)
    _ends("succeeded", "objective_met")
    # zero-based, as in test_no_iteration_cap: the seventh evaluation carries 6
    assert [i.supervisor_iteration_count for i in stubs.calls("evaluate_post_run")] == list(
        range(7)
    )
    assert len(stubs.calls("begin_mission_run")) == 1
    assert len(stubs.calls("plan_mission_run")) == 1


async def test_state_carried_across_can(env: WorkflowEnvironment, monkeypatch):
    seen: list[tuple[str, int, object]] = []

    def record(wf: MissionRunWorkflow, point: str, _task_id: str | None) -> str:
        if point == "pre_dispatch":
            seen.append((workflow.info().run_id, wf._approved_seq, wf._state.run_started_at))
        return "continue"

    _patch_gate(monkeypatch, record)
    stubs.SCRIPT.graphs = [graph(["a"])]
    stubs.SCRIPT.actions = ["wait", "propose_complete"]
    stubs.SCRIPT.task_results = {"a": [failed("a"), failed("a")]}

    async with _started(env, continue_as_new_after_iterations=1) as handle:
        await _until(lambda: len(stubs.calls("check_plan_active")) == 1)
        await handle.signal(MissionRunWorkflow.tasks_approved, TasksApprovedSignal(["a"]))
        assert await handle.result() == "succeeded"
        run_ids = await _run_ids(env, handle)

    assert len(run_ids) == 2
    assert _executed() == [
        "a",
        "a",
    ]  # the second run executed a wave with no second signal
    (first_run, seq_1, started_1), (second_run, seq_2, started_2) = seen
    assert (first_run, second_run) == tuple(run_ids)
    assert (seq_1, seq_2) == (0, 1)
    assert started_2 == started_1  # elapsed-time budget carried
    evaluations = stubs.calls("evaluate_post_run")
    assert [i.supervisor_iteration_count for i in evaluations] == [0, 1]
    assert [i.zero_completion_waves for i in evaluations] == [
        1,
        2,
    ]  # stall count carried
    assert len(stubs.calls("begin_mission_run")) == 1
    _ends("succeeded", "objective_met")


async def test_can_does_not_repeat_without_progress(env: WorkflowEnvironment):
    stubs.SCRIPT.graphs = [graph(["a"]), graph(["a"]), graph()]
    stubs.SCRIPT.actions = ["advance_approved", "wait"]

    async with _started(env, continue_as_new_after_iterations=2) as handle:
        await _until(lambda: len(stubs.calls("check_plan_active")) == 2)
        await handle.signal(MissionRunWorkflow.tasks_approved, TasksApprovedSignal(["a"]))
        assert await handle.result() == "succeeded"
        run_ids = await _run_ids(env, handle)

    assert len(run_ids) == 2  # exactly one continue-as-new
    _ends("succeeded", "no_further_work")


async def test_no_can_with_pending_gate(env: WorkflowEnvironment, monkeypatch):
    def open_gate(wf: MissionRunWorkflow, point: str, task_id: str | None) -> str:
        if point == "post_layer":
            wf._state.pending_gate = PendingGate(
                gate_request_id=str(uuid.uuid4()),
                gate_point=point,
                task_id=task_id,
                opened_at=workflow.now(),
                escalated=False,
                timed_out=False,
            )
        return "continue"

    _patch_gate(monkeypatch, open_gate)
    stubs.SCRIPT.graphs = [graph(["a"])]
    stubs.SCRIPT.actions = ["advance_approved", "advance_approved", "propose_complete"]

    async with _started(env, continue_as_new_after_iterations=1) as handle:
        assert await handle.result() == "succeeded"
        run_ids = await _run_ids(env, handle)

    assert run_ids == [handle.first_execution_run_id]
    assert len(stubs.calls("evaluate_post_run")) == 3
    _ends("succeeded", "objective_met")
