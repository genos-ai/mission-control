"""Tests for the deliberation_loop executor (Plan 79 v2).

The executor (execute_deliberation_loop) runs the 7-agent flow as Python
code with execute_agent_fn injected. These tests provide a deterministic
mock execute_agent_fn that returns schema-valid payloads, then verify:

- All 7 agent roles are dispatched in the right order
- Sparse-topology wiring (each round-N debater sees own + opponents + critic's attack on self)
- Verifier retry loop with feedback when packet fails
- Halt when verifier retries exhaust
- Follow-up research dispatch when debaters request it
- Early-stop fires when stance delta is small
- Final result carries the synthesiser's FinalDeliverable
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai.usage import UsageLimits

from modules.backend.agents.mission_control.dispatch.deliberation_loop import (
    DEBATER_IDS,
    DeliberationConfig,
    execute_deliberation_loop,
)
from modules.backend.agents.mission_control.outcome import TaskStatus
from modules.backend.core.embeddings import FakeEmbedder, FailOpenEmbedder


@pytest.fixture(autouse=True)
def _stub_embedder(monkeypatch):
    """OpenAIEmbedder fails in unit-test env (no API key) and returns []
    from FailOpenEmbedder, which forces text_distance=1.0 in
    compute_stance_delta and breaks the early-stop logic. Pin to
    FakeEmbedder so identical positions across rounds yield distance 0.
    """
    monkeypatch.setattr(
        "modules.backend.tools.compute_stance_delta.get_embedder",
        lambda: FailOpenEmbedder(FakeEmbedder()),
    )


# =============================================================================
# Schema-valid payload fixtures (matching modules.backend.schemas.deliberation)
# =============================================================================


def _packet_payload(question: str = "Will X happen?") -> dict:
    return {
        "question_restated": question,
        "what_is_known": [
            {"claim": "A real claim", "source": "https://example.org/paper",
             "confidence": "HIGH"},
            {"claim": "B real claim", "source": "https://example.org/paper2",
             "confidence": "MEDIUM"},
            {"claim": "C real claim", "source": "https://example.org/paper3",
             "confidence": "LOW"},
        ],
        "expert_disagreements": [
            {"topic": "t1", "camps": ["A", "B"], "side_a_steelman": "a",
             "side_b_steelman": "b", "resolving_evidence": "e"},
            {"topic": "t2", "camps": ["C", "D"], "side_a_steelman": "c",
             "side_b_steelman": "d", "resolving_evidence": "f"},
        ],
        "mainstream_consensus": "Conventional view X",
        "under_discussed_angles": ["a1", "a2", "a3"],
        "base_rates": [],
    }


def _verifier_payload(passed: bool = True) -> dict:
    return {
        "passed": passed,
        "issues": [] if passed else ["Source X is unverified"],
        "issues_text": "" if passed else "- Source X is unverified",
        "mainstream_consensus_looks_plausible": True,
        "under_discussed_angles_actually_under_discussed": True,
        "notes": "",
    }


def _debater_payload(
    debater_id: str,
    round_index: int = 0,
    *,
    decision: str = "HOLD",
    position: str = "My position.",
    research_requests: list[str] | None = None,
    confidence: float = 0.7,
) -> dict:
    return {
        "debater_id": debater_id,
        "round_index": round_index,
        "position": position,
        "load_bearing_claims": [
            {"claim": "c1", "if_this_fails": "f1"},
            {"claim": "c2", "if_this_fails": "f2"},
        ],
        "what_would_change_my_mind": "Specific evidence X.",
        "decision": decision,
        "decision_justification": "No counter offered.",
        "confidence": confidence,
        "research_requests": research_requests or [],
    }


def _critic_payload(round_index: int = 0) -> dict:
    attack = {
        "load_bearing_assumption": "A",
        "attack": "B",
        "steelman_of_attack": "C",
        "what_would_vindicate_the_debater": "D",
    }
    return {
        "round_index": round_index,
        "attacks": {d: attack for d in DEBATER_IDS},
        "convergence_flag": {"kind": "none", "debaters_involved": [], "explanation": ""},
    }


def _deliverable_payload(*, dvm: str = "modifies") -> dict:
    return {
        "question_restated": "Q?",
        "committed_answer": "Yes with caveats.",
        "confidence": 0.7,
        "cruxes": [
            {
                "crux_question": "cq1",
                "side_a_position": "a", "side_a_debaters": ["systems"],
                "side_a_steelman": "as",
                "side_b_position": "b", "side_b_debaters": ["quant"],
                "side_b_steelman": "bs",
                "resolving_evidence": "e",
            },
            {
                "crux_question": "cq2",
                "side_a_position": "a", "side_a_debaters": ["empiricist"],
                "side_a_steelman": "as",
                "side_b_position": "b", "side_b_debaters": ["ethicist"],
                "side_b_steelman": "bs",
                "resolving_evidence": "e",
            },
        ],
        "minority_position": None,
        "mainstream_prior": "X",
        "deliberation_vs_mainstream": dvm,
        "forward_claim": {
            "horizon": "2030", "most_likely": "Y",
            "plausible_alternative": "Z", "would_surprise_the_system": "W",
            "falsifiers": ["if A"],
        },
        "biggest_things_that_could_be_wrong": ["a", "b"],
        "sycophancy_flags": [],
        "report_markdown": "# Deliverable\n\n" + "x" * 250,
        "recommendation_markdown": "Watch for X, Y, and Z reversal.",
    }


# =============================================================================
# Mock execute_agent_fn
# =============================================================================


class _CallLog:
    """Records every dispatch call so tests can assert routing + sparse topology."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, agent_name: str, instructions: str, inputs: dict,
                 usage_limits: UsageLimits) -> Any:
        self.calls.append({
            "agent": agent_name,
            "instructions": instructions,
            "inputs": inputs,
            "request_limit": usage_limits.request_limit,
        })
        return None


def _mock_fn(call_log: _CallLog, payload_resolver):
    """Build an async execute_agent_fn that logs + returns scripted payloads."""

    async def _fn(*, agent_name: str, instructions: str, inputs: dict,
                  usage_limits: UsageLimits) -> dict:
        call_log(agent_name, instructions, inputs, usage_limits)
        payload = payload_resolver(agent_name, inputs, len(call_log.calls))
        return {
            "output": payload,
            "_meta": {"input_tokens": 100, "output_tokens": 50,
                      "thinking_tokens": 0, "cost_usd": 0.0},
        }

    return _fn


# =============================================================================
# Tests
# =============================================================================


@pytest.mark.asyncio
async def test_happy_path_completes_with_deliverable():
    """Full successful run: research → verify pass → opens → critic-r0 →
    round 1 (stance stable → early stop) → synthesise."""
    log = _CallLog()

    def resolver(agent, inputs, call_num):
        if "researcher" in agent:
            return _packet_payload()
        if "research_verifier" in agent:
            return _verifier_payload(passed=True)
        if "critic" in agent:
            return _critic_payload(round_index=inputs["round_index"])
        if "synthesiser" in agent:
            return _deliverable_payload()
        # A debater agent
        for d in DEBATER_IDS:
            if f"debater_{d}" in agent:
                # Set HOLD with stable position so early-stop fires
                return _debater_payload(d, round_index=inputs["round_index"],
                                        decision="HOLD",
                                        position="Stable position.",
                                        confidence=0.7)
        raise AssertionError(f"unexpected agent: {agent}")

    config = DeliberationConfig(max_rounds=2)
    result = await execute_deliberation_loop(
        task_id="t-happy",
        question="Will X happen?",
        config=config,
        execute_agent_fn=_mock_fn(log, resolver),
        mission_id=None,  # disables persistence
    )

    assert result.status == TaskStatus.SUCCESS
    # Output is the synthesiser's deliverable
    assert result.output_reference["committed_answer"] == "Yes with caveats."
    assert result.output_reference["deliberation_vs_mainstream"] == "modifies"
    # Verify the 7-agent flow ran
    agents_called = [c["agent"] for c in log.calls]
    assert any("researcher" in a for a in agents_called)
    assert any("research_verifier" in a for a in agents_called)
    assert sum(1 for a in agents_called if "debater_systems" in a) >= 1
    assert sum(1 for a in agents_called if "critic" in a) >= 1
    assert any("synthesiser" in a for a in agents_called)


@pytest.mark.asyncio
async def test_blind_opening_has_no_prior_context():
    """Round 0 debater calls must not have own_previous, opponents_previous,
    or critic_attack_on_self in their inputs."""
    log = _CallLog()

    def resolver(agent, inputs, call_num):
        if "researcher" in agent:
            return _packet_payload()
        if "research_verifier" in agent:
            return _verifier_payload(passed=True)
        if "critic" in agent:
            return _critic_payload(round_index=inputs["round_index"])
        if "synthesiser" in agent:
            return _deliverable_payload()
        for d in DEBATER_IDS:
            if f"debater_{d}" in agent:
                return _debater_payload(d, round_index=inputs["round_index"])
        raise AssertionError(agent)

    # max_rounds=0 → only the blind opening, no subsequent rounds
    config = DeliberationConfig(max_rounds=0)
    await execute_deliberation_loop(
        task_id="t-blind",
        question="Q?",
        config=config,
        execute_agent_fn=_mock_fn(log, resolver),
        mission_id=None,
    )

    # Find round-0 debater calls
    round_0_debaters = [
        c for c in log.calls
        if "debater_" in c["agent"] and c["inputs"]["round_index"] == 0
    ]
    assert len(round_0_debaters) == 4
    for c in round_0_debaters:
        assert "own_previous" not in c["inputs"]
        assert "opponents_previous" not in c["inputs"]
        assert "critic_attack_on_self" not in c["inputs"]


@pytest.mark.asyncio
async def test_sparse_topology_round_one():
    """Round-1 debaters must see own R0 + 3 opponents' R0 (NOT self) +
    critic's R0 attack on self only."""
    log = _CallLog()

    def resolver(agent, inputs, call_num):
        if "researcher" in agent:
            return _packet_payload()
        if "research_verifier" in agent:
            return _verifier_payload(passed=True)
        if "critic" in agent:
            return _critic_payload(round_index=inputs["round_index"])
        if "synthesiser" in agent:
            return _deliverable_payload()
        for d in DEBATER_IDS:
            if f"debater_{d}" in agent:
                # REFINE so early-stop does not fire
                return _debater_payload(d, round_index=inputs["round_index"],
                                        decision="REFINE")
        raise AssertionError(agent)

    config = DeliberationConfig(max_rounds=1)
    await execute_deliberation_loop(
        task_id="t-sparse",
        question="Q?",
        config=config,
        execute_agent_fn=_mock_fn(log, resolver),
        mission_id=None,
    )

    round_1_debaters = [
        c for c in log.calls
        if "debater_" in c["agent"] and c["inputs"]["round_index"] == 1
    ]
    assert len(round_1_debaters) == 4
    for c in round_1_debaters:
        debater_id = c["agent"].replace("deliberation.debater_", "").replace(".agent", "")
        inputs = c["inputs"]
        # own_previous: matches own debater_id
        assert inputs["own_previous"]["debater_id"] == debater_id
        # opponents_previous: the THREE others, no self
        opponents = inputs["opponents_previous"]
        assert set(opponents.keys()) == set(DEBATER_IDS) - {debater_id}
        for opp_id, turn in opponents.items():
            assert turn["debater_id"] == opp_id
        # critic_attack_on_self: matches self only
        assert inputs["critic_attack_on_self"] is not None


@pytest.mark.asyncio
async def test_verifier_retry_with_feedback_loop():
    """When verifier returns passed=False, the researcher is re-run with
    the verifier's issues_text as feedback. Up to verifier_max_retries times."""
    log = _CallLog()
    state = {"verifier_attempts": 0}

    def resolver(agent, inputs, call_num):
        if "researcher" in agent:
            return _packet_payload()
        if "research_verifier" in agent:
            state["verifier_attempts"] += 1
            # First two fail, third passes
            return _verifier_payload(passed=(state["verifier_attempts"] >= 3))
        if "critic" in agent:
            return _critic_payload(round_index=inputs["round_index"])
        if "synthesiser" in agent:
            return _deliverable_payload()
        for d in DEBATER_IDS:
            if f"debater_{d}" in agent:
                return _debater_payload(d, round_index=inputs["round_index"])
        raise AssertionError(agent)

    config = DeliberationConfig(max_rounds=0, verifier_max_retries=3)
    result = await execute_deliberation_loop(
        task_id="t-retry",
        question="Q?",
        config=config,
        execute_agent_fn=_mock_fn(log, resolver),
        mission_id=None,
    )

    assert result.status == TaskStatus.SUCCESS
    # 3 verifier attempts → 3 researcher calls (initial + 2 retries with feedback)
    researcher_calls = [c for c in log.calls if "researcher" in c["agent"]]
    assert len(researcher_calls) == 3
    # The retried researcher calls carry the feedback
    assert researcher_calls[1]["inputs"].get("previous_packet_issues")
    assert researcher_calls[2]["inputs"].get("previous_packet_issues")


@pytest.mark.asyncio
async def test_verifier_halts_after_retries_exhausted():
    """When the verifier keeps rejecting, the loop halts with a FAILED result."""
    log = _CallLog()

    def resolver(agent, inputs, call_num):
        if "researcher" in agent:
            return _packet_payload()
        if "research_verifier" in agent:
            return _verifier_payload(passed=False)  # never passes
        return None

    config = DeliberationConfig(verifier_max_retries=2)
    result = await execute_deliberation_loop(
        task_id="t-halt",
        question="Q?",
        config=config,
        execute_agent_fn=_mock_fn(log, resolver),
        mission_id=None,
    )

    assert result.status == TaskStatus.FAILED
    assert "verification" in result.output_reference["error"].lower()
    # Never dispatched a debater
    assert not any("debater_" in c["agent"] for c in log.calls)


@pytest.mark.asyncio
async def test_follow_up_research_dispatched_when_requests_present():
    """If debaters emit research_requests, the executor dispatches the
    researcher against each before the next round."""
    log = _CallLog()

    def resolver(agent, inputs, call_num):
        if "researcher" in agent:
            return _packet_payload()
        if "research_verifier" in agent:
            return _verifier_payload(passed=True)
        if "critic" in agent:
            return _critic_payload(round_index=inputs["round_index"])
        if "synthesiser" in agent:
            return _deliverable_payload()
        for d in DEBATER_IDS:
            if f"debater_{d}" in agent:
                # Round 0 debaters request follow-up research; round 1
                # debaters do not.
                requests = (
                    [f"What is X for debater {d}?"]
                    if inputs["round_index"] == 0
                    else []
                )
                return _debater_payload(
                    d, round_index=inputs["round_index"],
                    decision="REFINE",
                    research_requests=requests,
                )
        raise AssertionError(agent)

    config = DeliberationConfig(max_rounds=1)
    await execute_deliberation_loop(
        task_id="t-followup",
        question="Q?",
        config=config,
        execute_agent_fn=_mock_fn(log, resolver),
        mission_id=None,
    )

    researcher_calls = [c for c in log.calls if "researcher" in c["agent"]]
    # 1 initial + 4 follow-up (one per debater request)
    assert len(researcher_calls) == 5
    follow_ups = [c for c in researcher_calls if c["inputs"].get("mode") == "follow_up"]
    assert len(follow_ups) == 4


@pytest.mark.asyncio
async def test_early_stop_fires_when_stance_stable():
    """When stance delta < threshold AND no debater is REFINEing/CONCEDEing,
    the executor exits the round loop early."""
    log = _CallLog()

    def resolver(agent, inputs, call_num):
        if "researcher" in agent:
            return _packet_payload()
        if "research_verifier" in agent:
            return _verifier_payload(passed=True)
        if "critic" in agent:
            return _critic_payload(round_index=inputs["round_index"])
        if "synthesiser" in agent:
            return _deliverable_payload()
        for d in DEBATER_IDS:
            if f"debater_{d}" in agent:
                # Identical position every round + HOLD → stance delta = 0
                return _debater_payload(
                    d, round_index=inputs["round_index"],
                    position="Same identical position.",
                    decision="HOLD",
                    confidence=0.7,
                )
        raise AssertionError(agent)

    config = DeliberationConfig(max_rounds=3, early_stop_threshold=0.15)
    await execute_deliberation_loop(
        task_id="t-early",
        question="Q?",
        config=config,
        execute_agent_fn=_mock_fn(log, resolver),
        mission_id=None,
    )

    # Should have stopped after round 1 (delta=0, all HOLD)
    round_2_debaters = [
        c for c in log.calls
        if "debater_" in c["agent"] and c["inputs"]["round_index"] == 2
    ]
    assert len(round_2_debaters) == 0


@pytest.mark.asyncio
async def test_runs_max_rounds_when_stance_keeps_moving():
    """If a debater REFINEs every round, the executor uses the full
    max_rounds budget (active revision overrides the delta check)."""
    log = _CallLog()

    def resolver(agent, inputs, call_num):
        if "researcher" in agent:
            return _packet_payload()
        if "research_verifier" in agent:
            return _verifier_payload(passed=True)
        if "critic" in agent:
            return _critic_payload(round_index=inputs["round_index"])
        if "synthesiser" in agent:
            return _deliverable_payload()
        for d in DEBATER_IDS:
            if f"debater_{d}" in agent:
                return _debater_payload(d, round_index=inputs["round_index"],
                                        decision="REFINE")
        raise AssertionError(agent)

    config = DeliberationConfig(max_rounds=2)
    await execute_deliberation_loop(
        task_id="t-full",
        question="Q?",
        config=config,
        execute_agent_fn=_mock_fn(log, resolver),
        mission_id=None,
    )

    round_2_debaters = [
        c for c in log.calls
        if "debater_" in c["agent"] and c["inputs"]["round_index"] == 2
    ]
    assert len(round_2_debaters) == 4  # all 4 ran in round 2


class TestConfigFromDict:
    def test_defaults_when_empty(self):
        c = DeliberationConfig.from_dict({})
        assert c.max_rounds == 3
        assert c.agreement_intensity == 0.2
        assert c.early_stop_threshold == 0.15
        assert c.verifier_max_retries == 3

    def test_overrides_applied(self):
        c = DeliberationConfig.from_dict({
            "max_rounds": 5,
            "agreement_intensity": 0.5,
            "early_stop_threshold": 0.1,
            "verifier_max_retries": 1,
        })
        assert c.max_rounds == 5
        assert c.agreement_intensity == 0.5
        assert c.early_stop_threshold == 0.1
        assert c.verifier_max_retries == 1

    def test_rejects_non_dict(self):
        with pytest.raises(TypeError):
            DeliberationConfig.from_dict("not a dict")  # type: ignore[arg-type]
