"""Gate reviewers write their LLM spend to the ledger (Plan 88 step 88.4.6).

LlmGateReviewer records each call as ``gate.reviewer`` and the post-run Haiku
classifier as ``gate.post_run``, both tagged with the gate's mission run. A
model or provider failure is still an ABORT (or an ESCALATE fall-through); a
ledger failure propagates, because an unrecorded call bypasses the budget.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.backend.agents.mission_control import gate as gate_module
from modules.backend.agents.mission_control import gate_post_run as post_run_module
from modules.backend.agents.mission_control.gate import LlmGateReviewer
from modules.backend.agents.mission_control.gate_models import GateAction, GateContext
from modules.backend.agents.mission_control.gate_post_run import AutonomousPostRunReviewer
from modules.backend.models.mission_plan import GateMode

MODEL = "fixture:reviewer"
MISSION_ID = str(uuid.uuid4())
RUN_ID = str(uuid.uuid4())
SESSION_ID = str(uuid.uuid4())


class _LedgerDown(Exception):
    """The stubbed ledger write failure."""


def _context(gate_type: str = "pre_dispatch") -> GateContext:
    return GateContext(
        gate_type=gate_type,
        mission_id=MISSION_ID,
        session_id=SESSION_ID,
        mission_run_id=RUN_ID,
    )


def _reviewer() -> LlmGateReviewer:
    reviewer = LlmGateReviewer(model=MODEL, max_tokens=256)
    output = SimpleNamespace(action="continue", reason="ok", modified_instructions=None)
    usage = SimpleNamespace(input_tokens=100, output_tokens=20)
    reviewer._agent = MagicMock()
    reviewer._agent.run = AsyncMock(
        return_value=SimpleNamespace(output=output, usage=lambda: usage)
    )
    return reviewer


async def test_gate_review_records_llm_call(monkeypatch):
    record = AsyncMock()
    monkeypatch.setattr(gate_module, "record_llm_call", record)
    monkeypatch.setattr(gate_module, "compute_cost_usd", lambda *args, **kwargs: 0.002)

    decision = await _reviewer().review(_context())

    assert decision.action == GateAction.CONTINUE
    kwargs = record.await_args.kwargs
    assert kwargs["agent_name"] == "gate.reviewer"
    assert kwargs["agent_role"] == "gate"
    assert kwargs["model"] == MODEL
    assert kwargs["cost_usd"] == 0.002
    assert (kwargs["mission_id"], kwargs["mission_run_id"], kwargs["session_id"]) == (
        MISSION_ID,
        RUN_ID,
        SESSION_ID,
    )
    assert kwargs["task_id"] is None


async def test_gate_review_ledger_failure_propagates(monkeypatch):
    monkeypatch.setattr(gate_module, "record_llm_call", AsyncMock(side_effect=_LedgerDown()))

    with pytest.raises(_LedgerDown):
        await _reviewer().review(_context())


def test_llm_gate_reviewer_requires_model():
    with pytest.raises(TypeError, match="model"):
        LlmGateReviewer(max_tokens=256)


async def test_post_run_classifier_records_llm_call(db_session, monkeypatch):
    record = AsyncMock()
    monkeypatch.setattr(post_run_module, "record_llm_call", record)
    result = SimpleNamespace(
        output=SimpleNamespace(decision="ESCALATE", confidence=0.9, reason="needs a human"),
        usage=lambda: SimpleNamespace(input_tokens=10, output_tokens=5),
    )
    agent = MagicMock(run=AsyncMock(return_value=result))

    with patch(
        "modules.backend.agents.mission.supervisor.agent.create_event_agent",
        MagicMock(return_value=agent),
    ):
        decision = await AutonomousPostRunReviewer(
            db_session, gate_mode=GateMode.AUTONOMOUS
        )._classify_with_haiku(_context("post_run"))

    assert decision.action == GateAction.ESCALATE
    kwargs = record.await_args.kwargs
    assert kwargs["agent_name"] == "gate.post_run"
    assert kwargs["mission_run_id"] == RUN_ID


async def test_post_run_classifier_ledger_failure_propagates(db_session, monkeypatch):
    monkeypatch.setattr(post_run_module, "record_llm_call", AsyncMock(side_effect=_LedgerDown()))
    result = SimpleNamespace(
        output=SimpleNamespace(decision="ESCALATE", confidence=0.9, reason="needs a human"),
        usage=lambda: SimpleNamespace(input_tokens=10, output_tokens=5),
    )
    agent = MagicMock(run=AsyncMock(return_value=result))

    with (
        patch(
            "modules.backend.agents.mission.supervisor.agent.create_event_agent",
            MagicMock(return_value=agent),
        ),
        pytest.raises(_LedgerDown),
    ):
        await AutonomousPostRunReviewer(
            db_session, gate_mode=GateMode.AUTONOMOUS
        )._classify_with_haiku(_context("post_run"))
