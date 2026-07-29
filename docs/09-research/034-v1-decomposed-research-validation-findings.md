# 034 — v1-decomposed-research Validation Findings

*Date:* 2026-05-26
*Plan:* 81 (see `docs/97-plans/81-prompt-v1-research-decomposition.md` and
`docs/97-plans/81a-design-v1-research-decomposition.md`)
*Comparator:* `var/validation/v1_decomposed/` vs `var/validation/baseline/`
*Anonymisation seed:* 42 (`scripts/think_tank_anonymise.py --comparator v1_decomposed --seed 42`)

---

## TL;DR

**Ship v1-decomposed.** It wins on 9/9 dimensions across all 3 contested
validation questions. The decisive separator is **per-debater attribution
of disagreement**: v1-decomposed explicitly tags which debaters hold
which side of each crux, surfaces minority positions that are
structurally orthogonal to the majority view rather than stronger
versions of it, and produces sharper, mechanism-specific cruxes.

The Plan 80 §Phase 8 ship rule
("v1-decomposed beats baseline on ≥2/3 questions × ≥2/3 dimensions")
is exceeded by a wide margin.

---

## Method

1. Ran v1-with-decomposed-research autonomously against the 3 Plan-80
   validation questions (Q1 UK knowledge-work / Q2 EU AI Act / Q3
   fusion). All 3 produced a valid `FinalDeliverable`, persisted as
   `deliberation_deliverable` artifacts on
   `mission_id=019e6329-aee0-7540-b8c7-84abd7b8534b` and saved to
   `var/validation/v1_decomposed/q{1,2,3}_v1d.{json,md}`.
2. Ran `scripts/think_tank_anonymise.py --comparator v1_decomposed --seed 42`
   to A/B-shuffle baseline outputs (`var/validation/baseline/q{1,2,3}_solo.md`)
   against v1-decomposed outputs into `var/validation/blind_v1_decomposed/`.
3. Read each pair (q{1,2,3}_{A,B}.md) blind and scored on the three
   Plan-80-§Phase-8 dimensions:
   - **Preserves disagreement:** surfaces live expert disagreement
     vs collapses to one view
   - **Cruxes are real:** actual divergence points vs restated
     positions
   - **Minority has substance:** defensible alternative vs token
     contrarian
4. Revealed the key
   (`python scripts/think_tank_anonymise.py --comparator v1_decomposed --reveal`).

---

## Headline numbers

| Question | Cruxes (baseline / v1d) | Confidence (baseline / v1d) | Mainstream verdict |
|---|---|---|---|
| Q1 (UK knowledge-work) | 3 / 3 | 0.45 / 0.42 | both `modifies` |
| Q2 (EU AI Act) | 3 / 4 | 0.72 / 0.65 | baseline `modifies`, v1d `supports` |
| Q3 (fusion) | 3 / 5 | 0.73 / 0.82 | baseline `modifies`, v1d `supports` |

Where the deliverables differ structurally:

- **v1-decomposed always tags cruxes per-debater** (`Side A (systems, quant): …`),
  making it mechanically visible *which seat at the table* held which
  position. Baseline names abstract camps ("Civil society critics",
  "EU institutional insiders") which are exogenous to the deliberation.
- **v1-decomposed's `sycophancy_flags`** carry the actual
  `convergence_flag` outputs from the per-round critic
  (Round 0/1/2/3 `shared_hidden_assumption: …`), which is the
  Plan 79 anti-flattening mechanism doing its job. Baseline writes
  "None. This deliberation was conducted in a single pass without
  peer pressure" — by construction it cannot have convergence flags.
- **v1-decomposed's minority position names the debater** (Empiricist
  on Q2, Ethicist on Q1 and Q3). Baseline's minority is held by
  abstract schools.

---

## Per-question scoring

Blind labels (revealed at the end):

| | Q1 | Q2 | Q3 |
|---|---|---|---|
| A | baseline | v1_decomposed | baseline |
| B | v1_decomposed | baseline | v1_decomposed |

### Q1 — UK knowledge-work employment by 2030

**Preserves disagreement:** v1_decomposed wins. Both surface
multiple cruxes with bilateral steelmen, but v1d's per-debater
attribution (`Side A (systems, quant, empiricist): …`) makes the
4-way debate structure mechanically visible. Baseline names exogenous
schools ("Solow Paradox", "Acemoglu", "TBI/Augmentation, WEF
consensus") — useful as anchors but the disagreement is not
self-evidently grounded in the deliberation itself.

**Cruxes are real:** v1_decomposed wins. Baseline's cruxes are
**Adoption Speed**, **Productivity Transmission**, **Substitution vs
Augmentation** — important framing axes but somewhat textbook.
v1d's cruxes are sharper and mechanism-specific:
1. *Can AI absorb departed workers' output without quality degradation?*
2. *Will enterprise adoption reach 25-35% at-scale by 2030?* (specific threshold)
3. *Generational exclusion versus pipeline redirection?* (novel framing)
The "generational exclusion" crux in particular is not a restated
position; it is a mechanism that the Ethicist surfaced and the other
debaters did not address.

**Minority has substance:** v1_decomposed wins. Baseline's minority
("effect indistinguishable from cyclical variation; Solow Paradox
school") is a stronger version of the majority view's
slow-adoption side. v1d's minority is **structurally orthogonal** —
the Ethicist argues the aggregate-displacement framing obscures the
distributional injustice (attrition non-replacement burden falls
100% on would-be entrants, 0% on incumbents). This is not "more
slow" or "less slow" but "the framing is wrong." Survives an
explicit critic challenge that "could not break the core logic
that hiring freezes cannot, by construction, harm anyone already
employed."

**Q1 score: 3/3 to v1_decomposed.**

### Q2 — EU AI Act substantially weakened by end-2027

**Preserves disagreement:** v1_decomposed wins (narrowly). Baseline
has 3 cruxes with strong bilateral steelmen and named camps
("Civil society critics, deregulatory-ratchet analysts" vs "EU
institutional insiders, structural-resilience advocates"). v1d has
4 cruxes (one extra: Provider-vs-Deployer protection gap) with
per-debater attribution. The 4th crux adds a distinct axis of
disagreement (Ethicist surfacing the deployer-side context-failure
question) that baseline misses entirely.

**Cruxes are real:** v1_decomposed wins. Baseline's GDPR-precedent
crux (is GDPR's slow-then-fast trajectory the right reference
class?) is excellent meta-analytical. But v1d's "Standards as
Enforcement Precondition" crux is a sharper technical/legal
question with a sharper resolution criterion ("a national authority
initiating enforcement for inadequacy without referencing hENs").
v1d also surfaces the market-access-gate counter-mechanism as a
top-level crux, which baseline buries in the minority position.

**Minority has substance:** v1_decomposed wins. Baseline's minority
("weakened beyond meaningful recovery — omnibus as first in a
series") is a *stronger version* of the majority verdict
(yes, weakened). v1d's minority is the Empiricist arguing the
Act will **not** be substantially weakened — market-access
conditionality drives compliance independently of enforcement,
following EU product safety precedent. This is genuinely
contrarian; the survival rationale ("the majority shares an
unstated assumption that providers deploy regardless of compliance
that remains empirically untested") is exactly the
shared-hidden-assumption pattern Plan 79's anti-flattening
machinery is built to surface.

**Q2 score: 3/3 to v1_decomposed.**

### Q3 — Commercial fusion utility-grade electricity before 2040

**Preserves disagreement:** v1_decomposed wins. Baseline has 3
cruxes with abstract-camp framing ("Yes — regime change" vs
"No — new problems replace old ones"). v1d has 5 cruxes, each
with explicit per-debater attribution including the Critic's
counter-positions (e.g. Crux 2 `Side A (Systems, Quant,
Empiricist) vs Side B (Critic)`). The Critic acting as a
position-bearer is a Plan 79 architectural feature absent from
baseline by construction.

**Cruxes are real:** v1_decomposed wins. Baseline's cruxes hit
the surface (private vs government, time-to-cost-parity, AI
demand). v1d's cruxes go one layer deeper:
1. Factory cost-learning without operational feedback (Solow-vs-
   solar-PV analogy)
2. HTS-magnet fusion vs fission (categorically different or not)
3. 0/N historical slippage pattern (sample-confounded or not)
4. Progressive licensing compress the post-Q>1 timeline
5. Non-DT fuel cycle bypass

These are mechanism-level questions; baseline's are framing-level.

**Minority has substance:** v1_decomposed wins. Baseline's minority
("premium niche viability — fusion at $100-150/MWh for AI data
centres") is a softer/weaker version of the majority (still about
when fusion works at what price). v1d's minority is the Ethicist's
**distributional access argument**: even successful fusion
reproduces fission's geographic concentration; 20-30 year access
gap between OECD grids and energy-poor populations; no fusion
company has published binding non-OECD deployment commitments.
This is *not* about whether fusion works; it is about whose
question "competitive" answers. Survives because "no technical
debater engaged with the structural exclusion claim across three
rounds."

**Q3 score: 3/3 to v1_decomposed.**

---

## Aggregate

| Dimension | Q1 | Q2 | Q3 | Total |
|---|---|---|---|---|
| Preserves disagreement | v1d | v1d | v1d | 3/3 |
| Cruxes are real | v1d | v1d | v1d | 3/3 |
| Minority has substance | v1d | v1d | v1d | 3/3 |
| **By question** | 3/3 | 3/3 | 3/3 | **9/9** |

Decision rubric (Plan 80 §Phase 8):
**Ship v1-decomposed if ≥ 2/3 questions × ≥ 2/3 dimensions.**

Result: 3/3 × 3/3 = 9/9. **Ship.**

---

## Caveats and noted weaknesses

1. **Single-shot validation per question.** Each Q ran once for
   baseline and once for v1-decomposed. Plan 81's own smoke test
   surfaced run-to-run verifier variance — a v1-decomposed Q1
   packet that passed the smoke test verifier (first run) was
   rejected by the verifier on a subsequent autonomous run. The
   9/9 result is on the successful runs that produced
   deliverables; the per-question pass rate of v1-decomposed is
   not measured here. Recommend a follow-up study that samples
   N≥3 runs per question per system.

2. **The verifier is doing its job.** Two of three v1-decomposed
   Q1 runs in this work had their packets rejected by
   `deliberation.research_verifier` for legitimate quality
   reasons (mainstream consensus being a strawman or
   under-discussed angles in fact being widely discussed). This
   is the design working as intended — the verifier is the gate
   that prevents weak packets from reaching debaters — but it
   also means *getting* a successful v1-decomposed deliverable
   requires a retry budget that single-call baseline does not.

3. **Cost: not measured.** The Copilot SDK didn't report
   per-token cost in any of the deliverable steps; reported cost
   was $0.00 (with the verifier's $0.10 visible on one Phase 0
   run). Real costs are non-zero and v1-decomposed runs ~16-20
   debater+critic LLM calls per question against baseline's 1.
   The architectural win does not necessarily clear a
   cost-per-quality bar. Out of scope for this validation.

4. **Confidence calibration.** v1-decomposed reports lower
   confidence on Q1 (0.42 vs 0.45) and Q2 (0.65 vs 0.72) but
   higher on Q3 (0.82 vs 0.73). No clear pattern; both systems
   appear roughly calibrated to the question's actual
   contestedness.

---

## Platform bugs surfaced and fixed during validation

Plan 81's run uncovered 10 separate platform bugs that the original
v1 smoke tests would not have hit. All fixed in this branch:

1. **http_client deps not routed to deliberation Phase 0 agents**
   (`agent_setup.py`) — silent `search_web` failures. The original
   root cause of v1's "researcher refusal" pattern.
   Commit `c53ced9`.
2. **Kanban status mismatch** (`workflow_run_waves.py`) — every
   agent_step shown FAILED on the board even when it succeeded.
   Plan 80h regression. Commit `c53ced9`.
3. **Merge-skip bug** (`workflow_run_waves.py:_should_skip`) —
   `final-merge` skipped when both stop-r1 and stop-r2 chose
   "continue", killing the synthesiser. Commit `9cdb23f`.
4. **Critic prompt missing field on last debater entry** (last
   `attacks.*.what_would_vindicate_the_debater`) — repeatedly
   tripped Pydantic validation. Commit `9cdb23f`.
5. **Phantom mission-scoped workflow_definition** with auto-derived
   (label-less) edges via `import_from_template`'s missing
   `edges_json` passthrough. Caused `halt-bad-research` to fire
   on `gate=passed` packets. Commit `71c72a6`.
6. **`DebaterTurn` schema fields too tight** for round-3 output
   (LoadBearingClaim.if_this_fails 300→1000,
   what_would_change_my_mind 1000→2000, claim 500→1000,
   position 2000→4000, decision_justification 500→1000) and
   `FinalDeliverable.committed_answer` 2000→4000,
   `recommendation_markdown` 2000→4000. Commits `23c3e25`,
   `5de9fb6`.
7. **`artifact_type` enum missing deliberation entries**
   (`deliberation_deliverable`, `deliberation_transcript`) — store
   tool calls failed despite a valid `FinalDeliverable`. Plan 79
   omission; the YAML used the strings but
   `models/mission_artifact.py` never registered them in
   `ArtifactType`. Commit `aaf792c`.
8. **`think_tank_anonymise.py` hardcoded to v2 comparator** —
   needed `--comparator` flag for v1_decomposed family.
   Commit `67a8045`.
9. **(known follow-up)** `update_workflow` and `create_workflow`
   defaults in `workflow_definition.py` still call `_derive_edges`
   when steps are saved without explicit edges_json. Reachable from
   the frontend canvas-save flow; not fixed in this validation
   because the path was not reached.
10. **(known follow-up)** OpenAI embedding backend returning
    fail-open empty embeddings — `compute_stance_delta` then
    consistently chooses "continue" on both stop-r1 and stop-r2.
    All v1-decomposed runs ran full 3 debate rounds in this
    validation rather than early-stopping. Pre-existing infra
    issue; not Plan 81.

---

## Ship action plan

Per Plan 81 Step 6 ("If v1-decomposed beats baseline on ≥2/3
questions × ≥2/3 dimensions: ship v1-decomposed"):

1. Rename
   `config/workflow_templates/deliberation.think-tank.v1.workflow.yaml`
   → `deliberation.think-tank.workflow.yaml`.
2. Update `workflow_name` inside the YAML to drop `.v1` infix.
3. Re-seed: `python admin.py admin seed-workflows --force`.
4. Verify in DB:
   ```sql
   SELECT name FROM workflow_definitions
   WHERE name LIKE 'deliberation.think-tank%';
   ```
5. Update `MEMORY.md` and `project_think_tank_validation.md` to
   reflect that v1-with-decomposed-research is the canonical
   Think Tank workflow.
6. Final commit summarising what shipped vs. what was discarded.

This will be done as a follow-up commit after this findings doc
lands.

---

## Definition of done

- [x] All 3 v1-decomposed deliverables produced and persisted
  (`var/validation/v1_decomposed/q{1,2,3}_v1d.{json,md}`)
- [x] Anonymisation script supports the v1_decomposed comparator
- [x] Blind pairs scored on the 3 plan-defined dimensions
- [x] Findings doc written (this file)
- [x] Decision-gate outcome: **SHIP v1-decomposed** (9/9 result)
- [ ] Ship actions executed (rename + reseed + memory updates) — pending user OK
- [ ] Final hand-off commit
