"""Plan 88 step 88.4.1: ledger write failures are fatal inside a mission run.

The llm_calls ledger is the budget enforcement source, so a lost row in a
run is a budget bypass: the failure propagates. Outside a run (chat,
in-process paths) the failure is still logged and swallowed. TestModel
stands in for the LLM; record_llm_call is replaced by a failing stub.
"""

import uuid
from types import SimpleNamespace

import pytest
from pydantic_ai import UsageLimits
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from modules.backend.agents.mission_control.helpers import agent_executor as agent_executor_module
from modules.backend.agents.mission_control.helpers.agent_executor import (
    _call_planning_agent,
    _make_agent_executor,
)
from modules.backend.agents.mission_control.models import NoOpEventBus
from modules.backend.agents.mission_control.registry import get_registry
from modules.backend.agents.mission_control.roster import Roster


class _LedgerDown(Exception):
    """The stubbed ledger write failure."""


async def _failing_record(**kwargs) -> None:
    raise _LedgerDown("llm_calls insert failed")


@pytest.fixture(autouse=True)
def _ledger_down(monkeypatch):
    get_registry().reset()
    monkeypatch.setattr(agent_executor_module, "record_llm_call", _failing_record)
    monkeypatch.setattr(
        agent_executor_module, "_build_model", lambda model_ref: TestModel(call_tools=[])
    )
    yield
    get_registry().reset()


async def _execute(mission_run_id: str | None) -> dict:
    executor = _make_agent_executor(
        NoOpEventBus(),
        session_id=str(uuid.uuid4()),
        mission_id=str(uuid.uuid4()),
        mission_run_id=mission_run_id,
    )
    return await executor(
        agent_name="platform.health.agent",
        instructions="check system health",
        inputs={},
        usage_limits=UsageLimits(request_limit=5),
    )


async def test_ledger_failure_propagates_in_run_context():
    with pytest.raises(_LedgerDown):
        await _execute(str(uuid.uuid4()))


async def test_ledger_failure_swallowed_without_run():
    result = await _execute(None)

    assert "output" in result


class _FinalisingPlanner:
    """Planning agent stand-in: finalises an empty plan in one run."""

    _function_toolset = SimpleNamespace(tools={})

    async def run(self, prompt, *, deps, model_settings=None, usage_limits=None):
        deps.build_session.finalised_plan = {"tasks": []}
        return SimpleNamespace(
            usage=lambda: RunUsage(input_tokens=10, output_tokens=5),
            all_messages=lambda: [],
        )


async def test_planning_ledger_failure_propagates_in_run_context(monkeypatch):
    async def _no_trace(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "modules.backend.agents.mission.planning.agent.create_agent",
        lambda model: _FinalisingPlanner(),
    )
    monkeypatch.setattr("modules.backend.core.agent_trace.trace_and_emit", _no_trace)

    with pytest.raises(_LedgerDown):
        await _call_planning_agent(
            "brief",
            Roster(agents=[]),
            None,
            mission_id=str(uuid.uuid4()),
            mission_run_id=str(uuid.uuid4()),
        )
