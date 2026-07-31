# Plan 80: Think Tank — Advocate-Judge Architecture

## Status: DISCARDED 2026-05-24

This plan is no longer the path forward. Rationale below; the rest of the
document is preserved as a decision record.

### Why discarded

Plan 79's validation failure mode was diagnosed in this plan as "one
researcher producing five things in one shot for a contested question
under a strict verifier is unsolvable." The fix proposed here was
structural — Advocate-Judge across N candidates with information
asymmetry, single-round attacks, judge synthesis.

That diagnosis of the *researcher* step is correct. The proposed fix
for the *whole deliberation topology* is more than the data demands.
The empirical evidence in §1 (Khan et al. 76% vs 48% on QuALITY,
Hu & Collier on persona prompting, Du et al. on diminishing returns)
supports the debate-architecture changes, but **none of those papers
test against v1-with-decomposed-research as a baseline.** Plan 79's
shelving validation also ran against the broken researcher. We have
no data on whether v1 with the research step fixed beats the
single-call baseline.

The disciplined sequence:

1. Decompose v1's `deliberation.researcher` into the existing
   `research.deep-research-pipeline.workflow` (sub-workflow call).
   Half-day change.
2. Run the same A/B validation Plan 80 prescribes (§Phase 8) —
   v1-with-decomposed-research vs single-call baseline.
3. If v1-fixed beats baseline → ship v1-fixed. Plan 80's
   debate-restructuring stays as "interesting future research."
4. If v1-fixed still loses → re-open Plan 80 with empirical
   justification.

Discard cost vs build cost:
- Plan 80 v3 build: ~5 days + new schemas + multi-provider + ~$50-100
  validation budget.
- v1 research-decomposition fix: ~1 day, no new schemas, validates
  with existing pipeline.

The Plan 80 decision gate (§Phase 9 — "mechanical, not aspirational")
applies recursively: if we can't prove v3 is needed, we don't ship v3.

### What gets preserved from this branch

The infrastructure built on `feature/80-advocate-judge` is **kept** —
it was platform work, not Advocate-Judge-specific:

- `manual` gate mode (Plan 80g)
- Unified task lifecycle (Plan 80h)
- `task_approval` module
- `mc plan` / `mc gate` / `mc runs` CLI subgroups
- Async workflow run endpoint for interactive modes
- Workflow status truth-write fix
- Gate mode `off` collapsed into `autonomous`

What gets discarded:
- `modules/backend/agents/mission_control/dispatch/advocate_judge_loop.py`
- `modules/backend/schemas/deliberation_advocate_judge.py`
- `modules/backend/agents/deliberation/advocate_judge_framer/`
- `modules/backend/agents/deliberation/advocate_judge_framings_validator/`
- `config/agents/deliberation/advocate_judge_*/agent.yaml`
- `config/prompts/agents/deliberation/advocate_judge_*/system.md`
- Tests under `tests/unit/backend/agents/test_advocate_judge/`

These are dead code (never wired into any dispatch path or workflow
YAML) and should be removed in a cleanup commit.

---

## Original plan body (preserved below for context)

## Status (original): Draft v2 (2026-05-24 — multi-provider heterogeneity added; workflow takes canonical name from day 1)

**Branch:** `feature/80-advocate-judge` (to be cut off `main`; do not extend `feature/79-think-tank-deliberation`)
**Priority:** Medium-High (same user need as Plan 79; different architecture)
**Reference research:** [docs/98-research/032-Think Tank-A Multi-Agent Deliberation System for Contested Questions.md](../09-research/032-Think%20Tank-A%20Multi-Agent%20Deliberation%20System%20for%20Contested%20Questions.md)
**Reference validation:** [docs/98-research/033-Think-Tank-v2-Validation-Findings.md](../09-research/033-Think-Tank-v2-Validation-Findings.md)
**Supersedes:** Plan 79 (4-debater multi-round deliberation). Plan 79 is shelved per validation findings; v2 code in `feature/79-think-tank-deliberation` is reference only.

**Dependencies (unchanged from Plan 79):**
- Plan 45 (Rich Workflow Model)
- Plan 72 (Task First-Class)
- Plan 75 (Composable Workflows with Decision Nodes — used only minimally; mostly single-step)
- Plan 40 (Deep Research) — pattern reference for `type: <name>_loop` Python executors

**User intent (unchanged from Plan 79):** quality and depth over speed and cost. Defaults to Opus 4.6 for advocate/judge work; accepts multi-hour wall-clock per run. Cost is not the primary design constraint.

---

## 1. Why this plan exists

Plan 79's 7-agent architecture (4 persona debaters + critic + researcher + verifier over multiple rounds) failed validation on 2026-05-24:

- Single-call baseline (Opus 4.6, extended thinking, web search, same `FinalDeliverable` schema) produced clean deliverables on all 3 contested test questions in ~5 min each.
- Plan 79 v2 on the same setup failed on the first question with the *exact failure mode the original brief already named*: researcher pinched between fabricating (the verifier kills it) and refusing (the loop crashes). The model chose to refuse after 5 successful `search_web` calls, and PydanticAI couldn't parse the refusal as `ResearchPacket`.

The validation findings doc establishes this failure is **architectural, not a prompt bug**: one researcher producing {sourced claims, expert disagreements, mainstream consensus, under-discussed angles, base rates} for a contested question under a strict verifier is an unsolvable task structure. Five distinct cognitive tasks, one prompt, fear-driven framing — the model will either fabricate, refuse, or both depending on which knob you turn.

**Advocate-Judge re-scopes the research task by making it adversarial-per-side.** Each candidate answer gets a dedicated researcher whose narrow brief is *"find the strongest evidence that answer X is correct."* That brief is *searchable* — the model knows what it's looking for and stops when it has it. The balanced-packet construction is moved one layer up (into a deliberate framing step) and one layer down (into the judge, who reads all sides' evidence at once).

Information asymmetry between sides is the structural anti-convergence mechanism the empirical literature endorses (Khan et al. ICML 2024 Best Paper: 76% vs 48% on QuALITY with adversarial debate-with-judge). Persona diversity — which Plan 79 leaned on heavily — empirically changes style more than reasoning (Hu & Collier ACL 2024; Wharton "Playing Pretend"). Advocate-Judge keeps the mechanism the literature endorses and drops the mechanism the literature doesn't.

## 2. Architectural decisions (committed for v1)

The big ones, with one-line justification:

1. **5 agent roles, not 7.** Framer, framings validator, per-side researcher (N copies), per-side advocate (N copies), judge. No persona debaters. No standalone verifier (the judge fills that role with full information).
2. **N = 3 or 4 candidates per question** (not fixed at 4). The framer chooses based on the question's live answer space, capped at the framings validator's discretion. Three is the empirical sweet spot from Du et al.'s diminishing-returns curve.
3. **Single round of advocacy + single round of bilateral attacks.** No multi-round debate. "Talk Isn't Always Cheap" (2025) and "Peacemaker or Troublemaker" (2025) both show sycophancy intensifies past round 1–2. Cap at one substantive exchange.
4. **No stance-delta early stopping.** Stance-delta on Pydantic structured output is a category error (embedding the prose form, not the belief); v2's own `StanceDelta` docstring acknowledges this. Fixed cost is simpler and avoids false stops.
5. **Asymmetric research is THE anti-convergence mechanism.** Each side has dedicated evidence its opponents don't see at research time. Cannot be sycophant-converged because the priors are structurally different.
6. **One Python executor, one wave-engine step** (`type: advocate_judge_loop`). Same pattern as v2's `deliberation_loop` — bypasses per-step Planning Agent overhead. Per-phase narrative events emit for Kanban visibility.
7. **Keep `FinalDeliverable` schema from Plan 79 unchanged.** It's the anti-flattening machinery that empirically works (`cruxes ≥ 2`, `minority_position` required-or-null, `merely_reproduces` enum, `sycophancy_flags`). Survives the rewrite.
8. **Judge is Opus 4.6 with `reasoning_effort=high`.** Extended thinking matters most at the synthesis step. Advocates and researchers can also be Opus 4.6 but with normal effort.
9. **No CLI/API in the loop.** v2's CLI invocation timed out at 5 min (httpx ReadTimeout) because the synchronous POST endpoint blocks for the run's full duration. Use `scripts/think_tank_advocate_judge.py` for ad-hoc runs and the wave-engine workflow for mission-attached runs. Both call the same executor.
10. **Multi-provider model heterogeneity is the recommended default for the advocate roles.** Each per-side researcher + advocate pair SHOULD use a different model family where available (Claude / GPT / Gemini), because different families have different training data, different RLHF, different priors. This adds *structural reasoning diversity* on top of structural information asymmetry — exactly the mechanism the persona-prompting literature (Hu & Collier; Wharton "Playing Pretend") shows is missing from same-model-different-prompt setups. The judge stays single-model (otherwise you need a meta-judge). Fallback: if a provider isn't locally wired, single-family is acceptable — the architecture's structural information-asymmetry guarantees still hold. See §5.1.
11. **Workflow takes the canonical `deliberation.think-tank.workflow` name from day 1.** No "advocate-judge.workflow" dev-name interim. v2's YAML is moved to `deliberation.think-tank.v2.workflow.yaml` with `enabled: false` at the start of Phase 6, mirroring how v1 was preserved as `deliberation.think-tank.v1.workflow.yaml`. The architecture name lives in the code identifiers (`advocate_judge_loop.py`, etc.); the brand name lives in the workflow slot. They're different layers.

## 3. What we reuse from Plan 79 (verbatim)

To pre-empt the "rewrite from scratch" temptation — substantial pieces survive:

| Plan 79 file | Plan 80 use | Why kept |
|---|---|---|
| `modules/backend/schemas/deliberation.py` — `FinalDeliverable`, `CruxRecord`, `MinorityPosition`, `ForwardClaim`, `SourcedClaim`, `LoadBearingClaim` | Imported unchanged | Schema-enforced anti-flattening is the load-bearing protection; works as designed; the JSON-artifact persistence ensures the protection survives into storage. |
| `modules/backend/tools/registry.py` and `search_web`/`fetch_url`/`query_knowledge` tool modules | Used unchanged for per-side researchers | Same tools as the baseline used; works reliably. |
| `modules/backend/core/copilot_model.py` (`CopilotModel`, `_ToolBridge`) | Used unchanged | Bridge to Copilot SDK works; structured-output via `final_result` tool-mode works. |
| `modules/backend/agents/mission_control/helpers/agent_executor.py` (`_make_agent_executor`) | Used unchanged | The executor closure / registry lookup pattern works in v2; failure was in the agent prompts, not the executor wiring. |
| `modules/backend/agents/mission_control/gate.py` (`NoOpGate`, `GateReviewer`) | Used unchanged | Sufficient for autonomous runs. |
| `modules/backend/agents/mission_control/models.py` (`NoOpEventBus`, `EventBusProtocol`, `ExecuteAgentFn`) | Used unchanged | Protocols are good. |
| `modules/backend/tools/store_artifact.py`, `store_learning.py` | Used unchanged | Persistence works. |
| `scripts/think_tank_anonymise.py` | Used unchanged | Will be reused to A/B Advocate-Judge outputs vs the baseline outputs already in `var/validation/baseline/`. |

## 4. What we discard from Plan 79 (explicit non-goals)

| Discarded | Why |
|---|---|
| 4 persona debaters (Systems Mapper / Reductionist Quant / Adversarial Empiricist / Distributional Ethicist) and their YAMLs | Persona prompting changes style, not reasoning (Hu & Collier ACL 2024). Plan 79's bet that "reasoning method + value frame" beats "occupational persona" was reasoned but unbenchmarked (Plan 79 §9 caveat 1 admits this); the validation failure suggests the bet did not pay off. |
| Single broad-scope researcher | Root cause of the v2 failure. Replaced by per-side adversarial researchers with narrow scope. |
| Standalone research_verifier | Folded into the judge. The judge has all sides' evidence and is empowered to call a candidate's case "weak/uncited" in its `FinalDeliverable.biggest_things_that_could_be_wrong` list. |
| Critic-per-round agent | Subsumed by the bilateral-attacks phase. Every advocate attacks every other advocate's load-bearing claim. |
| Multi-round debate with sparse topology | Empirical sycophancy risk past round 1–2 outweighs marginal gain. One advocacy round + one attacks round. |
| Stance-delta early stopping (`compute_stance_delta` tool, `StanceDelta` schema) | Category error per v2's own docstring. Delete; fixed cost. |
| Workflow templates `deliberation.think-tank.workflow.yaml` (v2 single-step) — v1 is already archived at `…v1.workflow.yaml` | v2 YAML moves to `…v2.workflow.yaml` with `enabled: false` at the start of Phase 6, mirroring the v1 archive. The canonical `deliberation.think-tank.workflow.yaml` path is reused for the new architecture (§10). |
| `deliberation_loop.py` executor | Replaced by new `advocate_judge_loop.py` executor. v2 is reference. |
| Per-round `research_requests` from debater turns dispatched between rounds | No multi-round; no follow-up research between rounds. Per-side researcher is sized to do its job in one pass. |

## 5. Agent roster

Seven roles in concept but **5 agent YAMLs** (researcher and advocate are role-shared across the N candidates; N = 3 or 4):

| Role | YAML | Default model | Reasoning effort | Tools | Why |
|---|---|---|---|---|---|
| Framer | `deliberation.advocate_judge_framer.agent` | copilot:claude-opus-4.6 | medium | search_web, fetch_url | Knowledge of the answer space matters; one shallow search for "schools of thought on X" is enough. |
| Framings validator | `deliberation.advocate_judge_framings_validator.agent` | copilot:gpt-5.5 (different family from framer) | medium | (none) | Pure reasoning over the framer's output. P13 separate-agent rule. Different family from framer so the audit catches family-specific priors. |
| Per-side researcher | `deliberation.advocate_judge_side_researcher.agent` | **per-side override** (see §5.1) | medium | search_web, fetch_url, query_knowledge | Narrow brief: find the strongest evidence for ONE candidate. Different family per side surfaces different sources. |
| Per-side advocate | `deliberation.advocate_judge_advocate.agent` | **per-side override** (see §5.1) | high | (none) | Writes the strongest case from its packet; structured. Different family per side prevents shared-model convergence. |
| Judge | `deliberation.advocate_judge_judge.agent` | copilot:claude-opus-4.7 (or anthropic:claude-opus-4-7 with extended thinking) | high | (none) | Synthesis step where reasoning quality matters most. One model only (otherwise need a meta-judge). |

Per-side researcher and per-side advocate are invoked N times in parallel by the executor; the YAMLs themselves are not duplicated. The candidate label and the **per-side model assignment** are passed via `instructions`/`inputs`, not encoded in the agent identity.

The **attacks** phase reuses the per-side advocate YAML with a different instruction (Phase 4 in §9). Attempted simplification — splitting "advocate" and "attacker" into separate YAMLs — adds files without changing behaviour, because the model's task is the same shape: read its own assignment, write structured output. Keep as one YAML, two instruction templates.

### 5.1 Per-side model assignment

**Currently wired providers** (verified in [modules/backend/core/model_builder.py](../../modules/backend/core/model_builder.py)): `anthropic:`, `openai:`, `copilot:`. The Copilot SDK covers both Claude and GPT under one credential. **Google / Gemini is NOT wired** — see Phase 0 below for the small add.

For N=3 with all three families wired (post-Phase 0):

| Side index | Researcher model | Advocate model (same model) |
|---|---|---|
| 0 | `copilot:claude-opus-4.6` | `copilot:claude-opus-4.6` |
| 1 | `copilot:gpt-5.5` | `copilot:gpt-5.5` |
| 2 | `google:gemini-2.5-pro` | `google:gemini-2.5-pro` |

For N=4, add a 4th side using a 2nd-generation rotation (e.g. `copilot:claude-sonnet-4.6` for side 3) — still better than re-using a family already in use.

If Phase 0 is skipped (Gemini not wired), the rotation falls back to:

| Side index | Researcher / Advocate model |
|---|---|
| 0 | `copilot:claude-opus-4.6` |
| 1 | `copilot:gpt-5.5` |
| 2 | `copilot:claude-sonnet-4.6` (repeats Claude family) — logs a `sycophancy_flags` entry noting reduced heterogeneity |

Implementation: `AdvocateJudgeConfig` carries a `side_models: list[str] | None` field. If None (default), the executor uses the rotation appropriate to the currently-wired providers. If the user passes an explicit `side_models` list, it overrides — but the executor still validates each model string via `_build_model` at start, failing loud on unknown provider prefixes rather than mid-run.

The judge's model is fixed per `AdvocateJudgeConfig.judge_model` (default `copilot:claude-opus-4.7`). Per-side researcher and advocate models are bound at executor dispatch via the `model` parameter to the per-call agent factory; `_build_model` handles provider routing.

Provider availability check happens at executor start (Phase 1 in §12) so misconfiguration trips immediately, not 20 minutes into a run.

## 6. Schemas

All in `modules/backend/schemas/deliberation_advocate_judge.py`. Reuse `SourcedClaim`, `LoadBearingClaim`, `FinalDeliverable` from `modules/backend/schemas/deliberation.py`.

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

# Phase 1: framing
class CandidateAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(..., min_length=1, max_length=80,
        description="Short kebab-case identifier, e.g. 'institutional-friction'.")
    statement: str = Field(..., min_length=1, max_length=400,
        description="One-sentence claim the candidate represents.")
    rationale_for_inclusion: str = Field(..., min_length=1, max_length=600,
        description="Who actually holds this view and why it's a live answer (not a strawman).")

class CandidateSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidates: list[CandidateAnswer] = Field(..., min_length=3, max_length=5)
    mainstream_consensus: str = Field(..., min_length=1, max_length=600,
        description="The conventional answer (named once, used by the judge for the merely_reproduces audit).")

class FramingValidation(BaseModel):
    """Validator's response. Either approves the set or replaces it."""
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["approved", "revised"]
    revised_set: CandidateSet | None = Field(None,
        description="Present iff verdict == 'revised'. Final set to use.")
    rationale: str = Field(..., min_length=1, max_length=1000,
        description="If approved: what survived audit. If revised: what was missing and what changed.")

# Phase 2: asymmetric research
class SidePacket(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_label: str
    sourced_claims: list[SourcedClaim] = Field(..., min_length=3, max_length=10)
    strongest_supporting_argument: str = Field(..., min_length=1, max_length=2000)
    weakest_link: str = Field(..., min_length=1, max_length=1000,
        description="The honest naming of this packet's weakest claim. The judge uses this.")

# Phase 3: blind advocate cases
class AdvocateCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_label: str
    case_statement: str = Field(..., min_length=1, max_length=2000)
    load_bearing_claims: list[LoadBearingClaim] = Field(..., min_length=2, max_length=3)
    confidence: float = Field(ge=0.0, le=1.0,
        description="Honest confidence AFTER seeing own evidence packet.")

# Phase 4: bilateral attacks
class Attack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_label: str
    attacked_assumption: str = Field(..., min_length=1, max_length=500)
    attack_argument: str = Field(..., min_length=1, max_length=1500)
    cited_evidence_urls: list[str] = Field(..., min_length=1,
        description="Must be URLs that appear in some side's SidePacket.sourced_claims.")
    steelman_of_attack: str = Field(..., min_length=1, max_length=1000)

class AttacksByAdvocate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_label: str
    attacks: list[Attack] = Field(...,
        description="One attack per other candidate. Length = N - 1.")
```

The judge consumes the union and produces `FinalDeliverable` (reused unchanged from `modules/backend/schemas/deliberation.py`).

## 7. System prompts

Stored in `config/prompts/agents/deliberation/advocate_judge_<role>/system.md`. Sketches here; final wording during implementation Phase 2.

### 7.1 Framer

```
You are decomposing a contested question into the LIVE ANSWER SPACE.

Your job is to identify 3 to 5 candidate answers that competent observers
actually hold. Not 3 to 5 phrasings of the same answer — 3 to 5 different
answers that could each be right.

For each candidate, produce:
- label: short kebab-case identifier (e.g. "institutional-friction").
- statement: the answer in one sentence, concrete enough that it could
  later be wrong.
- rationale_for_inclusion: who holds this view in the real world (a named
  school of thought, an institution, an analyst), and why it is not a
  strawman.

Also produce: mainstream_consensus — the conventional answer a competent
non-specialist would give today. This is the prior the judge will audit
the deliberation against.

Avoid:
- Three variants of the mainstream view dressed up as alternatives.
- A "balanced" set that includes a token contrarian. Every candidate must
  be defensible enough that a strong advocate could argue it.
- More than 5 candidates. Marginal diversity collapses past 4 in the
  empirical literature.

You have search_web available. Use it lightly — one or two searches for
"schools of thought on X", not a full research pass. The deep research
happens in the next phase, one researcher per candidate.

Output format: CandidateSet schema.
```

### 7.2 Framings validator

```
You are auditing a CandidateSet for hidden bias. You did not generate it.
You do not love it.

Specifically check:
1. Are all candidates pulling in the same direction (all techno-optimist,
   all regulatory-pessimist, etc.)? If yes, the framer missed at least
   one school.
2. Is there a discipline missing that the question demands (e.g. the
   question is about an EU regulation but no candidate represents the
   legal-precedent perspective)?
3. Is any candidate a strawman — a position no real observer holds?
4. Is the mainstream_consensus an honest naming of the conventional view,
   or a softened version?

If everything passes, output verdict=approved with rationale stating what
survived audit.

If something fails, output verdict=revised with a revised_set that fixes
the problem. Specifically: add the missing school, replace the strawman,
sharpen the mainstream_consensus. You may not just complain; you must
produce the final set.

Output format: FramingValidation schema.
```

### 7.3 Per-side researcher

```
You are doing STEELMAN RESEARCH for ONE candidate answer.

Candidate label: {candidate_label}
Candidate statement: {candidate_statement}
Candidate rationale: {candidate_rationale}

Your job is to find the STRONGEST evidence that this candidate is
correct. You are NOT balanced. You are an advocate. The competition
will provide the counter-evidence.

Use search_web and fetch_url. Every claim you include must have a real
URL retrieved via the tools. If you cannot find supporting evidence for
a claim you wanted to make, drop it — but say so honestly in the
weakest_link field at the end of the packet.

You will produce 3 to 10 sourced_claims. Each must include:
- claim: the specific factual statement
- source: a URL you actually retrieved (or paper title + arXiv ID you
  retrieved)
- confidence: HIGH / MEDIUM / LOW based on source quality and
  independence.

Plus:
- strongest_supporting_argument: the case for this candidate in 2 to 4
  sentences, citing your strongest claims.
- weakest_link: which of your own claims is the weakest, and why. This
  honesty is mechanical — the judge uses it. Saying "all my evidence is
  strong" is a refusal to do the job.

You do not need to balance. You do not need to caveat. Do not say "but
opponents would argue". That's the next phase's job.

Output format: SidePacket schema.
```

### 7.4 Per-side advocate (blind case)

```
You are advocating for ONE candidate answer.

Candidate label: {candidate_label}
Candidate statement: {candidate_statement}

You see ONLY your own research packet. You do not see other candidates'
packets or cases. This is deliberate — the blind opening prevents
first-mover effects.

Write the strongest possible case for your candidate in case_statement
(2 to 5 sentences). Identify your 2 to 3 load_bearing_claims — the
claims that, if false, would break your case.

Confidence: how confident are you AFTER reading your evidence packet?
Be honest. If your packet's strongest evidence is genuinely weak (and
the researcher told you so in weakest_link), reflect that. A confidence
of 0.4 with a strong case is more useful than 0.9 with a smooth one.

Output format: AdvocateCase schema.
```

### 7.5 Per-side advocate (attacks)

```
You are now attacking the OTHER candidates' cases. You see:
- Your own original case and packet (for reference).
- Every other advocate's case and load-bearing claims.
- The UNION of all research packets (so you have access to opposing
  evidence the original advocate didn't see at writing time).

For each other candidate, produce one Attack:
- attacked_assumption: which load-bearing claim of theirs you attack
  (quote it).
- attack_argument: the strongest version of the attack. Cite specific
  evidence by URL from the available packets.
- cited_evidence_urls: the URLs you cite. Must appear in some side's
  packet — fabricated URLs are an error.
- steelman_of_attack: anticipate the strongest reply the target advocate
  could make to this attack, and address it.

Do NOT attack style or rhetoric. Do NOT attack the candidate's label or
framing. Attack the load-bearing assumption.

Output format: AttacksByAdvocate schema.
```

### 7.6 Judge

```
You are the Judge. You did not advocate. You did not research.

You see:
- The original question.
- The CandidateSet (including mainstream_consensus).
- Every advocate's case with confidence.
- Every advocate's attacks on every other candidate.
- The union of all SidePackets (research evidence).

Your job: produce a FinalDeliverable.

Procedure (use your extended thinking budget):

1. For each candidate, identify which load-bearing claims survived the
   strongest attack. A claim "survives" if the attacker's evidence did
   not actually refute it (e.g. the attacker cited a non-comparable
   reference class, or the attack targeted a claim that wasn't actually
   load-bearing).

2. The committed_answer is the candidate whose case survived attack
   most intact — OR a synthesis explicitly naming which candidate's case
   survived which attack. If two candidates' cases both survived, that
   is legitimate disagreement; name both in committed_answer.

3. Cruxes (minimum 2): the specific points where candidates' cited
   evidence actually conflicts. For each crux, identify the side_a and
   side_b cited evidence and the observation that would resolve.

4. Minority position: if a candidate's case survived attack but is not
   the most likely answer, that's the minority. Name the advocate's
   label, the position, and why it survived. Set to null only if no
   candidate's case survived attack while being a non-mainstream view.

5. Mainstream prior audit: the framer named the mainstream_consensus.
   Did this deliberation support / modify / reject it, or did it
   merely_reproduce it (committed_answer ≈ mainstream_consensus)? Pick
   the enum value honestly. merely_reproduces is the documented failure
   mode you must check for.

6. Forward claim: most likely, plausible alternative, what would
   surprise the system, falsifiers. Commit. "It depends" is acceptable
   only if the dependencies are specifically named.

7. Biggest things that could be wrong: 2 to 3 load-bearing claims that,
   if wrong, would invalidate your conclusion.

8. Sycophancy flags: if any advocate's confidence dropped without a
   specific attack landing, flag it. (The bilateral-attacks phase is
   structured so there is no opportunity for in-conversation
   sycophancy, but check the confidence drops anyway.)

9. report_markdown: the full Markdown rendering. UK English. No em
   dashes.

Output format: FinalDeliverable schema.
```

## 8. Orchestration

### 8.1 Flow

```
                              [Question]
                                  │
                                  ▼
                            ┌──────────┐
                            │  Framer  │   (1 LLM call, light search)
                            └─────┬────┘
                                  │ CandidateSet (3-5)
                                  ▼
                       ┌─────────────────────┐
                       │ Framings Validator  │  (1 LLM call, no tools)
                       └──────────┬──────────┘
                                  │ final CandidateSet
                  ┌───────────────┼───────────────┐
                  ▼               ▼               ▼
              ┌────────┐      ┌────────┐      ┌────────┐
              │ side-1 │      │ side-2 │      │ side-N │   (N parallel,
              │ resrch │      │ resrch │      │ resrch │    search_web +
              └────┬───┘      └────┬───┘      └────┬───┘    fetch_url)
                   │               │               │
                   ▼               ▼               ▼
              ┌────────┐      ┌────────┐      ┌────────┐
              │advoct-1│      │advoct-2│      │advoct-N│   (N parallel,
              │ (blind)│      │ (blind)│      │ (blind)│    no tools, own
              └────┬───┘      └────┬───┘      └────┬───┘    packet only)
                   └───────────────┼───────────────┘
                                   ▼ all packets + all cases
                  ┌────────────────┼────────────────┐
                  ▼                ▼                ▼
              ┌────────┐      ┌────────┐      ┌────────┐
              │attck-1 │      │attck-2 │      │attck-N │   (N parallel,
              │vs 2..N │      │vs 1,3..│      │vs 1..N-│    union of packets)
              └────┬───┘      └────┬───┘      └────┬───┘
                   └───────────────┼───────────────┘
                                   ▼
                              ┌────────┐
                              │  JUDGE │   (1 LLM call, Opus, high effort)
                              └────┬───┘
                                   ▼
                          [FinalDeliverable]
```

### 8.2 Phase-by-phase

1. **Framing** — framer produces CandidateSet (1 LLM call).
2. **Framing validation** — validator either approves or replaces. Final CandidateSet is fixed (1 LLM call).
3. **Asymmetric research** — N parallel researchers, one per candidate, each producing a SidePacket (N LLM calls in parallel; ~5 min wall time).
4. **Blind advocacy** — N parallel advocates, each seeing only own packet, producing AdvocateCase (N LLM calls in parallel).
5. **Bilateral attacks** — N parallel attackers, each seeing all packets + all cases, producing AttacksByAdvocate with N-1 attacks each (N LLM calls in parallel).
6. **Judging** — single judge consumes everything, produces FinalDeliverable (1 LLM call with extended thinking; ~3–5 min wall time).
7. **Persistence** — three artifacts (deliverable markdown, deliverable JSON, full transcript JSON) + one learning entry. Reuses v2's `_persist_artifacts` pattern verbatim.

Total LLM calls: 2 + 3N + 1 = 11 for N=3, 14 for N=4. Wall time: 10–15 minutes at defaults.

### 8.3 Topology guarantees (mechanical, not prompt-level)

- **Information asymmetry at research time.** Each side-researcher's `inputs` dict contains its candidate but NOT the other candidates' rationales or evidence. Enforced by the executor's per-call prompt assembly.
- **Blindness at advocacy time.** Each advocate's `inputs` dict contains ONLY its own SidePacket. Enforced by the executor.
- **Full information at attack time.** Each attacker sees `all_cases` and `all_packets`. Enforced by the executor.
- **No mutability of upstream outputs.** Phase outputs are frozen Pydantic models passed by reference; no agent can rewrite another's case.

These are structural anti-convergence properties, not prompt instructions. The model cannot disobey them because it cannot see what isn't in its inputs.

## 9. Executor

New file: `modules/backend/agents/mission_control/dispatch/advocate_judge_loop.py`.

Shape mirrors `deliberation_loop.py` (v2 reference). Skeleton:

```python
async def execute_advocate_judge_loop(
    *,
    task_id: str,
    question: str,
    config: AdvocateJudgeConfig,
    execute_agent_fn: ExecuteAgentFn,
    mission_id: str | None = None,
    gate: GateReviewer | None = None,
    event_bus: EventBusProtocol | None = None,
    session_id: str | None = None,
) -> TaskResult:
    # Phase 1: framing
    candidate_set = await _run_framer(...)
    candidate_set = await _run_framings_validator(candidate_set, ...)

    # Phase 2: asymmetric research (parallel)
    packets = await asyncio.gather(*[
        _run_side_researcher(candidate=c, ...)
        for c in candidate_set.candidates
    ])

    # Phase 3: blind advocacy (parallel)
    cases = await asyncio.gather(*[
        _run_advocate(packet=p, ...)
        for p in packets
    ])

    # Phase 4: bilateral attacks (parallel; each attacker sees union)
    union_of_packets = list(packets)
    union_of_cases = list(cases)
    attacks = await asyncio.gather(*[
        _run_attacker(
            advocate_label=c.candidate_label,
            own_case=cases[i],
            all_cases=union_of_cases,
            all_packets=union_of_packets,
            ...
        )
        for i, c in enumerate(cases)
    ])

    # Phase 5: judging
    deliverable = await _run_judge(
        question=question,
        candidate_set=candidate_set,
        packets=packets,
        cases=cases,
        attacks=attacks,
        ...
    )

    # Phase 6: persistence (mission-attached only)
    if mission_id:
        await _persist_artifacts(...)

    return TaskResult(status=SUCCESS, output_reference=deliverable.model_dump(), ...)
```

Per-phase helpers each return `(output_model, cost_usd, tokens)` tuples; the loop accumulates cost and token usage.

Per-phase `_narrative()` events emit at start of each phase for Kanban visibility. Phase markers: `framing`, `validate_framing`, `research`, `advocacy`, `attacks`, `judge`, `done`, `error`.

Failure handling: any phase failure raises; the loop catches at top and returns `TaskStatus.FAILED` with the error. No retries inside the loop; PydanticAI `output_retries=2` per agent is the only retry layer.

## 10. Workflow YAML

The new YAML takes the **canonical `deliberation.think-tank.workflow` name from day 1** (per architectural decision §2.11). v2's existing YAML at `config/workflow_templates/deliberation.think-tank.workflow.yaml` is moved to `deliberation.think-tank.v2.workflow.yaml` with `enabled: false`, mirroring how v1 was preserved as `…v1.workflow.yaml`.

New file (replacing v2's at the same path): `config/workflow_templates/deliberation.think-tank.workflow.yaml`. Single step with `type: advocate_judge_loop`.

```yaml
workflow_name: deliberation.think-tank.workflow
description: "Think Tank — advocate-judge deliberation for contested open questions"
objective:
  statement: "Produce a structured deliberation preserving live disagreement"
  category: research
  owner: user
  priority: normal
version: 3  # v1 = 34-step wave-engine; v2 = collapsed deliberation_loop; v3 = advocate-judge
enabled: true

trigger:
  type: on_demand
  match_patterns:
    - "think tank"
    - "deliberate"
    - "advocate-judge"
    - "contested question"

budget:
  # Conservative cap. Realistic worst case at N=4 is ~$15 (per-side
  # researchers ~$2 each, advocates+attacks+judge ~$1 each, plus framer
  # ~$1, validator ~$1). Set ceiling to 5x worst case.
  max_cost_usd: 75.00

parameters:
  - { key: question, label: "Question", type: text, required: true }
  - { key: max_candidates, label: "Max candidates", type: number, default: 4 }
  - { key: min_candidates, label: "Min candidates", type: number, default: 3 }
  - { key: side_models, label: "Per-side model override (CSV)", type: text, required: false, default: "" }
  - { key: judge_model, label: "Judge model", type: text, required: false, default: "copilot:claude-opus-4.7" }

context:
  question: ""
  max_candidates: 4
  min_candidates: 3
  side_models: ""
  judge_model: "copilot:claude-opus-4.7"

steps:
  - id: advocate_judge
    label: "Advocate-Judge deliberation"
    description: "Asymmetric multi-advocate + judge deliberation"
    capability: deliberation.advocate_judge_framer  # arbitrary; type routes elsewhere
    roster: default
    complexity_tier: complex
    cost_ceiling_usd: 75.00
    environment: local
    input:
      type: "advocate_judge_loop"
      question: "@context.question"
      loop_config:
        max_candidates: "@context.max_candidates"
        min_candidates: "@context.min_candidates"
        side_models: "@context.side_models"
        judge_model: "@context.judge_model"
    timeout_seconds: 3600
    termination: completion
    depends_on: []
```

Dispatch loop wiring: add a fork in `modules/backend/agents/mission_control/dispatch/loop.py` next to `deliberation_loop` (line 344):

```python
if task_type == "advocate_judge_loop":
    coros.append(_dispatch_advocate_judge_loop(...))
    continue
```

with a `_dispatch_advocate_judge_loop` helper that mirrors `_dispatch_deliberation_loop` (lines 670–745).

## 11. CLI standalone script

`scripts/think_tank_advocate_judge.py` — direct-invocation Python script, mirrors `scripts/think_tank_v2.py`. Same `--question`, `--out`, and per-phase config flags. Used for the A/B comparison in Phase 9 below.

## 12. Phases (implementation order)

0. **Phase 0 — Google provider hookup (optional but recommended).** Add a `google:` branch to `_build_model` in [modules/backend/core/model_builder.py](../../modules/backend/core/model_builder.py) using `pydantic_ai.models.google.GoogleModel`, plus an env-var or config-driven API key in `model_providers.py`. Tests: `_build_model("google:gemini-2.5-pro")` returns a working model; a hello-world prompt to it succeeds. Without this phase, the rotation in §5.1 falls back to 2 families with a re-use note — the architecture works, the heterogeneity signal weakens. Estimated effort: half day.
1. **Phase 1 — Schemas + executor skeleton.** Write `deliberation_advocate_judge.py` schemas (including `AdvocateJudgeConfig` with `side_models` and `judge_model` fields per §5.1). Write `advocate_judge_loop.py` skeleton that calls a noop `execute_agent_fn` (returns fake outputs) so the orchestration can be unit-tested without LLMs. Include a provider-availability check at executor start that calls `_build_model` once per resolved per-side model string and fails loud if any provider isn't wired — so misconfiguration trips immediately, not 20 min into a run. Tests: schema validation; executor topology (asymmetric inputs, blind inputs, union-at-attacks); provider rotation fallback when N exceeds available families.
2. **Phase 2 — Framer + validator.** YAMLs, system prompts, agent modules (`create_agent`). Tests: framer produces valid CandidateSet; validator produces FramingValidation; revised_set replaces original when verdict=revised.
3. **Phase 3 — Per-side researcher.** YAML, system prompt, agent module. Tests: with stubbed search_web, produces valid SidePacket; weakest_link is populated; sources all have URLs.
4. **Phase 4 — Per-side advocate (blind case + attacks).** YAML, two system prompts (one for blind case, one for attacks). Tests: blind case schema; attacks schema with N-1 entries; cited_evidence_urls are subset of union of packets.
5. **Phase 5 — Judge.** YAML, system prompt, agent module. Tests: produces valid FinalDeliverable; cruxes ≥ 2; minority_position present if any case survived attack while non-mainstream.
6. **Phase 6 — Wire executor end-to-end + dispatch loop fork + workflow YAML cutover.** Connect to `_make_agent_executor` (passing the per-side resolved model per agent dispatch). Add `advocate_judge_loop` fork to dispatch loop. Move v2's `config/workflow_templates/deliberation.think-tank.workflow.yaml` to `…v2.workflow.yaml` with `enabled: false` (mirrors v1's archive at `…v1.workflow.yaml`); write the new YAML at the canonical path with `workflow_name: deliberation.think-tank.workflow`. `scripts/think_tank_advocate_judge.py` works against the new executor (no workflow involvement).
7. **Phase 7 — Live smoke run.** Direct script on Q1 ("UK knowledge work 2030"). Goal: produces a valid FinalDeliverable end-to-end. Cost ≤ $20, wall time ≤ 30 min. If it fails: triage failure mode, fix, retry.
8. **Phase 8 — A/B comparison vs baseline.** Run Advocate-Judge on all 3 validation questions (Q1, Q2, Q3 from validation findings doc). Use existing `scripts/think_tank_anonymise.py` to blind-pair Advocate-Judge outputs with the baseline outputs already in `var/validation/baseline/`. Read blind and score on 3 dimensions: preserves disagreement / cruxes are real disagreements / minority has substance. Unmask. Document outcome in `docs/98-research/034-Advocate-Judge-Validation-Findings.md`.
9. **Phase 9 — Decision gate.** If Advocate-Judge measurably beats baseline on at least 2 of 3 questions on at least 2 of 3 dimensions, ship: promote to default Think Tank workflow; archive v2 code permanently; close Plan 79. If not, do not ship — recommend the single-call baseline as the production "deliberation" implementation and downgrade Plan 80 to research-only.

The decision in Phase 9 is mechanical, not aspirational. If Advocate-Judge doesn't beat the baseline, the answer to "what should Think Tank be" is "the baseline" — and the value of the work was the validation, not the rewrite.

## 13. Acceptance criteria

- Schemas: `deliberation_advocate_judge.py` passes mypy strict; all schemas have ConfigDict(extra="forbid"); FinalDeliverable from `deliberation.py` is reused (no duplication).
- Executor: `advocate_judge_loop.py` runs end-to-end with stubbed `execute_agent_fn` in <1s for unit tests; per-phase narrative events emit in correct order; mission_id=None skips persistence cleanly.
- Live run: Q1 produces a FinalDeliverable with cruxes ≥ 2, minority_position evaluation completed (either populated or explicitly null), deliberation_vs_mainstream picked from the enum honestly, sycophancy_flags populated if any.
- A/B vs baseline: deliverables for Q1, Q2, Q3 land in `var/validation/advocate_judge/`; anonymisation harness pairs them with baseline; key file persisted; reveal mechanism works.
- Workflow YAML: registers cleanly; mission-attached run via `mc.py run` produces artifacts in the mission's artifact store.

## 14. Caveats and open questions

1. **N is chosen by the framer.** That's a single point of decision that could be biased toward conventional N=3. Mitigation: framings_validator explicitly checks for missing schools. If this turns out to be a real bias, add a config knob `--force-n=4`.
2. **The framings_validator is itself an LLM and could miss bias.** P13 (no self-evaluation) is satisfied by it being a different agent, but two Claude calls share priors. If validation results show systematic under-counting of contrarian camps, consider human-in-the-loop framing review (Shape H from the original architectural memo).
3. **The judge's "merely_reproduces" judgement is itself biased by being one LLM.** Sub-mitigation: the schema's enum forces an explicit choice, and the synthesiser cannot quietly hedge. Real mitigation would be a separate auditor — out of scope for v1.
4. **No follow-up research between phases.** A debater in Plan 79 could ask for more research mid-deliberation. Advocate-Judge cannot — the per-side researchers are sized to do their job in one pass. If real questions need iterative research, this is the first place to extend.
5. **Cost is bounded but not measured yet.** Worst case at N=4 estimated ~$15 (3 researchers + 4 advocates + 4 attackers + 1 judge at Opus 4.6 with extended thinking). Real runs may differ; Phase 7 smoke run is the first data point.
6. **Persona-based debaters were the structural diversity mechanism in Plan 79.** Advocate-Judge substitutes two structural mechanisms: (a) information asymmetry (different evidence per side), and (b) model-family heterogeneity (different priors per side, §5.1). Both are structural rather than prompt-based. The bet (per the architectural memo and Khan et al. evidence) is that structural diversity is more durable than persona diversity. Phase 8 A/B comparison tests the combined bet against the single-call baseline. If Phase 8 ships, a follow-on experiment could disentangle the two mechanisms (single-family vs multi-family) to attribute the gain.
7. **Provider availability is an operational dependency.** The recommended per-side rotation (Claude / GPT / Gemini) assumes all three providers are wired locally. Copilot SDK covers Claude + GPT under one credential; Google provider is a separate hookup. If a provider isn't available, executor falls back to repeating available families (with a `sycophancy_flags` entry noting the reduced heterogeneity) — so the run continues but the experimental signal weakens. Production deployments should monitor that all configured providers stay healthy.

## 15. Out of scope for v1

- Multi-round attack-defence (more than one round of attacks per advocate). The literature doesn't support it; sycophancy risk grows.
- Stance-delta or any embedding-based early-stopping signal.
- A standalone verifier agent (the judge absorbs this role).
- Persona-based debaters in any form.
- Human-in-the-loop framing or judging.
- Tournament elimination of candidates.
- Single-call Claude with extended thinking (already exists as `scripts/think_tank_baseline.py`; this plan is "what beats the baseline").
- Adaptive N (framer decides 3 vs 4 dynamically based on question; v1 uses a fixed range with framer choosing within it).

## 16. File manifest

**New files:**
- `modules/backend/schemas/deliberation_advocate_judge.py` — Advocate-Judge schemas (Phase 1)
- `modules/backend/agents/mission_control/dispatch/advocate_judge_loop.py` — executor (Phases 1, 6)
- `modules/backend/agents/deliberation/advocate_judge_framer/agent.py` — framer module (Phase 2)
- `modules/backend/agents/deliberation/advocate_judge_framings_validator/agent.py` (Phase 2)
- `modules/backend/agents/deliberation/advocate_judge_side_researcher/agent.py` (Phase 3)
- `modules/backend/agents/deliberation/advocate_judge_advocate/agent.py` (Phase 4)
- `modules/backend/agents/deliberation/advocate_judge_judge/agent.py` (Phase 5)
- `config/agents/deliberation/advocate_judge_framer/agent.yaml` (Phase 2)
- `config/agents/deliberation/advocate_judge_framings_validator/agent.yaml` (Phase 2)
- `config/agents/deliberation/advocate_judge_side_researcher/agent.yaml` (Phase 3)
- `config/agents/deliberation/advocate_judge_advocate/agent.yaml` (Phase 4)
- `config/agents/deliberation/advocate_judge_judge/agent.yaml` (Phase 5)
- `config/prompts/agents/deliberation/advocate_judge_framer/system.md` (Phase 2)
- `config/prompts/agents/deliberation/advocate_judge_framings_validator/system.md` (Phase 2)
- `config/prompts/agents/deliberation/advocate_judge_side_researcher/system.md` (Phase 3)
- `config/prompts/agents/deliberation/advocate_judge_advocate/system_case.md` (Phase 4)
- `config/prompts/agents/deliberation/advocate_judge_advocate/system_attacks.md` (Phase 4)
- `config/prompts/agents/deliberation/advocate_judge_judge/system.md` (Phase 5)
- `config/workflow_templates/deliberation.think-tank.workflow.yaml` (Phase 6 — replaces v2's content at this path; v2 YAML moves to `…v2.workflow.yaml`)
- `scripts/think_tank_advocate_judge.py` — standalone direct invocation (Phase 6)
- `tests/unit/backend/agents/test_advocate_judge/` — unit tests per phase
- `docs/98-research/034-Advocate-Judge-Validation-Findings.md` — A/B writeup (Phase 8)

**Modified / renamed files:**
- `modules/backend/agents/mission_control/dispatch/loop.py` — add `advocate_judge_loop` task-type fork (~30 lines, mirrors deliberation_loop fork at line 344).
- `modules/backend/core/model_builder.py` — add `google:` branch to `_build_model` (Phase 0, optional but recommended).
- `modules/backend/core/model_providers.py` — add `get_google_provider()` parallel to `get_anthropic_provider()` / `get_openai_provider()` (Phase 0).
- `config/workflow_templates/deliberation.think-tank.workflow.yaml` — git mv to `deliberation.think-tank.v2.workflow.yaml`; set `enabled: false` in the moved file (Phase 6).

**Imported unchanged:**
- `modules/backend/schemas/deliberation.py` (for FinalDeliverable + supporting types)
- `modules/backend/tools/{search_web,fetch_url,query_knowledge,store_artifact,store_learning}.py`
- `modules/backend/core/copilot_model.py`
- `modules/backend/core/model_builder.py` — multi-provider `_build_model` (anthropic / openai / copilot / google) already supports the per-side model strings in §5.1
- `modules/backend/agents/mission_control/helpers/agent_executor.py`
- `modules/backend/agents/mission_control/{gate,models}.py`

**Deleted in this plan:** none. Plan 79 files remain on `feature/79-think-tank-deliberation` as reference. Promote-or-delete decision happens at Phase 9.

## 17. Estimated effort

Rough budget, assuming the executor wiring (Phase 1) and one agent (Phase 2) reveal no surprises:

- Phase 0 (Google provider hookup, optional): half day
- Phase 1 (schemas + skeleton + tests): half day
- Phase 2 (framer + validator + tests): half day
- Phase 3 (researcher + tests): half day
- Phase 4 (advocate two-mode + tests): half day
- Phase 5 (judge + tests): half day
- Phase 6 (end-to-end wiring + workflow YAML + CLI script): half day
- Phase 7 (live smoke + debug): 1 day (allow time for iterations)
- Phase 8 (A/B comparison run + write-up): half day
- Phase 9 (decision + ship-or-archive): half day

**Total: ~5–5.5 days of focused work** (Phase 0 adds half a day if Gemini support is included). Most of the risk is in Phase 7 (live debug); the structural work in Phases 0–6 should be straightforward because the patterns are well-established in v2.
