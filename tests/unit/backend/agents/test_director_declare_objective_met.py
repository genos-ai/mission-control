"""declare_objective_met is bound to a mission run's refine turn (Plan 88 Phase 2).

Owner decision 2026-11-11 after drill p88-faildrill-b3: the Director ends a
run's refine turn with a structured declaration instead of a text reply.
Outside a run's refine turn the tool refuses. Services are patched; no
database is used (the integration test test_director_refine.py uses one).
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.backend.agents.deps.base import RunRefineTurn
from modules.backend.agents.mission.director.tool_helpers import ToolRefusal, run_tool
from modules.backend.agents.mission.director.tools.declare_objective_met import (
    declare_objective_met,
)
from modules.backend.core.exceptions import ConflictError
from modules.backend.services.mission_run import MissionRunService

RUN_ID = "7f3e9d1c-aaaa-4bbb-8ccc-ddddeeeeffff"


@pytest.fixture
def record(monkeypatch) -> AsyncMock:
    fake = AsyncMock()
    monkeypatch.setattr(MissionRunService, "record_director_objective_met", fake)
    return fake


def _db() -> SimpleNamespace:
    return SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())


async def test_refuses_outside_a_run_refine_turn(record):
    db = _db()
    with pytest.raises(ToolRefusal, match="only works in a mission run's refine turn"):
        await declare_objective_met(db, "mission-1", None, "done", None)
    record.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_refusal_reaches_the_model_as_an_error():
    deps = SimpleNamespace(db_session=_db(), mission_id="mission-1", event_bus=None)
    out = await run_tool(
        SimpleNamespace(deps=deps),
        "declare_objective_met",
        lambda: declare_objective_met(deps.db_session, "mission-1", None, "done", None),
    )
    assert "only works in a mission run's refine turn" in json.loads(out)["error"]


async def test_refuses_without_a_reason(record):
    turn = RunRefineTurn(mission_run_id=RUN_ID)
    with pytest.raises(ToolRefusal, match="reason is required"):
        await declare_objective_met(_db(), "mission-1", turn, "   ", None)
    assert turn.objective_met_reason is None
    record.assert_not_awaited()


async def test_declares_records_and_marks_the_turn(record):
    db = _db()
    turn = RunRefineTurn(mission_run_id=RUN_ID)

    result = await declare_objective_met(db, "mission-1", turn, " poem completed ", None)

    assert result["status"] == "declared"
    assert result["mission_run_id"] == RUN_ID
    assert turn.objective_met_reason == "poem completed"
    record.assert_awaited_once_with("mission-1", RUN_ID, "poem completed", "mission.director.agent")
    db.commit.assert_awaited_once()


async def test_second_declaration_in_the_turn_is_refused(record):
    turn = RunRefineTurn(mission_run_id=RUN_ID, objective_met_reason="first")
    with pytest.raises(ToolRefusal, match="already declared"):
        await declare_objective_met(_db(), "mission-1", turn, "second", None)
    assert turn.objective_met_reason == "first"


async def test_run_no_longer_active_leaves_the_turn_undeclared(record):
    record.side_effect = ConflictError("Mission run x is not the active run of mission y")
    db = _db()
    turn = RunRefineTurn(mission_run_id=RUN_ID)

    with pytest.raises(ConflictError):
        await declare_objective_met(db, "mission-1", turn, "done", None)

    assert turn.objective_met_reason is None
    db.commit.assert_not_awaited()
