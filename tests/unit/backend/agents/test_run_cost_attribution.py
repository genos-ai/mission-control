"""Run cost attribution on the LLM ledger.

MissionRunLifecycle.finalise sums llm_calls by mission_run_id, so every
ledger write made inside a run must carry the run id:
- TokenEconomicsService.record_call and record_llm_call persist
  mission_run_id and task_id (real test database, P12).
- _call_planning_agent passes mission_run_id to record_llm_call.
"""

import contextlib
import uuid
from types import SimpleNamespace

import pytest
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from sqlalchemy import select

from modules.backend.agents.mission_control.helpers import agent_executor as agent_executor_module
from modules.backend.agents.mission_control.helpers.agent_executor import _call_planning_agent
from modules.backend.agents.mission_control.helpers.cost_recorder import record_llm_call
from modules.backend.agents.mission_control.roster import Roster
from modules.backend.models.llm_call import LlmCall
from modules.backend.services.token_economics import TokenEconomicsService


@pytest.fixture
def _route_llm_calls_to_test_db(monkeypatch, db_session_factory):
    """Point record_llm_call's own get_async_session() at the test database."""

    @contextlib.asynccontextmanager
    async def _fake_get_async_session():
        async with db_session_factory() as session:
            yield session
            await session.commit()

    monkeypatch.setattr(
        "modules.backend.core.database.get_async_session",
        _fake_get_async_session,
    )


def _record_call_kwargs(**overrides) -> dict:
    kwargs = {
        "session_id": None,
        "mission_id": str(uuid.uuid4()),
        "agent_name": "test.agent",
        "agent_role": "worker",
        "model": "test:model",
        "provider": "test",
        "input_tokens": 1,
        "output_tokens": 1,
        "cache_read_tokens": 0,
        "cache_write_5m_tokens": 0,
        "cache_write_1h_tokens": 0,
        "thinking_tokens": 0,
        "cost_usd": 0.01,
    }
    kwargs.update(overrides)
    return kwargs


class TestLedgerWritesRunAttribution:
    @pytest.mark.asyncio
    async def test_record_call_writes_run_and_task_ids(self, db_session):
        run_id, task_id = str(uuid.uuid4()), str(uuid.uuid4())

        call = await TokenEconomicsService(db_session).record_call(
            **_record_call_kwargs(mission_run_id=run_id, task_id=task_id)
        )
        await db_session.flush()

        stored = await db_session.get(LlmCall, call.id)
        assert stored.mission_run_id == run_id
        assert stored.task_id == task_id

    @pytest.mark.asyncio
    async def test_record_call_defaults_leave_row_untagged(self, db_session):
        call = await TokenEconomicsService(db_session).record_call(**_record_call_kwargs())
        await db_session.flush()

        stored = await db_session.get(LlmCall, call.id)
        assert stored.mission_run_id is None
        assert stored.task_id is None

    @pytest.mark.asyncio
    async def test_record_llm_call_passes_run_and_task_ids(
        self, _route_llm_calls_to_test_db, db_session_factory
    ):
        run_id, task_id = str(uuid.uuid4()), str(uuid.uuid4())

        await record_llm_call(
            session_id=None,
            mission_id=str(uuid.uuid4()),
            agent_name="test.agent",
            agent_role="worker",
            model="test:model",
            usage=RunUsage(input_tokens=3, output_tokens=2),
            cost_usd=0.02,
            mission_run_id=run_id,
            task_id=task_id,
        )

        async with db_session_factory() as session:
            rows = (
                (await session.execute(select(LlmCall).where(LlmCall.mission_run_id == run_id)))
                .scalars()
                .all()
            )
        assert len(rows) == 1
        assert rows[0].task_id == task_id
        assert rows[0].cost_usd == pytest.approx(0.02)


class _FinalisingPlanner:
    """Planning agent stand-in: finalises an empty plan in one run."""

    _function_toolset = SimpleNamespace(tools={})

    async def run(self, prompt, *, deps, model_settings=None, usage_limits=None):
        deps.build_session.finalised_plan = {"tasks": []}
        return SimpleNamespace(
            usage=lambda: RunUsage(input_tokens=10, output_tokens=5),
            all_messages=lambda: [],
        )


class TestPlannerRunAttribution:
    @pytest.mark.asyncio
    async def test_planner_passes_mission_run_id(self, monkeypatch):
        recorded: list[dict] = []

        async def _capture(**kwargs):
            recorded.append(kwargs)

        async def _no_trace(*args, **kwargs):
            return None

        monkeypatch.setattr(agent_executor_module, "record_llm_call", _capture)
        monkeypatch.setattr(agent_executor_module, "_build_model", lambda ref: TestModel())
        monkeypatch.setattr(
            "modules.backend.agents.mission.planning.agent.create_agent",
            lambda model: _FinalisingPlanner(),
        )
        monkeypatch.setattr("modules.backend.core.agent_trace.trace_and_emit", _no_trace)
        run_id = str(uuid.uuid4())

        await _call_planning_agent(
            "brief",
            Roster(agents=[]),
            None,
            mission_id=str(uuid.uuid4()),
            mission_run_id=run_id,
        )

        assert len(recorded) == 1
        assert recorded[0]["mission_run_id"] == run_id
        assert recorded[0]["agent_name"] == "mission.planning.agent"
