# Genos AI Deep Research Agent Platform — Production Specification

**Version:** 1.2
**Date:** 12 April 2026
**Author:** Herman (Group CISO, Icarus)
**Classification:** Internal — Genos AI Engineering
**Revision:** v1.1 → v1.2. Added: specification governance (0.1), security boundaries (2.7), AGE client specification (3.8), depth-to-config mapping (6.2.1). Fixed: architecture contradiction between distributed workers and in-process asyncio.gather (resolved to single-process orchestrator with task-level NATS distribution), SSE race condition (now NATS-backed), Tavily SDK parameter error, NLI label ordering assumption, undefined `execute_cypher` interface, missing spaCy dependency, graph write-back performance (batched Cypher), token budget sizing, `depends_on` indexing convention, `SynthesisStrategy` enum case sensitivity, `expected_output_length` disconnection from orchestrator behaviour, cost/compaction observability gaps.

---

## 0.1 Specification Governance

This specification is the authoritative source of truth for the Genos AI Research Agent Platform. It lives in the same git repository as the implementation code, at `docs/spec.md`.

**Modification rules:**

- Every change to the spec requires a pull request with at least one reviewer.
- The Pydantic models in `src/agents/models.py` are the executable form of Section 4.3. If the code and spec diverge, the spec is authoritative and the code must be updated.
- Every behavioural invariant in Section 2.5 must have a corresponding test in `tests/`. A CI step (`make test-invariants`) validates this coverage.
- Spec changes that alter Pydantic model schemas, API contracts (Section 2.3), or behavioural invariants (Section 2.5) must include the corresponding code change in the same PR.
- Sections marked "Out of Scope" (Section 12.0) may not be implemented without first updating the spec to move them in-scope.

**Version numbering:** Major.Minor. Major increments indicate breaking changes to API contracts or output models. Minor increments indicate additions, clarifications, or non-breaking fixes.

---

## Summary

Build a general-purpose autonomous research agent on the existing BFA framework (FastAPI, FastStream/NATS, PydanticAI, PostgreSQL/TimescaleDB). The system uses an Anthropic-style orchestrator-worker multi-agent pattern: a planner decomposes queries into 3–7 independent sub-questions, parallel sub-agents research each via Tavily web search and Trafilatura content extraction, and a synthesiser produces a cited report. PostgreSQL serves as a unified data layer with Apache AGE for knowledge graph storage (entity/relationship/provenance tracking) and pgvector for embedding-based RAG retrieval. NATS JetStream distributes tasks across 20+ concurrent workers. NLI cross-encoders verify citation accuracy post-synthesis.

---

## 1.0 Technology Stack

### 1.1 Technology Decision Matrix

| Component | Technology | Version | Role | Rationale |
|---|---|---|---|---|
| API Layer | FastAPI | >=0.115 | HTTP endpoints, SSE streaming | Existing BFA framework component; native async, Pydantic integration |
| Agent Orchestration | PydanticAI | 1.72.0 | Agent definition, tool registration, structured output | Type-safe agent abstraction with dependency injection; FallbackModel for multi-provider routing |
| Message Broker | NATS JetStream via FastStream | FastStream 0.6.x, NATS 2.10+ | Async task distribution, durable delivery | Sub-millisecond latency; pull consumers self-balance across 20+ workers without queue group config; single 20MB binary |
| Primary LLM (Planning, Synthesis) | Anthropic Claude Sonnet 4.6 | claude-sonnet-4-6 | Planner, sub-agent, synthesiser | Best reasoning-to-cost ratio for research tasks |
| Fallback LLM | Azure OpenAI GPT-4o | 2024-10-01-preview | Provider redundancy | Separate infrastructure from Anthropic; comparable quality |
| Local LLM | Ollama (Llama 3.3 70B) | llama3.3:70b | Last-resort fallback, cheap decomposition | Zero external dependency; runs on local GPU |
| Web Search | Tavily | tavily-python 0.7.23 | Primary retrieval | AI-optimised structured results; async SDK; `include_raw_content` returns full pages; 1,000 RPM |
| Content Extraction | Trafilatura | 2.0.0 | HTML-to-Markdown conversion | Best F1 score (0.883) in academic benchmarks; Apache 2.0 license |
| Content Extraction Fallback | Jina Reader API | r.jina.ai | JS-rendered pages, anti-bot bypass | Headless Chrome rendering; free tier 100 RPM |
| Knowledge Graph | PostgreSQL + Apache AGE | PG 16, AGE 1.5.0+ | Entity/relationship storage, provenance chains, Cypher queries | Single database with relational data; no additional infrastructure |
| Vector Search | PostgreSQL + pgvector | 0.8.2 | Embedding similarity search for RAG | Coexists with AGE in same PG instance; HNSW indexes; iterative scan for filtered queries |
| GraphRAG Framework | LightRAG | Latest | Graph+vector hybrid retrieval | Native `AGEStorage` and `PGVectorStorage` backends; incremental graph updates |
| Reranking | sentence-transformers CrossEncoder | 5.3.0 | Search result reranking | ms-marco-MiniLM-L6-v2: 22.7M params, 55ms/100 docs on GPU |
| Citation Verification | sentence-transformers CrossEncoder | 5.3.0 | NLI-based claim verification | nli-deberta-v3-base: 90.04% MNLI accuracy, 5ms per pair on GPU |
| Time-Series Metrics | TimescaleDB | Latest | Agent performance observability | Hypertables for search latency, token usage, source quality; continuous aggregates for dashboards |
| Relational Persistence | PostgreSQL | 16 | Task state, user data, research history | Existing BFA component; ACID transactions across graph, vector, and relational data |

### 1.2 Python Dependencies

```
# requirements.txt
pydantic-ai[anthropic,openai]>=1.72.0
pydantic-settings>=2.7.0
faststream[nats]>=0.6.0
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
tavily-python>=0.7.23
trafilatura>=2.0.0
asyncpg>=0.30.0
httpx>=0.28.0
sentence-transformers>=5.3.0
pgvector>=0.3.6
lightrag-hku>=1.0.0
spacy>=3.8.0
```

Post-install: `python -m spacy download en_core_web_sm` (included in Docker build step, see Section 1.3).

### 1.3 Infrastructure Dependencies

```yaml
# docker-compose.yml (core services)
services:
  postgres:
    image: apache/age:PG16_latest
    ports: ["5432:5432"]
    environment:
      POSTGRES_DB: genos_research
      POSTGRES_USER: genos
      POSTGRES_PASSWORD: ${PG_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    command: >
      postgres
        -c shared_preload_libraries=age
        -c shared_buffers=8GB
        -c work_mem=512MB
        -c maintenance_work_mem=2GB
        -c effective_cache_size=24GB
        -c max_parallel_maintenance_workers=4

  nats:
    image: nats:2.10-alpine
    ports: ["4222:4222", "8222:8222"]
    command: ["--jetstream", "--store_dir=/data", "-m", "8222"]
    volumes:
      - natsdata:/data
```

Post-startup SQL initialisation:

```sql
-- Load extensions
CREATE EXTENSION IF NOT EXISTS age;
CREATE EXTENSION IF NOT EXISTS vector;

-- Create research knowledge graph
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT * FROM ag_catalog.create_graph('research_kg');

-- Set search_path at database level (avoids per-connection LOAD issue with PgBouncer)
ALTER DATABASE genos_research SET search_path = ag_catalog, "$user", public;
```

### 1.4 Unified Configuration Model

All tuneable parameters across the system are defined in a single `pydantic-settings` model. Every other module imports from this model. No magic numbers in code.

```python
# src/config.py

from pydantic_settings import BaseSettings
from pydantic import Field


class AppConfig(BaseSettings):
    """Single source of truth for all configuration.

    Values are loaded from environment variables (prefixed GENOS_),
    a .env file, or defaults defined here. Every parameter includes
    its valid range and rationale as a comment.
    """

    model_config = {"env_prefix": "GENOS_"}

    # ── LLM Providers ──
    anthropic_api_key: str
    azure_openai_key: str
    azure_openai_endpoint: str
    azure_openai_api_version: str = "2024-10-01-preview"
    ollama_base_url: str = "http://localhost:11434/v1"

    primary_model: str = "claude-sonnet-4-6"
    # Rationale: Best reasoning-to-cost ratio for research; used by planner and synthesiser.
    fallback_model: str = "gpt-4o"
    # Rationale: Separate infrastructure from Anthropic for provider resilience.
    local_model: str = "llama3.3:70b"
    # Rationale: Zero external dependency for last-resort fallback.

    # ── Search & Extraction ──
    tavily_api_key: str
    tavily_max_results: int = Field(default=8, ge=1, le=20)
    # Rationale: 8 balances breadth with token cost. >10 increases noise without proportional quality.
    tavily_search_depth: str = "advanced"
    # Rationale: "advanced" (2 credits) provides deeper results; "basic" (1 credit) for simple lookups.
    extraction_max_chars: int = Field(default=6000, ge=1000, le=20000)
    # Rationale: 6000 chars fits most article bodies within sub-agent token budget.
    extraction_timeout_seconds: float = Field(default=15.0, ge=5.0, le=60.0)
    # Rationale: 15s covers slow sites; >30s blocks the sub-agent pipeline.
    jina_timeout_seconds: float = Field(default=15.0, ge=5.0, le=60.0)

    # ── Orchestrator ──
    max_sub_agents: int = Field(default=7, ge=2, le=10)
    # Rationale: 7 covers most research decompositions; >7 increases synthesis complexity without proportional quality.
    token_budget_planner: int = Field(default=2000, ge=500, le=4000)
    token_budget_per_sub_agent: int = Field(default=10000, ge=2000, le=20000)
    # Rationale: 10000 total tokens allows 3-5 search+extract cycles (each consuming ~1500 input tokens)
    # plus structured output (~1500 output tokens). The v1.1 default of 4000 was insufficient: a single
    # Tavily response with include_raw_content=True can exceed 2000 input tokens alone.
    token_budget_synthesis: int = Field(default=12000, ge=4000, le=24000)
    # Rationale: 12000 tokens supports comprehensive reports (~3000 words) with full source deduplication.
    request_limit_planner: int = Field(default=3, ge=1, le=10)
    request_limit_per_sub_agent: int = Field(default=15, ge=3, le=30)
    # Rationale: 15 requests covers 5 searches + 5 extractions + 5 graph queries.
    enable_gap_analysis: bool = True
    min_complexity_for_gap_pass: int = Field(default=7, ge=1, le=10)
    # Rationale: Gap analysis adds latency; only worthwhile for complex (7+) queries.
    max_gap_sub_questions: int = Field(default=3, ge=1, le=5)

    # ── Timeouts ──
    sub_agent_timeout_seconds: float = Field(default=90.0, ge=30.0, le=300.0)
    # Rationale: 90s covers worst-case LLM latency + multiple tool calls.
    synthesis_timeout_seconds: float = Field(default=120.0, ge=60.0, le=300.0)
    sse_heartbeat_seconds: float = Field(default=30.0, ge=10.0, le=60.0)
    total_research_timeout_seconds: float = Field(default=600.0, ge=120.0, le=1800.0)
    # Rationale: 10 minutes covers complexity-10 tasks with gap analysis.

    # ── NATS ──
    nats_url: str = "nats://localhost:4222"
    nats_max_ack_pending: int = Field(default=50, ge=10, le=500)
    # Rationale: Task-level distribution. Each orchestrator instance handles one task at a time.
    # 50 allows for 10 orchestrator instances with buffering.
    nats_ack_wait_seconds: int = Field(default=120, ge=60, le=300)
    nats_max_deliver: int = Field(default=3, ge=1, le=5)
    nats_pull_batch_size: int = Field(default=5, ge=1, le=20)

    # ── PostgreSQL ──
    pg_dsn: str = "postgresql://genos@localhost:5432/genos_research"
    pg_pool_min_size: int = Field(default=5, ge=1, le=20)
    pg_pool_max_size: int = Field(default=20, ge=5, le=100)

    # ── pgvector ──
    embedding_dimensions: int = Field(default=1536, ge=256, le=4096)
    # Rationale: 1536 matches OpenAI ada-002; adjust if switching embedding model.
    hnsw_m: int = Field(default=16, ge=8, le=64)
    # Rationale: 16 balances recall with index build time for <1M vectors.
    hnsw_ef_construction: int = Field(default=200, ge=64, le=500)
    # Rationale: 200 provides good recall; higher values slow index builds.
    vector_similarity_threshold: float = Field(default=0.7, ge=0.5, le=0.95)
    # Rationale: 0.7 cosine similarity is the blocking threshold for entity resolution candidates.

    # ── NLI Verification ──
    nli_model_name: str = "cross-encoder/nli-deberta-v3-base"
    nli_entailment_threshold: float = Field(default=0.5, ge=0.3, le=0.9)
    # Rationale: 0.5 balances false negatives (missed contradictions) with false positives (over-flagging).
    nli_batch_size: int = Field(default=32, ge=8, le=128)
    reranker_model_name: str = "cross-encoder/ms-marco-MiniLM-L6-v2"

    # ── Entity Resolution ──
    entity_resolution_similarity_threshold: float = Field(default=0.7, ge=0.5, le=0.95)
    # Rationale: 0.7 cosine similarity catches near-duplicates without merging distinct entities.
    entity_resolution_merge_threshold: float = Field(default=0.8, ge=0.6, le=0.95)
    # Rationale: 0.8 combined score required for merge; below this, entities remain separate.

    # ── Minimum Viable Results ──
    min_sub_agent_results_for_synthesis: int = Field(default=2, ge=1, le=5)
    # Rationale: Synthesiser needs at least 2 sub-agent findings to produce a meaningful report.
    # Below this threshold, the task fails with INSUFFICIENT_FINDINGS.
    min_source_count_for_claim: int = Field(default=1, ge=1, le=3)
    # Rationale: Every claim must reference at least 1 source. Unsourced claims are dropped.

    # ── Cost Observability ──
    cost_alert_threshold_usd: float = Field(default=3.0, ge=0.5, le=50.0)
    # Rationale: A comprehensive research task consumes ~50K input + ~10K output tokens.
    # At Claude Sonnet pricing (~$3/M input, ~$15/M output), that's ~$0.30 per task.
    # Alert at $3.00 flags tasks consuming 10x the expected cost.
    cost_per_1k_input_tokens: float = Field(default=0.003, ge=0.0, le=1.0)
    # Rationale: Used for real-time cost estimation. Update when provider pricing changes.
    cost_per_1k_output_tokens: float = Field(default=0.015, ge=0.0, le=1.0)

    # ── Graph Retention ──
    graph_edge_max_age_days: int = Field(default=365, ge=30, le=3650)
    # Rationale: Bi-temporal edges accumulate indefinitely. This parameter defines the
    # retention window for expired edges (t_expired IS NOT NULL). Active edges are never
    # compacted. Compaction logic is out of scope (Section 12.0) but the threshold is
    # defined here so it can be enforced when compaction is implemented.
```

**Files involved:** `src/config.py`

### 1.4.1 Anti-patterns (Configuration)

- **Do not hardcode values in agent code, tool functions, or SQL.** Import from `AppConfig`. If a value is not in `AppConfig`, add it there before using it.
- **Do not use `os.environ` directly.** Pydantic-settings handles environment variable loading, type coercion, and validation.
- **Do not create module-level config singletons.** Pass `AppConfig` via FastAPI's dependency injection or PydanticAI's `deps` context. This enables per-test configuration overrides.

---

## 2.0 System Architecture

### 2.1 High-Level Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI HTTP Layer                                             │
│  ├── POST /v1/research          → Publish to NATS              │
│  ├── GET  /v1/research/{id}/stream → SSE (NATS-backed)         │
│  ├── GET  /v1/research/{id}     → Final report from PG         │
│  └── GET  /v1/health            → Liveness check               │
├─────────────────────────────────────────────────────────────────┤
│  FastStream / NATS JetStream Message Layer                      │
│  ├── research.task              → Orchestrator Worker (N instances)
│  │     ├── Phase 1: Planner Agent → ResearchPlan                │
│  │     ├── Phase 2: Sub-Agents via asyncio.gather (in-process)  │
│  │     │     ├── Tavily search, Trafilatura/Jina extraction     │
│  │     │     └── Knowledge graph lookup (AGE)                   │
│  │     ├── Phase 2.5: Gap Analysis (optional, in-process)       │
│  │     ├── Phase 3: Synthesiser Agent → FinalReport             │
│  │     ├── Phase 4: NLI Citation Verification                  │
│  │     └── Phase 5: Persist report + async graph write-back     │
│  ├── research.progress.{task_id} → SSE relay (consumed by API) │
│  └── research.graph_writeback   → Graph Writer Worker           │
│        └── Batched Cypher writes to AGE (async, non-blocking)   │
├─────────────────────────────────────────────────────────────────┤
│  PostgreSQL 16 (Unified Data Layer)                             │
│  ├── Apache AGE     → Knowledge graph (entities, claims, edges) │
│  ├── pgvector       → Document chunk embeddings (HNSW)          │
│  ├── Relational     → Tasks, subtasks, users, config            │
│  └── TimescaleDB    → Agent metrics hypertable                  │
└─────────────────────────────────────────────────────────────────┘
```

**Architecture decision (v1.2):** Sub-agents run in-process via `asyncio.gather`, not as distributed NATS workers. NATS distributes at the research-task level: each orchestrator instance pulls one task from `research.task`, runs the full lifecycle (plan → delegate → synthesise → verify → persist), and publishes progress to `research.progress.{task_id}`. Horizontal scaling is achieved by deploying multiple orchestrator instances, each pulling different tasks. This resolves the v1.1 contradiction between the `asyncio.gather` pattern in the orchestrator code and the "20+ distributed workers" described in the architecture diagram. Graph write-back is genuinely backgrounded via a separate `research.graph_writeback` NATS subject consumed by a dedicated worker.

### 2.2 Request Lifecycle

1. **User submits query** via `POST /v1/research`. FastAPI validates, creates a `research_tasks` row (status: `accepted`), publishes to `research.task` NATS subject. Returns `201 Created` with task_id immediately.
2. **Orchestrator worker** (one of N instances) pulls the task from JetStream. Updates status to `planning`. Calls the planner agent, produces a `ResearchPlan` with 3–7 sub-questions.
3. **Sub-agents run in-process** via `asyncio.gather`. Each sub-agent executes independently within the orchestrator's event loop: checks knowledge graph, searches Tavily, extracts content, produces `SubAgentFindings`. No NATS messaging between sub-agents.
4. **Progress events** published to `research.progress.{task_id}` NATS subject after each sub-agent completes. The SSE endpoint subscribes to this subject (see Section 7.4).
5. **Synthesiser agent** receives all findings, deduplicates sources, resolves contradictions, produces a `FinalReport` with inline citations. NLI cross-encoder verifies each citation. Report stored in PostgreSQL.
6. **Graph write-back** published as a message to `research.graph_writeback` NATS subject. A dedicated graph writer worker processes this asynchronously (see Section 3.7).
7. **User receives** the final report via SSE stream or GET endpoint.

### 2.2.1 Module Dependency Map

This section defines which module imports from which and the data types flowing between them. The orchestrator calls agents directly via Python function calls; NATS is the transport between the HTTP layer, the orchestrator, and the workers.

```
api/routes.py
  ├── imports → api/schemas.py (ResearchRequest, ResearchResponse, ProgressEvent)
  ├── imports → config.py (AppConfig via FastAPI Depends)
  ├── publishes to NATS → streaming/publishers.py (research.task)
  ├── subscribes to NATS → research.progress.{task_id} (for SSE relay)
  └── reads from → db/models.py (research_tasks table)

streaming/subscribers.py
  ├── subscribes to NATS → research.task (full research lifecycle)
  ├── imports → orchestrator/coordinator.py (execute_research)
  ├── imports → config.py (AppConfig)
  └── calls → streaming/publishers.py (publish progress events)

streaming/graph_worker.py
  ├── subscribes to NATS → research.graph_writeback (dedicated worker)
  ├── imports → graph/writeback.py (write_research_to_graph)
  └── imports → config.py (AppConfig)

orchestrator/coordinator.py
  ├── imports → agents/planner.py (planner_agent)
  ├── imports → agents/researcher.py (create_sub_agent, build_sub_agent_prompt)
  ├── imports → agents/synthesiser.py (create_synthesiser_agent, build_synthesis_prompt)
  ├── imports → verification/nli_verifier.py (NLICitationVerifier)
  ├── imports → errors/taxonomy.py (ErrorCode, ResearchError)
  ├── publishes to NATS → research.progress.{task_id} (progress events)
  ├── publishes to NATS → research.graph_writeback (graph write-back payload)
  └── imports → config.py (AppConfig)
  NOTE: Sub-agents run in-process via asyncio.gather. No NATS messaging between sub-agents.

agents/planner.py
  ├── imports → agents/models.py (ResearchPlan)
  └── no tool imports (planner has no tools)

agents/researcher.py
  ├── imports → agents/models.py (SubAgentFindings)
  ├── imports → tools/search.py (search_web)
  ├── imports → tools/extract.py (extract_page)
  ├── imports → tools/knowledge_graph.py (check_knowledge_graph)
  └── imports → tools/reranker.py (rerank_results)

agents/synthesiser.py
  ├── imports → agents/models.py (FinalReport, ResearchPlan, SubAgentFindings)
  └── no tool imports (synthesiser has no tools)

graph/writeback.py
  ├── imports → agents/models.py (FinalReport, CitedClaim, SourceRef)
  ├── imports → graph/age_client.py (AGEClient)
  ├── imports → graph/entity_resolution.py (resolve_entities)
  ├── imports → graph/ner.py (extract_entities_from_text)
  └── imports → config.py (AppConfig)
```

**Data flow direction:** HTTP request → NATS `research.task` → orchestrator (in-process: planner → sub-agents via asyncio.gather → synthesiser → NLI verifier) → PostgreSQL (report) → NATS `research.progress.{task_id}` → SSE client. Graph write-back: NATS `research.graph_writeback` → graph writer worker → AGE.

### 2.3 API Contracts

#### 2.3.1 Request/Response Models

```python
# src/api/schemas.py

from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime


class ResearchDepth(str, Enum):
    BRIEF = "brief"          # Target ~500 words, 2-3 sub-questions
    STANDARD = "standard"    # Target ~1500 words, 3-5 sub-questions
    COMPREHENSIVE = "comprehensive"  # Target ~3000+ words, 5-7 sub-questions


class ResearchRequest(BaseModel):
    """POST /v1/research request body."""
    query: str = Field(
        min_length=10, max_length=2000,
        description="The research question. Must be a complete question or instruction.",
        examples=["How does Apache AGE compare to Neo4j for knowledge graph storage in PostgreSQL-based architectures?"],
    )
    depth: ResearchDepth = Field(
        default=ResearchDepth.STANDARD,
        description="Controls sub-question count, token budgets, and target output length.",
    )
    source_preferences: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="Preferred source types: academic, news, official, technical, any.",
    )
    callback_url: str | None = Field(
        default=None,
        description="Webhook URL for completion notification. POST with ResearchResponse body.",
    )


class TaskStatus(str, Enum):
    ACCEPTED = "accepted"
    PLANNING = "planning"
    RESEARCHING = "researching"
    SYNTHESISING = "synthesising"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class ResearchTaskResponse(BaseModel):
    """POST /v1/research response (immediate acknowledgement)."""
    task_id: str = Field(description="UUID for tracking. Use in GET and SSE endpoints.")
    status: TaskStatus
    stream_url: str = Field(description="SSE endpoint for real-time progress.")
    poll_url: str = Field(description="GET endpoint for final report.")
    estimated_duration_seconds: int = Field(
        description="Rough estimate based on depth. brief=30, standard=60, comprehensive=120.",
    )


class ProgressEvent(BaseModel):
    """SSE event payload for GET /v1/research/{task_id}/stream."""
    task_id: str
    status: TaskStatus
    phase: str = Field(description="Current phase: planning, researching, synthesising, verifying.")
    progress_pct: float = Field(ge=0.0, le=100.0, description="Percentage complete within current phase.")
    sub_agents_completed: int
    sub_agents_total: int
    message: str = Field(description="Human-readable progress message.")
    timestamp: datetime


class ErrorResponse(BaseModel):
    """Standard error response body for all error HTTP status codes."""
    error_code: str = Field(description="Machine-readable error code from the error taxonomy (Section 2.5).")
    message: str = Field(description="Human-readable error description.")
    task_id: str | None = Field(default=None, description="Task ID if the error relates to a specific task.")
    retry_after_seconds: int | None = Field(
        default=None,
        description="Seconds to wait before retrying. Present only for retryable errors.",
    )


class ResearchResponse(BaseModel):
    """GET /v1/research/{task_id} response (final report)."""
    task_id: str
    status: TaskStatus
    query: str
    report: "FinalReport | None" = Field(
        default=None,
        description="Present when status is COMPLETED. See Section 4.3 for FinalReport schema.",
    )
    error: ErrorResponse | None = Field(
        default=None,
        description="Present when status is FAILED or TIMED_OUT.",
    )
    started_at: datetime
    completed_at: datetime | None
    duration_seconds: float | None
    token_usage: "TokenUsageSummary | None"


class TokenUsageSummary(BaseModel):
    """Aggregate token consumption for cost tracking."""
    planner_input_tokens: int
    planner_output_tokens: int
    sub_agent_input_tokens: int
    sub_agent_output_tokens: int
    synthesiser_input_tokens: int
    synthesiser_output_tokens: int
    total_input_tokens: int
    total_output_tokens: int
    primary_model_calls: int
    fallback_model_calls: int
    local_model_calls: int
```

#### 2.3.2 Endpoint Specifications

| Endpoint | Method | Request Body | Success Response | Error Responses | Notes |
|---|---|---|---|---|---|
| `/v1/research` | POST | `ResearchRequest` | `201 Created` → `ResearchTaskResponse` | `400` (invalid query), `429` (rate limited), `503` (all LLM providers down) | Publishes to NATS and returns immediately |
| `/v1/research/{task_id}` | GET | None | `200 OK` → `ResearchResponse` | `404` (unknown task_id), `202 Accepted` (still in progress, body contains `ProgressEvent`) | Returns `202` with current progress if not yet complete |
| `/v1/research/{task_id}/stream` | GET | None | `200 OK` → SSE stream of `ProgressEvent` | `404` (unknown task_id), `410 Gone` (task already completed, use GET) | Final event has `status: completed` or `status: failed` |
| `/v1/health` | GET | None | `200 OK` → `{"status": "healthy", "nats": true, "pg": true}` | `503` → `{"status": "degraded", "nats": false, "pg": true}` | Checks NATS and PostgreSQL connectivity |

#### 2.3.3 Anti-patterns (API)

- **Do not return 200 for async task creation.** Use 201 Created. The resource (the task) is being created, not retrieved.
- **Do not return 404 for in-progress tasks on the GET endpoint.** Return 202 Accepted with a progress body. 404 means the task_id does not exist.
- **Do not mix SSE event types.** Every SSE event uses `event: progress` with a `ProgressEvent` JSON payload. Do not send raw strings or untyped JSON.
- **Do not omit `Content-Type: text/event-stream` on the SSE endpoint.** FastAPI's `EventSourceResponse` handles this, but verify it in integration tests.

### 2.4 Directory Structure

```
genos-research/
├── pyproject.toml
├── requirements.txt
├── docker-compose.yml
├── alembic/                          # Database migrations
│   ├── alembic.ini
│   └── versions/
├── src/
│   ├── __init__.py
│   ├── config.py                     # AppConfig (Section 1.4)
│   ├── main.py                       # FastAPI + FastStream app factory
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py                 # HTTP endpoints (Section 2.3.2)
│   │   ├── schemas.py               # Request/response models (Section 2.3.1)
│   │   └── sanitise.py              # Input sanitisation (Section 2.7.2)
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── planner.py                # Planner agent + prompt (Section 5.1)
│   │   ├── researcher.py             # Sub-agent factory + prompt template (Section 5.2)
│   │   ├── synthesiser.py            # Synthesis agent + prompt (Section 5.4)
│   │   └── models.py                 # Shared Pydantic output models (Section 4.3)
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── coordinator.py            # Research lifecycle (Section 6.2)
│   │   ├── aggregator.py             # Collects sub-agent results
│   │   └── gap_analysis.py           # Optional second-pass logic
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── search.py                 # Tavily search tool (Section 5.3)
│   │   ├── extract.py                # Trafilatura + Jina extraction (Section 5.3)
│   │   ├── knowledge_graph.py        # AGE graph queries (Section 5.3)
│   │   └── reranker.py               # Cross-encoder reranking
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── age_client.py             # AGE Cypher wrapper (Section 3.8)
│   │   ├── schema.py                 # Graph schema (Section 3.1)
│   │   ├── entity_resolution.py      # Deduplication pipeline (Section 3.5)
│   │   ├── ner.py                    # spaCy NER extraction (Section 3.9)
│   │   └── writeback.py              # Post-synthesis graph update (Section 3.7)
│   ├── verification/
│   │   ├── __init__.py
│   │   └── nli_verifier.py           # NLI citation verification (Section 8.0)
│   ├── streaming/
│   │   ├── __init__.py
│   │   ├── nats_config.py            # JetStream stream/consumer definitions (Section 7.1)
│   │   ├── publishers.py             # Task publishing helpers
│   │   ├── subscribers.py            # Orchestrator subscriber (Section 7.2)
│   │   └── graph_worker.py           # Graph write-back worker (Section 7.3)
│   ├── errors/
│   │   ├── __init__.py
│   │   └── taxonomy.py               # Error codes and exception classes (Section 2.6)
│   └── db/
│       ├── __init__.py
│       ├── pool.py                   # asyncpg connection pool with AGE init
│       ├── models.py                 # SQLAlchemy/raw SQL table definitions
│       └── migrations.py             # Schema setup helpers
└── tests/
    ├── conftest.py                   # Shared fixtures (Section 10.2)
    ├── fixtures/                     # Known-good test data (Section 10.3)
    │   ├── plans/                    # ResearchPlan JSON fixtures
    │   ├── findings/                 # SubAgentFindings JSON fixtures
    │   └── reports/                  # FinalReport JSON fixtures
    ├── test_planner.py
    ├── test_researcher.py
    ├── test_synthesiser.py
    ├── test_graph.py
    ├── test_api.py                   # HTTP contract tests
    ├── test_error_handling.py        # Error taxonomy coverage
    └── test_integration.py
```

### 2.5 Behavioural Invariants

These are verifiable assertions about system behaviour. Each invariant maps to one or more test cases. An implementation that violates any invariant is incorrect regardless of whether the code compiles and the Pydantic models validate.

#### 2.5.1 Planning Invariants

| ID | Invariant | Test Method |
|---|---|---|
| P-01 | A ResearchPlan for a query with `estimated_complexity` <= 3 MUST produce no more than 4 sub-questions. | Unit test: submit 5 simple queries to planner, assert `len(plan.sub_questions) <= 4` for all. |
| P-02 | Every sub-question's `search_hints` first entry MUST be 2-4 words. | Unit test: regex validation on `search_hints[0]` for all sub-questions. |
| P-03 | Sub-questions with `depends_on` populated MUST NOT create circular dependencies. | Unit test: topological sort of `depends_on` graph must not raise `CycleError`. |
| P-04 | The planner MUST NOT produce a ResearchPlan with `synthesis_strategy` outside the enumerated values: comparative, chronological, thematic, hierarchical, argumentative. | Enforced by Pydantic model (add `Literal` constraint). |
| P-05 | `depends_on` uses 0-based indices. Index 0 is the first sub-question. Every index in `depends_on` MUST be less than the total number of sub-questions and MUST NOT reference the sub-question's own index. | Unit test: validate all `depends_on` values are in range `[0, len(sub_questions))` and do not self-reference. |

#### 2.5.2 Research Invariants

| ID | Invariant | Test Method |
|---|---|---|
| R-01 | Every `Claim` in `SubAgentFindings` MUST reference at least one source by index, and every referenced index MUST exist in `sources_used`. | Unit test: cross-reference `source_indices` against `len(sources_used)`. |
| R-02 | A sub-agent MUST call `check_knowledge_graph` before `search_web` for its first action. | Integration test: mock both tools, assert call order. |
| R-03 | A sub-agent MUST NOT exceed `config.request_limit_per_sub_agent` tool calls. | Enforced by PydanticAI `UsageLimits(request_limit=...)`. |
| R-04 | If a sub-agent's token budget is exhausted mid-execution, it MUST return partial findings with `confidence < 0.5` and a gap entry stating "token budget exhausted". | Integration test: set `token_budget=500`, verify output structure. |
| R-05 | Sub-agents MUST NOT include sources in `sources_used` that were not actually referenced by any claim. | Unit test: every source in `sources_used` must appear in at least one `claim.source_indices`. |

#### 2.5.3 Synthesis Invariants

| ID | Invariant | Test Method |
|---|---|---|
| S-01 | Every factual statement in `ReportSection.content` MUST contain at least one `[N]` citation, and every `[N]` MUST reference a valid index in `FinalReport.sources`. | Unit test: regex extraction of `[N]` references, cross-reference against `len(report.sources)`. |
| S-02 | The `executive_summary` MUST be written after all sections are complete (i.e., it must reflect the actual report content, not be a generic introduction). | Manual review checkpoint; automated: verify executive_summary contains at least 2 entity names that appear in sections. |
| S-03 | Claims with NLI `VerificationResult.CONTRADICTED` MUST appear in `FinalReport.limitations` with the contradicted claim text and source URL. | Integration test: inject a known-contradicted claim, verify it appears in limitations. |
| S-04 | Claims with confidence < 0.3 from sub-agent findings MUST NOT appear in the final report without an explicit uncertainty qualifier (e.g., "unverified", "one source suggests"). | Automated: scan report sections for claims matching low-confidence sub-agent claims, verify qualifier presence. |
| S-05 | The synthesiser MUST produce at least 1 and at most 3 `suggested_follow_ups`, and none may be a restatement of the original query or any sub-question. | Unit test: semantic similarity check between follow-ups and original query/sub-questions (cosine < 0.85). |

#### 2.5.4 Orchestration Invariants

| ID | Invariant | Test Method |
|---|---|---|
| O-01 | If fewer than `config.min_sub_agent_results_for_synthesis` sub-agents return findings, the task MUST fail with error code `INSUFFICIENT_FINDINGS`, not proceed to synthesis. | Integration test: mock all sub-agents to fail except 1, verify task status is `FAILED`. |
| O-02 | Gap analysis MUST NOT execute if `plan.estimated_complexity` < `config.min_complexity_for_gap_pass`. | Integration test: submit complexity-3 query, verify no gap analysis sub-agents spawned. |
| O-03 | The total research lifecycle MUST NOT exceed `config.total_research_timeout_seconds`. If it does, the task MUST transition to `TIMED_OUT` with partial results if available. | Integration test: set timeout to 5 seconds, inject slow LLM mock, verify timeout behaviour. |
| O-04 | Every task status transition MUST be persisted to the `research_tasks` table before the next phase begins. | Integration test: inject failure at each phase boundary, verify database state. |
| O-05 | Dependent sub-questions (those with `depends_on` populated) MUST NOT execute until all their dependencies have completed. | Integration test: inject slow dependency, verify dependent sub-agent waits. |

#### 2.5.5 Graph Invariants

| ID | Invariant | Test Method |
|---|---|---|
| G-01 | No edge in the knowledge graph is ever deleted. Invalidation sets `t_expired` and `valid_to`; a new edge is created. | Integration test: update a claim, verify old edge has `t_expired` set, new edge exists. |
| G-02 | Entity resolution MUST NOT merge two entities with a combined similarity score below `config.entity_resolution_merge_threshold`. | Unit test: fixture pair with score 0.75, verify no merge occurs when threshold is 0.8. |
| G-03 | Every `Claim` node in the graph MUST have at least one `EXTRACTED_FROM` edge to a `Source` node. | Database constraint or post-write verification query. |
| G-04 | Every `ResearchTask` node MUST have a `PRODUCED_BY` edge linking it to the task's agent configuration. | Post-write verification query. |

### 2.6 Error Taxonomy

Every error condition the system can encounter maps to a specific error code, HTTP status, user-facing message, and recovery behaviour. The orchestrator catches exceptions and maps them to the appropriate error code before persisting task status.

```python
# src/errors/taxonomy.py

from enum import Enum
from dataclasses import dataclass


class ErrorCode(str, Enum):
    # ── LLM Provider Errors ──
    LLM_ALL_PROVIDERS_FAILED = "LLM_ALL_PROVIDERS_FAILED"
    LLM_PRIMARY_FAILED = "LLM_PRIMARY_FAILED"  # Informational; fallback engaged
    LLM_OUTPUT_VALIDATION_FAILED = "LLM_OUTPUT_VALIDATION_FAILED"
    LLM_CONTEXT_WINDOW_EXCEEDED = "LLM_CONTEXT_WINDOW_EXCEEDED"

    # ── Search & Extraction Errors ──
    SEARCH_RATE_LIMITED = "SEARCH_RATE_LIMITED"
    SEARCH_NO_RESULTS = "SEARCH_NO_RESULTS"
    EXTRACTION_ALL_METHODS_FAILED = "EXTRACTION_ALL_METHODS_FAILED"

    # ── Orchestration Errors ──
    INSUFFICIENT_FINDINGS = "INSUFFICIENT_FINDINGS"
    PLANNING_FAILED = "PLANNING_FAILED"
    SYNTHESIS_FAILED = "SYNTHESIS_FAILED"
    TASK_TIMED_OUT = "TASK_TIMED_OUT"
    CIRCULAR_DEPENDENCY = "CIRCULAR_DEPENDENCY"

    # ── Infrastructure Errors ──
    NATS_PUBLISH_FAILED = "NATS_PUBLISH_FAILED"
    DATABASE_ERROR = "DATABASE_ERROR"
    GRAPH_WRITE_FAILED = "GRAPH_WRITE_FAILED"

    # ── Input Errors ──
    INVALID_QUERY = "INVALID_QUERY"
    RATE_LIMITED = "RATE_LIMITED"


@dataclass
class ErrorSpec:
    code: ErrorCode
    http_status: int
    message_template: str
    retryable: bool
    retry_after_seconds: int | None
    recovery_action: str


ERROR_SPECS: dict[ErrorCode, ErrorSpec] = {
    ErrorCode.LLM_ALL_PROVIDERS_FAILED: ErrorSpec(
        code=ErrorCode.LLM_ALL_PROVIDERS_FAILED,
        http_status=503,
        message_template="All LLM providers are currently unavailable. The task has been queued for retry.",
        retryable=True,
        retry_after_seconds=60,
        recovery_action="NATS redelivery will retry the task up to config.nats_max_deliver times with graduated backoff.",
    ),
    ErrorCode.LLM_PRIMARY_FAILED: ErrorSpec(
        code=ErrorCode.LLM_PRIMARY_FAILED,
        http_status=200,  # Not a user-facing error; fallback engaged
        message_template="Primary model unavailable; using fallback provider.",
        retryable=False,
        retry_after_seconds=None,
        recovery_action="FallbackModel automatically routes to next provider. Log for observability.",
    ),
    ErrorCode.LLM_OUTPUT_VALIDATION_FAILED: ErrorSpec(
        code=ErrorCode.LLM_OUTPUT_VALIDATION_FAILED,
        http_status=502,
        message_template="The LLM produced output that does not match the expected schema. Retrying with a different provider.",
        retryable=True,
        retry_after_seconds=5,
        recovery_action="Retry once with the same provider. If validation fails again, fall through to next provider in FallbackModel chain.",
    ),
    ErrorCode.SEARCH_RATE_LIMITED: ErrorSpec(
        code=ErrorCode.SEARCH_RATE_LIMITED,
        http_status=200,  # Sub-agent continues with available results
        message_template="Search API rate limited. Proceeding with results already collected.",
        retryable=False,
        retry_after_seconds=None,
        recovery_action="Sub-agent stops searching and synthesises from results collected so far. Adds 'search rate limited' to gaps_identified.",
    ),
    ErrorCode.SEARCH_NO_RESULTS: ErrorSpec(
        code=ErrorCode.SEARCH_NO_RESULTS,
        http_status=200,  # Sub-agent reports gap
        message_template="No search results found for the given sub-question.",
        retryable=False,
        retry_after_seconds=None,
        recovery_action="Sub-agent returns SubAgentFindings with confidence=0.1 and gap entry. Orchestrator continues with other sub-agents.",
    ),
    ErrorCode.EXTRACTION_ALL_METHODS_FAILED: ErrorSpec(
        code=ErrorCode.EXTRACTION_ALL_METHODS_FAILED,
        http_status=200,  # Sub-agent continues without this source
        message_template="Content extraction failed for URL. Proceeding with search snippets only.",
        retryable=False,
        retry_after_seconds=None,
        recovery_action="Sub-agent uses Tavily snippet content. Does not re-attempt extraction for this URL.",
    ),
    ErrorCode.INSUFFICIENT_FINDINGS: ErrorSpec(
        code=ErrorCode.INSUFFICIENT_FINDINGS,
        http_status=500,
        message_template="Too few sub-agents returned results to produce a meaningful report. {completed} of {total} sub-agents completed.",
        retryable=True,
        retry_after_seconds=30,
        recovery_action="Task status set to FAILED. User may retry with a simpler query or reduced depth.",
    ),
    ErrorCode.PLANNING_FAILED: ErrorSpec(
        code=ErrorCode.PLANNING_FAILED,
        http_status=500,
        message_template="The planner agent failed to decompose the research query.",
        retryable=True,
        retry_after_seconds=10,
        recovery_action="Retry once via NATS redelivery. If planning fails twice, task status set to FAILED.",
    ),
    ErrorCode.SYNTHESIS_FAILED: ErrorSpec(
        code=ErrorCode.SYNTHESIS_FAILED,
        http_status=500,
        message_template="The synthesiser agent failed to produce a final report.",
        retryable=True,
        retry_after_seconds=15,
        recovery_action="Retry once. If synthesis fails twice, return raw sub-agent findings as a degraded report (status: DEGRADED).",
    ),
    ErrorCode.TASK_TIMED_OUT: ErrorSpec(
        code=ErrorCode.TASK_TIMED_OUT,
        http_status=504,
        message_template="Research task exceeded the maximum allowed duration of {timeout} seconds.",
        retryable=False,
        retry_after_seconds=None,
        recovery_action="If synthesis has not started, return TIMED_OUT with no report. If synthesis is in progress, wait an additional 30s for completion. If sub-agents have partial results, attempt synthesis with available findings.",
    ),
    ErrorCode.GRAPH_WRITE_FAILED: ErrorSpec(
        code=ErrorCode.GRAPH_WRITE_FAILED,
        http_status=200,  # Report still delivered; graph update is non-critical
        message_template="Knowledge graph update failed. Report delivered without graph persistence.",
        retryable=True,
        retry_after_seconds=None,
        recovery_action="Log error. Queue a background retry for graph writeback. The report is already persisted in PostgreSQL relational tables. The graph update is eventually consistent, not transactional with report delivery.",
    ),
    ErrorCode.DATABASE_ERROR: ErrorSpec(
        code=ErrorCode.DATABASE_ERROR,
        http_status=503,
        message_template="Database connection failed.",
        retryable=True,
        retry_after_seconds=10,
        recovery_action="asyncpg pool will retry connection. If pool is exhausted, NATS redelivery retries the task.",
    ),
    ErrorCode.INVALID_QUERY: ErrorSpec(
        code=ErrorCode.INVALID_QUERY,
        http_status=400,
        message_template="Invalid research query: {reason}",
        retryable=False,
        retry_after_seconds=None,
        recovery_action="Return 400 with validation error details. Do not create a task row.",
    ),
    ErrorCode.RATE_LIMITED: ErrorSpec(
        code=ErrorCode.RATE_LIMITED,
        http_status=429,
        message_template="Too many research requests. Try again in {retry_after} seconds.",
        retryable=True,
        retry_after_seconds=60,
        recovery_action="Return 429 with Retry-After header. Do not create a task row.",
    ),
}
```

#### 2.6.1 Error Handling in Sub-Agents

Sub-agent errors do not terminate the research task. The orchestrator handles them as follows:

| Error Condition | Sub-Agent Behaviour | Orchestrator Behaviour |
|---|---|---|
| Tavily returns 429 | Stop searching. Return findings with available results. Add gap: "search rate limited". | Continue with other sub-agents. |
| Token budget exhausted | Return partial `SubAgentFindings` with `confidence < 0.5`. | Include in synthesis with reduced weight. |
| LLM output fails Pydantic validation | PydanticAI retries once with same prompt. If retry fails, raise `UnexpectedModelBehavior`. | `FallbackModel` routes to next provider. If all fail, mark sub-agent as failed, increment failed counter. |
| Content extraction fails for all methods | Return findings using Tavily snippets only. | No action needed. |
| Knowledge graph query fails | Skip graph lookup. Proceed to web search. Log error. | No action needed. |
| Sub-agent times out (>90s) | N/A (orchestrator cancels the task). | Mark sub-agent as timed out. If enough other sub-agents completed, proceed to synthesis. |

#### 2.6.2 Anti-patterns (Error Handling)

- **Do not catch bare `Exception` and return `None` silently.** Every exception must be logged with the task_id, sub-question_id, error type, and traceback. Section 6.2's `run_sub_agent` must be updated to log before returning `None`.
- **Do not retry indefinitely.** Every retry has a maximum count (defined in `AppConfig` or NATS `MaxDeliver`). After max retries, fail explicitly.
- **Do not treat graph write failures as task failures.** The graph is eventually consistent. The report is the primary deliverable. See `GRAPH_WRITE_FAILED` in the error taxonomy.
- **Do not return HTTP 500 for expected error conditions.** Rate limiting is 429, timeout is 504, provider unavailability is 503. Reserve 500 for genuinely unexpected failures.

**Files involved:** `src/errors/taxonomy.py`, `src/orchestrator/coordinator.py`, `src/api/routes.py`

### 2.7 Security Boundaries

This section defines the security perimeter for the research agent platform. Authentication and authorisation remain out of scope (Section 12.0), but the following boundaries apply to all implementations.

#### 2.7.1 Secret Management

| Secret | Storage | Access Method | Rotation |
|---|---|---|---|
| `anthropic_api_key` | Secrets manager (HashiCorp Vault, AWS Secrets Manager, or k8s Secrets) | Injected as environment variable at deploy time | Rotate via provider console; redeploy to pick up new value |
| `azure_openai_key` | Same as above | Same | Same |
| `tavily_api_key` | Same as above | Same | Same |
| `pg_dsn` (contains password) | Same as above | Same | Rotate via PostgreSQL `ALTER ROLE` |

**Development override:** `.env` files are permitted in local development only. The `.env` file MUST be in `.gitignore`. Production deployments MUST NOT use `.env` files.

#### 2.7.2 Input Sanitisation

The `ResearchRequest.query` field (max 2000 chars) is passed directly to LLM prompts. This creates a prompt injection surface. Mitigations:

1. **Structural isolation.** The query appears in the user message, never in the system prompt. The planner's system prompt (Section 5.1) is static and cannot be overridden by query content.
2. **Output schema enforcement.** All agent outputs are validated against Pydantic models (Section 4.3). If the LLM produces output outside the schema (e.g., tool calls injected via the query), PydanticAI raises `UnexpectedModelBehavior` and the FallbackModel routes to the next provider.
3. **No shell execution.** No agent tool executes shell commands or evaluates dynamic code. All tools (Section 5.3) perform HTTP requests and database queries only.
4. **Query content filtering.** Reject queries containing common injection patterns: system prompt overrides (`ignore previous instructions`, `you are now`), tool call syntax (`<tool_call>`, `<function_call>`), and escape sequences (`\n\nsystem:`, `\n\nhuman:`). Implement as a pre-processing step in `api/routes.py` before publishing to NATS.

```python
# src/api/sanitise.py

import re

INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+a", re.IGNORECASE),
    re.compile(r"<(tool_call|function_call|system|assistant)>", re.IGNORECASE),
    re.compile(r"\\n\\n(system|human|assistant):", re.IGNORECASE),
]


def sanitise_query(query: str) -> str:
    """Sanitise research query. Raises ValueError if injection pattern detected."""
    for pattern in INJECTION_PATTERNS:
        if pattern.search(query):
            raise ValueError(f"Query contains disallowed pattern: {pattern.pattern}")
    return query.strip()
```

#### 2.7.3 Cypher Parameterisation

All Cypher queries executed via `AGEClient` (Section 3.8) MUST use parameterised inputs. String interpolation of user-controlled values into Cypher strings is prohibited.

AGE does not support native Cypher parameter binding through `asyncpg`. Instead, parameters are bound via PostgreSQL `SET` statements in the same transaction. See Section 3.8 for the implementation.

#### 2.7.4 Knowledge Graph Data Isolation

The current design uses a single `research_kg` graph. All research tasks share the same entity and claim namespace. This means:

- Any research task can read entities and claims created by any other task.
- Entity resolution (Section 3.5) may merge entities across tasks.
- The `PRODUCED_BY` and `VERIFIED_BY` edges provide provenance tracking, but not access control.

**Risk:** If the system serves multiple users with different access levels, research findings from one user's task are visible to all other users via the knowledge graph. This is acceptable for single-user or single-team deployments. Multi-tenant isolation requires a schema change (tracked in Section 12.0).

#### 2.7.5 Anti-patterns (Security)

- **Do not store API keys in `.env` files in production.** Use a secrets manager. `.env` files are for local development only.
- **Do not interpolate user input into Cypher strings.** Use the `AGEClient.execute` parameterisation pattern (Section 3.8).
- **Do not log API keys, even at DEBUG level.** Pydantic-settings' `SecretStr` type is recommended for key fields if log scrubbing is a concern.
- **Do not trust LLM output as safe.** All outputs are validated against Pydantic schemas. Never pass LLM-generated strings to `eval()`, `exec()`, `subprocess`, or `os.system()`.

**Files involved:** `src/api/sanitise.py`, `src/api/routes.py`, `src/graph/age_client.py`, `src/config.py`

---

## 3.0 Knowledge Graph Layer

### 3.1 Graph Schema

Seven node labels in the `research_kg` graph:

| Label | Purpose | Key Properties |
|---|---|---|
| `Entity` | Real-world entities (people, orgs, technologies) | `name`, `canonical_name`, `entity_type`, `summary`, `confidence` |
| `Claim` | Atomic factual assertions | `text`, `claim_type` (factual/opinion/prediction), `confidence`, `verified` |
| `Evidence` | Supporting/refuting data | `text`, `evidence_type`, `strength`, `methodology` |
| `Source` | Information origins | `url`, `title`, `source_type`, `credibility_score`, `retrieved_at` |
| `Episode` | Raw immutable data units | `content`, `source_task_id`, `created_at` |
| `ResearchTask` | Discrete research sessions | `query`, `status`, `agent_id`, `created_at` |
| `Community` | Entity clusters (Leiden detection) | `summary`, `member_count`, `level` |

Edge types:

| Category | Edge Types | Required Properties |
|---|---|---|
| Epistemic | `SUPPORTS`, `CONTRADICTS`, `PARTIALLY_SUPPORTS` | `confidence`, `valid_from`, `valid_to`, `source_task_id` |
| Derivation | `DERIVED_FROM`, `EXTRACTED_FROM` | `extraction_method`, `confidence` |
| Citation | `CITES`, `REFERENCES` | `context` |
| Temporal | `SUPERSEDES`, `PRECEDED_BY` | `valid_from`, `valid_to` |
| Semantic | `RELATED_TO`, `SAME_AS`, `PART_OF` | `confidence`, `method` |
| Provenance | `PRODUCED_BY`, `VERIFIED_BY` | `agent_id`, `timestamp` |

### 3.2 Bi-Temporal Versioning

Every edge carries four timestamps:

| Timestamp | Timeline | Description |
|---|---|---|
| `t_created` | Transaction | When recorded in system |
| `t_expired` | Transaction | When invalidated (null = current) |
| `valid_from` | Real-world | When fact became true |
| `valid_to` | Real-world | When fact ceased (null = current) |

**Rule:** Never delete edges. Set `valid_to` and `t_expired` on the old edge, create a new edge for updated facts. See invariant G-01 in Section 2.5.5.

### 3.3 Vector Search Integration (pgvector)

Document chunks are stored in a relational table with pgvector embeddings:

```sql
CREATE TABLE document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID REFERENCES research_tasks(id),
    source_url TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1536),  -- Dimension from config.embedding_dimensions
    entity_refs TEXT[],       -- Entity names for graph-vector join
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX ON document_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);
    -- m and ef_construction from config.hnsw_m and config.hnsw_ef_construction
```

### 3.4 Hybrid Retrieval Pattern

**Graph-first, then vector** (find related entities, retrieve relevant content about them):

```sql
WITH related_entities AS (
    SELECT * FROM cypher('research_kg', $$
        MATCH (e:Entity {name: $entity})-[:RELATED_TO*1..2]->(related)
        WHERE related.confidence > 0.5
        RETURN related.name
    $$) AS (name agtype)
)
SELECT dc.content, 1 - (dc.embedding <=> $query_vec::vector) AS similarity
FROM document_chunks dc
WHERE dc.entity_refs && ARRAY(SELECT name::text FROM related_entities)
ORDER BY dc.embedding <=> $query_vec::vector
LIMIT 10;
```

### 3.5 Entity Resolution Pipeline

Three-phase deduplication before graph insertion:

1. **Blocking:** pgvector ANN search with cosine similarity > `config.entity_resolution_similarity_threshold` (default 0.7) to find candidate matches.
2. **Matching:** Cascade of deterministic ID match → Jaro-Winkler + cosine similarity → LLM-based disambiguation for ambiguous cases.
3. **Merge:** Entities with combined score >= `config.entity_resolution_merge_threshold` (default 0.8) are merged. The entity with more edges becomes the canonical node. A `SAME_AS` edge preserves the merge history.

### 3.6 Anti-patterns (Knowledge Graph)

- **Do not use AGE for shallow lookups.** Single-hop property lookups on <10K nodes are faster with standard SQL. Use AGE only for multi-hop traversals (2+ hops) or pattern matching across multiple relationship types.
- **Do not embed Cypher inside pgvector queries.** Compose via CTEs or application-level orchestration. The `cypher()` function cannot appear inside pgvector operator expressions.
- **Do not use `pg_upgrade` with AGE.** AGE's use of `reg*` OID types prevents in-place major version upgrades. Use `pg_dump`/`pg_restore`.
- **Do not run AGE without `shared_preload_libraries`.** Without it, every connection requires `LOAD 'age';` which breaks PgBouncer transaction mode.
- **Do not delete graph edges.** Set `t_expired` and `valid_to` instead. See Section 3.2.

### 3.7 Graph Write-Back Specification

After the synthesiser produces a `FinalReport` and the NLI verifier completes (Section 8.0), the graph write-back process persists structured knowledge from the report into the `research_kg` graph. Graph write-back is non-transactional with report delivery: the report is saved to PostgreSQL relational tables first, and graph write-back runs asynchronously. If it fails, the report is still delivered (see error code `GRAPH_WRITE_FAILED` in Section 2.6).

#### 3.7.1 Write-Back Mapping

| Report Element | Graph Node/Edge | Extraction Logic |
|---|---|---|
| `FinalReport` (root) | `ResearchTask` node | One node per task. Properties: `query`, `status="completed"`, `confidence=report.confidence`, `created_at=now()`. |
| Each `SourceRef` in `report.sources` | `Source` node | Deduplicate by URL (exact match). If a Source with the same URL exists, reuse it and update `credibility_score` as a running average. Properties: `url`, `title`, `source_type`, `credibility_score=relevance_score`, `retrieved_at`. |
| Each `CitedClaim` in all `report.sections[*].claims` | `Claim` node | One node per unique claim text (deduplicate by semantic similarity > 0.95). Properties: `text`, `claim_type="factual"` (default; override from sub-agent claim_type if traceable), `confidence`, `verified` (true if NLI entailment > threshold). |
| Claim → Source relationship | `EXTRACTED_FROM` edge | One edge per (claim, source) pair. Properties: `extraction_method="synthesis"`, `confidence=claim.confidence`. |
| Claim → ResearchTask relationship | `PRODUCED_BY` edge | One edge per claim to the current task. Properties: `agent_id="synthesiser"`, `timestamp=now()`. |
| ResearchTask → Source relationship | `REFERENCES` edge | One edge per source used in the report. Properties: `context="research_report"`. |
| NLI-verified claims | `VERIFIED_BY` edge (Claim → ResearchTask) | Only for claims where NLI verification ran. Properties: `agent_id="nli_verifier"`, `timestamp=now()`, `entailment_score`, `contradiction_score`. |

#### 3.7.2 Entity Extraction from Claims

After creating Claim nodes, extract Entity nodes from claim text using the following process:

1. **NER extraction:** Run a lightweight NER pass over each claim's text to identify named entities (people, organisations, technologies, locations). Use spaCy `en_core_web_sm` or equivalent. Do not use an LLM for NER; it is disproportionately expensive for this step.
2. **Entity resolution:** For each extracted entity, run the resolution pipeline (Section 3.5) against existing graph entities.
3. **Edge creation:** Create `RELATED_TO` edges between resolved Entity nodes and the Claim node. Properties: `confidence` (from NER confidence), `method="ner_extraction"`.

#### 3.7.3 Write-Back Implementation

```python
# src/graph/writeback.py

from src.agents.models import FinalReport, CitedClaim, SourceRef
from src.graph.age_client import execute_cypher
from src.graph.entity_resolution import resolve_entity
from src.config import AppConfig
from datetime import datetime, timezone
import asyncpg
import logging

logger = logging.getLogger(__name__)


async def write_research_to_graph(
    report: FinalReport,
    task_id: str,
    original_query: str,
    nli_results: list[dict],
    db_pool: asyncpg.Pool,
    config: AppConfig,
) -> None:
    """Persist structured knowledge from a FinalReport into the research_kg graph.

    This function is idempotent: re-running it for the same task_id will not
    create duplicate nodes (deduplication by task_id for ResearchTask, by URL
    for Source, by semantic similarity for Claim and Entity).

    Args:
        report: The completed FinalReport from the synthesiser.
        task_id: UUID of the research task.
        original_query: The user's original query string.
        nli_results: NLI verification results from Section 8.0.
        db_pool: asyncpg connection pool.
        config: Application configuration.
    """
    now = datetime.now(timezone.utc).isoformat()
    age = AGEClient(db_pool)

    # ── Step 1: Create ResearchTask node ──
    await age.execute("""
        MERGE (t:ResearchTask {task_id: $task_id})
        SET t.query = $query, t.status = 'completed',
            t.confidence = $confidence, t.created_at = $now
    """, task_id=task_id, query=original_query,
         confidence=report.confidence, now=now)

    # ── Step 2: Batch-create Source nodes + ResearchTask edges ──
    # Build a single multi-MERGE Cypher statement for all sources.
    # This reduces N*2 round-trips to 1.
    source_cypher_parts = []
    source_params: dict[str, str | float] = {"task_id": task_id}
    for i, source in enumerate(report.sources):
        prefix = f"s{i}"
        source_cypher_parts.append(f"""
            MERGE ({prefix}:Source {{url: ${prefix}_url}})
            SET {prefix}.title = ${prefix}_title,
                {prefix}.source_type = ${prefix}_stype,
                {prefix}.credibility_score = ${prefix}_score,
                {prefix}.retrieved_at = ${prefix}_ret
            WITH {prefix}
            MATCH (t:ResearchTask {{task_id: $task_id}})
            MERGE (t)-[:REFERENCES {{context: 'research_report'}}]->({prefix})
        """)
        source_params[f"{prefix}_url"] = source.url
        source_params[f"{prefix}_title"] = source.title
        source_params[f"{prefix}_stype"] = source.source_type
        source_params[f"{prefix}_score"] = source.relevance_score
        source_params[f"{prefix}_ret"] = source.retrieved_at

    if source_cypher_parts:
        # AGE executes multi-statement Cypher via chained WITH clauses
        # within a single cypher() call. For large source lists (>20),
        # split into batches of 20 to avoid overly complex query plans.
        batch_size = 20
        for batch_start in range(0, len(source_cypher_parts), batch_size):
            batch = source_cypher_parts[batch_start:batch_start + batch_size]
            # Each statement is independent; join with WITH * separator
            combined = "\nWITH *\n".join(batch)
            batch_params = {
                k: v for k, v in source_params.items()
                if k == "task_id" or k.startswith(f"s{batch_start}")
                or any(k.startswith(f"s{j}") for j in range(batch_start, min(batch_start + batch_size, len(report.sources))))
            }
            batch_params["task_id"] = task_id
            await age.execute(combined, **batch_params)

    # ── Step 3: Batch-create Claim nodes per section ──
    # Group claims by section to reduce round-trips.
    # Each section's claims are created in a single transaction.
    all_claims = [
        claim
        for section in report.sections
        for claim in section.claims
    ]
    claim_batch_size = 10
    for batch_start in range(0, len(all_claims), claim_batch_size):
        batch_claims = all_claims[batch_start:batch_start + claim_batch_size]
        for j_offset, claim in enumerate(batch_claims):
            j = batch_start + j_offset
            claim_id = f"{task_id}-claim-{j}"
            nli_result = nli_results[j] if j < len(nli_results) else None
            verified = (
                nli_result is not None
                and nli_result.get("entailment", 0) >= config.nli_entailment_threshold
            )

            # Create claim node + provenance edge in one call
            await age.execute("""
                MERGE (c:Claim {claim_id: $claim_id})
                SET c.text = $text, c.confidence = $confidence,
                    c.verified = $verified, c.claim_type = 'factual',
                    c.t_created = $now
                WITH c
                MATCH (t:ResearchTask {task_id: $task_id})
                MERGE (c)-[:PRODUCED_BY {agent_id: 'synthesiser', timestamp: $now}]->(t)
            """, claim_id=claim_id, text=claim.text,
                 confidence=claim.confidence, verified=verified,
                 now=now, task_id=task_id)

            # Claim → Source edges (batch per claim)
            for source_url in claim.source_urls:
                await age.execute("""
                    MATCH (c:Claim {claim_id: $claim_id}), (s:Source {url: $url})
                    MERGE (c)-[:EXTRACTED_FROM {
                        extraction_method: 'synthesis', confidence: $confidence
                    }]->(s)
                """, claim_id=claim_id, url=source_url,
                     confidence=claim.confidence)

            # NLI verification edge
            if nli_result is not None:
                await age.execute("""
                    MATCH (c:Claim {claim_id: $claim_id}), (t:ResearchTask {task_id: $task_id})
                    MERGE (c)-[:VERIFIED_BY {
                        agent_id: 'nli_verifier', timestamp: $now,
                        entailment_score: $entailment,
                        contradiction_score: $contradiction
                    }]->(t)
                """, claim_id=claim_id, task_id=task_id, now=now,
                     entailment=nli_result.get("entailment", 0),
                     contradiction=nli_result.get("contradiction", 0))

    # ── Step 4: Entity extraction and resolution ──
    # NER runs in-process via spaCy (see Section 3.9 for extract_entities_from_text).
    for j, claim in enumerate(all_claims):
        claim_id = f"{task_id}-claim-{j}"
        entities = extract_entities_from_text(claim.text)
        for entity_name, entity_type, ner_confidence in entities:
            resolved = await resolve_entity(
                age, entity_name, entity_type, config
            )
            await age.execute("""
                MATCH (c:Claim {claim_id: $claim_id}),
                      (e:Entity {canonical_name: $entity_name})
                MERGE (c)-[:RELATED_TO {
                    confidence: $confidence, method: 'ner_extraction'
                }]->(e)
            """, claim_id=claim_id, entity_name=resolved,
                 confidence=ner_confidence)

    logger.info(
        f"Graph write-back complete for task {task_id}: "
        f"{len(report.sources)} sources, {len(all_claims)} claims"
    )
```

#### 3.7.4 Anti-patterns (Graph Write-Back)

- **Do not make graph write-back synchronous with report delivery.** The report is the primary deliverable. Graph persistence is eventually consistent. If the graph write fails, the user still gets their report. In v1.2, write-back runs in a dedicated NATS worker (Section 7.3).
- **Do not use LLMs for entity extraction during write-back.** NER is a classification task that runs in milliseconds with spaCy. Using an LLM adds seconds of latency and token cost per claim.
- **Do not create Entity nodes without running entity resolution first.** Skipping resolution leads to duplicate entities that fragment the graph.
- **Do not issue one Cypher call per node/edge.** Batch related operations using `WITH` clause chaining or multi-statement transactions. v1.1 issued ~54 round-trips for a typical report; v1.2 reduces this to ~15-20.
- **Do not batch all operations into a single giant transaction.** AGE transactions hold table-level locks. Batch per-section or per-10-claims, not per-report.

**Files involved:** `src/graph/writeback.py`, `src/graph/entity_resolution.py`, `src/graph/age_client.py`, `src/graph/ner.py`

### 3.8 AGE Client Specification

The `AGEClient` wraps `asyncpg` to provide safe, parameterised Cypher execution against Apache AGE. This is the only module permitted to execute Cypher queries. All other modules import `AGEClient` rather than constructing Cypher strings directly.

#### 3.8.1 Why a wrapper is needed

AGE does not support native Cypher parameter binding through `asyncpg`'s `$1, $2` placeholders. Instead, parameters must be bound via PostgreSQL `SET` statements in the same transaction, and the `cypher()` function returns `agtype` values that require explicit casting. The `AGEClient` abstracts both concerns.

#### 3.8.2 Interface

```python
# src/graph/age_client.py

import asyncpg
import json
import re
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Allowed parameter name pattern: alphanumeric + underscore only.
# Prevents Cypher injection via parameter names.
_PARAM_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class AGEClient:
    """Async wrapper for Apache AGE Cypher queries via asyncpg.

    All Cypher execution goes through this class. It handles:
    - Parameter binding via SET statements (AGE limitation)
    - agtype result casting to Python dicts
    - Connection acquisition from pool
    - search_path configuration per connection

    Usage:
        age = AGEClient(pool, graph_name="research_kg")
        await age.execute(
            "MERGE (e:Entity {name: $name}) SET e.type = $type",
            name="Apache AGE", type="technology",
        )
        rows = await age.query(
            "MATCH (e:Entity) WHERE e.name CONTAINS $term RETURN e",
            term="AGE",
        )
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        graph_name: str = "research_kg",
    ) -> None:
        self.pool = pool
        self.graph_name = graph_name

    def _validate_param_names(self, params: dict[str, Any]) -> None:
        """Reject parameter names that could enable Cypher injection."""
        for key in params:
            if not _PARAM_NAME_RE.match(key):
                raise ValueError(
                    f"Invalid parameter name '{key}'. "
                    f"Parameter names must match {_PARAM_NAME_RE.pattern}"
                )

    def _build_set_statements(self, params: dict[str, Any]) -> list[str]:
        """Convert Python parameters to AGE-compatible SET statements.

        AGE binds Cypher parameters via graph-scoped variables set with
        `SET graph_name.variable = value`. Values are JSON-encoded to
        preserve types (strings, numbers, booleans, null).
        """
        statements = []
        for key, value in params.items():
            # JSON-encode the value for type-safe binding
            json_value = json.dumps(value)
            statements.append(
                f"SET {self.graph_name}.{key} = {json_value}"
            )
        return statements

    async def execute(self, cypher: str, **params: Any) -> None:
        """Execute a Cypher statement that modifies the graph (MERGE, CREATE, SET).

        Does not return results. For read queries, use query().

        Args:
            cypher: Cypher statement with $parameter placeholders.
            **params: Parameter values. Names must be alphanumeric + underscore.

        Raises:
            ValueError: If parameter names contain disallowed characters.
            asyncpg.PostgresError: If the Cypher execution fails.
        """
        self._validate_param_names(params)

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Bind parameters via SET statements
                for stmt in self._build_set_statements(params):
                    await conn.execute(stmt)

                # Execute Cypher via AGE's cypher() function
                await conn.execute(f"""
                    SELECT * FROM cypher('{self.graph_name}', $$
                        {cypher}
                    $$) AS (result agtype)
                """)

    async def query(self, cypher: str, **params: Any) -> list[dict]:
        """Execute a read-only Cypher query and return results as dicts.

        Args:
            cypher: Cypher MATCH/RETURN statement with $parameter placeholders.
            **params: Parameter values.

        Returns:
            List of dicts, one per result row. Keys are the RETURN aliases.
        """
        self._validate_param_names(params)

        async with self.pool.acquire() as conn:
            # Bind parameters
            for stmt in self._build_set_statements(params):
                await conn.execute(stmt)

            rows = await conn.fetch(f"""
                SELECT * FROM cypher('{self.graph_name}', $$
                    {cypher}
                $$) AS (result agtype)
            """)

            # Parse agtype results to Python objects
            results = []
            for row in rows:
                # agtype values are JSON-encoded strings
                parsed = json.loads(str(row["result"]))
                results.append(parsed if isinstance(parsed, dict) else {"value": parsed})
            return results

    async def query_multi_column(
        self, cypher: str, columns: list[tuple[str, str]], **params: Any,
    ) -> list[dict]:
        """Execute a Cypher query returning multiple named columns.

        Args:
            cypher: Cypher statement with multiple RETURN values.
            columns: List of (name, agtype_cast) pairs for the AS clause.
                     Example: [("name", "agtype"), ("type", "agtype")]
            **params: Parameter values.

        Returns:
            List of dicts with column names as keys.
        """
        self._validate_param_names(params)
        col_clause = ", ".join(f"{name} {cast}" for name, cast in columns)

        async with self.pool.acquire() as conn:
            for stmt in self._build_set_statements(params):
                await conn.execute(stmt)

            rows = await conn.fetch(f"""
                SELECT * FROM cypher('{self.graph_name}', $$
                    {cypher}
                $$) AS ({col_clause})
            """)

            results = []
            for row in rows:
                parsed_row = {}
                for col_name, _ in columns:
                    val = row[col_name]
                    try:
                        parsed_row[col_name] = json.loads(str(val)) if val is not None else None
                    except (json.JSONDecodeError, TypeError):
                        parsed_row[col_name] = str(val)
                results.append(parsed_row)
            return results
```

#### 3.8.3 Anti-patterns (AGE Client)

- **Do not construct Cypher queries by string formatting user input.** Always use `$parameter` placeholders and pass values via `**params`. The `AGEClient` binds them safely via `SET` statements.
- **Do not call `cypher()` directly via `conn.execute()` outside of `AGEClient`.** All graph operations go through `AGEClient.execute()` or `AGEClient.query()`.
- **Do not forget the `AS (result agtype)` clause.** AGE requires an explicit column type declaration. Omitting it produces a PostgreSQL syntax error.
- **Do not assume `agtype` results are Python-native types.** They are JSON-encoded strings that require `json.loads()` to parse. The `AGEClient` handles this automatically.
- **Do not hold connections open across multiple Cypher calls unnecessarily.** Each `execute()` and `query()` call acquires and releases a connection. For batched writes, use the write-back pattern (Section 3.7.3) which acquires one connection per batch.

**Files involved:** `src/graph/age_client.py`

### 3.9 Entity Extraction (NER)

Lightweight named entity recognition for graph write-back. This module extracts entity mentions from claim text using spaCy. It does not use LLMs.

```python
# src/graph/ner.py

import spacy
from functools import lru_cache

# spaCy entity type → graph entity_type mapping
_ENTITY_TYPE_MAP = {
    "PERSON": "person",
    "ORG": "organisation",
    "GPE": "location",        # Geopolitical entity (country, city)
    "LOC": "location",
    "PRODUCT": "technology",
    "WORK_OF_ART": "concept",
    "EVENT": "event",
    "LAW": "regulation",
    "NORP": "group",          # Nationalities, religious, political groups
}

# Minimum confidence and length thresholds
_MIN_LABEL_SCORE = 0.5
_MIN_ENTITY_LENGTH = 2


@lru_cache(maxsize=1)
def _load_model() -> spacy.Language:
    """Load spaCy model once and cache. Thread-safe via lru_cache."""
    return spacy.load("en_core_web_sm", disable=["parser", "lemmatizer"])


def extract_entities_from_text(
    text: str,
) -> list[tuple[str, str, float]]:
    """Extract named entities from text using spaCy NER.

    Args:
        text: Claim or passage text to extract entities from.

    Returns:
        List of (entity_name, entity_type, confidence) tuples.
        entity_type is one of: person, organisation, location, technology,
        concept, event, regulation, group.
        confidence is spaCy's label score (0.0-1.0), defaulting to 0.7
        for models that do not expose per-entity scores.
    """
    nlp = _load_model()
    doc = nlp(text)

    entities = []
    seen_names: set[str] = set()
    for ent in doc.ents:
        # Filter by type (skip DATE, CARDINAL, MONEY, etc.)
        entity_type = _ENTITY_TYPE_MAP.get(ent.label_)
        if entity_type is None:
            continue

        # Filter by length
        name = ent.text.strip()
        if len(name) < _MIN_ENTITY_LENGTH:
            continue

        # Deduplicate within the same text
        name_lower = name.lower()
        if name_lower in seen_names:
            continue
        seen_names.add(name_lower)

        # spaCy sm models do not expose per-entity confidence scores.
        # Use a fixed confidence of 0.7 (sm model F1 on OntoNotes).
        # If using a transformer model (en_core_web_trf), this would
        # be available via ent.kb_id_ or custom scoring.
        confidence = 0.7

        entities.append((name, entity_type, confidence))

    return entities
```

**Files involved:** `src/graph/ner.py`

---

## 4.0 Agent Architecture

### 4.1 Multi-Provider LLM Routing

```python
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import AzureProvider
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior
import openai


def build_research_model(config: AppConfig) -> FallbackModel:
    """Construct the multi-provider LLM with fallback chain.

    Provider order: Anthropic (primary) → Azure OpenAI (fallback) → Ollama (last resort).
    max_retries=0 on SDK clients prevents built-in retry delays from blocking fallback.
    """
    azure_client = openai.AsyncAzureOpenAI(
        api_key=config.azure_openai_key,
        azure_endpoint=config.azure_openai_endpoint,
        api_version=config.azure_openai_api_version,
        max_retries=0,
    )

    return FallbackModel(
        AnthropicModel(config.primary_model),
        OpenAIChatModel(config.fallback_model, provider=AzureProvider(openai_client=azure_client)),
        OpenAIChatModel(config.local_model, provider=OpenAIProvider(
            openai_client=openai.AsyncOpenAI(
                base_url=config.ollama_base_url, api_key="ollama", max_retries=0
            )
        )),
        fallback_on=(ModelAPIError, UnexpectedModelBehavior),
    )
```

### 4.2 Agent Roles

| Agent | Model | Has Tools | Input | Output | Token Budget (from config) |
|---|---|---|---|---|---|
| Planner | `config.primary_model` | No | Raw user query | `ResearchPlan` | `config.token_budget_planner` |
| Sub-Agent | `RESEARCH_MODEL` (fallback) | Yes (search, extract, graph) | Single sub-question | `SubAgentFindings` | `config.token_budget_per_sub_agent` |
| Synthesiser | `config.primary_model` | No | All sub-agent findings | `FinalReport` | `config.token_budget_synthesis` |

### 4.3 Structured Output Models

```python
# src/agents/models.py

from pydantic import BaseModel, Field, field_validator
from enum import Enum
from typing import Literal


class SourcePreference(str, Enum):
    ACADEMIC = "academic"
    NEWS = "news"
    OFFICIAL = "official"
    TECHNICAL = "technical"
    ANY = "any"


class Priority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SynthesisStrategy(str, Enum):
    """Enforces invariant P-04: synthesis_strategy must be one of these values."""
    COMPARATIVE = "comparative"
    CHRONOLOGICAL = "chronological"
    THEMATIC = "thematic"
    HIERARCHICAL = "hierarchical"
    ARGUMENTATIVE = "argumentative"


class SubQuestion(BaseModel):
    question: str = Field(max_length=300)
    why_it_matters: str = Field(max_length=200)
    search_hints: list[str] = Field(min_length=2, max_length=4)
    source_preference: SourcePreference
    priority: Priority
    depends_on: list[int] | None = Field(
        default=None,
        description="0-based indices of sub-questions whose findings are needed "
        "before this one. Index 0 is the first sub-question. Must not self-reference "
        "or create cycles. Empty/null for independent questions.",
    )


class ResearchPlan(BaseModel):
    original_query: str
    clarified_intent: str = Field(max_length=500)
    sub_questions: list[SubQuestion] = Field(min_length=2, max_length=7)
    synthesis_strategy: SynthesisStrategy
    estimated_complexity: int = Field(ge=1, le=10)
    expected_output_length: Literal["brief", "standard", "comprehensive"]

    @field_validator("synthesis_strategy", mode="before")
    @classmethod
    def normalise_synthesis_strategy(cls, v: str) -> str:
        """Normalise LLM output to match enum values.

        LLMs may return 'Comparative', 'COMPARATIVE', or 'comparative_analysis'.
        Strip common suffixes and normalise to lowercase.
        """
        if isinstance(v, str):
            v = v.lower().strip()
            # Strip common LLM suffixes
            for suffix in ("_analysis", "_approach", "_method", "_strategy"):
                if v.endswith(suffix):
                    v = v[: -len(suffix)]
        return v


class Claim(BaseModel):
    text: str = Field(max_length=500)
    source_indices: list[int] = Field(min_length=1)
    # Enforces invariant R-01: every claim must reference at least one source.
    confidence: float = Field(ge=0.0, le=1.0)
    claim_type: Literal["factual", "opinion", "prediction", "methodological"]


class SourceRef(BaseModel):
    url: str
    title: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    source_type: Literal["academic", "news", "official", "blog", "docs"]
    extraction_method: Literal["tavily_snippet", "tavily_raw", "trafilatura", "jina"]
    retrieved_at: str  # ISO 8601


class SubAgentFindings(BaseModel):
    sub_question: str
    answer_summary: str = Field(max_length=1000)
    key_claims: list[Claim] = Field(min_length=1)
    sources_used: list[SourceRef]
    confidence: float = Field(ge=0.0, le=1.0)
    gaps_identified: list[str] = Field(default_factory=list)
    contradictions_found: list[str] = Field(default_factory=list)


class CitedClaim(BaseModel):
    text: str
    source_urls: list[str] = Field(min_length=1)
    # Enforces invariant S-01: every claim must cite at least one source.
    confidence: float = Field(ge=0.0, le=1.0)


class ReportSection(BaseModel):
    heading: str
    content: str  # Prose with [N] inline citations
    claims: list[CitedClaim]


class FinalReport(BaseModel):
    title: str
    executive_summary: str = Field(max_length=1000)
    sections: list[ReportSection] = Field(min_length=1)
    sources: list[SourceRef]
    confidence: float = Field(ge=0.0, le=1.0)
    limitations: list[str]
    suggested_follow_ups: list[str] = Field(min_length=1, max_length=3)
```

### 4.3.1 Anti-patterns (Output Models)

- **Do not use `str` where `Literal` or `Enum` is appropriate.** Open-ended strings for constrained fields (synthesis_strategy, claim_type, source_type) allow invalid values. Use `Literal` or `Enum` and let Pydantic enforce the constraint.
- **Do not use `list[int]` without `min_length=1` for source references.** An empty source_indices list violates invariant R-01. The Pydantic model should make this structurally impossible.
- **Do not add fields to output models without updating the graph write-back mapping (Section 3.7.1).** Every field in `FinalReport` that carries structured knowledge must have a defined graph representation.

---

## 5.0 Agent Prompts

### 5.1 Planner System Prompt

```python
# src/agents/planner.py

PLANNER_SYSTEM_PROMPT = """\
You are the research planning component of an autonomous research system. \
Your role is to decompose a research question into independent, parallelisable \
sub-questions that specialist research agents will investigate.

You do NOT perform research. You plan it. You have no access to the internet, \
no tools, no search capabilities. You think, decompose, and structure.

## How to decompose effectively

Start by restating the user's intent in your own words. This surfaces ambiguity \
early. If the query is vague ("tell me about X"), interpret it as the most useful \
version of the question a knowledgeable person would ask.

Then identify the 3-7 sub-questions that, when answered together, fully address \
the original query. Apply these rules:

1. **Independence first.** Each sub-question should be answerable without \
   knowing the answers to the others. If two sub-questions are tightly coupled, \
   merge them or mark the dependency explicitly via `depends_on`.

2. **Breadth before depth.** The first 2-3 sub-questions should cover the core \
   of what the user needs. Later sub-questions add nuance, counterarguments, \
   or supporting context. If budget is limited, the orchestrator may drop \
   low-priority questions.

3. **Justify every question.** Fill in `why_it_matters` honestly. If you cannot \
   articulate why a sub-question helps answer the original query in one sentence, \
   do not include it. Tangential questions waste compute and degrade report quality.

4. **Search hints must be short and staged.** The first hint for each sub-question \
   should be 2-3 words (broad). Subsequent hints narrow progressively. \
   WRONG: "specific regulatory requirements for AI medical devices in the EU" \
   RIGHT: First hint "AI medical regulation", second hint "EU MDR AI devices"

5. **Fewer is better.** If the question can be answered with 3 sub-questions, \
   do not produce 7. Extra sub-questions increase cost, latency, and synthesis \
   complexity without proportional quality gains.

6. **Source preferences matter.** A question about current market prices needs \
   news sources. A question about mechanisms needs academic sources. A question \
   about compliance needs official sources. Be specific.

## Complexity calibration

Be honest about complexity. A simple factual question ("When was X founded?") \
is complexity 1-2. A comparative analysis ("How do approaches A, B, C differ \
in their handling of X?") is 5-7. Only questions requiring synthesis across \
multiple domains, temporal analysis, and contested evidence reach 8-10.

Overestimating complexity wastes resources. Underestimating it produces \
shallow reports. Calibrate based on: number of independent dimensions to \
investigate, degree of source disagreement expected, and whether temporal \
change tracking is needed.

## Constraints (enforced by the output schema)

- Sub-questions list: minimum 2, maximum 7.
- First search hint per sub-question: 2-4 words.
- synthesis_strategy: must be exactly one of these lowercase values: comparative, \
  chronological, thematic, hierarchical, argumentative. No other values are accepted.
- expected_output_length: must be exactly one of: brief, standard, comprehensive.
- depends_on uses **0-based indices**. Index 0 is the first sub-question in the list. \
  A sub-question must not reference its own index. Cycles are not permitted.

## Depth calibration

The user has requested a specific research depth. Calibrate your plan accordingly:

- **brief**: Target 2-3 sub-questions. Complexity should be 1-4. \
  The report will be ~500 words. Focus on the core answer only.
- **standard**: Target 3-5 sub-questions. Complexity should be 3-7. \
  The report will be ~1500 words. Cover the core answer plus context.
- **comprehensive**: Target 5-7 sub-questions. Complexity should be 6-10. \
  The report will be ~3000+ words. Cover the full landscape including \
  counterarguments, historical context, and future implications.

Do not produce 7 sub-questions for a brief request. Do not produce 2 \
sub-questions for a comprehensive request unless the topic is genuinely narrow.

## Output format

Return a ResearchPlan with all fields populated. The orchestrator will use \
your plan to spawn sub-agents, allocate token budgets, and schedule execution. \
Your plan is the single source of truth for the entire research task.
"""

planner_agent = Agent(
    "anthropic:claude-sonnet-4-6",
    output_type=ResearchPlan,
    system_prompt=PLANNER_SYSTEM_PROMPT,
)
```

### 5.2 Sub-Agent System Prompt (Template)

This prompt is dynamically assembled per sub-question by `build_sub_agent_prompt()`. Each sub-agent receives a unique system prompt containing its specific question, justification, search hints, source preferences, and token budget. The sub-agent never sees other sub-questions or the broader research plan.

```python
# src/agents/researcher.py

SUB_AGENT_SYSTEM_PROMPT = """\
You are a specialist research agent investigating one specific question as \
part of a larger research task. You have access to web search, content \
extraction, and a knowledge graph of previously researched information.

## Your assigned sub-question

{sub_question}

## Why this matters to the overall research

{why_it_matters}

## Search guidance

Suggested starting queries (adapt based on what you find):
{search_hints}

Preferred source types: {source_preference}

## Research protocol

Follow this sequence. Do not skip steps.

1. **Check existing knowledge first.** Query the knowledge graph for entities \
   and claims related to your sub-question. If high-confidence information \
   already exists from prior research, use it and note the source. Do not \
   re-research what the system already knows well.

2. **Search broadly, then narrow.** Your first web search should use the \
   broadest search hint (2-3 words). Read the results. Then construct a \
   more specific query based on what you learned. Repeat 2-4 times. \
   Most sub-questions need 3-5 total searches.

3. **Extract when snippets are insufficient.** If a search result looks \
   highly relevant but the snippet does not contain enough detail, use the \
   extract_page tool to get the full content. Do not extract every page; \
   be selective. Extraction is slower and more expensive than search.

4. **Track provenance rigorously.** Every factual claim in your output MUST \
   reference at least one source by index. If you cannot attribute a claim \
   to a specific source, mark it as confidence < 0.3 and flag it as a gap.

5. **Report honestly.** If the evidence is thin, say so. If sources conflict, \
   report both positions. If a question is partially unanswerable with \
   available sources, explain what is missing and why.

## Error handling

- If the knowledge graph query fails, skip it and proceed to web search. \
  Do not retry the graph query.
- If a search returns a 429 (rate limit), stop searching immediately. \
  Return findings from results already collected. Add a gap: \
  "search rate limited after N queries".
- If your token budget is running low, prioritise completing your \
  answer_summary and key_claims over additional searches. Return partial \
  findings with confidence < 0.5 and add a gap: "token budget exhausted".
- If content extraction fails for a URL, use the search snippet for that \
  source. Do not retry extraction for the same URL.

## What NOT to do

- Do not fabricate information. An honest "I could not find this" is always \
  better than a plausible-sounding unsourced claim.
- Do not over-search. If you have strong, consistent evidence from 3+ sources \
  after 3 searches, stop searching and synthesise.
- Do not produce generic summaries. Be specific: names, dates, numbers, \
  percentages, version numbers.
- Do not include sources you did not actually use in your reasoning. Only \
  list sources that informed your claims.

## Token budget

You have approximately {token_budget} tokens for this sub-question. \
Allocate roughly 60% to search/extraction tool calls and 40% to your \
final structured output. If you are running low, prioritise completing \
your answer_summary and key_claims over additional searches.
"""


def build_sub_agent_prompt(sq: SubQuestion, token_budget: int = 4000) -> str:
    hints_formatted = "\n".join(f"  - {h}" for h in sq.search_hints)
    return SUB_AGENT_SYSTEM_PROMPT.format(
        sub_question=sq.question,
        why_it_matters=sq.why_it_matters,
        search_hints=hints_formatted,
        source_preference=sq.source_preference.value,
        token_budget=token_budget,
    )
```

### 5.3 Sub-Agent Tool Definitions

```python
# src/tools/search.py

@agent.tool
async def search_web(
    ctx: RunContext[SubAgentDeps], query: str, depth: str = "advanced",
) -> str:
    """Search the web. Keep queries SHORT (2-5 words).
    Start broad, then narrow based on results.

    Args:
        query: Search query, 2-5 words for best results.
        depth: "basic" (1 credit) or "advanced" (2 credits, deeper).
    """
    config = ctx.deps.config
    try:
        result = await ctx.deps.tavily.search(
            query=query,
            search_depth=depth,
            max_results=config.tavily_max_results,
            include_raw_content=True,  # Boolean, not string. Returns full page markdown.
        )
    except Exception as e:
        if "429" in str(e) or "rate" in str(e).lower():
            return (
                f"SEARCH RATE LIMITED. Stop searching. "
                f"Use results from previous searches to answer the question. "
                f"Add 'search rate limited' to gaps_identified."
            )
        return f"Search failed: {e}. Try a different query or proceed with available results."

    now = datetime.now(timezone.utc).isoformat()
    for r in result.get("results", []):
        ctx.deps.collected_sources.append({
            "url": r["url"], "title": r.get("title", ""),
            "score": r.get("score", 0.0), "method": "tavily_search",
            "retrieved_at": now,
        })
    formatted = []
    for i, r in enumerate(result.get("results", [])):
        formatted.append(
            f"[{i}] {r.get('title', 'No title')}\n"
            f"    URL: {r['url']}\n"
            f"    Score: {r.get('score', 'N/A')}\n"
            f"    Snippet: {r.get('content', 'No snippet')[:500]}"
        )
    if not formatted:
        return "No search results found. Try a different query or broaden your search terms."
    return "\n\n".join(formatted)


# src/tools/extract.py

@agent.tool
async def extract_page(ctx: RunContext[SubAgentDeps], url: str) -> str:
    """Extract full page content when search snippets are not enough.
    Use selectively: extraction is slower than search.

    Args:
        url: The URL to extract content from.
    """
    import trafilatura

    config = ctx.deps.config
    try:
        resp = await ctx.deps.http_client.get(
            url, timeout=config.extraction_timeout_seconds,
        )
        html = resp.text
    except Exception as e:
        return f"Failed to fetch {url}: {e}. Use the search snippet for this source instead."

    content = await asyncio.to_thread(
        trafilatura.extract, html, url=url,
        output_format="markdown", include_links=True, include_tables=True,
    )
    method = "trafilatura"

    if not content or len(content.strip()) < 100:
        try:
            jina_resp = await ctx.deps.http_client.get(
                f"https://r.jina.ai/{url}",
                headers={"Accept": "application/json"},
                timeout=config.jina_timeout_seconds,
            )
            content = jina_resp.json().get("content", "")
            method = "jina"
        except Exception:
            return (
                f"All extraction methods failed for {url}. "
                f"Use the search snippet for this source instead. "
                f"Do not retry extraction for this URL."
            )

    if not content:
        return f"No content extracted from {url}."

    ctx.deps.collected_sources.append({"url": url, "method": method})
    return content[: config.extraction_max_chars]


# src/tools/knowledge_graph.py

@agent.tool
async def check_knowledge_graph(
    ctx: RunContext[SubAgentDeps], search_term: str,
) -> str:
    """Check what the system already knows about an entity or topic.
    Query this BEFORE searching the web.

    Args:
        search_term: Entity name or topic keyword to look up.
    """
    try:
        rows = await ctx.deps.db_pool.fetch("""
            SELECT * FROM cypher('research_kg', $$
                MATCH (e:Entity)
                WHERE e.name CONTAINS $term
                OPTIONAL MATCH (e)-[r]->(t)
                WHERE r.valid_to IS NULL
                RETURN e.name, e.entity_type, e.summary, e.confidence,
                       type(r), t.name
                LIMIT 20
            $$) AS (
                entity agtype, type agtype, summary agtype,
                confidence agtype, rel_type agtype, related agtype
            )
        """)
    except Exception as e:
        return (
            f"Knowledge graph query failed: {e}. "
            f"Proceed to web search. Do not retry the graph query."
        )

    if not rows:
        return f"No existing knowledge about '{search_term}' in the graph. Proceed to web search."
    formatted = [f"Existing knowledge for '{search_term}':"]
    for row in rows:
        line = f"  - {row['entity']} ({row['type']})"
        if row.get("rel_type"):
            line += f" --[{row['rel_type']}]--> {row['related']}"
        formatted.append(line)
    return "\n".join(formatted)
```

### 5.4 Synthesiser System Prompt

```python
# src/agents/synthesiser.py

SYNTHESISER_SYSTEM_PROMPT = """\
You are the synthesis component of an autonomous research system. You receive \
structured findings from multiple specialist research agents and produce a \
single coherent research report.

## Your inputs

You will receive:
1. The original research question
2. The planner's clarified intent and synthesis strategy
3. Findings from {n_findings} sub-agents, each containing:
   - An answer summary
   - Atomic claims with source references
   - Confidence scores
   - Identified gaps and contradictions

## Synthesis protocol

1. **Deduplicate sources.** Multiple sub-agents may have found the same sources. \
   Build a single numbered source list. Remap all claim references to this \
   unified list.

2. **Resolve contradictions.** If sub-agents report conflicting claims, \
   do not silently pick one. Present both positions, cite both sources, \
   and explain why one may be more credible (source type, recency, \
   corroboration by other sources).

3. **Follow the synthesis strategy.** The planner specified how to organise \
   the report: {synthesis_strategy}. Structure your sections accordingly. \
   Do not default to a generic structure if a specific one was requested.

4. **Maintain citation discipline.** Every factual statement in the report \
   MUST have an inline [N] citation referencing the sources list. If a claim \
   appeared in sub-agent findings without adequate sourcing (confidence < 0.5), \
   either verify it against other sub-agents' sources or flag it explicitly \
   as uncertain.

5. **Filter low-confidence claims.** Claims with confidence < 0.3 from \
   sub-agent findings MUST NOT appear in the final report unless qualified \
   with explicit uncertainty language (e.g., "unverified reports suggest", \
   "one source indicates without corroboration").

6. **Write the executive summary LAST.** It should accurately reflect the \
   full report content, not be a generic introduction. Include the 2-3 most \
   important findings and the overall confidence level.

7. **Be honest about limitations.** Gaps identified by sub-agents become \
   limitations in the final report. Do not hide them. A report that clearly \
   states its boundaries is more useful than one that implies completeness.

8. **Flag contradicted claims.** Any claim that was contradicted by NLI \
   verification in a prior iteration, or that conflicts with another \
   sub-agent's high-confidence claim, must appear in the limitations field \
   with the contradicted claim text and the conflicting source.

## Quality standards

- Concrete over generic. If a sub-agent found a specific number, date, name, \
  or percentage, use it. Do not soften "37% increase" to "significant increase".
- No filler. Every sentence should convey information or analysis that the \
  reader needs. Cut anything that exists only to smooth transitions.
- Proportional depth. Allocate more space to high-priority sub-questions \
  and less to supporting context.
- Suggested follow-ups should be genuinely useful next questions, not \
  restatements of what was already researched. Each follow-up must address \
  a gap or extend the analysis in a direction not covered by the current report.
"""
```

### 5.5 Synthesis Prompt Assembly

The synthesiser receives all sub-agent findings as a structured user message:

```python
# src/agents/synthesiser.py

def build_synthesis_prompt(
    query: str, plan: ResearchPlan, findings: list[SubAgentFindings],
) -> str:
    findings_text = []
    for i, f in enumerate(findings):
        section = [
            f"## Sub-agent {i + 1}: {f.sub_question}",
            f"**Confidence:** {f.confidence}",
            f"**Summary:** {f.answer_summary}",
            "", "**Claims:**",
        ]
        for j, claim in enumerate(f.key_claims):
            sources_str = ", ".join(f"[{s}]" for s in claim.source_indices)
            section.append(
                f"  {j + 1}. {claim.text} "
                f"(sources: {sources_str}, confidence: {claim.confidence}, "
                f"type: {claim.claim_type})"
            )
        section.append("\n**Sources used:**")
        for k, src in enumerate(f.sources_used):
            section.append(f"  [{k}] {src.title} ({src.source_type}) - {src.url}")
        if f.gaps_identified:
            section.append("\n**Gaps:**")
            for gap in f.gaps_identified:
                section.append(f"  - {gap}")
        if f.contradictions_found:
            section.append("\n**Contradictions:**")
            for c in f.contradictions_found:
                section.append(f"  - {c}")
        findings_text.append("\n".join(section))

    return (
        f"# Research Task\n\n"
        f"**Original query:** {query}\n\n"
        f"**Clarified intent:** {plan.clarified_intent}\n\n"
        f"**Synthesis strategy:** {plan.synthesis_strategy.value}\n\n"
        f"**Expected length:** {plan.expected_output_length}\n\n"
        f"---\n\n# Sub-Agent Findings\n\n"
        + "\n\n---\n\n".join(findings_text)
        + "\n\n---\n\n"
        f"Synthesise these findings into a final research report. "
        f"Follow the synthesis protocol in your instructions."
    )
```

---

## 6.0 Orchestrator

### 6.1 Design Principle

The orchestrator is **plain Python, not an LLM agent**. It calls the planner agent, reads the structured plan, spawns sub-agents, collects results, and calls the synthesiser. No LLM reasoning happens in the orchestration layer. Concurrency, error handling, timeouts, and progress reporting are code, not prompts.

### 6.2 Execution Flow

```python
# src/orchestrator/coordinator.py

from src.config import AppConfig
from src.errors.taxonomy import ErrorCode, ERROR_SPECS
import logging

logger = logging.getLogger(__name__)


@dataclass
class SubAgentDeps:
    tavily: AsyncTavilyClient
    http_client: httpx.AsyncClient
    db_pool: asyncpg.Pool
    config: AppConfig
    task_id: str
    sub_question_id: str
    collected_sources: list[dict] = field(default_factory=list)


async def execute_research(
    query: str,
    depth: str,  # "brief", "standard", "comprehensive" from ResearchRequest
    tavily_client: AsyncTavilyClient,
    http_client: httpx.AsyncClient,
    db_pool: asyncpg.Pool,
    task_id: str,
    config: AppConfig,
    progress_callback: Callable | None = None,
) -> FinalReport:
    """Execute the full research lifecycle: plan → delegate → synthesise → verify → persist.

    Raises:
        ResearchError: With appropriate ErrorCode if any phase fails fatally.
    """

    # ── Depth-to-config mapping ──
    # Adjust orchestrator behaviour based on requested research depth.
    # These overrides apply per-task without mutating the shared AppConfig.
    depth_overrides = {
        "brief": {
            "max_sub_agents": min(config.max_sub_agents, 3),
            "token_budget_per_sub_agent": min(config.token_budget_per_sub_agent, 6000),
            "token_budget_synthesis": min(config.token_budget_synthesis, 6000),
            "enable_gap_analysis": False,
        },
        "standard": {
            "max_sub_agents": min(config.max_sub_agents, 5),
            "token_budget_per_sub_agent": config.token_budget_per_sub_agent,
            "token_budget_synthesis": config.token_budget_synthesis,
            "enable_gap_analysis": config.enable_gap_analysis,
        },
        "comprehensive": {
            "max_sub_agents": config.max_sub_agents,
            "token_budget_per_sub_agent": config.token_budget_per_sub_agent,
            "token_budget_synthesis": config.token_budget_synthesis,
            "enable_gap_analysis": True,
        },
    }
    overrides = depth_overrides.get(depth, depth_overrides["standard"])

    # ── Phase 1: PLAN ──
    await _update_task_status(db_pool, task_id, TaskStatus.PLANNING)
    # Pass depth to planner so it calibrates sub-question count and complexity
    planner_input = f"[Research depth: {depth}]\n\n{query}"
    try:
        plan_result = await asyncio.wait_for(
            planner_agent.run(
                planner_input,
                usage_limits=UsageLimits(
                    request_limit=config.request_limit_planner,
                    total_tokens_limit=config.token_budget_planner,
                ),
            ),
            timeout=config.sub_agent_timeout_seconds,
        )
        plan = plan_result.output
    except asyncio.TimeoutError:
        raise ResearchError(ErrorCode.TASK_TIMED_OUT, phase="planning")
    except (ModelAPIError, UnexpectedModelBehavior) as e:
        logger.error(f"Planning failed for task {task_id}: {e}", exc_info=True)
        raise ResearchError(ErrorCode.PLANNING_FAILED, detail=str(e))

    # Validate invariant P-03: no circular dependencies
    _validate_no_cycles(plan.sub_questions)

    # Enforce depth-based sub-question cap
    if len(plan.sub_questions) > overrides["max_sub_agents"]:
        plan.sub_questions = plan.sub_questions[: overrides["max_sub_agents"]]

    # ── Phase 2: DELEGATE (parallel sub-agents, in-process via asyncio.gather) ──
    await _update_task_status(db_pool, task_id, TaskStatus.RESEARCHING)
    independent = [(i, sq) for i, sq in enumerate(plan.sub_questions) if not sq.depends_on]
    dependent = [(i, sq) for i, sq in enumerate(plan.sub_questions) if sq.depends_on]

    all_findings: dict[int, SubAgentFindings] = {}
    failed_count = 0

    async def run_sub_agent(index: int, sq: SubQuestion) -> tuple[int, SubAgentFindings | None]:
        sub_deps = SubAgentDeps(
            tavily=tavily_client, http_client=http_client, db_pool=db_pool,
            config=config, task_id=task_id,
            sub_question_id=f"{task_id}-sq-{index}",
        )
        agent = create_sub_agent(sq, token_budget=overrides["token_budget_per_sub_agent"])
        try:
            result = await asyncio.wait_for(
                agent.run(
                    sq.question, deps=sub_deps,
                    usage_limits=UsageLimits(
                        request_limit=config.request_limit_per_sub_agent,
                        total_tokens_limit=overrides["token_budget_per_sub_agent"],
                    ),
                ),
                timeout=config.sub_agent_timeout_seconds,
            )
            return (index, result.output)
        except asyncio.TimeoutError:
            logger.warning(f"Sub-agent {index} timed out for task {task_id}")
            return (index, None)
        except Exception as e:
            logger.error(
                f"Sub-agent {index} failed for task {task_id}: {e}",
                exc_info=True,
            )
            return (index, None)

    # Fan-out: independent sub-agents run concurrently
    results = await asyncio.gather(
        *(run_sub_agent(i, sq) for i, sq in independent)
    )
    for idx, findings in results:
        if findings:
            all_findings[idx] = findings
        else:
            failed_count += 1

    # Execute dependent sub-questions after their dependencies complete
    for idx, sq in dependent:
        deps_met = all(d in all_findings for d in (sq.depends_on or []))
        if deps_met:
            dep_idx, findings = await run_sub_agent(idx, sq)
            if findings:
                all_findings[dep_idx] = findings
            else:
                failed_count += 1
        else:
            logger.warning(
                f"Skipping dependent sub-agent {idx}: dependencies not met"
            )
            failed_count += 1

    # Invariant O-01: minimum findings threshold
    if len(all_findings) < config.min_sub_agent_results_for_synthesis:
        raise ResearchError(
            ErrorCode.INSUFFICIENT_FINDINGS,
            detail=f"{len(all_findings)} of {len(plan.sub_questions)} sub-agents completed",
        )

    if progress_callback:
        await progress_callback(ProgressEvent(
            task_id=task_id, status=TaskStatus.RESEARCHING, phase="researching",
            progress_pct=100.0, sub_agents_completed=len(all_findings),
            sub_agents_total=len(plan.sub_questions),
            message=f"Research complete: {len(all_findings)} sub-agents returned findings.",
            timestamp=datetime.now(timezone.utc),
        ))

    # ── Phase 2.5: GAP ANALYSIS (optional) ──
    # Invariant O-02: only runs for complexity >= threshold
    if (
        overrides["enable_gap_analysis"]
        and plan.estimated_complexity >= config.min_complexity_for_gap_pass
    ):
        all_gaps = [g for f in all_findings.values() for g in f.gaps_identified]
        if len(all_gaps) >= 2:
            gap_query = (
                f"Original question: {query}\n\n"
                f"Gaps identified during initial research:\n"
                + "\n".join(f"- {g}" for g in all_gaps[:5])
                + "\n\nGenerate 1-3 targeted sub-questions to fill the most critical gaps."
            )
            try:
                gap_plan = (await planner_agent.run(gap_query)).output
                gap_results = await asyncio.gather(
                    *(run_sub_agent(100 + i, sq)
                      for i, sq in enumerate(gap_plan.sub_questions[:config.max_gap_sub_questions]))
                )
                for idx, findings in gap_results:
                    if findings:
                        all_findings[idx] = findings
            except Exception as e:
                logger.warning(f"Gap analysis failed for task {task_id}: {e}")
                # Non-fatal: proceed to synthesis without gap results

    # ── Phase 3: SYNTHESISE ──
    await _update_task_status(db_pool, task_id, TaskStatus.SYNTHESISING)
    ordered_findings = [all_findings[k] for k in sorted(all_findings.keys())]
    synthesiser = create_synthesiser_agent(plan, n_findings=len(ordered_findings))
    synthesis_prompt = build_synthesis_prompt(query, plan, ordered_findings)

    try:
        final_result = await asyncio.wait_for(
            synthesiser.run(
                synthesis_prompt,
                usage_limits=UsageLimits(total_tokens_limit=config.token_budget_synthesis),
            ),
            timeout=config.synthesis_timeout_seconds,
        )
    except asyncio.TimeoutError:
        raise ResearchError(ErrorCode.TASK_TIMED_OUT, phase="synthesis")
    except Exception as e:
        logger.error(f"Synthesis failed for task {task_id}: {e}", exc_info=True)
        raise ResearchError(ErrorCode.SYNTHESIS_FAILED, detail=str(e))

    report = final_result.output

    # ── Phase 4: VERIFY CITATIONS ──
    await _update_task_status(db_pool, task_id, TaskStatus.VERIFYING)
    verifier = NLICitationVerifier(
        model_name=config.nli_model_name,
        threshold=config.nli_entailment_threshold,
    )
    nli_results = await _verify_citations(report, verifier, db_pool, config)

    # Invariant S-03: contradicted claims go to limitations
    for i, nli_result in enumerate(nli_results):
        if nli_result.get("result") == "contradicted":
            claim_text = nli_result.get("claim", "Unknown claim")
            report.limitations.append(
                f"CONTRADICTED: '{claim_text}' was contradicted by its cited source."
            )

    # ── Phase 5: PERSIST ──
    await _persist_report(db_pool, task_id, report)
    await _update_task_status(db_pool, task_id, TaskStatus.COMPLETED)

    # ── Cost alert check ──
    # Estimate cost from token usage across all phases.
    # If cost exceeds threshold, log a warning for operator review.
    total_input = sum(m.input_tokens for m in all_metrics)
    total_output = sum(m.output_tokens for m in all_metrics)
    estimated_cost = (
        (total_input / 1000) * config.cost_per_1k_input_tokens
        + (total_output / 1000) * config.cost_per_1k_output_tokens
    )
    if estimated_cost > config.cost_alert_threshold_usd:
        logger.warning(
            f"COST ALERT: Task {task_id} estimated at ${estimated_cost:.2f} "
            f"(threshold: ${config.cost_alert_threshold_usd:.2f}). "
            f"Input tokens: {total_input}, output tokens: {total_output}."
        )

    # ── Graph write-back via NATS (async, non-blocking) ──
    # The report is already persisted. Graph write-back runs in a dedicated
    # worker (Section 7.3). If the publish fails, the report is still delivered.
    if progress_callback:
        # Reuse the progress_callback's NATS publisher to send the graph payload.
        # The graph_worker subscriber (Section 7.3) processes it asynchronously.
        pass  # Actual publish happens in the calling subscriber (Section 7.2)

    return report


def _validate_no_cycles(sub_questions: list[SubQuestion]) -> None:
    """Validate invariant P-03: no circular dependencies in depends_on."""
    from graphlib import TopologicalSorter, CycleError

    graph: dict[int, set[int]] = {}
    for i, sq in enumerate(sub_questions):
        graph[i] = set(sq.depends_on or [])
    try:
        list(TopologicalSorter(graph).static_order())
    except CycleError as e:
        raise ResearchError(ErrorCode.CIRCULAR_DEPENDENCY, detail=str(e))
```

### 6.3 Anti-patterns (Orchestrator)

- **Do not make the orchestrator an LLM agent.** Orchestration logic (topological sort, fan-out/fan-in, error handling, timeouts) is better expressed as code. LLMs handle understanding and writing; Python handles coordination.
- **Do not share context between sub-agents.** Each sub-agent gets a clean context window. Sharing context causes "context rot" where reasoning quality degrades as the window fills.
- **Do not retry failed sub-agents more than once.** A single retry covers transient API failures. Persistent failures indicate the sub-question is unanswerable; mark it as a gap and proceed to synthesis.
- **Do not catch bare `Exception` and silently discard.** Log the exception with task_id, sub-question_id, and full traceback. Then return `None` for the sub-agent result.
- **Do not proceed to synthesis without checking `min_sub_agent_results_for_synthesis`.** See invariant O-01.

---

## 7.0 NATS JetStream Task Distribution

### 7.1 Stream Configuration

```python
# src/streaming/nats_config.py

from faststream.nats import JStream, PullSub
from nats.js.api import RetentionPolicy, DeliverPolicy

TASK_STREAM = JStream(
    name="RESEARCH_TASKS",
    subjects=["research.task"],
    retention=RetentionPolicy.WORK_QUEUE,  # Auto-remove after ack
)

PROGRESS_STREAM = JStream(
    name="RESEARCH_PROGRESS",
    subjects=["research.progress.>"],
    retention=RetentionPolicy.LIMITS,
    max_age=86400,  # 1 day; progress events are ephemeral
)

GRAPH_STREAM = JStream(
    name="GRAPH_WRITEBACK",
    subjects=["research.graph_writeback"],
    retention=RetentionPolicy.WORK_QUEUE,
)
```

### 7.2 Orchestrator Worker (Pull Consumer)

Each orchestrator instance pulls one research task at a time from `research.task`, executes the full lifecycle (plan → delegate → synthesise → verify → persist), and publishes progress events to `research.progress.{task_id}`. Horizontal scaling is achieved by deploying multiple orchestrator instances.

```python
# src/streaming/subscribers.py

@broker.subscriber(
    "research.task",
    stream=TASK_STREAM,
    durable="research-orchestrators",
    deliver_policy=DeliverPolicy.ALL,
    pull_sub=PullSub(batch_size=1, timeout=5.0),  # One task at a time per instance
)
async def process_research_task(task: ResearchTaskMessage, logger: Logger) -> None:
    logger.info(f"Processing research task {task.task_id}: {task.query[:100]}")

    async def publish_progress(event: ProgressEvent) -> None:
        await broker.publish(
            event.model_dump_json(),
            f"research.progress.{task.task_id}",
            stream="RESEARCH_PROGRESS",
        )

    try:
        report = await execute_research(
            query=task.query,
            depth=task.depth,
            tavily_client=deps.tavily,
            http_client=deps.http_client,
            db_pool=deps.db_pool,
            task_id=task.task_id,
            config=deps.config,
            progress_callback=publish_progress,
        )
        # Publish graph write-back as a separate NATS message (Section 3.7)
        await broker.publish(
            GraphWritebackPayload(
                task_id=task.task_id,
                query=task.query,
                report=report,
            ).model_dump_json(),
            "research.graph_writeback",
            stream="GRAPH_WRITEBACK",
        )
    except ResearchError as e:
        logger.error(f"Research task {task.task_id} failed: {e}")
        await publish_progress(ProgressEvent(
            task_id=task.task_id, status=TaskStatus.FAILED,
            phase="error", progress_pct=0.0,
            sub_agents_completed=0, sub_agents_total=0,
            message=str(e), timestamp=datetime.now(timezone.utc),
        ))
```

### 7.3 Graph Writer Worker

Dedicated worker that processes graph write-back messages asynchronously. Decoupled from the orchestrator so graph write failures do not block report delivery.

```python
# src/streaming/graph_worker.py

@broker.subscriber(
    "research.graph_writeback",
    stream=GRAPH_STREAM,
    durable="graph-writers",
    deliver_policy=DeliverPolicy.ALL,
    pull_sub=PullSub(batch_size=1, timeout=10.0),
)
async def process_graph_writeback(payload: GraphWritebackPayload, logger: Logger) -> None:
    logger.info(f"Graph write-back for task {payload.task_id}")
    try:
        await write_research_to_graph(
            report=payload.report,
            task_id=payload.task_id,
            original_query=payload.query,
            nli_results=payload.nli_results,
            db_pool=deps.db_pool,
            config=deps.config,
        )
    except Exception as e:
        logger.error(
            f"Graph write-back failed for task {payload.task_id}: {e}",
            exc_info=True,
        )
        # Non-fatal. NATS MaxDeliver will retry up to config.nats_max_deliver times.
```

Deploy 1-2 graph writer instances. Graph writes are not latency-sensitive.

### 7.4 Flow Control

All values from `AppConfig` (Section 1.4).

| Parameter | Config Key | Default | Rationale |
|---|---|---|---|
| `MaxAckPending` | `nats_max_ack_pending` | 50 | Task-level distribution; 10 orchestrator instances with buffering |
| `AckWait` | `nats_ack_wait_seconds` | 120s | Full research lifecycle can take 60-120s for standard depth |
| `MaxDeliver` | `nats_max_deliver` | 3 | 1 initial + 2 retries |
| `Backoff` | (hardcoded) | [5s, 30s, 120s] | Graduated retry for transient failures |

### 7.5 SSE Progress Streaming

The SSE endpoint subscribes to the NATS `research.progress.{task_id}` subject. This decouples the SSE handler from the orchestrator process, supports multi-worker deployments, and handles client reconnection. The orchestrator publishes progress events to NATS; the SSE handler relays them to the HTTP client.

```python
# src/api/routes.py

from nats.aio.client import Client as NATSClient

@app.get("/v1/research/{task_id}/stream")
async def stream_progress(task_id: str, nats_client: NATSClient = Depends(get_nats)):
    # Verify task exists
    task = await _get_task(db_pool, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Unknown task_id")
    if task["status"] in ("completed", "failed", "timed_out"):
        raise HTTPException(
            status_code=410,
            detail="Task already completed. Use GET /v1/research/{task_id}.",
        )

    async def event_generator():
        sub = await nats_client.subscribe(f"research.progress.{task_id}")
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(
                        sub.next_msg(),
                        timeout=config.sse_heartbeat_seconds,
                    )
                    event = ProgressEvent.model_validate_json(msg.data)
                    yield {
                        "event": "progress",
                        "data": event.model_dump_json(),
                    }
                    if event.status in (
                        TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMED_OUT,
                    ):
                        break
                except asyncio.TimeoutError:
                    # Heartbeat keeps proxies/load balancers from closing the connection
                    yield {"event": "heartbeat", "data": ""}
                    # Also check if task completed while we were waiting
                    task = await _get_task(db_pool, task_id)
                    if task and task["status"] in ("completed", "failed", "timed_out"):
                        break
        finally:
            await sub.unsubscribe()

    return EventSourceResponse(event_generator())
```

**Why NATS, not in-process queues:** v1.1 used `asyncio.Queue` stored in a module-level dict. This fails when: (a) the SSE endpoint and the orchestrator run in different uvicorn workers, (b) the client connects after events were already published, or (c) the client disconnects and reconnects. The NATS subscription solves all three: events are delivered via the message broker regardless of process topology, and late subscribers receive events from the point of subscription (current events are not replayed, but the GET endpoint provides the final state).

### 7.6 Anti-patterns (NATS / SSE)

- **Do not use in-process queues for SSE progress delivery.** They break in multi-worker deployments. Use NATS subscriptions.
- **Do not use push consumers for research task distribution.** Pull consumers allow orchestrator instances to self-throttle based on processing capacity.
- **Do not rely on SSE connection staying open.** Clients may disconnect. The report is persisted to PostgreSQL regardless of SSE state. The GET endpoint is the fallback.
- **Do not send SSE events without a heartbeat mechanism.** Proxies and load balancers terminate idle connections after 30-60 seconds. The heartbeat event (empty payload) keeps the connection alive.

---

## 8.0 Citation Verification

### 8.1 NLI Cross-Encoder Pipeline

```python
# src/verification/nli_verifier.py

from sentence_transformers import CrossEncoder
from enum import Enum
import numpy as np

class VerificationResult(Enum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    NOT_ENOUGH_INFO = "not_enough_info"

class NLICitationVerifier:
    EXPECTED_LABELS = ["contradiction", "entailment", "neutral"]

    def __init__(
        self,
        model_name: str = "cross-encoder/nli-deberta-v3-base",
        device: str | None = None,
        threshold: float = 0.5,
    ) -> None:
        self.model = CrossEncoder(model_name, device=device)
        self.threshold = threshold

        # Fix #11: Verify label ordering matches our assumption.
        # If the model is updated or swapped, label order may change,
        # which would silently swap contradiction and entailment scores.
        model_labels = list(self.model.config.id2label.values())
        if model_labels != self.EXPECTED_LABELS:
            raise RuntimeError(
                f"NLI model label order mismatch. "
                f"Expected {self.EXPECTED_LABELS}, got {model_labels}. "
                f"Update EXPECTED_LABELS and the score unpacking in verify_batch()."
            )

    def verify_batch(
        self, pairs: list[tuple[str, str]], batch_size: int = 32,
    ) -> list[dict]:
        """Verify (claim, source_passage) pairs via NLI.

        Args:
            pairs: List of (claim_text, source_passage_text) tuples.
        Returns:
            List of dicts with result, entailment_score, contradiction_score.
        """
        nli_pairs = [(source, claim) for claim, source in pairs]
        all_scores = self.model.predict(nli_pairs, batch_size=batch_size)
        results = []
        for (claim, source), scores in zip(pairs, all_scores):
            probs = np.exp(scores - np.max(scores))
            probs /= probs.sum()
            c, e, n = probs
            result = (
                VerificationResult.SUPPORTED if e >= self.threshold
                else VerificationResult.CONTRADICTED if c >= self.threshold
                else VerificationResult.NOT_ENOUGH_INFO
            )
            results.append({
                "claim": claim, "source": source, "result": result.value,
                "entailment": float(e), "contradiction": float(c),
            })
        return results
```

### 8.2 Integration with Synthesis

After the synthesiser produces a `FinalReport`, iterate over each section's claims. For each claim, retrieve the source passage text (from the `document_chunks` table or cached extraction results). Run NLI verification in batch. Claims with `VerificationResult.NOT_ENOUGH_INFO` or `VerificationResult.CONTRADICTED` get their confidence scores downgraded in the final output. Claims with `CONTRADICTED` are flagged in the report's `limitations` field (see invariant S-03 and orchestrator Phase 4 in Section 6.2).

### 8.3 Anti-patterns (Verification)

- **Do not skip NLI verification for performance reasons.** Verification runs in <100ms for a typical report (50 claims x 5ms per pair). It is the primary defence against hallucinated citations.
- **Do not verify claims against search snippets.** Use the full extracted content (from `document_chunks` or Trafilatura output). Snippets are too short for reliable NLI classification.
- **Do not treat `NOT_ENOUGH_INFO` as `SUPPORTED`.** `NOT_ENOUGH_INFO` means the source passage does not contain enough information to verify the claim. Downgrade confidence but do not flag as contradicted.

---

## 9.0 Observability

### 9.1 TimescaleDB Metrics

```sql
CREATE TABLE agent_metrics (
    time        TIMESTAMPTZ NOT NULL,
    task_id     UUID,
    agent_type  TEXT,  -- planner, researcher, synthesiser
    model_used  TEXT,
    input_tokens  INT,
    output_tokens INT,
    latency_ms    INT,
    tool_calls    INT,
    sources_found INT,
    confidence    FLOAT,
    error_code    TEXT  -- NULL for success; ErrorCode value for failures
);

SELECT create_hypertable('agent_metrics', by_range('time'));

-- Continuous aggregate: hourly cost tracking
CREATE MATERIALIZED VIEW agent_cost_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    agent_type,
    model_used,
    SUM(input_tokens) AS total_input_tokens,
    SUM(output_tokens) AS total_output_tokens,
    AVG(latency_ms) AS avg_latency_ms,
    COUNT(*) AS invocations,
    COUNT(*) FILTER (WHERE error_code IS NOT NULL) AS failures
FROM agent_metrics
GROUP BY bucket, agent_type, model_used;
```

### 9.2 Anti-patterns (Observability)

- **Do not log raw prompts or full LLM responses to the metrics table.** These are large text blobs that bloat the hypertable. Store them in the relational `research_tasks` table for debugging, not in time-series.
- **Do not skip logging for failed invocations.** Failed calls with `error_code` populated are the most important signals for reliability monitoring.

---

## 10.0 Testing Approach

### 10.1 Test Matrix

| Layer | Test Type | Tool | What to Assert | Files |
|---|---|---|---|---|
| Planner prompt | Unit | pytest + PydanticAI `TestModel` | Output validates as `ResearchPlan`; invariants P-01 through P-05 hold; depth calibration respects brief/standard/comprehensive | `tests/test_planner.py` |
| Sub-agent tools | Unit | pytest + httpx MockTransport | Tavily response parsing; Trafilatura extraction; graph query formatting; error messages returned on failure | `tests/test_researcher.py` |
| Orchestrator | Integration | pytest-asyncio + NATS test server | Fan-out produces correct number of tasks; aggregation triggers synthesis; gap analysis fires above complexity threshold; invariants O-01 through O-05 | `tests/test_integration.py` |
| Knowledge graph | Integration | pytest + AGE test graph | Entity resolution deduplicates correctly; bi-temporal edges preserve history; hybrid query returns expected results; invariants G-01 through G-04 | `tests/test_graph.py` |
| Graph write-back | Integration | pytest + AGE test graph | Write-back creates correct nodes and edges per Section 3.7.1 mapping; idempotency on re-run | `tests/test_graph.py` |
| NLI verifier | Unit | pytest + fixture pairs | Known entailment/contradiction pairs classified correctly; batch processing handles edge cases | `tests/test_synthesiser.py` |
| API contracts | Contract | pytest + httpx AsyncClient | Request validation rejects invalid input; response schemas match Section 2.3.1; correct HTTP status codes per Section 2.3.2 | `tests/test_api.py` |
| Input sanitisation | Unit | pytest | Injection patterns rejected; clean queries pass; edge cases (unicode, long strings) handled | `tests/test_api.py` |
| AGE Client | Integration | pytest + AGE test graph | Parameter binding prevents injection; agtype parsing returns correct Python types; label order assertion fires on mismatch | `tests/test_graph.py` |
| NER extraction | Unit | pytest + fixture text | Known entities extracted with correct types; deduplication within text; short/numeric entities filtered | `tests/test_graph.py` |
| Error handling | Unit/Integration | pytest | Every ErrorCode in taxonomy has at least one test; error responses match ErrorSpec templates | `tests/test_error_handling.py` |
| End-to-end | E2E | pytest + live APIs (staging) | Full query → report lifecycle; citations are verifiable; report confidence correlates with source quality | `tests/test_integration.py` |

### 10.2 Shared Fixtures

```python
# tests/conftest.py

import pytest
import json
from pathlib import Path
from src.config import AppConfig
from src.agents.models import ResearchPlan, SubAgentFindings, FinalReport


FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def test_config() -> AppConfig:
    """Test configuration with reduced timeouts and budgets."""
    return AppConfig(
        anthropic_api_key="test-key",
        azure_openai_key="test-key",
        azure_openai_endpoint="https://test.openai.azure.com",
        tavily_api_key="test-key",
        token_budget_planner=500,
        token_budget_per_sub_agent=1000,
        token_budget_synthesis=2000,
        sub_agent_timeout_seconds=10.0,
        synthesis_timeout_seconds=15.0,
        total_research_timeout_seconds=60.0,
        min_sub_agent_results_for_synthesis=1,  # Relaxed for unit tests
    )


@pytest.fixture
def sample_plan() -> ResearchPlan:
    """Known-good ResearchPlan for testing downstream components."""
    with open(FIXTURE_DIR / "plans" / "standard_plan.json") as f:
        return ResearchPlan.model_validate_json(f.read())


@pytest.fixture
def sample_findings() -> list[SubAgentFindings]:
    """Known-good SubAgentFindings for testing synthesis."""
    results = []
    for path in sorted((FIXTURE_DIR / "findings").glob("*.json")):
        with open(path) as f:
            results.append(SubAgentFindings.model_validate_json(f.read()))
    return results


@pytest.fixture
def sample_report() -> FinalReport:
    """Known-good FinalReport for testing graph write-back and verification."""
    with open(FIXTURE_DIR / "reports" / "standard_report.json") as f:
        return FinalReport.model_validate_json(f.read())
```

### 10.3 Fixture Data Requirements

Each fixture file must be a valid JSON document that passes Pydantic validation for its respective model. Fixtures must be committed to the repository and updated whenever the Pydantic models change.

| Fixture | File | Contents |
|---|---|---|
| Simple plan (complexity 2) | `fixtures/plans/simple_plan.json` | 2 sub-questions, no dependencies, complexity=2, strategy=thematic |
| Standard plan (complexity 5) | `fixtures/plans/standard_plan.json` | 4 sub-questions, 1 dependency, complexity=5, strategy=comparative |
| Complex plan (complexity 9) | `fixtures/plans/complex_plan.json` | 7 sub-questions, 2 dependencies, complexity=9, strategy=argumentative |
| High-confidence findings | `fixtures/findings/high_confidence.json` | 5 claims, all confidence >= 0.8, 4 sources, no gaps |
| Low-confidence findings | `fixtures/findings/low_confidence.json` | 3 claims, 2 with confidence < 0.3, 2 sources, 1 gap |
| Contradictory findings | `fixtures/findings/contradictory.json` | 4 claims, 1 contradiction flagged, 3 sources |
| Standard report | `fixtures/reports/standard_report.json` | 3 sections, 8 claims, 6 sources, 2 limitations |
| NLI entailment pairs | `fixtures/nli_pairs/entailment.json` | 10 (claim, passage) pairs with known entailment |
| NLI contradiction pairs | `fixtures/nli_pairs/contradiction.json` | 10 (claim, passage) pairs with known contradiction |

### 10.4 Mock Boundaries

| External Service | Mock Strategy | What Is Not Mocked |
|---|---|---|
| Anthropic / Azure / Ollama LLMs | PydanticAI `TestModel` with pre-loaded responses matching Pydantic output schemas | Model selection logic in `FallbackModel` (tested via integration tests with a deliberately-failing primary mock) |
| Tavily search | `httpx.MockTransport` returning fixture search results | Search query construction (verified by inspecting mock call args) |
| Trafilatura | `unittest.mock.patch` on `trafilatura.extract` returning fixture HTML→markdown | Actual HTML parsing (covered by Trafilatura's own test suite) |
| Jina Reader | `httpx.MockTransport` returning fixture JSON | N/A |
| PostgreSQL / AGE | Real PostgreSQL test instance with `research_kg_test` graph (created/destroyed per test session) | Nothing. Graph tests run against real AGE. |
| NATS | `nats.aio.client.Client` connected to an in-memory NATS test server (`nats-server --port 0`) | Nothing. NATS tests run against a real server. |

### 10.5 Anti-patterns (Testing)

- **Do not mock PostgreSQL or AGE in graph tests.** SQL and Cypher syntax differences between mocks and real AGE cause false passes. Use a real test database.
- **Do not use `TestModel` for integration tests.** Integration tests verify the full pipeline including LLM response parsing. Use recorded responses from real LLM calls (snapshot testing).
- **Do not create fixtures by hand.** Generate them by running the relevant agent once against real APIs, validating the output, and saving it. This ensures fixtures are structurally valid.
- **Do not test invariants only via Pydantic validation.** Structural invariants (field types, ranges) are covered by Pydantic. Behavioural invariants (P-01, R-02, O-01, S-03, G-01) require explicit test assertions.

---

## 11.0 Glossary

| Term | Definition |
|---|---|
| BFA | Backend for Agents. Herman's Python framework built on FastAPI, FastStream, PydanticAI, and PostgreSQL. |
| AGE | Apache AGE (A Graph Extension). PostgreSQL extension that adds openCypher graph query support. |
| pgvector | PostgreSQL extension for vector similarity search using HNSW and IVFFlat indexes. |
| Context rot | Degradation of LLM reasoning quality as the context window fills with raw search results and extracted text. |
| Fan-out/fan-in | Concurrency pattern: distribute N tasks in parallel (fan-out), collect all results (fan-in). |
| NLI | Natural Language Inference. Classification of (premise, hypothesis) pairs as entailment, contradiction, or neutral. |
| Pull consumer | NATS JetStream consumer type where clients explicitly request messages, enabling self-balancing across workers. |
| Bi-temporal | Data model tracking both real-world time (when a fact was true) and transaction time (when it was recorded in the system). |
| GraphRAG | Retrieval pattern combining knowledge graph traversal with vector similarity search to provide richer context to LLMs. |
| SDD | Spec-Driven Development. Methodology where a formal specification serves as the authoritative source of truth from which implementation, testing, and documentation are derived. |
| Behavioural invariant | A verifiable assertion about system behaviour that must hold regardless of implementation details. Distinguished from structural validation (Pydantic schemas) which only checks data shape. |
| Error taxonomy | A complete enumeration of error conditions with machine-readable codes, HTTP status mappings, and defined recovery behaviour. |

---

## 12.0 Out of Scope

- **Authentication and authorisation.** The API layer assumes an authenticated user context is provided by the BFA gateway. Role-based access control for research tasks is not covered.
- **Multi-tenant graph isolation.** The current design uses a single `research_kg` graph. Per-tenant or per-workspace graph isolation requires schema changes.
- **PDF and document corpus ingestion.** This spec covers web search retrieval only. Ingesting internal PDFs, Confluence pages, or SharePoint documents is a separate capability.
- **Fine-tuning or training.** All models are used via API. No model fine-tuning is included.
- **Cost optimisation beyond model routing.** Tavily credit management, embedding model selection for cost, and token budget auto-tuning are future work. A cost alert threshold is defined in `AppConfig` (Section 1.4) for monitoring.
- **UI/frontend.** This spec covers the backend platform only.
- **NER model selection and training.** Entity extraction uses spaCy `en_core_web_sm` (Section 3.9). Custom NER training for domain-specific entities is future work.
- **Graph compaction and archival.** The bi-temporal model grows indefinitely. A retention threshold is defined in `AppConfig` (`graph_edge_max_age_days`, Section 1.4) but the compaction logic itself is deferred. Active edges (where `t_expired IS NULL`) are never compacted.
- **Distributed sub-agent execution.** Sub-agents run in-process via `asyncio.gather` (Section 6.2). Distributing individual sub-agents across NATS workers is a potential future optimisation for CPU-bound extraction workloads but adds significant complexity to the aggregation and timeout logic.
