"""ScheduledMissionCheckWorkflow shares the MissionRunWorkflow id (Plan 88 step 88.0.3).

Runs the real check workflow in a time-skipping Temporal environment with a
stub ``find_ready_plans`` activity and a stub ``MissionRunWorkflow`` that
waits on a signal, so the child stays open across both checks. Automatic
time skipping is disabled while a check runs: otherwise the test server skips
to the stub child's execution timeout and closes it before the assertions.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from temporalio import activity, workflow
from temporalio.client import Client, WorkflowExecutionStatus, WorkflowHandle
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

# The workflow sandbox re-imports this module; pass application imports through,
# as every workflow module in modules/backend/temporal does.
with workflow.unsafe.imports_passed_through():
    from modules.backend.core.config import get_app_config
    from modules.backend.temporal.scheduled_workflow import ScheduledMissionCheckWorkflow

PLAN_ID = str(uuid.uuid4())
MISSION_ID = str(uuid.uuid4())


@activity.defn(name="find_ready_plans")
async def find_ready_plans_stub() -> list[dict]:
    return [
        {
            "plan_id": PLAN_ID,
            "mission_id": MISSION_ID,
            "brief": "brief",
            "budget": 5.0,
            "gate_mode": "autonomous",
            "roster": "default",
            "owner_id": "",
        }
    ]


@workflow.defn(name="MissionRunWorkflow")
class MissionRunWorkflowStub:
    def __init__(self) -> None:
        self._released = False

    @workflow.run
    async def run(self, input_data: dict) -> str:
        await workflow.wait_condition(lambda: self._released)
        return "released"

    @workflow.signal
    def release(self) -> None:
        self._released = True


@pytest.fixture
async def temporal_env() -> AsyncIterator[WorkflowEnvironment]:
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        task_queue = get_app_config().temporal.task_queue
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ScheduledMissionCheckWorkflow, MissionRunWorkflowStub],
            activities=[find_ready_plans_stub],
        ):
            yield env
    finally:
        await env.shutdown()


async def _run_check(env: WorkflowEnvironment) -> dict:
    with env.auto_time_skipping_disabled():
        return await env.client.execute_workflow(
            ScheduledMissionCheckWorkflow.run,
            id=f"scheduled-check-{uuid.uuid4().hex}",
            task_queue=get_app_config().temporal.task_queue,
        )


def _child(client: Client) -> WorkflowHandle:
    return client.get_workflow_handle(f"mission-run-{PLAN_ID}")


async def test_child_started_with_shared_id(temporal_env: WorkflowEnvironment):
    result = await _run_check(temporal_env)

    assert result["dispatched"] == 1
    child = _child(temporal_env.client)
    description = await child.describe()
    assert description.status == WorkflowExecutionStatus.RUNNING
    await child.signal(MissionRunWorkflowStub.release)


async def test_second_check_does_not_start_duplicate(temporal_env: WorkflowEnvironment):
    first = await _run_check(temporal_env)
    child = _child(temporal_env.client)
    first_run_id = (await child.describe()).run_id

    second = await _run_check(temporal_env)

    assert first["dispatched"] == 1
    assert second["dispatched"] == 0
    # Exactly one child: the open execution is still the first run.
    description = await child.describe()
    assert description.status == WorkflowExecutionStatus.RUNNING
    assert description.run_id == first_run_id
    await child.signal(MissionRunWorkflowStub.release)
