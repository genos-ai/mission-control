# Plan 79: Think Tank Deliberation Mission

## Status: Draft v5 (2026-05-23 — adversarial-review fixes)

**v1 → v2 revision notes:**
- Found that `extract_outputs` returns `{}` for agent_step without `output_mapping`, so chained `@node.X.output.field` refs would silently resolve to None. Added a third platform enabler (§8.3) to default-populate `completed_outcomes` from the agent's structured output.
- Found that `_execute_tool_call_step` only resolves refs in top-level string args, not nested dicts. Added a fourth enabler (§8.4) to deep-resolve refs in tool_args.
- Corrected the `compute_stance_delta` tool (§9) to use the actual `get_embedder().embed(text)` API. `embed_text` does not exist.
- Added an explicit reuse manifest (§8.0) so the plan declares what it reuses unchanged and what it changes.
- Added a `render-deliverable` step before `store-deliverable` so the artifact stored is Markdown, not Python `repr` of a Pydantic dict (§7).
- Added a one-paragraph justification for why a new `deliberation.synthesiser` is needed when `system.synthesis` exists (§4).

**v2 → v3 revision notes (open-issues fix pass):**
- Added §8.5: `resolve_template` raises on syntax errors (typo in ref root like `@nodez.X`) instead of leaving the literal `{{@badref}}` in output. Legitimate missing-data paths (a skipped predecessor) continue to return empty — distinguishing structural error from runtime absence.
- Added §8.6: standalone refs (the entire string is `{{@ref}}`) preserve the raw resolved value's type. `confidence: "{{@node.synthesise.output.confidence}}"` now yields a `float`, not a `str` like `"0.85"`. Mixed strings (templates with surrounding text) continue to produce strings.
- Added §8.7: load-time validation that every `@node.X` ref in `step.input` and `tool_args` points to a step that exists in the workflow. Catches typos at YAML parse time instead of at runtime mid-deliberation.
- Updated the `store-learning` YAML to pass `confidence` as a pure standalone ref (so §8.6 preserves the float).
- Added stance-vector-as-stopping-signal-only clarification to the critic and synthesiser system-prompt fragments in §6.
- Synthesiser objective bloat (~100-500 KB) is now an accepted monitoring item, not an open issue — see §13 caveat 2 for the trigger that would force a redesign.

**v3 → v4 revision notes (second-pass cleanup):**
- `CriticReport.attacks` changed from `dict[Literal[...], CriticAttack]` to `dict[str, CriticAttack]` with a Pydantic validator constraining keys to the four debater IDs. No existing schema uses Literal-keyed dicts; Anthropic structured output is unreliable on this pattern. The dot-walk reference `@node.critic-r1.output.attacks.systems` works identically.
- Workflow `max_cost_usd` raised from 25.00 to 60.00 to match the realistic worst-case at full 3-round run with Opus defaults.
- Synthesiser system prompt now explicitly handles `None` for skipped rounds: "If a round entry is null, that round did not run (early-stop fired); synthesise from the rounds that did run."
- §8.5 / §8.6 expanded with an explicit note about updating the two internal `_resolve_ref` callers in `condition_evaluator.py` after the rename.
- §6 prompt manifest now specifies `max_input_length` per agent (required field on `AgentConfigSchema`). Synthesiser uses 1_000_000; debaters/critic 100_000; researcher/verifier 20_000.
- §7 YAML truncation note hardened: implementation must mechanically generate the round 2 and round 3 step bodies from the round 1 pattern (no manual transcription).
- Phase 8 acceptance criteria now asserts step counts (34 total: 23 agent_step + 4 tool_call + 2 llm_call + 3 decision + 1 notification + 1 merge) so a missing step is caught immediately.
- §8.6 risk audit: grep over existing `config/workflow_templates/*.yaml` confirmed no tool_args standalone ref currently relies on the str()-coercion behaviour. All standalone refs today resolve to string-valued fields already (e.g. `summarize.output` is `str` from llm_call). No regression risk.

**v4 → v5 revision notes (adversarial-review fixes):**
- **B1 (blocking):** `FinalDeliverable` is now persisted as a structured JSON artifact in addition to the Markdown rendering. The schema-enforced anti-flattening protection now survives into storage. `store_artifact` is extended to accept `content: str | dict | list` and JSON-encode non-string content (§9.1).
- **B2 (blocking):** Transcript persistence re-instated as a `store-transcript` step that JSON-stores the full transcript (research packet + all rounds + all critic reports) as an `artifact_type=deliberation_transcript` artifact. Uses §8.4 deep-resolve to assemble the nested dict without a new tool.
- **B3 (blocking):** §8.3 default-output extraction now matches by `agent_name`, not by `task_results[-1]`. The wave engine passes `step.capability + ".agent"` as the expected agent. Fallback to `[-1]` only if no agent_name match (logged as a warning).
- **S1:** `halt-bad-research` is now a `tool_call` to a new `halt_workflow` tool that raises `RuntimeError` (which the tool_call dispatcher re-raises per existing line 866–867). Workflow status is now `failed`, not `completed`. The tool also publishes an SSE notification before raising.
- **S2:** Phase 8 static assertion extended to verify, for each round-N debater step, that `opponents_previous` contains exactly the three other debater IDs mapped to `round(N-1)-<id>`.
- **S3:** Removed `render-deliverable` and `render-recommendation` nodes. `FinalDeliverable` now includes `report_markdown: str` and `recommendation_markdown: str` produced by the synthesiser itself. Single source of truth; both forms are schema-validated. Node total stays at 34 (two render llm_calls removed, but two new artifact-store steps added by B1/B2: store-deliverable-json and store-transcript).
- **S4:** `output_retries` specified in §6.1 per agent (critic/synthesiser: 3; debaters: 2; researcher/verifier: 1).
- **S5:** `compute_stance_delta` now uses `asyncio.gather` over the four debater embed pairs.
- **S6:** Synthesise step `cost_ceiling_usd` raised from 5.00 to 8.00.
- **C1:** §8.1 and §8.4 collapsed into a single recursive walker `walk_refs(value, outcomes, ctx, *, leaf_resolver)` parameterised by the leaf-resolver function. Used by both agent_step input and tool_call args.
- **C2:** `compute_stance_delta` `deps` cleared (no longer declares `mission_id`).
- **C3:** §13 updated: structured artifact persistence enables programmatic query of past deliberations via `GET /missions/{id}/artifacts?type=deliberation_deliverable`.
- **V1:** Resolved by B3.
- **V2:** Added explicit Phase 1 test asserting `wait_all` over partially-skipped predecessors.
- **V3:** Documented in S4 — `output_retries` is the mitigation for the dict-validator-fails-on-incomplete-keys case.

**v5 follow-on fixes (issues introduced by v5 changes):**
- **S7:** `compute_stance_delta` signature had `mission_id: str` as positional but C2 removed it from `deps`. Would have failed at call time with `TypeError`. Dropped from signature; tool is now fully keyword-only.
- **S8:** `halt_workflow.reason` template embedded `{{@node.verify-research.output.issues}}` (a list) inside mixed text — §8.6 standalone-preservation does not apply to mixed text, so the list str()-coerced to ugly Python repr. Added `issues_text: str` field to `ResearchPacketVerification` (joined string, one bullet per issue) and switched the template to use it. Verifier prompt updated to require both forms.
- **S9 resolved (not just verified):** confirmed at [services/workflow_run.py:327](modules/backend/services/workflow_run.py#L327) that the outer wave executor catches `RuntimeError` and sets `run.status = WorkflowRunState.FAILED`. The `halt_workflow` tool path is genuinely end-to-end correct, not just an assumption.
- **Budget arithmetic:** sum of per-step ceilings is $62, workflow `max_cost_usd` was $60. Raised to $65 to leave $3 headroom for the storers and stance-delta tool. Avoids spurious budget-trip failures at the very end of a successful run.

**Priority:** Medium-High
**Branch:** TBD — `feature/79-think-tank-deliberation`
**Reference:** [docs/98-research/032-Think Tank-A Multi-Agent Deliberation System for Contested Questions.md](../09-research/032-Think%20Tank-A%20Multi-Agent%20Deliberation%20System%20for%20Contested%20Questions.md)

**Dependencies:**
- Plan 45 (Rich Workflow Model)
- Plan 72 (Task First-Class)
- Plan 75 (Composable Workflows with Decision Nodes — `decision`, `merge`, labelled `edges`, `_branch` routing)
- Plan 40 (Deep Research) — pattern reference for multi-agent loops (we do NOT reuse the loop executor; this is a workflow, not a loop)

**User intent:** quality and depth over speed and cost. The plan defaults to Claude Opus 4.7 for debaters, critic, and synthesiser, and accepts a multi-hour wall-clock per run if the deliberation merits it. Cost knobs remain in YAML but are not the primary design constraint.

---

## 1. Problem statement

Mission Control today is excellent at deterministic workflows and at LLM-planned task DAGs, but it has no first-class capability for **structured deliberation on contested, open questions** — the class of questions where a single model pass converges on the mainstream prior, where chain-of-thought + self-consistency cannot help (because there is no single ground truth to converge on), and where the user explicitly wants a structured challenge to the easy answer.

Examples of in-scope questions:
- "What is the most likely effect of agentic AI on knowledge-worker employment in the UK by 2030?"
- "Should we enter the South African retail-banking market in the current regulatory climate?"
- "Is the current energy transition trajectory robust to a sustained gas price shock?"
- "What is the right rate of pace for adopting LLM-driven coding inside this engineering org?"

Examples explicitly out of scope:
- Factual lookups, well-specified maths, code generation, anything with a knowable right answer.
- Time-critical operational questions (latency makes this unsuitable).
- Questions where the bottleneck is retrieval, not reasoning.

The 2024–2025 multi-agent debate literature (Du et al. ICML 2024; Liang et al. EMNLP 2024; Khan et al. ICML 2024 Best Paper; Smit et al. ICML 2024; arXiv:2509.05396; arXiv:2509.23055; arXiv:2502.19559) supports a narrow but specific claim: **structured debate beats naive single-pass on the class of question described above, provided three counter-measures are baked in from the start** — sycophancy cascade, mainstream-prior collapse, and synthesiser flattening must each have a mechanical (not prompt-only) mitigation.

This plan delivers that capability as a composable workflow on top of the platform shipped in Plan 75. It introduces seven new agents under a new `deliberation.*` namespace, two small platform enablers, one deterministic tool, and one workflow template. **No changes are required to mission control, the dispatch loop, the verification pipeline, Temporal, or the event bus.**

---

## 2. Architectural decisions (committed for v1)

| Decision | Choice | Why |
|---|---|---|
| **Shape** | A composable workflow template, not a new dispatch primitive. | The wave engine + decision nodes + sub-workflows are sufficient to express the entire flow. Building a `deliberation_loop` executor (as `execute_research_loop` does for Plan 40) would couple the deliberation policy to Python; keeping it in YAML makes the rounds, critic invocations, and early-stop reviewable as configuration. P1 / P10 say "every phase is an expansion, not a rewrite". |
| **Namespace** | `deliberation.*` — `deliberation.researcher`, `deliberation.research_verifier`, `deliberation.debater_systems`, `deliberation.debater_quant`, `deliberation.debater_empiricist`, `deliberation.debater_ethicist`, `deliberation.critic`, `deliberation.synthesiser`. | Distinct from `research.*` (deep research is information aggregation; deliberation is contested reasoning) and from `mission.*` (which is platform-level orchestration). New namespace is cheaper than overloading either. |
| **Debater identity** | Four debaters by reasoning method × value frame: Systems Mapper, Reductionist Quant, Adversarial Empiricist, Distributional Ethicist. NOT occupational personas. | Hu and Collier ACL 2024, Kambhatla et al. EMNLP 2025, Savir et al. arXiv:2512.05858 all show persona prompting moves style more than reasoning. Cognitive-method × value-frame is the empirically-defended alternative. |
| **Critic** | Single position-free critic agent, invoked every round, sees only the current round, never sees its own prior reports. | Avoids the critic developing a committed line. Anchored in Khan et al. and the design rationale in research §2.4. Satisfies P13 (no agent self-evaluation). |
| **Synthesiser** | Reads full transcript, runs once at the end, mechanically forbidden from flattening (Pydantic `min_length=2` cruxes, required `minority_position` field, explicit `merely_reproduces` enum value on `deliberation_vs_mainstream`). | The synthesiser is the highest-risk single point of failure; the schema does the work that the prompt cannot enforce. |
| **Research packet verifier** | Cheap Haiku 4.5 pass between researcher and blind opening. | Caught in initial review of research doc: the entire deliberation is anchored on the research packet's "mainstream consensus" and "what is actually known" sections. A bad researcher pass poisons the run. This is also P13 compliance — researcher does not self-evaluate. |
| **Sparse topology** | Each debater in round N sees: own round N-1, opponents' round N-1, critic's round N-1 attack on self only. NOT full transcript, NOT critic attacks on others. | arXiv:2502.19559: "problem drift" is the dominant late-round failure when context grows. Sparse topology mechanically prevents drift and cuts ~30–40% of token cost. Implemented by explicit input mapping in the workflow YAML, not by prompt instructions. |
| **Blind opening** | Debaters open in parallel before seeing each other or the critic. | Breaks first-mover anchoring. Du et al. and the design rationale in research §5.1 both call this out. |
| **Round count** | Default 3, max 5, early-stop on stance stability. | Du et al. plateau by round 3; arXiv:2509.23055 finds sycophancy intensifies after round 3; arXiv:2502.19559 finds accuracy decay from round 4 onward. |
| **Early-stop computation** | Deterministic Python tool (`compute_stance_delta`), called as a `tool_call` node, whose output feeds a `decision` node with `rule` resolver. NOT an LLM. | P2 (deterministic over non-deterministic). An LLM "should we stop" decision is itself subject to sycophancy. |
| **Hold/Concede schema** | Every debater turn must emit `decision: Literal["HOLD", "REFINE", "CONCEDE_PARTIAL", "CONCEDE_FULL"]` with a `decision_justification: str`. | Makes sycophancy mechanically detectable: a `CONCEDE_FULL` with no specific refutation cited is a red flag the synthesiser is required to surface. |
| **Default models** | Researcher: Sonnet 4.6. Verifier: Haiku 4.5. Debaters: Opus 4.7. Critic: Opus 4.7. Synthesiser: Opus 4.7. | Per user steer: quality over cost. Sonnet for researcher (better recall than Haiku); Opus for everything that does load-bearing reasoning. All are config knobs in YAML. |
| **Persistence** | Three artifacts per run: deliverable as Markdown (human-readable), deliverable as structured JSON (schema-validated, programmatically queryable), full transcript as JSON (audit trail). Plus a `store_learning` entry for cross-mission knowledge. The JSON deliverable closes the anti-flattening loop — the schema constraints (`cruxes: min_length=2`, required `minority_position`, `merely_reproduces` enum) survive into storage because the persisted JSON IS the validated Pydantic dump. | Reuses Plan 43 (artifacts) with one extension: `store_artifact` accepts dict/list content and JSON-encodes (§9.1). No new persistence primitives. |
| **Trigger** | `on_demand` (workflow run created via API/TUI/CLI). Not auto-triggered by the Director (yet). | Future enhancement: the Director's `run_workflow` tool could match deliberation questions and dispatch this workflow, but the Director's heuristics need to be tuned not to over-trigger. Out of scope for v1. |

---

## 3. Empirical grounding (one-paragraph synthesis)

Three rounds of structured debate with four reasoning-diverse agents and a position-free critic beat single-pass reasoning on contested open questions (Du et al. arithmetic 67% → 82%; Khan et al. QuALITY 48% → 76%; Liang et al. CIAR 26% → 37%). The same protocols *underperform* a tuned single-agent on closed-answer benchmarks (Smit et al.) and *decay* if rounds exceed three under default settings (arXiv:2502.19559: -4.65% by round 7; arXiv:2509.05396: correct-to-incorrect flips dominate after round 1). The three robust counter-measures are (a) blind opening + sparse topology to suppress anchoring and drift, (b) low agreement-intensity prompting + structured hold/concede decisions to make sycophancy visible, and (c) a synthesiser that is mechanically forbidden from collapsing the deliberation to a single answer via Pydantic schema constraints. This plan implements all three.

---

## 4. Agent roster

Seven agents in total. All under `deliberation.*`. All follow the 4-file contract from Plan 1: YAML config, system prompt (`config/prompts/agents/...`), Python module with `create_agent()`, and a roster entry.

| Agent name | Role | Model default | Output schema | Read scope | Write scope |
|---|---|---|---|---|---|
| `deliberation.researcher.agent` | Assemble the evidence packet | Sonnet 4.6 | `ResearchPacket` | `search_web`, `fetch_url`, `query_knowledge` | none |
| `deliberation.research_verifier.agent` | Validate the packet (sanity, completeness, fail-loud on holes) | Haiku 4.5 | `ResearchPacketVerification` | none | none |
| `deliberation.debater_systems.agent` | Systems Mapper — feedback loops, second-order effects | Opus 4.7 | `DebaterTurn` | none | none |
| `deliberation.debater_quant.agent` | Reductionist Quant — falsifiable mechanism + numbers | Opus 4.7 | `DebaterTurn` | none | none |
| `deliberation.debater_empiricist.agent` | Adversarial Empiricist (the maverick seat) — historical priors, contrarian by default | Opus 4.7 | `DebaterTurn` | none | none |
| `deliberation.debater_ethicist.agent` | Distributional Ethicist — who wins, who loses, absent voices | Opus 4.7 | `DebaterTurn` | none | none |
| `deliberation.critic.agent` | Adversarial, position-free — attacks load-bearing assumptions, flags convergence | Opus 4.7 | `CriticReport` | none | none |
| `deliberation.synthesiser.agent` | Maps cruxes, preserves minority position, owns uncertainty | Opus 4.7 | `FinalDeliverable` | none | none |

**Roster size justification.** Du et al.'s diminishing-returns curve: marginal accuracy from the 5th debater is ~2-3 points; from the 7th, ~0.5. The four chosen quadrants ((mechanism vs system) × (efficiency vs equity)) cover the minimum diversity needed to break correlated priors on contested questions. A fifth or sixth debater earns its keep only when a question crosses into a genuinely new domain (e.g. an explicit theological dimension); supporting that case is out of scope for v1. Documented as a future option in §13.

**Why `deliberation.synthesiser` is a new agent, not a reuse of `system.synthesis`.** [system.synthesis.agent](modules/backend/agents/system/synthesis/agent.py) exists today and produces a narrative `str` summary from generic outcome data — it is the platform's execution-summary writer (Haiku, presentation-layer, no schema enforcement). The deliberation synthesiser produces a structured `FinalDeliverable` Pydantic model whose schema constraints (`cruxes: min_length=2`, required `minority_position`, `deliberation_vs_mainstream: Literal[..., "merely_reproduces"]`) do the load-bearing anti-flattening work. Different output type, different role, different model tier. Not reusable.

---

## 5. Schemas

A new module: `modules/backend/schemas/deliberation.py`.

```python
"""
Deliberation schemas (Plan 79).

Pydantic models for the Think Tank multi-agent deliberation workflow:
research packet, packet verification, debater turn, critic report,
final deliverable.
"""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


# =============================================================================
# Research packet (researcher output)
# =============================================================================

class SourcedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim: str = Field(..., min_length=1, max_length=1000)
    source: str = Field(..., min_length=1, max_length=500)
    confidence: Literal["HIGH", "MEDIUM", "LOW"]


class ExpertDisagreement(BaseModel):
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
    expert_disagreements: list[ExpertDisagreement] = Field(..., min_length=2, max_length=5)
    mainstream_consensus: str = Field(..., min_length=1, max_length=2000)
    under_discussed_angles: list[str] = Field(..., min_length=3, max_length=5)
    base_rates: list[str] = Field(default_factory=list)


# =============================================================================
# Research packet verification (research_verifier output)
# =============================================================================

class ResearchPacketVerification(BaseModel):
    """Output of deliberation.research_verifier.agent.

    Fails LOUD: if `passed` is False, the workflow halts via a decision node
    and the user is notified. This is P13 (no self-evaluation) for the
    researcher — a separate cheap agent audits the packet.
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


# =============================================================================
# Debater turn (all four debaters share this schema)
# =============================================================================

class LoadBearingClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim: str = Field(..., min_length=1, max_length=500)
    if_this_fails: str = Field(..., min_length=1, max_length=300)


class DebaterTurn(BaseModel):
    """Per-round output of a debater agent."""
    model_config = ConfigDict(extra="forbid")
    debater_id: Literal["systems", "quant", "empiricist", "ethicist"]
    round_index: int = Field(ge=0, le=5)
    position: str = Field(..., min_length=1, max_length=2000)
    load_bearing_claims: list[LoadBearingClaim] = Field(..., min_length=2, max_length=3)
    what_would_change_my_mind: str = Field(..., min_length=1, max_length=1000)
    decision: Literal["HOLD", "REFINE", "CONCEDE_PARTIAL", "CONCEDE_FULL"]
    decision_justification: str = Field(..., min_length=1, max_length=500)
    confidence: float = Field(ge=0.0, le=1.0)


# =============================================================================
# Critic report (one per round)
# =============================================================================

class CriticAttack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    load_bearing_assumption: str
    attack: str
    steelman_of_attack: str
    what_would_vindicate_the_debater: str


class ConvergenceFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["shared_hidden_assumption", "paraphrase", "collapse_to_mainstream", "none"]
    debaters_involved: list[str] = Field(default_factory=list)
    explanation: str = ""


_ALLOWED_DEBATER_IDS = {"systems", "quant", "empiricist", "ethicist"}


class CriticReport(BaseModel):
    """Per-round output of deliberation.critic.agent.

    `attacks` is a dict keyed by debater_id so the wave engine can extract
    `@node.critic-r1.output.attacks.systems` for the Systems debater's
    round 2 input (sparse topology).

    Note: keys are str-typed (not Literal-keyed) because LLM structured
    output is unreliable on Literal-keyed dicts. A validator constrains
    keys to the four allowed debater IDs at parse time.
    """
    model_config = ConfigDict(extra="forbid")
    round_index: int = Field(ge=0, le=5)
    attacks: dict[str, CriticAttack]
    convergence_flag: ConvergenceFlag

    @field_validator("attacks")
    @classmethod
    def _validate_attack_keys(cls, v: dict[str, CriticAttack]) -> dict[str, CriticAttack]:
        bad = set(v.keys()) - _ALLOWED_DEBATER_IDS
        missing = _ALLOWED_DEBATER_IDS - set(v.keys())
        if bad:
            raise ValueError(f"CriticReport.attacks has unknown debater IDs: {sorted(bad)}")
        if missing:
            raise ValueError(f"CriticReport.attacks missing debater IDs: {sorted(missing)}")
        return v


# =============================================================================
# Stance delta (deterministic tool output — early-stop check)
# =============================================================================

class StanceDelta(BaseModel):
    """Output of compute_stance_delta tool — deterministic, no LLM."""
    model_config = ConfigDict(extra="forbid")
    delta: float = Field(ge=0.0, description="Aggregate change in stance vectors")
    threshold: float
    should_continue: bool
    per_debater: dict[str, float]
    reasoning: str  # e.g. "stance change 0.08 < threshold 0.15, no CONCEDE_PARTIAL/REFINE"


# =============================================================================
# Final deliverable (synthesiser output)
# =============================================================================

class CruxRecord(BaseModel):
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
    model_config = ConfigDict(extra="forbid")
    debater: str
    position: str
    why_it_survived: str
    why_it_merits_preservation: str


class ForwardClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    horizon: str
    most_likely: str
    plausible_alternative: str
    would_surprise_the_system: str
    falsifiers: list[str] = Field(..., min_length=1)


class FinalDeliverable(BaseModel):
    """Output of deliberation.synthesiser.agent.

    The Pydantic constraints below do the work that prompts cannot:
    - `cruxes` must have >= 2 entries (prevents flattening)
    - `minority_position` is required to be either a record or explicit None
    - `deliberation_vs_mainstream` has `merely_reproduces` as a typed value,
      making "we just agreed with the mainstream" a detectable enum case
      rather than a hidden failure.
    - `report_markdown` and `recommendation_markdown` are emitted by the
      synthesiser itself, not by a downstream Haiku renderer. The Markdown
      form is therefore subject to the same anti-flattening prompt and
      lives or dies with the structured fields.
    """
    model_config = ConfigDict(extra="forbid")
    question_restated: str
    committed_answer: str = Field(..., min_length=1, max_length=2000)
    confidence: float = Field(ge=0.0, le=1.0)
    cruxes: list[CruxRecord] = Field(..., min_length=2, max_length=5)
    minority_position: MinorityPosition | None
    mainstream_prior: str
    deliberation_vs_mainstream: Literal["supports", "modifies", "rejects", "merely_reproduces"]
    forward_claim: ForwardClaim
    biggest_things_that_could_be_wrong: list[str] = Field(..., min_length=2, max_length=3)
    sycophancy_flags: list[str] = Field(
        default_factory=list,
        description=(
            "Synthesiser must list any CONCEDE_FULL/CONCEDE_PARTIAL decisions "
            "that were not justified by a specific refutation cited in the "
            "transcript. Empty list is fine if none occurred."
        ),
    )
    report_markdown: str = Field(
        ...,
        min_length=200,
        description=(
            "Full Markdown rendering of this deliverable, produced by the "
            "synthesiser itself. Must include all sections: question, committed "
            "answer, cruxes (one subsection each with steelmen), minority "
            "position (if any), mainstream prior + how the deliberation related "
            "to it, forward claim with falsifiers, biggest things that could be "
            "wrong, sycophancy flags. Persisted as the human-readable artifact."
        ),
    )
    recommendation_markdown: str = Field(
        ...,
        min_length=20,
        max_length=2000,
        description=(
            "Single-paragraph recommendation derived from "
            "biggest_things_that_could_be_wrong. Persisted as the learning "
            "entry's recommendation field."
        ),
    )
```

---

## 6. System prompts

Eight prompt files. All in UK English, no em dashes (per the source research doc's stipulation, which also keeps them consistent with the rest of the prompts catalog).

Paths:
- `config/prompts/agents/deliberation/researcher/system.md`
- `config/prompts/agents/deliberation/research_verifier/system.md`
- `config/prompts/agents/deliberation/debater_systems/system.md`
- `config/prompts/agents/deliberation/debater_quant/system.md`
- `config/prompts/agents/deliberation/debater_empiricist/system.md`
- `config/prompts/agents/deliberation/debater_ethicist/system.md`
- `config/prompts/agents/deliberation/critic/system.md`
- `config/prompts/agents/deliberation/synthesiser/system.md`

**Source content for all seven role prompts is taken verbatim from research §4.1–4.7** with only two modifications:
1. The variable interpolation block at the top of each prompt is dropped (the platform injects context via the objective/instructions path, not via `{{VAR}}` template substitution at the prompt level).
2. Each prompt ends with a section pointing the agent at its `output_type` Pydantic schema name (e.g. "Output: a `DebaterTurn` object validated against the schema").

**Additional clarification appended to the critic prompt (§4.6) and synthesiser prompt (§4.7) by this plan:**

```markdown
### A note on the early-stop signal

The orchestration uses a deterministic stance-delta computation (embedding
distance between this round's and the previous round's positions, plus
confidence-delta) as a stopping signal — it answers "is it worth running
another round". It is not a quality measure. Two debaters could converge on
the same answer via shared hidden assumptions, and the stance vector would
not see this. Convergence-by-shared-assumption is the critic's job to detect
(via the `convergence_flag` field). Do not infer quality from the stop signal.
```

This is appended to the critic prompt (after its existing rules) and synthesiser prompt (in a "Rules" section).

**Additional clarification appended to the synthesiser prompt only:**

```markdown
### Handling skipped rounds

The early-stop check may halt the deliberation after round 1 or round 2.
In your input, `all_rounds.round_2` and `all_rounds.round_3` may be null
(or contain null entries) if those rounds did not run. This is expected:
the early-stop machinery decided the stance was stable enough to synthesise.

When a round is null, synthesise from the rounds that actually ran. Do not
treat the absence of a round as a signal about quality. The presence of
later rounds means the stance was still moving; the absence means it was
stable. Neither is itself good or bad.
```

### 6.1 Per-agent YAML field values

`max_input_length` is a required field on `AgentConfigSchema`. The synthesiser receives the full transcript (~100-500 KB), so its limit must be high. The debaters and critic receive sparse-topology slices (~5-20 KB). The researcher/verifier receive only the question and the packet (~2-5 KB).

| Agent | model | temperature | max_tokens | max_input_length | max_budget_usd | output_retries |
|---|---|---|---|---|---|---|
| `deliberation.researcher` | copilot:claude-sonnet-4.6 | 0.2 | 8192 | 20_000 | 5.00 | 1 |
| `deliberation.research_verifier` | copilot:claude-haiku-4.5 | 0.0 | 2048 | 20_000 | 1.00 | 1 |
| `deliberation.debater_systems` | copilot:claude-opus-4.7 | 0.7 | 4096 | 100_000 | 3.00 | 2 |
| `deliberation.debater_quant` | copilot:claude-opus-4.7 | 0.7 | 4096 | 100_000 | 3.00 | 2 |
| `deliberation.debater_empiricist` | copilot:claude-opus-4.7 | 0.7 | 4096 | 100_000 | 3.00 | 2 |
| `deliberation.debater_ethicist` | copilot:claude-opus-4.7 | 0.7 | 4096 | 100_000 | 3.00 | 2 |
| `deliberation.critic` | copilot:claude-opus-4.7 | 0.4 | 4096 | 100_000 | 3.00 | 3 |
| `deliberation.synthesiser` | copilot:claude-opus-4.7 | 0.3 | 16384 | 1_000_000 | 8.00 | 3 |

`output_retries` rationale: critic/synthesiser are 3 because their schemas have the strictest validators (4-key `attacks` dict; `cruxes: min_length=2`; required `report_markdown`/`recommendation_markdown` with length floors). Debaters are 2 because `DebaterTurn` has only a `Literal` decision field that may need one retry. Researcher/verifier are 1 because their schemas are tolerant.

Researcher `tools: [search_web, fetch_url, query_knowledge]`. All other agents `tools: []`.

**Synthesise step `cost_ceiling_usd` raised from 5.00 → 8.00** to absorb verbose-debater worst-case input size. The synthesiser is also the only step that produces both structured fields and full Markdown rendering in a single call (per S3 fix), so its output token budget is correspondingly larger.

The eighth prompt — `research_verifier/system.md` — is new and is added by this plan. Draft:

```markdown
## Research Packet Verifier

You verify research packets produced by the Researcher for the Think Tank
deliberation. You do not contribute to the deliberation. You do not propose
content. You audit the packet against four checks.

### Input
A `ResearchPacket` JSON object.

### Checks

1. **Mainstream consensus plausibility.** Is the stated mainstream consensus
   actually what a competent non-specialist would say today? If the stated
   consensus is a strawman, or omits the most-cited recent view, the packet
   has poisoned the deliberation before it begins. Reject.

2. **Under-discussed angles are genuinely under-discussed.** If the listed
   "under-discussed angles" are in fact widely discussed (e.g. listed as
   "AI safety" for an AI question), the packet has failed at its main
   anti-convergence job. Reject.

3. **Sourced claims have real sources.** Spot-check three claims. If a source
   is vague ("a recent report"), or appears fabricated, reject.

4. **Cohesion.** The question_restated should match the user's actual question.
   The base_rates should be quantitative where the question has a quantitative
   form.

### Output

Return a `ResearchPacketVerification` object. If any check fails, set
`passed: false` and populate `issues` with one-line descriptions of each
failure. Also populate `issues_text` with the same content joined as
`"- {issue1}\n- {issue2}\n..."` so notification templates can embed it
cleanly. Do not soften. A failed verification halts the workflow.

You do not propose fixes. You do not run the deliberation. You audit.

UK English. No em dashes.
```

---

## 7. Workflow template

New file: `config/workflow_templates/deliberation.think-tank.workflow.yaml`.

The workflow has **34 nodes** across 7 phases (breakdown in §7 closing note). Phases 5 and 6 (rounds 2 and 3) are gated on early-stop decisions so they only fire if the stance vector is still moving.

```yaml
# =============================================================================
# Workflow: Think Tank (Multi-Agent Deliberation)
# =============================================================================
# Structured deliberation on contested, open questions. Four reasoning-diverse
# debaters plus a position-free critic over up to three rounds, with a
# mechanical sycophancy detector (HOLD/CONCEDE schema) and a synthesiser
# forbidden from flattening via Pydantic schema constraints.
#
# Use when: the user wants a structured challenge to a contested view.
# Do NOT use for: factual lookups, well-specified maths, code generation.
# =============================================================================

workflow_name: deliberation.think-tank.workflow
description: "Multi-agent deliberation for contested open questions"
objective:
  statement: "Produce a structured deliberation on a contested question, preserving live disagreement"
  category: research
  owner: user
  priority: normal
version: 1
enabled: true

trigger:
  type: on_demand
  match_patterns:
    - "deliberate"
    - "think tank"
    - "contested question"

budget:
  # Sum of per-step ceilings at full 3-round run with Opus defaults:
  #   researcher 5 + verifier 1
  # + 4 debaters × 3 rounds × 3 = 36
  # + 4 critic rounds × 3 = 12
  # + synthesiser 8
  # = $62 worst-case if every step hits its ceiling.
  # $65 leaves $3 headroom for the cheap storers and stance-delta tool.
  max_cost_usd: 65.00

parameters:
  - key: question
    label: "Question"
    type: text
    required: true
    description: "The contested question to deliberate"
    placeholder: "e.g. What will agentic AI do to UK knowledge-work employment by 2030?"
  - key: rounds_max
    label: "Maximum rounds"
    type: integer
    required: false
    default: 3
  - key: agreement_intensity
    label: "Agreement intensity (0.0-1.0)"
    type: float
    required: false
    default: 0.2

context:
  question: ""
  rounds_max: 3
  agreement_intensity: 0.2
  early_stop_threshold: 0.15

edges:
  # Phase 0 → 1
  - {source: research,             target: verify-research}
  - {source: verify-research,      target: research-gate}
  - {source: research-gate,        target: halt-bad-research, label: failed,  source_handle: failed}
  - {source: research-gate,        target: open-systems,      label: passed,  source_handle: passed}
  - {source: research-gate,        target: open-quant,        label: passed,  source_handle: passed}
  - {source: research-gate,        target: open-empiricist,   label: passed,  source_handle: passed}
  - {source: research-gate,        target: open-ethicist,     label: passed,  source_handle: passed}

  # Phase 1 → 2 (critic round 0)
  - {source: open-systems,         target: critic-r0}
  - {source: open-quant,           target: critic-r0}
  - {source: open-empiricist,      target: critic-r0}
  - {source: open-ethicist,        target: critic-r0}

  # Phase 2 → 3 (debate round 1)
  - {source: critic-r0,            target: round1-systems}
  - {source: critic-r0,            target: round1-quant}
  - {source: critic-r0,            target: round1-empiricist}
  - {source: critic-r0,            target: round1-ethicist}

  # Phase 3 → 4 (critic round 1)
  - {source: round1-systems,       target: critic-r1}
  - {source: round1-quant,         target: critic-r1}
  - {source: round1-empiricist,    target: critic-r1}
  - {source: round1-ethicist,      target: critic-r1}

  # Early-stop after round 1
  - {source: critic-r1,            target: delta-r1}
  - {source: delta-r1,             target: stop-r1}
  - {source: stop-r1,              target: round2-systems,    label: continue, source_handle: continue}
  - {source: stop-r1,              target: round2-quant,      label: continue, source_handle: continue}
  - {source: stop-r1,              target: round2-empiricist, label: continue, source_handle: continue}
  - {source: stop-r1,              target: round2-ethicist,   label: continue, source_handle: continue}
  - {source: stop-r1,              target: final-merge,       label: halt,     source_handle: halt}

  # Round 2 → critic round 2
  - {source: round2-systems,       target: critic-r2}
  - {source: round2-quant,         target: critic-r2}
  - {source: round2-empiricist,    target: critic-r2}
  - {source: round2-ethicist,      target: critic-r2}

  # Early-stop after round 2
  - {source: critic-r2,            target: delta-r2}
  - {source: delta-r2,             target: stop-r2}
  - {source: stop-r2,              target: round3-systems,    label: continue, source_handle: continue}
  - {source: stop-r2,              target: round3-quant,      label: continue, source_handle: continue}
  - {source: stop-r2,              target: round3-empiricist, label: continue, source_handle: continue}
  - {source: stop-r2,              target: round3-ethicist,   label: continue, source_handle: continue}
  - {source: stop-r2,              target: final-merge,       label: halt,     source_handle: halt}

  # Round 3 → final merge
  - {source: round3-systems,       target: critic-r3}
  - {source: round3-quant,         target: critic-r3}
  - {source: round3-empiricist,    target: critic-r3}
  - {source: round3-ethicist,      target: critic-r3}
  - {source: critic-r3,            target: final-merge}

  # Synthesis + persist (Markdown + structured JSON + transcript JSON + learning)
  - {source: final-merge,    target: synthesise}
  - {source: synthesise,     target: store-deliverable-markdown}
  - {source: synthesise,     target: store-deliverable-json}
  - {source: synthesise,     target: store-transcript}
  - {source: synthesise,     target: store-learning}

steps:
  # ---------------------------------------------------------------------------
  # Phase 0: Research + verification
  # ---------------------------------------------------------------------------
  - id: research
    label: "Assemble research packet"
    description: "Produce a structured evidence packet for the deliberation"
    capability: deliberation.researcher
    roster: default
    complexity_tier: complex
    cost_ceiling_usd: 5.00
    input:
      question: "@context.question"
    timeout_seconds: 1800
    depends_on: []

  - id: verify-research
    label: "Verify research packet"
    description: "Audit the research packet for plausibility and source quality"
    capability: deliberation.research_verifier
    roster: default
    complexity_tier: simple
    cost_ceiling_usd: 1.00
    input:
      packet: "@node.research.output"
    depends_on:
      - research

  - id: research-gate
    label: "Research gate"
    description: "Halt the workflow if the packet failed verification"
    node_type: decision
    decision_config:
      resolver: rule
      expression: "@node.verify-research.output.passed == true"
      options:
        - key: passed
          label: "Packet passed verification — proceed to blind opening"
        - key: failed
          label: "Packet failed verification — halt and surface issues"
    depends_on:
      - verify-research

  - id: halt-bad-research
    label: "Halt: bad research"
    description: "Halt the workflow loud (status=failed) because the research packet failed verification"
    node_type: tool_call
    tool_call_config:
      tool_name: halt_workflow
      tool_args:
        # issues_text is the human-readable joined form (one bullet per issue).
        # Using `issues` (the list) would str()-coerce to Python repr.
        reason: "Research packet failed verification:\n{{@node.verify-research.output.issues_text}}"
        channel: sse
    depends_on:
      - research-gate

  # ---------------------------------------------------------------------------
  # Phase 1: Blind opening (parallel; no debater sees another's opening)
  # ---------------------------------------------------------------------------
  - id: open-systems
    label: "Open: Systems Mapper"
    description: "Blind opening position — Systems Mapper"
    capability: deliberation.debater_systems
    roster: default
    complexity_tier: complex
    cost_ceiling_usd: 3.00
    input:
      question: "@context.question"
      research_packet: "@node.research.output"
      round_index: 0
      agreement_intensity: "@context.agreement_intensity"
    depends_on:
      - research-gate

  - id: open-quant
    label: "Open: Reductionist Quant"
    capability: deliberation.debater_quant
    roster: default
    complexity_tier: complex
    cost_ceiling_usd: 3.00
    input:
      question: "@context.question"
      research_packet: "@node.research.output"
      round_index: 0
      agreement_intensity: "@context.agreement_intensity"
    depends_on:
      - research-gate

  - id: open-empiricist
    label: "Open: Adversarial Empiricist"
    capability: deliberation.debater_empiricist
    roster: default
    complexity_tier: complex
    cost_ceiling_usd: 3.00
    input:
      question: "@context.question"
      research_packet: "@node.research.output"
      round_index: 0
      agreement_intensity: "@context.agreement_intensity"
    depends_on:
      - research-gate

  - id: open-ethicist
    label: "Open: Distributional Ethicist"
    capability: deliberation.debater_ethicist
    roster: default
    complexity_tier: complex
    cost_ceiling_usd: 3.00
    input:
      question: "@context.question"
      research_packet: "@node.research.output"
      round_index: 0
      agreement_intensity: "@context.agreement_intensity"
    depends_on:
      - research-gate

  # ---------------------------------------------------------------------------
  # Phase 2: Critic round 0
  # ---------------------------------------------------------------------------
  - id: critic-r0
    label: "Critic — round 0"
    description: "Attack the load-bearing assumption of every debater"
    capability: deliberation.critic
    roster: default
    complexity_tier: complex
    cost_ceiling_usd: 3.00
    input:
      question: "@context.question"
      research_packet: "@node.research.output"
      round_index: 0
      positions:
        systems: "@node.open-systems.output"
        quant: "@node.open-quant.output"
        empiricist: "@node.open-empiricist.output"
        ethicist: "@node.open-ethicist.output"
    depends_on:
      - open-systems
      - open-quant
      - open-empiricist
      - open-ethicist

  # ---------------------------------------------------------------------------
  # Phase 3: Debate round 1 (sparse topology — see input mapping)
  # ---------------------------------------------------------------------------
  - id: round1-systems
    label: "Round 1: Systems Mapper"
    capability: deliberation.debater_systems
    roster: default
    complexity_tier: complex
    cost_ceiling_usd: 3.00
    input:
      question: "@context.question"
      round_index: 1
      own_previous: "@node.open-systems.output"
      opponents_previous:
        quant: "@node.open-quant.output"
        empiricist: "@node.open-empiricist.output"
        ethicist: "@node.open-ethicist.output"
      critic_attack_on_self: "@node.critic-r0.output.attacks.systems"
    depends_on:
      - critic-r0

  - id: round1-quant
    label: "Round 1: Reductionist Quant"
    capability: deliberation.debater_quant
    roster: default
    complexity_tier: complex
    cost_ceiling_usd: 3.00
    input:
      question: "@context.question"
      round_index: 1
      own_previous: "@node.open-quant.output"
      opponents_previous:
        systems: "@node.open-systems.output"
        empiricist: "@node.open-empiricist.output"
        ethicist: "@node.open-ethicist.output"
      critic_attack_on_self: "@node.critic-r0.output.attacks.quant"
    depends_on:
      - critic-r0

  - id: round1-empiricist
    label: "Round 1: Adversarial Empiricist"
    capability: deliberation.debater_empiricist
    roster: default
    complexity_tier: complex
    cost_ceiling_usd: 3.00
    input:
      question: "@context.question"
      round_index: 1
      own_previous: "@node.open-empiricist.output"
      opponents_previous:
        systems: "@node.open-systems.output"
        quant: "@node.open-quant.output"
        ethicist: "@node.open-ethicist.output"
      critic_attack_on_self: "@node.critic-r0.output.attacks.empiricist"
    depends_on:
      - critic-r0

  - id: round1-ethicist
    label: "Round 1: Distributional Ethicist"
    capability: deliberation.debater_ethicist
    roster: default
    complexity_tier: complex
    cost_ceiling_usd: 3.00
    input:
      question: "@context.question"
      round_index: 1
      own_previous: "@node.open-ethicist.output"
      opponents_previous:
        systems: "@node.open-systems.output"
        quant: "@node.open-quant.output"
        empiricist: "@node.open-empiricist.output"
      critic_attack_on_self: "@node.critic-r0.output.attacks.ethicist"
    depends_on:
      - critic-r0

  # ---------------------------------------------------------------------------
  # Phase 4: Critic round 1 + early-stop check
  # ---------------------------------------------------------------------------
  - id: critic-r1
    label: "Critic — round 1"
    capability: deliberation.critic
    roster: default
    complexity_tier: complex
    cost_ceiling_usd: 3.00
    input:
      question: "@context.question"
      research_packet: "@node.research.output"
      round_index: 1
      positions:
        systems: "@node.round1-systems.output"
        quant: "@node.round1-quant.output"
        empiricist: "@node.round1-empiricist.output"
        ethicist: "@node.round1-ethicist.output"
    depends_on:
      - round1-systems
      - round1-quant
      - round1-empiricist
      - round1-ethicist

  - id: delta-r1
    label: "Compute stance delta (round 1)"
    description: "Deterministic computation of stance vector change"
    node_type: tool_call
    tool_call_config:
      tool_name: compute_stance_delta
      tool_args:
        previous_round:
          systems: "@node.open-systems.output"
          quant: "@node.open-quant.output"
          empiricist: "@node.open-empiricist.output"
          ethicist: "@node.open-ethicist.output"
        current_round:
          systems: "@node.round1-systems.output"
          quant: "@node.round1-quant.output"
          empiricist: "@node.round1-empiricist.output"
          ethicist: "@node.round1-ethicist.output"
        threshold: "@context.early_stop_threshold"
    depends_on:
      - critic-r1

  - id: stop-r1
    label: "Early-stop check (round 1)"
    description: "If stance stable AND no CONCEDE/REFINE this round, halt. Else continue."
    node_type: decision
    decision_config:
      resolver: rule
      expression: "@node.delta-r1.output.should_continue == true"
      options:
        - key: continue
          label: "Stance still moving — continue to round 2"
        - key: halt
          label: "Stance stable — proceed to synthesis"
    depends_on:
      - delta-r1

  # ---------------------------------------------------------------------------
  # Phase 5: Round 2 (sparse topology again; gated by stop-r1)
  # ---------------------------------------------------------------------------
  - id: round2-systems
    label: "Round 2: Systems Mapper"
    capability: deliberation.debater_systems
    roster: default
    complexity_tier: complex
    cost_ceiling_usd: 3.00
    input:
      question: "@context.question"
      round_index: 2
      own_previous: "@node.round1-systems.output"
      opponents_previous:
        quant: "@node.round1-quant.output"
        empiricist: "@node.round1-empiricist.output"
        ethicist: "@node.round1-ethicist.output"
      critic_attack_on_self: "@node.critic-r1.output.attacks.systems"
    depends_on:
      - stop-r1

  # ... round2-quant, round2-empiricist, round2-ethicist follow the same pattern.
  # (Full YAML in the implementation will list them; truncated here for plan readability.)

  - id: critic-r2
    label: "Critic — round 2"
    capability: deliberation.critic
    # ... same shape as critic-r1
    depends_on:
      - round2-systems
      - round2-quant
      - round2-empiricist
      - round2-ethicist

  - id: delta-r2
    node_type: tool_call
    # ... compute_stance_delta between round 1 and round 2
    depends_on:
      - critic-r2

  - id: stop-r2
    node_type: decision
    decision_config:
      resolver: rule
      expression: "@node.delta-r2.output.should_continue == true"
      options:
        - key: continue
          label: "Continue to round 3"
        - key: halt
          label: "Stance stable — synthesise"
    depends_on:
      - delta-r2

  # ---------------------------------------------------------------------------
  # Phase 6: Round 3 (final round; no early-stop check after it)
  # ---------------------------------------------------------------------------
  - id: round3-systems
    # ... same pattern, sparse topology
    depends_on:
      - stop-r2

  # ... round3-quant, round3-empiricist, round3-ethicist

  - id: critic-r3
    capability: deliberation.critic
    depends_on:
      - round3-systems
      - round3-quant
      - round3-empiricist
      - round3-ethicist

  # ---------------------------------------------------------------------------
  # Phase 7: Synthesis + persist
  # ---------------------------------------------------------------------------
  - id: final-merge
    label: "Final merge"
    description: "Converge round 1/2/3 termination paths"
    node_type: merge
    merge_config:
      strategy: wait_all
    depends_on:
      - stop-r1
      - stop-r2
      - critic-r3

  - id: synthesise
    label: "Synthesise"
    description: "Map cruxes, preserve minority position, audit vs mainstream, emit both structured output and Markdown rendering"
    capability: deliberation.synthesiser
    roster: default
    complexity_tier: complex
    cost_ceiling_usd: 8.00
    input:
      question: "@context.question"
      research_packet: "@node.research.output"
      mainstream_consensus: "@node.research.output.mainstream_consensus"
      all_rounds:
        round_0:
          systems: "@node.open-systems.output"
          quant: "@node.open-quant.output"
          empiricist: "@node.open-empiricist.output"
          ethicist: "@node.open-ethicist.output"
        round_1:
          systems: "@node.round1-systems.output"
          quant: "@node.round1-quant.output"
          empiricist: "@node.round1-empiricist.output"
          ethicist: "@node.round1-ethicist.output"
        round_2:
          systems: "@node.round2-systems.output"
          quant: "@node.round2-quant.output"
          empiricist: "@node.round2-empiricist.output"
          ethicist: "@node.round2-ethicist.output"
        round_3:
          systems: "@node.round3-systems.output"
          quant: "@node.round3-quant.output"
          empiricist: "@node.round3-empiricist.output"
          ethicist: "@node.round3-ethicist.output"
      critic_reports:
        round_0: "@node.critic-r0.output"
        round_1: "@node.critic-r1.output"
        round_2: "@node.critic-r2.output"
        round_3: "@node.critic-r3.output"
    timeout_seconds: 3600
    depends_on:
      - final-merge

  # Persistence: the synthesiser produces structured FinalDeliverable AND
  # report_markdown + recommendation_markdown in a single call (per S3). No
  # separate render steps. Three artifacts are stored:
  # 1. Markdown deliverable (human-readable)
  # 2. JSON deliverable (programmatically queryable, schema-validated)
  # 3. JSON transcript (full audit trail of every round)

  - id: store-deliverable-markdown
    label: "Store deliverable (Markdown)"
    node_type: tool_call
    tool_call_config:
      tool_name: store_artifact
      tool_args:
        title: "Think Tank Deliverable: {{@context.question}}"
        content: "{{@node.synthesise.output.report_markdown}}"
        artifact_type: deliberation_deliverable
        content_type: markdown
    depends_on:
      - synthesise

  - id: store-deliverable-json
    label: "Store deliverable (structured JSON)"
    description: "Persist the schema-validated FinalDeliverable as JSON so programmatic queries preserve cruxes, minority position, and the merely_reproduces flag."
    node_type: tool_call
    tool_call_config:
      tool_name: store_artifact
      tool_args:
        title: "Think Tank Deliverable (structured): {{@context.question}}"
        # Standalone ref — §8.6 preserves the dict; §9.1 JSON-encodes it.
        content: "{{@node.synthesise.output}}"
        artifact_type: deliberation_deliverable
        content_type: json
    depends_on:
      - synthesise

  - id: store-transcript
    label: "Store transcript (structured JSON)"
    description: "Persist the full deliberation transcript for audit and future synthesis verification (B2)."
    node_type: tool_call
    tool_call_config:
      tool_name: store_artifact
      tool_args:
        title: "Think Tank Transcript: {{@context.question}}"
        artifact_type: deliberation_transcript
        content_type: json
        # §8.4 deep-resolve walks the nested dict; §8.6 preserves each ref's type;
        # §9.1 JSON-encodes the resulting dict for storage. Skipped-round refs
        # (e.g. round_3 when early-stop fired) resolve to None and serialise as null.
        content:
          question: "{{@context.question}}"
          research_packet: "{{@node.research.output}}"
          rounds:
            round_0:
              systems: "{{@node.open-systems.output}}"
              quant: "{{@node.open-quant.output}}"
              empiricist: "{{@node.open-empiricist.output}}"
              ethicist: "{{@node.open-ethicist.output}}"
            round_1:
              systems: "{{@node.round1-systems.output}}"
              quant: "{{@node.round1-quant.output}}"
              empiricist: "{{@node.round1-empiricist.output}}"
              ethicist: "{{@node.round1-ethicist.output}}"
            round_2:
              systems: "{{@node.round2-systems.output}}"
              quant: "{{@node.round2-quant.output}}"
              empiricist: "{{@node.round2-empiricist.output}}"
              ethicist: "{{@node.round2-ethicist.output}}"
            round_3:
              systems: "{{@node.round3-systems.output}}"
              quant: "{{@node.round3-quant.output}}"
              empiricist: "{{@node.round3-empiricist.output}}"
              ethicist: "{{@node.round3-ethicist.output}}"
          critic_reports:
            round_0: "{{@node.critic-r0.output}}"
            round_1: "{{@node.critic-r1.output}}"
            round_2: "{{@node.critic-r2.output}}"
            round_3: "{{@node.critic-r3.output}}"
          stance_deltas:
            after_round_1: "{{@node.delta-r1.output}}"
            after_round_2: "{{@node.delta-r2.output}}"
    depends_on:
      - synthesise

  - id: store-learning
    node_type: tool_call
    tool_call_config:
      tool_name: store_learning
      tool_args:
        title: "Deliberation cruxes: {{@context.question}}"
        body: "{{@node.synthesise.output.report_markdown}}"
        recommendation: "{{@node.synthesise.output.recommendation_markdown}}"
        kind: deliberation
        domain_tags:
          - deliberation
          - cruxes
        # Standalone refs — §8.6 preserves float / list types
        confidence: "{{@node.synthesise.output.confidence}}"
    depends_on:
      - synthesise
```

**Note on the truncation.** The plan YAML above truncates round 2 and round 3 step definitions for readability. The implementation must list all four debater steps per round explicitly — **mechanically generated from the round 1 template**, not hand-typed. The pattern is:

- Replace `round1-` with `round2-` / `round3-` in `id` and `label`.
- Set `round_index` to 2 / 3.
- Replace `own_previous: @node.open-X.output` with `@node.round1-X.output` (round 2) or `@node.round2-X.output` (round 3).
- Replace `opponents_previous` refs from `open-Y` → `round1-Y` / `round2-Y`.
- Replace `critic_attack_on_self: @node.critic-r0.output.attacks.X` with `critic-r1.output.attacks.X` / `critic-r2.output.attacks.X`.
- Replace `depends_on: [critic-r0]` with `[stop-r1]` / `[stop-r2]`.

Total node count: **34**. Breakdown by node_type:

| node_type | Count | Step IDs |
|---|---|---|
| `agent_step` | 23 | research, verify-research, open-{systems,quant,empiricist,ethicist}, critic-r0, round{1,2,3}-{systems,quant,empiricist,ethicist}, critic-r{1,2,3}, synthesise |
| `tool_call` | 7 | halt-bad-research, delta-r1, delta-r2, store-deliverable-markdown, store-deliverable-json, store-transcript, store-learning |
| `decision` | 3 | research-gate, stop-r1, stop-r2 |
| `merge` | 1 | final-merge |
| **Total** | **34** | |

(v4 had 2 `llm_call` and 1 `notification` for the rendering steps and the soft-halt. v5 removed both: the synthesiser now emits its own Markdown, and the halt is a tool_call to `halt_workflow` so the run status is `failed` rather than `completed`.)

The Phase 8 static assertion (§12) is the source of truth for this count.

A small generator helper (a Python script or a Jinja template) is preferable to hand-editing 12 near-identical step blocks. Hand-edits are exactly where sparse-topology refs get scrambled.

---

## 8. Platform enablers

Four small platform changes required. All four are minimal, generic, and benefit any workflow that needs richer cross-node data wiring — not just deliberation. Quality-check pass identified that the v1 plan was missing two of these (§8.3 and §8.4).

### 8.0 Reuse manifest (what we explicitly do NOT touch)

| Existing primitive | Location | Status |
|---|---|---|
| `resolve_template(template, completed_outcomes, ctx)` — `{{@node.X.output.field}}` substitution in strings | [services/condition_evaluator.py:419](modules/backend/services/condition_evaluator.py#L419) | Reused for tool_call/llm_call/notification templates; modified in §8.5 (fail-loud) and §8.6 (type preservation) |
| `_resolve_ref(path, completed_outcomes, ctx)` — bare-ref resolution including auto-unwrap of `"output"` key | [services/condition_evaluator.py:283](modules/backend/services/condition_evaluator.py#L283) | Promoted to public `resolve_ref` and reused for new resolvers below |
| `evaluate_condition`, `evaluate_expression`, AST tokeniser | [services/condition_evaluator.py](modules/backend/services/condition_evaluator.py) | Reused unchanged by decision-gate `rule` resolvers |
| `get_embedder()` factory + `Embedder.embed(text) -> list[float]` | [core/embeddings.py:179](modules/backend/core/embeddings.py#L179) | Reused unchanged by `compute_stance_delta` |
| `assemble_instructions(namespace, agent)` | [agents/mission_control/helpers/...](modules/backend/agents/mission_control/helpers/) | Reused by all 8 new agents — same pattern as `research.analyst.agent` |
| `BaseAgentDeps` | [agents/deps/base.py](modules/backend/agents/deps/base.py) | Reused by all 8 new agents |
| Tool auto-discovery via `TOOL_DEF` dict | [tools/registry.py](modules/backend/tools/registry.py) | `compute_stance_delta` registers automatically |
| `store_artifact`, `store_learning`, `query_knowledge`, `search_web`, `fetch_url` | [tools/](modules/backend/tools/) | Reused as-is |
| `WorkflowSchema` + `edges` + decision `_branch` routing | [schemas/workflow.py](modules/backend/schemas/workflow.py) | Reused as Plan 75 designed |
| `merge` node with `wait_all` over partially-skipped predecessors | [services/workflow_run_waves.py:944](modules/backend/services/workflow_run_waves.py#L944) | Reused at `final-merge` — Plan 75's documented mechanism |
| Workflow seeder picks up YAML in `config/workflow_templates/` | (existing) | No code change for catalog visibility |
| `ExecutionOutcome.task_results[].output_reference` carries structured agent output | [schemas/execution_outcome.py:106](modules/backend/schemas/execution_outcome.py#L106) | Source of truth read by the new default-output enabler in §8.3 |

### 8.1 Shared recursive ref walker

**File:** [modules/backend/services/condition_evaluator.py](modules/backend/services/condition_evaluator.py) (new helper) — used by both §8.1's agent_step input resolver and §8.4's tool_call args resolver.

Per C1 from the adversarial review: §8.1 and §8.4 are 85% the same code. Extract one helper parameterised by the leaf resolver:

```python
def walk_refs(value, completed_outcomes, workflow_context, *, leaf_resolver, source_id="<unknown>"):
    """Recursively walk str/dict/list, applying leaf_resolver to strings.

    leaf_resolver(s: str) -> Any handles the per-syntax substitution
    (bare-ref via resolve_ref, or template via resolve_template).
    Non-str/dict/list values pass through unchanged.

    Raises ConditionEvaluationError (or whatever the leaf resolver raises)
    on structural errors. Caller wraps with ValueError(source_id, ...) if
    a richer error message is needed.
    """
    if isinstance(value, str):
        return leaf_resolver(value)
    if isinstance(value, dict):
        return {k: walk_refs(v, completed_outcomes, workflow_context,
                             leaf_resolver=leaf_resolver, source_id=source_id) for k, v in value.items()}
    if isinstance(value, list):
        return [walk_refs(v, completed_outcomes, workflow_context,
                          leaf_resolver=leaf_resolver, source_id=source_id) for v in value]
    return value
```

### 8.1a `resolve_upstream_context` uses `walk_refs` with bare-ref resolver

**File:** [modules/backend/services/workflow.py:289](modules/backend/services/workflow.py#L289)

Today only `@context.*` strings are resolved (line 310). The fix delegates to `resolve_ref` (the promoted `_resolve_ref`) for any `@`-prefixed bare string, via `walk_refs`:

```python
def resolve_upstream_context(self, step, completed_outcomes, workflow_context):
    from modules.backend.services.condition_evaluator import (
        walk_refs, resolve_ref, ConditionEvaluationError,
    )

    upstream: dict[str, Any] = dict(workflow_context)
    for dep_id in step.depends_on:
        if dep_id in completed_outcomes:
            upstream.update(completed_outcomes[dep_id])

    def _leaf(s: str):
        if s.startswith("@"):
            try:
                return resolve_ref(s, completed_outcomes, workflow_context)
            except ConditionEvaluationError as e:
                raise ValueError(f"Step '{step.id}': unresolvable reference '{s}': {e}") from e
        return s

    resolved_input = walk_refs(
        step.input, completed_outcomes, workflow_context,
        leaf_resolver=_leaf, source_id=step.id,
    )
    upstream["_step_input"] = resolved_input
    return upstream
```

**Visibility of `_resolve_ref`:** promote to public `resolve_ref` and export `ConditionEvaluationError`. Internal callers in `condition_evaluator.py` (lines 319, 430) update to use the new public name.

**Fail-loud behaviour:** unresolved refs raise `ValueError` with the step id, the unresolved path, and the underlying error.

### 8.2 Extend `_build_step_objective` to handle dict and structured-output inputs

**File:** [modules/backend/services/workflow_run_waves.py:1291](modules/backend/services/workflow_run_waves.py#L1291)

Today only `str` and `list` are formatted; dict values are dropped. The debater inputs are dicts (sparse topology). Extension (~10 lines): JSON-encode dict and Pydantic-model values with `default=str` for safety.

```python
def _build_step_objective(self, step, step_input):
    import json
    parts = [step.description or f"Execute step: {step.id}"]
    if step_input:
        context_parts = []
        for key, value in step_input.items():
            if isinstance(value, (dict, list)):
                context_parts.append(f"{key}: {json.dumps(value, default=str)}")
            elif value is not None:
                context_parts.append(f"{key}: {value}")
        if context_parts:
            parts.append("Context: " + "; ".join(context_parts))
    return ". ".join(parts)
```

**Risk:** the objective string can get large (the synthesiser passes a full transcript). Today `objective` is stored on `ExecutionRecord.objective_statement` which is a TEXT column — no length cap. Still, the synthesiser-step objective will be several hundred KB. Acceptable for v1; if profiling shows a problem, the synthesiser can read the transcript from the artifact store instead of via objective. Documented as a follow-up risk in §13.

### 8.3 Default-populate `completed_outcomes` for agent_step (LOAD-BEARING)

**File:** [modules/backend/services/workflow_run_waves.py:534](modules/backend/services/workflow_run_waves.py#L534)

This is the most important enabler. The quality-check pass caught that today `extract_outputs(outcome_dict, output_mapping)` returns `{}` when `output_mapping` is None. For tool_call and llm_call nodes, output is populated by their own dispatchers. For agent_step, with no `output_mapping`, `completed_outcomes[step.id]` is `{}` and every downstream `@node.X.output.field` reference resolves to None.

Without this enabler, the entire deliberation workflow chains through empty dicts.

**B3 fix from the adversarial review:** extraction matches by `agent_name` (`step.capability + ".agent"`), not by `task_results[-1]`. The previous design risked picking up an integrator/summariser task in multi-task plans.

Required change (~25 lines):

```python
# In _execute_step around line 528, replace the existing extract_outputs call:
expected_agent = f"{step.capability}.agent" if step.capability else None
extracted = _extract_default_agent_output(outcome_dict, expected_agent=expected_agent)
if output_mapping:
    extracted.update(ctx.persistence.extract_outputs(outcome_dict, output_mapping))

# Module-level helper:
def _extract_default_agent_output(
    outcome_dict: dict | None,
    *,
    expected_agent: str | None = None,
) -> dict[str, Any]:
    """Default-populate completed_outcomes for an agent_step.

    Strategy:
    1. If expected_agent is given, find the TaskResult whose agent_name matches.
       This is the deterministic case for single-capability agent_steps.
    2. Otherwise fall back to the last task_result (legacy behaviour for
       multi-task plans where the integrator runs last). Log a warning when
       this fallback fires so the case stays visible.

    Output is wrapped under "output" key so @node.X.output.field references
    auto-unwrap (matching the convention used by tool_call/llm_call dispatchers).
    """
    if not outcome_dict:
        return {}
    task_results = outcome_dict.get("task_results", []) or []
    if not task_results:
        return {}

    if expected_agent:
        for tr in task_results:
            if isinstance(tr, dict) and tr.get("agent_name") == expected_agent:
                return {"output": tr.get("output_reference", {})}
        logger.warning(
            "Agent name match failed for default-output extraction; falling back to last task",
            extra={"expected_agent": expected_agent,
                   "available": [tr.get("agent_name") for tr in task_results if isinstance(tr, dict)]},
        )

    last = task_results[-1]
    output_ref = last.get("output_reference", {}) if isinstance(last, dict) else {}
    return {"output": output_ref}
```

**Tests:** new unit tests in `test_workflow_run_waves.py` covering:
- empty `task_results` → `{}`;
- single task_result, expected_agent matches → `{"output": <dict>}`;
- multiple task_results, expected_agent matches one → returns that one's output_reference;
- multiple task_results, no expected_agent match → falls back to `[-1]` and logs warning;
- output_mapping present → merged result.

**V1 verification gate:** before declaring Phase 1 done, run a deliberation agent_step end-to-end through `handle_mission` and assert that the `ExecutionOutcome.task_results` contains exactly one entry with `agent_name == "deliberation.debater_systems.agent"`. If `handle_mission` produces multiple tasks even for single-capability dispatch (planning agent decomposition), this assertion catches it and the agent-name match guarantees correctness anyway.

### 8.4 Deep-resolve refs in tool_call `tool_args`

**File:** [modules/backend/services/workflow_run_waves.py:840](modules/backend/services/workflow_run_waves.py#L840)

Today the tool_call dispatcher only resolves refs in top-level **string** args. Nested dicts and lists pass through unchanged, so `tool_args.previous_round.systems = "{{@node.X.output}}"` inside a dict-valued arg is delivered as the literal string, not the resolved value.

Replace the existing for-loop at line 840 with a call to the shared `walk_refs` helper from §8.1, this time with `resolve_template` as the leaf resolver:

```python
# In _execute_tool_call_step:
from modules.backend.services.condition_evaluator import walk_refs, resolve_template

resolved_args = walk_refs(
    tool_args, completed_outcomes, run.context,
    leaf_resolver=lambda s: resolve_template(s, completed_outcomes, run.context),
    source_id=f"tool_call:{step.id}",
)
```

The leaf-resolver choice is the only difference from §8.1a: bare `@`-prefixed refs (no braces) in agent_step input vs `{{@ref}}` templates in tool_args. Same walker.

**Tests:** nested dict with `{{@node...}}` refs in dict values; lists of refs; standalone-vs-mixed refs (verifies §8.6 type preservation propagates through the walker).

### 8.5 Make `resolve_template` fail loud on structural errors

**File:** [modules/backend/services/condition_evaluator.py:419](modules/backend/services/condition_evaluator.py#L419)

Today `resolve_template` catches `ConditionEvaluationError` and leaves the literal `{{@badref}}` in the output (line 432–433). That swallows two different failure modes into the same silent passthrough:

1. **Structural error** — typo in the ref root (`@nodez.X` instead of `@node.X`), malformed expression. This is always a bug. Must fail loud.
2. **Missing-data path** — a legitimate skipped predecessor produces `None` when its outputs are walked. This is expected behaviour for branched workflows. Must keep returning `""`.

`_resolve_ref` already raises `ConditionEvaluationError` only for case 1 (line 311: "Unknown reference root"). For case 2 it returns `None` and the existing line 431 maps that to `""`. So the fix is to **not catch** `ConditionEvaluationError` — let it propagate. The existing test of catching the error in `_replace` is wrong.

Required change (~3 lines):

```python
def _replace(m: re.Match) -> str:
    ref = m.group(1).strip()
    val = _resolve_ref(ref, completed_outcomes, ctx)
    return str(val) if val is not None else ""
# (delete the try/except wrapper)
```

**Internal caller update:** after the `_resolve_ref` → `resolve_ref` rename from §8.0, the two private call sites in the same file (line 319 inside `_eval`, line 430 inside the existing `resolve_template._replace`) must reference the new public name. Both are pure renames, no behaviour change.

**Risk:** any caller today that relies on the silent fall-back (typo in a yaml file that "works because the marker survives") will start failing at workflow load. That is the intended behaviour — fail-fast project principle (no silent fallbacks). Mitigation: §8.7 below catches the same class of bug statically at workflow load time, so most bad refs are caught before runtime.

**Tests:** typo in tool_arg ref → `ConditionEvaluationError` propagates; valid ref to a skipped predecessor → returns `""` (no exception). Add to the existing condition_evaluator test suite.

### 8.6 Preserve types for standalone refs

**File:** [modules/backend/services/condition_evaluator.py:419](modules/backend/services/condition_evaluator.py#L419) — same function as §8.5.

Today every resolved ref is `str(val)`-coerced because `resolve_template` is a regex-substitution over a string. That breaks numeric/boolean/list passthrough: `confidence: "{{@node.X.confidence}}"` resolves a `float` 0.85 but gets coerced to the string `"0.85"`, then handed to `store_learning` which expects `confidence: float`.

Fix: detect the **standalone ref pattern** — the entire string (modulo whitespace) is exactly `{{@ref}}` — and return the raw resolved value preserving its Python type. Mixed templates with surrounding text continue to produce strings.

Required change (~10 lines, returns `Any` not `str` for the standalone case):

```python
_STANDALONE_RE = re.compile(r"^\s*\{\{(@[^}]+)\}\}\s*$")

def resolve_template(template, completed_outcomes, workflow_context=None):
    """Resolve {{@node.x.y}} and {{@context.k}} placeholders.

    If the entire template is a single ref, returns the raw resolved value
    preserving its type. Otherwise returns a string with substitutions applied.
    """
    if not isinstance(template, str):
        return template
    ctx = workflow_context or {}

    # Standalone ref: preserve type
    m = _STANDALONE_RE.match(template)
    if m:
        return _resolve_ref(m.group(1).strip(), completed_outcomes, ctx)

    # Multi-ref or mixed-text: string substitution
    def _replace(m: re.Match) -> str:
        val = _resolve_ref(m.group(1).strip(), completed_outcomes, ctx)
        return str(val) if val is not None else ""
    return re.sub(r"\{\{(@[^}]+)\}\}", _replace, template)
```

**Type implication:** the return type changes from `str` to `Any`. All call sites (tool_call dispatcher, llm_call dispatcher, notification dispatcher) currently accept strings — they'll continue to accept them, plus now they handle structured values transparently. The tool_call dispatcher (§8.4) and the agent_step input resolver (§8.1) both benefit immediately.

**Existing YAML audit:** grep over `config/workflow_templates/*.yaml` confirmed no existing standalone `{{@ref}}` arg today resolves to a non-string value. The decision-routing workflow's standalone refs (`body: "{{@node.summarize.output}}"`, etc.) all point to llm_call outputs which return `{"output": <str>}`. No behaviour change for existing workflows.

**Tests:** standalone float ref preserves `float`; standalone list ref preserves `list`; mixed `"prefix {{ref}} suffix"` produces `str`; whitespace around the standalone ref is tolerated.

### 8.7 Workflow load-time validation of `@node.X` refs

**File:** [modules/backend/schemas/workflow.py:474](modules/backend/schemas/workflow.py#L474) (extend the existing `validate_steps`).

Today `validate_steps` validates step IDs, dep references, cycles, and output-mapping target keys (line 478–537). It does **not** validate that `@node.X.field` references inside `step.input` or `tool_call_config.tool_args` point to declared steps. A typo like `@node.opem-systems.output` (missing 'n') currently passes load, then silently produces empty values at runtime.

After §8.5/§8.6 the typo would raise at runtime — but for a 34-node workflow that runs for hours, catching it at runtime is too late. Load-time validation is cheap and saves whole runs.

Required change (~25 lines), new helper called from `validate_steps`:

```python
_NODE_REF_RE = re.compile(r"@node\.([a-z][a-z0-9_-]*)(?:\.[a-zA-Z0-9_.-]+)?")

def _collect_node_refs(value: Any) -> list[str]:
    """Walk str/dict/list recursively, return list of @node.X step IDs referenced."""
    if isinstance(value, str):
        return _NODE_REF_RE.findall(value)
    if isinstance(value, dict):
        out = []
        for v in value.values():
            out.extend(_collect_node_refs(v))
        return out
    if isinstance(value, list):
        out = []
        for v in value:
            out.extend(_collect_node_refs(v))
        return out
    return []

# Inside validate_steps, after the cycle-detection block:
step_ids = {step.id for step in steps}
for step in steps:
    refs: list[str] = _collect_node_refs(step.input)
    if step.tool_call_config:
        refs.extend(_collect_node_refs(step.tool_call_config.tool_args))
    if step.llm_call_config:
        refs.extend(_collect_node_refs(step.llm_call_config.prompt_template))
        if step.llm_call_config.system_prompt:
            refs.extend(_collect_node_refs(step.llm_call_config.system_prompt))
    if step.decision_config:
        if step.decision_config.expression:
            refs.extend(_collect_node_refs(step.decision_config.expression))
        if step.decision_config.prompt:
            refs.extend(_collect_node_refs(step.decision_config.prompt))
    if step.notification_config:
        refs.extend(_collect_node_refs(step.notification_config.message_template))
    if step.condition_config:
        refs.extend(_collect_node_refs(step.condition_config.expression))
    if step.condition:
        refs.extend(_collect_node_refs(step.condition))
    bad = [r for r in refs if r not in step_ids]
    if bad:
        raise ValueError(
            f"Step '{step.id}' references unknown step IDs: {sorted(set(bad))}. "
            f"Available: {sorted(step_ids)}"
        )
```

**Reusability:** any workflow gets this validation, not just deliberation. Catches the same class of bug in `security.code-assessment.workflow`, `research.deep-research.workflow`, and the existing `general.decision-routing.workflow`.

**Limitation:** does not validate the field path (`@node.research.output.mainstream_consensus` — we don't statically know what fields `research.output` has). Only validates the step ID. Field-level validation would require knowing each agent's `output_type` schema, which is not declared on `WorkflowStepSchema` today. Future enhancement.

**Tests:** workflow with a typo step ID in `tool_args` raises at parse time; workflow with all-valid refs parses cleanly; field-path-only typo (e.g. `@node.research.outpu.x`) is allowed (we only validate step IDs at this layer).

---

## 9. New deterministic tool: `compute_stance_delta`

**File:** `modules/backend/tools/compute_stance_delta.py` (new).

Pure function, no LLM. Computes a stance-vector delta between two rounds and decides whether the deliberation should continue. Replaces the "cosine distance over embeddings" hand-wave from the research doc with something the workflow can actually reproduce.

```python
"""
Tool: compute_stance_delta

Deterministic early-stop computation for the Think Tank workflow.
Computes a per-debater stance delta as a normalised distance between
their position embeddings on two consecutive rounds, then aggregates.

If aggregate delta < threshold AND no debater issued CONCEDE_PARTIAL,
CONCEDE_FULL, or REFINE in the most recent round, returns should_continue=False.
Otherwise returns should_continue=True.
"""

from __future__ import annotations
from typing import Any
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


async def compute_stance_delta(
    *,
    previous_round: dict[str, dict[str, Any]],
    current_round: dict[str, dict[str, Any]],
    threshold: float = 0.15,
) -> dict[str, Any]:
    """Compute per-debater stance delta and aggregate stop signal.

    Pure computation, no mission state read or write — `deps` is empty
    so the wave engine does not inject `mission_id` or `http_client`.
    All inputs come from `tool_args` (the workflow YAML).

    Args:
        previous_round: {debater_id: DebaterTurn dict}
        current_round: {debater_id: DebaterTurn dict}
        threshold: delta below which we consider stance stable

    Returns: StanceDelta dict.
    """
    from modules.backend.core.embeddings import get_embedder

    embedder = get_embedder()
    per_debater: dict[str, float] = {}
    any_active_revision = False

    for debater_id, curr in current_round.items():
        prev = previous_round.get(debater_id)
        if prev is None:
            per_debater[debater_id] = 1.0  # treat missing prior as max change
            continue

        # Embedding-based distance on the position string
        prev_emb = await embedder.embed(prev["position"])
        curr_emb = await embedder.embed(curr["position"])
        per_debater[debater_id] = _cosine_distance(prev_emb, curr_emb)

        # Confidence-weighted; large confidence swings count even if text is similar
        conf_delta = abs(curr.get("confidence", 0.5) - prev.get("confidence", 0.5))
        per_debater[debater_id] = max(per_debater[debater_id], conf_delta)

        if curr.get("decision") in {"CONCEDE_PARTIAL", "CONCEDE_FULL", "REFINE"}:
            any_active_revision = True

    aggregate = sum(per_debater.values()) / max(len(per_debater), 1)
    stance_stable = aggregate < threshold
    should_continue = (not stance_stable) or any_active_revision

    reasoning = (
        f"aggregate delta {aggregate:.3f} "
        f"{'<' if stance_stable else '>='} threshold {threshold:.3f}; "
        f"active_revision={any_active_revision}"
    )

    return {
        "delta": aggregate,
        "threshold": threshold,
        "should_continue": should_continue,
        "per_debater": per_debater,
        "reasoning": reasoning,
    }


def _cosine_distance(a: list[float], b: list[float]) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 1.0
    return 1.0 - (dot / (na * nb))


# ── Registry integration ─────────────────────────────────

TOOL_DEF = {
    "name": "compute_stance_delta",
    "description": "Deterministic stance-delta computation for the Think Tank early-stop check",
    "category": "workflow",
    "deps": [],
}

_impl = compute_stance_delta
```

**Note:** `get_embedder()` and `Embedder.embed()` are already available via `modules.backend.core.embeddings` (used by Plan 73 and the knowledge service). Reuse, no new dependency.

**S5 — parallel embedding:** the embed calls are independent across debaters. Replace the sequential for-loop with `asyncio.gather` over the 4 debater pairs:

```python
async def _embed_one(debater_id, prev, curr):
    if prev is None:
        return debater_id, 1.0
    prev_emb, curr_emb = await asyncio.gather(
        embedder.embed(prev["position"]),
        embedder.embed(curr["position"]),
    )
    text_distance = _cosine_distance(prev_emb, curr_emb)
    conf_delta = abs(curr.get("confidence", 0.5) - prev.get("confidence", 0.5))
    return debater_id, max(text_distance, conf_delta)

per_debater_pairs = await asyncio.gather(*[
    _embed_one(d, previous_round.get(d), curr)
    for d, curr in current_round.items()
])
per_debater = dict(per_debater_pairs)
```

Cuts early-stop latency from 8×serial to 1×parallel.

**C2 — drop unused `mission_id` dep:** the tool does not write to mission state, so it does not need `deps`. Update `TOOL_DEF` to `"deps": []`. The wave engine will not inject `mission_id`.

## 9.1 Extend `store_artifact` to accept structured content (B1)

**File:** [modules/backend/tools/store_artifact.py](modules/backend/tools/store_artifact.py)

Today `store_artifact` accepts `content: str`. The B1 fix needs to store the structured `FinalDeliverable` dict and the full transcript dict as JSON artifacts.

Two paths considered:
- Add a new dedicated tool `store_json_artifact`. Rejected: API creep, and the only thing it would do differently is JSON-encode.
- Extend `store_artifact` to accept `str | dict | list` and JSON-encode non-string content when `content_type` is `json` or `markdown` mismatches. **Chosen** — minimal surface change, fail-loud on type/content-type mismatch.

Required change (~15 lines):

```python
import json

async def store_artifact(
    mission_id: str,
    *,
    title: str,
    content: str | dict | list,
    artifact_type: str = "report",
    content_type: str = "markdown",
) -> str:
    if isinstance(content, (dict, list)):
        if content_type != "json":
            raise ValueError(
                f"store_artifact: content is {type(content).__name__} but "
                f"content_type is {content_type!r}; structured content requires "
                f"content_type='json'"
            )
        content_text = json.dumps(content, default=str, indent=2)
    elif isinstance(content, str):
        content_text = content
    else:
        raise TypeError(
            f"store_artifact: content must be str/dict/list, got {type(content).__name__}"
        )
    # ... existing persistence code, using content_text in place of content
```

**Backwards-compat:** existing callers pass strings — unchanged. Type union expands; no caller breaks. The `ValueError` on content_type mismatch is the fail-loud guard so a YAML author who accidentally passes a dict with `content_type=markdown` finds out immediately.

**Tests:** dict content + content_type=json → stored as indented JSON; dict content + content_type=markdown → raises ValueError; str content (existing path) → unchanged.

## 9.2 New tool: `halt_workflow` (S1)

**File:** `modules/backend/tools/halt_workflow.py` (new).

S1 from the adversarial review: the original `halt-bad-research` notification step left the workflow with `status=completed` (the run finished even though it produced no deliverable). A user glancing at the dashboard would think the deliberation succeeded.

This tool emits an SSE workflow-halted event and then **raises `RuntimeError`**. The tool_call dispatcher's existing exception-handling path ([workflow_run_waves.py:866](modules/backend/services/workflow_run_waves.py#L866)) explicitly re-raises `RuntimeError` (unlike other exceptions, which are caught and recorded as failures). The wave engine treats this as a step failure and marks the run as `failed`.

```python
"""
Tool: halt_workflow

Deliberately halt the current workflow run with a clear failure status.
Emits an SSE workflow-halted event before raising. Used by validation/gate
steps that need to fail loud rather than silently completing the workflow
with no deliverable.
"""

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


async def halt_workflow(*, reason: str, channel: str = "sse") -> None:
    """Halt the workflow with a clear failure status.

    Args:
        reason: Human-readable explanation of why the workflow is halting.
        channel: Notification channel for the halt event (sse, telegram).

    Raises:
        RuntimeError: Always. The tool_call dispatcher re-raises this so the
            run is marked failed rather than silently completed.
    """
    logger.warning("halt_workflow called", extra={"reason": reason, "channel": channel})
    # Note: SSE emission happens automatically because the tool_call dispatcher
    # publishes a WorkflowToolCallCompletedEvent regardless. The reason is
    # captured in that event's error field (set when success=False), but
    # since we re-raise immediately the event will carry the exception
    # message. No extra emission needed.
    raise RuntimeError(f"Workflow halted: {reason}")


TOOL_DEF = {
    "name": "halt_workflow",
    "description": "Halt the workflow with a clear failure status and emit a notification",
    "category": "workflow",
    "deps": [],
}

_impl = halt_workflow
```

The new `halt-bad-research` step (see updated §7) uses this tool:

```yaml
- id: halt-bad-research
  label: "Halt: bad research"
  description: "Halt the workflow loud because the research packet failed verification"
  node_type: tool_call
  tool_call_config:
    tool_name: halt_workflow
    tool_args:
      reason: "Research packet failed verification: {{@node.verify-research.output.issues}}"
      channel: sse
  depends_on:
    - research-gate
```

**Tests:** invoking `halt_workflow(reason="x")` raises `RuntimeError("Workflow halted: x")`; the wave engine, given a workflow whose only reachable step is a `halt_workflow` tool_call, marks the run as `failed`.

---

## 10. Execution flow

```
                          ┌─────────────────┐
                          │   Question      │
                          └────────┬────────┘
                                   ▼
                          ┌─────────────────┐
                          │   Researcher    │  (Sonnet 4.6)
                          └────────┬────────┘
                                   ▼
                          ┌─────────────────┐
                          │ Research Verifier│  (Haiku 4.5)
                          └────────┬────────┘
                                   ▼
                          ┌─────────────────┐
                          │  research-gate  │ rule: passed==true
                          └────┬───────┬────┘
                       passed  │       │  failed
              ┌────────────────┘       └─→ halt-bad-research
              ▼
   ┌──────┬───┴──┬──────┐
   ▼      ▼      ▼      ▼      (BLIND, parallel)
 ┌─S─┐  ┌─Q─┐  ┌─E─┐  ┌─Et─┐
 └─┬─┘  └─┬─┘  └─┬─┘  └─┬──┘
   └──────┴──┬───┴──────┘
            ▼
       ┌─────────┐
       │Critic R0│  (attacks each debater individually)
       └────┬────┘
            ▼
   ┌────────┴──────────┐       Round 1 (sparse topology)
   ▼   ▼   ▼   ▼               each sees: own R0 + opponents' R0 + critic's R0 attack on self
 ┌S1┐ ┌Q1┐ ┌E1┐ ┌Et1┐
 └┬─┘ └┬─┘ └┬─┘ └─┬─┘
  └────┴───┬┴─────┘
           ▼
      ┌─────────┐
      │Critic R1│
      └────┬────┘
           ▼
   ┌───────────────┐
   │ delta-r1 tool │  (deterministic stance vector + active-revision check)
   └───────┬───────┘
           ▼
      ┌─────────┐
      │ stop-r1 │
      └─┬────┬──┘
 continue│    │halt
         ▼    └────────────────────────────────────────┐
   Round 2 (sparse) → Critic R2 → delta-r2 → stop-r2   │
                                        │              │
                                continue│    halt──────┤
                                        ▼              │
                            Round 3 → Critic R3────────┤
                                                       ▼
                                                  ┌────────────┐
                                                  │ final-merge│  (wait_all over actual predecessors)
                                                  └─────┬──────┘
                                                        ▼
                                                  ┌────────────┐
                                                  │ Synthesiser│  (Opus 4.7)
                                                  └─────┬──────┘
                                                        ▼
                                  ┌─────────────┬───────┴────────┬──────────────┐
                                  ▼             ▼                ▼              ▼
                            store-deliverable  store-transcript  store-learning  (artifact + knowledge)
```

---

## 11. Anti-convergence mechanisms (mapping to research §2.4)

How each research-doc finding lands in this implementation:

| Research technique | Implementation |
|---|---|
| Stubborn prompt phrasing (Du et al.) | Each debater prompt uses "Using the opinion of other agents as additional advice" verbatim. |
| Tit-for-tat intensity Level 2 (Liang et al.) | The shared meta-prompt fragment "It's not necessary to fully agree with each other's perspectives" appears in every debater system prompt. |
| Agreement-intensity hyperparameter (Smit et al.) | Workflow context variable `agreement_intensity` (default 0.2). Each debater prompt embeds the value via the input dict. Tunable per run without code change. |
| Devil's advocate role (Smit et al.) | `deliberation.debater_empiricist` is mandated in its system prompt to challenge the mainstream consensus stated in the research packet. |
| Confidence-based persistence rule | Each debater prompt explicitly forbids conceding because "the room disagrees" or because an opponent sounds confident. |
| Misconception refutation + quality pruning (Estornell & Liu) | The critic's `ConvergenceFlag` field explicitly identifies shared hidden assumptions, paraphrase, or mainstream collapse, and the synthesiser is required (by prompt) to use these flags in its `sycophancy_flags` output. |
| HOLD/REFINE/CONCEDE_PARTIAL/CONCEDE_FULL schema | Enforced by `DebaterTurn.decision: Literal[...]` Pydantic field. A `CONCEDE_FULL` requires `decision_justification`; the synthesiser must surface unjustified concessions. |
| Cap on rounds | Workflow defaults to 3, early-stops on stance stability, hard cap at the YAML round-3 graph (no round 4 nodes). |
| Sparse topology (research §5.2) | Implemented by per-step input dicts that name exactly the prior outputs each debater needs. No debater sees the full transcript until the synthesiser. |
| Synthesiser cannot flatten | Pydantic schema: `cruxes` `min_length=2`; `minority_position` required (None allowed only when none survived); `deliberation_vs_mainstream` enum includes `merely_reproduces`. |

---

## 12. Phases (implementation order)

Each phase is a single shippable PR. Tests written before the YAML so the platform enablers are verified independently.

### Phase 1: Platform enablers (no agents yet)
Order matters — §8.5 and §8.6 modify `resolve_template`, which §8.1 and §8.4 then call. Suggested merge order:

1. Promote `_resolve_ref` → public `resolve_ref` in `condition_evaluator.py`.
2. **§8.5** — `resolve_template` raises on structural errors (typo in ref root) instead of leaving the marker.
3. **§8.6** — Standalone refs preserve their resolved value's type (`float`, `list`, `dict`).
4. **§8.1** — `resolve_upstream_context` deep-resolves refs in agent_step input, calling the now-public `resolve_ref`.
5. **§8.2** — `_build_step_objective` JSON-encodes dict/list values.
6. **§8.3** — Default-populate `completed_outcomes` for agent_step from `task_results[-1].output_reference`. **Load-bearing — without this every downstream `@node.X.output.field` ref resolves to None.**
7. **§8.4** — Deep-resolve refs in tool_call `tool_args` for nested dict/list values, calling the now-type-preserving `resolve_template`.
8. **§8.7** — Extend `validate_steps` to verify `@node.X` step-ID refs at workflow load time.

Tests covering each: agent_step ref resolution with nested dicts/lists, fail-loud on unresolved refs, type preservation for standalone refs, default agent output extraction (empty / single / multi-task), tool_args deep resolution, and validate-steps catching typos in tool_args / prompt_template / decision-config.

No new functionality observable to end users from these changes — verify zero regression by running each existing workflow (decision-routing, deep-research, security-code-assessment) end-to-end before declaring Phase 1 complete.

### Phase 2: Schemas + verifier agent
- `modules/backend/schemas/deliberation.py` (full file from §5).
- `deliberation.research_verifier` agent (the smallest, simplest agent — proves the 4-file contract works for the new namespace).
- Catalog YAML, prompt file, Python module, roster entry.
- Unit test: invoke the verifier with a hand-crafted packet, assert it passes; invoke with a tampered packet (vague sources), assert it fails.

### Phase 3: Researcher agent
- `deliberation.researcher` agent. Reuses `search_web`, `fetch_url`, `query_knowledge` tools.
- Test: pass a known contested question, assert the packet has >= 3 sourced claims, >= 2 expert disagreements, named mainstream consensus, and >= 3 under-discussed angles.

### Phase 4: Four debater agents
- All four debaters share `DebaterTurn` output_type and a similar shape; differ only by system prompt and `debater_id` injection.
- Tests: invoke each debater on the same question, assert they produce four genuinely different `load_bearing_claims` (string overlap < 30%).
- Tests: assert each debater's `position` differs from the mainstream consensus in the research packet (string-distance check; weak but useful).

### Phase 5: Critic agent
- `deliberation.critic` agent. Output is `CriticReport` with the `attacks: dict[...]` keyed structure.
- Test: invoke critic on four hand-crafted positions, assert it produces an attack keyed by every debater id and at least one non-`none` `ConvergenceFlag` when the four positions are deliberately similar.

### Phase 6: Synthesiser agent
- `deliberation.synthesiser` agent. Output is `FinalDeliverable`.
- Test: invoke synthesiser on a hand-crafted transcript with one obvious minority position, assert the synthesis preserves it. Invoke on a transcript where all four debaters converged on the mainstream view, assert `deliberation_vs_mainstream == "merely_reproduces"`.

### Phase 7: compute_stance_delta tool
- `modules/backend/tools/compute_stance_delta.py` (full file from §9).
- Unit tests: stable round (delta < threshold, no active revision) returns `should_continue=False`; one debater issued CONCEDE_PARTIAL returns `should_continue=True` regardless of delta.

### Phase 8: Workflow YAML + end-to-end smoke test
- `config/workflow_templates/deliberation.think-tank.workflow.yaml` (full from §7, with round 2 and round 3 expanded per the §7 pattern).
- Workflow seeder picks it up automatically (Plan 75 mechanism).
- **Static assertion** (new test in `tests/integration/test_deliberation_workflow.py`): load the workflow YAML and assert the structure expected by the plan:
  - exactly 34 steps total;
  - exactly 23 `agent_step` nodes (research + verify-research + 4 opens + critic-r0 + 4·3 round debaters + critic-r{1,2,3} + synthesise);
  - exactly 7 `tool_call` nodes (halt-bad-research, delta-r1, delta-r2, store-deliverable-markdown, store-deliverable-json, store-transcript, store-learning);
  - exactly 3 `decision` nodes (research-gate, stop-r1, stop-r2);
  - exactly 1 `merge` node (final-merge);
  - zero `llm_call` and zero `notification` nodes (synthesiser produces Markdown; halt uses tool_call);
  - **Sparse-topology checks** for every round-N debater step (per adversarial-review S2):
    - `critic_attack_on_self` references the matching debater's attack key only (e.g. `round2-systems` references `@node.critic-r1.output.attacks.systems`, not `.quant`/`.empiricist`/`.ethicist`).
    - `opponents_previous` is a 3-key dict whose keys are exactly the three OTHER debater IDs (self excluded, no duplicates, no missing) and whose values reference `round(N-1)-<id>.output` (or `open-<id>.output` for round 1).
    - `own_previous` references the matching debater's previous-round output.
  - **Persistence-shape check:** the workflow has three artifact-storing steps (store-deliverable-markdown / -json / transcript) plus a learning store, and the JSON artifact step references `@node.synthesise.output` as a **standalone ref** (so §8.6 preserves the dict for §9.1 to JSON-encode).
- The static assertion catches: missing rounds, scrambled refs, wrong node_type, copy-paste errors in opponents_previous, missing artifact persistence. Source of truth for counts. Update this test (not the plan prose) if the structure changes during implementation.
- E2E test: trigger the workflow on a real contested question (e.g. "Should we adopt LLM-based code review as the primary review mechanism in 2026?"), assert it produces a `FinalDeliverable` artifact in the mission's artifact store. Manual review of the artifact for v1 — automated quality scoring is a follow-up.

### Phase 9: TUI + frontend trigger
- The deliberation workflow appears in the workflow catalog like any other (no code change needed if Plan 75 catalog is generic, which it is).
- Validate that the TUI's workflow runner can launch it and stream events back. The final deliverable artifact is visible in the artifacts panel.

---

## 13. Caveats and open questions

1. **Diff resolution heuristic for stance delta.** `compute_stance_delta` uses an embedding-cosine distance plus a confidence-delta `max`. This is the simplest reasonable signal and matches what the research doc describes (it explicitly hand-waves about "cosine distance over structured position embeddings"). The first ~10 real runs should be reviewed manually to confirm the threshold (default 0.15) actually corresponds to "stable". Recalibrate after data.

2. **Objective-string size at synthesis step.** With four debaters × four rounds + four critic reports + research packet, the synthesiser's `objective` string will be ~100 KB worst-case. Acceptable for v1 because `ExecutionRecord.objective_statement` is TEXT and Anthropic models accept the full context. **Trigger for redesign:** if the synthesiser step fails with a context-window error, OR the objective JSON-encoding step (§8.2) takes >1s, switch to the artifact-passthrough pattern (pre-synthesis tool_call writes transcript JSON to an artifact, synthesiser receives only the artifact_id and reads via a new `fetch_artifact` tool). Note that the transcript artifact is now persisted regardless (B2 fix), so the read side is already there — only a `fetch_artifact` tool is needed to fully decouple.

3. **PydanticAI structured output limit.** `FinalDeliverable` has ~10 fields and `cruxes` is a list of records. Total schema size is comfortably under the 5-`$def` / 2 KB threshold from P17. If field count grows in v2 (e.g. per-debater steelmen, evidence catalogues), refactor to tool-calls per P17.

4. **No agent self-correction loop.** v1 has no `max_refinement_rounds > 1` anywhere — every step runs once. If a debater fails schema validation, the existing PydanticAI `output_retries=3` handles it. If the critic emits a malformed report, the workflow will fail loud. Acceptable for v1; if production runs show >5% step-level failures, revisit.

5. **No human gate.** v1 runs to completion without human approval. A future enhancement could insert a `human_input` node after the research packet (review before debate begins) or after the synthesis (challenge the conclusion before persisting). Out of scope for v1 because the user explicitly accepts long autonomous runs.

6. **Roster size fixed at 4.** Research §3 notes the 5th/6th debater earns its keep only on genuinely novel-domain questions. v1 ships with four. If a future user wants a fifth (e.g. an explicit theological or geopolitical lens), the fix is two files: a new YAML + prompt and a workflow variant that includes a 5th branch per round. Documented but not scheduled.

7. **The Director does not auto-trigger this.** v1 ships as an on-demand workflow only. The Director's `run_workflow` tool could match deliberation questions and dispatch automatically; tuning the trigger heuristics to avoid over-triggering is its own piece of work. Future plan.

8. **Stance vector is a stopping signal, not a quality measure.** Two debaters could land on the same numerical answer via wildly different reasoning, and the embedding distance would call them "similar". The `confidence_delta` `max` partially mitigates. The critic's `ConvergenceFlag` is the proper mechanism for catching shared-hidden-assumption convergence; the stance delta only answers "is it worth running another round". The critic and synthesiser system prompts (§6) explicitly state this so neither leans on the stance delta as a quality signal.

9. **Anthropic rate limits.** With 4 debaters × 3 rounds + 3 critic rounds = 15 Opus 4.7 calls, plus researcher, verifier, synthesiser = 18 calls per run. At Anthropic tier-2 limits this is fine; at lower tiers, the wave engine's existing parallelism will hit the per-minute cap. Existing `app_config.workflows.max_concurrent_missions` throttling applies. Real-world latency in §13 of the research doc says 90-180s; expect 5-30 minutes under default Opus settings and rate-limit-aware retry behaviour. Acceptable per the user steer.

---

## 14. File manifest

### New files

| File | Purpose | Approx LOC |
|---|---|---|
| `modules/backend/schemas/deliberation.py` | All Pydantic models (§5) | 220 |
| `modules/backend/agents/deliberation/__init__.py` | Minimal init | 5 |
| `modules/backend/agents/deliberation/researcher/__init__.py` | Re-export | 1 |
| `modules/backend/agents/deliberation/researcher/agent.py` | `create_agent()` for researcher | 50 |
| `modules/backend/agents/deliberation/research_verifier/agent.py` | verifier agent | 50 |
| `modules/backend/agents/deliberation/debater_systems/agent.py` | Systems debater | 50 |
| `modules/backend/agents/deliberation/debater_quant/agent.py` | Quant debater | 50 |
| `modules/backend/agents/deliberation/debater_empiricist/agent.py` | Empiricist debater | 50 |
| `modules/backend/agents/deliberation/debater_ethicist/agent.py` | Ethicist debater | 50 |
| `modules/backend/agents/deliberation/critic/agent.py` | Critic agent | 50 |
| `modules/backend/agents/deliberation/synthesiser/agent.py` | Synthesiser agent | 50 |
| `modules/backend/tools/compute_stance_delta.py` | Stance delta tool (§9) | 90 |
| `config/agents/deliberation/researcher/agent.yaml` | catalog config | 30 |
| `config/agents/deliberation/research_verifier/agent.yaml` | | 25 |
| `config/agents/deliberation/debater_systems/agent.yaml` | | 25 |
| `config/agents/deliberation/debater_quant/agent.yaml` | | 25 |
| `config/agents/deliberation/debater_empiricist/agent.yaml` | | 25 |
| `config/agents/deliberation/debater_ethicist/agent.yaml` | | 25 |
| `config/agents/deliberation/critic/agent.yaml` | | 25 |
| `config/agents/deliberation/synthesiser/agent.yaml` | | 25 |
| `config/prompts/agents/deliberation/researcher/system.md` | from research §4.1 | 60 |
| `config/prompts/agents/deliberation/research_verifier/system.md` | new (§6) | 50 |
| `config/prompts/agents/deliberation/debater_systems/system.md` | from §4.2 | 70 |
| `config/prompts/agents/deliberation/debater_quant/system.md` | from §4.3 | 70 |
| `config/prompts/agents/deliberation/debater_empiricist/system.md` | from §4.4 | 75 |
| `config/prompts/agents/deliberation/debater_ethicist/system.md` | from §4.5 | 70 |
| `config/prompts/agents/deliberation/critic/system.md` | from §4.6 | 60 |
| `config/prompts/agents/deliberation/synthesiser/system.md` | from §4.7 | 80 |
| `config/workflow_templates/deliberation.think-tank.workflow.yaml` | The workflow (§7) — **34 nodes** (23 agent_step + 7 tool_call + 3 decision + 1 merge) | 780 |
| `modules/backend/tools/halt_workflow.py` | New tool (§9.2) — raises RuntimeError so the run is marked failed | 50 |
| `tests/unit/backend/agents/test_deliberation/test_schemas.py` | schema tests | 150 |
| `tests/unit/backend/agents/test_deliberation/test_research_verifier.py` | verifier tests | 80 |
| `tests/unit/backend/agents/test_deliberation/test_debaters.py` | diversity test | 120 |
| `tests/unit/backend/agents/test_deliberation/test_critic.py` | critic test | 80 |
| `tests/unit/backend/agents/test_deliberation/test_synthesiser.py` | synthesiser test | 120 |
| `tests/unit/backend/tools/test_compute_stance_delta.py` | stance-delta unit tests | 100 |
| `tests/unit/backend/tools/test_halt_workflow.py` | halt-workflow tool tests (raises RuntimeError; marks run failed) | 60 |
| `tests/unit/backend/tools/test_store_artifact.py` | store_artifact extension tests (dict + content_type=json → JSON-encoded; dict + content_type=markdown → ValueError) | 80 |
| `tests/integration/test_deliberation_workflow.py` | end-to-end smoke | 150 |

### Modified files

| File | Change |
|---|---|
| [modules/backend/services/condition_evaluator.py:283](modules/backend/services/condition_evaluator.py#L283) | Promote `_resolve_ref` → public `resolve_ref`; export `ConditionEvaluationError` |
| [modules/backend/services/condition_evaluator.py:419](modules/backend/services/condition_evaluator.py#L419) | `resolve_template` fails loud on structural errors (§8.5); preserves types for standalone refs (§8.6) |
| [modules/backend/services/workflow.py:289](modules/backend/services/workflow.py#L289) | Extend `resolve_upstream_context` to deep-resolve `@node.X.output.field` refs in dict/list inputs (§8.1) |
| [modules/backend/services/workflow_run_waves.py:1291](modules/backend/services/workflow_run_waves.py#L1291) | Extend `_build_step_objective` to JSON-encode dict/list values (§8.2) |
| [modules/backend/services/workflow_run_waves.py:534](modules/backend/services/workflow_run_waves.py#L534) | Default-populate `completed_outcomes` for agent_step from `task_results[-1].output_reference` (§8.3) — load-bearing |
| [modules/backend/services/workflow_run_waves.py:840](modules/backend/services/workflow_run_waves.py#L840) | Deep-resolve refs in tool_call `tool_args` for nested dict/list values (§8.4) |
| [modules/backend/schemas/workflow.py:474](modules/backend/schemas/workflow.py#L474) | Extend `validate_steps` to validate `@node.X` refs in `step.input`, `tool_args`, `prompt_template`, decision/condition/notification configs (§8.7) |
| [modules/backend/tools/store_artifact.py](modules/backend/tools/store_artifact.py) | Accept `content: str \| dict \| list`; JSON-encode non-string content when `content_type=json` (§9.1, B1 fix) |
| [modules/backend/tools/registry.py](modules/backend/tools/registry.py) | Picks up `compute_stance_delta` and `halt_workflow` automatically — no manual registration needed (auto-discovery already exists) |
| [config/agents/mission_control.yaml](config/agents/mission_control.yaml) | Add the 8 new agents to the default roster |
| [tests/unit/backend/services/test_workflow.py](tests/unit/backend/services/test_workflow.py) | New tests for the extended `resolve_upstream_context` |
| [tests/unit/backend/services/test_workflow_run_waves.py](tests/unit/backend/services/test_workflow_run_waves.py) | New tests for §8.2 (objective builder), §8.3 (default agent output), §8.4 (tool_args deep resolve) |
| [tests/unit/backend/services/test_condition_evaluator.py](tests/unit/backend/services/test_condition_evaluator.py) | New tests for §8.5 (fail-loud on syntax errors), §8.6 (standalone-ref type preservation) |
| [tests/unit/backend/schemas/test_workflow_schema.py](tests/unit/backend/schemas/test_workflow_schema.py) | New tests for §8.7 (load-time `@node.X` ref validation) |

### Files explicitly NOT modified

- `modules/backend/agents/mission_control/**` — no dispatch changes required.
- `modules/backend/agents/mission/director/agent.py` — Director does not auto-trigger v1.
- `modules/backend/temporal/**` — runs entirely via the existing wave engine.
- `modules/backend/agents/mission_control/verification.py` — verification pipeline applies to debater outputs automatically; no changes needed.

---

## 15. Acceptance criteria

The plan is done when:

1. **All eight agents discoverable.** `GET /catalog/agents` lists the eight new `deliberation.*` entries; each has a valid YAML, prompt, and `create_agent()` callable from the registry.
2. **Workflow visible.** `GET /workflows` lists `deliberation.think-tank.workflow` v1. The TUI workflow catalog shows it.
3. **Platform enablers tested.** `@node.X.output.field` refs in step input resolve correctly, including nested dicts and lists. Unresolved refs fail loud with a clear error.
4. **`compute_stance_delta` tested.** Round-on-round stable rounds return `should_continue=False`; rounds with any active revision return `True` regardless of delta.
5. **End-to-end smoke run.** Triggering the workflow on a real contested question runs to completion and produces three artifacts in the mission's artifact store:
   - `deliberation_deliverable` (Markdown) with the human-readable report;
   - `deliberation_deliverable` (JSON) — the schema-validated `FinalDeliverable` with `>=2` cruxes, populated `deliberation_vs_mainstream`, populated `minority_position` (or explicit null), and matching `report_markdown` + `recommendation_markdown` strings;
   - `deliberation_transcript` (JSON) — the full transcript including research packet, every round's debater outputs (with null for skipped rounds), every critic report, and both stance-delta records.
6. **Anti-flattening test.** Triggering the workflow on a question where all four debaters genuinely agree (e.g. "Is 2 + 2 = 4?") produces a `FinalDeliverable` (in BOTH the JSON artifact and the Markdown) with `deliberation_vs_mainstream == "merely_reproduces"`. The Markdown rendering and the structured JSON must agree on this field — they come from the same synthesiser call.
7. **Sparse topology preserved.** The Phase 8 static assertion (§12) verifies every round-N debater's `own_previous`, `opponents_previous`, and `critic_attack_on_self` references are correctly wired.
8. **No silent failures.** When the research-packet verifier fails, the workflow run is marked `failed` (not `completed`) via the `halt_workflow` tool, AND an SSE notification is emitted with the verifier's `issues` list.
9. **No regressions.** PQI score for the project does not drop on the `Modularity` or `Robustness` dimensions. The new agent files all stay under 100 lines (P14, Code Map quality threshold). No new `except: pass`. All existing workflows (decision-routing, deep-research, security-code-assessment) pass their existing tests after Phase 1.
10. **Programmatic deliverable query works.** `GET /missions/{id}/artifacts?type=deliberation_deliverable` returns the JSON artifact and a consumer can read `confidence`, `cruxes[i].crux_question`, `minority_position`, etc. without re-parsing Markdown.

---

## 16. Out of scope (explicit non-goals for v1)

- Director auto-triggering of deliberation workflows.
- Human-in-the-loop gates (packet review, post-synthesis challenge).
- 5- or 6-debater variants.
- Adversarial-quality scoring of the deliverable (is the synthesis good?). v1 ships and learns from real use.
- Cross-mission learning over deliberation cruxes (Plan 73 knowledge layer can store them; using them to seed future deliberations is a follow-up).
- A bespoke TUI panel for live debate viewing. v1 reuses the existing workflow run / artifact viewer.
- Internationalisation of prompts (UK English only for v1).
- Multi-language deliberation (UK English only).
