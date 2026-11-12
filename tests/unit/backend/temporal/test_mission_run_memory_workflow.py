"""MissionRunWorkflow run-end memory wiring (Plan 88 step 88.3.8, patch p88-run-memory).

A run that reached RUNNING ends compact_mission_context, write_run_digest,
finalise_mission_run, in that order. Compaction failure does not block the
digest; a cancelled run gets a deterministic digest; a run whose begin was
rejected gets neither. Runs the real workflow in a time-skipping Temporal
environment with every activity faked under its real name.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
from temporalio import activity, workflow
from temporalio.client import WorkflowFailureError, WorkflowHandle
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

# The workflow sandbox re-imports this module; pass application imports through.
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
        PlanRunInput,
        PlanRunResult,
        RetrySnapshot,
        RunConfigSnapshot,
        RunTaskGraph,
        SupervisorFollowupInput,
        WriteDigestInput,
    )
    from modules.backend.temporal.mission_run_workflow import MissionRunWorkflow
    from modules.backend.temporal.supervisor_activities import PostRunEvalInput, PostRunEvalResult

_SESSION_ID = "11111111-1111-1111-1111-111111111111"
_RECORD_ID = "22222222-2222-2222-2222-222222222222"
_END = ("compact_mission_context", "write_run_digest", "finalise_mission_run")


@dataclass
class _Fake:
    calls: list[tuple[str, Any]] = field(default_factory=list)
    begin_error: Exception | None = None
    compaction_error: Exception | None = None
    execute_block: bool = False
    execute_started: asyncio.Event = field(default_factory=asyncio.Event)

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def args(self, name: str) -> list[Any]:
        return [arg for called, arg in self.calls if called == name]


_fake = _Fake()


@activity.defn(name="begin_mission_run")
async def begin_fake(inp: BeginRunInput) -> BeginRunResult:
    _fake.calls.append(("begin_mission_run", inp))
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
    return PlanRunResult(task_ids=["t1"], status="planned", detail=None)


@activity.defn(name="fetch_run_task_graph")
async def graph_fake(mission_run_id: str) -> RunTaskGraph:
    return RunTaskGraph(layers=[["t1"]], proposed=0, approved=1, running=0)


@activity.defn(name="execute_plan_task")
async def execute_fake(inp: ExecuteTaskInput) -> ExecuteTaskResult:
    _fake.execute_started.set()
    while _fake.execute_block:
        activity.heartbeat()
        await asyncio.sleep(0.05)
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
    return PostRunEvalResult(action="propose_complete", reason="because")


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
    return "director-turn"


@activity.defn(name="compact_mission_context")
async def compact_fake(inp: CompactContextInput) -> CompactContextResult:
    _fake.calls.append(("compact_mission_context", inp))
    if _fake.compaction_error is not None:
        raise _fake.compaction_error
    return CompactContextResult(compacted=False, from_bytes=0, to_bytes=0)


@activity.defn(name="write_run_digest")
async def digest_fake(inp: WriteDigestInput) -> DigestResult:
    _fake.calls.append(("write_run_digest", inp))
    generator = "deterministic" if inp.force_deterministic else "agent"
    return DigestResult(digest_id=str(uuid.uuid4()), generator=generator)


@activity.defn(name="finalise_mission_run")
async def finalise_fake(inp: FinaliseRunInput) -> FinaliseRunResult:
    _fake.calls.append(("finalise_mission_run", inp))
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
    compact_fake,
    digest_fake,
    finalise_fake,
]


def _input(task_queue: str) -> MissionRunWorkflowInput:
    policy = ActivityPolicySnapshot(
        start_to_close_seconds=30,
        heartbeat_timeout_seconds=None,
        retry=RetrySnapshot(
            initial_interval_seconds=1,
            backoff_coefficient=1.0,
            maximum_interval_seconds=1,
            maximum_attempts=3,
        ),
    )
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
    task_queue = f"mission-run-memory-{uuid.uuid4().hex[:8]}"
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


async def test_end_run_order_compact_digest_finalise(env: WorkflowEnvironment):
    async with _started(env) as handle:
        assert await handle.result() == "succeeded"

    assert tuple(_fake.names()[-3:]) == _END
    (digest,) = _fake.args("write_run_digest")
    assert (digest.status, digest.reason, digest.force_deterministic) == (
        "succeeded",
        "objective_met",
        False,
    )
    (compaction,) = _fake.args("compact_mission_context")
    assert compaction.mission_run_id == digest.mission_run_id


async def test_compaction_failure_does_not_block_digest(env: WorkflowEnvironment):
    _fake.compaction_error = ApplicationError("mcd unavailable", non_retryable=True)

    async with _started(env) as handle:
        assert await handle.result() == "succeeded"

    assert tuple(_fake.names()[-3:]) == _END
    assert len(_fake.args("write_run_digest")) == 1
    assert len(_fake.args("finalise_mission_run")) == 1


async def test_cancel_path_forces_deterministic_digest(env: WorkflowEnvironment):
    _fake.execute_block = True

    async with _started(env) as handle:
        await asyncio.wait_for(_fake.execute_started.wait(), timeout=15)
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await handle.result()

    assert tuple(_fake.names()[-3:]) == _END
    (digest,) = _fake.args("write_run_digest")
    assert (digest.status, digest.force_deterministic) == ("cancelled", True)
    assert [(f.status, f.reason) for f in _fake.args("finalise_mission_run")] == [
        ("cancelled", None)
    ]


async def test_no_digest_when_begin_fails(env: WorkflowEnvironment):
    _fake.begin_error = ApplicationError(
        "owner not a platform user", type="RunStartRejectedError", non_retryable=True
    )

    async with _started(env) as handle:
        assert await handle.result() == "failed"

    assert _fake.args("compact_mission_context") == []
    assert _fake.args("write_run_digest") == []
