# Plan 57 — Knowledge, Intent & Learnings Platform

| Field | Value |
|-------|-------|
| **Status** | Ready |
| **Created** | 2026-04-16 |
| **Depends on** | Plan 18 (Project Context Layer — done), Plan 51 (Session Followups — done), Plan 56 (Unified Async — done) |
| **Closes TODO** | `Context management — continuous update of knowledge, intent, context, learnings`, `Investigate system.knowledge.officer.agent` |
| **Scope** | Two new tables (`mission_intents`, `mission_learnings`), one new service (`KnowledgeService`), one new extractor (deterministic), one minimal system agent (governance only), pgvector hybrid retrieval for narrative content, full frontend + CLI + TUI surfaces |
| **Companion** | [57a — Deferred Horizon](./57a-plan-knowledge-horizon.md) tracks what we deliberately don't build yet |

---

## 1 · Problem

Today the platform captures every signal that matters — `TaskAttempt.failure_reason`, `TaskAttempt.feedback_provided`, `domain_tags`, `MissionContext` (MCD), `mission_decisions`, `mission_events` — but none of it becomes **reusable strategy**. Four concrete gaps:

1. **Knowledge** — facts discovered during execution live in one execution's output JSON and evaporate next run. Agents re-discover the same things.
2. **Intent** — the mission brief is captured at creation; user corrections ("actually focus on X first", "ignore Y") accumulate in chat history and must be reconstructed every Director turn.
3. **Context** — agents re-read the full MCD every run. Session conversations grow without bound.
4. **Learnings** — when an agent retries 5 times before succeeding, the retry pattern is logged but never promoted to a strategy ("avoid X, prefer Y").

Mission-scoped memory exists (the MCD). **Platform-scoped memory does not.** If mission A discovers that `software.quality.agent` needs >1M tokens for full scans, mission B starts cold.

---

## 2 · Target Architecture

### 2.1 Five surfaces, one query service

| Surface | Table | Scope | Writer | Reader |
|---|---|---|---|---|
| MCD (existing) | `mission_contexts` | Mission | Agent `context_updates` | Context Assembler |
| Decisions (existing) | `mission_decisions` | Mission | `SummarizationService.prune_mcd_decisions` | `KnowledgeService` |
| Milestones (existing) | `milestone_summaries` | Mission | `SummarizationService` | `KnowledgeService` |
| **Intents** (NEW) | `mission_intents` | Mission | Director tool / user CLI | `KnowledgeService` |
| **Learnings** (NEW) | `mission_learnings` | Mission → promoted to platform | `MissionLearningExtractor` | `KnowledgeService` |

One new facade — `KnowledgeService` — fronts all five for agents and clients. One new deterministic extractor. One thin governance agent. All writes flow through the service; no client touches repositories.

**`KnowledgeService` is a composer, not a replacement.** It delegates reads to existing services and repositories rather than duplicating their queries:

| `KnowledgeService` method | Delegates to |
|---|---|
| `get_mission_knowledge()` | `MissionContextManager.get_context()` + `HistoryQueryService.get_mission_summaries()`/`get_recent_failures()` + `MissionIntentRepository.get_current()` + `MissionLearningRepository.list_by_mission()` |
| `search(mode="structured")` | `MissionLearningRepository.list_by_filter()` + `MissionDecisionRepository.list_by_filter()` |
| `search(mode="semantic"|"hybrid")` | Repos' new `semantic_search()` and `hybrid_search()` methods (vector queries live on the repo per existing layering) |
| `similar(entry_id)` | Repo `semantic_search()` with the entry's own embedding |
| `get_current_intent()` | `MissionIntentService.get_current()` |
| `capture_intent()` | `MissionIntentService.create_intent()` |

No reimplementation of `HistoryQueryService`, `MissionContextManager`, or `SummarizationService` — they already do their jobs.

### 2.2 Scoping model

- **Mission-scoped** — default. Any member of a mission can read. Writes by agents assigned to the mission or by a mission owner.
- **Platform-scoped** — read by system admins only. A mission-scoped learning becomes platform-scoped when `platform_promoted=true`. Promotion is automatic above a confidence threshold (configurable), reversible via `retract`.

No `Project` entity. The `platform_promoted` flag is the only cross-mission surface. This resolves the `docs/48-agentic-project-context.md` vs `AGENTS.md` scoping tension in favour of the mission primitive (per AGENTS.md §Design Principles).

### 2.3 Intent is event-sourced, auto-captured

`mission_intents` is append-only. Each revision is a row. Current intent = the most recent row.

The Director auto-captures revisions whenever scope shifts in a user message (detected via a Layer-3 runtime instruction + explicit `capture_intent` tool call). No approval gate in v1 — users see every revision in the intent strip and can override via `mc mission intent set`.

### 2.4 Session memory: anchored rolling summary

Add `rolling_summary`, `rolling_summary_anchor`, `rolling_summary_version` to `sessions`. A local Temporal activity compresses messages above the anchor using Haiku when `message_count - anchor > threshold` (Factory.ai 4-category prompt: intent / play-by-play / artifacts / breadcrumbs). The raw message log is never deleted — the summary is a view.

### 2.5 Retrieval: hybrid (structured + semantic)

Narrative content (learnings, intents, decisions, milestones, rolling summaries) is retrieved via **hybrid retrieval**: structured filter first (`domain_tags`, `kind`, `status`, `platform_promoted`), then vector rerank by cosine similarity against the query embedding. Pure semantic and pure structured are both supported as degenerate cases.

This is explicitly *not* RAG over code — [doc 002 §Why Not Embeddings/RAG for Code](../02-architecture/002-codebase-intelligence.md#L48) correctly argues structure is superior for code retrieval (Code Map stays structured). But learnings/intents/decisions are prose artifacts where "I remember something about token limits…" is a legitimate recall pattern. Hybrid retrieval handles both cleanly.

**Embeddings:** `text-embedding-3-small` (1536 dim), async embed-on-write via local Temporal activity, stored in a **single generic `embeddings` table** (not per-source-table columns) with one HNSW index covering all embeddable types. This is the correct design for *your* primary use case — cross-type unified retrieval — because it collapses a 5-way UNION/HNSW-scan query into a single HNSW scan. It also makes model-version upgrades a single backfill instead of five, and adding new embeddable types (future `mission_artifacts`, `session_messages`, etc.) requires zero schema changes. Trade-off: no native FK cascade from source tables → mitigated by denormalised `mission_id` on `embeddings` with its own CASCADE from `missions`.

**Hybrid mode** (default) uses filter-then-rerank. This is simple and correct for corpora under ~100k rows. If retrieval quality becomes the bottleneck on larger corpora, the next step is **Reciprocal Rank Fusion (RRF)** — the 2026 standard for hybrid search (Elastic, Weaviate, Qdrant defaults). Added as `mode="rrf"` later without schema changes.

### 2.5 Wiring

```
  AGENTS                          SERVICES                        CLIENTS
  ──────                          ────────                        ───────

  context_updates ──┐                                        ┌── Web Mission Tabs
  capture_intent    │                                        │   - Overview (intent strip)
  knowledge.query ──┤                                        │   - Chat (intent strip)
                    ▼                                        │   - Context (+ sub-nav)
        ┌────────────────────┐                               │   - Knowledge (NEW)
        │ KnowledgeService   │◄──── GET /v1/missions/{id}/   │
        │  - search()        │         intent                │
        │  - get_mission_    │         intent/history        ├── Web Platform Page
        │     knowledge()    │         learnings             │   - /knowledge (NEW)
        │  - get_current_    │         context               │     (sysadmin only)
        │     intent()       │                               │
        │  - capture_        │◄──── GET /v1/knowledge/       ├── CLI
        │     intent()       │         search                │   - mc mission intent *
        └─────────┬──────────┘         learnings             │   - mc mission learnings *
                  │                    decisions             │   - mc knowledge * (admin)
     ┌────────────┼────────────┬──────────────┬──────────┐   │
     ▼            ▼            ▼              ▼          ▼   ├── TUI
  intents    learnings     contexts     decisions   embeddings│  - Knowledge screen
                                                    (generic) │  - Intent strip widget
                                                    1 HNSW    │  - Context tab expanded
                                                    all types │

  Deterministic writers (no LLM):
    MissionLearningExtractor  ── daily + post-mission Temporal activity
    SessionMemoryCompressor   ── local activity, fires on threshold

  Judgment writer (Haiku, $0.10/run cap):
    system.knowledge.officer  ── daily Temporal schedule
      - flag_contradictions()
      - promote_to_platform(id)
      - retract(id, reason)
```

---

## 3 · Data Model

### 3.1 New tables

```sql
CREATE EXTENSION IF NOT EXISTS vector;  -- pgvector

CREATE TABLE mission_intents (
    id              UUID PRIMARY KEY,
    mission_id      VARCHAR(36) NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    intent          TEXT NOT NULL,
    intent_summary  TEXT NOT NULL,               -- one-line compression
    scope           JSONB NOT NULL DEFAULT '{}', -- {in: [...], out: [...]}
    source          VARCHAR(32) NOT NULL,        -- user_chat | user_cli | director_inferred | system
    revised_from    UUID REFERENCES mission_intents(id),
    reason          TEXT NOT NULL,
    agent_id        VARCHAR(200),
    session_id      VARCHAR(36) REFERENCES sessions(id) ON DELETE SET NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX ix_mission_intents_mission_created ON mission_intents(mission_id, created_at DESC);

CREATE TABLE mission_learnings (
    id                  UUID PRIMARY KEY,
    mission_id          VARCHAR(36) NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    kind                VARCHAR(32) NOT NULL,    -- failure_pattern|success_pattern|anti_pattern|retry_strategy|capability_gap
    title               VARCHAR(200) NOT NULL,
    body                TEXT NOT NULL,
    evidence            JSONB NOT NULL DEFAULT '{}',  -- Evidence schema; uncapped, render-limited
    domain_tags         JSONB NOT NULL DEFAULT '[]',
    agent_names         JSONB NOT NULL DEFAULT '[]',
    recommendation      TEXT NOT NULL,
    confidence          FLOAT NOT NULL DEFAULT 0.0,   -- 0.0–1.0
    occurrence_count    INT NOT NULL DEFAULT 1,
    platform_promoted   BOOLEAN NOT NULL DEFAULT FALSE,
    promoted_at         TIMESTAMP,
    promoted_by         VARCHAR(200),
    contradicts_id      UUID REFERENCES mission_learnings(id),
    status              VARCHAR(32) NOT NULL DEFAULT 'active',  -- active|superseded|retracted
    created_at          TIMESTAMP NOT NULL DEFAULT now(),
    updated_at          TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX ix_mission_learnings_mission ON mission_learnings(mission_id);
CREATE INDEX ix_mission_learnings_platform ON mission_learnings(platform_promoted, status);
CREATE INDEX ix_mission_learnings_kind_status ON mission_learnings(kind, status);
CREATE INDEX ix_mission_learnings_tags ON mission_learnings USING GIN (domain_tags);

-- Generic embeddings table: one row per (source_table, source_id, version)
CREATE TABLE embeddings (
    id              UUID PRIMARY KEY,
    source_table    VARCHAR(64) NOT NULL,      -- mission_learnings | mission_intents | mission_decisions | milestone_summaries | sessions_rolling_summary
    source_id       UUID NOT NULL,
    mission_id      VARCHAR(36) REFERENCES missions(id) ON DELETE CASCADE,  -- denormalised for cascade + scope filter
    embedding       vector(1536) NOT NULL,
    model           VARCHAR(64) NOT NULL,      -- e.g. "text-embedding-3-small"
    version         INT NOT NULL,              -- bumps trigger backfill
    content_hash    VARCHAR(64),               -- for cross-row dedup of identical text
    created_at      TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE(source_table, source_id, version)
);
CREATE INDEX ix_embeddings_source ON embeddings(source_table, source_id);
CREATE INDEX ix_embeddings_mission ON embeddings(mission_id);
CREATE INDEX ix_embeddings_hnsw ON embeddings USING hnsw (embedding vector_cosine_ops);
```

**Notes on the generic `embeddings` table:**
- **Cascade:** source-table rows are deleted via `missions.id CASCADE` → `mission_learnings` / etc. CASCADE → orphan `embeddings` would remain. The denormalised `mission_id` + CASCADE on `missions` handles this cleanly. Rows not scoped to a mission (platform-level, future) use a nullable `mission_id`.
- **Two-step query pattern:** get top-K `source_id`s from `embeddings`, then fetch source rows by PK. Postgres `JOIN LATERAL` executes this in one round trip.
- **Model upgrades:** bump `embedding.version` in config → daily backfill activity re-embeds where `version < current`. One code path for all types.

### 3.2 Table alterations

```sql
ALTER TABLE sessions
    ADD COLUMN rolling_summary TEXT NOT NULL DEFAULT '',
    ADD COLUMN rolling_summary_anchor INT NOT NULL DEFAULT 0,
    ADD COLUMN rolling_summary_version INT NOT NULL DEFAULT 0;
```

No embedding columns on `sessions`, `mission_decisions`, `milestone_summaries` — embeddings for their content live in the generic `embeddings` table keyed by `(source_table, source_id)`.

### 3.3 JSONB migration for existing tables

Convert existing `JSON` columns to `JSONB` with GIN indexes:
- `mission_contexts.context_data` — GIN on paths.
- `mission_decisions.domain` — B-tree (already indexed by column).
- `milestone_summaries.domain_tags` — GIN.

Use a dialect-aware column type: `JSONB().with_variant(JSON, "sqlite")` so unit tests keep working.

### 3.4 pgvector dialect handling

`vector(1536)` is Postgres-only. The `embeddings` table is created only on Postgres migrations; SQLite unit tests skip it. Any test that exercises semantic search is marked `@pytest.mark.requires_pgvector` and runs against real Postgres (per P12).

### 3.5 Evidence schema (no storage cap)

`mission_learnings.evidence` stores the `Evidence` Pydantic schema uncapped. Render pagination is a config value (`knowledge.learnings.evidence_render_limit: 20`) enforced by API and UI, not at write time. Truncating at write loses audit value and there's no realistic pathology in scope for v1.

---

## 4 · Domain Tag Taxonomy

### 4.1 The allowlist

`modules/backend/core/domain_tags.py` (NEW):

```python
CROSS_CUTTING_TAGS: frozenset[str] = frozenset({
    "auth", "api", "database", "testing", "deployment", "security",
    "performance", "documentation", "config", "infra",
    "backend", "frontend", "tui", "cli",
    "code", "implementation", "refactor", "bugfix", "feature",
    "migration", "quality", "observability",
})


def normalize_tag(raw: str) -> str:
    """Lowercase, strip, deslug. 'Auth' -> 'auth'."""


def validate_tags(
    tags: list[str],
    mcd: dict,
) -> tuple[list[str], list[str]]:
    """Return (valid, invalid).

    Valid = tag ∈ CROSS_CUTTING_TAGS ∪ mcd.architecture.components.keys()
    """


def infer_tags_from_manifest(
    file_manifest: FileManifest,
    mcd: dict,
) -> list[str]:
    """Derive tags from file paths via mcd.identity.repo_structure."""
```

### 4.2 Enforcement points

- `ContextCurator.apply_task_updates()` — validates `domain_tags` writes.
- `TaskExecution.domain_tags` setter — validates on persistence.
- `MissionLearning.domain_tags` setter — validates on creation.

Invalid tags are **logged and dropped**, not rejected (per P8 size-cap philosophy — never block the parent write). A weekly cron surfaces unknown-tag suggestions to the Knowledge Officer.

---

## 5 · Phased Delivery

### Phase A — Foundation (3 days)

**Files:**
- `modules/backend/core/domain_tags.py` — NEW
- `modules/backend/core/embeddings.py` — NEW (provider-agnostic client: `Embedder.embed(text) -> list[float]`, async, `FakeEmbedder` test subclass, fail-open wrapper)
- `modules/backend/models/mission_intent.py` — NEW
- `modules/backend/models/mission_learning.py` — NEW
- `modules/backend/models/embedding.py` — NEW (generic `Embedding` model — one per source row per version)
- `modules/backend/models/session.py` — MODIFY (rolling summary columns — no embedding column; embedding stored in generic table keyed by `('sessions_rolling_summary', session_id)`)
- `modules/backend/repositories/mission_intent.py` — NEW (structured CRUD + filter; no vector methods)
- `modules/backend/repositories/mission_learning.py` — NEW (structured CRUD + filter; no vector methods)
- `modules/backend/repositories/embedding.py` — NEW (`EmbeddingRepository`: `upsert`, `get`, `semantic_search(source_tables, mission_id_scope, query_vec, limit)`, `hybrid_search(source_tables, filter_ids, query_vec, limit)`, `list_missing(model, version, limit)`)
- `modules/backend/schemas/mission_intent.py` — NEW (`MissionIntentCreate`, `MissionIntentResponse`)
- `modules/backend/schemas/mission_learning.py` — NEW
- `modules/backend/schemas/knowledge.py` — NEW (shared `Evidence` schema — uncapped storage, used by learnings and future decision evidence)
- `modules/backend/migrations/versions/2026xxxx_plan57_foundation.py` — NEW (creates `vector` extension, all tables; **HNSW index on `embeddings` is created in a separate post-backfill script** to avoid slow builds on bulk re-embed)
- `config/settings/missions.yaml` — MODIFY (add `knowledge.*` section including `evidence_render_limit` and `embedding.*`)
- `requirements.txt` — ADD `pgvector>=0.2.5`

**DoD:**
- Postgres: `CREATE EXTENSION vector` succeeds; `embeddings` table exists; HNSW index can be created post-backfill and hit via EXPLAIN on `ORDER BY embedding <=> $q`.
- GIN indexes hit on `domain_tags` filter.
- `Embedder.embed("test")` returns a 1536-length vector via the configured provider; `FakeEmbedder` returns deterministic pseudo-vectors from `hashlib` in tests.
- SQLite: `embeddings` table creation skipped; tests that need semantic search marked `@pytest.mark.requires_pgvector` and gated accordingly.
- Repos have CRUD + search coverage ≥90%.

### Phase B — Learnings Pipeline + Hybrid Retrieval (4 days) — highest leverage

**Files:**
- `modules/backend/services/knowledge.py` — NEW (`KnowledgeService`, composer — delegates, does not reimplement)
  - `get_mission_knowledge(mission_id, *, domain_tags=None) -> MissionKnowledgeView` — composes existing services (see Section 2.1 table).
  - `search(query, *, mission_id=None, platform_only=False, kinds=None, domain_tags=None, mode="hybrid", limit=20) -> list[KnowledgeEntry]`
    - `mode="structured"` — tag/kind/status filter only. Zero embedding calls. Single repo method per table.
    - `mode="semantic"` — query text embedded once → `EmbeddingRepository.semantic_search(source_tables=[...], mission_id_scope=..., query_vec, limit)` returns top-K `(source_table, source_id)` pairs → batch fetch source rows by PK.
    - `mode="hybrid"` (default) — structured filter first (collects candidate IDs per source_table), then `EmbeddingRepository.hybrid_search(filter_ids=..., query_vec, limit)` reranks by cosine. Single HNSW scan over the filtered subset.
  - `similar(entry_id, *, limit=10) -> list[KnowledgeEntry]` — looks up the entry's embedding, then `EmbeddingRepository.semantic_search` with that vector.
  - `get_current_intent(mission_id) -> MissionIntent | None`
  - `list_intent_history(mission_id) -> list[MissionIntent]`
  - `capture_intent(...)` — delegated to `MissionIntentService` internally
  - Single factory, single session.
  - **Note:** RRF (Reciprocal Rank Fusion) is the obvious next mode past `hybrid` for large corpora (>100k rows). Not in v1 scope — adds as `mode="rrf"` later with zero schema change.
- `modules/backend/services/mission_learning.py` — NEW
  - `MissionLearningService` — CRUD + promote/retract.
  - `MissionLearningExtractor` — deterministic, reads `TaskAttempt` where status=FAILED, groups by `(agent_name, failure_tier, normalize_tags(domain_tags))`, emits:
    - `kind=failure_pattern` when `occurrence_count >= 2`
    - `kind=retry_strategy` when same `(agent, domain_tags)` failed N times and then succeeded with non-null `feedback_provided`
    - `kind=capability_gap` when agent failures cluster on missing tools
  - Confidence = `min(0.95, 0.3 + 0.15 * occurrence_count - 0.1 * days_since_last_occurrence)`.
  - **No LLM.**
- `modules/backend/services/context_assembler.py` — MODIFY
  - Add Layer 2.5 (learnings) between inputs and history. Budget: `cfg.dispatch.learnings_reserve_tokens` (default 1500). Filtered by `domain_tags`, ordered by confidence.
- `modules/backend/temporal/knowledge_activities.py` — NEW
  - `extract_mission_learnings(mission_id)` — local activity, called on `mission.completed`.
  - `embed_source(source_table, source_id)` — local activity; embeds the content of the named source row and upserts into `embeddings` via `EmbeddingRepository.upsert()`. Fired on every write to an embeddable source row. Asynchronous — never blocks the source write. Each source model exposes a canonical `embed_text()` property so this activity is generic across all types.
  - `backfill_embeddings(source_table=None, to_version=None)` — regular activity + manual admin trigger; calls `EmbeddingRepository.list_missing(model, version, limit)` and re-embeds in batches. Single code path for all source types.
  - Daily Temporal schedule `extract_all_learnings` — walks active missions.
  - Daily Temporal schedule `sweep_missing_embeddings` — idempotent safety net; backfills any source row missing an embedding at the current version.
- `modules/backend/api/v1/endpoints/mission_knowledge.py` — NEW
  - `GET /v1/missions/{id}/knowledge` — unified view.
  - `GET /v1/missions/{id}/learnings` — list + filter.
  - `GET /v1/missions/{id}/learnings/{learning_id}` — detail + first `evidence_render_limit` evidence items + `evidence_total` count.
  - `GET /v1/missions/{id}/learnings/{learning_id}/evidence?offset=0&limit=20` — paged evidence.
  - `GET /v1/missions/{id}/learnings/{learning_id}/similar` — vector-similar entries within mission.
- `modules/backend/api/v1/endpoints/knowledge.py` — NEW
  - `GET /v1/knowledge/search?q=&tags=&kinds=&platform_only=true&mode=hybrid` — sysadmin-gated.
  - `GET /v1/knowledge/similar/{entry_id}` — vector-similar entries platform-wide.
  - `GET /v1/knowledge/learnings` — platform-promoted only, sysadmin.
  - `GET /v1/knowledge/decisions` — sysadmin, cross-mission.
  - `GET /v1/knowledge/milestones` — sysadmin.
- `modules/backend/events/types.py` — MODIFY
  - `MissionLearningExtractedEvent`, `PlatformLearningPromotedEvent`, `LearningContradictionFlaggedEvent`, `MissionIntentRevisedEvent`.

- `modules/backend/services/mission_learning.py` — MODIFY
  - `MissionLearningExtractor` calls `KnowledgeService.similar()` before creating a new learning; if similarity > 0.92 against an active learning with same `kind`, it **increments `occurrence_count`** on the existing row instead of creating a duplicate. Per [doc 46 §Memory Extraction Pipeline](../99-reference-architecture/46-agentic-event-session-architecture.md#L1048) dedup pattern.
  - `MissionLearningService.find_contradiction_candidates()` — deterministic query used by Officer Phase 1.
  - `MissionLearningService.promote()` / `retract()` — enforce gating rules, publish events. Idempotent.
- `modules/backend/schemas/knowledge.py` — already created in Phase A. `Evidence` schema is uncapped at write time; API and UI render-paginate via `evidence_render_limit` config.

**DoD:**
- Recorded fixtures of `TaskAttempt` rows produce expected learnings with expected confidence.
- `KnowledgeService.search(mode="hybrid")` against 10k fixture rows returns in <300ms.
- `KnowledgeService.search(mode="structured")` against 10k fixture rows returns in <100ms.
- Semantic dedup: creating two near-identical learnings results in one row with `occurrence_count=2`.
- Context Assembler injects learnings only when budget allows.
- Events appear in Console Stream tab.

### Phase C — Intent Model (2 days)

**Files:**
- `modules/backend/services/mission_intent.py` — NEW
  - `MissionIntentService.create_intent(mission_id, intent, *, scope, source, session_id=None, revised_from=None, reason, agent_id=None)`.
  - **Dedup on create:** if `intent == current.intent AND scope == current.scope`, return existing without insert. Once embeddings are live, additionally skip if `cosine_similarity(new_embedding, current_embedding) > 0.95`.
  - `get_current(mission_id)`, `list_revisions(mission_id, limit=50)`, `diff(intent_a_id, intent_b_id)`.
  - On create: publishes `MissionIntentRevisedEvent`. Seeds intent_summary deterministically (first 160 chars or first sentence).
- `modules/backend/agents/tools/intent.py` — NEW
  - `capture_intent(intent: str, scope: dict, reason: str) -> str` — Director tool, returns new intent id.
  - `restate_current_intent() -> str` — idempotent read.
- `modules/backend/agents/mission/director/agent.py` — MODIFY
  - Register `capture_intent` + `restate_current_intent` tools.
  - Add `@agent.instructions` hook injecting `"Current intent: {...}\nScope: in={...}, out={...}"` at the top of every turn.
  - System prompt update: "When the user's scope changes (narrowed, expanded, reprioritised), call `capture_intent` before responding."
- `modules/backend/services/session_memory.py` — NEW
  - `compress_if_needed(session_id, threshold=50)` — if `message_count - anchor >= threshold`, dispatches `compress_session_summary` local activity.
- `modules/backend/agents/system/summarization/agent.py` — MODIFY (reuse existing agent)
  - Add a new output type `SessionSpanSummary` and function `summarize_session_span(messages, existing_summary, anchor_index) -> SessionSpanSummary` that uses the Factory.ai 4-category merge prompt (intent / play-by-play / artifacts / breadcrumbs). **Do not create a parallel Haiku path** — the `system.summarization.agent` already exists with `lru_cache`'d instance and `assemble_instructions("system", "summarization")`.
- `modules/backend/temporal/knowledge_activities.py` — MODIFY
  - Add `compress_session_summary(session_id)` local activity that delegates to `system.summarization.agent.summarize_session_span()`. Activity is a thin wrapper — no business logic.
- `modules/backend/agents/mission_control/mission_control.py` — MODIFY
  - After each handled turn, fire `compress_if_needed` (fire-and-forget via local activity — safe, no data loss if it fails).
- `modules/backend/api/v1/endpoints/mission_knowledge.py` — MODIFY
  - `GET /v1/missions/{id}/intent`, `GET /v1/missions/{id}/intent/history`, `POST /v1/missions/{id}/intent`.
- On `MissionService.create_mission()` — seed the first `MissionIntent` from `mission.brief`.

**DoD:**
- Every mission has ≥1 intent row after creation.
- Director system prompt includes current intent verbatim (verified via test that captures the rendered instructions).
- Rolling summary anchors advance monotonically under load.
- Intent strip updates in real-time on revision via SSE.

### Phase D — Retrieval API & Tag Enforcement (2 days)

**Files:**
- `modules/backend/agents/tools/knowledge.py` — NEW
  - `knowledge_query(kinds: list[str] | None, domain_tags: list[str] | None, *, platform_only: bool = False, limit: int = 10) -> list[dict]` — agent tool, thin wrapper over `KnowledgeService.search`.
  - Registered globally in `agents/mission_control/helpers/agent_setup.py`.
- `modules/backend/services/context_curator.py` — MODIFY
  - Validate `domain_tags` on update. Invalid tags logged to a new `tag_suggestions` structured log key.
- `modules/backend/models/execution_record.py` — MODIFY
  - Add validator on `TaskExecution.domain_tags`.
- `modules/backend/services/mission_learning.py` — MODIFY
  - `infer_tags_from_manifest` hook applied on write if caller didn't provide tags.
- `modules/backend/api/v1/endpoints/knowledge.py` — MODIFY
  - Add `GET /v1/knowledge/tags` — sysadmin view of current taxonomy + suggestion log.

**DoD:**
- An agent with `knowledge_query` wired receives correctly-filtered entries in <100ms.
- Tag validator rejects `Auth` (case) → normalized to `auth`.
- Unknown tag `authentification` logged, does not block write.

### Phase E — Knowledge Officer Agent (2 days)

**Files:**
- `config/agents/system/knowledge_officer.yaml` — NEW (tier: system, model: haiku, budget_usd: 0.10)
- `config/prompts/agents/system/knowledge_officer/system.md` — NEW
- `modules/backend/agents/system/knowledge_officer/__init__.py` — NEW
- `modules/backend/agents/system/knowledge_officer/agent.py` — NEW
  - Three tools, all thin wrappers over `MissionLearningService` methods (P7):
    - `flag_contradictions()` — **two-phase**: (1) `MissionLearningService.find_contradiction_candidates()` runs a deterministic query (same `kind`, overlapping `domain_tags ∩ agent_names`, recommendations with opposing verbs via regex: "prefer X" vs "avoid X", "always" vs "never"); (2) Haiku confirms only for candidates. Reduces LLM calls to near-zero on clean data.
    - `promote_to_platform(learning_id)` — idempotent; re-promote is a no-op. Delegates to `MissionLearningService.promote()` which enforces `confidence >= 0.7 AND occurrence_count >= 3 AND distinct_missions >= 2`.
    - `retract(learning_id, reason)` — `MissionLearningService.retract()`.
  - Agent file contains only tool registrations, output schema, and the system prompt. All logic in the service (P7).
  - Output schema: `KnowledgeOfficerReport` with `contradictions_flagged`, `promoted`, `retracted`.
- `modules/backend/temporal/knowledge_activities.py` — MODIFY
  - `run_knowledge_officer` regular activity + daily Temporal schedule.
- `config/prompts/categories/system.md` — NEW (missing from Phase 47 prompt library): describes system agents as having output consumed by code, requiring deterministic structure, tight budgets.

**Missing prompt library files also added:**
- `config/prompts/organization/security_posture.md` — NEW
- `config/prompts/organization/communication_style.md` — NEW

**DoD:**
- Officer runs daily, produces `KnowledgeOfficerReport`, publishes events.
- Contradictions appear in Console + Knowledge tab with red badge.
- Promotion is idempotent (re-promotion is a no-op).

### Phase F — Frontend (3 days)

**Component tree:**
```
modules/frontend/src/
  pages/
    knowledge/                          NEW — top-level route /knowledge (sysadmin)
      index.tsx
      platform-knowledge-page.tsx
      components/
        entry-list.tsx
        entry-detail-panel.tsx
        evidence-drawer.tsx
        knowledge-filters.tsx
        similar-entries-panel.tsx       — vector-similar entries on detail view
        mode-toggle.tsx                  — structured | hybrid | semantic
    mission/
      tabs/
        knowledge-tab.tsx               NEW — per-mission learnings
        context-tab.tsx                 EXPAND — sub-nav: Brief / Arch / Decisions / Intent History
      layout.tsx                        MODIFY — add "Knowledge" tab
  components/
    knowledge/                          NEW
      intent-strip.tsx                  — used in overview + chat
      intent-editor-drawer.tsx
      intent-diff-view.tsx
      learning-card.tsx
      decision-card.tsx
      knowledge-search-box.tsx          — Cmd+K palette, defaults to hybrid mode
  hooks/
    use-mission-intent.ts               NEW
    use-mission-learnings.ts            NEW
    use-mission-knowledge.ts            NEW  — unified view
    use-knowledge-search.ts             NEW  — supports mode=structured|hybrid|semantic
    use-similar-entries.ts              NEW
  api/
    knowledge.ts                        NEW  — typed wrapper
  stores/
    knowledge.ts                        NEW  — filters + search mode + selected-entry state
```

**Mission tab surface:**

| Tab | Change |
|---|---|
| **Overview** | Top strip: `IntentStrip` (1-line summary + ✏ icon). |
| **Chat** | Above input: `IntentStrip` collapsed by default; expands yellow-border on new revision in last 30s. |
| **Context** | Internal sub-nav: Brief & Identity / Architecture / Decisions / Intent History. Intent History uses `IntentDiffView` between revisions. |
| **Knowledge (NEW)** | Two sub-sections: Mission Learnings (filtered table) + Relevant Platform Knowledge (entries where `domain_tags ∩ mission.domain_tags ≠ ∅`). Each row expands to `EvidenceDrawer` showing linked task attempts. |

**Platform page `/knowledge` (sysadmin only):**

```
┌──────────────────────────────────────────────────────────────┐
│  Platform Knowledge          [🔍 search] [⚙ officer report]  │
├──────────────────────────────────────────────────────────────┤
│  Filters: [domain tags] [kind] [status] [platform_only ✓]    │
├─────────────────────┬────────────────────────────────────────┤
│  LEFT PANEL          │  RIGHT PANEL                           │
│  ─ Entry List        │  ─ Entry Detail                        │
│                      │                                        │
│  ▼ failure_pattern   │  # software.quality.agent token limit  │
│    confidence 0.82   │  Kind: failure_pattern                 │
│    4 occurrences     │  Confidence: 0.82                      │
│                      │  Missions: 3                            │
│  ▼ decision d-041    │  Recommendation: split scans by dir    │
│    context           │                                        │
│                      │  [▶ View evidence] [↻ Retract]         │
└─────────────────────┴────────────────────────────────────────┘
```

**Global Cmd+K** — add "Search knowledge…" → opens `KnowledgeSearchBox` (fuzzy over title+body, domain-tag chips).

**RBAC:** `/knowledge` route guard checks `useAuthStore().user.system_role === "admin"`. 403 panel otherwise.

**SSE integration:** `knowledge.*` events from Phase B wired into existing `useMissionStream()`. Add a new Console event category "Knowledge" with 4 filter chips.

**DoD:**
- Non-admin user on `/knowledge` → 403 panel.
- Mission Knowledge tab renders with learnings + relevant platform entries.
- Intent strip updates via SSE without reload.
- Cmd+K palette search returns results in <300ms against 10k-entry fixture.

### Phase G — CLI & TUI (2 days)

**CLI (`mc.py`):**

```
mc mission intent
├── show [--mission ID]                       # current intent
├── history [--mission ID] [--limit N]        # revision timeline
├── set "intent" [--reason TEXT]              # bump intent
└── diff --from UUID --to UUID                # rendered diff

mc mission learnings
├── list [--kind KIND] [--domain TAG]
├── show LEARNING_ID                          # evidence + recommendation
└── export [--format json|md]

mc knowledge                                  # sysadmin only
├── search QUERY [--tags auth,api] [--kinds K] [--mode hybrid|structured|semantic]
├── similar ENTRY_ID [--limit 10]
├── learnings list [--domain X]
├── learnings show ID
├── decisions list [--domain X]
├── decisions show ID
└── milestones list [--mission ID]
```

**Admin (`admin.py`):**

```
admin knowledge
├── officer run [--dry-run]                   # trigger curator
├── officer stats                             # entries, promotions, contradictions
├── officer retract LEARNING_ID --reason T
├── extractor run [--mission ID] [--dry-run]  # trigger deterministic extraction
├── embeddings backfill [--table T] [--model M] # re-embed rows; also runs daily
├── embeddings status                         # NULL embeddings by table, model versions
├── stats                                     # storage, counts, top tags
└── taxonomy [list|validate]
```

**Files:**
```
modules/clients/cli/
  intent_cmds.py                        NEW
  knowledge_cmds.py                     NEW  — both mission + platform subcommands
modules/clients/common/
  knowledge_rendering.py                NEW
    render_intent(intent) -> Panel
    render_intent_history(entries) -> Table
    render_intent_diff(a, b) -> Rich rendered diff
    render_learning_card(learning) -> Panel
    render_learning_list(entries) -> Table
    render_decision_list(entries) -> Table
    render_knowledge_search_results(entries) -> Table
```

All output via `get_console()` from `report.py`. Sysadmin gate on `mc knowledge`: if not admin, show `[red]Access denied[/red]` and exit 3.

**TUI:**
```
modules/clients/tui/
  screens/
    knowledge.py                        NEW — platform browser (admin only)
  tabs/
    knowledge.py                        NEW — per-mission
    context.py                          EXPAND — add intent sub-panel
  widgets/
    intent_strip.py                     NEW — reusable header
    learning_card.py                    NEW
  messages.py                           MODIFY — KnowledgeEvent variants
```

Main TUI menu: add "Knowledge" option (admin-gated) to the bindings in `app.py`.

**DoD:**
- `mc mission intent set "..."` produces a new row + SSE event + updated chat strip on the frontend.
- `mc knowledge search security` against 10k entries returns in <500ms.
- Non-admin `mc knowledge ...` exits with clear error.
- TUI Knowledge screen navigable with j/k, q to exit.

---

## 6 · Event Contract

Add to `EVENT_TYPE_REGISTRY` in [events/types.py](modules/backend/events/types.py):

```python
class MissionIntentRevisedEvent(BaseMissionEvent):
    event_type: Literal["knowledge.intent.revised"]
    intent_id: str
    old_intent_summary: str
    new_intent_summary: str
    reason: str
    source: Literal["user_chat", "user_cli", "director_inferred", "system"]

class MissionLearningExtractedEvent(BaseMissionEvent):
    event_type: Literal["knowledge.learning.extracted"]
    learning_id: str
    kind: str
    title: str
    domain_tags: list[str]
    confidence: float

class PlatformLearningPromotedEvent(BaseMissionEvent):
    event_type: Literal["knowledge.learning.promoted"]
    learning_id: str
    promoted_by: str

class LearningContradictionFlaggedEvent(BaseMissionEvent):
    event_type: Literal["knowledge.contradiction.flagged"]
    learning_ids: list[str]
    reason: str
```

All four publish to `mission_events:{mission_id}` (Redis Pub/Sub) AND persist to `mission_events` table (per ADR-004). Each gets a Console category filter chip and a dedicated colour.

---

## 7 · Configuration

`config/settings/missions.yaml` additions:

```yaml
knowledge:
  learnings:
    min_occurrence_for_extraction: 2
    promotion_confidence_threshold: 0.7
    promotion_min_missions: 2
    context_assembler_reserve_tokens: 1500
    context_assembler_max_entries: 5
    dedup_similarity_threshold: 0.92      # cosine; above this, increment occurrence_count instead of creating
    evidence_render_limit: 20             # UI pagination only — storage is uncapped
  intent:
    auto_capture: true
    summary_max_chars: 160
    dedup_similarity_threshold: 0.95      # skip create if cosine(new, current) exceeds this
  session_memory:
    compression_threshold_messages: 50
    summary_max_tokens: 8000
  officer:
    schedule_cron: "0 4 * * *"        # daily 04:00 UTC
    budget_usd_per_run: 0.10
    model: haiku
  embedding:
    provider: openai                  # openai | voyage | local
    model: text-embedding-3-small     # 1536 dims
    dimensions: 1536
    version: 1                        # bumps trigger backfill across the single generic embeddings table
    backfill_batch_size: 50
    backfill_schedule_cron: "15 4 * * *"  # daily 04:15 UTC; runs after officer
    default_search_mode: hybrid
    fail_open: true                   # provider outage → fall back to structured-only search
```

**Secrets** (`config/.env`):
```
OPENAI_API_KEY=sk-...                 # required when provider=openai
```

---

## 8 · Tests (P11 + P12)

| Layer | Test | Real infra | Mock |
|---|---|---|---|
| `domain_tags.validate_tags` | unit | — | — |
| `MissionLearningExtractor` | fixture-driven integration | Real Postgres | — |
| `MissionIntentService` create + get_current + diff | integration | Real Postgres | — |
| `KnowledgeService.search(mode=structured)` — GIN hit, latency | integration | Real Postgres | — |
| `KnowledgeService.search(mode=hybrid)` — HNSW hit, rerank correctness, single-scan EXPLAIN | integration | Real Postgres + pgvector | `FakeEmbedder` for query |
| `KnowledgeService.search(mode=semantic)` cross-type — one HNSW scan across source tables | integration | Real Postgres + pgvector | `FakeEmbedder` |
| `KnowledgeService.similar()` — returns by cosine distance | integration | Real Postgres + pgvector | — |
| Semantic dedup — near-duplicate increments occurrence_count | integration | Real Postgres + pgvector | — |
| `EmbeddingRepository.upsert` — `(source_table, source_id, version)` uniqueness enforced | integration | Real Postgres | — |
| `embed_source` local activity — idempotent, upserts correctly | integration | Real Postgres + Temporal test server | `FakeEmbedder` |
| Backfill — version bump re-embeds all rows generically | integration | Real Postgres | `FakeEmbedder` |
| CASCADE — deleting mission removes its `embeddings` rows | integration | Real Postgres | — |
| Fail-open behaviour — provider outage falls back to structured | integration | Real Postgres | Embedder raises |
| `ContextAssembler` Layer 2.5 injection under budget | integration | Real Postgres | — |
| Director `capture_intent` tool wiring | agent test | Real Postgres | TestModel |
| `session_memory.compress_if_needed` | integration | Real Postgres + Temporal test server | Haiku via TestModel |
| Knowledge Officer promote/retract | agent test | Real Postgres | TestModel |
| API RBAC — sysadmin gate on `/v1/knowledge/*` | integration | Real Postgres | — |
| Frontend hooks | component | MSW | — |
| CLI commands — `mc mission intent set` → SSE event fires | e2e | Real stack | — |
| TUI Knowledge screen navigation | snapshot | — | — |

**No test mocks the DB.** Extractor is pure enough to also have fast unit tests with in-memory fixtures.

---

## 9 · Failure Modes & Mitigations

| Risk | Mitigation |
|---|---|
| Extractor produces noise (low-confidence spam) | Confidence threshold gates Context Assembler inclusion. Officer auto-retracts stale entries. |
| Taxonomy drift | Validator on every write. Invalid tags logged but not rejected. Officer reviews weekly. |
| Intent auto-capture loops (Director re-captures identical intent) | Deduplication: skip create if `intent == current.intent AND scope == current.scope`. |
| Officer promotes incorrectly | `platform_promoted` reversible via `retract`. All actions emit events + audit. |
| MCD size cap already enforces bounds | No change — continue existing `MissionContextManager` size checks. |
| Rolling summary loses detail | Raw messages stay in DB. Summary is a view, not a replacement. Factory.ai 4-category anchor prevents drift. |
| JSONB migration breaks dev SQLite | Dialect-aware column type (`JSONB().with_variant(JSON, 'sqlite')`). |
| Sysadmin RBAC bypass | Middleware-level check + frontend guard + CLI check. Three-layer defence. |
| Cross-mission leakage via platform-promoted entries | Only sysadmins see platform view. Mission view includes platform entries only via `domain_tags` overlap — no identifying information from other missions. |
| Embedding provider outage | `fail_open: true` makes `search(mode=hybrid)` fall back to `mode=structured`. Embeddings are a performance layer, not a correctness layer. Write path is async — outage just delays embed, doesn't block writes. |
| Embedding model change (drift / upgrade) | `embedding_version` bumped in config → daily backfill activity walks rows where `embedding_version < current` and re-embeds. Old vectors are overwritten atomically. |
| Embedding cost runaway | Costed at ~$0.02 per 1M tokens for `text-embedding-3-small`. At typical learning body ~200 tokens, 10k learnings = $0.04 total. Negligible, but `knowledge.embedding.provider=local` (e.g. bge-small) is a future fallback. |
| Semantic dedup merges genuinely-distinct learnings | `dedup_similarity_threshold` is conservative (0.92). Officer retraction path is one call. All merges logged with linked source IDs. |
| Contradiction false positives from Haiku | Two-phase detection: deterministic candidates first; Haiku only confirms. If zero candidates, zero LLM calls. Contradictions flagged via `LearningContradictionFlaggedEvent` and an auto-`schedule_followup` for human review via the existing Plan 51 primitive. |
| HNSW index build time on bulk backfill | HNSW index on `embeddings` is created in a **separate post-backfill script**, not in the foundation migration. Initial migration creates the table without the index; after the first round of embed-on-write populates it, the script runs `CREATE INDEX … USING hnsw`. Subsequent model-version upgrades reuse the existing index (HNSW handles overwrites fine). |
| Runaway `evidence` JSONB size in pathological case | Storage is uncapped by design (audit-trail integrity). UI and API pagination cap visible items at `evidence_render_limit`. If the pathology ever manifests in production, add truncation then — not prematurely. |
| Unit tests hit real embedding provider | `tests/conftest.py` registers a `FakeEmbedder` fixture by default (returns deterministic pseudo-vectors from `hashlib`). Real provider only used in the `@pytest.mark.embedding_provider` integration tier. |

---

## 10 · Rollout & Decommissioning

- **No existing table removed.** MCD, decisions, milestones all unchanged.
- **No existing service replaced.** `MissionContextManager`, `SummarizationService`, `HistoryQueryService` unchanged.
- **Additive only.** New surfaces can be disabled via `knowledge.enabled: false` feature flag in config without breaking existing flows.
- Director prompt changes (Phase C) are gated by the feature flag until Phase E ships.

---

## 10a · Reuse Contract (what we do NOT build)

This plan adds as little new code as possible. Every piece of functionality that already exists must be reused, not reimplemented. Enforced:

| Existing primitive | Plan 57 reuses it for |
|---|---|
| [services/base.py](../../modules/backend/services/base.py) `BaseService` | All new services extend it (`KnowledgeService`, `MissionIntentService`, `MissionLearningService`) — gets `_execute_db_operation`, `_log_operation`, session mgmt, `factory()` pattern. |
| [repositories/base.py](../../modules/backend/repositories/base.py) `BaseRepository` | New repos extend it — get `get_by_id`, `create`, `update`, `delete`, `exists`, `count` for free. |
| [core/utils.py](../../modules/backend/core/utils.py) `utc_now`, `estimate_tokens` | Used throughout. Never call `datetime.now()` or recompute token estimates. |
| [core/logging.py](../../modules/backend/core/logging.py) `get_logger` | All new modules. Rule 001.2. |
| [services/mission_context.py](../../modules/backend/services/mission_context.py) `MissionContextManager` | MCD read/write unchanged — the only mutator. `KnowledgeService.get_mission_knowledge()` calls `.get_context()`. |
| [services/history_query.py](../../modules/backend/services/history_query.py) `HistoryQueryService` | Mission history, failures, summaries. `KnowledgeService` composes it — no replacement. |
| [services/summarization.py](../../modules/backend/services/summarization.py) `SummarizationService` | Fractal compression of decisions + milestones — unchanged. Plan 57 does not touch this path. |
| [agents/system/summarization/agent.py](../../modules/backend/agents/system/summarization/agent.py) `system.summarization.agent` | **Reused** for session rolling-summary compression — new `summarize_session_span()` function added to it, not a parallel agent. |
| [services/session_followup.py](../../modules/backend/services/session_followup.py) `SessionFollowupService` (Plan 51) | Contradiction flags auto-schedule a followup via the existing primitive. No new watcher mechanism. |
| [events/bus.py](../../modules/backend/events/bus.py) `SessionEventBus.publish_to_mission` | All new events go through the existing bus. |
| [core/dependencies.py](../../modules/backend/core/dependencies.py) admin-role guard | Sysadmin-gated `/v1/knowledge/*` endpoints reuse the existing `AdminRole` dependency. No new RBAC code. |
| [agents/mission_control/helpers/_build_model](../../modules/backend/agents/mission_control/helpers/model_builder.py) | Officer agent + session summarizer use the existing model builder — no new provider plumbing. |
| [clients/common/display.py](../../modules/clients/common/display.py) `get_console`, primitives | All CLI rendering. No new Console instantiation (rule 006). |
| [clients/common/event_rendering.py](../../modules/clients/common/event_rendering.py) | New `knowledge.*` event categories registered here, not in separate renderers. |
| [schemas/task_plan.py](../../modules/backend/schemas/task_plan.py) `FileManifest` | `infer_tags_from_manifest()` reads it — no new manifest type. |
| [idempotency](../../modules/backend/core/idempotency.py) fail-open pattern | Embedding provider outage follows the same "fail open, log, continue" shape as idempotency cache outage. |
| [services/mission_context.py](../../modules/backend/services/mission_context.py) TTL-cache pattern | If a cache is needed later, copy this pattern. v1 has no cache on `KnowledgeService` (reads are DB-direct). |

**Explicit non-duplications:**
- No new "ContextAssembler v2" — Plan 57 extends the existing assembler with one new layer (learnings), it does not replace it.
- No new event bus, no new SSE path, no new session model.
- No new `Console`/`Table`/`Panel` instantiation in clients — all through `report.py`/`get_console()`.
- No new DB session management in clients — `KnowledgeService.factory()` only.
- No new logger creation — `get_logger(__name__)` everywhere.
- No new `datetime` usage — `utc_now()` only.
- **No per-table embedding columns.** One `embeddings` table, one `EmbeddingRepository`, one HNSW index. Embedding is a cross-cutting concern with a single owner — not a field scattered across 5 domain tables.
- **No storage-level truncation of `evidence`.** Pagination is a presentation concern and lives in API + UI only.

---

## 11 · Out of Scope (Deferred)

All deferred work is tracked in **[57a — Deferred Horizon](./57a-plan-knowledge-horizon.md)**. Summary:

| Deferred | Why | Future trigger |
|---|---|---|
| MCP server exposing `KnowledgeService` | Not needed until a non-platform consumer exists | External agent integration |
| Exemplar Registry population | Requires first-boot discovery mission pattern | After Phase E proven stable |
| Multi-user-per-mission RBAC | Single-owner missions today | Second user needs mission access |
| Cross-platform federation | Single-platform deployment | Multi-tenant deployment |
| Proactive surfacing by Officer | Needs enough platform learnings to matter (~20+) | Directors complain "should have mentioned X" |
| Knowledge graph edges | Single-entry queries still sufficient | Users ask "what led to this?" |
| Multi-modal evidence (screenshots, diagrams) | Text evidence credible for now | Visual bug learnings ignored |
| Time-decay on confidence | Fresh enough data | Officer retraction volume climbs |

---

## 12 · Sequencing Summary

| Phase | Days | Unblocks | Leverage |
|---|---|---|---|
| A Foundation | 3 | All subsequent | Low (infra) — includes pgvector extension, embed client, HNSW indexes |
| B Learnings + Hybrid Retrieval | 4 | Officer, Context, Frontend learnings surface | **Highest** — turns retry infra into reusable strategy + semantic recall |
| C Intent | 2 | Director UX fix, Session memory | **High** — removes biggest UX scar |
| D Retrieval API + Tagging | 2 | Agents self-serve, cleaner data | Medium |
| E Officer Agent | 2 | Auto-promotion, contradiction hygiene | Medium |
| F Frontend | 3 | Human participation | **High** |
| G CLI/TUI | 2 | Symmetrical clients | Medium |

**Total: 18 focused days.**

The critical path is A → B → C → F. D and E can run in parallel with F once B and C land. G follows F but doesn't depend on it.

---

## 13 · Open Questions — Resolved

| # | Question | Answer |
|---|---|---|
| 1 | Platform knowledge scope — single platform or per-team? | Mission-scoped (multiple users per mission in future) + platform-scoped (sysadmins, all missions). No Project entity. |
| 2 | Intent capture — propose-and-confirm or auto-capture? | Auto-capture. Refine over time. |
| 3 | Officer promotion gate — human approval or auto-promote? | Auto-promote above threshold. Retraction path compensates. |
| 4 | Frontend — separate Knowledge tab or merge into Context? | Separate tab. Context gets intent history sub-nav only. |
| 5 | CLI naming — `mc mission ...` / `mc knowledge ...`? | Confirmed. |

---

## References

- Architecture: [docs/02-architecture/001-project-context-layer.md](../02-architecture/001-project-context-layer.md)
- Architecture: [docs/02-architecture/002-codebase-intelligence.md](../02-architecture/002-codebase-intelligence.md)
- Reference: [docs/99-reference-architecture/46-agentic-event-session-architecture.md §Memory Architecture](../99-reference-architecture/46-agentic-event-session-architecture.md)
- Reference: [docs/99-reference-architecture/47-agentic-module-organization.md §Layered Intent Engineering](../99-reference-architecture/47-agentic-module-organization.md)
- Reference: [docs/99-reference-architecture/48-agentic-project-context.md](../99-reference-architecture/48-agentic-project-context.md)
- Principles: [docs/03-principles/01-project-principles.md](../03-principles/01-project-principles.md) — P2, P6, P10, P14
- ADR: [docs/02-architecture/004-adr-unified-async-architecture.md](../02-architecture/004-adr-unified-async-architecture.md) — Temporal / Redis Pub/Sub / PostgreSQL
- Closes: TODO.md "Context management — continuous update of knowledge, intent, context, learnings"
- Closes: TODO.md "Investigate system.knowledge.officer.agent"
