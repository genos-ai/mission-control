"""
Tests for Advocate-Judge deliberation schemas (Plan 80 §6).

These tests pin down the schema-level constraints that the executor
relies on. The validation here is mechanical (rejects bad labels,
enforces length bounds, gates revised_set on verdict) so prompt
drift cannot quietly weaken the guarantees.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from modules.backend.schemas.deliberation import LoadBearingClaim, SourcedClaim
from modules.backend.schemas.deliberation_advocate_judge import (
    AdvocateCase,
    AdvocateJudgeConfig,
    Attack,
    AttacksByAdvocate,
    CandidateAnswer,
    CandidateSet,
    FramingValidation,
    SidePacket,
)


# =============================================================================
# CandidateAnswer
# =============================================================================


def _candidate(**overrides) -> CandidateAnswer:
    return CandidateAnswer(**{
        "label": "institutional-friction",
        "statement": "Adoption is slow.",
        "rationale_for_inclusion": "Held by the Solow Paradox school.",
        **overrides,
    })


def test_candidate_answer_valid():
    c = _candidate()
    assert c.label == "institutional-friction"


def test_candidate_answer_rejects_uppercase_label():
    with pytest.raises(ValidationError, match="kebab-case"):
        _candidate(label="InstitutionalFriction")


def test_candidate_answer_rejects_label_with_space():
    with pytest.raises(ValidationError, match="kebab-case"):
        _candidate(label="institutional friction")


def test_candidate_answer_rejects_label_leading_or_trailing_hyphen():
    with pytest.raises(ValidationError, match="start or end with a hyphen"):
        _candidate(label="-institutional")
    with pytest.raises(ValidationError, match="start or end with a hyphen"):
        _candidate(label="institutional-")


def test_candidate_answer_allows_digits_in_label():
    c = _candidate(label="post-2030-shift")
    assert c.label == "post-2030-shift"


def test_candidate_answer_empty_label_rejected():
    with pytest.raises(ValidationError):
        _candidate(label="")


# =============================================================================
# CandidateSet
# =============================================================================


def _set(n: int = 3, **overrides) -> CandidateSet:
    candidates = [
        _candidate(label=f"label-{i}", statement=f"stmt {i}")
        for i in range(n)
    ]
    return CandidateSet(**{
        "candidates": candidates,
        "mainstream_consensus": "The conventional view.",
        **overrides,
    })


def test_candidate_set_valid_three():
    s = _set(3)
    assert len(s.candidates) == 3


def test_candidate_set_valid_five():
    s = _set(5)
    assert len(s.candidates) == 5


def test_candidate_set_rejects_two():
    with pytest.raises(ValidationError, match="at least 3"):
        _set(2)


def test_candidate_set_rejects_six():
    with pytest.raises(ValidationError, match="at most 5"):
        _set(6)


def test_candidate_set_rejects_duplicate_labels():
    duplicated = [
        _candidate(label="alpha"),
        _candidate(label="beta"),
        _candidate(label="alpha"),  # dup
    ]
    with pytest.raises(ValidationError, match="unique"):
        CandidateSet(
            candidates=duplicated,
            mainstream_consensus="The conventional view.",
        )


# =============================================================================
# FramingValidation
# =============================================================================


def test_framing_validation_approved_no_revised():
    v = FramingValidation(verdict="approved", rationale="Survived audit.")
    assert v.verdict == "approved"
    assert v.revised_set is None


def test_framing_validation_revised_with_set():
    v = FramingValidation(
        verdict="revised",
        revised_set=_set(),
        rationale="Added missing school.",
    )
    assert v.verdict == "revised"
    assert v.revised_set is not None


def test_framing_validation_approved_with_revised_rejected():
    with pytest.raises(ValidationError, match="None when verdict == 'approved'"):
        FramingValidation(
            verdict="approved",
            revised_set=_set(),
            rationale="Survived.",
        )


def test_framing_validation_revised_without_set_rejected():
    with pytest.raises(ValidationError, match="present when verdict == 'revised'"):
        FramingValidation(
            verdict="revised",
            revised_set=None,
            rationale="Should have a set.",
        )


# =============================================================================
# SidePacket
# =============================================================================


def _packet(label: str = "alpha", n_claims: int = 3) -> SidePacket:
    return SidePacket(
        candidate_label=label,
        sourced_claims=[
            SourcedClaim(
                claim=f"claim {i}",
                source=f"https://example.org/{i}",
                confidence="HIGH",
            )
            for i in range(n_claims)
        ],
        strongest_supporting_argument="The case in 2-4 sentences.",
        weakest_link="Claim 0 relies on a single source.",
    )


def test_side_packet_valid():
    p = _packet()
    assert p.candidate_label == "alpha"
    assert len(p.sourced_claims) == 3


def test_side_packet_requires_three_claims_min():
    with pytest.raises(ValidationError):
        _packet(n_claims=2)


def test_side_packet_rejects_more_than_ten_claims():
    with pytest.raises(ValidationError):
        _packet(n_claims=11)


def test_side_packet_requires_weakest_link():
    with pytest.raises(ValidationError):
        SidePacket(
            candidate_label="alpha",
            sourced_claims=_packet().sourced_claims,
            strongest_supporting_argument="argument",
            weakest_link="",  # empty = refusal
        )


# =============================================================================
# AdvocateCase
# =============================================================================


def _case(label: str = "alpha") -> AdvocateCase:
    return AdvocateCase(
        candidate_label=label,
        case_statement="The strongest case in 2-5 sentences.",
        load_bearing_claims=[
            LoadBearingClaim(claim="lb1", if_this_fails="fail1"),
            LoadBearingClaim(claim="lb2", if_this_fails="fail2"),
        ],
        confidence=0.6,
    )


def test_advocate_case_valid():
    c = _case()
    assert c.confidence == 0.6


def test_advocate_case_requires_two_load_bearing_min():
    with pytest.raises(ValidationError):
        AdvocateCase(
            candidate_label="alpha",
            case_statement="case",
            load_bearing_claims=[
                LoadBearingClaim(claim="lb1", if_this_fails="fail1"),
            ],
            confidence=0.5,
        )


def test_advocate_case_rejects_four_load_bearing():
    with pytest.raises(ValidationError):
        AdvocateCase(
            candidate_label="alpha",
            case_statement="case",
            load_bearing_claims=[
                LoadBearingClaim(claim=f"lb{i}", if_this_fails=f"fail{i}")
                for i in range(4)
            ],
            confidence=0.5,
        )


def test_advocate_case_confidence_above_one_rejected():
    with pytest.raises(ValidationError):
        AdvocateCase(
            candidate_label="alpha",
            case_statement="case",
            load_bearing_claims=_case().load_bearing_claims,
            confidence=1.5,
        )


def test_advocate_case_confidence_negative_rejected():
    with pytest.raises(ValidationError):
        AdvocateCase(
            candidate_label="alpha",
            case_statement="case",
            load_bearing_claims=_case().load_bearing_claims,
            confidence=-0.1,
        )


# =============================================================================
# Attack / AttacksByAdvocate
# =============================================================================


def _attack(target: str = "beta") -> Attack:
    return Attack(
        target_label=target,
        attacked_assumption="That claim X holds.",
        attack_argument="It doesn't because Y.",
        cited_evidence_urls=["https://example.org/1"],
        steelman_of_attack="They'd reply with Z, which doesn't survive W.",
    )


def test_attack_valid():
    a = _attack()
    assert a.target_label == "beta"


def test_attack_requires_at_least_one_url():
    with pytest.raises(ValidationError):
        Attack(
            target_label="beta",
            attacked_assumption="x",
            attack_argument="y",
            cited_evidence_urls=[],  # empty
            steelman_of_attack="z",
        )


def test_attacks_by_advocate_valid_with_two():
    a = AttacksByAdvocate(
        from_label="alpha",
        attacks=[_attack("beta"), _attack("gamma")],
    )
    assert len(a.attacks) == 2


def test_attacks_by_advocate_rejects_empty_attacks():
    with pytest.raises(ValidationError):
        AttacksByAdvocate(from_label="alpha", attacks=[])


# =============================================================================
# AdvocateJudgeConfig
# =============================================================================


def test_config_defaults():
    c = AdvocateJudgeConfig()
    assert c.min_candidates == 3
    assert c.max_candidates == 4
    assert c.side_models is None
    assert c.judge_model == "copilot:claude-opus-4.7"


def test_config_max_lt_min_rejected():
    with pytest.raises(ValidationError, match="max_candidates"):
        AdvocateJudgeConfig(min_candidates=4, max_candidates=3)


def test_config_from_dict_defaults_when_empty():
    c = AdvocateJudgeConfig.from_dict({})
    assert c.min_candidates == 3
    assert c.side_models is None


def test_config_from_dict_with_side_models_list():
    c = AdvocateJudgeConfig.from_dict({
        "side_models": ["copilot:claude-opus-4.6", "copilot:gpt-5.5"],
    })
    assert c.side_models == ["copilot:claude-opus-4.6", "copilot:gpt-5.5"]


def test_config_from_dict_with_side_models_csv_string():
    """YAML/CLI convenience: side_models can come in as a CSV string."""
    c = AdvocateJudgeConfig.from_dict({
        "side_models": "copilot:claude-opus-4.6, copilot:gpt-5.5",
    })
    assert c.side_models == ["copilot:claude-opus-4.6", "copilot:gpt-5.5"]


def test_config_from_dict_with_empty_csv_string_becomes_none():
    c = AdvocateJudgeConfig.from_dict({"side_models": "   "})
    assert c.side_models is None


def test_config_from_dict_rejects_non_dict():
    with pytest.raises(TypeError):
        AdvocateJudgeConfig.from_dict("not a dict")
