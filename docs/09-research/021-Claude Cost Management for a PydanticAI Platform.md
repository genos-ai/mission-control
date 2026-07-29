# Claude Cost Management for a PydanticAI Platform

**Focus.** Observability first, caching second. Everything else is downstream of knowing where the money goes.

**Scope.** Local M4 Max, PydanticAI, home-grown JSONL plus Postgres already in place. The goal is to turn "I'm burning tokens" into a per-token-type, per-run, per-agent, per-model cost attribution you can act on in under 30 seconds.

---

## 1.0 The observability stack

### 1.1 Stack choice

Three components, zero cash cost, under 1 GiB of RAM on the M4 Max.

| Component | Role | Footprint |
|---|---|---|
| Pydantic Logfire (Personal, free) | Trace ingestion, GenAI semantic conventions, prompt/response capture when enabled | 10M spans/month free, no local RAM |
| PostgreSQL (existing) | Cost system of record, time-partitioned `llm_calls`, price history | ~400 MiB |
| Grafana OSS | Dashboard layer, Postgres datasource, alerts | ~300 MiB |

Logfire handles trace ingestion and gives us OpenTelemetry GenAI semantic conventions for free. Postgres is the queryable store of truth for cost. Grafana renders.

**Why not Langfuse/Helicone/SigNoz.** Langfuse is excellent but runs six containers and 6 to 8 GiB of RAM. Helicone is a proxy, which loses tool-call granularity in a multi-agent graph. SigNoz has rough arm64 edges. None of them beat Logfire plus our own Postgres for this specific use case.

### 1.2 Wire Logfire into PydanticAI

One-time setup:

```python
import logfire
from pydantic_ai import Agent
from pydantic_ai.instrumentation import InstrumentationSettings

logfire.configure(
    service_name='genos-ai',
    send_to_logfire=True,  # free tier
)

# Content capture off for sensitive workloads; turn on selectively per agent
Agent.instrument_all(InstrumentationSettings(
    include_content=False,
    include_binary_content=False,
    use_aggregated_usage_attribute_names=True,  # avoids double-counting in dashboards
))
logfire.instrument_pydantic_ai()
```

The spans will carry these attributes out of the box: `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.details.cache_read_tokens`, `gen_ai.usage.details.cache_write_tokens`, `gen_ai.usage.details.reasoning_tokens`, and an `operation.cost` attribute computed from the `genai-prices` library.

### 1.3 Postgres schema for cost attribution

Three tables. `runs` holds one row per `agent.run()`, with a self-referencing `parent_run_id` so a multi-agent graph is queryable. `llm_calls` is partitioned monthly by `ts`. `model_pricing` keeps time-bounded rates so historical cost stays correct across price changes.

```sql
CREATE EXTENSION IF NOT EXISTS ltree;

CREATE TABLE runs (
    run_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_run_id   uuid REFERENCES runs(run_id) ON DELETE SET NULL,
    agent_id        text NOT NULL,
    agent_role      text NOT NULL,     -- orchestrator | worker | classifier | summariser | critic | code_gen
    conversation_id uuid,
    user_id         text,
    started_at      timestamptz NOT NULL DEFAULT now(),
    ended_at        timestamptz,
    status          text NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running','ok','error','cancelled','limit_breach')),
    agent_path      ltree,
    tags            jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX runs_started_brin ON runs USING brin (started_at);
CREATE INDEX runs_role_idx     ON runs (agent_role);
CREATE INDEX runs_conv_idx     ON runs (conversation_id);

CREATE TABLE llm_calls (
    call_id                  uuid NOT NULL DEFAULT gen_random_uuid(),
    run_id                   uuid NOT NULL,
    model                    text NOT NULL,
    provider                 text NOT NULL DEFAULT 'anthropic',
    input_tokens             integer NOT NULL DEFAULT 0,   -- uncached input only
    output_tokens            integer NOT NULL DEFAULT 0,
    cache_creation_5m_tokens integer NOT NULL DEFAULT 0,
    cache_creation_1h_tokens integer NOT NULL DEFAULT 0,
    cache_read_tokens        integer NOT NULL DEFAULT 0,
    thinking_tokens          integer NOT NULL DEFAULT 0,
    latency_ms               integer,
    request_id               text,
    ts                       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (call_id, ts),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
) PARTITION BY RANGE (ts);

CREATE INDEX llm_calls_ts_brin   ON llm_calls USING brin (ts);
CREATE INDEX llm_calls_run_idx   ON llm_calls (run_id);
CREATE INDEX llm_calls_model_ts  ON llm_calls (model, ts DESC);

-- Monthly partitions (generate ahead with pg_partman or a cron)
CREATE TABLE llm_calls_2026_04 PARTITION OF llm_calls
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE llm_calls_2026_05 PARTITION OF llm_calls
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');

CREATE TABLE model_pricing (
    model                         text NOT NULL,
    effective_from                timestamptz NOT NULL,
    effective_to                  timestamptz NOT NULL DEFAULT 'infinity',
    price_per_mtok_input          numeric(12,6) NOT NULL,
    price_per_mtok_output         numeric(12,6) NOT NULL,
    price_per_mtok_cache_write_5m numeric(12,6),
    price_per_mtok_cache_write_1h numeric(12,6),
    price_per_mtok_cache_read     numeric(12,6),
    PRIMARY KEY (model, effective_from)
);

-- Current Anthropic list prices (April 2026)
INSERT INTO model_pricing VALUES
 ('claude-opus-4-7',   '2026-04-16', 'infinity', 5.00, 25.00, 6.25, 10.00, 0.50),
 ('claude-sonnet-4-6', '2026-02-01', 'infinity', 3.00, 15.00, 3.75,  6.00, 0.30),
 ('claude-haiku-4-5',  '2025-10-01', 'infinity', 1.00,  5.00, 1.25,  2.00, 0.10);
```

### 1.4 The costed view

The dashboard queries all hit one view. Keep it as a view, not a materialised view, until you exceed ~10M rows per month; the BRIN index makes scans cheap enough.

```sql
CREATE OR REPLACE VIEW v_llm_calls_costed AS
SELECT
    c.call_id,
    c.run_id,
    c.model,
    c.ts,
    c.latency_ms,
    c.input_tokens,
    c.output_tokens,
    c.thinking_tokens,
    c.cache_creation_5m_tokens,
    c.cache_creation_1h_tokens,
    c.cache_read_tokens,
    r.agent_id,
    r.agent_role,
    r.conversation_id,
    -- Cost components (in USD)
    (c.input_tokens / 1e6) * p.price_per_mtok_input                 AS cost_input_usd,
    ((c.output_tokens + c.thinking_tokens) / 1e6) * p.price_per_mtok_output AS cost_output_usd,
    (c.thinking_tokens / 1e6) * p.price_per_mtok_output             AS cost_thinking_usd,
    (c.cache_creation_5m_tokens / 1e6) * p.price_per_mtok_cache_write_5m AS cost_cache_write_5m_usd,
    (c.cache_creation_1h_tokens / 1e6) * p.price_per_mtok_cache_write_1h AS cost_cache_write_1h_usd,
    (c.cache_read_tokens / 1e6) * p.price_per_mtok_cache_read       AS cost_cache_read_usd,
    -- Total
    ((c.input_tokens / 1e6) * p.price_per_mtok_input
     + ((c.output_tokens + c.thinking_tokens) / 1e6) * p.price_per_mtok_output
     + (c.cache_creation_5m_tokens / 1e6) * p.price_per_mtok_cache_write_5m
     + (c.cache_creation_1h_tokens / 1e6) * p.price_per_mtok_cache_write_1h
     + (c.cache_read_tokens / 1e6) * p.price_per_mtok_cache_read) AS total_cost_usd
FROM llm_calls c
JOIN runs r USING (run_id)
LEFT JOIN LATERAL (
    SELECT mp.*
    FROM model_pricing mp
    WHERE mp.model = c.model
      AND c.ts >= mp.effective_from
      AND c.ts <  mp.effective_to
    ORDER BY mp.effective_from DESC
    LIMIT 1
) p ON TRUE;
```

### 1.5 Bridging Logfire to Postgres

Two viable shapes.

**Shape A: span processor tap.** Register a span processor inside the Python process that writes rows to `llm_calls` on span end. Zero external dependency. One downside: if the process dies mid-run you lose that run's writes.

```python
from opentelemetry.sdk.trace import SpanProcessor
import psycopg
import json

class CostWriter(SpanProcessor):
    def __init__(self, dsn: str):
        self.pool = psycopg.connect(dsn, autocommit=True)

    def on_end(self, span):
        attrs = span.attributes or {}
        if not attrs.get('gen_ai.request.model'):
            return
        run_id = attrs.get('pydantic_ai.run_id')
        model = attrs.get('gen_ai.response.model') or attrs['gen_ai.request.model']
        details = attrs.get('gen_ai.usage.details', {}) or {}
        # Anthropic separates 5m vs 1h in cache_creation; handle both shapes
        cc5 = details.get('cache_creation_5m_tokens', 0)
        cc1 = details.get('cache_creation_1h_tokens', 0)
        if not cc5 and not cc1:
            cc5 = attrs.get('gen_ai.usage.details.cache_write_tokens', 0)
        with self.pool.cursor() as cur:
            cur.execute("""
              INSERT INTO llm_calls (run_id, model, input_tokens, output_tokens,
                 cache_creation_5m_tokens, cache_creation_1h_tokens,
                 cache_read_tokens, thinking_tokens, latency_ms, request_id, ts)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, to_timestamp(%s))
            """, (
              run_id, model,
              attrs.get('gen_ai.usage.input_tokens', 0),
              attrs.get('gen_ai.usage.output_tokens', 0),
              cc5, cc1,
              details.get('cache_read_tokens', 0),
              details.get('reasoning_tokens', 0),
              int((span.end_time - span.start_time) / 1e6),
              attrs.get('gen_ai.response.id'),
              span.end_time / 1e9,
            ))
```

**Shape B: Logfire SQL API pull.** Run a cron that pulls from Logfire's read-only SQL endpoint and upserts into Postgres. Durable, lags by one cron interval. Use this if reliability matters more than freshness.

For a solo dev, Shape A plus JSONL as crash-safety (already in place) is the right answer.

---

## 2.0 Caching: pragmatic rules

Prompt caching is the single biggest lever in the platform. It is cheap to enable and often cuts blended cost by 50 to 70% on orchestrator-pattern agents.

### 2.1 Five rules that matter

**Rule 1: cache hierarchy is tools > system > messages.** Anthropic walks the prompt top to bottom. A change at any level invalidates everything downstream. Put stable content first, volatile content last.

**Rule 2: minimum cacheable prefix is 1,024 tokens.** Below that, writes fail silently. Cache counters return zero. Check `gen_ai.usage.details.cache_write_tokens > 0` after deploying to confirm the cache is actually engaging.

**Rule 3: four `cache_control` breakpoints per request, not five.** It is easy to overshoot. `anthropic_cache_instructions` plus `anthropic_cache_tool_definitions` plus `anthropic_cache=True` plus one `CachePoint()` already equals four. Plan the budget.

**Rule 4: TTL decision is a back-of-envelope.** If the p95 gap between hits on the same prefix is under 4 minutes, use 5m. Above 4 minutes, use 1h.
- **5m write** costs 1.25x input. One read pays it back.
- **1h write** costs 2x input. Two reads pay it back.
- **Reads** cost 0.1x input. Cheap.

**Rule 5: break-even threshold.** A 5m cache is always worth it if you expect one more call within 5 minutes. A 1h cache is worth it if you expect two more calls within the hour. Orchestrators, critics, and tool-using workers almost always clear this bar.

### 2.2 What to cache, by agent role

| Agent role | Cache target | TTL | Reason |
|---|---|---|---|
| Orchestrator | Instructions + tool defs | 1h | Same prefix re-used every sub-task |
| Critic | Instructions + rubric | 1h | Stable evaluator over a full run |
| Summariser | Instructions | 5m | Tight loops, short-lived |
| Worker | Tool defs only | 5m | Instructions vary; tool defs don't |
| Classifier | Instructions | 5m | Short calls, high volume, tight loops |
| Code gen | Instructions + repo context | 1h | Long sessions, expensive model (Opus) |

### 2.3 PydanticAI wiring

```python
from pydantic_ai import Agent, CachePoint
from pydantic_ai.models.anthropic import AnthropicModelSettings

orchestrator = Agent(
    'anthropic:claude-sonnet-4-6',
    instructions=LONG_STABLE_POLICY,          # >1024 tokens ideally
    model_settings=AnthropicModelSettings(
        anthropic_cache_instructions='1h',     # breakpoint 1: system
        anthropic_cache_tool_definitions='1h', # breakpoint 2: tools
        anthropic_cache=True,                  # breakpoint 3: last message auto-cache
        max_tokens=1024,
    ),
)

async def ask(question: str, retrieved_docs: str):
    # Put stable docs first, CachePoint between docs and volatile question,
    # so the docs are cached even as questions change
    return await orchestrator.run([retrieved_docs, CachePoint(), question])
```

### 2.4 Three anti-patterns that silently break caching

**Anti-pattern 1: dynamic timestamps in system prompt.** "You are an assistant. The current time is 2026-04-19T14:32:17Z..." invalidates the cache on every call. Move timestamps to the user turn.

**Anti-pattern 2: tool set churn.** If the orchestrator shows Haiku-workers one tool set and Sonnet-workers another, each agent variant has its own cache key. Either standardise or split into clearly separate agents with their own toolsets.

**Anti-pattern 3: thinking mode flips.** Switching `thinking` on and off between calls on the same agent invalidates message-level cache hits (system and tool caches survive). Pick one mode per agent.

### 2.5 Verifying the cache is working

The three numbers that matter, pulled straight from the dashboard:

1. **Cache hit rate per agent** = `cache_read_tokens / (input_tokens + cache_read_tokens)`. Target > 60% in steady state.
2. **Cache write-to-read ratio per agent** = `cache_write_tokens / cache_read_tokens`. Target < 0.5 in steady state; if it's close to 1, you are writing as often as reading and getting no benefit.
3. **Savings estimate** = `cache_read_tokens * (full_input_price - read_price) / 1e6`. This is your caching dividend in USD per day.

---

## 3.0 The cost dashboard

### 3.1 What it answers

In rank order (matches your priority):

1. **Where are my tokens going by type?** Input, output, cache read, cache write (5m + 1h), thinking. This tells you whether the bill is input bloat, output sprawl, cache churn, or thinking abuse.
2. **Which runs/conversations cost the most?** Top 20 runs by cost with drill-down to per-call detail.
3. **Which agent role is the most expensive?** Often reveals that a "cheap" classifier is running 500x a day and costing more than the Opus code-gen agent.
4. **Which model costs the most?** Usually confirms the obvious but sometimes surprises: a Haiku agent stuck in a tool loop can out-cost Sonnet.

Plus cache effectiveness as a dedicated row (hit rate, write-to-read ratio, savings).

### 3.2 Panels

The Grafana JSON artifact includes eleven panels organised in four rows:

**Row 1 — Headline.** Total spend (24h, 7d, 30d), spend rate per hour (last 6h), p95 tokens per run.

**Row 2 — Cost by token type.** Stacked time series (input/output/thinking/cache write 5m/cache write 1h/cache read) plus a pie chart for the active time range.

**Row 3 — Cost by run, role, model.** Top 20 runs table with drill-down link, cost by agent role time series, cost by model time series.

**Row 4 — Cache effectiveness.** Hit rate per agent, write-to-read ratio, cache savings USD per day.

### 3.3 The drill-down path

The "Top 20 runs by cost" panel has a data link that filters every other panel to a single `run_id`. Click a row, the whole dashboard reloads scoped to that run. This is how you find the outlier that burned $4 in 90 seconds.

---

## 4.0 Implementation sequence

Ten steps, two weeks, reversible at each stage.

1. **Day 1.** Apply the Postgres migration. Seed `model_pricing`.
2. **Day 1.** Enable Logfire, set `include_content=False`.
3. **Day 2.** Deploy the span processor tap (Shape A above).
4. **Day 3.** Run Grafana via the compose file below, import the JSON artifact, confirm data renders.
5. **Day 4-7.** Baseline. No changes. Identify top 3 token sinks and top 3 cache hit-rate laggards.
6. **Day 8.** Enable caching on the orchestrator. Verify hit rate climbs above 60% within 24h.
7. **Day 9.** Enable caching on workers and critic. Verify.
8. **Day 10.** Set `max_tokens` per role. Most classifiers need <=64.
9. **Day 11.** Add `UsageLimits` per role as safety rails.
10. **Day 14.** Re-baseline. Expect 50 to 70% reduction versus day 1.

---

## 5.0 Grafana deployment

```yaml
# compose.yaml
services:
  grafana:
    image: grafana/grafana-oss:11.3.0
    platform: linux/arm64
    ports: ["3000:3000"]
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: changeme
      GF_INSTALL_PLUGINS: ""
    volumes:
      - grafana-data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
    deploy:
      resources:
        limits:
          memory: 512M
volumes:
  grafana-data:
```

Provision the datasource automatically:

```yaml
# grafana/provisioning/datasources/postgres.yaml
apiVersion: 1
datasources:
  - name: genos-postgres
    type: postgres
    access: proxy
    url: host.docker.internal:5432
    user: grafana_ro
    jsonData:
      database: genos
      sslmode: disable
      postgresVersion: 1600
    secureJsonData:
      password: "CHANGE_ME"
    readOnly: true
```

Create the read-only role in Postgres:

```sql
CREATE ROLE grafana_ro LOGIN PASSWORD 'CHANGE_ME';
GRANT CONNECT ON DATABASE genos TO grafana_ro;
GRANT USAGE ON SCHEMA public TO grafana_ro;
GRANT SELECT ON runs, llm_calls, model_pricing TO grafana_ro;
GRANT SELECT ON v_llm_calls_costed TO grafana_ro;
```

Import the companion `genos-cost-dashboard.json` via the Grafana UI (Dashboards > Import). The dashboard UID is `genos-cost-v1` so it survives re-imports.

---

## 6.0 Alerts worth configuring on day one

Three Grafana alert rules catch 90% of cost incidents. Set them after one week of baselining so thresholds are calibrated to your actual workload.

| Alert | Condition | Why |
|---|---|---|
| Hourly spend exceeds $5 | `sum_over_time(total_cost_usd[1h]) > 5` | Catches runaway loops within the hour |
| Single agent exceeds $2/hour | `max by (agent_role) (...) > 2` | Isolates which agent is the culprit |
| Orchestrator cache hit rate below 40% | 15-min rolling | Prefix churn; instructions or tools changing |

Pair with a circuit-breaker feature flag: when an alert fires, flip routing to drop the offending agent to Haiku until you investigate.

---

## 7.0 A note on the current model lineup

Pricing as of April 2026:

| Model | Input | Cache read | Cache write 1h | Output | Best for |
|---|---|---|---|---|---|
| Haiku 4.5 | $1.00 | $0.10 | $2.00 | $5.00 | Classifier, summariser, worker |
| Sonnet 4.6 | $3.00 | $0.30 | $6.00 | $15.00 | Orchestrator, critic, research |
| Opus 4.7 | $5.00 | $0.50 | $10.00 | $25.00 | Hard code generation only |

**Opus 4.7 has a new tokenizer that can inflate token counts by up to 35% on identical prose versus Opus 4.6.** Headline price parity is misleading. Re-baseline after migration.

Output is 5x input across all three tiers. This is why `max_tokens` discipline matters more than prompt length for most agent roles.
