"""declare_objective_met is bound to a mission run's refine turn (Plan 88 Phase 2).

Owner decision 2026-11-11 after drill p88-faildrill-b3: the Director ends a
run's refine turn with a structured declaration instead of a text reply.
Outside a run's refine turn the tool refuses. The tool writes nothing: the run
records the decision as it ends on it. Services are patched; no database is
used (the integration test test_director_refine.py uses one).
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from modules.backend.agents.config_schema import AgentConfigSchema
from modules.backend.agents.deps.base import RunRefineTurn
from modules.backend.agents.mission.director.agent import create_agent
from modules.backend.agents.mission.director.deps import MissionDirectorDeps
from modules.backend.agents.mission.director.tool_helpers import ToolRefusal, run_tool
from modules.backend.agents.mission.director.tools.declare_objective_met import (
    declare_objective_met,
)
from modules.backend.agents.mission.director.tools.refine_plan import refine_plan
from modules.backend.agents.mission_control.helpers.agent_setup import _build_agent_deps
from modules.backend.core.exceptions import ConflictError
from modules.backend.services.mission_run import MissionRunService

RUN_ID = "7f3e9d1c-aaaa-4bbb-8ccc-ddddeeeeffff"


@pytest.fixture
def require_active(monkeypatch) -> AsyncMock:
    fake = AsyncMock()
    monkeypatch.setattr(MissionRunService, "require_active_run", fake)
    return fake


def _db() -> SimpleNamespace:
    return SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())


async def test_refuses_outside_a_run_refine_turn(require_active):
    db = _db()
    with pytest.raises(ToolRefusal, match="only works in a mission run's refine turn"):
        await declare_objective_met(db, "mission-1", None, "done", None)
    require_active.assert_not_awaited()


async def test_refusal_reaches_the_model_as_an_error():
    deps = SimpleNamespace(db_session=_db(), mission_id="mission-1", event_bus=None)
    out = await run_tool(
        SimpleNamespace(deps=deps),
        "declare_objective_met",
        lambda: declare_objective_met(deps.db_session, "mission-1", None, "done", None),
    )
    assert "only works in a mission run's refine turn" in json.loads(out)["error"]


async def test_refuses_without_a_reason(require_active):
    turn = RunRefineTurn(mission_run_id=RUN_ID)
    with pytest.raises(ToolRefusal, match="reason is required"):
        await declare_objective_met(_db(), "mission-1", turn, "   ", None)
    assert turn.objective_met_reason is None
    require_active.assert_not_awaited()


async def test_declares_and_marks_the_turn_without_writing(require_active):
    db = _db()
    turn = RunRefineTurn(mission_run_id=RUN_ID)

    result = await declare_objective_met(db, "mission-1", turn, " poem completed ", None)

    assert result["status"] == "declared"
    assert result["mission_run_id"] == RUN_ID
    assert turn.objective_met_reason == "poem completed"
    require_active.assert_awaited_once_with("mission-1", RUN_ID)
    # The run records the decision when it ends on it; the tool commits nothing.
    db.commit.assert_not_awaited()


async def test_second_declaration_in_the_turn_is_refused(require_active):
    turn = RunRefineTurn(mission_run_id=RUN_ID, objective_met_reason="first")
    with pytest.raises(ToolRefusal, match="already declared"):
        await declare_objective_met(_db(), "mission-1", turn, "second", None)
    assert turn.objective_met_reason == "first"


async def test_declaration_after_refine_plan_is_refused(require_active):
    turn = RunRefineTurn(mission_run_id=RUN_ID, refined=True)
    with pytest.raises(ToolRefusal, match="refine_plan was already called"):
        await declare_objective_met(_db(), "mission-1", turn, "done", None)
    assert turn.objective_met_reason is None
    require_active.assert_not_awaited()


async def test_refine_plan_after_declaration_is_refused():
    turn = RunRefineTurn(mission_run_id=RUN_ID, objective_met_reason="done")
    with pytest.raises(ToolRefusal, match="already declared met"):
        await refine_plan(_db(), "mission-1", "next wave", None, turn)
    assert turn.refined is False


async def test_run_no_longer_active_leaves_the_turn_undeclared(require_active):
    require_active.side_effect = ConflictError("Mission run x is not the active run of mission y")
    turn = RunRefineTurn(mission_run_id=RUN_ID)

    with pytest.raises(ConflictError):
        await declare_objective_met(_db(), "mission-1", turn, "done", None)

    assert turn.objective_met_reason is None


# ── Wiring: handle() -> _build_agent_deps -> the registered tool ─────────────


def _config(name: str) -> AgentConfigSchema:
    return AgentConfigSchema(
        agent_name=name,
        agent_type="vertical",
        description="A test agent",
        enabled=True,
        model="foundry:gpt-fixture",
        max_input_length=1000,
        max_budget_usd=0.1,
        execution={"mode": "local"},
    )


def test_build_agent_deps_gives_run_refine_to_the_director_only():
    turn = RunRefineTurn(mission_run_id=RUN_ID)
    director = _build_agent_deps(
        "mission.director.agent", _config("mission.director.agent"), "s-1", run_refine=turn
    )
    other = _build_agent_deps(
        "mission.supervisor.agent", _config("mission.supervisor.agent"), "s-1", run_refine=turn
    )

    assert isinstance(director, MissionDirectorDeps)
    assert director.run_refine is turn
    assert not hasattr(other, "run_refine")


async def test_registered_tool_reads_run_refine_from_deps(require_active):
    # The tool as the agent registered it, through a RunContext over the deps
    # _build_agent_deps builds: a break in the wiring refuses the call.
    turn = RunRefineTurn(mission_run_id=RUN_ID)
    deps = _build_agent_deps(
        "mission.director.agent",
        _config("mission.director.agent"),
        "s-1",
        mission_id="mission-1",
        db_session=_db(),
        run_refine=turn,
    )
    tool = create_agent(TestModel())._function_toolset.tools["declare_objective_met"]
    ctx = RunContext(deps=deps, model=TestModel(), usage=RunUsage())

    out = json.loads(await tool.function(ctx, reason="poem completed"))

    assert out["status"] == "declared"
    assert turn.objective_met_reason == "poem completed"
    require_active.assert_awaited_once_with("mission-1", RUN_ID)
