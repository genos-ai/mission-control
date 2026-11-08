"""MissionRunWorkflow passes the plan gate mode to the supervisor (Plan 88 step 88.0.4).

Runs the real workflow in a time-skipping Temporal environment with stub
activities registered under the real activity names. ``evaluate_post_run``
returns ``escalate``, so the loop ends after one iteration, and the stub
records the ``PostRunEvalInput`` it received.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from temporalio import activity, workflow
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


@activity.defn(name="execute_mission")
async def execute_mission_stub(input: MissionWorkflowInput) -> MissionExecutionResult:
    return MissionExecutionResult(
        mission_id=input.mission_id or input.mission_run_id,
        status="success",
        execution_record_id=str(uuid.uuid4()),
        session_id=input.session_id,
    )


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


@pytest.fixture
async def temporal_env() -> AsyncIterator[WorkflowEnvironment]:
    _captured.clear()
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        async with Worker(
            env.client,
            task_queue=get_app_config().temporal.task_queue,
            workflows=[MissionRunWorkflow],
            activities=[
                execute_mission_stub,
                persist_mission_outcome_stub,
                evaluate_post_run_stub,
                fire_supervisor_followups_stub,
                check_plan_active_stub,
                start_director_turn_stub,
                send_notification_stub,
            ],
        ):
            yield env
    finally:
        await env.shutdown()


async def _run(env: WorkflowEnvironment, gate_mode: str | None) -> dict:
    plan_id = str(uuid.uuid4())
    return await env.client.execute_workflow(
        MissionRunWorkflow.run,
        MissionWorkflowInput(
            mission_run_id=plan_id,
            session_id=str(uuid.uuid4()),
            mission_brief="brief",
            mission_id=str(uuid.uuid4()),
            gate_mode=gate_mode,
        ),
        id=f"mission-run-{plan_id}",
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
