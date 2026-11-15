"""Plan 88 step 88.4.6: the agent executor enforces the task's budget headroom.

A call is refused once the executor's spend reaches its headroom, and a call
that crosses it raises after its ledger row is written, so the overshoot is
at most one LLM call. Zero headroom refuses the first call: it never means
unlimited. TestModel stands in for the LLM; the ledger write and the cost
function are stubbed.
"""

import uuid

import pytest
from pydantic_ai import UsageLimits
from pydantic_ai.models.test import TestModel

from modules.backend.agents.mission_control.helpers import agent_executor as agent_executor_module
from modules.backend.agents.mission_control.helpers.agent_executor import (
    _make_agent_executor,
)
from modules.backend.agents.mission_control.models import NoOpEventBus
from modules.backend.agents.mission_control.registry import get_registry
from modules.backend.core.exceptions import BudgetExceededError

_CALL_COST_USD = 0.6


@pytest.fixture
def ledger(monkeypatch) -> list[dict]:
    rows: list[dict] = []

    async def _record(**kwargs) -> None:
        rows.append(kwargs)

    get_registry().reset()
    monkeypatch.setattr(agent_executor_module, "record_llm_call", _record)
    monkeypatch.setattr(
        agent_executor_module,
        "_build_model",
        lambda model_ref: TestModel(call_tools=[]),
    )
    monkeypatch.setattr(
        agent_executor_module,
        "compute_cost_usd",
        lambda *args, **kwargs: _CALL_COST_USD,
    )
    yield rows
    get_registry().reset()


def _executor(headroom: float | None):
    return _make_agent_executor(
        NoOpEventBus(),
        session_id=str(uuid.uuid4()),
        mission_id=str(uuid.uuid4()),
        mission_run_id=str(uuid.uuid4()),
        task_id=str(uuid.uuid4()),
        budget_headroom_usd=headroom,
    )


async def _call(executor) -> dict:
    return await executor(
        agent_name="platform.health.agent",
        instructions="check system health",
        inputs={},
        usage_limits=UsageLimits(request_limit=5),
    )


async def test_raises_before_call_when_headroom_exhausted(ledger):
    with pytest.raises(BudgetExceededError, match="task headroom 0.0000 exhausted"):
        await _call(_executor(0.0))

    assert ledger == []


async def test_raises_after_call_that_crosses_headroom_and_row_recorded(ledger):
    executor = _executor(0.5)

    with pytest.raises(BudgetExceededError):
        await _call(executor)
    assert [row["cost_usd"] for row in ledger] == [_CALL_COST_USD]

    with pytest.raises(BudgetExceededError):
        await _call(executor)  # refused before the model is called: no second row
    assert len(ledger) == 1


async def test_no_headroom_means_no_run_budget(ledger):
    executor = _executor(None)

    await _call(executor)
    await _call(executor)

    assert len(ledger) == 2
