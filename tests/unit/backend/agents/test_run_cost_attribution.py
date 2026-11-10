"""Run cost attribution on the LLM ledger.

MissionRunLifecycle.finalise sums llm_calls by mission_run_id, so every
ledger write made inside a run must carry the run id:
- TokenEconomicsService.record_call and record_llm_call persist
  mission_run_id (real test database, P12).
- _call_planning_agent passes mission_run_id to record_llm_call.
- handle_mission forwards mission_run_id to the agent executor and planner.
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
from modules.backend.agents.mission_control.outcome import ExecutionStatus
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
    async def test_record_call_writes_run_id(self, db_session):
        run_id = str(uuid.uuid4())

        call = await TokenEconomicsService(db_session).record_call(
            **_record_call_kwargs(mission_run_id=run_id)
        )
        await db_session.flush()

        stored = await db_session.get(LlmCall, call.id)
        assert stored.mission_run_id == run_id

    @pytest.mark.asyncio
    async def test_record_call_defaults_leave_row_untagged(self, db_session):
        call = await TokenEconomicsService(db_session).record_call(**_record_call_kwargs())
        await db_session.flush()

        stored = await db_session.get(LlmCall, call.id)
        assert stored.mission_run_id is None

    @pytest.mark.asyncio
    async def test_record_llm_call_passes_run_id(
        self, _route_llm_calls_to_test_db, db_session_factory
    ):
        run_id = str(uuid.uuid4())

        await record_llm_call(
            session_id=None,
            mission_id=str(uuid.uuid4()),
            agent_name="test.agent",
            agent_role="worker",
            model="test:model",
            usage=RunUsage(input_tokens=3, output_tokens=2),
            cost_usd=0.02,
            mission_run_id=run_id,
        )

        async with db_session_factory() as session:
            rows = (
                (await session.execute(select(LlmCall).where(LlmCall.mission_run_id == run_id)))
                .scalars()
                .all()
            )
        assert len(rows) == 1
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


class _StopAtCapture(Exception):
    """Raised by a capture stub to end handle_mission once the kwargs are seen."""


class _NullBus:
    async def publish(self, event):
        return None


class _StubCurator:
    def __init__(self, *args, **kwargs):
        pass

    async def get_mission_context(self, mission_id):
        return None


class _StubHistory:
    def __init__(self, *args, **kwargs):
        pass

    async def get_recent_failures(self, mission_id, limit):
        return []


class TestHandleMissionRunAttribution:
    """handle_mission must forward mission_run_id; a dropped kwarg zeroes run cost."""

    @pytest.fixture
    def _isolated_handle_mission(self, monkeypatch):
        from modules.backend.agents.mission_control import mission_dispatch

        async def _empty_roster(mission_id, db_session):
            return Roster(agents=[])

        monkeypatch.setattr(mission_dispatch, "derive_roster_from_team", _empty_roster)
        monkeypatch.setattr(mission_dispatch, "MissionContextManager", lambda db: None)
        monkeypatch.setattr(mission_dispatch, "ContextCurator", _StubCurator)
        monkeypatch.setattr(mission_dispatch, "HistoryQueryService", _StubHistory)
        monkeypatch.setattr(mission_dispatch, "ContextAssembler", lambda **kwargs: None)
        monkeypatch.setattr(
            "modules.backend.services.code_map.loader.CodeMapLoader", lambda root: None
        )
        monkeypatch.setattr(
            mission_dispatch,
            "validate_plan",
            lambda plan, roster, budget: SimpleNamespace(is_valid=True, errors=[]),
        )
        return mission_dispatch

    async def _call(self, mission_dispatch, run_id, **kwargs):
        return await mission_dispatch.handle_mission(
            "label",
            "brief",
            session_service=None,
            event_bus=_NullBus(),
            mission_id=str(uuid.uuid4()),
            db_session=object(),
            mission_budget_usd=1.0,
            mission_run_id=run_id,
            **kwargs,
        )

    @pytest.mark.asyncio
    async def test_forwards_run_id_to_agent_executor(self, _isolated_handle_mission, monkeypatch):
        captured: dict = {}

        def _capture(event_bus, **kwargs):
            captured.update(kwargs)
            raise _StopAtCapture

        monkeypatch.setattr(_isolated_handle_mission, "_make_agent_executor", _capture)
        run_id = str(uuid.uuid4())

        with pytest.raises(_StopAtCapture):
            await self._call(
                _isolated_handle_mission,
                run_id,
                precomputed_plan=SimpleNamespace(tasks=[]),
            )

        assert captured["mission_run_id"] == run_id

    @pytest.mark.asyncio
    async def test_forwards_run_id_to_planner(self, _isolated_handle_mission, monkeypatch):
        captured: list[dict] = []

        async def _capture(*args, **kwargs):
            captured.append(kwargs)
            raise ValueError("planner stub")

        monkeypatch.setattr(_isolated_handle_mission, "_call_planning_agent", _capture)
        run_id = str(uuid.uuid4())

        # The retry loop swallows the planner error, so handle_mission
        # returns a FAILED outcome after its attempts instead of dispatching.
        outcome = await self._call(_isolated_handle_mission, run_id)

        assert outcome.status == ExecutionStatus.FAILED
        assert captured
        assert all(kwargs["mission_run_id"] == run_id for kwargs in captured)
