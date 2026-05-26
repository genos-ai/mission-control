"""
Deliberation schemas (Plan 79).

Pydantic models for the Think Tank multi-agent deliberation workflow:
research packet, packet verification, debater turn, critic report,
stance delta, final deliverable.

The anti-flattening machinery lives in this file. The synthesiser's
output is constrained at the schema level so the protection survives
into storage (the structured FinalDeliverable is persisted as a JSON
artifact, see Plan 79 §7 store-deliverable-json step).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


# =============================================================================
# Research packet (researcher output)
# =============================================================================


class SourcedClaim(BaseModel):
    """A single sourced claim in the research packet."""

    model_config = ConfigDict(extra="forbid")

    claim: str = Field(..., min_length=1, max_length=1000)
    source: str = Field(..., min_length=1, max_length=500)
    confidence: Literal["HIGH", "MEDIUM", "LOW"]


class ExpertDisagreement(BaseModel):
    """A live disagreement in the relevant literature."""

    model_config = ConfigDict(extra="forbid")

    topic: str = Field(..., min_length=1, max_length=500)
    camps: list[str] = Field(..., min_length=2)
    side_a_steelman: str
    side_b_steelman: str
    resolving_evidence: str


class ResearchPacket(BaseModel):
    """Output of deliberation.researcher.agent."""

    model_config = ConfigDict(extra="forbid")

    question_restated: str = Field(..., min_length=1, max_length=2000)
    what_is_known: list[SourcedClaim] = Field(..., min_length=3)
    expert_disagreements: list[ExpertDisagreement] = Field(
        ..., min_length=2, max_length=5,
    )
    mainstream_consensus: str = Field(..., min_length=1, max_length=2000)
    under_discussed_angles: list[str] = Field(..., min_length=3, max_length=5)
    base_rates: list[str] = Field(default_factory=list)


# =============================================================================
# Evidence corpus (gather-step output, Plan 81)
# =============================================================================
#
# Output of deliberation.evidence_gatherer.agent. Wide-cast, lightly
# structured pre-gathered evidence the packet builder reshapes into a
# ResearchPacket. Intentionally permissive (no min_length on findings)
# so the gatherer can return partial results instead of refusing when a
# sub-question yields nothing.


class SourcedFinding(BaseModel):
    """A single finding from the gather step.

    Less structured than SourcedClaim — the gather phase is wide-cast
    and the shaping happens downstream in the packet builder.
    """

    model_config = ConfigDict(extra="forbid")

    sub_question_id: str = Field(..., min_length=1, max_length=50)
    claim: str = Field(..., min_length=1, max_length=1000)
    evidence: str = Field(..., min_length=1, max_length=2000)
    source_url: str = Field(..., min_length=1, max_length=500)
    source_title: str = Field("", max_length=500)
    confidence: Literal["HIGH", "MEDIUM", "LOW"]


class EvidenceCorpus(BaseModel):
    """Output of deliberation.evidence_gatherer.agent.

    Intentionally permissive on `findings` (no min_length) so the
    gatherer returns partial results rather than refusing on
    sub-questions that yield no sources. The packet builder is the
    enforcer of the ResearchPacket schema minima.
    """

    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1, max_length=2000)
    sub_questions_addressed: list[str] = Field(default_factory=list)
    findings: list[SourcedFinding] = Field(default_factory=list)
    numeric_claims: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(
        default_factory=list,
        description=(
            "Sub-questions or framings the gatherer could not find "
            "good sources for. The packet builder uses these as "
            "candidates for `under_discussed_angles`."
        ),
    )
    notes: str = Field("", max_length=2000)


# =============================================================================
# Research packet verification (research_verifier output)
# =============================================================================


class ResearchPacketVerification(BaseModel):
    """Output of deliberation.research_verifier.agent.

    Fails LOUD: if `passed` is False, the workflow halts via a decision
    node and the user is notified. The verifier is a separate cheap
    Haiku agent — P13 (no self-evaluation) for the researcher.
    """

    model_config = ConfigDict(extra="forbid")

    passed: bool
    issues: list[str] = Field(default_factory=list)
    issues_text: str = Field(
        default="",
        description=(
            "Human-readable joined version of `issues` (one issue per "
            "line, prefixed with '- '). Used by the halt_workflow "
            "notification template so the user sees a clean message "
            "rather than Python list repr. The verifier produces both "
            "forms; downstream consumers pick whichever fits the channel."
        ),
    )
    mainstream_consensus_looks_plausible: bool
    under_discussed_angles_actually_under_discussed: bool
    notes: str = ""

    @computed_field  # type: ignore[misc]
    @property
    def gate(self) -> Literal["passed", "failed"]:
        """String form of `passed` matching the research-gate decision option keys.

        The workflow's research-gate decision node uses a rule resolver
        whose expression resolves to one of its option keys. Booleans
        don't match the keys, so we derive the matching string here.
        """
        return "passed" if self.passed else "failed"


# =============================================================================
# Debater turn (all four debaters share this schema)
# =============================================================================


class LoadBearingClaim(BaseModel):
    """A claim the debater's position depends on. If false, position fails."""

    model_config = ConfigDict(extra="forbid")

    claim: str = Field(..., min_length=1, max_length=1000)
    if_this_fails: str = Field(..., min_length=1, max_length=1000)


class DebaterTurn(BaseModel):
    """Per-round output of a debater agent.

    The `decision` field is the structured sycophancy detector: a
    CONCEDE_FULL with no specific refutation in `decision_justification`
    is mechanically visible to the synthesiser (see
    FinalDeliverable.sycophancy_flags).

    The `research_requests` field lets a debater ask for follow-up
    research before the next round. The deliberation loop pools these
    requests after each round, dispatches the researcher against each,
    and appends the new findings to the packet for subsequent rounds.
    Empty list = no request.
    """

    model_config = ConfigDict(extra="forbid")

    debater_id: Literal["systems", "quant", "empiricist", "ethicist"]
    round_index: int = Field(ge=0, le=5)
    position: str = Field(..., min_length=1, max_length=4000)
    load_bearing_claims: list[LoadBearingClaim] = Field(
        ..., min_length=2, max_length=3,
    )
    what_would_change_my_mind: str = Field(..., min_length=1, max_length=2000)
    decision: Literal["HOLD", "REFINE", "CONCEDE_PARTIAL", "CONCEDE_FULL"]
    decision_justification: str = Field(..., min_length=1, max_length=1000)
    confidence: float = Field(ge=0.0, le=1.0)
    research_requests: list[str] = Field(
        default_factory=list,
        max_length=3,
        description=(
            "Optional list of specific follow-up research questions this "
            "debater wants answered before the next round. Each question "
            "should be focused and answerable by a search-tool-equipped "
            "agent (e.g. \"What is the empirical false-positive rate of "
            "LLM-based static analysis on Python codebases at >100K LOC?\"). "
            "Empty list = no request. The deliberation orchestrator "
            "dispatches the researcher against pooled requests between "
            "rounds and appends the new findings to the packet."
        ),
    )


# =============================================================================
# Critic report (one per round)
# =============================================================================


class CriticAttack(BaseModel):
    """The critic's attack on one debater's load-bearing assumption."""

    model_config = ConfigDict(extra="forbid")

    load_bearing_assumption: str
    attack: str
    steelman_of_attack: str
    what_would_vindicate_the_debater: str


class ConvergenceFlag(BaseModel):
    """The critic's flag for convergence-by-shared-assumption.

    The critic's ConvergenceFlag is the proper mechanism for detecting
    sycophancy/echo-chamber. The stance-delta tool is only a stopping
    signal — convergence by shared hidden assumption looks identical to
    healthy agreement in embedding space, but is detectable by reading
    the actual arguments. That is this field's job.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "shared_hidden_assumption",
        "paraphrase",
        "collapse_to_mainstream",
        "none",
    ]
    debaters_involved: list[str] = Field(default_factory=list)
    explanation: str = ""


_ALLOWED_DEBATER_IDS = {"systems", "quant", "empiricist", "ethicist"}


class CriticReport(BaseModel):
    """Per-round output of deliberation.critic.agent.

    `attacks` is a str-keyed dict (not Literal-keyed) because LLM
    structured output is unreliable on Literal-keyed dicts. A
    field_validator constrains keys to the four allowed debater IDs at
    parse time so missing or extra keys fail loud (with PydanticAI's
    output_retries giving the model a chance to self-correct).
    """

    model_config = ConfigDict(extra="forbid")

    round_index: int = Field(ge=0, le=5)
    attacks: dict[str, CriticAttack]
    convergence_flag: ConvergenceFlag

    @field_validator("attacks")
    @classmethod
    def _validate_attack_keys(
        cls, v: dict[str, CriticAttack],
    ) -> dict[str, CriticAttack]:
        bad = set(v.keys()) - _ALLOWED_DEBATER_IDS
        missing = _ALLOWED_DEBATER_IDS - set(v.keys())
        if bad:
            raise ValueError(
                f"CriticReport.attacks has unknown debater IDs: {sorted(bad)}"
            )
        if missing:
            raise ValueError(
                f"CriticReport.attacks missing debater IDs: {sorted(missing)}"
            )
        return v


# =============================================================================
# Stance delta (deterministic tool output — early-stop check)
# =============================================================================


class StanceDelta(BaseModel):
    """Output of compute_stance_delta tool — deterministic, no LLM.

    This is a STOPPING signal, not a quality measure. Two debaters can
    converge on the same answer via different reasoning (or via shared
    hidden assumptions); the stance delta does not see that.
    Convergence-by-assumption is the critic's ConvergenceFlag's job.
    """

    model_config = ConfigDict(extra="forbid")

    delta: float = Field(ge=0.0, description="Aggregate change in stance vectors")
    threshold: float
    should_continue: bool
    gate: Literal["continue", "halt"] = Field(
        description=(
            "String form of should_continue matching the stop-rN decision "
            "option keys. The decision rule resolver expects an exact "
            "option-key string, not a bool."
        ),
    )
    per_debater: dict[str, float]
    reasoning: str


# =============================================================================
# Final deliverable (synthesiser output)
# =============================================================================


class CruxRecord(BaseModel):
    """An unresolved disagreement preserved by the synthesiser."""

    model_config = ConfigDict(extra="forbid")

    crux_question: str
    side_a_position: str
    side_a_debaters: list[str]
    side_a_steelman: str
    side_b_position: str
    side_b_debaters: list[str]
    side_b_steelman: str
    resolving_evidence: str


class MinorityPosition(BaseModel):
    """A non-mainstream position held to the end with a coherent argument."""

    model_config = ConfigDict(extra="forbid")

    debater: str
    position: str
    why_it_survived: str
    why_it_merits_preservation: str


class ForwardClaim(BaseModel):
    """The synthesiser's committed forecast with falsifiers."""

    model_config = ConfigDict(extra="forbid")

    horizon: str
    most_likely: str
    plausible_alternative: str
    would_surprise_the_system: str
    falsifiers: list[str] = Field(..., min_length=1)


class FinalDeliverable(BaseModel):
    """Output of deliberation.synthesiser.agent.

    The Pydantic constraints below do the work that prompts cannot:

    - `cruxes` must have >= 2 entries (prevents flattening to a single
      consensus answer).
    - `minority_position` is required to be either a record or explicit
      None (so "no minority position was preserved" is an explicit
      decision, not an absence).
    - `deliberation_vs_mainstream` has `merely_reproduces` as a typed
      enum value, making "the deliberation just agreed with the
      mainstream view" detectable rather than hidden.
    - `report_markdown` and `recommendation_markdown` are emitted by the
      synthesiser itself, not by a downstream Haiku renderer. The
      Markdown form is therefore subject to the same anti-flattening
      prompt and lives or dies with the structured fields.

    Persistence: the JSON dump of this model is stored as
    artifact_type=deliberation_deliverable so programmatic consumers can
    query confidence, cruxes, minority position. The report_markdown
    string is stored as a parallel Markdown artifact for humans.
    """

    model_config = ConfigDict(extra="forbid")

    question_restated: str
    committed_answer: str = Field(..., min_length=1, max_length=4000)
    confidence: float = Field(ge=0.0, le=1.0)
    cruxes: list[CruxRecord] = Field(..., min_length=2, max_length=5)
    minority_position: MinorityPosition | None
    mainstream_prior: str
    deliberation_vs_mainstream: Literal[
        "supports", "modifies", "rejects", "merely_reproduces",
    ]
    forward_claim: ForwardClaim
    biggest_things_that_could_be_wrong: list[str] = Field(
        ..., min_length=2, max_length=3,
    )
    sycophancy_flags: list[str] = Field(
        default_factory=list,
        description=(
            "Synthesiser must list any CONCEDE_FULL/CONCEDE_PARTIAL "
            "decisions that were not justified by a specific refutation "
            "cited in the transcript. Empty list is fine if none occurred."
        ),
    )
    report_markdown: str = Field(
        ...,
        min_length=200,
        description=(
            "Full Markdown rendering of this deliverable, produced by the "
            "synthesiser itself. Must include all sections: question, "
            "committed answer, cruxes (one subsection each with "
            "steelmen), minority position (if any), mainstream prior + "
            "how the deliberation related to it, forward claim with "
            "falsifiers, biggest things that could be wrong, sycophancy "
            "flags. Persisted as the human-readable artifact."
        ),
    )
    recommendation_markdown: str = Field(
        ...,
        min_length=20,
        max_length=4000,
        description=(
            "Single-paragraph recommendation derived from "
            "biggest_things_that_could_be_wrong. Persisted as the "
            "learning entry's recommendation field."
        ),
    )
