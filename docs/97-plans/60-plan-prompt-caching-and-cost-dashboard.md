# Plan 60 — Prompt Caching & Cost Management Dashboard

**Version:** 1.0.0
**Date:** 2026-04-19
**Author:** Herman + Architecture Review
**Status:** Ready to implement
**Research basis:** docs/98-research/019-Claude token economics.md, docs/98-research/020-Cutting Anthropic spend on the BFA platform.md
**Expected impact:** 70-80% reduction in Anthropic API spend

---

## 0. Problem Statement

The platform currently sends **every request uncached** — system prompts (~39KB total), tool schemas, and mission context are re-sent in full on every LLM call. Output tokens cost **5x input tokens** but there are no per-agent output caps. There is a basic cost dashboard (`/admin/metrics`) but it shows only aggregate totals — no per-request breakdown, no cache hit rates, no input/output token split, no tool schema cost, and no trend visibility.

Combined, these gaps mean:
1. **~80% of API spend is wasted** on re-transmitting stable content
2. **No visibility** into which agents, tools, or prompts drive costs
3. **No levers** to optimise without risking functionality

---

## Phase 1 — Prompt Caching (the 70-80% win)

### 1.1 What PydanticAI supports natively

PydanticAI's `AnthropicModelSettings` already has cache control fields:

```python
from pydantic_ai.models.anthropic import AnthropicModelSettings

settings = AnthropicModelSettings(
    anthropic_cache_instructions='1h',      # cache system prompt for 1 hour
    anthropic_cache_tool_definitions='1h',   # cache tool schemas for 1 hour
    anthropic_cache=True,                    # auto-cache the last content block
    max_tokens=1024,
)
```

**Current state:** `build_model_settings()` in `model_builder.py` only handles `thinking_budget`. It does NOT set any cache fields. This is the single change that delivers 70-80% savings.

### 1.2 Implementation — update `build_model_settings()`

**File:** `modules/backend/agents/mission_control/helpers/model_builder.py`

**Current function** (line 17) only handles thinking. Add cache settings for ALL Anthropic agents.

```python
def build_model_settings(agent_config: AgentConfigSchema) -> ModelSettings | None:
    from pydantic_ai.settings import ModelSettings
    from pydantic_ai.models.anthropic import AnthropicModelSettings

    model_name = (
        agent_config.model.name
        if isinstance(agent_config.model, AgentModelSchema)
        else agent_config.model
    )
    provider = model_name.split(":")[0] if ":" in model_name else ""

    if provider != "anthropic":
        return None  # cache control is Anthropic-specific

    # ── Cache control (Plan 60) ──────────────────────────────
    # System prompts and tool definitions are stable across requests.
    # 1h TTL because agent loops may pause for human approval (>5min).
    # Auto-cache last block catches retrieved context (MCD, code map).
    # This alone cuts 70-80% of input token cost.
    cache_kwargs = {
        "anthropic_cache_instructions": "1h",
        "anthropic_cache_tool_definitions": "1h",
        "anthropic_cache": True,
    }

    # ── Output token cap by agent role ───────────────────────
    # Output is 5x input cost. Cap per role to prevent waste.
    max_tokens = _get_max_tokens_for_role(agent_config)

    # ── Thinking configuration ───────────────────────────────
    thinking_config = None
    if agent_config.thinking_budget:
        budget = agent_config.thinking_budget.get("max_thinking_tokens", 10000)
        bare_name = model_name.split(":")[-1] if ":" in model_name else model_name
        _adaptive_models = ("claude-opus-4", "claude-sonnet-4", "opus-4", "sonnet-4")
        _use_adaptive = any(m in model_name for m in _adaptive_models)

        if _use_adaptive:
            thinking_config = {"type": "adaptive"}
        else:
            if max_tokens <= budget:
                max_tokens = budget + 8192
            thinking_config = {"type": "enabled", "budget_tokens": budget}

    settings_kwargs = {
        **cache_kwargs,
        "max_tokens": max_tokens,
    }
    if thinking_config:
        settings_kwargs["anthropic_thinking"] = thinking_config

    return AnthropicModelSettings(**settings_kwargs)


def _get_max_tokens_for_role(agent_config: AgentConfigSchema) -> int:
    """Return appropriate max_tokens based on agent role.

    Output tokens cost 5x input. Capping per role prevents waste
    without losing functionality. Values from research paper §2.7.
    """
    name = agent_config.agent_name

    # Utility agents — short output
    if any(k in name for k in ("summarization", "synthesis", "health", "knowledge")):
        return 800

    # Verification, supervisor — judgement, not prose
    if any(k in name for k in ("verification", "supervisor")):
        return 256

    # Planning — structured output (TaskPlan JSON)
    if "planning" in name:
        return 4096

    # Director — conversational but bounded
    if "director" in name:
        return 2048

    # Code generation — needs room
    if any(k in name for k in ("quality", "architecture")):
        return 4096

    # Default
    return 2048
```

### 1.3 Wire model_settings into the chat path

**File:** `modules/backend/agents/mission_control/mission_control.py`

**Current state (line 374):** `agent.run()` already passes `model_settings=model_settings` where `model_settings` comes from `build_model_settings(agent_config)` (line 261). **This already works** — once we add cache fields to `build_model_settings()`, they flow through automatically.

**Verify:** Line 261: `model_settings = build_model_settings(agent_config)` — confirmed.

### 1.4 Wire model_settings into the dispatch path

**File:** `modules/backend/agents/mission_control/helpers/agent_executor.py`

**Current state:** The dispatch path uses `agent.run()` with `model_settings` built inside `execute_agent()`. Check if `build_model_settings` is called there.

Search for `build_model_settings` in `agent_executor.py`. If not present, add it:

```python
# Inside execute_agent(), before agent.run():
from modules.backend.agents.mission_control.helpers.model_builder import build_model_settings
model_settings = build_model_settings(agent_config)

# Then pass to agent.run():
result = await agent.run(
    instructions,
    model_settings=model_settings,
    ...
)
```

### 1.5 Add CachePoint for dynamic context

**File:** `modules/backend/agents/mission_control/helpers/prompt_builder.py`

When assembling instructions, add a `CachePoint()` after the stable context (system prompt, MCD) and before the variable user message. This ensures the stable prefix is cached even when the user message changes.

```python
from pydantic_ai import CachePoint

def assemble_instructions_with_cache(
    category: str,
    name: str,
    mission_context: str | None = None,
) -> list:
    """Assemble instructions as a list with CachePoint for caching.

    Layout: [system_prompt, mission_context, CachePoint(), user_message]
    Everything before CachePoint is cached at 1h TTL.
    """
    parts = []
    # Stable prefix — cached
    system_prompt = assemble_instructions(category, name)
    parts.append(system_prompt)

    if mission_context:
        parts.append(mission_context)

    # Cache boundary — everything above is cached
    parts.append(CachePoint())

    return parts
```

**Usage in handle():**
```python
# Instead of: result = await agent.run(message, ...)
# Use: result = await agent.run([*cached_prefix, message], ...)
```

### 1.6 Update cost calculation for cache tokens

**File:** `modules/backend/agents/mission_control/cost.py`

Current `compute_cost_usd()` only handles `input_tokens` and `output_tokens`. Add cache token pricing:

```python
def compute_cost_usd(
    input_tokens: int,
    output_tokens: int,
    model: str | None = None,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    thinking_tokens: int = 0,
) -> float:
    """Compute cost including cache and thinking tokens.

    Pricing (per MTok):
      Input:       base rate
      Output:      5x base rate
      Cache read:  0.1x base rate (90% discount!)
      Cache write: 1.25x base rate (5min) or 2x (1h)
      Thinking:    same as output
    """
    config = _load_mission_control_config()
    rates = config.model_pricing.get(model or "", config.model_pricing.get("default"))

    input_cost = (input_tokens / 1_000_000) * rates.input
    output_cost = ((output_tokens + thinking_tokens) / 1_000_000) * rates.output
    cache_read_cost = (cache_read_tokens / 1_000_000) * rates.input * 0.1
    cache_write_cost = (cache_write_tokens / 1_000_000) * rates.input * 2.0  # 1h TTL

    return round(input_cost + output_cost + cache_read_cost + cache_write_cost, 6)
```

Update callers to pass cache tokens from PydanticAI's `usage` object:
```python
usage = result.usage()
cost = compute_cost_usd(
    usage.input_tokens,
    usage.output_tokens,
    model=model_str,
    cache_read_tokens=usage.cache_read_tokens,
    cache_write_tokens=usage.cache_write_tokens,
)
```

### 1.7 Update model pricing config

**File:** `config/agents/mission_control.yaml`

Update pricing to include cache rates and fix Opus pricing:

```yaml
model_pricing:
  "anthropic:claude-haiku-4-5-20251001":
    input: 1.00
    output: 5.00
  "anthropic:claude-sonnet-4-6":
    input: 3.00
    output: 15.00
  "anthropic:claude-opus-4-6":
    input: 15.00
    output: 75.00
  "anthropic:claude-opus-4-7":
    input: 5.00
    output: 25.00
  default:
    input: 3.00
    output: 15.00
```

### 1.8 Verification

After implementing:

1. **Cache hit rate query** — run a few agent calls, then check:
```python
usage = result.usage()
total_input = usage.input_tokens + usage.cache_read_tokens
cache_rate = usage.cache_read_tokens / total_input if total_input else 0
print(f"Cache hit rate: {cache_rate:.1%}")
# Target: >60% on second+ calls to the same agent
```

2. **Cost comparison** — compare cost before and after caching on identical prompts

3. **No quality regression** — agent outputs should be identical (caching doesn't affect output quality)

### 1.9 Files changed

| # | File | Action | Lines |
|---|------|--------|-------|
| 1 | `modules/backend/agents/mission_control/helpers/model_builder.py` | Rewrite `build_model_settings()` | ~50 |
| 2 | `modules/backend/agents/mission_control/cost.py` | Add cache/thinking token params | ~15 |
| 3 | `modules/backend/agents/mission_control/helpers/agent_executor.py` | Pass cache tokens to cost calc | ~5 |
| 4 | `config/agents/mission_control.yaml` | Update pricing | ~5 |

**Estimated effort: 2-3 hours.**

---

## Phase 2 — Cost Management Dashboard

### 2.1 Problem

The current `/admin/metrics` page shows:
- Total cost (one number)
- Cost by agent (table: agent_name, run_count, cost_usd)
- Agent utilisation (table: agent_name, run_count, avg_duration, total_cost)

What's missing:
- **No input vs output token split** (output costs 5x — critical for optimisation)
- **No cache hit rate** (the key metric for validating Phase 1)
- **No per-request granularity** (can't see individual expensive calls)
- **No time-series trends** (can't see if costs are going up or down)
- **No tool schema cost** (tools consume tokens on every uncached request)
- **No model breakdown** (Haiku vs Sonnet vs Opus distribution)
- **No budget alerts** (no warning when approaching limits)

### 2.2 New database table: `llm_calls`

Per-request cost tracking. One row per LLM API call (not per agent run — a run may make multiple calls due to tool loops).

**File:** `modules/backend/models/llm_call.py` (new)

```python
"""Per-request LLM call tracking for cost attribution.

Each row represents a single API call to an LLM provider. Agent runs
that involve tool loops produce multiple rows. This is the source of
truth for token economics — all dashboard queries read from here.
"""

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class LlmCall(UUIDMixin, TimestampMixin, Base):
    """A single LLM API call with full token breakdown."""

    __tablename__ = "llm_calls"

    # Context
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    mission_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    execution_record_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    agent_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    agent_role: Mapped[str] = mapped_column(String(50), nullable=False)

    # Model
    model: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)

    # Token breakdown (the full picture)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
        comment="Uncached input tokens")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
        comment="Tokens served from cache (90% discount)")
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
        comment="Tokens written to cache (1.25x or 2x cost)")
    thinking_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
        comment="Extended thinking tokens (billed as output)")

    # Cost
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Performance
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True,
        comment="Anthropic request ID for debugging")

    # Tool context
    tool_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
        comment="Number of tools in this request's schema")
    tool_schema_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
        comment="Estimated tokens consumed by tool definitions")
```

**Migration:** Create `llm_calls` table with indexes on `(agent_name)`, `(model)`, `(mission_id)`, `(created_at)`.

### 2.3 Record LLM calls from agent execution

**File:** `modules/backend/agents/mission_control/helpers/agent_executor.py`

After each `agent.run()` or `stream` completion, persist an `LlmCall` row:

```python
# After getting usage from result/stream:
usage = result.usage()  # or stream.usage()

from modules.backend.models.llm_call import LlmCall
from modules.backend.core.database import get_async_session

llm_call = LlmCall(
    session_id=session_id,
    mission_id=mission_id,
    agent_name=agent_name,
    agent_role=agent_config.agent_type,
    model=model_str,
    provider=model_str.split(":")[0] if ":" in model_str else "unknown",
    input_tokens=usage.input_tokens or 0,
    output_tokens=usage.output_tokens or 0,
    cache_read_tokens=usage.cache_read_tokens or 0,
    cache_write_tokens=usage.cache_write_tokens or 0,
    thinking_tokens=usage.details.get("thinking_tokens", 0) if usage.details else 0,
    cost_usd=cost_usd,
    latency_ms=int(elapsed_ms),
    tool_count=len(agent_config.tools),
    tool_schema_tokens=_estimate_tool_schema_tokens(agent_config.tools),
)
# Persist via the active DB session or a fire-and-forget task
```

### 2.4 Backend API endpoints

**File:** `modules/backend/api/v1/endpoints/admin.py` (extend)

Add these endpoints:

```python
# GET /admin/metrics/token-economics
# Returns: per-agent token breakdown (input, output, cache_read, cache_write, thinking)
# Timeframe: last 24h, 7d, 30d (query param)

# GET /admin/metrics/cache-performance
# Returns: per-agent cache hit rate, cache savings in USD
# Formula: cache_hit_rate = cache_read_tokens / (cache_read_tokens + input_tokens)

# GET /admin/metrics/cost-timeline
# Returns: hourly cost aggregation for time-series chart
# Grouped by: agent_name or model

# GET /admin/metrics/expensive-calls
# Returns: top 20 most expensive individual LLM calls
# Includes: agent, model, tokens, cost, timestamp

# GET /admin/metrics/model-distribution
# Returns: percentage of calls and cost per model (Haiku vs Sonnet vs Opus)

# GET /admin/metrics/output-efficiency
# Returns: per-agent output_tokens / input_tokens ratio
# High ratio = agent producing too much output (5x cost multiplier)
```

### 2.5 Backend service

**File:** `modules/backend/services/token_economics.py` (new)

```python
"""Token economics service — queries for the cost management dashboard.

All queries read from the llm_calls table. Time-bounded by default
to prevent full-table scans on large deployments.
"""

class TokenEconomicsService(BaseService):

    async def get_token_breakdown(
        self, *, timeframe: str = "7d", group_by: str = "agent",
    ) -> list[dict]:
        """Per-agent/model token breakdown with cost attribution."""
        ...

    async def get_cache_performance(
        self, *, timeframe: str = "7d",
    ) -> list[dict]:
        """Per-agent cache hit rate and savings.

        Returns:
            agent_name, total_input, cache_read, cache_write,
            cache_hit_rate, estimated_savings_usd
        """
        ...

    async def get_cost_timeline(
        self, *, timeframe: str = "7d", interval: str = "1h",
        group_by: str = "agent",
    ) -> list[dict]:
        """Hourly/daily cost for time-series chart."""
        ...

    async def get_expensive_calls(
        self, *, limit: int = 20, timeframe: str = "7d",
    ) -> list[dict]:
        """Top N most expensive individual LLM calls."""
        ...

    async def get_model_distribution(
        self, *, timeframe: str = "7d",
    ) -> dict:
        """Call count and cost percentage per model."""
        ...

    async def get_output_efficiency(
        self, *, timeframe: str = "7d",
    ) -> list[dict]:
        """Per-agent output/input ratio — high = expensive."""
        ...
```

### 2.6 Frontend dashboard

**File:** `modules/frontend/src/pages/admin/token-economics.tsx` (new)

A dedicated cost management page with these panels:

```
┌────────────────────────────────────────────────────────────────┐
│ Token Economics Dashboard                    [24h] [7d] [30d] │
├────────────────┬───────────────┬───────────────┬──────────────┤
│ Total Cost     │ Cache Hit Rate│ Avg Cost/Run  │ Output Ratio │
│ $12.45         │ 72%           │ $0.08         │ 3.2x         │
├────────────────┴───────────────┴───────────────┴──────────────┤
│                                                                │
│  📊 Cost Timeline (area chart, stacked by agent)               │
│  ████████████████████████████████████████████                  │
│  ██████████████████████████████                                │
│  ████████████████████                                          │
│                                                                │
├───────────────────────────────┬────────────────────────────────┤
│ Token Breakdown by Agent      │ Model Distribution              │
│ ┌─────────────────────────┐  │ ┌────────────────────────────┐ │
│ │ Agent    In   Out Cache │  │ │ Haiku 45%  ████████████    │ │
│ │ director 12K  3K  89%  │  │ │ Sonnet 48% █████████████   │ │
│ │ planning 8K   2K  74%  │  │ │ Opus   7%  ██             │ │
│ │ quality  5K   4K  62%  │  │ └────────────────────────────┘ │
│ └─────────────────────────┘  │                                │
├───────────────────────────────┼────────────────────────────────┤
│ Cache Performance             │ Output Efficiency               │
│ ┌─────────────────────────┐  │ ┌────────────────────────────┐ │
│ │ Agent   Hit%  Savings   │  │ │ Agent      Out/In  Flag    │ │
│ │ director 89%  $4.20     │  │ │ quality    4.2x    ⚠ HIGH  │ │
│ │ planning 74%  $2.10     │  │ │ director   1.8x    ✓       │ │
│ │ quality  62%  $1.50     │  │ │ planning   2.1x    ✓       │ │
│ └─────────────────────────┘  │ └────────────────────────────┘ │
├───────────────────────────────┴────────────────────────────────┤
│ Most Expensive Calls                                           │
│ ┌──────────────────────────────────────────────────────────┐  │
│ │ Time       Agent      Model    In     Out    Cost       │  │
│ │ 14:32:01   director   Sonnet   45K    8K     $0.42     │  │
│ │ 14:28:15   planning   Sonnet   38K    4K     $0.18     │  │
│ │ 14:25:03   quality    Sonnet   22K    12K    $0.24     │  │
│ └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

### 2.7 Frontend types

**File:** `modules/frontend/src/types/admin.ts` (extend)

```typescript
export interface TokenBreakdown {
  agent_name: string
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  cache_write_tokens: number
  thinking_tokens: number
  total_cost_usd: number
  call_count: number
}

export interface CachePerformance {
  agent_name: string
  total_input_tokens: number
  cache_read_tokens: number
  cache_write_tokens: number
  cache_hit_rate: number
  estimated_savings_usd: number
}

export interface CostTimelinePoint {
  timestamp: string
  group: string   // agent_name or model
  cost_usd: number
}

export interface ExpensiveCall {
  id: string
  timestamp: string
  agent_name: string
  model: string
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  cost_usd: number
  latency_ms: number
}

export interface ModelDistribution {
  model: string
  call_count: number
  call_pct: number
  cost_usd: number
  cost_pct: number
}

export interface OutputEfficiency {
  agent_name: string
  avg_input_tokens: number
  avg_output_tokens: number
  output_input_ratio: number
  flag: 'ok' | 'high' | 'critical'  // >3x = high, >5x = critical
}
```

### 2.8 Frontend hooks

**File:** `modules/frontend/src/hooks/use-admin.ts` (extend)

```typescript
export function useTokenBreakdown(timeframe = '7d') {
  return useQuery(['admin', 'token-breakdown', timeframe], () =>
    api.get(`/admin/metrics/token-economics?timeframe=${timeframe}`)
  )
}

export function useCachePerformance(timeframe = '7d') { ... }
export function useCostTimeline(timeframe = '7d', groupBy = 'agent') { ... }
export function useExpensiveCalls(timeframe = '7d') { ... }
export function useModelDistribution(timeframe = '7d') { ... }
export function useOutputEfficiency(timeframe = '7d') { ... }
```

### 2.9 Navigation

Add "Token Economics" to the admin sidebar/nav, alongside the existing "Metrics" page.

---

## Phase 3 — Alerting & Budget Controls

### 3.1 Per-agent budget limits

Add `budget_usd_per_hour` to `AgentConfigSchema` and the DB catalog. The dispatch loop checks cumulative hourly cost from `llm_calls` before executing.

### 3.2 Alert thresholds

Three rules (implemented as periodic checks):
1. **Hourly spend > $5** — alert admin
2. **Any single agent > $2/hour** — likely runaway loop
3. **Cache hit rate < 40%** — prefix instability, needs investigation

### 3.3 Emergency downgrade

Feature flag `EMERGENCY_MODEL_DOWNGRADE=true` forces all agents to Haiku. Activated manually or by the alerting system.

---

## Implementation Order

```
Phase 1 (Prompt Caching)         ← Do first — immediate 70-80% savings
  ├── 1.2 build_model_settings   ← Core change (30 min)
  ├── 1.4 Wire dispatch path     ← Ensure settings flow (15 min)
  ├── 1.6 Update cost.py         ← Cache token pricing (15 min)
  ├── 1.7 Update pricing config  ← Fix Opus 4.7 rates (5 min)
  └── 1.8 Verify cache hits      ← Must see >60% on second call

Phase 2 (Cost Dashboard)         ← Visibility for continuous optimisation
  ├── 2.2 LlmCall model + migration  ← Schema (30 min)
  ├── 2.3 Record calls in executor   ← Instrumentation (1 hour)
  ├── 2.4-2.5 API + service          ← Backend queries (2 hours)
  ├── 2.6-2.8 Frontend dashboard     ← UI (3 hours)
  └── 2.9 Navigation                 ← Wire into admin (15 min)

Phase 3 (Alerting)               ← Safety net
  ├── 3.1 Per-agent budgets      ← Config change (30 min)
  ├── 3.2 Alert thresholds       ← Periodic check (1 hour)
  └── 3.3 Emergency downgrade    ← Feature flag (30 min)
```

**Total estimated effort:** Phase 1: ~2 hours, Phase 2: ~7 hours, Phase 3: ~2 hours.

---

## Exit Criteria

### Phase 1
1. `anthropic_cache_instructions='1h'` set on all Anthropic agents
2. `anthropic_cache_tool_definitions='1h'` set on all Anthropic agents
3. Cache hit rate >60% on second+ calls to the same agent
4. `max_tokens` capped per agent role
5. Cost calculation includes cache_read and cache_write tokens

### Phase 2
1. `llm_calls` table records every LLM API call with full token breakdown
2. Dashboard shows: token breakdown, cache performance, cost timeline, expensive calls, model distribution, output efficiency
3. All metrics filterable by timeframe (24h, 7d, 30d)
4. Cost timeline renders as a stacked area chart

### Phase 3
1. Per-agent hourly budget enforced
2. Three alert rules firing
3. Emergency downgrade switch works
