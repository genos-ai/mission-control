"""Tests for the agent executor closure (Plan 84 Phase 2.2).

Targets _make_agent_executor / execute_agent (helpers/agent_executor.py):
- Output contract: result is wrapped under {"output": ...}.
- Cost recording occurs on success, verified against a real db_session
  (record_llm_call manages its own session via get_async_session(), so
  it's redirected to the test database for this test — see
  _route_llm_calls_to_test_db — never the developer's local database).
- Agent exceptions propagate as a raised error — never swallowed.

Uses the real platform.health.agent (already proven safe for TestModel use
in test_agent_testmodel.py) with TestModel standing in for the LLM, per P11.
"""

import contextlib
import uuid

import pytest
from pydantic_ai import UsageLimits
from pydantic_ai.models.test import TestModel
from sqlalchemy import select

from modules.backend.agents.mission_control.helpers import agent_executor as agent_executor_module
from modules.backend.agents.mission_control.helpers.agent_executor import _make_agent_executor
from modules.backend.agents.mission_control.models import NoOpEventBus
from modules.backend.agents.mission_control.registry import get_registry
from modules.backend.models.llm_call import LlmCall

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_agent_instances():
    """Clear the registry's cached Agent instances so TestModel wiring
    from _build_model patching takes effect fresh in every test."""
    get_registry().reset()
    yield
    get_registry().reset()


@pytest.fixture
def _route_llm_calls_to_test_db(monkeypatch, db_session_factory):
    """Redirect record_llm_call's internal get_async_session() to the test
    database instead of the developer's local database, so cost-recording
    writes are real (P12) without polluting dev data."""

    @contextlib.asynccontextmanager
    async def _fake_get_async_session():
        async with db_session_factory() as session:
            yield session
            await session.commit()

    monkeypatch.setattr(
        "modules.backend.core.database.get_async_session",
        _fake_get_async_session,
    )


@pytest.fixture
def executor_ids():
    return {"session_id": str(uuid.uuid4()), "mission_id": str(uuid.uuid4())}


@pytest.fixture
def executor(monkeypatch, _route_llm_calls_to_test_db, executor_ids):
    """A real execute_agent closure with TestModel standing in for the LLM."""
    monkeypatch.setattr(
        agent_executor_module,
        "_build_model",
        lambda model_ref: TestModel(call_tools=[]),
    )
    return _make_agent_executor(
        NoOpEventBus(),
        session_id=executor_ids["session_id"],
        mission_id=executor_ids["mission_id"],
    )


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------


class TestExecuteAgentOutputContract:
    @pytest.mark.asyncio
    async def test_output_wrapped_under_output_key(self, executor):
        result = await executor(
            agent_name="platform.health.agent",
            instructions="check system health",
            inputs={},
            usage_limits=UsageLimits(request_limit=5),
        )

        assert isinstance(result, dict)
        assert "output" in result
        assert isinstance(result["output"], dict)
        # HealthCheckResult fields per test_agent_testmodel.py
        assert "summary" in result["output"]
        assert "overall_status" in result["output"]

        # Consumers read result.get("output", {}) — verify that contract works
        assert result.get("output", {})["summary"] == result["output"]["summary"]

    @pytest.mark.asyncio
    async def test_meta_contains_token_and_cost_fields(self, executor):
        result = await executor(
            agent_name="platform.health.agent",
            instructions="check system health",
            inputs={},
            usage_limits=UsageLimits(request_limit=5),
        )

        assert "_meta" in result
        for key in ("input_tokens", "output_tokens", "thinking_tokens", "cost_usd"):
            assert key in result["_meta"]


# ---------------------------------------------------------------------------
# Cost recording
# ---------------------------------------------------------------------------


class TestExecuteAgentCostRecording:
    @pytest.mark.asyncio
    async def test_cost_recorded_on_success(self, executor, executor_ids, db_session_factory):
        await executor(
            agent_name="platform.health.agent",
            instructions="check system health",
            inputs={},
            usage_limits=UsageLimits(request_limit=5),
        )

        async with db_session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(LlmCall).where(
                            LlmCall.session_id == executor_ids["session_id"],
                            LlmCall.mission_id == executor_ids["mission_id"],
                        )
                    )
                )
                .scalars()
                .all()
            )

        assert len(rows) == 1
        recorded = rows[0]
        assert recorded.agent_name == "platform.health.agent"
        assert recorded.cost_usd >= 0.0
        assert recorded.input_tokens >= 0
        assert recorded.mission_run_id is None

    @pytest.mark.asyncio
    async def test_cost_tagged_with_mission_run_id(
        self, monkeypatch, _route_llm_calls_to_test_db, executor_ids, db_session_factory
    ):
        """A run's executor tags every ledger row so finalise can sum the run's cost."""
        monkeypatch.setattr(
            agent_executor_module,
            "_build_model",
            lambda model_ref: TestModel(call_tools=[]),
        )
        run_id = str(uuid.uuid4())
        executor = _make_agent_executor(
            NoOpEventBus(),
            session_id=executor_ids["session_id"],
            mission_id=executor_ids["mission_id"],
            mission_run_id=run_id,
        )

        await executor(
            agent_name="platform.health.agent",
            instructions="check system health",
            inputs={},
            usage_limits=UsageLimits(request_limit=5),
        )

        async with db_session_factory() as session:
            rows = (
                (await session.execute(select(LlmCall).where(LlmCall.mission_run_id == run_id)))
                .scalars()
                .all()
            )

        assert len(rows) == 1
        assert rows[0].mission_id == executor_ids["mission_id"]
        assert rows[0].task_id is None

    @pytest.mark.asyncio
    async def test_cost_tagged_with_task_id(
        self, monkeypatch, _route_llm_calls_to_test_db, executor_ids, db_session_factory
    ):
        """A per-task executor tags its ledger rows with the task (88.2.3)."""
        monkeypatch.setattr(
            agent_executor_module,
            "_build_model",
            lambda model_ref: TestModel(call_tools=[]),
        )
        run_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())
        executor = _make_agent_executor(
            NoOpEventBus(),
            session_id=executor_ids["session_id"],
            mission_id=executor_ids["mission_id"],
            mission_run_id=run_id,
            task_id=task_id,
        )

        await executor(
            agent_name="platform.health.agent",
            instructions="check system health",
            inputs={},
            usage_limits=UsageLimits(request_limit=5),
        )

        async with db_session_factory() as session:
            rows = (
                (await session.execute(select(LlmCall).where(LlmCall.task_id == task_id)))
                .scalars()
                .all()
            )

        assert len(rows) == 1
        assert rows[0].mission_run_id == run_id


# ---------------------------------------------------------------------------
# Exception propagation
# ---------------------------------------------------------------------------


class _FakeAgentModule:
    """A minimal agent module stand-in exposing only create_agent —
    no pre_execute/post_execute hooks, matching hasattr() checks in
    execute_agent."""

    def __init__(self, agent):
        self._agent = agent

    def create_agent(self, model, tool_names=None):
        return self._agent


class _BrokenStream:
    """An async context manager that raises on entry, simulating a
    mid-run agent failure (provider error, tool crash, etc.)."""

    async def __aenter__(self):
        raise RuntimeError("agent run exploded")

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _BrokenAgent:
    def run_stream(self, *args, **kwargs):
        return _BrokenStream()


class TestExecuteAgentExceptionPropagation:
    @pytest.mark.asyncio
    async def test_agent_exception_propagates_not_swallowed(self, monkeypatch):
        monkeypatch.setattr(
            agent_executor_module,
            "_import_agent_module",
            lambda agent_name: _FakeAgentModule(_BrokenAgent()),
        )
        monkeypatch.setattr(
            agent_executor_module,
            "_build_model",
            lambda model_ref: TestModel(call_tools=[]),
        )

        executor = _make_agent_executor(
            NoOpEventBus(),
            session_id=str(uuid.uuid4()),
            mission_id=str(uuid.uuid4()),
        )

        with pytest.raises(RuntimeError, match="agent run exploded"):
            await executor(
                agent_name="platform.health.agent",
                instructions="check system health",
                inputs={},
                usage_limits=UsageLimits(request_limit=5),
            )
