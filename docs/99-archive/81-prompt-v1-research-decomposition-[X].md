# Plan 81 prompt — Decompose v1's `deliberation.researcher` step

Hand this prompt to a fresh agent. It is self-contained: read it once,
then execute. Don't ask for clarification on items already covered.

---

## Context (read carefully)

**Project:** Mission Control — an agentic orchestration platform under
`/Users/herman.young/development/mission-control`. Backend in Python (FastAPI
+ Temporal + Postgres + Redis), frontend in React/TypeScript. CLI entry
files are at the repo root: `mc.py` (user CLI), `admin.py`, `services.py`,
`tui.py`. Conda env `mission-control` is active; commands run from repo
root unless stated.

**Branch:** `feature/80-advocate-judge` — mis-named historically. The
Advocate-Judge plan it was originally for is discarded (see
`docs/97-plans/80-plan-think-tank-advocate-judge.md` status header).
Recent commits on this branch landed substantial platform infrastructure
(manual gate mode, unified task lifecycle, `mc plan` / `mc gate` /
`mc runs` CLI tooling, async workflow run endpoint). All committed and
clean — `git log --oneline -6` will orient you.

**Your task:** Decompose v1 deliberation's monolithic research step into a
multi-step pipeline whose final output preserves the existing
`ResearchPacket` shape. Then validate v1-with-decomposed-research
against the single-call baseline using the procedure Plan 80 §Phase 8
prescribes. Decide-gate the result and write up findings.

**Why this matters:** v1's `deliberation.researcher.agent` agent is given
one prompt asking for one fat `ResearchPacket` (5 fields, ~50 properties,
deep `$defs`). On contested questions the model refuses ("I cannot
produce a valid…") because the framing is unsolvable (fabricating is
killed by the verifier; refusing crashes the loop). This is the failure
that shelved Plan 79 v2. The fix is structural — decompose the work like
`research.deep-research-pipeline.workflow` already does. The schema-per-
agent becomes small. No refusals.

**What is empirically settled:**

- Single-call Opus 4.6 + extended thinking + web search beat v1 on all
  3 contested test questions in ~5 min each. See
  `docs/98-research/033-Think-Tank-v2-Validation-Findings.md`. That
  baseline lives at `scripts/think_tank_baseline.py`, outputs in
  `var/validation/baseline/`.
- v1's failure was structural (researcher schema), not prompt-tuning.
  **Do not** iterate on `config/prompts/agents/deliberation/researcher/
  system.md` or the verifier's prompt. The fix is decomposition.

**What is open:**

- Whether v1 with the research step fixed beats the baseline. We have
  no data. Your job is to produce that data.

---

## What v1 currently looks like

File: `config/workflow_templates/deliberation.think-tank.v1.workflow.yaml`

Phase 0 of v1 is two steps:

1. `research` (`capability: deliberation.researcher`) — single agent
   producing `ResearchPacket`. **This is the broken step.**
2. `verify-research` (`capability: deliberation.research_verifier`) —
   reads `packet: "@node.research.output"`, returns
   `ResearchPacketVerification` with a `gate` field used by the
   `research-gate` decision node.

Then ~10 downstream steps (4 debaters × 3 rounds + critic + synth +
persistence) all read `@node.research.output` as `research_packet`.
The downstream contract IS the `ResearchPacket` schema. Preserve it.

`ResearchPacket` Pydantic schema lives in
`modules/backend/schemas/deliberation.py`. Read it. It has roughly:

```
{
  question_restated: str
  what_is_known:       list[SourcedClaim]
  expert_disagreements: list[ExpertDisagreement]
  mainstream_consensus: str
  under_discussed_angles: list[UnderDiscussedAngle]
  base_rates:          list[BaseRate]
}
```

(Read the actual schema file for exact field names and validation
rules. Don't guess.)

---

## What the existing research pipeline does

File: `config/workflow_templates/research.deep-research-pipeline.workflow.yaml`

13 steps:

```
decompose (research.strategist)   → list of sub-questions
search-r1 (research.searcher)     → search results per sub-question
analyze-r1 (research.analyst)     → coverage bools + counts
refine + search-r2 + analyze-r2   → iterative refinement
search-r3 + analyze-r3            → final pass
merge-findings                    → join
compress (research.compressor)    → trim
synthesize (research.synthesizer) → final report with citations
verify (research.verifier)        → citation NLI check
notify-complete                   → SSE notification
```

Final structured output (per the YAML) is a "comprehensive research
report with [N] inline citations, executive summary, key findings,
and source bibliography" — the `research.synthesizer` agent's output.
**This shape is NOT `ResearchPacket`.** Mapping is required.

---

## The decision the fresh agent makes

You have three real architectural options. Pick one with justification.

### Option 1 — Sub-workflow + adapter agent

Add a `sub_workflow` step that calls
`research.deep-research-pipeline.workflow`, then add ONE more
`agent_step` after it whose job is "translate the deep-research output
into a `ResearchPacket`." That last step is a small focused task
(reformat already-gathered evidence) — schema is `ResearchPacket`,
but the model isn't being asked to *invent* anything, just reshape.
The original refusal trap is gone because the data is already there.

Trade-offs:
- ✅ Reuses an existing, tested pipeline.
- ✅ The adapter step is a low-creativity task, so refusal risk is
  near zero.
- ❌ Two LLM calls' worth of overhead for the translation
  (deep-research-synthesizer + adapter).
- ❌ Sub-workflows have their own complexity (`sub_workflow_config`
  in the workflow schema, output mapping, error propagation). See
  `workflow_run_waves._execute_sub_workflow_step` for the runtime
  behavior — read this method before designing.

### Option 2 — Inline decomposition

Replace v1's single `research` step with N parallel steps inside the
same YAML:

```
- research.decompose    (research.strategist) → sub-questions
- research.search       (research.searcher)   → results
- research.analyze      (research.analyst)    → coverage
- research.synth-packet (deliberation.researcher) → ResearchPacket
```

The last step is the deliberation.researcher agent, but now it
receives pre-gathered evidence as `@upstream` and only needs to
produce the `ResearchPacket` shape. Its prompt should be rewritten to
"format the evidence I've given you into ResearchPacket" rather than
"go find evidence and produce ResearchPacket."

Trade-offs:
- ✅ All in one workflow YAML, no sub_workflow plumbing.
- ✅ Direct control over which steps run.
- ❌ Duplicates pipeline logic that the research workflow already has.
- ❌ Requires rewriting deliberation.researcher's system prompt — and
  the prompt above explicitly said don't.

### Option 3 — Skip sub-workflow plumbing, use the research workflow's
agents directly inline

Same shape as Option 2 but use research.strategist + research.searcher
+ research.analyst directly as v1 agents (no sub-workflow). The final
step is a NEW small agent (e.g. `deliberation.research_packet_builder`)
whose only job is shape adaptation: turn the deep-research evidence
into `ResearchPacket`.

Trade-offs: same as Option 2 but with a new agent definition. The new
agent is small and focused — its prompt would be "given these search
results, claims, and coverage data, return a `ResearchPacket`." Easy.

### Recommendation (consider, not mandate)

Option 3 is the most maintainable: clean separation, reusable
research-domain agents, and the new `deliberation.research_packet_builder`
isolates the shape concern.

Option 1 is faster to ship if the `sub_workflow` plumbing already works
end-to-end. Test it first before committing to it.

Option 2 is the worst pick — it duplicates work already done in the
research workflow.

---

## Concrete implementation steps

### Step 1 — Verify the substrate works

Before changing any production YAML:

1. Read `modules/backend/services/workflow_run_waves.py:_execute_sub_workflow_step`.
   Understand how it dispatches a child workflow, awaits its result,
   and surfaces outputs. Note any limitations.
2. Run the existing `research.deep-research-pipeline.workflow`
   end-to-end against a known-easy question (e.g. "What are the main
   approaches to renewable energy storage in 2026?") in a throwaway
   mission. Use `--gate autonomous` so it runs unattended. Confirm
   it produces a research report with citations.
3. If step 2 fails, fix the failure before proceeding. Document what
   was broken; this is its own deliverable.

### Step 2 — Pick the option, write the design

In one ~50-line markdown block, document:

- Which option (1/2/3) you picked and why
- Schema mapping table: `deep-research-pipeline output field` → `ResearchPacket field`
- Any new agent definitions (YAML + system prompt + Python module —
  follow the 4-file blueprint at `docs/02-architecture/003-agent-blueprint.md`
  if it exists)
- Any new schemas

Commit this design doc at `docs/97-plans/81a-design-v1-research-decomposition.md`
before writing code.

### Step 3 — Implement

Whatever option you picked. Hard constraints:

- **DO NOT** modify the v1 YAML's downstream steps (verifier, debaters,
  critic, synth, persistence). Their contract — read `ResearchPacket`
  from `@node.research.output` — must hold.
- **DO NOT** change `ResearchPacket` schema in `deliberation.py`.
- **DO NOT** modify `deliberation.researcher`'s system prompt. The
  failure is architectural.
- If you create new agents, they get the 4-file treatment: agent.yaml
  in `config/agents/<domain>/<name>/`, system.md in
  `config/prompts/agents/<domain>/<name>/`, `agent.py` in
  `modules/backend/agents/<domain>/<name>/`, and a roster entry. Be
  consistent with existing patterns under
  `modules/backend/agents/research/` or `modules/backend/agents/deliberation/`.

### Step 4 — Smoke test

Use the platform's manual-gate walkthrough infrastructure (already
built on this branch — don't reinvent):

```
mc.py mission create --name v1-research-decomp-test \
    --description "Smoke test for Plan 81" --budget 100
mc.py mission use --name v1-research-decomp-test
mc.py team add  # add all 8 v1 deliberation agents
                # (research.strategist, research.searcher,
                # research.analyst, deliberation.researcher,
                # deliberation.research_verifier, 4 debaters,
                # deliberation.critic, deliberation.synthesiser,
                # plus any new agents you defined)
mc.py gate set manual
mc.py run -o deliberation.think-tank.v1.workflow \
    --gate manual \
    -c "question=What will agentic AI do to UK knowledge-work employment by 2030?"
```

The workflow returns immediately in interactive modes (Plan 80h —
async). Walk through gates one at a time:

```
mc.py plan show --status proposed       # see what's ready
mc.py plan approve --next               # approve the next ready task
mc.py plan task <id>                    # inspect when something failed
mc.py plan reject --all                 # nuke and start over
mc.py runs                              # see active workflow runs
mc.py runs cancel <id>                  # clean up stale RUNNING orphans
```

If a step fails:

1. `mc.py plan task <full-uuid>` shows the failure_reason. Read it.
2. `scripts/trace_execution.py -e <execution_record_id>` gives the
   full timeline including SSE events, tool calls, errors.
3. If the failure is in a research-pipeline step, you're debugging the
   sub-pipeline. If it's in `deliberation.research_verifier`, the
   issue is shape mismatch — your translation layer isn't producing
   valid `ResearchPacket`. Fix and retry.

**Don't restart the backend manually.** Tell the user (or whoever
launched the agent) and ask them to restart. Uvicorn runs with
`--reload` which auto-restarts on backend file edits and kills
in-flight gates — be mindful of edit timing when a workflow is mid-run.

### Step 5 — End-to-end validation

Once the workflow completes end-to-end on the smoke question
(researcher → verifier → 12 debater turns + 4 critic rounds →
synthesiser + 4 persistence tool_calls):

1. Run the full v1-with-decomposed-research against all 3 validation
   questions (Q1, Q2, Q3 — see Plan 80 §Phase 8 or the validation
   findings doc for the exact wording). Outputs go to
   `var/validation/v1_decomposed/`.
2. Use `scripts/think_tank_anonymise.py` to blind-pair v1-decomposed
   outputs with the baseline outputs already in
   `var/validation/baseline/`. The script may need a small flag
   addition to pick up `v1_decomposed` as a third comparator — read
   it first.
3. Read both blind-paired outputs per question and score them on the
   3 Plan-80-§Phase-8 dimensions:
   - **Preserves disagreement:** does the deliverable surface live
     expert disagreement, or does it collapse to one view?
   - **Cruxes are real:** are the deliverable's named "cruxes" actual
     points where reasonable observers diverge, or are they restated
     positions?
   - **Minority has substance:** is `minority_position` a defensible
     alternative or a token contrarian?

### Step 6 — Decision gate (mechanical)

Write findings at `docs/98-research/034-v1-decomposed-research-validation-findings.md`.
Include:

- The 3 anonymised paired outputs per question (or links to them).
- Your score per dimension.
- The unmasked attribution.

**If v1-decomposed beats baseline on ≥2/3 questions × ≥2/3 dimensions:**
ship v1-decomposed.

1. Rename v1's workflow YAML from
   `deliberation.think-tank.v1.workflow.yaml` to
   `deliberation.think-tank.workflow.yaml` (the canonical slot is
   currently empty — see commit `452a024`).
2. Update `workflow_name` inside to drop `.v1` infix.
3. Re-seed: `python admin.py admin seed-workflows --force`.
4. Verify in DB: `SELECT name FROM workflow_definitions WHERE name
   LIKE 'deliberation.think-tank%';` — should show the new canonical
   name and the v1 row gone.
5. Update `MEMORY.md` and `project_think_tank_validation.md` (under
   `/Users/herman.young/.claude/projects/.../memory/`) to reflect
   that v1-with-decomposed-research is shipped.
6. Close `feature/80-advocate-judge` by merging to main with a final
   commit summarising what shipped vs what was discarded.

**If v1-decomposed loses on ≥2/3 questions:**

1. Document the specific failure modes in the findings doc.
2. **Do not** proceed to "ship Plan 80 v3" without explicit user
   sign-off. The empirical evidence that motivated Plan 80
   (Khan et al. on adversarial debate, Hu & Collier on persona
   prompting) is still valid, but the user discarded Plan 80 v3 for
   cost reasons (~5 days + multi-provider + new schemas). Surface the
   data and let them decide.

### Step 7 — Commit hygiene

One commit per logical step:

- `Plan 81 design: pick option N for v1 research decomposition`
- `Plan 81 impl: research-domain agents wired into v1 workflow`
  (or whatever shape your impl takes)
- `Plan 81 validation: A/B v1-decomposed vs single-call baseline`
- `Plan 81 ship/no-ship: <outcome>`

Use HEREDOC for multi-line commit messages (per project convention).
Always include the Co-Authored-By trailer.

---

## Tools you have

These were built on this branch — use them; do not reinvent or fall
back to direct psql when an `mc.py` command exists:

- `mc.py plan show [--status X] [--deps]` — Kanban-style task list
- `mc.py plan task <full-uuid>` — single-task detail with
  failure_reason, instructions, dependencies
- `mc.py plan approve <id|--next>` — flip PROPOSED → APPROVED
- `mc.py plan reject <id|--all>` — cancel one or all non-terminal
- `mc.py plan retry <id>` — flip FAILED → APPROVED
- `mc.py plan dispatch` — start a Temporal run for APPROVED tasks
- `mc.py gate` — current gate mode + pending post-execution gates
- `mc.py gate set <mode>` — change gate mode for current mission
- `mc.py gate modes` — list available modes
- `mc.py gate pending` — pending post-execution gates only (rare)
- `mc.py gate decide <id> <action>` — decide post-execution gate
- `mc.py runs` — list active workflow runs
- `mc.py runs cancel <id>` — mark stale RUNNING orphan as CANCELLED
- `mc.py runs show <id>` — workflow run detail
- `mc.py tree` — see every command (use this when in doubt)
- `scripts/trace_execution.py -e <id>` — full timeline including SSE
  events, tool calls, errors. Use this when a step fails.

If a feature is missing, **build it.** Don't fall back to psql or
direct SQL for things that should be CLI commands. Existing tooling
proves the pattern: a new endpoint + a function in `modules/clients/
cli/mc_*.py` + a `@plan.command` (or wherever) in `mc.py`. The user
has confirmed: "use mc.py as much as possible — if a feature is
missing, we build it."

---

## Constraints / conventions

Read once, don't violate:

- **Fail fast, fail loud.** No silent fallbacks, no hardcoded defaults.
  If a config value is missing, raise. (See `feedback_no_silent_fallbacks`
  in memory.)
- **Thin clients.** CLI / TUI / web frontend are thin HTTP. Business
  logic in backend service layer. (See `feedback_thin_clients`.)
- **API envelope.** All endpoints return `ApiResponse`. Frontend
  unwraps via `json.data`. (See `feedback_api_envelope`.)
- **Status enum case.** `SQLAlchemy Enum(native_enum=False)` stores
  by NAME (uppercase). When writing status strings directly to the
  DB, use uppercase: `'COMPLETED'`, not `'completed'`.
  (See `feedback_enum_status_uppercase`.)
- **No PRs.** This project pushes to `main` directly. Don't propose
  `gh pr create`. (See `feedback_no_prs`.)
- **DateTime columns** use `DateTime(timezone=True)`. Pass
  `utc_now()` directly; never `.isoformat()` strings.
- **P17 — Tools over structured output for complex schemas.** If you
  ever find yourself making an agent produce a multi-KB monolithic
  JSON blob, you've taken the wrong turn. This is the root cause of
  v1's researcher failure.
- **No agent self-evaluation (P13).** The agent that produces output
  must not be the same agent that evaluates it. The verifier-after-
  researcher pattern is correct; don't collapse them.
- **File size.** Keep files under 1000 lines, aim for ~500.
- **Test against real infrastructure (P12).** Don't mock the DB.
  Tests run against real Postgres / real Redis. Only LLM calls are
  mocked via PydanticAI `TestModel`.
- **No LLMs in CI (P11).** Use `TestModel(call_tools=[...])` for
  agent tests. Real LLM calls only happen against a live dev mission.

---

## Definition of done

This task is done when ALL of the following are true:

1. `docs/97-plans/81a-design-v1-research-decomposition.md` exists with
   the chosen-option rationale.
2. The implementation is committed (one or more clean commits with
   sensible messages).
3. The v1 workflow runs end-to-end on at least one contested question
   without the researcher refusing — verified via the `mc.py plan
   approve --next` step-through.
4. The 3-question A/B validation has been run; results saved to
   `var/validation/v1_decomposed/`.
5. The validation findings doc exists at
   `docs/98-research/034-v1-decomposed-research-validation-findings.md`
   with anonymised blind-paired scoring and decision-gate outcome.
6. The ship-or-don't decision has been made and acted on per Step 6.
7. `MEMORY.md` and the relevant project memory file are updated.
8. Working tree is clean. `git log --oneline -10` tells a coherent
   story.

---

## What NOT to do

- Don't iterate on `deliberation.researcher`'s system prompt.
- Don't re-introduce Plan 80 v3 (Advocate-Judge) without explicit
  user sign-off. It is discarded by deliberate decision; the dead
  code was deleted in commit `fc29b04`.
- Don't break the v1 workflow's downstream contract (verifier +
  debaters + critic + synth all read `@node.research.output` as
  `ResearchPacket`).
- Don't change `ResearchPacket` schema.
- Don't add a new dispatch pattern (e.g. another `*_loop.py`
  executor). The user's directive earlier in this branch was clear:
  workflow steps belong in the DAG, not hidden in Python loops.
- Don't commit broken code. The pre-commit hook (codemap quality
  report) will warn but not block — that's intentional, but it's
  not permission to commit broken state.

---

## Final sanity check before you start

Run these to orient:

```
git -C /Users/herman.young/development/mission-control status
git -C /Users/herman.young/development/mission-control log --oneline -10
python /Users/herman.young/development/mission-control/mc.py tree
cat /Users/herman.young/development/mission-control/TODO.md
```

If anything in the recent log surprises you, stop and ask.

Begin.
