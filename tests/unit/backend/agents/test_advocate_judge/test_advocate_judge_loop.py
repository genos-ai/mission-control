"""
Tests for the Advocate-Judge executor (Plan 80 Phase 1 skeleton).

These tests verify the executor's TOPOLOGY: that each phase dispatches
the right agents with the right input shapes. They do NOT test real
LLM calls (those land in Phase 7). A mock execute_agent_fn returns
schema-valid canned outputs based on agent_name + inputs, and the
tests assert:

- All phases run in order (framer -> validator -> N researchers ->
  N advocates -> N attackers -> judge).
- Information asymmetry: each side-researcher input contains ONLY
  its own candidate (not the others).
- Blindness: each blind-advocate input contains ONLY its own packet.
- Full information at attacks: each attacker sees all packets and all
  other cases.
- Per-side model resolution propagates correctly to each call's
  `_resolved_model` input field.
- Provider availability is validated at executor start (judge model
  + side models).
- Sycophancy_flags get heterogeneity-reduction notes when the rotation
  has fewer families than sides.
"""

from __future__ import annotations

from typing import Any

import pytest

from modules.backend.agents.mission_control.dispatch.advocate_judge_loop import (
    DEFAULT_SIDE_MODEL_ROTATION,
    _resolve_side_models,
    execute_advocate_judge_loop,
)
from modules.backend.agents.mission_control.outcome import TaskStatus
from modules.backend.schemas.deliberation_advocate_judge import AdvocateJudgeConfig


# =============================================================================
# Provider-wiring stub — assume everything is wired for tests
# =============================================================================


@pytest.fixture(autouse=True)
def _stub_provider_check(monkeypatch):
    """Tests don't have real Copilot/Google providers wired; stub the check."""
    monkeypatch.setattr(
        "modules.backend.agents.mission_control.dispatch.advocate_judge_loop._provider_is_wired",
        lambda model_name: True,
    )


# =============================================================================
# Canned payload builders (all schema-valid)
# =============================================================================


def _candidate_set_payload(n: int = 3) -> dict:
    return {
        "candidates": [
            {
                "label": f"camp-{i}",
                "statement": f"Statement for camp {i}.",
                "rationale_for_inclusion": f"Held by school {i}.",
            }
            for i in range(n)
        ],
        "mainstream_consensus": "The conventional answer.",
    }


def _framing_validation_payload(verdict: str = "approved", revised_n: int = 3) -> dict:
    return {
        "verdict": verdict,
        "revised_set": _candidate_set_payload(revised_n) if verdict == "revised" else None,
        "rationale": "Audit passed." if verdict == "approved" else "Added missing camp.",
    }


def _side_packet_payload(label: str) -> dict:
    return {
        "candidate_label": label,
        "sourced_claims": [
            {"claim": f"{label}-claim-{i}", "source": f"https://example.org/{label}/{i}",
             "confidence": "HIGH"}
            for i in range(3)
        ],
        "strongest_supporting_argument": f"The case for {label}.",
        "weakest_link": f"Weakest link in {label}'s evidence.",
    }


def _advocate_case_payload(label: str) -> dict:
    return {
        "candidate_label": label,
        "case_statement": f"The case for {label}.",
        "load_bearing_claims": [
            {"claim": f"{label}-lb-{i}", "if_this_fails": f"{label} fails"}
            for i in range(2)
        ],
        "confidence": 0.6,
    }


def _attacks_payload(from_label: str, other_labels: list[str]) -> dict:
    return {
        "from_label": from_label,
        "attacks": [
            {
                "target_label": t,
                "attacked_assumption": f"{t}'s claim 0",
                "attack_argument": f"Attack from {from_label} on {t}",
                "cited_evidence_urls": [f"https://example.org/{t}/0"],
                "steelman_of_attack": "Their best reply.",
            }
            for t in other_labels
        ],
    }


def _final_deliverable_payload() -> dict:
    return {
        "question_restated": "Will X happen by 2030?",
        "committed_answer": "Most likely yes, with caveats.",
        "confidence": 0.65,
        "cruxes": [
            {
                "crux_question": "Does Y hold?",
                "side_a_position": "Y holds.",
                "side_a_debaters": ["camp-0"],
                "side_a_steelman": "Strong evidence A.",
                "side_b_position": "Y fails.",
                "side_b_debaters": ["camp-1"],
                "side_b_steelman": "Strong evidence B.",
                "resolving_evidence": "Watch for Z by 2027.",
            },
            {
                "crux_question": "Does W matter?",
                "side_a_position": "W matters.",
                "side_a_debaters": ["camp-2"],
                "side_a_steelman": "Strong evidence C.",
                "side_b_position": "W is noise.",
                "side_b_debaters": ["camp-0"],
                "side_b_steelman": "Strong evidence D.",
                "resolving_evidence": "Watch for V by 2027.",
            },
        ],
        "minority_position": None,
        "mainstream_prior": "The conventional answer.",
        "deliberation_vs_mainstream": "modifies",
        "forward_claim": {
            "horizon": "2030",
            "most_likely": "X happens with friction.",
            "plausible_alternative": "X is delayed past 2032.",
            "would_surprise_the_system": "X is wholly reversed.",
            "falsifiers": ["Indicator Z hits target by 2027."],
        },
        "biggest_things_that_could_be_wrong": [
            "Claim A may be wrong.", "Claim B may be wrong.",
        ],
        "sycophancy_flags": [],
        "report_markdown": "# Report\n\n" + ("Body. " * 50),
        "recommendation_markdown": "Recommendation paragraph that fits within bounds.",
    }


# =============================================================================
# FakeAgentExecutor — records calls and dispatches by agent_name
# =============================================================================


class FakeAgentExecutor:
    """Stand-in for the production execute_agent_fn.

    Records every call, dispatches to canned payloads based on the
    agent name and inputs. Tests inspect `self.calls` to verify topology.
    """

    def __init__(self, *, framer_n: int = 3, validator_verdict: str = "approved"):
        self.calls: list[dict[str, Any]] = []
        self.framer_n = framer_n
        self.validator_verdict = validator_verdict

    async def __call__(
        self, *,
        agent_name: str,
        instructions: str,
        inputs: dict,
        usage_limits,
    ) -> dict:
        self.calls.append({
            "agent": agent_name,
            "instructions": instructions,
            "inputs": inputs,
        })
        meta = {"cost_usd": 0.01, "input_tokens": 100, "output_tokens": 50}

        if agent_name.endswith("framer.agent"):
            return {"output": _candidate_set_payload(self.framer_n), "_meta": meta}
        if agent_name.endswith("framings_validator.agent"):
            return {
                "output": _framing_validation_payload(
                    verdict=self.validator_verdict,
                    revised_n=self.framer_n,
                ),
                "_meta": meta,
            }
        if agent_name.endswith("side_researcher.agent"):
            return {"output": _side_packet_payload(inputs["candidate"]["label"]), "_meta": meta}
        if agent_name.endswith("advocate.agent"):
            phase = inputs.get("_phase")
            if phase == "blind_case":
                return {"output": _advocate_case_payload(inputs["candidate"]["label"]), "_meta": meta}
            elif phase == "attacks":
                other_labels = [c["candidate_label"] for c in inputs["other_cases"]]
                return {"output": _attacks_payload(inputs["own_label"], other_labels), "_meta": meta}
            raise RuntimeError(f"Advocate called without _phase: {inputs!r}")
        if agent_name.endswith("judge.agent"):
            return {"output": _final_deliverable_payload(), "_meta": meta}
        raise RuntimeError(f"Unmocked agent: {agent_name}")

    def calls_to(self, agent_suffix: str) -> list[dict]:
        return [c for c in self.calls if c["agent"].endswith(agent_suffix)]


# =============================================================================
# Topology tests
# =============================================================================


@pytest.mark.asyncio
async def test_executor_dispatches_all_phases_in_order():
    """Phase 1 (framer + validator) -> Phase 2 (3 researchers) -> Phase 3
    (3 blind advocates) -> Phase 4 (3 attackers) -> Phase 5 (judge)."""
    fake = FakeAgentExecutor(framer_n=3)
    result = await execute_advocate_judge_loop(
        task_id="t1",
        question="Will X happen by 2030?",
        config=AdvocateJudgeConfig(min_candidates=3, max_candidates=3),
        execute_agent_fn=fake,
        mission_id=None,
    )
    assert result.status == TaskStatus.SUCCESS

    # Expected: 1 framer + 1 validator + 3 researchers + 3 blind advocates
    #           + 3 attackers + 1 judge = 12 calls.
    assert len(fake.calls) == 12

    # Order: first two calls are framer + validator.
    assert fake.calls[0]["agent"].endswith("framer.agent")
    assert fake.calls[1]["agent"].endswith("framings_validator.agent")
    # Judge is the last call.
    assert fake.calls[-1]["agent"].endswith("judge.agent")


@pytest.mark.asyncio
async def test_executor_information_asymmetry_at_research():
    """Each side researcher sees ONLY its own candidate."""
    fake = FakeAgentExecutor(framer_n=3)
    await execute_advocate_judge_loop(
        task_id="t1",
        question="Q",
        config=AdvocateJudgeConfig(min_candidates=3, max_candidates=3),
        execute_agent_fn=fake,
        mission_id=None,
    )

    researcher_calls = fake.calls_to("side_researcher.agent")
    assert len(researcher_calls) == 3

    for call in researcher_calls:
        # Only `candidate` (singular) in inputs — never `candidates` or
        # references to other camps.
        assert "candidate" in call["inputs"]
        assert "candidates" not in call["inputs"]
        # The candidate dict is for ONE label.
        assert isinstance(call["inputs"]["candidate"], dict)
        assert "label" in call["inputs"]["candidate"]


@pytest.mark.asyncio
async def test_executor_blindness_at_blind_case():
    """Each blind-advocate sees ONLY own packet — not others'."""
    fake = FakeAgentExecutor(framer_n=3)
    await execute_advocate_judge_loop(
        task_id="t1",
        question="Q",
        config=AdvocateJudgeConfig(min_candidates=3, max_candidates=3),
        execute_agent_fn=fake,
        mission_id=None,
    )

    blind_calls = [
        c for c in fake.calls_to("advocate.agent")
        if c["inputs"].get("_phase") == "blind_case"
    ]
    assert len(blind_calls) == 3

    for call in blind_calls:
        assert "own_packet" in call["inputs"]
        assert "all_packets" not in call["inputs"]
        assert "other_cases" not in call["inputs"]
        assert "all_cases" not in call["inputs"]


@pytest.mark.asyncio
async def test_executor_full_information_at_attacks():
    """Each attacker sees ALL packets + ALL other cases."""
    fake = FakeAgentExecutor(framer_n=3)
    await execute_advocate_judge_loop(
        task_id="t1",
        question="Q",
        config=AdvocateJudgeConfig(min_candidates=3, max_candidates=3),
        execute_agent_fn=fake,
        mission_id=None,
    )

    attack_calls = [
        c for c in fake.calls_to("advocate.agent")
        if c["inputs"].get("_phase") == "attacks"
    ]
    assert len(attack_calls) == 3

    for call in attack_calls:
        assert "all_packets" in call["inputs"]
        assert "other_cases" in call["inputs"]
        assert "own_label" in call["inputs"]
        # Other cases excludes own (length N-1 = 2 here).
        assert len(call["inputs"]["other_cases"]) == 2
        # All packets includes own (length N = 3).
        assert len(call["inputs"]["all_packets"]) == 3


@pytest.mark.asyncio
async def test_executor_judge_sees_everything():
    """Judge input contains candidate_set + packets + cases + attacks."""
    fake = FakeAgentExecutor(framer_n=3)
    await execute_advocate_judge_loop(
        task_id="t1",
        question="Q",
        config=AdvocateJudgeConfig(min_candidates=3, max_candidates=3),
        execute_agent_fn=fake,
        mission_id=None,
    )

    judge_calls = fake.calls_to("judge.agent")
    assert len(judge_calls) == 1
    judge_inputs = judge_calls[0]["inputs"]
    assert "candidate_set" in judge_inputs
    assert len(judge_inputs["packets"]) == 3
    assert len(judge_inputs["cases"]) == 3
    assert len(judge_inputs["attacks"]) == 3


@pytest.mark.asyncio
async def test_executor_per_side_model_propagates():
    """`_resolved_model` in each side-call input reflects the rotation."""
    fake = FakeAgentExecutor(framer_n=3)
    await execute_advocate_judge_loop(
        task_id="t1",
        question="Q",
        config=AdvocateJudgeConfig(
            min_candidates=3,
            max_candidates=3,
            side_models=["model-a", "model-b", "model-c"],
        ),
        execute_agent_fn=fake,
        mission_id=None,
    )

    # All per-side calls (researcher + blind advocate + attacker) for
    # side index i should carry _resolved_model = "model-<i>".
    expected_per_label = {"camp-0": "model-a", "camp-1": "model-b", "camp-2": "model-c"}

    for call in fake.calls_to("side_researcher.agent"):
        label = call["inputs"]["candidate"]["label"]
        assert call["inputs"]["_resolved_model"] == expected_per_label[label]

    blind_calls = [
        c for c in fake.calls_to("advocate.agent")
        if c["inputs"].get("_phase") == "blind_case"
    ]
    for call in blind_calls:
        label = call["inputs"]["candidate"]["label"]
        assert call["inputs"]["_resolved_model"] == expected_per_label[label]

    attack_calls = [
        c for c in fake.calls_to("advocate.agent")
        if c["inputs"].get("_phase") == "attacks"
    ]
    for call in attack_calls:
        label = call["inputs"]["own_label"]
        assert call["inputs"]["_resolved_model"] == expected_per_label[label]


@pytest.mark.asyncio
async def test_executor_handles_revised_framing():
    """If validator revises the set, downstream phases use the revised set."""
    fake = FakeAgentExecutor(framer_n=3, validator_verdict="revised")
    result = await execute_advocate_judge_loop(
        task_id="t1",
        question="Q",
        config=AdvocateJudgeConfig(min_candidates=3, max_candidates=3),
        execute_agent_fn=fake,
        mission_id=None,
    )
    assert result.status == TaskStatus.SUCCESS
    # Still 3 researchers etc. (revised_set has same n).
    assert len(fake.calls_to("side_researcher.agent")) == 3


@pytest.mark.asyncio
async def test_executor_skips_persistence_when_mission_id_none():
    """mission_id=None means no _persist_artifacts call (no DB needed)."""
    fake = FakeAgentExecutor(framer_n=3)
    # If persistence were attempted, store_artifact would fail (no DB).
    # If this test passes without raising, persistence was correctly skipped.
    result = await execute_advocate_judge_loop(
        task_id="t1",
        question="Q",
        config=AdvocateJudgeConfig(min_candidates=3, max_candidates=3),
        execute_agent_fn=fake,
        mission_id=None,
    )
    assert result.status == TaskStatus.SUCCESS


@pytest.mark.asyncio
async def test_executor_fails_loud_on_unwired_judge_model(monkeypatch):
    """Judge-model provider availability check raises at start."""
    # Re-stub: only judge model is unwired.
    monkeypatch.setattr(
        "modules.backend.agents.mission_control.dispatch.advocate_judge_loop._provider_is_wired",
        lambda model_name: model_name != "unwired:provider",
    )
    fake = FakeAgentExecutor()
    result = await execute_advocate_judge_loop(
        task_id="t1",
        question="Q",
        config=AdvocateJudgeConfig(judge_model="unwired:provider"),
        execute_agent_fn=fake,
        mission_id=None,
    )
    # Should fail in Phase 0 validation, before any agent dispatch.
    assert result.status == TaskStatus.FAILED
    assert "unwired:provider" in result.output_reference["error"]
    assert len(fake.calls) == 0  # No agent calls made.


# =============================================================================
# Side-model rotation (unit tests for _resolve_side_models directly)
# =============================================================================


def test_resolve_side_models_uses_default_rotation_when_explicit_is_none(monkeypatch):
    monkeypatch.setattr(
        "modules.backend.agents.mission_control.dispatch.advocate_judge_loop._provider_is_wired",
        lambda m: True,
    )
    resolved, notes = _resolve_side_models(n_sides=3, explicit=None)
    assert resolved == list(DEFAULT_SIDE_MODEL_ROTATION[:3])
    assert notes == []


def test_resolve_side_models_drops_unwired_providers(monkeypatch):
    """If a provider is unwired, that entry is dropped (with a note)."""
    monkeypatch.setattr(
        "modules.backend.agents.mission_control.dispatch.advocate_judge_loop._provider_is_wired",
        lambda m: not m.startswith("google:"),  # Pretend google isn't wired.
    )
    resolved, notes = _resolve_side_models(n_sides=3, explicit=None)
    # Default rotation has 2 non-google entries before the google one; the
    # 3rd slot falls back to copilot:claude-sonnet-4.6 (the 4th entry).
    assert "google:gemini-2.5-pro" not in resolved
    assert len(resolved) == 3
    # A "dropped" note should mention google.
    assert any("google:gemini-2.5-pro" in n for n in notes)


def test_resolve_side_models_repeats_when_n_exceeds_rotation(monkeypatch):
    """If N > unique models, families repeat with a reduced-heterogeneity note."""
    monkeypatch.setattr(
        "modules.backend.agents.mission_control.dispatch.advocate_judge_loop._provider_is_wired",
        lambda m: m == "copilot:claude-opus-4.6",  # Only one model wired.
    )
    resolved, notes = _resolve_side_models(n_sides=3, explicit=None)
    assert resolved == ["copilot:claude-opus-4.6"] * 3
    assert any("heterogeneity is reduced" in n.lower() for n in notes)


def test_resolve_side_models_honours_explicit_override(monkeypatch):
    monkeypatch.setattr(
        "modules.backend.agents.mission_control.dispatch.advocate_judge_loop._provider_is_wired",
        lambda m: True,
    )
    resolved, notes = _resolve_side_models(
        n_sides=2, explicit=["openai:gpt-5.5", "anthropic:claude-opus-4-7"],
    )
    assert resolved == ["openai:gpt-5.5", "anthropic:claude-opus-4-7"]
    assert notes == []


def test_resolve_side_models_raises_when_nothing_wired(monkeypatch):
    monkeypatch.setattr(
        "modules.backend.agents.mission_control.dispatch.advocate_judge_loop._provider_is_wired",
        lambda m: False,
    )
    with pytest.raises(ValueError, match="No usable models"):
        _resolve_side_models(n_sides=3, explicit=None)
