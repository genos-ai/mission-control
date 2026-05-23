"""
Tests for deliberation schemas (Plan 79 §5).

The schema constraints do the anti-flattening work that prompts cannot.
These tests pin down the constraint surface so prompt drift cannot
silently weaken the guarantees.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from modules.backend.schemas.deliberation import (
    CriticAttack,
    CriticReport,
    CruxRecord,
    ConvergenceFlag,
    DebaterTurn,
    ExpertDisagreement,
    FinalDeliverable,
    ForwardClaim,
    LoadBearingClaim,
    MinorityPosition,
    ResearchPacket,
    ResearchPacketVerification,
    SourcedClaim,
    StanceDelta,
)


# Reusable fixtures -----------------------------------------------------------


def _packet(**overrides):
    base = dict(
        question_restated="Will X happen by 2030?",
        what_is_known=[
            SourcedClaim(claim="A", source="src1", confidence="HIGH"),
            SourcedClaim(claim="B", source="src2", confidence="MEDIUM"),
            SourcedClaim(claim="C", source="src3", confidence="LOW"),
        ],
        expert_disagreements=[
            ExpertDisagreement(
                topic="t1", camps=["A", "B"],
                side_a_steelman="a", side_b_steelman="b",
                resolving_evidence="e",
            ),
            ExpertDisagreement(
                topic="t2", camps=["C", "D"],
                side_a_steelman="c", side_b_steelman="d",
                resolving_evidence="f",
            ),
        ],
        mainstream_consensus="Mainstream view",
        under_discussed_angles=["a1", "a2", "a3"],
    )
    base.update(overrides)
    return ResearchPacket(**base)


def _critic_attack():
    return CriticAttack(
        load_bearing_assumption="X",
        attack="Y",
        steelman_of_attack="Z",
        what_would_vindicate_the_debater="W",
    )


def _full_attacks():
    return {
        "systems": _critic_attack(),
        "quant": _critic_attack(),
        "empiricist": _critic_attack(),
        "ethicist": _critic_attack(),
    }


def _convergence_none():
    return ConvergenceFlag(kind="none")


def _crux(side_a_debaters, side_b_debaters):
    return CruxRecord(
        crux_question="cq",
        side_a_position="a",
        side_a_debaters=side_a_debaters,
        side_a_steelman="as",
        side_b_position="b",
        side_b_debaters=side_b_debaters,
        side_b_steelman="bs",
        resolving_evidence="e",
    )


def _forward():
    return ForwardClaim(
        horizon="2030",
        most_likely="X",
        plausible_alternative="Y",
        would_surprise_the_system="Z",
        falsifiers=["if A then position fails"],
    )


def _deliverable(**overrides):
    base = dict(
        question_restated="Will X happen by 2030?",
        committed_answer="Yes with caveats.",
        confidence=0.7,
        cruxes=[
            _crux(["systems"], ["quant"]),
            _crux(["empiricist"], ["ethicist"]),
        ],
        minority_position=None,
        mainstream_prior="Mainstream view",
        deliberation_vs_mainstream="modifies",
        forward_claim=_forward(),
        biggest_things_that_could_be_wrong=["a is wrong", "b is wrong"],
        report_markdown="x" * 200,  # min_length=200
        recommendation_markdown="Watch for these specific reversals.",
    )
    base.update(overrides)
    return FinalDeliverable(**base)


# =============================================================================
# ResearchPacket
# =============================================================================


class TestResearchPacket:
    def test_minimal_valid(self):
        p = _packet()
        assert len(p.what_is_known) == 3
        assert len(p.expert_disagreements) == 2

    def test_requires_three_sourced_claims(self):
        with pytest.raises(ValidationError):
            _packet(what_is_known=[
                SourcedClaim(claim="A", source="s", confidence="HIGH"),
                SourcedClaim(claim="B", source="s", confidence="HIGH"),
            ])

    def test_requires_two_disagreements(self):
        with pytest.raises(ValidationError):
            _packet(expert_disagreements=[
                ExpertDisagreement(
                    topic="t", camps=["a", "b"],
                    side_a_steelman="x", side_b_steelman="y",
                    resolving_evidence="e",
                ),
            ])

    def test_caps_disagreements_at_five(self):
        with pytest.raises(ValidationError):
            _packet(expert_disagreements=[
                ExpertDisagreement(
                    topic=f"t{i}", camps=["a", "b"],
                    side_a_steelman="x", side_b_steelman="y",
                    resolving_evidence="e",
                ) for i in range(6)
            ])

    def test_under_discussed_angles_bounds(self):
        with pytest.raises(ValidationError):
            _packet(under_discussed_angles=["only one"])
        with pytest.raises(ValidationError):
            _packet(under_discussed_angles=[str(i) for i in range(6)])


class TestSourcedClaim:
    def test_confidence_literal(self):
        # Only HIGH/MEDIUM/LOW allowed.
        with pytest.raises(ValidationError):
            SourcedClaim(claim="X", source="s", confidence="UNCERTAIN")


# =============================================================================
# ResearchPacketVerification
# =============================================================================


class TestResearchPacketVerification:
    def test_minimal_valid(self):
        v = ResearchPacketVerification(
            passed=True,
            mainstream_consensus_looks_plausible=True,
            under_discussed_angles_actually_under_discussed=True,
        )
        assert v.issues == []
        assert v.issues_text == ""

    def test_carries_both_issues_forms(self):
        # S8 fix: issues_text is the human-readable joined form used by
        # the halt_workflow notification template.
        v = ResearchPacketVerification(
            passed=False,
            issues=["mainstream consensus is wrong", "sources fabricated"],
            issues_text="- mainstream consensus is wrong\n- sources fabricated",
            mainstream_consensus_looks_plausible=False,
            under_discussed_angles_actually_under_discussed=True,
        )
        assert v.passed is False
        assert len(v.issues) == 2
        assert "mainstream" in v.issues_text


# =============================================================================
# DebaterTurn
# =============================================================================


class TestDebaterTurn:
    def _turn(self, **overrides):
        base = dict(
            debater_id="systems",
            round_index=0,
            position="My position.",
            load_bearing_claims=[
                LoadBearingClaim(claim="c1", if_this_fails="f1"),
                LoadBearingClaim(claim="c2", if_this_fails="f2"),
            ],
            what_would_change_my_mind="Specific evidence.",
            decision="HOLD",
            decision_justification="No refutation offered.",
            confidence=0.7,
        )
        base.update(overrides)
        return DebaterTurn(**base)

    def test_minimal_valid(self):
        t = self._turn()
        assert t.debater_id == "systems"
        assert t.decision == "HOLD"

    def test_debater_id_literal(self):
        with pytest.raises(ValidationError):
            self._turn(debater_id="philosopher")  # not in the 4 allowed

    def test_decision_literal(self):
        # The four-state sycophancy detector must use exactly these values.
        for valid in ("HOLD", "REFINE", "CONCEDE_PARTIAL", "CONCEDE_FULL"):
            t = self._turn(decision=valid)
            assert t.decision == valid
        with pytest.raises(ValidationError):
            self._turn(decision="DISAGREE")

    def test_requires_at_least_two_load_bearing_claims(self):
        with pytest.raises(ValidationError):
            self._turn(load_bearing_claims=[
                LoadBearingClaim(claim="only one", if_this_fails="x"),
            ])

    def test_caps_load_bearing_claims_at_three(self):
        with pytest.raises(ValidationError):
            self._turn(load_bearing_claims=[
                LoadBearingClaim(claim=f"c{i}", if_this_fails="f")
                for i in range(4)
            ])

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            self._turn(confidence=1.5)
        with pytest.raises(ValidationError):
            self._turn(confidence=-0.1)

    def test_round_index_bounds(self):
        with pytest.raises(ValidationError):
            self._turn(round_index=6)


# =============================================================================
# CriticReport (the 4-key validator)
# =============================================================================


class TestCriticReport:
    def test_valid_with_all_four_debaters(self):
        report = CriticReport(
            round_index=0,
            attacks=_full_attacks(),
            convergence_flag=_convergence_none(),
        )
        assert set(report.attacks.keys()) == {
            "systems", "quant", "empiricist", "ethicist",
        }

    def test_rejects_missing_debater(self):
        # Drop one — must raise.
        partial = _full_attacks()
        del partial["ethicist"]
        with pytest.raises(ValidationError, match="missing debater"):
            CriticReport(
                round_index=0,
                attacks=partial,
                convergence_flag=_convergence_none(),
            )

    def test_rejects_extra_debater(self):
        extra = _full_attacks()
        extra["sociologist"] = _critic_attack()
        with pytest.raises(ValidationError, match="unknown debater"):
            CriticReport(
                round_index=0,
                attacks=extra,
                convergence_flag=_convergence_none(),
            )

    def test_convergence_flag_kinds(self):
        for kind in ("shared_hidden_assumption", "paraphrase",
                     "collapse_to_mainstream", "none"):
            CriticReport(
                round_index=1,
                attacks=_full_attacks(),
                convergence_flag=ConvergenceFlag(kind=kind),
            )
        with pytest.raises(ValidationError):
            ConvergenceFlag(kind="suspicious")


# =============================================================================
# StanceDelta
# =============================================================================


class TestStanceDelta:
    def test_minimal_valid(self):
        d = StanceDelta(
            delta=0.08,
            threshold=0.15,
            should_continue=False,
            gate="halt",
            per_debater={"systems": 0.05, "quant": 0.1, "empiricist": 0.07,
                         "ethicist": 0.1},
            reasoning="stance change 0.08 < threshold 0.15; no active revision",
        )
        assert d.should_continue is False
        assert d.gate == "halt"

    def test_delta_must_be_non_negative(self):
        with pytest.raises(ValidationError):
            StanceDelta(
                delta=-0.1,
                threshold=0.15,
                should_continue=False,
                gate="halt",
                per_debater={},
                reasoning="",
            )

    def test_gate_is_literal(self):
        # Catches typos in the option-key string emitted by
        # compute_stance_delta.
        with pytest.raises(ValidationError):
            StanceDelta(
                delta=0.0,
                threshold=0.15,
                should_continue=False,
                gate="stop",  # not in Literal["continue", "halt"]
                per_debater={},
                reasoning="",
            )


# =============================================================================
# FinalDeliverable — the anti-flattening machinery
# =============================================================================


class TestFinalDeliverableAntiFlattening:
    """Plan 79 §5 — these constraints are the load-bearing guarantee that
    the synthesiser cannot quietly collapse the deliberation to a single
    answer. Tests pin the surface so prompt drift cannot weaken them."""

    def test_minimal_valid(self):
        d = _deliverable()
        assert d.deliberation_vs_mainstream == "modifies"
        assert len(d.cruxes) == 2

    def test_requires_at_least_two_cruxes(self):
        # The schema floor for cruxes: a deliverable with one crux is a
        # collapsed deliberation. Reject.
        with pytest.raises(ValidationError, match="at least 2"):
            _deliverable(cruxes=[_crux(["systems"], ["quant"])])

    def test_caps_cruxes_at_five(self):
        # Cruxes proliferating means the synthesiser failed to filter
        # noise from real disagreement. Cap.
        with pytest.raises(ValidationError):
            _deliverable(cruxes=[
                _crux(["systems"], ["quant"]) for _ in range(6)
            ])

    def test_minority_position_can_be_none(self):
        # "No minority position survived" must be an explicit None, not
        # a missing field.
        d = _deliverable(minority_position=None)
        assert d.minority_position is None

    def test_minority_position_can_be_record(self):
        m = MinorityPosition(
            debater="empiricist",
            position="held contrarian view",
            why_it_survived="critic could not break it",
            why_it_merits_preservation="track record",
        )
        d = _deliverable(minority_position=m)
        assert d.minority_position.debater == "empiricist"

    def test_merely_reproduces_is_a_typed_enum_value(self):
        # The whole point: "we just collapsed to the mainstream" is a
        # detectable enum case, not a hidden failure.
        d = _deliverable(deliberation_vs_mainstream="merely_reproduces")
        assert d.deliberation_vs_mainstream == "merely_reproduces"

    def test_deliberation_vs_mainstream_constrained(self):
        with pytest.raises(ValidationError):
            _deliverable(deliberation_vs_mainstream="ignores")

    def test_biggest_things_lower_bound(self):
        # The synthesiser must name at least 2 things that could be wrong.
        with pytest.raises(ValidationError):
            _deliverable(biggest_things_that_could_be_wrong=["only one"])

    def test_biggest_things_upper_bound(self):
        # More than 3 means noise; cap.
        with pytest.raises(ValidationError):
            _deliverable(biggest_things_that_could_be_wrong=[
                "one", "two", "three", "four",
            ])

    def test_report_markdown_min_length(self):
        # A short report_markdown means the synthesiser didn't actually
        # render the full deliverable. Fail.
        with pytest.raises(ValidationError):
            _deliverable(report_markdown="short")

    def test_recommendation_markdown_required(self):
        # Must be present; cannot be empty short string.
        with pytest.raises(ValidationError):
            _deliverable(recommendation_markdown="too short")

    def test_forward_claim_requires_falsifier(self):
        with pytest.raises(ValidationError):
            _deliverable(forward_claim=ForwardClaim(
                horizon="2030", most_likely="X",
                plausible_alternative="Y",
                would_surprise_the_system="Z",
                falsifiers=[],  # empty → reject
            ))

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            _deliverable(confidence=1.5)
