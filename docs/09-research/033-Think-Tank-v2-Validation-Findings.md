# Think Tank v2 — Validation Findings

**Date:** 2026-05-24
**Plan:** 79 (Think Tank multi-agent deliberation)
**Compared:** v2 (7-agent orchestrated deliberation) vs single-call baseline (Opus 4.6, extended thinking, web search, same `FinalDeliverable` schema)
**Recommendation:** v2 architecture is not load-bearing. Commit to a rewrite (Advocate-Judge — asymmetric multi-advocate + judge, per [022/032 architectural memo](../99-archive/79-plan-think-tank-deliberation-mission-[X].md)).

---

## The validation question

Plan 79 v2 surfaced ~10 platform bugs across ~9 live runs. Before committing more engineering to it, we asked: **does the 7-agent orchestrated deliberation produce a measurably better deliverable than one Claude Opus 4.6 call with extended thinking, given the same FinalDeliverable schema?**

If yes → fix the bugs and ship v2.
If no → v2 is dead weight. Commit to a different shape.

## Experiment

Three contested questions, deliberately diverse in domain:

| # | Question | Domain |
|---|----------|--------|
| Q1 | What will agentic AI do to UK knowledge-work employment by 2030? | Future tech-economic (canonical) |
| Q2 | Will the EU AI Act be substantially weakened by enforcement gaps and sectoral carve-outs by end-2027? | Regulatory / political |
| Q3 | Will commercial nuclear fusion deliver utility-grade electricity at competitive cost before 2040? | Technical / economic, hard falsifier |

Both architectures used Copilot Opus 4.6 as the underlying model and were given access to `search_web` + `fetch_url`. Both produced the same `FinalDeliverable` Pydantic schema (`cruxes ≥ 2`, `minority_position` required-or-null, `deliberation_vs_mainstream` enum including `merely_reproduces`).

- **Baseline:** [scripts/think_tank_baseline.py](../../scripts/think_tank_baseline.py) — single Opus call, `reasoning_effort=high`, baseline prompt explicitly walks the model through "consider 3–5 incompatible positions, name load-bearing assumptions, identify cruxes, pick a minority position, audit against mainstream, commit to a forward claim with falsifiers."
- **v2:** [scripts/think_tank_v2.py](../../scripts/think_tank_v2.py) — direct in-process invocation of `execute_deliberation_loop()`, bypassing FastAPI / Temporal / SSE. Same execution path as the workflow YAML; no transport-layer timeouts.

## Results

### Baseline: 3/3 on first attempt

| Q | Confidence | Cruxes | Minority preserved | vs mainstream | Sycophancy flags | Wall time | Tool calls |
|---|-----------|--------|--------------------|---------------|------------------|-----------|------------|
| Q1 | 0.45 | 3 | yes | modifies | 0 | ~4.5 min | 12 |
| Q2 | 0.72 | 3 | yes | modifies | 0 | ~5.0 min | 11 |
| Q3 | 0.73 | 3 | yes | modifies | 0 | ~5.0 min | 9 |

All three hit the structural anti-flattening constraints. All three modify (not merely reproduce) the mainstream prior. Cruxes are real, named disagreements with steelmen and falsifiable resolving evidence. Minority positions are substantive. Deliverables at [var/validation/baseline/](../../var/validation/baseline/).

### v2: 0/1, failed in the same mode it has failed in before

Q1 v2 ran for ~3 min and crashed. The deliberation researcher made 5 successful `search_web` calls, then *chose to refuse the task*:

```
"I cannot complete this request... do you have working internet access?"
```

PydanticAI then tried to parse the refusal as a `ResearchPacket` and threw `ValidationError: Invalid JSON: expected ident at line 1 column 2`. The deliberation loop bombed in `_run_researcher` before any debater ran.

This is structurally the same failure named in the original brief: *"The researcher fabricates citations even with tools. We've tried: tightening the prompt, switching to Opus 4.6, bumping output_retries, adding a verifier that halts. Verifier still keeps rejecting."* The current state of [config/prompts/agents/deliberation/researcher/system.md:56-95](../../config/prompts/agents/deliberation/researcher/system.md#L56-L95) is the natural endpoint of that loop — the citation discipline is so strict that the only safe move is to refuse:

> The verifier explicitly rejects packets containing claims you "remembered" from training but could not confirm via tools... Self-confessed unverifiable claims — phrases like "I cannot confirm the exact citation without live access"... are an automatic rejection.

Between fabricating (which gets killed by the verifier) and refusing (which crashes the loop), the model picked refusal. **This is not a prompt-engineering miss; it's the architectural choice of "one researcher must produce a balanced, fully-cited packet on a contested topic" hitting the limit of what the task structure allows.**

Q2 and Q3 v2 runs were not attempted. The Q1 failure is not "a bad day for one question"; it's a re-occurrence of the documented architectural failure mode.

## Why baseline succeeded where v2 failed

Same model. Same tools. Different *task scope*:

- The v2 researcher is asked to produce {sourced claims, expert disagreements, mainstream consensus, under-discussed angles, base rates} simultaneously for one prompt, and is told a strict verifier will reject anything weak. Five distinct cognitive tasks, one prompt, fear-driven framing.
- The baseline prompt scopes narrower per-step (think of K positions, name load-bearing assumptions, identify cruxes, audit against mainstream) and is permissive about evidence: *"if you cannot find a source for a claim, drop the claim or label it explicitly as a prior."* The model could partial-attempt, which is what it did.

The single-call baseline does not have a stronger anti-collapse mechanism than v2; it has a *more achievable* task per call.

## What this means for the architecture

The original architectural memo identified five possible shapes:

1. **Single deep call** (the baseline we just validated)
2. **Khan-style binary advocate + judge**
3. **Tournament bracket**
4. **Asymmetric multi-advocate + judge** (recommended)
5. **Drafter + adversarial veto**

The validation result doesn't elevate the baseline to "good enough" — it elevates it to "the bar to beat." Baseline reliably produces well-structured deliverables; we don't yet know if its disagreement is *real* or *plausible-looking*. The empirical literature (Khan et al. 76% vs 48% on QuALITY; Liang et al. on Degeneration of Thought) says structured adversarial pressure with information asymmetry beats single-pass on contested-disagreement tasks. But that only matters if the structured system actually runs.

**Advocate-Judge (asymmetric multi-advocate + judge) directly addresses v2's failure mode** by re-scoping the research task: each side-advocate's dedicated researcher has the narrow job of *"find the strongest evidence for answer X"* rather than the unsolvable *"build a balanced, fully-cited packet on a contested topic."* Narrow + adversarial scope is searchable; broad + neutral scope is not.

## Recommendation

1. **Stop iterating on v2.** The failure mode is architectural, not a bug. Patching the researcher prompt to be more permissive would either re-introduce the fabrication failure mode or weaken the citation discipline that made the verifier worth having.
2. **Commit to Advocate-Judge as the next implementation.** Five phases (framer + framings critic → asymmetric researchers in parallel → advocate cases blind → one bilateral attacks round → judge). Maps cleanly onto Mission Control's wave-engine primitives as ~5 steps without per-step Planning Agent overhead.
3. **Keep the single-call baseline ([scripts/think_tank_baseline.py](../../scripts/think_tank_baseline.py)) in the repo** as the bar Advocate-Judge must beat. Run it on the same questions when Advocate-Judge is ready. If Advocate-Judge doesn't measurably improve disagreement-preservation or crux quality, the simpler architecture wins.
4. **Preserve from v2:** the FinalDeliverable schema (the anti-flattening machinery: `cruxes ≥ 2`, required-or-null `minority_position`, `merely_reproduces` enum, `sycophancy_flags`) is doing real work and survives the rewrite.
5. **Discard from v2:** persona-based debaters (4 fixed reasoning lenses), stance-delta early-stopping (embedding cosine on Pydantic output is a category error per `StanceDelta` docstring), the multi-round + sparse-topology orchestration, the over-broad researcher.

The empirical literature gave us a clue we underweighted: persona prompting changes style, not reasoning (Hu & Collier ACL 2024; Wharton "Playing Pretend"). v2's whole anti-collapse story rests on persona diversity. Information asymmetry between advocates is the one mechanism the literature endorses that the new design can structurally guarantee.

## Artifacts

- Baseline script: [scripts/think_tank_baseline.py](../../scripts/think_tank_baseline.py)
- v2 direct-invocation script: [scripts/think_tank_v2.py](../../scripts/think_tank_v2.py)
- Anonymisation harness (unused this round; ready for advocate-judge-vs-baseline): [scripts/think_tank_anonymise.py](../../scripts/think_tank_anonymise.py)
- Baseline deliverables: [var/validation/baseline/](../../var/validation/baseline/)
- v2 failure log: [var/validation/v2/q1.json](../../var/validation/v2/q1.json), [var/validation/logs/q1_v2_direct.log](../../var/validation/logs/q1_v2_direct.log)

## Caveats

- This is a 3-question, 1-attempt v2 sample. A patient observer would say "the researcher refusal could be transient" — but the same failure mode has now appeared across multiple iterations including after the *"8 bugs fixed"* commit ([a1a23fe](../../) on `feature/79-think-tank-deliberation`). The signal is not noise.
- Deliverable *quality* (vs structural shape) was not blind-scored, because there are no v2 deliverables to score. The baseline alone could be subtly wrong in ways a multi-agent system would catch. Advocate-Judge vs baseline blind comparison should happen once Advocate-Judge produces deliverables.
- Cost is not analysed here. Baseline ran at <$5 per question; v2 cost data is contaminated by its failures.
