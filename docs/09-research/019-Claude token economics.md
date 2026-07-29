# Claude token economics for a PydanticAI platform on M4 Max

**Bottom line up front.** A solo developer running PydanticAI with Anthropic on a local M4 Max should adopt **Pydantic Logfire (free Personal tier) as the default observability plane**, keep the existing Postgres-plus-JSONL pipeline as the system of record for cost attribution, and add **Grafana OSS as the dashboard layer**. Self-hosted Langfuse is the correct fallback only when cloud Logfire is a hard no. On the Claude side, the largest levers are **prompt caching (≈90% savings on stable prefixes), model routing (Haiku for classify/summarise/worker, Sonnet for orchestrator/critic, Opus only for hard code generation), and `max_tokens` discipline per agent role**. Applied together these typically cut blended cost by 60 to 70% with no measurable quality loss.

The real-model line-up that matters in April 2026 is **Claude Haiku 4.5 ($1/$5 per MTok), Claude Sonnet 4.6 ($3/$15), and Claude Opus 4.7 ($5/$25)**. The user's version numbering maps correctly to current models. Opus 4.7 ships a new tokenizer that produces up to **35% more tokens for the same text**, so headline parity with Opus 4.6 hides an effective price rise: measure before migrating.

The rest of this report is organised as three numbered sections matching the brief, with code, SQL, Docker, and pricing tables you can paste into your platform.

---

## 1. Token monitoring and attribution

### 1.1 PydanticAI's native Usage model

PydanticAI exposes three dataclasses in `pydantic_ai.usage`. **`UsageBase`** carries the token fields, **`RequestUsage`** wraps a single HTTP call, and **`RunUsage`** aggregates an entire `agent.run`. The legacy name `Usage` is a deprecated alias for `RunUsage`.

The fields you care about are `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `details` (dict of provider extras such as reasoning tokens), plus `requests` and `tool_calls` on `RunUsage`. Two caveats matter. First, PydanticAI uses **`cache_write_tokens`**, not `cache_creation_tokens` as the brief named it. Second, `total_tokens` is `input + output` only and excludes cache or audio. If you want the true billed input figure, compute it yourself as `input_tokens + cache_read_tokens + cache_write_tokens` (Anthropic reports the three buckets separately).

```python
from pydantic_ai import Agent

agent = Agent('anthropic:claude-sonnet-4-6')
result = agent.run_sync('Where were the 2012 Olympics held?')
u = result.usage()
# RunUsage(input_tokens=62, output_tokens=34, requests=1)
print(u.input_tokens, u.output_tokens,
      u.cache_read_tokens, u.cache_write_tokens,
      u.requests, u.tool_calls, u.details)
```

**`UsageLimits` is your budget circuit-breaker.** It accepts `request_limit` (default **50**, not `None`), `tool_calls_limit`, `input_tokens_limit`, `output_tokens_limit`, `total_tokens_limit`, and `count_tokens_before_request` (Anthropic, Google, Bedrock Converse only). Violations raise `pydantic_ai.exceptions.UsageLimitExceeded`. The limit applies per run; pass a single shared instance to every `agent.run*` call at app startup.

```python
from pydantic_ai import UsageLimits, UsageLimitExceeded
limits = UsageLimits(
    request_limit=25,
    tool_calls_limit=50,
    total_tokens_limit=200_000,
    output_tokens_limit=8_000,
    count_tokens_before_request=True,
)
```

### 1.2 Usage propagation across multi-agent graphs

PydanticAI offers two idioms, and both hinge on the `usage=` kwarg of `agent.run*`.

**Agent delegation (child called from a tool).** Pass `ctx.usage` into the child so its model calls `incr()` into the parent's live `RunUsage`. This is the pattern to use for orchestrator-plus-workers, because a single `UsageLimits` then caps the entire team.

```python
from pydantic_ai import Agent, RunContext, UsageLimits

orchestrator = Agent('anthropic:claude-sonnet-4-6')
worker       = Agent('anthropic:claude-haiku-4-5', output_type=str)

@orchestrator.tool
async def delegate(ctx: RunContext[None], task: str) -> str:
    r = await worker.run(task, usage=ctx.usage)   # shared accumulator
    return r.output

result = orchestrator.run_sync(
    'Summarise the French Revolution in two bullets',
    usage_limits=UsageLimits(request_limit=6, total_tokens_limit=4_000),
)
# result.usage() covers BOTH orchestrator and worker
```

**Programmatic hand-off.** For sequential pipelines where application code picks the next agent, instantiate a `RunUsage` in outer code and thread it through every call. Same effect, different ownership. This is the right shape for vertical agents running in a deterministic flow.

**Per-tool attribution** is not a first-class `RunUsage` field. Either iterate with `agent.iter()` and diff `run.usage()` across `CallToolsNode` boundaries, or read `execute_tool {name}` spans from OpenTelemetry, which carry `gen_ai.tool.name`, `gen_ai.tool.call.arguments`, and `gen_ai.tool.call.result`. The OTel path is strictly better: it gives you per-tool latency and arg/result capture for free.

### 1.3 OpenTelemetry semantics and Logfire wiring

`logfire.instrument_pydantic_ai()` is the minimum. It emits spec-compliant OpenTelemetry GenAI spans with attributes including `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.details.cache_read_tokens`, `gen_ai.usage.details.cache_write_tokens`, and an `operation.cost` attribute computed from the `genai-prices` library. Two OTel metrics are published: a `gen_ai.client.token.usage` histogram (attribute `gen_ai.token.type=input|output`) and an `operation.cost` histogram in USD.

Three instrumentation controls matter for a CISO context. **Turn off content capture** to avoid sending prompts and tool results upstream: `Agent.instrument_all(InstrumentationSettings(include_content=False))`. **Turn off binary bytes** with `include_binary_content=False`. **Switch run-span aggregation** to avoid double-counting in backends that roll child attributes upward: `InstrumentationSettings(use_aggregated_usage_attribute_names=True)` renames run-span attributes to `gen_ai.aggregated_usage.*`.

Emitting to any OTLP endpoint (local Jaeger, SigNoz, Langfuse, Grafana Tempo) is a one-liner:

```python
import os, logfire
os.environ['OTEL_EXPORTER_OTLP_ENDPOINT'] = 'http://localhost:4318'
logfire.configure(send_to_logfire=False)
logfire.instrument_pydantic_ai()
```

### 1.4 Observability stack choice for a solo dev on M4 Max

Six options were evaluated. The short verdict:

**Primary recommendation: Logfire Personal tier (free).** Pydantic's own pricing schedule (effective 1 January 2026) gives 10 million records per month, one seat, three projects on the free plan. The next tier is Team at $49 per month (same 10M envelope, five seats). Ten million spans roughly corresponds to $100k of Claude spend. Native PydanticAI integration is strictly the best in market. Data retention is 90 days on standard plans. **Self-hosted Logfire exists but is Enterprise-only**, Kubernetes-based, custom priced, not realistic for one person.

**If cloud is a hard no, use Langfuse self-hosted v3.** Six containers (`langfuse-web`, `langfuse-worker`, Postgres, ClickHouse, Redis, MinIO), all arm64-native. Realistic RAM footprint on M4 Max is **6 to 8 GiB** for the full stack; budget it. Integrates with PydanticAI via the OTLP endpoint at `http://localhost:3000/api/public/otel` (HTTP/JSON or HTTP/protobuf, **no gRPC**). Anthropic cache-token cost is auto-attributed because Langfuse ships default Claude 3.5/4.x pricing and honours `gen_ai.usage.details.cache_*`. Licence is MIT core with EE-gated extras. Mitigate ClickHouse disk sprawl from day one with `LANGFUSE_INGESTION_CLICKHOUSE_WRITE_INTERVAL_MS=5000` and TTLs on `system.trace_log`.

**Helicone** is an HTTP proxy, not a tracer. That mismatches PydanticAI's structured trace model: you lose tool-call granularity and see only raw HTTP. Useful for a pure spend-tracking use case, not for agent debugging. Self-hosted Helicone is now a single Docker command (Apache 2.0) but currently only supports OpenAI and Anthropic backends.

**SigNoz** has first-class GenAI dashboards and OTel semantic conventions, but Apple Silicon support still has rough edges in April 2026 (the default compose file pulls some amd64 images for Zookeeper and friends). Expect to edit the compose or run through Rosetta. Not worth the friction given Langfuse exists.

**Jaeger all-in-one** is the lightest option at roughly 300 MiB RAM. Use it when you want a quick disposable view during local debugging, not as the long-term store; it has no cost rollup, no token aggregation, and no GenAI dashboards.

**Full Grafana LGTM** (Tempo, Loki, Prometheus, Grafana) is overkill for a solo dev who isn't already running that stack.

**Table: observability option ranking**

| Criterion | Logfire free | Langfuse OSS | SigNoz | Jaeger | Helicone OSS |
|---|---|---|---|---|---|
| Setup on M4 Max | pip + one env var | Six containers, arm64 | arm64 partial | Single container | One compose |
| PydanticAI fit | Native | OTLP | OTLP | OTLP | HTTP proxy |
| Claude cache cost attribution | Built-in | Built-in, configurable | Tokens yes, $ DIY | None | Built-in |
| Steady-state RAM | 0 local | 6 to 8 GiB | ~4 GiB | ~300 MiB | ~2 to 4 GiB |
| Data sovereignty | Cloud | Local | Local | Local | Local |

### 1.5 Extending JSONL and Postgres for token attribution

Keep JSONL as the ingest buffer (append-only, crash-tolerant) and Postgres as the queryable system of record. The schema below is designed to pair with OTel attributes and Anthropic's per-TTL cache breakdown.

**Core tables.** `runs` stores one row per `agent.run` with `parent_run_id` self-reference plus an `ltree`-backed `agent_path` populated by a trigger (O(log n) sub-tree queries without recursive CTEs). `llm_calls` is declaratively partitioned by month on `ts` with BRIN on `ts` (ideal for append-only workloads) and btree on `run_id` and `(model, ts DESC)`. `tool_calls` stores `args_hash` and `result_hash` to drive dedup and memoisation analytics. `model_pricing` holds time-bounded `$/MTok` rows with a `tstzrange` exclusion constraint so overlapping periods are impossible.

```sql
-- Abbreviated; full migration in the research notes
CREATE TABLE runs (
    run_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_run_id   uuid REFERENCES runs(run_id) ON DELETE SET NULL,
    agent_id        text NOT NULL,
    agent_role      text NOT NULL,
    conversation_id uuid,
    user_id         text,
    started_at      timestamptz NOT NULL DEFAULT now(),
    ended_at        timestamptz,
    status          text NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running','ok','error','cancelled','limit_breach')),
    total_cost_usd  numeric(18,8) NOT NULL DEFAULT 0,
    agent_path      ltree,
    tags            jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE llm_calls (
    call_id                  uuid NOT NULL DEFAULT gen_random_uuid(),
    run_id                   uuid NOT NULL,
    model                    text NOT NULL,
    provider                 text NOT NULL,
    input_tokens             integer NOT NULL DEFAULT 0,   -- uncached input only
    output_tokens            integer NOT NULL DEFAULT 0,
    cache_creation_5m_tokens integer NOT NULL DEFAULT 0,
    cache_creation_1h_tokens integer NOT NULL DEFAULT 0,
    cache_read_tokens        integer NOT NULL DEFAULT 0,
    thinking_tokens          integer NOT NULL DEFAULT 0,
    cost_usd                 numeric(18,8),
    latency_ms               integer,
    request_id               text,
    ts                       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (call_id, ts),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
) PARTITION BY RANGE (ts);
CREATE INDEX llm_calls_ts_brin   ON llm_calls USING brin (ts);
CREATE INDEX llm_calls_run_idx   ON llm_calls (run_id);
CREATE INDEX llm_calls_model_ts  ON llm_calls (model, ts DESC);

CREATE TABLE tool_calls (
    tool_call_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id       uuid NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    tool_name    text NOT NULL,
    args_hash    bytea NOT NULL,          -- sha256 of canonicalised args
    result_hash  bytea,
    duration_ms  integer,
    ts           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE model_pricing (
    model                         text NOT NULL,
    effective_from                timestamptz NOT NULL,
    effective_to                  timestamptz NOT NULL DEFAULT 'infinity',
    price_per_mtok_input          numeric(12,6) NOT NULL,
    price_per_mtok_output         numeric(12,6) NOT NULL,
    price_per_mtok_cache_write_5m numeric(12,6),
    price_per_mtok_cache_write_1h numeric(12,6),
    price_per_mtok_cache_read     numeric(12,6),
    PRIMARY KEY (model, effective_from),
    CHECK (effective_to > effective_from)
);

-- Seed (16 April 2026 Anthropic list prices)
INSERT INTO model_pricing VALUES
 ('claude-opus-4-7',   '2026-04-16', 'infinity', 5.00, 25.00, 6.25, 10.00, 0.50),
 ('claude-sonnet-4-6', '2026-02-01', 'infinity', 3.00, 15.00, 3.75,  6.00, 0.30),
 ('claude-haiku-4-5',  '2025-10-01', 'infinity', 1.00,  5.00, 1.25,  2.00, 0.10);
```

**Cost view.** Use a `LEFT JOIN LATERAL` so price lookups are bounded and partition-pruning-friendly. Store the three Anthropic cache buckets separately and compute cost at query time; this avoids the double-count bug (Langfuse issue #12306) that hits teams who sum Anthropic `input_tokens` with OTel-summed input attributes.

```sql
CREATE OR REPLACE VIEW v_llm_calls_costed AS
SELECT c.*, r.agent_id, r.agent_role,
  (c.input_tokens/1e6)*p.price_per_mtok_input
  + ((c.output_tokens+c.thinking_tokens)/1e6)*p.price_per_mtok_output
  + (c.cache_creation_5m_tokens/1e6)*p.price_per_mtok_cache_write_5m
  + (c.cache_creation_1h_tokens/1e6)*p.price_per_mtok_cache_write_1h
  + (c.cache_read_tokens/1e6)*p.price_per_mtok_cache_read
  AS total_cost_usd
FROM llm_calls c JOIN runs r USING (run_id)
LEFT JOIN LATERAL (
    SELECT * FROM model_pricing mp
    WHERE mp.model = c.model
      AND c.ts >= mp.effective_from AND c.ts < mp.effective_to
    ORDER BY mp.effective_from DESC LIMIT 1
) p ON TRUE;
```

### 1.6 Local dashboard: Grafana OSS on arm64

**Grafana beats Metabase and Superset for this workload.** The data is overwhelmingly time-series (tokens per hour, cost per day, p95 latency, cache hit rate), Grafana's arm64 image idles at ~300 MiB against Metabase's ~1 GiB JVM, and the Postgres datasource macros (`$__timeFilter`, `$__timeGroup`) map directly onto the schema. Keep Metabase in reserve only if non-technical stakeholders need click-to-filter access.

```yaml
# compose.yaml
services:
  grafana:
    image: grafana/grafana-oss:11.3.0
    platform: linux/arm64
    ports: ["3000:3000"]
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: admin
    volumes:
      - grafana-data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
    deploy: { resources: { limits: { memory: 512M } } }
volumes: { grafana-data: }
```

The six dashboard panels worth building on day one are: tokens per hour stacked by agent, cost per day by model, cache hit rate per agent, p95 latency per agent, `UsageLimits` breach count, and tool-call dedup opportunities (count of repeated `args_hash` per day). The SQL for cache hit rate is instructive because it reveals prefix instability problems early:

```sql
SELECT $__timeGroup(c.ts, '$__interval') AS time,
       r.agent_id AS metric,
       CASE WHEN sum(c.input_tokens + c.cache_read_tokens) = 0 THEN 0
            ELSE sum(c.cache_read_tokens)::float
                 / sum(c.input_tokens + c.cache_read_tokens) END AS value
FROM llm_calls c JOIN runs r USING (run_id)
WHERE $__timeFilter(c.ts)
GROUP BY 1, 2 ORDER BY 1;
```

### 1.7 Anthropic response fields and cost calculation

Claude's `usage` object returns four fields relevant to billing: `input_tokens` (uncached only), `output_tokens`, `cache_creation_input_tokens`, and `cache_read_input_tokens`. When mixing TTLs within a request, a `cache_creation` sub-object breaks creation tokens down by TTL. **A cache was not hit if both creation and read counts are zero.**

Cost per request in pseudo-Python:

```python
PRICE = {  # $/MTok: input, output, write_5m, write_1h, read
    'claude-haiku-4-5':  (1.00,  5.00, 1.25,  2.00, 0.10),
    'claude-sonnet-4-6': (3.00, 15.00, 3.75,  6.00, 0.30),
    'claude-opus-4-7':   (5.00, 25.00, 6.25, 10.00, 0.50),
}
def cost(model, u, thinking_tokens=0):
    p = PRICE[model]
    return (u.input_tokens             * p[0]
          + (u.output_tokens + thinking_tokens) * p[1]
          + u.cache_creation_input_tokens_5m * p[2]
          + u.cache_creation_input_tokens_1h * p[3]
          + u.cache_read_input_tokens   * p[4]) / 1e6
```

Thinking tokens are billed as output at the model's normal output rate. Setting `display: "omitted"` reduces latency and payload but not cost. The `/v1/messages/count_tokens` endpoint is **free** and supports the same payload shape (system, tools, images, PDFs, thinking); use it in CI to budget requests before sending.

---

## 2. Cost optimisation without losing effectiveness

### 2.1 Current Claude pricing and key constraints (April 2026)

**Model lineup and per-million-token pricing:**

| Model | Input | Cache write 5m | Cache write 1h | Cache read | Output | Context | Max output |
|---|---|---|---|---|---|---|---|
| Claude Opus 4.7 | $5 | $6.25 | $10 | $0.50 | $25 | 1M (flat) | 128K sync / 300K batch |
| Claude Sonnet 4.6 | $3 | $3.75 | $6 | $0.30 | $15 | 1M (flat) | 64K sync / 300K batch |
| Claude Haiku 4.5 | $1 | $1.25 | $2 | $0.10 | $5 | 200K | 64K |

Output is **5x input across all three tiers**. Cost ratios: Sonnet = 3x Haiku, Opus = 1.67x Sonnet ≈ 5x Haiku. Opus 4.7 and Sonnet 4.6 both ship 1M context with **flat pricing** (no surcharge above 200K, no beta header needed). Sonnet 4.5's 1M beta retires 30 April 2026 and carries a 2x input / 1.5x output surcharge until then; migrate now.

Surcharges to watch: **US-only inference (`inference_geo`) is 1.1x on every token category** for Opus 4.6+. Bedrock and Vertex regional endpoints add **+10%** over global. Opus 4.6 Fast Mode is **6x list price** ($30/$150); avoid unless latency is revenue-critical.

### 2.2 Prompt caching is the single biggest lever

Mechanics. Up to **4 `cache_control` breakpoints per request**. Automatic check for hits at content-block boundaries up to ~20 blocks behind each breakpoint. Minimum cacheable prefix is **1,024 tokens** on all 4.x models. Writes below that threshold fail silently (both cache counters return zero). TTL multipliers are **1.25x input for 5m writes, 2x for 1h writes, 0.1x for reads**. Break-even: one read pays back a 5m write; two reads pay back a 1h write.

The cache hierarchy is **tools → system → messages**. Anything that changes invalidates downstream blocks: `tool_choice` flips, presence or absence of images anywhere, thinking-mode changes on the assistant turn, budget changes. Thinking blocks cannot be directly marked `cache_control` but travel as part of the prefix. Switching between `adaptive` and `enabled` thinking modes breaks message-level cache hits but leaves system and tool caches intact.

PydanticAI now surfaces cache control natively:

```python
from pydantic_ai import Agent, CachePoint
from pydantic_ai.models.anthropic import AnthropicModelSettings

orchestrator = Agent(
    'anthropic:claude-sonnet-4-6',
    instructions='... long stable policy text ...',
    model_settings=AnthropicModelSettings(
        anthropic_cache_instructions='1h',     # static system block
        anthropic_cache_tool_definitions='1h', # tool schemas
        anthropic_cache=True,                  # auto-cache last block
        max_tokens=1024,
    ),
)

async def ask(question: str, retrieved_docs: str):
    # CachePoint goes after retrieved docs, before the variable question
    return await orchestrator.run([retrieved_docs, CachePoint(), question])
```

**TTL decision rule.** If the p95 gap between hits on the same prefix exceeds 4 minutes, use 1h. 5m is fine for single-user chat and tight loops under 5 minutes. 1h is correct for shared orchestrator prefixes, loops that pause on external I/O or human approval, batch jobs, and any multi-agent fleet sharing tool schemas. The 4-block cap is easy to trip: `anthropic_cache_instructions` plus `anthropic_cache_tool_definitions` plus `anthropic_cache=True` plus one `CachePoint()` already equals four.

**Target cache hit rate:** `cache_read_tokens / (cache_read_tokens + input_tokens) > 60%` in steady state for any agent called more than a handful of times per minute. Below that, your prefix is churning.

### 2.3 Model routing by agent role

| Role | Model | Reason |
|---|---|---|
| Classifier, router | Haiku 4.5 | Short labels, `output_type=Literal[...]`, 3x cheaper than Sonnet |
| Summariser | Haiku 4.5 | Long input / short output exactly fits Haiku's 1:5 ratio |
| Worker (extract, fill, tool args) | Haiku 4.5 | Low branching; escalate only on failure |
| Orchestrator, planner | Sonnet 4.6 | Multi-step planning, within 1 to 2 percentage points of Opus on SWE-bench at 40% less |
| Critic, evaluator | Sonnet 4.6 | Subtle judgement, keep `max_tokens=256` |
| Research agent | Sonnet 4.6 | Long loops benefit from adaptive thinking; Opus rarely pays back |
| Hard code generation | Opus 4.7 | Only tier where the quality delta is measurable; gate behind a difficulty classifier |

**Escalation pattern** (Haiku → Sonnet → Opus) is the single biggest cost saver after caching. Escalate on schema validation failure or a deterministic signal, not on self-reported confidence (noisy). At a realistic 60 / 35 / 5 split, effective input rate collapses from $3 (all-Sonnet) to roughly $1.45 per MTok.

```python
async def escalating_answer(prompt: str):
    r1 = await haiku.run(prompt)
    if schema_ok(r1.output) and r1.output.confidence >= 0.80:
        return r1.output, 'haiku'
    r2 = await sonnet.run(prompt, message_history=r1.all_messages())
    if schema_ok(r2.output) and r2.output.confidence >= 0.55:
        return r2.output, 'sonnet'
    r3 = await opus.run(prompt, message_history=r2.all_messages())
    return r3.output, 'opus'
```

### 2.4 Message Batches API: when it applies

**50% off input and output**, stacks with prompt caching, 24h SLA (most finish in under an hour), up to 100,000 requests or 256 MB per batch. Supported on every current-gen model. The 300K output token beta (`output-300k-2026-03-24`) is batch-only on Opus 4.7 / 4.6 and Sonnet 4.6.

Good fits for your platform: **offline evaluation suites, synthetic data generation, nightly bulk research passes, backtesting prompts against historical logs, mass summarisation of a document corpus**. Bad fits: interactive agent turns, any coordinated multi-agent loop needing tool-result feedback within a turn. Split at 2K to 5K requests per batch during peak demand to avoid the 24h expiry edge.

### 2.5 Context window management

**Three tactics in order of preference.** First, aggressive caching of the stable prefix turns 100K of system context into $0.30 per MTok (Sonnet 4.6 read price) rather than $3. Second, a Haiku-based summariser checkpoint every ~20 turns costs about a third of the Sonnet calls it eliminates. Third, `AnthropicCompaction(token_threshold=100_000)` is a server-side belt-and-braces safety net that runs once input crosses the threshold; use it as a floor, not a primary control.

```python
from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicCompaction, AnthropicModelSettings

summariser = Agent('anthropic:claude-haiku-4-5',
    instructions='Summarise. Preserve IDs, numbers, pending actions.',
    model_settings=AnthropicModelSettings(max_tokens=800))

async def checkpoint_summariser(ctx, messages):
    if len(messages) <= 20: return messages
    old, recent = messages[:-20], messages[-20:]
    s = await summariser.run(message_history=old)
    return s.new_messages() + repair_tool_pairs(recent)

agent = Agent('anthropic:claude-sonnet-4-6',
    history_processors=[checkpoint_summariser],
    capabilities=[AnthropicCompaction(token_threshold=100_000)])
```

**RAG vs stuff rule.** Under 20K tokens of reusable reference content: stuff it and cache behind a `CachePoint()`. Over 50K with high churn or narrow per-query relevance: use pgvector on the existing Postgres. IVFFlat with `lists = sqrt(N)` for under 10M rows; HNSW above that. voyage-3-large at 1024-d embeddings is the default; BGE-large-en-v1.5 runs free locally on the M4 Max's Metal GPU and matches it on English recall.

### 2.6 Tool schema discipline

Anthropic includes the full tool schema on every non-cached request. A 20-tool fleet at 200 tokens each burns 4,000 tokens per call. Rules: verb-plus-object descriptions under **50 tokens**, `Literal` or enums instead of free-text parameters, per-role tool subsets via PydanticAI `FunctionToolset` or `prepare_tools`, and a regression test that calls `messages.count_tokens(tools=...)` and fails if schema cost exceeds 1,000 tokens.

```python
from pydantic_ai.toolsets import FunctionToolset

read_tools  = FunctionToolset([get_user, find_orders, get_invoice])
write_tools = FunctionToolset([refund, cancel_order])

reader = Agent('anthropic:claude-sonnet-4-6', toolsets=[read_tools])
writer = Agent('anthropic:claude-sonnet-4-6', toolsets=[read_tools, write_tools])
```

### 2.7 Output token control

Output is the expensive side (5x input). Cap `max_tokens` per role:

```python
classifier   = Agent(HAIKU,  model_settings=AnthropicModelSettings(max_tokens=64))
worker       = Agent(HAIKU,  model_settings=AnthropicModelSettings(max_tokens=256))
summariser   = Agent(HAIKU,  model_settings=AnthropicModelSettings(max_tokens=800))
orchestrator = Agent(SONNET, model_settings=AnthropicModelSettings(max_tokens=1024))
critic       = Agent(SONNET, model_settings=AnthropicModelSettings(max_tokens=256))
code_gen     = Agent(OPUS,   model_settings=AnthropicModelSettings(max_tokens=4096))
```

Use `output_type=Pydantic model` with `Literal` unions and `Field(max_length=...)` on string fields to make the schema itself a length constraint. This forces the model through a structured tool call, which also makes retries deterministic.

### 2.8 Extended and adaptive thinking

Adaptive thinking (Opus 4.7, Sonnet 4.6) auto-regulates and is the right default. **Opus 4.7 only supports adaptive**: manual `budget_tokens` returns 400. Enable thinking only for hard code generation, multi-step planning, complex SQL, and root-cause debugging. Never for classification, routing, extraction, or any task with <256 output tokens; thinking tokens are billed as output and swamp the real answer. For long thinking sessions (>5 minutes) prefer 1h cache TTL.

### 2.9 Tool-call memoisation and search coalescing

The two patterns that compound. **Memoise read-only tools with SHA-256 of canonicalised args as key**, TTL tuned to the tool's staleness tolerance (30s for volatile search, 15 min for web fetch, 1h for reference data). Redis is cleanest; Postgres with a `tool_cache` table works if you want auditability.

**Per-run search coalescing.** Namespace the memoisation cache by `run_id` with a 30s TTL. Concurrent sub-agents in the same team that happen to issue the same query then hit cache, not Anthropic. The alternative (and often better) shape is a **single search gateway**: only the orchestrator holds the search tool; sub-agents request via a typed parameter and the orchestrator batches.

---

## 3. Practical workflow

### 3.1 Baseline week

Turn on Logfire, let it run for seven days, then aggregate. Three queries answer the only questions that matter.

**Top 3 token sinks** by cost in the last 7 days:
```sql
SELECT agent_id, agent_role, count(*) calls,
       sum(total_cost_usd)::numeric(12,4) AS cost_usd
FROM v_llm_calls_costed
WHERE ts >= now() - interval '7 days'
GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 5;
```

**p50 / p95 / p99 tokens per run per agent_role:**
```sql
WITH per_run AS (
  SELECT r.run_id, r.agent_role,
         sum(c.input_tokens + c.output_tokens + c.thinking_tokens
           + c.cache_creation_5m_tokens + c.cache_creation_1h_tokens
           + c.cache_read_tokens) AS tokens
  FROM runs r JOIN llm_calls c USING (run_id)
  WHERE r.started_at >= now() - interval '7 days'
  GROUP BY 1, 2)
SELECT agent_role, count(*) runs,
  percentile_cont(0.50) WITHIN GROUP (ORDER BY tokens)::int AS p50,
  percentile_cont(0.95) WITHIN GROUP (ORDER BY tokens)::int AS p95,
  percentile_cont(0.99) WITHIN GROUP (ORDER BY tokens)::int AS p99
FROM per_run GROUP BY 1 ORDER BY p95 DESC;
```

**Cache hit rate and dedup opportunities** (queries in §1.5, §1.6). In practice the top three sinks are almost always: oversized tool schemas on a high-traffic agent, an uncached orchestrator system prompt, and a summariser running on Sonnet when it should be on Haiku. Fixing these is 80% of the bill.

### 3.2 A/B harness

Run the same cases through two model configurations concurrently with `asyncio.gather`, score with both a deterministic check and a Haiku-as-judge, then ship the cheaper variant only if `quality_B >= quality_A * (1 - 0.02)` and `pass_rate_B >= pass_rate_A`.

```python
async def score_once(agent, case, judge):
    t0 = time.perf_counter()
    r = await agent.run(case['prompt'])
    u = r.usage()
    passed = case.get('must_contain', '') in str(r.output)
    j = await judge.run(f"Ref: {case['reference']}\nCand: {r.output}\n"
                        f"Return 0..1 quality score only.")
    quality = float(str(j.output).strip() or 0)
    return dict(passed=passed, quality=quality,
                latency=time.perf_counter()-t0,
                input=u.input_tokens, output=u.output_tokens,
                cache_read=u.cache_read_tokens)
```

### 3.3 Alerting thresholds and per-run budgets

`UsageLimits` is the per-run safety rail. Set it at three layers: a global default (`request_limit=25`, `total_tokens_limit=200_000`, `output_tokens_limit=8_000`), a per-role override (a classifier should have `request_limit=1, output_tokens_limit=128`), and an emergency override via feature flag that can drop every agent to Haiku instantly.

Export per-run cost as a Prometheus counter from a Logfire exporter or a thin shim, then alert on three PromQL rules in Grafana:

```promql
# Hourly spend > $5
sum(increase(llm_cost_usd_total[1h])) > 5
# Any single agent > $2/hour: likely runaway loop
sum by (agent) (increase(llm_cost_usd_total[1h])) > 2
# Orchestrator cache hit rate below 40%: prefix instability
sum(rate(llm_tokens_total{agent="orchestrator",kind="cache_read"}[15m]))
/ sum(rate(llm_tokens_total{agent="orchestrator",kind=~"input|cache_read"}[15m]))
< 0.4
```

Pair with a circuit breaker: if the last five runs average over N tokens, the feature flag drops the agent to the cheaper tier automatically until a human investigates.

### 3.4 Recommended architecture and implementation sequence

**Stack decision:** Logfire Personal (free) as the trace plane, existing JSONL plus Postgres as the system of record and spend attribution, Grafana OSS arm64 as the dashboard layer, `pgvector` for RAG on the same Postgres, Redis (or `tool_cache` table) for tool memoisation. Add Langfuse self-hosted only if cloud Logfire becomes politically unacceptable.

This stack **costs zero in cash**, consumes roughly 800 MiB of local RAM (Grafana plus Redis), keeps sensitive prompts on the M4 Max (Logfire `include_content=False`), and gives you currency-denominated cost attribution out of the box.

**Implementation sequence (two weeks, low risk at each step):**

1. Day 1. `logfire.instrument_pydantic_ai()` with `include_content=False`. Ship. Free observability.
2. Day 2. Apply the Postgres migration. Write an OTel exporter that consumes `gen_ai.*` spans from Logfire (or a span processor tap) and inserts into `llm_calls` and `tool_calls`.
3. Day 3. Stand up Grafana OSS via the compose file, provision the Postgres datasource read-only, import the six panels.
4. Day 4 to 7. Baseline. Let it run. Identify top-3 sinks.
5. Week 2. Apply fixes in this order: tool-schema pruning, `anthropic_cache_instructions='1h'` on the orchestrator, Haiku-based summariser, model routing by role, escalation ladder, tool memoisation. Re-baseline after each. Expect a 60 to 70% cost cut.
6. Day 14. Add `UsageLimits` per role and the three Grafana alerts. Wire feature-flag-driven emergency downgrade.

## 4. Conclusion

The hard-won insight is that **cost optimisation for Claude agentic systems is dominated by two moves**: cache the stable prefix aggressively (at 1h TTL whenever the agent loop might cross 5 minutes), and route by role with Haiku as the default and Opus as the exception. Every other tactic - output caps, tool schema pruning, summarisation checkpoints, memoisation, batch API - is additive and matters, but these two alone account for the majority of the blended savings reported in practice.

Observability is a solved problem for this persona. **Logfire free tier plus a Postgres attribution layer plus Grafana OSS gives you currency-denominated per-agent, per-run, per-tool cost at zero cash cost and under a gigabyte of RAM.** The self-hosted alternatives (Langfuse, SigNoz, the full LGTM stack) are worth the operational surface only when data sovereignty is a hard constraint. For a CISO whose day job is building agentic systems, starting with Logfire and owning the Postgres schema is the path with the shortest time to actionable insight and the clearest audit trail.

One genuine risk worth naming: **Opus 4.7's new tokenizer can inflate apparent token consumption by up to 35% on identical prose versus Opus 4.6**. If you use Opus anywhere in the stack, re-baseline after the 16 April 2026 migration; list-price parity is misleading. Adaptive thinking is another subtle trap: it is off by default on the right tasks, on by default on the wrong ones, and thinking tokens are billed as output. Explicit `anthropic_effort='low'` on classifiers and routers prevents silent cost creep.

Ship Logfire and the Postgres schema today. Cache tomorrow. Route by role the day after. Measure everything.
