# 81a — Design: v1 Research Decomposition

*Status:* design, pre-implementation
*Plan:* 81 (see `81-prompt-v1-research-decomposition.md`)
*Date:* 2026-05-26

---

## Decision

**Option 3 — inline research-domain agents + new packet builder.**

v1's broken Phase 0 (one `research` step doing too much) is replaced by
three steps. Step IDs and downstream contract preserved.

```
research-decompose  →  research-gather  →  research  →  verify-research → research-gate
   strategist           evidence_gatherer     packet_builder    unchanged          unchanged
```

The third step keeps the ID `research` so `@node.research.output`
references in the ~10 downstream steps still resolve. Its
**capability** is repointed from `deliberation.researcher` to
`deliberation.research_packet_builder`. The old
`deliberation.researcher.agent` stays in the codebase but is no
longer used by v1 (cleanup later).

### Why not Option 1 (sub-workflow)

Substrate constraint, confirmed by reading
`modules/backend/services/workflow_run_waves.py:_execute_sub_workflow_step`
(lines 1164-1229) and the `run.result_summary` write in
`workflow_run.py:301`:

- A `sub_workflow` step surfaces only
  `{child_run_id, status, result_summary, total_cost_usd}` to the
  parent. The child workflow's per-step outputs (e.g. the deep-research
  synthesizer's report) are NOT addressable via `@node.X.output` in
  the parent.
- `result_summary` is hard-coded to
  `"Workflow completed: {N} steps, ${cost}"` — a stats string with no
  payload.
- An adapter agent reading `result_summary` cannot reach the actual
  research report. Option 1 would require a new
  `fetch_workflow_output(child_run_id, step_id)` tool that queries
  the DB for the child run's execution records and extracts a
  specific step's output. That is substantial new infrastructure for
  a path the user's earlier commit message suggested but did not
  validate against the substrate.

Option 3 sidesteps this entirely: regular `agent_step` outputs are
already plumbed through `@node.X.output` via the existing
output-extraction flow.

### Why not Option 2

Option 2 would rewrite `deliberation.researcher`'s system prompt. The
plan explicitly forbids that — and the prompt is fine for an adapter-
style task; the failure is the framing it's asked to operate under,
not the prompt's text.

---

## What the decomposition fixes

v1's current `research` step asks one agent to:
1. Search the web for the question (contested, open).
2. Produce ≥3 sourced claims, 2-5 expert disagreements, mainstream
   consensus, 3-5 under-discussed angles, base rates.
3. Submit to a verifier that rejects vague sources or
   "I couldn't confirm…" admissions.

On contested questions the model refuses ("I cannot produce a
valid…") because the task is unsolvable in one cognitive pass
without fabricating, and the verifier kills fabrication.

The fix is to separate **gather** from **shape**:

- **`research-decompose`** — strategist breaks the question into
  3-7 sub-questions. Cheap. No schema pressure on the cited claims
  yet.
- **`research-gather`** — gatherer agent searches each sub-question
  with web tools, dumps a flat list of sourced findings. Wide cast,
  shallow schema. No "produce 2-5 expert disagreements" pressure.
- **`research`** — packet builder takes the corpus and reshapes into
  the existing `ResearchPacket`. The model's job is reformatting
  pre-gathered evidence — a low-creativity, low-refusal task.

---

## Schema mapping table

The gather step's output (`EvidenceCorpus`) feeds the packet
builder. The packet builder produces `ResearchPacket` (unchanged
schema). Mapping below.

| `EvidenceCorpus` field            | Source in builder logic                                          | `ResearchPacket` field          |
|-----------------------------------|------------------------------------------------------------------|---------------------------------|
| `findings: list[SourcedFinding]`  | direct one-to-one for HIGH/MED confidence items                  | `what_is_known: list[SourcedClaim]` (≥3) |
| `findings` with contradictions    | builder pairs contradicting findings, names camps                | `expert_disagreements` (2-5)    |
| `findings` aggregated             | builder writes 2-3 sentences naming the most-cited mainstream view | `mainstream_consensus`        |
| `gaps: list[str]` (from gatherer) | builder identifies framings absent from the corpus               | `under_discussed_angles` (3-5)  |
| `numeric_claims: list[str]`       | builder extracts quantitative figures with reference classes     | `base_rates: list[str]`         |
| —                                 | builder restates the question (passthrough)                      | `question_restated`             |

If the corpus is too thin to satisfy a `ResearchPacket` minimum
(e.g. fewer than 3 sourced findings), the packet builder still has
search tools and may fill gaps before emitting. This is the
escape hatch; in practice the gather step should make it
unnecessary on most runs.

---

## New schema: `EvidenceCorpus`

Add to `modules/backend/schemas/deliberation.py` (same file as
`ResearchPacket` — they're co-domain).

```python
class SourcedFinding(BaseModel):
    """A single finding from the gather step. Less structured than
    SourcedClaim — gather is wide-cast, shaping happens later."""

    model_config = ConfigDict(extra="forbid")

    sub_question_id: str = Field(..., min_length=1, max_length=50)
    claim: str = Field(..., min_length=1, max_length=1000)
    evidence: str = Field(..., min_length=1, max_length=2000)
    source_url: str = Field(..., min_length=1, max_length=500)
    source_title: str = Field("", max_length=500)
    confidence: Literal["HIGH", "MEDIUM", "LOW"]


class EvidenceCorpus(BaseModel):
    """Output of deliberation.evidence_gatherer.agent.

    Pre-gathered, lightly structured evidence the packet builder
    will reshape into a ResearchPacket. Intentionally permissive
    (no min_length on findings) so the gatherer can return partial
    results rather than refusing.
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
```

---

## New agents

### Agent 1: `deliberation.evidence_gatherer.agent`

**Job:** given a question + sub-questions, search the web for each,
return a flat `EvidenceCorpus`.

**Files:**

```
config/agents/deliberation/evidence_gatherer/agent.yaml
config/prompts/agents/deliberation/evidence_gatherer/system.md
modules/backend/agents/deliberation/evidence_gatherer/__init__.py
modules/backend/agents/deliberation/evidence_gatherer/agent.py
```

**Key YAML config:**

- `model`: `copilot:claude-sonnet-4.6` (same family as researcher; gather
  is recall-bounded, doesn't need Opus reasoning)
- `tools`: `search_web`, `fetch_url`, `query_knowledge`
- `max_budget_usd`: `4.00`
- `interface.input`: `question: string`, `sub_questions: list`
- `interface.output`: `findings: list`, `numeric_claims: list`,
  `gaps: list`, `notes: string`
- `output_type`: `EvidenceCorpus`
- `deps_type`: `ResearchAgentDeps` (needs httpx for fetch_url)

**System prompt sketch:** "You have N sub-questions. For each:
search the web (search_web), pick the most relevant 1-3 results,
optionally extract full content (fetch_url) when snippets are
thin, capture one finding per useful source. Don't synthesise.
Don't take positions. If you can't find sources for a
sub-question, list it under `gaps` and move on — partial output
is fine. UK English, no em dashes."

### Agent 2: `deliberation.research_packet_builder.agent`

**Job:** given the question, sub-questions, and an `EvidenceCorpus`,
produce a `ResearchPacket`.

**Files:**

```
config/agents/deliberation/research_packet_builder/agent.yaml
config/prompts/agents/deliberation/research_packet_builder/system.md
modules/backend/agents/deliberation/research_packet_builder/__init__.py
modules/backend/agents/deliberation/research_packet_builder/agent.py
```

**Key YAML config:**

- `model`: `copilot:claude-opus-4.6` (shape decisions benefit from
  Opus reasoning; cost stays low because input is pre-gathered)
- `tools`: `search_web`, `fetch_url`, `query_knowledge` (gap-fill
  only; prompt discourages)
- `max_budget_usd`: `3.00`
- `output_type`: `ResearchPacket` (existing schema, no change)
- `deps_type`: `ResearchAgentDeps`

**System prompt sketch:** "You have a pre-gathered EvidenceCorpus
addressing N sub-questions. Reshape it into a `ResearchPacket`.
Most of your output should come from the corpus's findings, not
fresh searches. Pair contradicting findings as
`expert_disagreements`. The most-cited consensus view is
`mainstream_consensus`. Use the corpus's `gaps` as candidates for
`under_discussed_angles` — but only include angles that are
genuinely under-discussed, not just absent from this corpus. Honest
restatement of `question_restated`. UK English, no em dashes. Tool
use is permitted ONLY for gap-filling when the corpus is
insufficient to satisfy schema minima; prefer to use what's there."

---

## Workflow YAML changes

Edits to
`config/workflow_templates/deliberation.think-tank.v1.workflow.yaml`:

### New steps

```yaml
- id: research-decompose
  label: "Decompose research question"
  description: "Break the contested question into 3-7 focused sub-questions"
  capability: research.strategist
  roster: default
  complexity_tier: simple
  cost_ceiling_usd: 1.00
  input:
    query: "@context.question"
  timeout_seconds: 300
  depends_on: []

- id: research-gather
  label: "Gather evidence"
  description: "Search the web for each sub-question; produce a flat sourced corpus"
  capability: deliberation.evidence_gatherer
  roster: default
  complexity_tier: complex
  cost_ceiling_usd: 4.00
  input:
    question: "@context.question"
    sub_questions: "@node.research-decompose.output.sub_questions"
  timeout_seconds: 1800
  depends_on:
    - research-decompose
```

### Modified step (capability change only)

```yaml
- id: research
  label: "Build research packet"
  description: "Reshape the pre-gathered evidence corpus into a ResearchPacket"
  capability: deliberation.research_packet_builder   # was: deliberation.researcher
  roster: default
  complexity_tier: complex
  cost_ceiling_usd: 3.00
  input:
    question: "@context.question"
    sub_questions: "@node.research-decompose.output.sub_questions"
    evidence_corpus: "@node.research-gather.output"
  timeout_seconds: 1800
  depends_on:
    - research-gather                                  # was: []
```

### New edges (added to `edges:` block)

```yaml
- {source: research-decompose, target: research-gather}
- {source: research-gather,    target: research}
```

Everything from `research → verify-research → research-gate → ...`
downstream is untouched. Step ID `research` remains; only its
capability and dependencies change.

### Budget bump

Phase 0 cost ceiling rises by ~$3 (decompose $1 + gather $4 +
builder $3 = $8, versus $5 for the old researcher). Update
`budget.max_cost_usd` from `350.00` → `355.00`. Worst-case sum
recomputed in the YAML comment.

---

## Roster / catalog update

Per memory note `pattern_agent_catalog`: DB is authoritative, YAML
is seed-only. After the 4-file YAML/prompt/Python work for each
new agent:

```bash
python admin.py admin seed-catalog --force
```

Then for the test mission:

```bash
mc.py team add deliberation.evidence_gatherer
mc.py team add deliberation.research_packet_builder
mc.py team add research.strategist
# (plus the existing 8 deliberation agents)
```

---

## Tests

Per project P11 (no LLMs in CI) and P12 (real infrastructure):

- Unit test the `EvidenceCorpus` Pydantic schema (validates min/max
  lengths, `extra=forbid` rejection).
- Unit test each new agent with PydanticAI `TestModel(call_tools=[])`
  driving the agent to return a fixture-shaped output; assert the
  output validates and the schema parses.
- No new e2e test infrastructure — the smoke test in Plan 81 Step 4
  is the integration test, run live against the dev mission.

---

## Deviation from the prompt's Step 1

Plan 81's Step 1.2 says to run the full
`research.deep-research-pipeline.workflow` end-to-end as a substrate
check. That was scoped for Option 1 (where we'd be invoking the
deep-research pipeline as a sub-workflow). Option 3 uses only
`research.strategist` from that pipeline; the full deep-research
substrate is out of scope.

The `research.strategist` agent is validated naturally by the Step 4
smoke test on the real workflow on the real question. Saves ~$5-10
of LLM time and ~10 minutes of agent walk-through on a probe that
does not change the design or catch a failure earlier.

---

## Definition of done for this design doc

- [x] Option chosen with substrate-grounded rationale
- [x] Schema mapping table specified
- [x] New agent files enumerated
- [x] New schema specified
- [x] Workflow YAML diff specified
- [x] Roster/catalog reseed step specified
- [x] Deviation from prompt called out

Implementation begins at Plan 81 Step 3.
