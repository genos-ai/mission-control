"""MissionScheduleTickWorkflow (Plan 88 step 88.1.8, contract 3.3.2).

Runs the real tick workflow in a time-skipping Temporal environment with a fake
claim_occurrence and a stub MissionRunWorkflow child. The test server does not
define TemporalScheduledStartTime, so each environment registers it and the
tests set it on start, as a Temporal Schedule does.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from temporalio import activity, workflow
from temporalio.api.enums.v1 import IndexedValueType
from temporalio.api.operatorservice.v1 import AddSearchAttributesRequest
from temporalio.client import WorkflowFailureError
from temporalio.common import SearchAttributePair, TypedSearchAttributes
from temporalio.exceptions import ApplicationError
from temporalio.service import RPCError, RPCStatusCode
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

# The workflow sandbox re-imports this module; pass application imports through,
# as every workflow module in modules/backend/temporal does.
with workflow.unsafe.imports_passed_through():
    from modules.backend.temporal.mission_run_models import (
        ActivityPolicySnapshot,
        ClaimOccurrenceInput,
        ClaimOccurrenceResult,
        MissionRunWorkflowInput,
        MissionScheduleTickInput,
        RetrySnapshot,
        RunConfigSnapshot,
        TickConfigSnapshot,
    )
    from modules.backend.temporal.mission_schedule_tick_workflow import (
        SCHEDULED_START_TIME,
        MissionScheduleTickWorkflow,
    )
    from modules.backend.temporal.workflow_ids import mission_run_workflow_id

_SCHEDULED_FOR = datetime(2027, 1, 4, 6, 0, tzinfo=UTC)
_claims: list[ClaimOccurrenceInput] = []
_result: list[ClaimOccurrenceResult] = []
_children: list[str] = []


@activity.defn(name="claim_occurrence")
async def claim_fake(inp: ClaimOccurrenceInput) -> ClaimOccurrenceResult:
    _claims.append(inp)
    return _result[0]


@workflow.defn(name="MissionRunWorkflow")
class MissionRunWorkflowStub:
    @workflow.run
    async def run(self, inp: MissionRunWorkflowInput) -> str:
        return inp.mission_run_id


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


def _run_input(run_id: str, task_queue: str) -> MissionRunWorkflowInput:
    policy = _policy()
    return MissionRunWorkflowInput(
        mission_run_id=run_id,
        mission_id=str(uuid.uuid4()),
        plan_id=str(uuid.uuid4()),
        config=RunConfigSnapshot(
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
        ),
    )


@pytest.fixture
async def env() -> AsyncIterator[WorkflowEnvironment]:
    _claims.clear()
    _result.clear()
    _children.clear()
    environment = await WorkflowEnvironment.start_time_skipping()
    try:
        await environment.client.operator_service.add_search_attributes(
            AddSearchAttributesRequest(
                namespace=environment.client.namespace,
                search_attributes={
                    SCHEDULED_START_TIME.name: IndexedValueType.INDEXED_VALUE_TYPE_DATETIME
                },
            )
        )
        yield environment
    finally:
        await environment.shutdown()


@pytest.fixture
def task_queue() -> str:
    return f"mission-tick-test-{uuid.uuid4().hex[:8]}"


async def _tick(env: WorkflowEnvironment, task_queue: str, *, scheduled: bool = True) -> str:
    inp = MissionScheduleTickInput(
        mission_schedule_id=str(uuid.uuid4()),
        config=TickConfigSnapshot(
            config_hash="test", task_queue=task_queue, claim=_policy(), notify=_policy()
        ),
    )
    attributes = (
        TypedSearchAttributes([SearchAttributePair(SCHEDULED_START_TIME, _SCHEDULED_FOR)])
        if scheduled
        else TypedSearchAttributes.empty
    )
    async with Worker(
        env.client,
        task_queue=task_queue,
        workflows=[MissionScheduleTickWorkflow, MissionRunWorkflowStub],
        activities=[claim_fake],
    ):
        return await env.client.execute_workflow(
            MissionScheduleTickWorkflow.run,
            inp,
            id=f"mission-tick-{inp.mission_schedule_id}",
            task_queue=task_queue,
            search_attributes=attributes,
        )


async def _child_result(env: WorkflowEnvironment, run_id: str) -> str:
    return await env.client.get_workflow_handle(mission_run_workflow_id(run_id)).result()


async def test_missing_scheduled_time_fails_non_retryable(
    env: WorkflowEnvironment, task_queue: str
):
    with pytest.raises(WorkflowFailureError) as exc_info:
        await _tick(env, task_queue, scheduled=False)

    cause = exc_info.value.cause
    assert isinstance(cause, ApplicationError)
    assert cause.message == "NO_SCHEDULED_TIME"
    assert cause.non_retryable
    assert _claims == []


async def test_run_outcome_starts_child_with_run_id(env: WorkflowEnvironment, task_queue: str):
    run_id = str(uuid.uuid4())
    _result.append(
        ClaimOccurrenceResult(
            outcome="run",
            mission_run_id=run_id,
            run_input=_run_input(run_id, task_queue),
            notifications=[],
        )
    )

    assert await _tick(env, task_queue) == "run"

    assert _claims[0].scheduled_for == _SCHEDULED_FOR
    assert await _child_result(env, run_id) == run_id


async def test_duplicate_pending_starts_child(env: WorkflowEnvironment, task_queue: str):
    run_id = str(uuid.uuid4())
    _result.append(
        ClaimOccurrenceResult(
            outcome="duplicate",
            mission_run_id=run_id,
            run_input=_run_input(run_id, task_queue),
            notifications=[],
        )
    )

    assert await _tick(env, task_queue) == "duplicate"

    assert await _child_result(env, run_id) == run_id


async def test_skipped_outcome_starts_nothing(env: WorkflowEnvironment, task_queue: str):
    run_id = str(uuid.uuid4())
    _result.append(
        ClaimOccurrenceResult(
            outcome="skipped", mission_run_id=run_id, run_input=None, notifications=[]
        )
    )

    assert await _tick(env, task_queue) == "skipped"

    with pytest.raises(RPCError) as exc_info:
        await env.client.get_workflow_handle(mission_run_workflow_id(run_id)).describe()
    assert exc_info.value.status == RPCStatusCode.NOT_FOUND


async def test_child_already_started_is_success(env: WorkflowEnvironment, task_queue: str):
    run_id = str(uuid.uuid4())
    async with Worker(env.client, task_queue=task_queue, workflows=[MissionRunWorkflowStub]):
        first = await env.client.start_workflow(
            MissionRunWorkflowStub.run,
            _run_input(run_id, task_queue),
            id=mission_run_workflow_id(run_id),
            task_queue=task_queue,
        )
        await first.result()
    _result.append(
        ClaimOccurrenceResult(
            outcome="run",
            mission_run_id=run_id,
            run_input=_run_input(run_id, task_queue),
            notifications=[],
        )
    )

    assert await _tick(env, task_queue) == "run"
    described = await env.client.get_workflow_handle(mission_run_workflow_id(run_id)).describe()
    assert described.run_id == first.result_run_id
