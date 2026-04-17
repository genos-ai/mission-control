# Plan 57a — Knowledge Platform: Deferred Horizon

| Field | Value |
|-------|-------|
| **Status** | Parking lot — nothing scheduled |
| **Created** | 2026-04-16 |
| **Parent** | [Plan 57 — Knowledge, Intent & Learnings Platform](./57-plan-knowledge-platform.md) |
| **Purpose** | Catalogue work we deliberately don't build yet so we don't forget. Each item has a concrete trigger and design sketch. |

---

## Intent

Plan 57 is deliberately narrow. It ships the knowledge/intent/learnings platform and hybrid retrieval — the minimum that delivers the core value. This companion doc parks everything else that logically belongs to the same landscape but isn't justified *yet*.

**Do not pre-build anything here.** Each item is gated on a concrete signal. When a signal fires, promote the corresponding section into its own plan.

---

## H1 · MCP server exposing `KnowledgeService`

**Trigger:** A non-platform agent needs to query your knowledge.
- Claude Code / Cursor / pi-mono doing dev on this repo and asking "what decisions have we made about auth?"
- A third-party agent backend wraps the platform (see TODO.md "Third-party agent backends").
- Cross-platform federation (H5) becomes real.

**What it adds**
- Dedicated MCP server process exposing `KnowledgeService` as MCP tools over **streamable HTTP transport** (the 2026 standard — stdio is obsolete for network use).
- Per-user API key auth (reuse existing `api_keys` table).
- Read-only by default; write tools behind `mcp.allow_writes: true`.

**Design sketch**
```python
# modules/backend/mcp/server.py
@mcp.tool
async def search_knowledge(
    query: str,
    domain_tags: list[str] | None = None,
    kinds: list[str] | None = None,
    platform_only: bool = False,
    mode: Literal["structured", "hybrid", "semantic"] = "hybrid",
) -> list[KnowledgeEntry]: ...

@mcp.tool
async def get_current_intent(mission_id: str) -> MissionIntent | None: ...

@mcp.tool
async def list_decisions(domain: str | None = None) -> list[MissionDecision]: ...

@mcp.tool
async def list_learnings(
    kind: str | None = None,
    platform_only: bool = False,
) -> list[MissionLearning]: ...
```

Mounted at `/mcp` alongside the REST API. Reuses `KnowledgeService.factory()` — zero logic duplication, rule 008.2 preserved.

**Effort:** ~2 days.

**Dependencies:** Plan 57 Phase B + Phase C complete.

---

## H2 · Exemplar Registry population

**Trigger:** Plan 57 is stable and coding-agent token burn from exploration shows up as a cost line.
- PQI / code map usage plateaus — agents have spatial memory but still re-derive patterns.
- Recurring class of bug where agents use "close but wrong" patterns (e.g. `logging.getLogger()` instead of `get_logger()`).

**What it adds**
- Populates MCD `architecture.components.{name}.exemplar_file` per [doc 002 §Exemplar Registry](../02-architecture/002-codebase-intelligence.md).
- New `system.project_discovery.agent` that runs once on mission creation (or on-demand via `mc mission discover`).
- Weekly "exemplar review" Officer task — re-evaluates whether the current exemplar is still the best example.

**Design sketch**

Discovery inputs: Code Map + PQI top-ranked files + PageRank + directory structure.

Output:
```python
class ExemplarProposal(BaseModel):
    component: str          # e.g. "services", "repositories"
    exemplar_file: str      # path
    reasons: list[str]      # "highest PageRank in services/", "shortest at <300 lines", "zero rule violations"
    confidence: float
```

Writes to MCD via existing `context_updates`. No new service — reuses `MissionContextManager`. Weekly review uses `KnowledgeService` + Code Map diff to detect when a better candidate emerges.

Coding agents already receive the MCD in every invocation — populating `exemplar_file` just makes it useful.

**Effort:** ~2 days. Mostly agent design and prompt tuning.

**Dependencies:** Plan 57 Phase A (taxonomy), Plan 20 (Code Map — done).

---

## H3 · Multi-user-per-mission RBAC

**Trigger:** The first time a second person needs mission access. Today missions are effectively single-owner.

**What it adds**
- `mission_members` table — `(mission_id, user_id, role)` where `role ∈ {owner, editor, viewer}`.
- Propagation of `session.user_id` into every write that currently uses `system:cli`.
- Role-gated API endpoints:
  - `viewer` — read MCD, read knowledge, read events.
  - `editor` — viewer + write `context_updates`, capture intent, approve gates.
  - `owner` — editor + membership changes, archive mission.
- Frontend: member list + invite modal on Mission settings.
- CLI: `mc mission members add|remove|list`.

**Design sketch**
```sql
CREATE TABLE mission_members (
    id UUID PRIMARY KEY,
    mission_id VARCHAR(36) NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(16) NOT NULL CHECK (role IN ('owner','editor','viewer')),
    added_by VARCHAR(36) NOT NULL,
    added_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE(mission_id, user_id)
);
CREATE INDEX ix_mission_members_user ON mission_members(user_id);
```

Middleware: a `MissionRole` dependency that resolves role from `(session.user_id, path.mission_id)` and rejects with 403 if insufficient.

**Knowledge impact**
- `mission_learnings` and `mission_intents` gain an `author_user_id` field.
- Platform-promoted learnings hide the author for privacy ("promoted by system").
- Mission-scoped learnings show the author for evidence trails.

**Effort:** ~4 days. Schema + middleware + CLI + frontend + test RBAC matrix.

**Dependencies:** None structural. Can be built independently of Plan 57.

---

## H4 · Proactive surfacing by the Officer

**Trigger:** Enough platform learnings exist (~20+) that passive retrieval starts missing relevant hits. Directors complain "you should have mentioned X."

**What it adds**
- `system.knowledge.officer.agent` gains `seed_relevant_learnings(new_mission_id)` — called on mission creation.
- On Director turn, an optional "relevant platform learnings for your current intent" pre-brief surfaces in the response, capped at 2 entries.
- Cross-mission similarity via pgvector: when a new mission brief is embedded, find similar past missions and surface their learnings automatically.

**Design sketch**

Runs as a local Temporal activity on `mission.created` and on `intent.revised`. Queries `KnowledgeService.search(mode=hybrid, platform_only=true, domain_tags=<inferred from brief>)`. Seeds results into the new mission's MCD `current_state.relevant_platform_knowledge` section (new).

Requires careful opt-out — users must be able to silence proactive surfacing per-mission (`mission.knowledge.proactive_enabled = false`).

**Effort:** ~1 day. All primitives exist in Plan 57.

**Dependencies:** Plan 57 Phase E (Officer live), H3 optional (user-level opt-out is cleaner with RBAC).

---

## H5 · Cross-platform federation

**Trigger:** You operate more than one Mission Control instance (multiple tenants, regions, acquisitions). Probably never for this codebase unless productized.

**What it adds (per [doc 13 research](../98-research/13-Scaling Open Brain to enterprise- a centralized knowledge architecture.md))**
- Lightweight central control plane that holds **metadata only** — "what platform-promoted entries exist, where, under what tags" — not content.
- Per-instance data plane unchanged.
- Federated query: `knowledge.search(federated=true, instances=["a","b"])` routes through the control plane and aggregates.
- Policy engine (OPA) enforcing cross-instance sharing rules.
- MCP federation as transport (H1 is a prerequisite).

**Design sketch:** out of scope to detail. Becomes its own architecture doc when the need arises.

**Effort:** ~4–6 weeks if it ever happens.

**Dependencies:** H1 (MCP), H3 (RBAC — federation multiplies the RBAC surface).

---

## H6 · Knowledge graph edges (typed relationships)

**Trigger:** Single-entry queries stop being sufficient. Users ask "what failures led to this decision?" or "what intent revisions came from this mission?"

**What it adds**
- Typed edge table:
  ```sql
  CREATE TABLE knowledge_edges (
      id UUID PRIMARY KEY,
      source_kind VARCHAR(32) NOT NULL,     -- learning | decision | intent | milestone
      source_id UUID NOT NULL,
      target_kind VARCHAR(32) NOT NULL,
      target_id UUID NOT NULL,
      edge_type VARCHAR(32) NOT NULL,       -- supersedes | derived_from | contradicts | triggered_by | evidence_of
      reason TEXT,
      created_by VARCHAR(200),
      created_at TIMESTAMP NOT NULL DEFAULT now()
  );
  CREATE INDEX ix_knowledge_edges_source ON knowledge_edges(source_kind, source_id);
  CREATE INDEX ix_knowledge_edges_target ON knowledge_edges(target_kind, target_id);
  ```
- `KnowledgeService.get_related(entry) -> list[RelatedEntry]`.
- Frontend: edge-view panel on entry detail; optional force-directed graph view for a mission's knowledge subgraph.
- `mission_learnings.contradicts_id` (already in Plan 57) folded into the generic edge table — no change for consumers.

**Design principle:** edges are user/agent-declared, not inferred. Agents add edges via `knowledge.link(source, target, edge_type)` — deterministic tool. Officer validates consistency (e.g. `supersedes` + `contradicts` between same pair is contradictory).

**Effort:** ~3 days including frontend graph view.

**Dependencies:** Plan 57 Phase B.

---

## H7 · Multi-modal evidence (screenshots, diagrams, attachments)

**Trigger:** Text-only evidence becomes a credibility gap — UI bug learnings ignored because no screenshot.

**What it adds**
- `mission_artifacts` table already exists (Plan 43). Wire `mission_learnings.evidence.artifact_ids` + `mission_decisions.evidence.artifact_ids`.
- Frontend: inline artifact rendering in entry detail (image preview, PDF embed, downloadable file).
- Optional OCR pipeline for images → text → embedding (via provider vision models) so screenshots are searchable semantically.

**Design sketch**
```python
# schemas
class Evidence(BaseModel):
    task_attempt_ids: list[str] = []
    execution_ids: list[str] = []
    failure_tiers: list[int] = []
    artifact_ids: list[str] = []   # NEW
```

Existing Plan 57 code requires zero change — `evidence` is already JSONB.

**Effort:** ~1 day backend + 1 day frontend rendering.

**Dependencies:** Plan 43 (Persistent Mission Artifacts — done).

---

## H8 · Time-decay on confidence

**Trigger:** Officer retraction volume climbs because older-but-still-active entries get stale.

**What it adds**
- Confidence decay function:
  ```python
  effective_confidence = confidence * exp(-days_since_last_occurrence / tau)
  # default tau = 90 days, configurable per-kind
  ```
- Context Assembler and `KnowledgeService.search` use `effective_confidence` for ranking instead of raw `confidence`.
- Raw `confidence` preserved on the row — decay is a computed view.
- Monthly "staleness report" via Officer: entries where `effective_confidence < 0.3` and `last_occurrence > 120 days` ago.

**Design principle:** time decay is *not* retraction. A decayed learning still surfaces on exact-match queries; it just deprioritises in ranked results. Retraction remains an explicit Officer call.

**Effort:** <1 day. One SQL expression change + config + staleness report.

**Dependencies:** Plan 57 Phase B + E.

---

## H9 · Embedding provider diversity & local fallback

**Trigger:** OpenAI outage causes hybrid search to fall back to structured-only for extended periods, OR you want to run air-gapped.

**What it adds**
- `knowledge.embedding.provider = local` implemented via `sentence-transformers` running `bge-small-en-v1.5` or `nomic-embed-text-v1.5` in-process.
- `knowledge.embedding.provider = voyage` added (`voyage-3-lite` is strong on code-adjacent content).
- Per-row `embedding_provider` field so mixed-provider backfills work during a migration.

**Effort:** ~1 day per provider. Local is the biggest — needs GPU/CPU decision.

**Dependencies:** Plan 57 Phase A (the provider-agnostic client is already there).

---

## H10 · Knowledge export / import

**Trigger:** You want to snapshot a mission's knowledge for archival, share with an external reviewer, or migrate between deployments.

**What it adds**
- `mc mission knowledge export --format json|md [--output FILE]` — bundles MCD + intent history + learnings + decisions + milestones + edges (if H6) into a single deterministic JSON.
- `mc mission knowledge import FILE` — reverse operation, with UUID remapping and conflict resolution.
- Admin endpoint for bulk export across missions (sysadmin only).

**Effort:** ~2 days.

**Dependencies:** Plan 57 Phase B + C.

---

## H11 · Per-user knowledge subscriptions

**Trigger:** Multiple users on the platform (H3 live) and some want to be notified when platform learnings land in their domain.

**What it adds**
- `knowledge_subscriptions` table: `(user_id, domain_tags, kinds, notification_channel)`.
- Subscription fires on `PlatformLearningPromotedEvent` when `tags ∩ subscription.domain_tags ≠ ∅`.
- Channels: in-app bell, email, Slack, Telegram (reuse existing gateway).

**Effort:** ~2 days.

**Dependencies:** H3 (multi-user), Plan 57 Phase E.

---

## Horizon signal map

| Item | Signal that promotes this to a real plan |
|---|---|
| H1 MCP server | Manual copy-paste of "what did we decide about X" from one tool to another, or an external agent integration request. |
| H2 Exemplar Registry | Coding-agent rule violations don't trend down after Plan 57 + code map. |
| H3 Multi-user RBAC | Second user needs mission access. |
| H4 Proactive surfacing | "You should have mentioned that" complaint from a Director user. |
| H5 Federation | Second Mission Control deployment (acquisition, tenant). |
| H6 Graph edges | "What led to this?" appears as a user question without a clean query answer. |
| H7 Multi-modal | A UI bug learning is ignored because evidence is text-only. |
| H8 Time decay | Officer retraction volume climbs AND staleness complaints emerge. |
| H9 Provider diversity | OpenAI outage ≥1 hour OR air-gap deployment request. |
| H10 Export/import | First archival, review, or migration need. |
| H11 Subscriptions | Users ask "can I be notified when…" |

---

## What this doc is *not*

- A roadmap. None of these are scheduled.
- A priority list. Signal order determines priority.
- Exhaustive. New items land here as we discover them.

If a horizon item fires, promote it to its own `docs/97-plans/NN-plan-*.md` with full phase detail — don't try to execute from this doc.

---

## Changelog

- 2026-04-16: Created. Extracted from Plan 57 Section 11 plus items surfaced in the Plan 57 review (proactive surfacing, graph edges, multi-modal, time decay, provider diversity, export/import, subscriptions).
