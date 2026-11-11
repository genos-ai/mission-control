"""Record the MissionRunWorkflow replay fixtures (Plan 88 step 88.2.9).

Skipped unless pytest runs with --record-histories. Each test drives one
scenario through the real workflow with the stub activities in
mission_run_stubs, in a time-skipping Temporal environment, then writes the
redacted history of each run to tests/fixtures/temporal_histories/mission_run.

    pytest tests/integration/backend/temporal/test_record_mission_run_histories.py \
        --record-histories -q
"""

import asyncio
import dataclasses
import json
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError, WorkflowHandle
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from modules.backend.core.config import find_project_root
from modules.backend.temporal.config_snapshots import build_run_config_snapshot
from modules.backend.temporal.history_redaction import redact_history
from modules.backend.temporal.mission_run_models import (
    ExecuteTaskInput,
    MissionRunWorkflowInput,
    TasksApprovedSignal,
)
from modules.backend.temporal.mission_run_workflow import MissionRunWorkflow
from tests.integration.backend.temporal import mission_run_stubs as stubs
from tests.integration.backend.temporal.mission_run_stubs import completed, failed, graph

HISTORY_DIR = find_project_root() / Path("tests/fixtures/temporal_histories/mission_run")


@pytest.fixture(autouse=True)
def _record_only(request: pytest.FixtureRequest) -> None:
    if not request.config.getoption("--record-histories"):
        pytest.skip("pass --record-histories to regenerate fixtures")


@pytest.fixture
async def env() -> AsyncIterator[WorkflowEnvironment]:
    stubs.reset()
    environment = await WorkflowEnvironment.start_time_skipping()
    try:
        yield environment
    finally:
        await environment.shutdown()


@asynccontextmanager
async def _started(env: WorkflowEnvironment, **config) -> AsyncIterator[WorkflowHandle]:
    task_queue = f"mission-run-record-{uuid.uuid4().hex[:8]}"
    snapshot = dataclasses.replace(build_run_config_snapshot(), task_queue=task_queue, **config)
    inp = MissionRunWorkflowInput(
        mission_run_id=str(uuid.uuid4()),
        mission_id=str(uuid.uuid4()),
        plan_id=str(uuid.uuid4()),
        config=snapshot,
    )
    async with Worker(
        env.client,
        task_queue=task_queue,
        workflows=[MissionRunWorkflow],
        activities=stubs.ACTIVITIES,
        max_heartbeat_throttle_interval=timedelta(milliseconds=200),
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


async def _write(env: WorkflowEnvironment, name: str, workflow_id: str, run_id: str) -> None:
    history = await env.client.get_workflow_handle(workflow_id, run_id=run_id).fetch_history()
    redacted = redact_history(json.loads(history.to_json()))
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    (HISTORY_DIR / f"{name}.json").write_text(json.dumps(redacted, indent=2) + "\n")


async def test_two_layer_success(env: WorkflowEnvironment):
    stubs.SCRIPT.graphs = [graph(["a", "b"], ["c"])]
    stubs.SCRIPT.actions = ["propose_complete"]

    async with _started(env) as handle:
        assert await handle.result() == "succeeded"
        await _write(env, "two_layer_success", handle.id, handle.result_run_id)


async def test_wait_then_signal(env: WorkflowEnvironment):
    stubs.SCRIPT.graphs = [graph(["a"])]
    stubs.SCRIPT.actions = ["wait", "propose_complete"]

    async with _started(env) as handle:
        await _until(lambda: len(stubs.calls("check_plan_active")) == 1)
        await handle.signal(MissionRunWorkflow.tasks_approved, TasksApprovedSignal(["a"]))
        assert await handle.result() == "succeeded"
        await _write(env, "wait_then_signal", handle.id, handle.result_run_id)


async def test_continue_as_new(env: WorkflowEnvironment):
    """Failing waves first, so the carried state has a non-zero zero_completion_waves."""
    stubs.SCRIPT.graphs = [graph(["a"])]
    stubs.SCRIPT.actions = ["advance_approved", "advance_approved", "propose_complete"]
    stubs.SCRIPT.task_results = {"a": [failed("a"), failed("a"), completed("a")]}

    async with _started(env, continue_as_new_after_iterations=2) as handle:
        assert await handle.result() == "succeeded"
        run_ids = await _run_ids(env, handle)
        assert len(run_ids) == 2
        await _write(env, "can_first_run", handle.id, run_ids[0])
        await _write(env, "can_carried_state_run", handle.id, run_ids[1])

    assert [i.zero_completion_waves for i in stubs.calls("evaluate_post_run")] == [1, 2, 0]


async def test_verification_failed_continue(env: WorkflowEnvironment):
    stubs.SCRIPT.graphs = [graph(["a"])]
    stubs.SCRIPT.actions = ["propose_complete"]
    stubs.SCRIPT.task_results = {"a": [failed("a", verification_failed=True)]}

    async with _started(env) as handle:
        assert await handle.result() == "succeeded"
        await _write(env, "verification_failed_continue", handle.id, handle.result_run_id)

    assert stubs.calls("resolve_failed_task") == []


async def test_cancelled_mid_layer(env: WorkflowEnvironment):
    async def heartbeat_until_cancelled(_inp: ExecuteTaskInput) -> None:
        while True:
            activity.heartbeat()
            await asyncio.sleep(0.05)

    stubs.SCRIPT.graphs = [graph(["a"])]
    stubs.SCRIPT.task_hook = heartbeat_until_cancelled

    async with _started(env) as handle:
        await _until(lambda: len(stubs.calls("execute_plan_task")) == 1)
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await handle.result()
        await _write(env, "cancelled_mid_layer", handle.id, handle.first_execution_run_id)

    assert [(f.status, f.reason) for f in stubs.calls("finalise_mission_run")] == [
        ("cancelled", None)
    ]


async def test_max_duration_stop(env: WorkflowEnvironment):
    stubs.SCRIPT.graphs = [graph(["a"])]
    stubs.SCRIPT.actions = ["wait"]

    async with _started(env) as handle:
        assert await handle.result() == "failed"
        await _write(env, "max_duration_stop", handle.id, handle.result_run_id)

    assert [(f.status, f.reason) for f in stubs.calls("finalise_mission_run")] == [
        ("failed", "max_duration_exceeded")
    ]
