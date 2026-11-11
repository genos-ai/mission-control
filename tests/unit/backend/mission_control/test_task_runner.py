"""Tests for run_single_task, the per-task unit shared by both dispatch paths (Plan 88, 88.2.3)."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.backend.agents.mission_control.dispatch import task_runner
from modules.backend.agents.mission_control.dispatch.task_runner import run_single_task
from modules.backend.agents.mission_control.outcome import TaskResult, TaskStatus, TaskTokenUsage
from modules.backend.agents.mission_control.roster import (
    Roster,
    RosterAgentEntry,
    RosterConstraintsSchema,
    RosterInterfaceSchema,
    RosterModelSchema,
)
from modules.backend.agents.mission_control.runtime import DispatchRuntime
from modules.backend.core.protocols import NoOpEventBus
from modules.backend.schemas.task_failure import FailureClass
from modules.backend.schemas.task_plan import TaskDefinition


def _entry(name: str) -> RosterAgentEntry:
    return RosterAgentEntry(
        agent_name=name,
        agent_version="1.0.0",
        description=f"Agent {name}",
        model=RosterModelSchema(name="test-model"),
        interface=RosterInterfaceSchema(
            input={"query": "string"}, output={"result": "string", "confidence": "float"}
        ),
        constraints=RosterConstraintsSchema(
            timeout_seconds=10, cost_ceiling_usd=1.0, retry_budget=0
        ),
    )


def _task(agent: str = "agent_a", inputs: dict | None = None) -> TaskDefinition:
    return TaskDefinition.model_validate(
        {
            "task_id": "t1",
            "agent": agent,
            "agent_version": "1.0.0",
            "description": "Test",
            "instructions": "Do it",
            "inputs": inputs or {"static": {}, "from_upstream": {}},
            "dependencies": [],
            "verification": {
                "tier_1": {"schema_validation": True, "required_output_fields": ["result"]},
                "tier_2": {"deterministic_checks": []},
                "tier_3": {"requires_ai_evaluation": False},
            },
        }
    )


def _runtime(execute_agent_fn=None, curator=None) -> DispatchRuntime:
    async def _default_execute(agent_name, instructions, inputs, usage_limits):
        return {"result": "done", "confidence": 0.9, "_meta": {}}

    return DispatchRuntime(
        roster=Roster(agents=[_entry("agent_a")]),
        execute_agent_fn=execute_agent_fn or _default_execute,
        context_curator=curator,
        context_assembler=None,
        environment_handle=None,
    )


class _CapturingBus:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


async def _run(
    task: TaskDefinition, runtime: DispatchRuntime, upstream=None, bus=None
) -> TaskResult:
    return await run_single_task(
        task=task,
        runtime=runtime,
        upstream_outputs=upstream or {},
        mission_id="mission-1",
        budget_usd=10.0,
        event_bus=bus or NoOpEventBus(),
        session_id=str(uuid.uuid4()),
        gate=None,
        project_context=None,
    )


def _routed_result(agent_name: str) -> TaskResult:
    return TaskResult(
        task_id="t1",
        agent_name=agent_name,
        status=TaskStatus.SUCCESS,
        output_reference={"result": "routed"},
        cost_usd=0.0,
        token_usage=TaskTokenUsage(),
    )


@pytest.mark.asyncio
async def test_standard_task_calls_executor_once():
    execute = AsyncMock(return_value={"result": "done", "confidence": 0.9, "_meta": {}})

    result = await _run(_task(), _runtime(execute_agent_fn=execute))

    assert result.status == TaskStatus.SUCCESS
    execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_roster_miss_returns_failed_result():
    execute = AsyncMock()
    bus = _CapturingBus()

    result = await _run(_task(agent="unknown_agent"), _runtime(execute_agent_fn=execute), bus=bus)

    assert result.status == TaskStatus.FAILED
    assert result.failure.failure_class is FailureClass.PLATFORM_DEFECT
    assert any(result.failure.summary in e.narrative for e in bus.events)
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_upstream_returns_failed_result():
    task = _task(
        inputs={
            "static": {},
            "from_upstream": {"data": {"source_task": "absent", "source_field": "result"}},
        }
    )
    execute = AsyncMock()

    result = await _run(task, _runtime(execute_agent_fn=execute))

    assert result.status == TaskStatus.FAILED
    assert result.failure.failure_class is FailureClass.UPSTREAM_BLOCKED
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_research_loop_routed(monkeypatch):
    routed = AsyncMock(return_value=_routed_result("research"))
    monkeypatch.setattr(task_runner, "_dispatch_research_loop", routed)
    task = _task(inputs={"static": {"type": "research_loop"}, "from_upstream": {}})

    result = await _run(task, _runtime())

    routed.assert_awaited_once()
    assert result.agent_name == "research"


@pytest.mark.asyncio
async def test_workflow_agent_routed(monkeypatch):
    routed = AsyncMock(return_value=_routed_result("workflow:x"))
    monkeypatch.setattr(task_runner, "_dispatch_workflow_task", routed)

    result = await _run(_task(agent="workflow:x"), _runtime())

    routed.assert_awaited_once()
    assert routed.await_args.kwargs["workflow_name"] == "x"
    assert result.agent_name == "workflow:x"


@pytest.mark.asyncio
async def test_no_mcd_write():
    curator = MagicMock()
    curator.apply_task_updates = AsyncMock(return_value=(1, []))

    async def _execute(agent_name, instructions, inputs, usage_limits):
        return {
            "result": "done",
            "confidence": 0.9,
            "context_updates": [{"op": "add", "path": "/decisions/-", "value": "x"}],
            "_meta": {},
        }

    result = await _run(_task(), _runtime(execute_agent_fn=_execute, curator=curator))

    assert result.status == TaskStatus.SUCCESS
    curator.apply_task_updates.assert_not_called()
