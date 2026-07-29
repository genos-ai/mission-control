# Plan 60 — Prompt Caching & Cost Management Dashboard

**Version:** 1.3.0
**Date:** 2026-04-19
**Author:** Herman + Architecture Review + Codebase Verification
**Status:** Ready to implement
**Research basis:** docs/98-research/019, 020, 021 (Claude token economics, cost cutting, cost management)
**Expected impact:** 70-80% reduction in Anthropic API spend

### v1.3 changelog (codebase verification)

1. **Fixed `build_model_settings()` rewrite** — removed early return on no `thinking_budget`; cache settings now flow for ALL Anthropic agents regardless of thinking config
2. **Fixed dispatch path gap** — `agent_executor.py` uses `run_stream()` (not `run()`) and does NOT currently call `build_model_settings()` at all; added explicit wiring + import
3. **Fixed files-changed table** — 11 files, not 4. Added: `config_schema.py` (core + agents), `config.py`, `agent_catalog.py`, `cost.yaml`, Alembic migration
4. **Fixed strict schema handling** — `_StrictBase` uses `extra='forbid'`; new fields (`cache_ttl`, cache pricing rates) must be added to schemas before YAML changes
5. **Removed role-based `max_tokens`** — `AgentModelSchema.max_tokens` (default 4096) is already the correct per-agent source of truth; `_resolve_max_tokens()` removed
6. **No swallowed exceptions** — `record_llm_call()` raises on failure; callers catch + log at WARNING with `exc_info=True`. `_get_default_cache_ttl()` raises on invalid config (no silent fallback)
7. **Fixed `effective_to` sentinel** — `datetime(9999, 12, 31)` instead of string `"infinity"` (portable across PostgreSQL versions)
8. **Added `created_at` index** to `llm_calls` — all timeline queries filter by time range
9. **Deferred CachePoint to Phase 1.5** — requires `str` → `list` return type change in `assemble_instructions()` + caller updates in both execution paths
10. **Fixed `estimate_cost()`** — output estimate changed from 100% to 30% of input (more realistic)
11. **Added `cost_recorder.py` session management** — dispatch path has no `db_session` in scope; recorder uses `get_async_session()` internally

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

### 1.2 Implementation — rewrite `build_model_settings()`

**File:** `modules/backend/agents/mission_control/helpers/model_builder.py`

**Current function** (line 15) returns `None` when `thinking_budget` is absent — meaning
agents without thinking get **no** `model_settings` at all. The rewrite must remove that
early return so cache settings flow for ALL Anthropic agents, with or without thinking.

**Breaking change:** The current function returns `None` for non-thinking agents. After
this change it returns `AnthropicModelSettings` for all Anthropic agents. Callers already
handle both `None` and `ModelSettings`, so this is safe — but verify in §1.3 and §1.4.

```python
def build_model_settings(
    agent_config: AgentConfigSchema,
) -> "ModelSettings | None":
    """Build provider-specific model settings from agent config.

    Returns AnthropicModelSettings for ALL Anthropic agents (cache + thinking).
    Returns None for non-Anthropic providers (cache control is Anthropic-specific).
    """
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
    # Per-agent cache_ttl from YAML, then cost.yaml default, then "1h".
    cache_ttl = agent_config.cache_ttl or _get_default_cache_ttl()
    cache_kwargs = {
        "anthropic_cache_instructions": cache_ttl,
        "anthropic_cache_tool_definitions": cache_ttl,
        "anthropic_cache": True,
    }

    # ── Output token cap ─────────────────────────────────────
    # AgentModelSchema.max_tokens (pinned per-agent, default 4096).
    max_tokens = (
        agent_config.model.max_tokens
        if isinstance(agent_config.model, AgentModelSchema)
        else 4096
    )

    # ── Thinking configuration ───────────────────────────────
    thinking_config = None
    if agent_config.thinking_budget:
        budget = agent_config.thinking_budget.get("max_thinking_tokens", 10000)
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


def _get_default_cache_ttl() -> str:
    """Read default_cache_ttl from cost.yaml config.

    Raises if cost.yaml exists but has invalid schema — we do NOT
    silently fall back, because a broken config must be fixed.
    """
    from modules.backend.core.config import get_app_config
    return get_app_config().cost.default_cache_ttl
```

**Removed `_resolve_max_tokens()`** — the original plan added a role-based
`max_tokens` resolution from `cost.yaml`. This is unnecessary: `AgentModelSchema`
already has `max_tokens` (default 4096) pinned per-agent. The existing field is
the correct source of truth — adding a second resolution path creates ambiguity
about which value wins. If we need role-based defaults, add them as a future plan.

#### New config file: `config/settings/cost.yaml`

Cost-related configuration. Loaded by `AppConfig` via `_load_validated_optional`
(returns defaults if file is missing — but validation errors are **not** swallowed).

```yaml
# Cost management configuration.

# Default cache TTL for Anthropic agents.
# "5m" for tight loops, "1h" for agents that may pause for human approval.
default_cache_ttl: "1h"

# Alert thresholds (Phase 3)
alerts:
  hourly_spend_limit_usd: 5.00
  per_agent_hourly_limit_usd: 2.00
  min_cache_hit_rate: 0.40

# Emergency downgrade (Phase 3)
emergency_downgrade_model: "anthropic:claude-haiku-4-5-20251001"

# Output efficiency flags (Phase 2 dashboard)
output_efficiency:
  high_threshold: 3.0    # output/input ratio > 3x = warning
  critical_threshold: 5.0  # > 5x = critical
```

#### New config schema additions

**File:** `modules/backend/core/config_schema.py`

Add alongside existing schemas. Uses `_StrictBase` — unknown YAML keys
will fail validation at startup (not silently ignored).

```python
class CostAlertsSchema(_StrictBase):
    hourly_spend_limit_usd: float = 5.0
    per_agent_hourly_limit_usd: float = 2.0
    min_cache_hit_rate: float = 0.40

class OutputEfficiencySchema(_StrictBase):
    high_threshold: float = 3.0
    critical_threshold: float = 5.0

class CostSchema(_StrictBase):
    """Cost management configuration (cost.yaml)."""
    default_cache_ttl: str = "1h"
    alerts: CostAlertsSchema = Field(default_factory=CostAlertsSchema)
    emergency_downgrade_model: str = "anthropic:claude-haiku-4-5-20251001"
    output_efficiency: OutputEfficiencySchema = Field(default_factory=OutputEfficiencySchema)
```

**File:** `modules/backend/core/config.py`

Add to `AppConfig.__init__()` alongside the other optional configs:
```python
self._cost = _load_validated_optional(CostSchema, "cost.yaml")
```

Add property (same pattern as `sessions`, `executions`, etc.):
```python
@property
def cost(self) -> CostSchema:
    return self._cost
```

**Note:** `_load_validated_optional` already exists and is used for 9 other
configs (`events`, `sessions`, `executions`, etc.). If the file is missing,
it returns `CostSchema()` with defaults. If the file exists but has invalid
content, it raises `ValueError` — this is the correct behavior (no swallowed errors).

#### New agent config field: `cache_ttl`

**File:** `modules/backend/agents/config_schema.py`

Add to `AgentConfigSchema` (after `effort`, line 162). Since `AgentConfigSchema`
uses `_StrictBase` (`extra='forbid'`), the field **must** be added to the schema
before any agent YAML includes `cache_ttl` — otherwise startup validation fails.

```python
# Cache TTL for Anthropic prompt caching (Plan 60).
# "5m" for tight loops, "1h" for agents with human-approval pauses.
# None = use default from config/settings/cost.yaml.
cache_ttl: str | None = None
```

**File:** `modules/backend/models/agent_catalog.py`

Add column + **Alembic migration** (the plan must include a migration step):
```python
cache_ttl: Mapped[str | None] = mapped_column(
    String(10), nullable=True,
    comment="Cache TTL: 5m or 1h (None = use default from cost.yaml)",
)
```

**Migration:** `alembic revision --autogenerate -m "add cache_ttl to agent_catalog"`

### 1.3 Wire model_settings into the chat path

**File:** `modules/backend/agents/mission_control/mission_control.py`

**Current state (line 374):** `agent.run()` already passes `model_settings=model_settings`
where `model_settings` comes from `build_model_settings(agent_config)` (line 263).

**Behavioral change:** Previously, non-thinking agents got `model_settings=None`.
After §1.2, all Anthropic agents get `AnthropicModelSettings` with cache fields.
PydanticAI handles `model_settings=None` vs populated settings identically for
non-configured fields, so this is safe. **No code changes needed in this file for
cache to work** — the rewrite in §1.2 is sufficient.

**Verified:** Line 263 calls `build_model_settings(agent_config)`, line 374 passes
it to `agent.run()`. Cache settings flow automatically.

### 1.4 Wire model_settings into the dispatch path

**File:** `modules/backend/agents/mission_control/helpers/agent_executor.py`

**Current state:** The dispatch path uses `agent.run_stream()` (NOT `agent.run()`)
at line 187. It does **not** call `build_model_settings()` and does **not** pass
`model_settings` at all. This means dispatch-path agents currently get:
- No cache control
- No thinking configuration (even if `thinking_budget` is set in their YAML)

This is a **real gap** — not a 5-line fix. The change:

```python
# Line 32 — add import (build_model_settings is not currently imported):
from modules.backend.agents.mission_control.helpers.model_builder import (
    _build_model, _get_model_name, build_model_settings,
)

# Line 64-66 — after building model, add model_settings:
model = _build_model(agent_config.model)
agent = module.create_agent(model)
model_settings = build_model_settings(agent_config)  # NEW

# Line 187-188 — pass model_settings to run_stream():
async with agent.run_stream(
    user_message, deps=deps, usage_limits=usage_limits,
    model_settings=model_settings,  # NEW — enables cache + thinking
) as stream:
```

**Also wire into `_call_planning_agent()`** (line 351):
```python
# Line 323-325 — add model_settings for planning agent:
planning_cfg = registry.get("system.planning.agent")
model = _build_model(planning_cfg.model)
model_settings = build_model_settings(planning_cfg)  # NEW

# Line 351 — pass to run_stream():
async with agent.run_stream(
    planning_prompt, deps=deps, model_settings=model_settings,
) as stream:
```

**Impact:** This also fixes the existing bug where dispatch-path agents
don't get thinking configuration. The `thinking_tokens: 0` hardcoded at
line 252 should be updated to read from `usage.details` (see §1.6).

### 1.5 Add CachePoint for dynamic context (deferred — Phase 1.5)

**File:** `modules/backend/agents/mission_control/helpers/prompt_builder.py`

**Current state:** `assemble_instructions()` returns a single `str`. Both callers
(`mission_control.py` line 374 and `agent_executor.py` line 187) pass a string
to `agent.run()` / `agent.run_stream()`.

Adding `CachePoint()` requires changing the return type from `str` to `list` and
updating both callers to pass `[*cached_prefix, user_message]` instead of a flat
string. This is a meaningful refactor across the two execution paths.

**Recommendation:** Defer to Phase 1.5. The `anthropic_cache_instructions` and
`anthropic_cache_tool_definitions` settings from §1.2 already cache the system
prompt and tool schemas (the two largest stable prefixes). `CachePoint()` adds
an additional cache boundary for mission context — valuable but not required
for the initial 70-80% savings.

**When implementing (Phase 1.5):**
```python
from pydantic_ai import CachePoint

def assemble_instructions_with_cache(
    category: str,
    name: str,
    mission_context: str | None = None,
) -> list:
    """Assemble instructions as a list with CachePoint for caching.

    Layout: [system_prompt, mission_context, CachePoint(), user_message]
    Everything before CachePoint is cached at the TTL from model_settings.
    """
    parts = []
    system_prompt = assemble_instructions(category, name)
    parts.append(system_prompt)

    if mission_context:
        parts.append(mission_context)

    # WARNING: Anthropic allows max 4 cache_control breakpoints per request.
    # anthropic_cache_instructions (1) + anthropic_cache_tool_definitions (2)
    # + anthropic_cache=True (3) + this CachePoint (4) = exactly 4.
    # Do NOT add a second CachePoint — it will be silently dropped.
    parts.append(CachePoint())

    return parts
```

**Caller change required (both paths):**
```python
# mission_control.py — change agent.run(message, ...) to:
cached_prefix = assemble_instructions_with_cache(category, name, mission_context)
result = await agent.run([*cached_prefix, message], ...)

# agent_executor.py — change agent.run_stream(user_message, ...) to:
cached_prefix = assemble_instructions_with_cache(category, name, mission_context)
async with agent.run_stream([*cached_prefix, user_message], ...) as stream:
```

### 1.6 Update cost calculation for cache tokens

**File:** `modules/backend/agents/mission_control/cost.py`

**Current state:** `compute_cost_usd()` (line 13) takes only `input_tokens`,
`output_tokens`, `model`. Uses `ModelPricingRateSchema` which only has
`input` and `output` fields.

**Both the function AND the schema need updating.**

**Step 1 — Update `ModelPricingRateSchema`:**

**File:** `modules/backend/agents/config_schema.py` (line 267)

```python
class ModelPricingRateSchema(_StrictBase):
    """Cost per million tokens for a specific model."""

    input: float
    output: float
    cache_read: float = 0.0
    cache_write_5m: float = 0.0
    cache_write_1h: float = 0.0
```

Cache fields default to `0.0` so existing `mission_control.yaml` entries
(which only have `input`/`output`) continue to validate. New entries add
cache rates explicitly. `_StrictBase` ensures typos in field names are
caught at startup.

**Step 2 — Update `compute_cost_usd()`:**

```python
def compute_cost_usd(
    input_tokens: int,
    output_tokens: int,
    model: str | None = None,
    cache_read_tokens: int = 0,
    cache_write_5m_tokens: int = 0,
    cache_write_1h_tokens: int = 0,
    thinking_tokens: int = 0,
) -> float:
    """Compute cost including cache and thinking tokens.

    All rates read from config/agents/mission_control.yaml model_pricing.
    5m and 1h cache writes have different pricing (1.25x vs 2x input).
    """
    config = _load_mission_control_config()
    default_rates = config.model_pricing.get("default")
    rates = config.model_pricing.get(model or "", default_rates)
    if rates is None:
        rates = default_rates
    if rates is None:
        logger.warning("No pricing config found", extra={"model": model})
        return 0.0

    input_cost = (input_tokens / 1_000_000) * rates.input
    output_cost = ((output_tokens + thinking_tokens) / 1_000_000) * rates.output
    cache_read_cost = (cache_read_tokens / 1_000_000) * rates.cache_read
    cache_write_5m_cost = (cache_write_5m_tokens / 1_000_000) * rates.cache_write_5m
    cache_write_1h_cost = (cache_write_1h_tokens / 1_000_000) * rates.cache_write_1h

    return round(
        input_cost + output_cost + cache_read_cost
        + cache_write_5m_cost + cache_write_1h_cost, 6,
    )
```

**Step 3 — Update callers** (both paths):

```python
# mission_control.py (line 410-415) and agent_executor.py (line 243-246):
usage = result.usage()  # or stream.usage()
cost_usd = compute_cost_usd(
    usage.input_tokens or 0,
    usage.output_tokens or 0,
    model_str,
    cache_read_tokens=getattr(usage, "cache_read_tokens", 0) or 0,
    cache_write_1h_tokens=getattr(usage, "cache_write_tokens", 0) or 0,
    thinking_tokens=_extract_thinking_tokens(usage),
)
```

**Note on `getattr` guards:** PydanticAI's `Usage` object may not have
`cache_read_tokens` / `cache_write_tokens` on older versions. Using `getattr`
with a default is defensive but intentional — if the fields are missing, we
get 0 (correct: no cache = no cache cost). This is NOT a swallowed error —
it's forward-compatible field access.

**Step 4 — Fix `estimate_cost()`:**

Current implementation assumes `output ≈ input` which overestimates (output is
typically 10-30% of input). Update to use a configurable ratio:

```python
def estimate_cost(
    estimated_input_tokens: int,
    model: str | None = None,
) -> float:
    """Estimate cost before execution. Conservative: assumes output = 30% of input."""
    estimated_output = int(estimated_input_tokens * 0.3)
    return compute_cost_usd(estimated_input_tokens, estimated_output, model)
```

### 1.7 Update model pricing config

**File:** `config/agents/mission_control.yaml`

**Current state** (line 46-58): Only has `input`/`output` per model. Add cache
rates. Because `ModelPricingRateSchema` defaults cache fields to `0.0` (see §1.6
step 1), existing entries without cache fields continue to work — but costs will
be under-reported for cached requests. Add rates to all entries:

```yaml
model_pricing:
  "anthropic:claude-haiku-4-5-20251001":
    input: 1.00
    output: 5.00
    cache_read: 0.10       # 0.1x input (90% discount)
    cache_write_5m: 1.25   # 1.25x input
    cache_write_1h: 2.00   # 2x input
  "anthropic:claude-sonnet-4-6":
    input: 3.00
    output: 15.00
    cache_read: 0.30
    cache_write_5m: 3.75
    cache_write_1h: 6.00
  "anthropic:claude-opus-4-6":
    input: 15.00
    output: 75.00
    cache_read: 1.50
    cache_write_5m: 18.75
    cache_write_1h: 30.00
  "anthropic:claude-opus-4-7":
    input: 5.00
    output: 25.00
    cache_read: 0.50
    cache_write_5m: 6.25
    cache_write_1h: 10.00
  default:
    input: 3.00
    output: 15.00
    cache_read: 0.30
    cache_write_5m: 3.75
    cache_write_1h: 6.00
```

**Note:** Model names use the `anthropic:` prefix to match `_get_model_name()`
return values (e.g., `"anthropic:claude-sonnet-4-6"`). The `model_pricing` DB
table (§2.2b) must use the same prefix format.

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
| 1 | `modules/backend/core/config_schema.py` | Add `CostSchema` + sub-schemas | ~20 |
| 2 | `modules/backend/core/config.py` | Add `_cost` field + `cost` property to `AppConfig` | ~5 |
| 3 | `modules/backend/agents/config_schema.py` | Add `cache_ttl` to `AgentConfigSchema`, cache fields to `ModelPricingRateSchema` | ~10 |
| 4 | `modules/backend/models/agent_catalog.py` | Add `cache_ttl` column | ~5 |
| 5 | `modules/backend/agents/mission_control/helpers/model_builder.py` | Rewrite `build_model_settings()` — remove early return, add cache | ~50 |
| 6 | `modules/backend/agents/mission_control/helpers/agent_executor.py` | Import + call `build_model_settings()`, pass to `run_stream()` | ~10 |
| 7 | `modules/backend/agents/mission_control/cost.py` | Add cache/thinking token params to `compute_cost_usd()`, fix `estimate_cost()` | ~20 |
| 8 | `modules/backend/agents/mission_control/mission_control.py` | Update `compute_cost_usd()` call to pass cache tokens | ~5 |
| 9 | `config/agents/mission_control.yaml` | Add cache rates to `model_pricing` | ~20 |
| 10 | `config/settings/cost.yaml` | New file — cache TTL defaults, alert thresholds | ~15 |
| 11 | Alembic migration | Add `cache_ttl` column to `agent_catalog` | ~10 |

**Estimated effort: 3-4 hours.**

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

    # Token breakdown — separate 5m vs 1h cache (different pricing)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
        comment="Uncached input tokens only")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
        comment="Tokens served from cache (0.1x input price)")
    cache_write_5m_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
        comment="Tokens written to 5-minute cache (1.25x input price)")
    cache_write_1h_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
        comment="Tokens written to 1-hour cache (2x input price)")
    thinking_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
        comment="Extended thinking tokens (billed as output rate)")

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

**Migration:** Create `llm_calls` table with indexes on `(agent_name)`, `(model)`,
`(mission_id)`, `(session_id)`, `(created_at)`.

**Critical:** The `created_at` index is required — all dashboard timeline queries
(§2.5) filter by time range. Without it, every query is a full table scan.
`TimestampMixin` adds `created_at` but does NOT add an index — add it explicitly:

```python
from sqlalchemy import Index

# At module level, after class definition:
Index("ix_llm_calls_created_at", LlmCall.created_at)
```

### 2.2b New database table: `model_pricing` (from research paper 021)

Time-bounded pricing so historical cost stays correct across price changes. The YAML config provides runtime defaults; this table is the source of truth for dashboard cost calculation.

**File:** `modules/backend/models/model_pricing.py` (new)

```python
class ModelPricing(Base):
    """Time-bounded per-model pricing for cost attribution.

    Each row is valid from effective_from to effective_to. When
    Anthropic changes prices, insert a new row — old rows stay
    for historical accuracy.
    """
    __tablename__ = "model_pricing"

    model: Mapped[str] = mapped_column(String(100), primary_key=True)
    effective_from: Mapped[datetime] = mapped_column(primary_key=True)
    effective_to: Mapped[datetime] = mapped_column(
        default=datetime(9999, 12, 31, tzinfo=timezone.utc),
        comment="Far-future sentinel for 'current' pricing — not PostgreSQL 'infinity'",
    )
    price_per_mtok_input: Mapped[float] = mapped_column(Float, nullable=False)
    price_per_mtok_output: Mapped[float] = mapped_column(Float, nullable=False)
    price_per_mtok_cache_write_5m: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_per_mtok_cache_write_1h: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_per_mtok_cache_read: Mapped[float | None] = mapped_column(Float, nullable=True)
```

**Seed data** (April 2026 Anthropic list prices — prefixed to match `llm_calls.model`):
```sql
INSERT INTO model_pricing VALUES
  ('anthropic:claude-opus-4-7',          '2026-04-16', '9999-12-31', 5.00, 25.00, 6.25, 10.00, 0.50),
  ('anthropic:claude-sonnet-4-6',        '2026-02-01', '9999-12-31', 3.00, 15.00, 3.75,  6.00, 0.30),
  ('anthropic:claude-haiku-4-5-20251001','2025-10-01', '9999-12-31', 1.00,  5.00, 1.25,  2.00, 0.10);
```

### 2.2c Costed view (from research paper 021)

Single view for all dashboard queries. Cost is calculated at query time from time-bounded pricing — always historically accurate.

```sql
CREATE OR REPLACE VIEW v_llm_calls_costed AS
SELECT
    c.*,
    -- Cost components
    (c.input_tokens / 1e6) * p.price_per_mtok_input               AS cost_input_usd,
    ((c.output_tokens + c.thinking_tokens) / 1e6) * p.price_per_mtok_output AS cost_output_usd,
    (c.cache_write_5m_tokens / 1e6) * COALESCE(p.price_per_mtok_cache_write_5m, 0) AS cost_cache_write_5m_usd,
    (c.cache_write_1h_tokens / 1e6) * COALESCE(p.price_per_mtok_cache_write_1h, 0) AS cost_cache_write_1h_usd,
    (c.cache_read_tokens / 1e6) * COALESCE(p.price_per_mtok_cache_read, 0) AS cost_cache_read_usd,
    -- Total
    ((c.input_tokens / 1e6) * p.price_per_mtok_input
     + ((c.output_tokens + c.thinking_tokens) / 1e6) * p.price_per_mtok_output
     + (c.cache_write_5m_tokens / 1e6) * COALESCE(p.price_per_mtok_cache_write_5m, 0)
     + (c.cache_write_1h_tokens / 1e6) * COALESCE(p.price_per_mtok_cache_write_1h, 0)
     + (c.cache_read_tokens / 1e6) * COALESCE(p.price_per_mtok_cache_read, 0)
    ) AS total_cost_usd
FROM llm_calls c
LEFT JOIN LATERAL (
    SELECT mp.*
    FROM model_pricing mp
    WHERE mp.model = c.model
      AND c.created_at >= mp.effective_from
      AND c.created_at <  mp.effective_to
    ORDER BY mp.effective_from DESC
    LIMIT 1
) p ON TRUE;
```

### 2.2d Cache anti-patterns to audit before enabling (from research paper 021)

Before deploying caching, verify the platform doesn't have these silent cache breakers:

1. **Dynamic timestamps in system prompts** — check `assemble_instructions()` output for `datetime.now()`, `utc_now()`, or any time-varying content. Move timestamps to user turns.

2. **Tool set churn** — check if agents change their tool list between calls (e.g., different tool subsets for different task types). Each variant creates a separate cache key.

3. **Thinking mode flips** — check if agents switch `thinking` on/off between calls. This invalidates message-level cache hits (system and tool caches survive).

Run these checks and fix any issues BEFORE enabling cache in Phase 1.

### 2.2e Additional cache metric: write-to-read ratio (from research paper 021)

Add to cache performance queries:

```
cache_write_to_read_ratio = (cache_write_5m_tokens + cache_write_1h_tokens) / cache_read_tokens
```

- Target: < 0.5 in steady state
- If close to 1.0: writing as often as reading = no benefit = prefix instability
- Add this as a column in the Cache Performance panel

### 2.3 Record LLM calls from BOTH execution paths

Recording must happen in **both** the dispatch path and the chat path. Extract a shared helper:

**File:** `modules/backend/agents/mission_control/helpers/cost_recorder.py` (new)

```python
"""Records LLM calls to the llm_calls table for cost attribution.

Called from both agent_executor.py (dispatch path) and
mission_control.py (chat path) to ensure all costs are captured.
"""

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

# Estimate ~200 tokens per tool definition (name + description + schema)
TOKENS_PER_TOOL_ESTIMATE = 200


async def record_llm_call(
    db_session,
    *,
    session_id: str | None,
    mission_id: str | None,
    agent_name: str,
    agent_role: str,
    model: str,
    usage,  # PydanticAI RunUsage or RequestUsage
    cost_usd: float,
    latency_ms: int = 0,
    tool_count: int = 0,
) -> None:
    """Persist an LlmCall row.

    Raises on failure — callers decide whether to catch.
    Silent data loss in cost tracking defeats the purpose of this system.
    """
    from modules.backend.models.llm_call import LlmCall

    provider = model.split(":")[0] if ":" in model else "unknown"
    details = usage.details if hasattr(usage, "details") and usage.details else {}

    # PydanticAI reports cache_write_tokens as a single value.
    # Attribute to 1h bucket by default (our default TTL).
    # If usage.details has per-TTL breakdown, use it.
    cache_write_5m = details.get("cache_creation_5m_tokens", 0)
    cache_write_1h = details.get("cache_creation_1h_tokens", 0)
    if not cache_write_5m and not cache_write_1h:
        cache_write_1h = getattr(usage, "cache_write_tokens", 0) or 0

    call = LlmCall(
        session_id=session_id,
        mission_id=mission_id,
        agent_name=agent_name,
        agent_role=agent_role,
        model=model,
        provider=provider,
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        cache_read_tokens=getattr(usage, "cache_read_tokens", 0) or 0,
        cache_write_5m_tokens=cache_write_5m,
        cache_write_1h_tokens=cache_write_1h,
        thinking_tokens=details.get("reasoning_tokens", 0) or details.get("thinking_tokens", 0),
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        tool_count=tool_count,
        tool_schema_tokens=tool_count * TOKENS_PER_TOOL_ESTIMATE,
    )
    db_session.add(call)
    await db_session.flush()
```

**Wire into dispatch path** (`agent_executor.py`):

The dispatch path does NOT have a `db_session` in scope — it runs inside
`_make_agent_executor()` which only receives `event_bus`, `session_id`,
`mission_id`. Two options:

**Option A (preferred):** Acquire a session inside `record_llm_call`:
```python
# cost_recorder.py — use standalone session:
from modules.backend.core.database import get_async_session

async def record_llm_call(...) -> None:
    ...
    async with get_async_session() as db_session:
        db_session.add(call)
        await db_session.commit()
```

**Option B:** Pass `db_session` factory into `_make_agent_executor`. This
requires changing the closure signature, which ripples into callers.

**Recommended: Option A.** `record_llm_call` manages its own session. Callers
are simpler. The write is small (one row) so the session overhead is negligible.

```python
# agent_executor.py — after cost calculation (line 246), before return:
try:
    await record_llm_call(
        session_id=session_id, mission_id=mission_id,
        agent_name=agent_name, agent_role=agent_config.agent_type,
        model=model_name, usage=usage, cost_usd=cost_usd,
        latency_ms=0, tool_count=len(agent_config.tools),
    )
except Exception:
    logger.warning(
        "Failed to record LLM call for %s — cost data will be missing",
        agent_name, exc_info=True,
    )
```

**Wire into chat path** (`mission_control.py`):
```python
# After usage extraction (~line 415), before persisting messages:
try:
    await record_llm_call(
        session_id=str(session_id), mission_id=mission_id,
        agent_name=agent_name, agent_role=agent_config.agent_type,
        model=model_str, usage=usage, cost_usd=cost_usd,
        latency_ms=int(elapsed_ms), tool_count=len(agent_config.tools),
    )
except Exception:
    logger.warning(
        "Failed to record LLM call for %s — cost data will be missing",
        agent_name, exc_info=True,
    )
```

**Error handling philosophy:** `record_llm_call` raises on failure (no
swallowed exceptions). Callers catch and log at `WARNING` level with
`exc_info=True` — the full traceback is in the logs. The agent response
is not blocked by a recording failure, but the failure is **visible**.

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
  cache_write_5m_tokens: number
  cache_write_1h_tokens: number
  cache_hit_rate: number          // cache_read / (cache_read + input)
  write_to_read_ratio: number     // (write_5m + write_1h) / cache_read
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
Phase 0 (Config + Instrumentation)  ← Must come first — schemas before code
  ├── 0.1  CostSchema + cost.yaml           ← Config foundation (20 min)
  │        Files: core/config_schema.py, core/config.py, config/settings/cost.yaml
  ├── 0.2  ModelPricingRateSchema + cache_ttl ← Schema updates (15 min)
  │        Files: agents/config_schema.py, models/agent_catalog.py + migration
  ├── 0.3  llm_calls table + migration       ← Per-request tracking (30 min)
  │        File: models/llm_call.py (new) — include created_at index
  ├── 0.4  model_pricing table + seed data   ← Historical pricing (20 min)
  │        File: models/model_pricing.py (new) — use 9999-12-31 sentinel
  ├── 0.5  v_llm_calls_costed view           ← Single query surface (10 min)
  ├── 0.6  cost_recorder.py                  ← Shared recording helper (30 min)
  │        File: helpers/cost_recorder.py (new) — raises on failure
  ├── 0.7  Wire recording into both paths    ← Start collecting data (30 min)
  │        Files: agent_executor.py, mission_control.py
  └── 0.8  Audit cache anti-patterns (§2.2d) ← Fix before enabling cache (30 min)

Phase 0.5 (Baseline)               ← Run for 3-7 days with no changes
  └── Let data accumulate in llm_calls. Proceed when:
      - llm_calls has >100 rows across >3 distinct agents
      - Top 3 sinks identified via:
        SELECT agent_name, sum(cost_usd) FROM llm_calls
        GROUP BY 1 ORDER BY 2 DESC LIMIT 3

Phase 1 (Prompt Caching)           ← Apply after baseline shows where money goes
  ├── 1.2 Rewrite build_model_settings()     ← Core change (45 min)
  │        Remove early return, add cache for all Anthropic agents
  ├── 1.4 Wire model_settings into dispatch  ← Fix existing gap (30 min)
  │        agent_executor.py + _call_planning_agent()
  ├── 1.6 Update cost.py                     ← Cache token pricing (20 min)
  ├── 1.7 Update mission_control.yaml        ← Add cache rates (10 min)
  └── 1.8 Verify cache hits                  ← Must see >60% on second call

Phase 1.5 (CachePoint — optional)  ← Additional savings on mission context
  └── 1.5 assemble_instructions_with_cache() ← Requires caller refactor (1 hour)
          Changes return type from str to list, updates both execution paths

Phase 2 (Cost Dashboard)           ← Visibility for continuous optimisation
  ├── 2.4-2.5 API + service             ← Backend queries (2 hours)
  ├── 2.6-2.8 Frontend dashboard        ← UI (3 hours)
  └── 2.9 Navigation                    ← Wire into admin (15 min)

Phase 3 (Alerting)                  ← Safety net
  ├── 3.1 Per-agent budgets         ← Config from cost.yaml (30 min)
  ├── 3.2 Alert thresholds          ← Config from cost.yaml (1 hour)
  └── 3.3 Emergency downgrade       ← Config from cost.yaml (30 min)
```

**Total estimated effort:** Phase 0: ~3 hours, Phase 0.5: 3-7 days (passive),
Phase 1: ~2 hours, Phase 1.5: ~1 hour (optional), Phase 2: ~5.5 hours, Phase 3: ~2 hours.

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
