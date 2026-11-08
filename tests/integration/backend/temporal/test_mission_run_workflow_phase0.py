"""MissionRunWorkflow Phase 0 behaviour (Plan 88 steps 88.0.4 and 88.0.8).

Runs the real workflow in a time-skipping Temporal environment with stub
activities registered under the real activity names. ``evaluate_post_run``
returns ``escalate``, so the loop ends after one iteration, and the stub
records the ``PostRunEvalInput`` it received. 88.0.8 adds cancellation
delivery into ``execute_mission`` and its budget-independent timeouts.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from temporalio import activity, workflow
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowExecutionStatus, WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

# The workflow sandbox re-imports this module; pass application imports through,
# as every workflow module in modules/backend/temporal does.
with workflow.unsafe.imports_passed_through():
    from modules.backend.core.config import get_app_config
    from modules.backend.temporal.mission_run_workflow import MissionRunWorkflow
    from modules.backend.temporal.models import (
        MissionExecutionResult,
        MissionWorkflowInput,
        NotificationPayload,
    )
    from modules.backend.temporal.supervisor_activities import (
        PostRunEvalInput,
        PostRunEvalResult,
    )

_captured: list[PostRunEvalInput] = []
_execute_events: list[str] = []


@activity.defn(name="execute_mission")
async def execute_mission_stub(input: MissionWorkflowInput) -> MissionExecutionResult:
    return MissionExecutionResult(
        mission_id=input.mission_id or input.mission_run_id,
        status="success",
        execution_record_id=str(uuid.uuid4()),
        session_id=input.session_id,
    )


@activity.defn(name="execute_mission")
async def execute_mission_heartbeat_stub(input: MissionWorkflowInput) -> MissionExecutionResult:
    _execute_events.append("started")
    try:
        while True:
            activity.heartbeat({"phase": "dispatch"})
            await asyncio.sleep(0.1)
    except asyncio.CancelledError:
        _execute_events.append("cancelled")
        raise


@activity.defn(name="persist_mission_outcome")
async def persist_mission_outcome_stub(
    mission_run_id: str,
    session_id: str,
    roster_name: str,
    outcome_json: dict,
    mission_id: str | None,
) -> None:
    return None


@activity.defn(name="evaluate_post_run")
async def evaluate_post_run_stub(input: PostRunEvalInput) -> PostRunEvalResult:
    _captured.append(input)
    return PostRunEvalResult(action="escalate", reason="stub")


@activity.defn(name="fire_supervisor_followups")
async def fire_supervisor_followups_stub(*args: object) -> None:
    return None


@activity.defn(name="check_plan_active")
async def check_plan_active_stub(mission_id: str) -> bool:
    return True


@activity.defn(name="start_director_turn")
async def start_director_turn_stub(*args: object) -> None:
    return None


@activity.defn(name="send_notification")
async def send_notification_stub(payload: NotificationPayload) -> bool:
    return True


@asynccontextmanager
async def _worker(env: WorkflowEnvironment, execute_stub=execute_mission_stub, **kwargs):
    async with Worker(
        env.client,
        task_queue=get_app_config().temporal.task_queue,
        workflows=[MissionRunWorkflow],
        activities=[
            execute_stub,
            persist_mission_outcome_stub,
            evaluate_post_run_stub,
            fire_supervisor_followups_stub,
            check_plan_active_stub,
            start_director_turn_stub,
            send_notification_stub,
        ],
        **kwargs,
    ):
        yield


@pytest.fixture
async def bare_env() -> AsyncIterator[WorkflowEnvironment]:
    _captured.clear()
    _execute_events.clear()
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        yield env
    finally:
        await env.shutdown()


@pytest.fixture
async def temporal_env(bare_env: WorkflowEnvironment) -> AsyncIterator[WorkflowEnvironment]:
    async with _worker(bare_env):
        yield bare_env


def _input(gate_mode: str | None = "manual", budget: float = 10.0) -> MissionWorkflowInput:
    return MissionWorkflowInput(
        mission_run_id=str(uuid.uuid4()),
        session_id=str(uuid.uuid4()),
        mission_brief="brief",
        mission_id=str(uuid.uuid4()),
        mission_budget_usd=budget,
        gate_mode=gate_mode,
    )


async def _run(env: WorkflowEnvironment, gate_mode: str | None) -> dict:
    wf_input = _input(gate_mode)
    return await env.client.execute_workflow(
        MissionRunWorkflow.run,
        wf_input,
        id=f"mission-run-{wf_input.mission_run_id}",
        task_queue=get_app_config().temporal.task_queue,
    )


async def test_supervisor_receives_input_gate_mode(temporal_env: WorkflowEnvironment):
    result = await _run(temporal_env, "manual")

    assert result["last_action"] == "escalate"
    assert len(_captured) == 1
    assert _captured[0].gate_mode == "manual"


async def test_supervisor_receives_manual_when_gate_mode_missing(
    temporal_env: WorkflowEnvironment,
):
    result = await _run(temporal_env, None)

    assert result["last_action"] == "escalate"
    assert len(_captured) == 1
    assert _captured[0].gate_mode == "manual"


async def test_cancel_reaches_execute_mission(bare_env: WorkflowEnvironment):
    async with _worker(
        bare_env,
        execute_mission_heartbeat_stub,
        max_heartbeat_throttle_interval=timedelta(milliseconds=200),
        default_heartbeat_throttle_interval=timedelta(milliseconds=200),
    ):
        with bare_env.auto_time_skipping_disabled():
            wf_input = _input()
            handle = await bare_env.client.start_workflow(
                MissionRunWorkflow.run,
                wf_input,
                id=f"mission-run-{wf_input.mission_run_id}",
                task_queue=get_app_config().temporal.task_queue,
            )
            for _ in range(100):
                if _execute_events:
                    break
                await asyncio.sleep(0.05)
            assert _execute_events == ["started"]

            await handle.cancel()
            with pytest.raises(WorkflowFailureError):
                await handle.result()

            assert _execute_events == ["started", "cancelled"]
            assert (await handle.describe()).status == WorkflowExecutionStatus.CANCELED


@pytest.mark.parametrize("budget", [0.01, 1000])
async def test_execute_timeout_independent_of_budget(
    temporal_env: WorkflowEnvironment, budget: float
):
    wf_input = _input(budget=budget)
    handle = await temporal_env.client.start_workflow(
        MissionRunWorkflow.run,
        wf_input,
        id=f"mission-run-{wf_input.mission_run_id}",
        task_queue=get_app_config().temporal.task_queue,
    )
    await handle.result()

    scheduled = [
        event.activity_task_scheduled_event_attributes
        async for event in handle.fetch_history_events()
        if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
        and event.activity_task_scheduled_event_attributes.activity_type.name == "execute_mission"
    ]
    assert len(scheduled) == 1
    assert scheduled[0].start_to_close_timeout.ToTimedelta() == timedelta(seconds=3600)
    assert scheduled[0].heartbeat_timeout.ToTimedelta() == timedelta(seconds=60)
