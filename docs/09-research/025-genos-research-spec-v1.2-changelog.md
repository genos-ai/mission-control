# Spec v1.1 → v1.2 Changelog: Adversarial Review Fixes

14 findings, 14 fixes. This document maps each adversarial finding to its implementation in v1.2.

---

## Finding #1: No security model

**Severity:** Critical
**Fix location:** New Section 2.7 "Security Boundaries", additions to Section 1.4 (`query_blocked_patterns`, `query_max_length`), Section 2.3 (route handler sanitisation)

**What changed:**
- Added `config.query_blocked_patterns` with 5 default prompt injection substrings, checked case-insensitively in the route handler before task creation.
- Added `config.query_max_length` (default 2000).
- Section 2.7.1: Secret management table specifying `.env` for dev, secrets manager for staging/prod.
- Section 2.7.2: Input sanitisation rules. User query goes to LLM prompts via PydanticAI's separated `system_prompt` / `run()` argument, not concatenated.
- Section 2.7.3: All Cypher queries must go through `AGEClient`. No raw Cypher string construction outside `age_client.py`.
- Section 2.7.4: Data isolation statement. Single-graph model acknowledged; multi-tenant isolation flagged as out of scope.
- Added invariant SEC-01 (blocked patterns) and SEC-02 (no Cypher string interpolation).

---

## Finding #2: `execute_cypher` referenced but never defined

**Severity:** High
**Fix location:** New Section 3.8 "AGE Client Specification"

**What changed:**
- Full `AGEClient` class specification with `execute()` and `execute_batch()` methods.
- `execute()`: parameterised Cypher via `SET` statements + asyncpg `$N` SQL parameter binding. User values never appear in Cypher strings.
- `execute_batch()`: runs multiple operations sequentially within a single connection acquisition. Individual failures logged, not batch-aborting.
- Anti-patterns section (3.8.1) prohibits Cypher construction outside `AGEClient`.
- Note that the parameterisation pattern is a specification of intent; production implementation must be verified against the deployed AGE version.

---

## Finding #3: Graph write-back performance

**Severity:** High
**Fix location:** Rewritten Section 3.7.3, new `GraphWritebackJob` model in Section 4.3, Section 7.1/7.2 (NATS graph stream)

**What changed:**
- Write-back is now genuinely backgrounded via NATS. Orchestrator publishes a `GraphWritebackJob` to `research.graph.writeback` subject after report persistence.
- Dedicated graph writer worker (Process C in architecture diagram) consumes these jobs.
- Cypher operations batched: all sources in one batch, claims in batches of 10, entities per claim. Reduces round-trips from ~54 to ~8-12 per report.
- `_build_source_batch_cypher()` and `_build_claim_batch_cypher()` return lists of `{"cypher": str, "params": dict}` for `AGEClient.execute_batch()`.
- New `GRAPH_STREAM` JStream added to Section 7.1 with `WORK_QUEUE` retention.
- New graph writer subscriber in Section 7.2.

---

## Finding #4: Entity extraction dependency undeclared

**Severity:** High
**Fix location:** Section 1.2 (requirements.txt), Section 1.3 (post-install step), new `src/graph/ner.py` in Section 3.7.2

**What changed:**
- `spacy>=3.8.0` added to requirements.txt.
- `python -m spacy download en_core_web_sm` added as post-install step.
- spaCy added to technology decision matrix (Section 1.1) with version and role.
- `extract_entities_from_text()` fully defined: signature `async def extract_entities_from_text(text: str) -> list[tuple[str, str, float]]`, spaCy pipeline with disabled components, entity type mapping, fixed confidence of 0.85.
- `src/graph/ner.py` added to directory structure (Section 2.4).

---

## Finding #5: SynthesisStrategy enum case sensitivity

**Severity:** Medium
**Fix location:** Section 4.3 (`SynthesisStrategy` class), Section 5.1 (planner prompt)

**What changed:**
- Added `_missing_()` classmethod to `SynthesisStrategy` that normalises case (lowercase, stripped) before lookup. Handles LLM outputs like `"Comparative"`, `"THEMATIC"`, `" chronological "`.
- Planner prompt updated with explicit instruction: "The `synthesis_strategy` field must be exactly one of these lowercase values: comparative, chronological, thematic, hierarchical, argumentative."
- Added invariant P-05 testing case normalisation.

---

## Finding #6: SSE progress tracking race condition

**Severity:** High
**Fix location:** Section 7.4 (completely rewritten), Section 7.1 (new `PROGRESS_STREAM`)

**What changed:**
- SSE endpoint now subscribes to NATS `research.progress.{task_id}` subject instead of using a process-local `asyncio.Queue`.
- New `PROGRESS_STREAM` JStream in Section 7.1 with `LIMITS` retention (7 days).
- SSE handler creates a NATS subscription, relays messages to the client, and unsubscribes on disconnect.
- Heartbeat mechanism preserved (sends empty heartbeat event on timeout).
- This decouples the SSE handler from the orchestrator process, supporting multi-worker deployments.
- Anti-pattern added: "Do not use process-local queues for SSE progress relay."

---

## Finding #7: `depends_on` uses fragile integer indices

**Severity:** Medium
**Fix location:** Section 4.3 (`SubQuestion`, `SubAgentFindings`, `ResearchPlan`), Section 5.1 (planner prompt), Section 6.2 (orchestrator)

**What changed:**
- `SubQuestion.depends_on` changed from `list[int] | None` to `list[str]` (default empty list).
- New `SubQuestion.question_id` field: `str = Field(max_length=20)`, format `"sq_0"`, `"sq_1"`, etc.
- New `SubAgentFindings.question_id` field matching the plan's question_id.
- `ResearchPlan` now has a `@field_validator("sub_questions")` that validates all `depends_on` references exist and checks for cycles.
- Planner prompt updated with explicit instructions: "Assign each sub-question a unique `question_id` using the format 'sq_0', 'sq_1', 'sq_2', etc. These are string identifiers, not array indices."
- Orchestrator `all_findings` changed from `dict[int, SubAgentFindings]` to `dict[str, SubAgentFindings]` keyed by `question_id`.
- Invariant P-03 updated to reference `question_id` values instead of integer indices.

---

## Finding #8: Token budgets conflate input and output

**Severity:** High
**Fix location:** Section 1.4 (AppConfig token budget defaults)

**What changed:**
- `token_budget_planner`: 2000 → 4000. Rationale: planner has no tools but large queries with structured output need headroom.
- `token_budget_per_sub_agent`: 4000 → 12000. Rationale: a single Tavily search with `include_raw_content=True` can consume 2000+ input tokens. 3-5 searches + structured output needs ~12000 total.
- `token_budget_synthesis`: 8000 → 16000. Rationale: input includes all sub-agent findings (~8000 tokens for 5 findings) plus output (~4000 tokens for a 3000-word report).
- Added comments explaining the input/output composition for each budget.
- Noted that `total_tokens_limit` counts both input and output. Future improvement: split into separate limits if PydanticAI supports it.

---

## Finding #9: `expected_output_length` disconnected from everything

**Severity:** Medium
**Fix location:** New Section 6.2.1 "Depth-to-Config Mapping", Section 1.4 (depth-specific config params), Section 6.2 (orchestrator)

**What changed:**
- New `get_depth_overrides()` function in `src/orchestrator/depth_config.py` that maps depth to `max_sub_agents`, `token_budget_synthesis`, and `enable_gap_analysis`.
- Six new AppConfig parameters: `depth_brief_max_sub_agents` (3), `depth_brief_token_budget_synthesis` (6000), `depth_standard_max_sub_agents` (5), `depth_standard_token_budget_synthesis` (12000), `depth_comprehensive_max_sub_agents` (7), `depth_comprehensive_token_budget_synthesis` (16000).
- Brief depth disables gap analysis unconditionally.
- Orchestrator now receives `depth` as a parameter and applies overrides before planning.
- Planner prompt updated: "The number of sub-questions depends on the requested depth: brief: 2-3, standard: 3-5, comprehensive: 5-7."
- Orchestrator caps `plan.sub_questions` to `effective_max_sub_agents` after planning (in case planner produces more than requested).

---

## Finding #10: Tavily `include_raw_content` parameter wrong

**Severity:** Critical
**Fix location:** Section 5.3 (search tool)

**What changed:**
- `include_raw_content="markdown"` → `include_raw_content=True`
- Comment added: `# v1.2 fix: boolean, not string`

One-line fix. High impact: the old value was a truthy string that might have worked accidentally (Python treats non-empty strings as truthy) but was not the intended API usage and could break with SDK updates.

---

## Finding #11: NLI label ordering assumption

**Severity:** Critical
**Fix location:** Section 8.1 (`NLICitationVerifier.__init__`)

**What changed:**
- Renamed `LABEL_MAPPING` to `EXPECTED_LABELS` with explicit index-to-label mapping: `{0: "contradiction", 1: "entailment", 2: "neutral"}`.
- New `_validate_label_ordering()` method called during `__init__` that loads the model's `config.id2label` and verifies each index matches the expected label.
- Raises `RuntimeError` at startup if labels don't match, rather than silently misclassifying at runtime.
- Falls back to a warning log if the model config is not available (some model formats don't expose `id2label`).
- Added to test matrix: unit test that the verifier raises `RuntimeError` with a mismatched model.

---

## Finding #12: Out-of-scope operational debt

**Severity:** Low
**Fix location:** Section 1.4 (AppConfig), Section 6.2 (orchestrator), Section 12.0 (out of scope)

**What changed:**
- New `config.cost_alert_threshold_usd` (default $5.00): logs a warning when a single task's estimated cost exceeds this.
- New `config.cost_pricing_input_per_mtok` and `config.cost_pricing_output_per_mtok`: per-model pricing lookup tables for cost estimation.
- Orchestrator Phase 5 now calls `_estimate_cost()` and logs a warning if threshold exceeded.
- New `config.graph_edge_retention_days` (default 365): defines the retention boundary for expired bi-temporal edges. Compaction logic itself is still out of scope but the parameter exists.
- Section 12.0 updated to acknowledge cost alerting is implemented while full cost optimisation remains future work.

---

## Finding #13: Architecture contradiction (orchestrator-managed vs. distributed sub-agents)

**Severity:** Critical
**Fix location:** Sections 2.1, 2.2, 7.0, 7.1, 7.2, 7.3, Summary

**What changed:**
- **Decision: orchestrator-managed model.** Sub-agents run in-process via `asyncio.gather`. NATS distributes research *tasks* across orchestrator instances, not individual sub-questions.
- Architecture diagram (Section 2.1) rewritten to show three processes: API server (A), orchestrator worker (B), graph writer (C).
- Summary paragraph updated: removed "20+ concurrent workers" language.
- NATS subjects simplified: `research.task` (singular, not `research.task.search.*`), `research.progress.{id}`, `research.graph.writeback`.
- NATS flow control updated: `batch_size` reduced to 1 (each task is expensive), `MaxAckPending` reduced to 50, `AckWait` increased to 600s (must exceed total research timeout).
- Removed all references to "20+ worker instances pulling tasks" for sub-agents.
- Added explicit "Why orchestrator-managed" rationale: sub-agents need shared state, dependency ordering, and gap analysis that are simpler in-process.
- Anti-pattern added: "Do not distribute sub-agent tasks via NATS."
- Technology decision matrix updated: NATS role clarified as "Task-level queuing, progress distribution, graph write-back queue."

---

## Finding #14: No spec versioning/governance strategy

**Severity:** Medium
**Fix location:** New Section 0.1 "Specification Governance"

**What changed:**
- Spec lives at `docs/SPEC.md` in the git repository.
- Spec changes require PR review.
- Any PR modifying behaviour must include a spec update in the same PR.
- CI step validates invariant coverage: every invariant ID must have a test annotated with `@pytest.mark.invariant("ID")`.
- CI step validates Pydantic model sync: models serialised to JSON Schema and diffed against spec.
- `test_spec_compliance.py` added to directory structure.

---

## Summary of all affected files

| File | Finding(s) | Change Type |
|---|---|---|
| `docs/SPEC.md` | All | This specification document |
| `src/config.py` | #1, #8, #9, #12 | New config params: blocked patterns, token budgets, depth overrides, cost alerting, graph retention |
| `src/api/routes.py` | #1, #6 | Query sanitisation; SSE via NATS subscription |
| `src/api/schemas.py` | #1 | `@field_validator` on query field |
| `src/agents/models.py` | #3, #5, #7 | `GraphWritebackJob`, `SynthesisStrategy._missing_()`, `question_id` fields, `depends_on` to `list[str]`, `ResearchPlan` dependency validator |
| `src/agents/planner.py` | #7, #9 | Prompt updated for question_id format and depth calibration |
| `src/graph/age_client.py` | #2 | New file. `AGEClient` class with parameterised Cypher execution |
| `src/graph/ner.py` | #4 | New file. `extract_entities_from_text()` using spaCy |
| `src/graph/writeback.py` | #3 | Rewritten. Batched operations, NATS-backgrounded, `process_graph_writeback()` |
| `src/orchestrator/coordinator.py` | #7, #8, #9, #12, #13 | question_id-based deps, depth overrides, cost alerting, NATS graph publish |
| `src/orchestrator/depth_config.py` | #9 | New file. `get_depth_overrides()` |
| `src/tools/search.py` | #10 | `include_raw_content=True` (was `"markdown"`) |
| `src/verification/nli_verifier.py` | #11 | `_validate_label_ordering()` startup assertion |
| `src/streaming/nats_config.py` | #6, #13 | New `PROGRESS_STREAM` and `GRAPH_STREAM`; simplified subjects |
| `src/streaming/subscribers.py` | #3, #13 | Graph writer subscriber; orchestrator subscriber simplified |
| `src/errors/taxonomy.py` | — | No changes |
| `tests/test_spec_compliance.py` | #14 | New file. Invariant coverage check |
| `requirements.txt` | #4 | `spacy>=3.8.0` added |
