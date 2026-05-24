"""
Advocate-Judge deliberation schemas (Plan 80 Phase 1).

Pydantic models for the Think Tank Advocate-Judge architecture:
framer + framings validator -> N asymmetric researchers -> N blind
advocate cases -> N bilateral attacks -> judge.

Reuses `SourcedClaim`, `LoadBearingClaim`, and `FinalDeliverable` from
`modules.backend.schemas.deliberation`. The anti-flattening machinery
on `FinalDeliverable` (cruxes >= 2, required-or-null minority_position,
merely_reproduces enum, sycophancy_flags) survives unchanged from
Plan 79 v2 — that part empirically works and is the deliberate seam
where Advocate-Judge plugs into the existing artifact persistence.

The configuration model `AdvocateJudgeConfig` carries the per-side
model assignment (§5.1) so the executor can bind a different model
family per advocate. Multi-provider heterogeneity is the second
structural anti-convergence mechanism (alongside information
asymmetry between per-side researchers).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Reuse the validated types from the existing deliberation schemas.
from modules.backend.schemas.deliberation import LoadBearingClaim, SourcedClaim


# =============================================================================
# Phase 1: framing
# =============================================================================


class CandidateAnswer(BaseModel):
    """One candidate answer in the framer's output set."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(
        ..., min_length=1, max_length=80,
        description=(
            "Short kebab-case identifier, e.g. 'institutional-friction'. "
            "Used as the side ID throughout the deliberation."
        ),
    )
    statement: str = Field(
        ..., min_length=1, max_length=400,
        description=(
            "One-sentence claim the candidate represents. Concrete enough "
            "that it could later be wrong."
        ),
    )
    rationale_for_inclusion: str = Field(
        ..., min_length=1, max_length=600,
        description=(
            "Who actually holds this view in the real world and why it's a "
            "live answer (not a strawman). Names a school of thought, "
            "institution, or analyst where possible."
        ),
    )

    @field_validator("label")
    @classmethod
    def _validate_label_kebab(cls, v: str) -> str:
        """Labels must be kebab-case ASCII (lowercase + digits + hyphens)."""
        if not v or not all(c.islower() or c.isdigit() or c == "-" for c in v):
            raise ValueError(
                f"label must be kebab-case (lowercase + digits + hyphens), got: {v!r}",
            )
        if v.startswith("-") or v.endswith("-"):
            raise ValueError(f"label must not start or end with a hyphen, got: {v!r}")
        return v


class CandidateSet(BaseModel):
    """Framer's output — the live answer space for the question."""

    model_config = ConfigDict(extra="forbid")

    candidates: list[CandidateAnswer] = Field(..., min_length=3, max_length=5)
    mainstream_consensus: str = Field(
        ..., min_length=1, max_length=600,
        description=(
            "The conventional answer a competent non-specialist would give "
            "today. Named once here; the judge uses it for the "
            "merely_reproduces audit on FinalDeliverable."
        ),
    )

    @field_validator("candidates")
    @classmethod
    def _validate_unique_labels(
        cls, v: list[CandidateAnswer],
    ) -> list[CandidateAnswer]:
        labels = [c.label for c in v]
        if len(labels) != len(set(labels)):
            dupes = sorted({lbl for lbl in labels if labels.count(lbl) > 1})
            raise ValueError(f"candidate labels must be unique; duplicates: {dupes}")
        return v


class FramingValidation(BaseModel):
    """Framings validator's response. Either approves or replaces the set.

    `verdict='approved'` means the framer's set survives audit. The
    `revised_set` field is None in that case, and downstream phases use
    the original framer output.

    `verdict='revised'` means the validator rewrote the set (added a
    missing school, replaced a strawman, sharpened the mainstream
    consensus). `revised_set` MUST be present; downstream phases use
    it as the final set.
    """

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["approved", "revised"]
    revised_set: CandidateSet | None = Field(
        None,
        description="Present iff verdict == 'revised'. Final set to use.",
    )
    rationale: str = Field(
        ..., min_length=1, max_length=1000,
        description=(
            "If approved: what survived audit. If revised: what was missing "
            "and what changed."
        ),
    )

    @field_validator("revised_set")
    @classmethod
    def _validate_revised_present_iff_revised(
        cls, v: CandidateSet | None, info,
    ) -> CandidateSet | None:
        verdict = info.data.get("verdict")
        if verdict == "revised" and v is None:
            raise ValueError(
                "revised_set must be present when verdict == 'revised'",
            )
        if verdict == "approved" and v is not None:
            raise ValueError(
                "revised_set must be None when verdict == 'approved'",
            )
        return v


# =============================================================================
# Phase 2: asymmetric research (one packet per candidate)
# =============================================================================


class SidePacket(BaseModel):
    """Steelman research packet for ONE candidate answer.

    The per-side researcher's narrow job: find the strongest evidence
    that this candidate is correct. NOT balanced. The competition
    provides the counter-evidence.
    """

    model_config = ConfigDict(extra="forbid")

    candidate_label: str = Field(..., min_length=1, max_length=80)
    sourced_claims: list[SourcedClaim] = Field(..., min_length=3, max_length=10)
    strongest_supporting_argument: str = Field(
        ..., min_length=1, max_length=2000,
        description=(
            "The case for this candidate in 2 to 4 sentences, citing the "
            "researcher's strongest claims."
        ),
    )
    weakest_link: str = Field(
        ..., min_length=1, max_length=1000,
        description=(
            "Honest naming of this packet's weakest claim, and why. "
            "Required field — 'all my evidence is strong' is a refusal "
            "to do the job. The judge uses this in the final audit."
        ),
    )


# =============================================================================
# Phase 3: blind advocate case
# =============================================================================


class AdvocateCase(BaseModel):
    """One advocate's blind case for its candidate.

    Blind: the advocate sees only its own SidePacket — not other
    candidates' packets or cases. This prevents first-mover effects
    and forces independent commitment.
    """

    model_config = ConfigDict(extra="forbid")

    candidate_label: str = Field(..., min_length=1, max_length=80)
    case_statement: str = Field(
        ..., min_length=1, max_length=2000,
        description="The strongest possible case for this candidate, 2-5 sentences.",
    )
    load_bearing_claims: list[LoadBearingClaim] = Field(
        ..., min_length=2, max_length=3,
        description=(
            "The 2-3 claims that, if false, break the advocate's case. "
            "Reused from deliberation.LoadBearingClaim (Plan 79 schema)."
        ),
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description=(
            "Honest confidence AFTER seeing own evidence packet. If the "
            "packet's strongest evidence is weak (weakest_link says so), "
            "this should reflect that. Low confidence with a strong case "
            "is more useful than 0.9 with a smooth one."
        ),
    )


# =============================================================================
# Phase 4: bilateral attacks
# =============================================================================


class Attack(BaseModel):
    """One advocate's attack on one OTHER advocate's load-bearing claim."""

    model_config = ConfigDict(extra="forbid")

    target_label: str = Field(
        ..., min_length=1, max_length=80,
        description="The candidate_label of the advocate being attacked.",
    )
    attacked_assumption: str = Field(
        ..., min_length=1, max_length=500,
        description=(
            "Which load-bearing claim of the target is attacked. Quotes "
            "the claim from the target's AdvocateCase."
        ),
    )
    attack_argument: str = Field(
        ..., min_length=1, max_length=1500,
        description=(
            "The strongest version of the attack. Cites specific evidence "
            "by URL from the union of all SidePackets."
        ),
    )
    cited_evidence_urls: list[str] = Field(
        ..., min_length=1,
        description=(
            "URLs cited in attack_argument. Must appear in some side's "
            "SidePacket.sourced_claims. Fabricated URLs are a schema error "
            "(though not enforced at the schema level — the attacker prompt "
            "and the executor's post-validation handle it)."
        ),
    )
    steelman_of_attack: str = Field(
        ..., min_length=1, max_length=1000,
        description=(
            "The strongest reply the target advocate could make to this "
            "attack, addressed. Differentiates a critique from a hostile "
            "question."
        ),
    )


class AttacksByAdvocate(BaseModel):
    """All attacks from ONE advocate. Length = N - 1 (one per other candidate)."""

    model_config = ConfigDict(extra="forbid")

    from_label: str = Field(
        ..., min_length=1, max_length=80,
        description="The candidate_label of the attacking advocate.",
    )
    attacks: list[Attack] = Field(
        ..., min_length=1,
        description=(
            "One Attack per OTHER candidate. The executor validates that "
            "target_labels cover all other candidates exactly once."
        ),
    )


# =============================================================================
# Executor configuration
# =============================================================================


class AdvocateJudgeConfig(BaseModel):
    """Configuration for an Advocate-Judge deliberation run.

    See Plan 80 §5.1 for the per-side model assignment strategy. The
    `side_models` field controls multi-provider heterogeneity:

    - If None (default), the executor uses the rotation appropriate
      to the currently-wired providers (Claude / GPT / optionally Gemini).
    - If provided, the list overrides — but each entry is validated
      against `_build_model` at executor start so misconfiguration
      trips immediately, not 20 minutes into a run.

    Length of `side_models` (after resolution) is matched to the number
    of candidates the framer produces (between `min_candidates` and
    `max_candidates`). If the resolved rotation has fewer entries than
    candidates, the executor repeats families with a sycophancy_flags
    entry noting reduced heterogeneity.
    """

    model_config = ConfigDict(extra="forbid")

    min_candidates: int = Field(default=3, ge=2, le=5)
    max_candidates: int = Field(default=4, ge=2, le=5)
    side_models: list[str] | None = Field(
        default=None,
        description=(
            "Per-side model strings (e.g. 'copilot:claude-opus-4.6'). If "
            "None, the executor uses the default rotation."
        ),
    )
    judge_model: str = Field(
        default="copilot:claude-opus-4.7",
        description="Single model for the judge phase. Extended thinking recommended.",
    )

    # Agent names (overridable for tests)
    framer_agent: str = "deliberation.advocate_judge_framer.agent"
    framings_validator_agent: str = (
        "deliberation.advocate_judge_framings_validator.agent"
    )
    side_researcher_agent: str = "deliberation.advocate_judge_side_researcher.agent"
    advocate_agent: str = "deliberation.advocate_judge_advocate.agent"
    judge_agent: str = "deliberation.advocate_judge_judge.agent"

    # Per-call request limits (UsageLimits.request_limit)
    framer_request_limit: int = 15
    framings_validator_request_limit: int = 5
    side_researcher_request_limit: int = 30
    advocate_request_limit: int = 10
    judge_request_limit: int = 15

    @field_validator("max_candidates")
    @classmethod
    def _validate_max_ge_min(cls, v: int, info) -> int:
        min_val = info.data.get("min_candidates", 3)
        if v < min_val:
            raise ValueError(
                f"max_candidates ({v}) must be >= min_candidates ({min_val})",
            )
        return v

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdvocateJudgeConfig:
        """Build from task input_data['loop_config'].

        Accepts string `side_models` (comma-separated) for CLI/YAML
        convenience and converts to a list.
        """
        if not isinstance(data, dict):
            raise TypeError(f"loop_config must be a dict, got {type(data).__name__}")
        side_models = data.get("side_models")
        if isinstance(side_models, str):
            side_models = (
                [s.strip() for s in side_models.split(",") if s.strip()]
                if side_models.strip()
                else None
            )
        return cls(
            min_candidates=int(data.get("min_candidates", 3)),
            max_candidates=int(data.get("max_candidates", 4)),
            side_models=side_models,
            judge_model=str(data.get("judge_model", "copilot:claude-opus-4.7")),
        )
