"""execute_plan_task with a task stopped by its budget share (Plan 88 step 88.4.6).

The executor guard raises BudgetExceededError; the 88.2.3b machinery classifies
it as CONTROL/BUDGET_EXCEEDED, which is never retryable, so the agent is called
once, the failed TaskResult is recorded and the activity returns a failed
result instead of raising: Temporal never retries the task. The real
run_single_task runs on a stub runtime; the DB, Redis and the bus are patched.
"""

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.testing import ActivityEnvironment

from modules.backend.agents.mission_control.roster import (
    Roster,
    RosterAgentEntry,
    RosterConstraintsSchema,
    RosterInterfaceSchema,
    RosterModelSchema,
)
from modules.backend.agents.mission_control.runtime import DispatchRuntime
from modules.backend.core.exceptions import BudgetExceededError
from modules.backend.schemas.task_plan import TaskDefinition
from modules.backend.services.run_task_execution import TaskClaim
from modules.backend.temporal.mission_run_models import (
    ExecuteTaskInput,
    ExecuteTaskResult,
)
from modules.backend.temporal.task_activities import execute_plan_task

_MOD = "modules.backend.temporal.task_activities"
MISSION_ID = str(uuid.uuid4())
RUN_ID = str(uuid.uuid4())
TASK_ID = "t1"


def _runtime(execute_agent_fn) -> DispatchRuntime:
    entry = RosterAgentEntry(
        agent_name="agent_a",
        agent_version="1.0.0",
        description="Agent a",
        model=RosterModelSchema(name="anthropic:claude-sonnet-5"),
        interface=RosterInterfaceSchema(input={"query": "string"}, output={"result": "string"}),
        constraints=RosterConstraintsSchema(
            timeout_seconds=10, cost_ceiling_usd=1.0, retry_budget=3
        ),
    )
    return DispatchRuntime(
        roster=Roster(agents=[entry]),
        execute_agent_fn=execute_agent_fn,
        context_curator=None,
        context_assembler=None,
        environment_handle=None,
        mission_run_id=RUN_ID,
    )


def _task() -> TaskDefinition:
    return TaskDefinition.model_validate(
        {
            "task_id": TASK_ID,
            "agent": "agent_a",
            "agent_version": "1.0.0",
            "description": "Test",
            "instructions": "Do it",
            "inputs": {"static": {}, "from_upstream": {}},
            "dependencies": [],
        }
    )


def _recorded(**kwargs) -> ExecuteTaskResult:
    """What RunTaskExecutionService.record returns for the stored TaskResult."""
    failure = kwargs["task_result_json"]["failure"]
    return ExecuteTaskResult(
        task_id=kwargs["task_id"],
        status="failed",
        verification_failed=False,
        cost_usd=0.0,
        idempotent_replay=False,
        failure_reason=failure["summary"],
        failure_origin=failure["origin"],
        failure_class=failure["failure_class"],
        failure_fingerprint=failure["fingerprint"],
    )


async def test_budget_exceeded_marks_task_failed_without_retry():
    calls: list[str] = []

    async def _exhausted(agent_name, instructions, inputs, usage_limits):
        calls.append(agent_name)
        raise BudgetExceededError("task headroom 0.5000 exhausted")

    @asynccontextmanager
    async def _session():
        yield SimpleNamespace()

    claim = TaskClaim(
        outcome="execute",
        idempotency_key=f"{RUN_ID}:{TASK_ID}:0",
        task_definition=_task(),
        stored=None,
        mission_id=MISSION_ID,
        execution_mode="local",
        mission_repo_root=None,
    )
    svc = MagicMock(claim=AsyncMock(return_value=claim), record=AsyncMock(side_effect=_recorded))
    build = AsyncMock(return_value=_runtime(_exhausted))
    with (
        patch(f"{_MOD}.CopilotModel.ensure_healthy", AsyncMock()),
        patch(f"{_MOD}.get_async_session", _session),
        patch(f"{_MOD}.RunTaskExecutionService", return_value=svc),
        patch(f"{_MOD}.AsyncRedis.from_url", return_value=MagicMock(aclose=AsyncMock())),
        patch(f"{_MOD}.get_redis_url", return_value="redis://test"),
        patch(f"{_MOD}.SessionEventBus", return_value=MagicMock(publish=AsyncMock())),
        patch(f"{_MOD}.build_dispatch_runtime", build),
        patch(f"{_MOD}.load_dependency_outputs", AsyncMock(return_value={})),
    ):
        result = await ActivityEnvironment().run(
            execute_plan_task,
            ExecuteTaskInput(
                mission_run_id=RUN_ID,
                task_id=TASK_ID,
                session_id=str(uuid.uuid4()),
                execution_record_id="rec-1",
                budget_headroom_usd=0.5,
                heartbeat_interval_seconds=60,
            ),
        )

    assert calls == ["agent_a"]  # retry_budget=3, yet one attempt: never retryable
    assert build.await_args.kwargs["budget_headroom_usd"] == 0.5
    stored = svc.record.await_args.kwargs["task_result_json"]
    assert stored["status"] == "failed"
    assert stored["failure"]["origin"] == "control"
    assert stored["failure"]["failure_class"] == "budget_exceeded"
    assert stored["failure"]["retryable"] is False
    assert result.status == "failed"
    assert result.failure_origin == "control"
    assert result.failure_class == "budget_exceeded"
    assert result.failure_reason == "budget_exceeded"
