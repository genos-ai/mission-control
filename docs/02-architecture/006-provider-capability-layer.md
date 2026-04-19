# Architecture: Provider Capability Layer

**Version:** 1.0.0
**Date:** 2026-04-18
**Author:** Herman + Architecture Review
**Status:** Design — ready for review
**Depends on:** Plan 55 (CLI engines), Plan 58 (provider factory), Plan 59 (Copilot adapter)

---

## 0. Problem Statement

Mission Control runs 12 agents across three model providers (Anthropic API, GitHub Copilot SDK, Claude Code CLI), each with fundamentally different protocols for tool calling, streaming, structured output, and reasoning. Today these differences are handled ad-hoc:

1. **No assignment-time validation** — an admin can assign GPT-4.1 via Copilot to the Planning Agent, but GPT-4.1 can't produce structured `TaskPlan` output through that provider. The failure surfaces at runtime.
2. **Hardcoded model names** — model identifiers like `anthropic:claude-sonnet-4-6` are scattered through YAML configs, validators, and `model_builder.py`. Model upgrades require multi-file changes.
3. **Provider protocols handled ad-hoc** — `copilot_model.py`, `cli_executor.py`, and `model_builder.py` each handle tools/streaming/thinking with no shared abstraction.
4. **No graceful degradation** — if an agent expects streaming but the provider doesn't support it, behavior is undefined rather than falling back.
5. **Thinking configured three different ways** — `anthropic_thinking`, `reasoning_effort`, and `CLAUDE_CODE_EFFORT_LEVEL` are three mechanisms for the same concept with no unifying abstraction.

---

## 1. Architecture Overview

The Provider Capability Layer sits between agent configuration and model construction. It introduces three concepts:

```
┌─────────────────────────────────────────────────────────────────┐
│                        Agent Config (YAML / DB)                 │
│  agent_name, model, engine, thinking_budget, interface, tools   │
│                              │                                  │
│                    ┌─────────▼──────────┐                       │
│                    │ AgentRequirements   │ ◄── Inferred from    │
│                    │ (what the agent     │     config + code     │
│                    │  needs to function) │                       │
│                    └─────────┬──────────┘                       │
│                              │                                  │
│                    ┌─────────▼──────────┐                       │
│                    │ CapabilityValidator │ ◄── Assignment-time   │
│                    │ (can this model     │     check             │
│                    │  serve this agent?) │                       │
│                    └─────────┬──────────┘                       │
│                              │                                  │
│                    ┌─────────▼──────────┐                       │
│                    │ ModelCapability     │ ◄── Registry of       │
│                    │ Registry            │     what each model   │
│                    │ (what each model    │     can do            │
│                    │  can provide)       │                       │
│                    └─────────┬──────────┘                       │
│                              │                                  │
│                    ┌─────────▼──────────┐                       │
│                    │ ThinkingAdapter     │ ◄── Translates         │
│                    │ (thinking_budget →  │     thinking config    │
│                    │  provider mechanism)│     per provider       │
│                    └─────────┬──────────┘                       │
│                              │                                  │
│              ┌───────────────┼───────────────┐                  │
│              ▼               ▼               ▼                  │
│     AnthropicModel    CopilotModel    CLI Executor              │
│     (PydanticAI)      (PydanticAI)    (subprocess)              │
└─────────────────────────────────────────────────────────────────┘
```

**Key principle:** Agents declare what they *need*. The capability layer determines *how* (or *whether*) a given model+provider combination can deliver it.

---

## 2. Capability Dimensions

Five dimensions define what a model+provider combination can provide and what an agent requires.

### 2.1 Dimension Definitions

| Dimension | Model/Provider Values | Agent Requirement Values |
|-----------|----------------------|--------------------------|
| **tool_calling** | `native_pydanticai`, `native_copilot`, `cli_only`, `none` | `required`, `preferred`, `none` |
| **structured_output** | `native`, `text_parse`, `none` | `required`, `preferred`, `none` |
| **streaming** | `native`, `buffered`, `none` | `required`, `preferred`, `none` |
| **reasoning** | `anthropic_thinking`, `reasoning_effort`, `env_var`, `none` | `required`, `preferred`, `none` |
| **context_window** | Integer (tokens) | Integer (minimum tokens) |

### 2.2 Dimension Details

**Tool Calling** — how custom tools (PydanticAI `ToolDefinition`s) reach the model.

| Value | Provider | Mechanism | Custom Tools Work? |
|-------|----------|-----------|-------------------|
| `native_pydanticai` | Anthropic API, OpenAI API | ToolUse blocks / function_call | Yes — full PydanticAI tool loop |
| `native_copilot` | Copilot SDK | `_ToolBridge` async handler pattern | Yes — via bridge (Plan 59) |
| `cli_only` | Claude Code CLI | Built-in Read/Write/Edit/Bash/Grep/Glob | No — only filesystem tools |
| `none` | — | — | No |

**Structured Output** — whether the model can return typed Pydantic schemas.

| Value | Provider | Mechanism |
|-------|----------|-----------|
| `native` | Anthropic API, OpenAI API (via PydanticAI) | PydanticAI `output_type=Schema`, `output_retries`, `output_validator` |
| `text_parse` | Copilot SDK | Model returns text; caller must parse JSON (fragile for complex schemas) |
| `none` | CLI engines | Unstructured text only |

**Streaming** — real-time token delivery to event bus.

| Value | Provider | Mechanism |
|-------|----------|-----------|
| `native` | Anthropic API (SSE), OpenAI API (SSE) | PydanticAI `run_stream()` → `stream_text(delta=True)` |
| `buffered` | Copilot SDK | `CopilotStreamedResponse` wraps complete response as single-chunk stream |
| `none` | CLI engines | Complete output returned after subprocess completes |

**Reasoning** — extended thinking / chain-of-thought.

| Value | Provider | Mechanism | Parameter |
|-------|----------|-----------|-----------|
| `anthropic_thinking` | Anthropic API | `AnthropicModelSettings(anthropic_thinking=...)` | `adaptive` or `{type: enabled, budget_tokens: N}` |
| `reasoning_effort` | Copilot SDK | `create_session(reasoning_effort=...)` | `low`, `medium`, `high`, `xhigh` |
| `env_var` | Claude Code CLI | `CLAUDE_CODE_EFFORT_LEVEL` env var | `low`, `medium`, `high` |
| `none` | — | Model doesn't support reasoning (Haiku, GPT-4.1) | — |

---

## 3. Data Models

### 3.1 Model Capability — What a Model Can Provide

```python
class ToolCallingCapability(str, Enum):
    NATIVE_PYDANTICAI = "native_pydanticai"
    NATIVE_COPILOT = "native_copilot"
    CLI_ONLY = "cli_only"
    NONE = "none"

class StructuredOutputCapability(str, Enum):
    NATIVE = "native"
    TEXT_PARSE = "text_parse"
    NONE = "none"

class StreamingCapability(str, Enum):
    NATIVE = "native"
    BUFFERED = "buffered"
    NONE = "none"

class ReasoningCapability(str, Enum):
    ANTHROPIC_THINKING = "anthropic_thinking"
    REASONING_EFFORT = "reasoning_effort"
    ENV_VAR = "env_var"
    NONE = "none"


class ModelCapability(BaseModel):
    """What a specific model+provider combination can deliver."""

    model_id: str                     # e.g. "claude-sonnet-4-6"
    provider: str                     # e.g. "anthropic", "copilot", "cli"
    display_name: str                 # e.g. "Claude Sonnet 4.6"
    model_family: str                 # e.g. "claude-sonnet-4"

    # Capabilities
    tool_calling: ToolCallingCapability
    structured_output: StructuredOutputCapability
    streaming: StreamingCapability
    reasoning: ReasoningCapability
    adaptive_thinking: bool = False   # Anthropic adaptive mode (no budget_tokens)
    context_window: int               # e.g. 200_000

    # Cost
    cost_per_m_input: float           # Per million input tokens
    cost_per_m_output: float          # Per million output tokens

    # Metadata
    deprecated: bool = False
    successor: str | None = None      # Model to migrate to when deprecated
```

### 3.2 Agent Requirements — What an Agent Needs

```python
class RequirementLevel(str, Enum):
    REQUIRED = "required"     # Must have — incompatibility is an error
    PREFERRED = "preferred"   # Want — absence is a warning, agent still works
    NONE = "none"             # Don't need

class AgentRequirements(BaseModel):
    """What an agent needs from its model+provider to function correctly."""

    tool_calling: RequirementLevel = RequirementLevel.NONE
    structured_output: RequirementLevel = RequirementLevel.NONE
    streaming: RequirementLevel = RequirementLevel.NONE
    reasoning: RequirementLevel = RequirementLevel.NONE
    min_context_window: int = 32_000
```

### 3.3 Compatibility Result — Validation Output

```python
class CompatibilitySeverity(str, Enum):
    ERROR = "error"           # Will fail at runtime — block assignment
    WARNING = "warning"       # May degrade — allow with notice
    INFO = "info"             # Suboptimal but functional

class CompatibilityIssue(BaseModel):
    dimension: str            # e.g. "tool_calling", "structured_output"
    severity: CompatibilitySeverity
    message: str              # Human-readable explanation
    agent_requires: str       # What the agent needs
    model_provides: str       # What the model offers

class CompatibilityResult(BaseModel):
    compatible: bool          # True if no ERROR-level issues
    issues: list[CompatibilityIssue]
    model_id: str
    provider: str
    agent_name: str
```

---

## 4. Model Capability Registry

### 4.1 Registry Structure

The registry is a singleton that maps `(provider, model_id)` → `ModelCapability`. It is populated from three sources:

```
┌──────────────────────────────────────────────────┐
│              ModelCapabilityRegistry              │
│                                                  │
│  Source 1: Static config (models.yaml)           │
│    ← Known models with hand-verified caps        │
│                                                  │
│  Source 2: Copilot SDK list_models()             │
│    ← Runtime discovery of available models       │
│                                                  │
│  Source 3: Provider defaults                     │
│    ← Fallback capabilities per provider          │
│                                                  │
│  Lookup: get(provider, model_id) → Capability    │
│  Refresh: refresh(provider?) → re-query sources  │
│  List: list(provider?) → all known capabilities  │
└──────────────────────────────────────────────────┘
```

### 4.2 Provider vs Engine — Terminology

In the capability registry, the `provider` field identifies the **execution path** — the combination of auth + transport + tool protocol that determines what capabilities are available. This is broader than the auth-only provider in `providers.yaml`:

| Registry `provider` | Auth provider | Engine | Notes |
|---------------------|---------------|--------|-------|
| `anthropic` | Anthropic API key | `pydantic_ai` | Native PydanticAI — full capabilities |
| `openai` | OpenAI API key | `pydantic_ai` | Native PydanticAI — full capabilities |
| `copilot` | GitHub OAuth | `pydantic_ai` | CopilotModel adapter — bridged capabilities |
| `cli` | Subscription | `claude_code`, `codex`, `copilot` | Subprocess — filesystem tools only |

The first three are **in-process PydanticAI models**. The last is a **subprocess engine** — all CLI engines share the same capability profile regardless of which CLI binary is used, because the capability constraints come from the subprocess boundary, not the underlying model.

### 4.3 Static Configuration — `config/settings/models.yaml`

```yaml
# Known model capabilities. The `provider` field identifies the
# execution path (auth + transport + tool protocol), not just auth.
#
# Same model through different providers has different capabilities:
#   anthropic:claude-sonnet-4-6 → native tools, structured output, streaming
#   copilot:claude-sonnet-4.6   → bridged tools, text-parse output, buffered
#   cli:claude-sonnet-4-6       → filesystem tools only, no structured output

models:
  # ── Anthropic API (native PydanticAI) ─────────────────────────
  - model_id: claude-opus-4-6
    provider: anthropic
    display_name: Claude Opus 4.6
    model_family: claude-opus-4
    tool_calling: native_pydanticai
    structured_output: native
    streaming: native
    reasoning: anthropic_thinking
    adaptive_thinking: true          # No budget_tokens — uses {type: adaptive}
    context_window: 200000
    cost_per_m_input: 15.0
    cost_per_m_output: 75.0

  - model_id: claude-sonnet-4-6
    provider: anthropic
    display_name: Claude Sonnet 4.6
    model_family: claude-sonnet-4
    tool_calling: native_pydanticai
    structured_output: native
    streaming: native
    reasoning: anthropic_thinking
    adaptive_thinking: true
    context_window: 200000
    cost_per_m_input: 3.0
    cost_per_m_output: 15.0

  - model_id: claude-haiku-4-5-20251001
    provider: anthropic
    display_name: Claude Haiku 4.5
    model_family: claude-haiku-4
    tool_calling: native_pydanticai
    structured_output: native
    streaming: native
    reasoning: none
    context_window: 200000
    cost_per_m_input: 0.80
    cost_per_m_output: 4.0

  # ── Copilot SDK (tool bridge, buffered streaming) ─────────────
  - model_id: claude-opus-4.6
    provider: copilot
    display_name: Claude Opus 4.6 (Copilot)
    model_family: claude-opus-4
    tool_calling: native_copilot
    structured_output: text_parse
    streaming: buffered
    reasoning: reasoning_effort
    context_window: 200000
    cost_per_m_input: 0.0
    cost_per_m_output: 0.0

  - model_id: claude-sonnet-4.6
    provider: copilot
    display_name: Claude Sonnet 4.6 (Copilot)
    model_family: claude-sonnet-4
    tool_calling: native_copilot
    structured_output: text_parse
    streaming: buffered
    reasoning: reasoning_effort
    context_window: 200000
    cost_per_m_input: 0.0
    cost_per_m_output: 0.0

  - model_id: gpt-5.4
    provider: copilot
    display_name: GPT-5.4 (Copilot)
    model_family: gpt-5
    tool_calling: native_copilot
    structured_output: text_parse
    streaming: buffered
    reasoning: reasoning_effort
    context_window: 400000
    cost_per_m_input: 0.0
    cost_per_m_output: 0.0

  - model_id: gpt-4.1
    provider: copilot
    display_name: GPT-4.1 (Copilot)
    model_family: gpt-4.1
    tool_calling: native_copilot
    structured_output: text_parse
    streaming: buffered
    reasoning: none
    context_window: 128000
    cost_per_m_input: 0.0
    cost_per_m_output: 0.0

  # ── CLI engines (subprocess — all share same capability profile) ──
  # All CLI engines (claude_code, codex, copilot) execute as subprocesses.
  # Custom PydanticAI tools don't cross the subprocess boundary — only
  # built-in filesystem tools are available. No individual model entries
  # are needed; the cli provider_default covers all CLI engine models.

# Provider defaults — used for unknown models within a known provider.
# The registry falls back to these when a specific model isn't listed.
provider_defaults:
  anthropic:
    tool_calling: native_pydanticai
    structured_output: native
    streaming: native
    reasoning: none                # conservative default
    context_window: 200000
    cost_per_m_input: 3.0
    cost_per_m_output: 15.0

  copilot:
    tool_calling: native_copilot
    structured_output: text_parse
    streaming: buffered
    reasoning: none
    context_window: 200000
    cost_per_m_input: 0.0
    cost_per_m_output: 0.0

  openai:
    tool_calling: native_pydanticai
    structured_output: native
    streaming: native
    reasoning: none
    context_window: 128000
    cost_per_m_input: 2.5
    cost_per_m_output: 10.0

  cli:
    # Shared by all CLI engines (claude_code, codex, copilot).
    # Capability constraints come from the subprocess boundary,
    # not the underlying model.
    tool_calling: cli_only
    structured_output: none
    streaming: none
    reasoning: env_var
    context_window: 200000
    cost_per_m_input: 0.0
    cost_per_m_output: 0.0
```

### 4.4 Model Family Abstraction

Model names contain version suffixes that change on every release (`claude-sonnet-4-6`, `claude-sonnet-4-20250514`). The `model_family` field groups models that share the same capability profile:

```
model_family: claude-sonnet-4
  ├── claude-sonnet-4-6          (latest alias, Anthropic format)
  ├── claude-sonnet-4.6          (Copilot format — dots, not hyphens)
  ├── claude-sonnet-4-20250514   (date-pinned)
  └── claude-sonnet-4-20250601   (future release)
```

**Cross-provider naming:** Anthropic uses hyphens (`claude-sonnet-4-6`), Copilot uses dots (`claude-sonnet-4.6`). The `_infer_family()` function normalizes both formats to the same family string.

**Algorithm:** `model_family` is always set explicitly in `models.yaml` entries — no inference needed for static config. `_infer_family()` is only used for **Copilot dynamic discovery** (Phase 5), where the model list is small and the naming is predictable. The function uses a prefix table:

```python
# Known family prefixes, longest-match-first.
_FAMILY_PREFIXES = [
    "claude-opus-4",
    "claude-sonnet-4",
    "claude-haiku-4",
    "gpt-5",
    "gpt-4.1",       # 4.1 is the family, not a version
    "gpt-4o",
    "o3",
]

def _infer_family(model_id: str) -> str:
    """Infer model family from model ID (Copilot discovery only).

    Matches against known family prefixes. Normalizes dots to hyphens
    for Claude models (Copilot uses claude-sonnet-4.6, Anthropic uses
    claude-sonnet-4-6 — both map to family claude-sonnet-4).

    Falls back to the full model_id if no prefix matches (safe —
    just means no family-based capability inheritance for unknown models).
    """
    # Normalize: claude-sonnet-4.6 → claude-sonnet-4-6
    normalized = model_id
    if model_id.startswith("claude-"):
        normalized = model_id.replace(".", "-")

    for prefix in _FAMILY_PREFIXES:
        if normalized.startswith(prefix):
            return prefix
    return model_id  # Unknown model — use full ID as family
```

For unknown models that don't match any prefix, the family defaults to the full `model_id`. This means no family inheritance (the model gets provider defaults), which is safe.

**Resolution order** for capability lookup:
1. Exact `(provider, model_id)` match
2. Family match — find any entry with matching `model_family` in the same provider
3. Provider default

This means new date-pinned releases automatically inherit family capabilities without config changes.

### 4.5 Shared Utility: `parse_model_ref()`

The pattern `model_name.split(":", 1)` is currently duplicated in 4+ files (`config_schema.py`, `model_builder.py`, `gate.py`, `cost.py`). Phase 1 extracts this into a shared function in `capabilities.py`:

```python
def parse_model_ref(model_ref: str | AgentModelSchema) -> tuple[str, str]:
    """Parse 'provider:model_id' into (provider, model_id).

    Also accepts AgentModelSchema, extracting .name first.
    Raises ValueError if no provider prefix is present.

    This is a pure string parser — it does NOT handle CLI engine
    remapping. CLI remapping (engine=claude_code → provider='cli')
    is handled by get_for_agent_config(), which knows the engine.
    """
```

This replaces all existing ad-hoc splits and becomes the single authoritative parser.

**CLI engine remapping** lives in `get_for_agent_config()`, not `parse_model_ref()`:

```python
def get_for_agent_config(self, agent_config: AgentConfigSchema) -> ModelCapability | None:
    provider, model_id = parse_model_ref(agent_config.model)
    # CLI engines have a fixed capability profile regardless of the
    # underlying model's auth provider.
    if agent_config.engine in ("claude_code", "codex", "copilot"):
        provider = "cli"
    return self.get(provider, model_id)
```

### 4.6 Registry API

```python
class ModelCapabilityRegistry:
    """Singleton registry of model capabilities."""

    def get(self, provider: str, model_id: str) -> ModelCapability | None:
        """Look up capability for a model+provider.

        Resolution order:
          1. Exact (provider, model_id) match
          2. Family match — find entry with same model_family in same provider
          3. Provider default — if provider is in provider_defaults
          4. None — unknown provider or no fallback available

        Returns None only when the provider itself is unknown.
        For known providers, always returns at least the provider default.
        """

    def get_for_agent_config(self, agent_config: AgentConfigSchema) -> ModelCapability | None:
        """Extract provider+model from agent config and look up capability.

        For CLI engines (claude_code, codex, copilot), remaps to
        provider='cli' regardless of the model's auth provider prefix.
        """

    def has(self, provider: str, model_id: str) -> bool:
        """Check if an exact (provider, model_id) entry exists (not fallback)."""

    def list_models(self, provider: str | None = None) -> list[ModelCapability]:
        """List all known model capabilities, optionally filtered by provider."""

    def list_compatible(self, requirements: AgentRequirements) -> list[ModelCapability]:
        """List all models compatible with the given requirements."""

    def refresh(self, provider: str | None = None) -> None:
        """Re-read static config + query dynamic sources (Copilot list_models)."""

    def register(self, capability: ModelCapability) -> None:
        """Dynamically register a model capability (from Copilot discovery)."""
```

---

## 5. Agent Requirements Inference

Agent requirements are **inferred from existing config**, not manually declared. This avoids a second source of truth and means existing agents work without changes.

### 5.1 Inference Rules

```python
def infer_requirements(config: AgentConfigSchema) -> AgentRequirements:
    """Infer what an agent needs from its existing config fields."""

    # Tool calling: required if agent declares tools, none otherwise
    tool_calling = (
        RequirementLevel.REQUIRED if config.tools
        else RequirementLevel.NONE
    )

    # Structured output: required if interface.output is defined and non-empty.
    # (CLI engines already can't declare interface.output — enforced by
    # _validate_cli_engine_interface in config_schema.py, so no engine
    # check is needed here.)
    has_output_schema = (
        config.interface is not None
        and config.interface.output  # non-empty output fields
    )
    structured_output = (
        RequirementLevel.REQUIRED if has_output_schema
        else RequirementLevel.NONE
    )

    # Streaming: preferred for user/platform agents (event bus), none for system
    streaming = (
        RequirementLevel.PREFERRED
        if config.invocation.tier in ("user", "platform")
        else RequirementLevel.NONE
    )

    # Reasoning: required if thinking_budget is set, none otherwise
    reasoning = (
        RequirementLevel.REQUIRED if config.thinking_budget
        else RequirementLevel.NONE
    )

    # Context window: use max_input_length as proxy
    min_context_window = config.max_input_length * 2  # 2x headroom

    return AgentRequirements(
        tool_calling=tool_calling,
        structured_output=structured_output,
        streaming=streaming,
        reasoning=reasoning,
        min_context_window=min_context_window,
    )
```

### 5.2 Override via YAML

For cases where inference is insufficient, agents can explicitly declare `model_requirements` in their YAML:

```yaml
# config/agents/mission/director/agent.yaml
agent_name: mission.director.agent
model_requirements:              # Optional — overrides inference
  tool_calling: required
  streaming: required            # Director needs real-time streaming
  reasoning: preferred
  min_context_window: 128000
```

If `model_requirements` is present in the YAML, it takes precedence over inference. If absent, inference is used. This keeps existing configs working while allowing fine-tuning.

### 5.3 Current Agent Requirements Map

Inferred from the existing 12 agent configs:

| Agent | Tools | Structured Output | Streaming | Reasoning | Min Context |
|-------|-------|-------------------|-----------|-----------|-------------|
| `mission.director.agent` | required (7 tools) | none | preferred | none | 128K |
| `mission.supervisor.agent` | required | none | preferred | none | 64K |
| `mission.workflow.agent` | required | none | preferred | none | 64K |
| `platform.director.agent` | required | none | preferred | none | 128K |
| `platform.health.agent` | required | required | preferred | none | 64K |
| `software.quality.agent` | required (12 tools) | required | preferred | none | 4K |
| `software.architecture.agent` | required (3 tools) | required | preferred | none | 128K |
| `system.planning.agent` | none | none | none | required | 128K |
| `system.verification.agent` | none | required | none | none | 128K |
| `system.summarization.agent` | none | required | none | none | 64K |
| `system.synthesis.agent` | none | none | none | none | 64K |
| `system.knowledge_officer.agent` | none | none | none | none | 64K |

---

## 6. Validation Rules

### 6.1 Compatibility Matrix

The validator checks each capability dimension against the model's capability:

```
Agent Requires    Model Provides          Result
─────────────     ──────────────          ──────
required          native/equivalent       ✅ compatible
required          degraded alternative    ⚠️ warning (with explanation)
required          none                    ❌ error (will fail)
preferred         any non-none            ✅ compatible
preferred         none                    ℹ️ info (suboptimal)
none              any                     ✅ compatible (ignored)
```

### 6.2 Dimension-Specific Rules

**Tool Calling:**

| Agent Requires | Model Provides | Verdict | Reason |
|----------------|---------------|---------|--------|
| required | `native_pydanticai` | ✅ | Full PydanticAI tool loop |
| required | `native_copilot` | ✅ | Tool bridge handles it |
| required | `cli_only` | ❌ ERROR | Custom PydanticAI tools won't execute — CLI only has filesystem tools |
| required | `none` | ❌ ERROR | No tool support at all |

**Structured Output:**

| Agent Requires | Model Provides | Verdict | Reason |
|----------------|---------------|---------|--------|
| required | `native` | ✅ | PydanticAI handles schema enforcement + retries |
| required | `text_parse` | ⚠️ WARNING | May work for simple schemas; complex nested schemas will likely fail |
| required | `none` | ❌ ERROR | No structured output possible |

**Streaming:**

| Agent Requires | Model Provides | Verdict | Reason |
|----------------|---------------|---------|--------|
| required | `native` | ✅ | Real-time token streaming |
| required | `buffered` | ⚠️ WARNING | Works but no real-time UX — full response appears at once |
| required | `none` | ❌ ERROR | No streaming support |
| preferred | `none` | ℹ️ INFO | Agent works; event bus receives `complete` event only |

**Reasoning:**

| Agent Requires | Model Provides | Verdict | Reason |
|----------------|---------------|---------|--------|
| required | any non-`none` | ✅ | Reasoning available (mechanism differs) |
| required | `none` | ❌ ERROR | Model cannot reason (e.g. Haiku) — agent requires it |
| preferred | `none` | ℹ️ INFO | Agent works; output quality may be lower |

**Context Window:**

| Condition | Verdict |
|-----------|---------|
| `model.context_window >= agent.min_context_window` | ✅ |
| `model.context_window < agent.min_context_window` | ❌ ERROR |

### 6.3 Cross-Dimension Rules

Beyond individual dimension checks, some combinations create compound issues:

1. **Engine mismatch** — If `engine != pydantic_ai` and agent requires `structured_output=required`, emit ERROR. CLI engines cannot enforce Pydantic schemas. (Already validated in `config_schema.py` line 249.)

2. **Copilot + structured output** — If provider is `copilot` and agent requires `structured_output=required`, emit WARNING with message: *"Copilot returns text; structured output relies on the model producing valid JSON in its response. Consider using `text_parse` extraction with retry logic, or switch to Anthropic API for this agent."*

3. **CLI engine + custom tools** — If engine is `claude_code`/`codex`/`copilot` and agent declares `tools:` in config, emit ERROR. Custom tools won't execute in CLI subprocess.

### 6.4 Validator API

```python
class CapabilityValidator:
    """Validates model+provider compatibility against agent requirements."""

    def __init__(self, registry: ModelCapabilityRegistry):
        self._registry = registry

    def validate(
        self,
        agent_config: AgentConfigSchema,
        requirements: AgentRequirements | None = None,
    ) -> CompatibilityResult:
        """Check if the agent's configured model can serve its requirements.

        If requirements is None, infers from agent_config.
        """

    def validate_assignment(
        self,
        agent_name: str,
        new_model: str,          # e.g. "copilot:gpt-4.1"
        new_engine: str = "pydantic_ai",
    ) -> CompatibilityResult:
        """Check compatibility before an admin changes an agent's model.

        Called by the admin API endpoint for model reassignment.
        """

    def find_compatible_models(
        self,
        agent_config: AgentConfigSchema,
    ) -> list[ModelCapability]:
        """Return all models that are fully compatible with this agent."""
```

### 6.5 Validation Integration Points

1. **Boot-time** — `AgentRegistry._load_from_db()` validates each agent's model after loading. Incompatible agents are logged as warnings but still loaded (to avoid blocking startup).

2. **Admin API** — `PATCH /api/agents/{name}/model` calls `validate_assignment()` before persisting. Returns validation issues in the response. ERRORs block the change; WARNINGs require explicit confirmation.

3. **Registry reload** — `AgentRegistry.reload()` re-validates after admin changes.

4. **CLI tooling** — `mc admin validate-agents` runs validation across all agents and prints a compatibility report.

---

## 7. Runtime Adaptation

Runtime adaptation translates between agent config (what the agent declares) and provider-specific mechanisms (how to deliver it).

**Design principle: only adapt where the abstraction gap is real.** The existing codebase already handles tool calling and streaming cleanly through PydanticAI's model interface and the engine branching in `agent_executor.py`. Only **thinking/reasoning** has three genuinely divergent mechanisms that need unification. For other dimensions, the capability layer's value is **validation** (Phases 1-3), not runtime wrapping.

### 7.1 Thinking Adapter (the one real adapter)

The only capability that genuinely needs runtime translation. Three providers use three different mechanisms for the same concept.

**ThinkingConfig** — the adapter's output type:

```python
@dataclass
class ThinkingConfig:
    """Provider-agnostic thinking configuration.

    The adapter produces this; the caller applies it to the right
    provider mechanism. This is NOT a polymorphic "settings" object —
    each mechanism is consumed differently:
      - anthropic_thinking → AnthropicModelSettings (passed to run_stream)
      - reasoning_effort   → CopilotModel.__init__() parameter
      - env_var            → os.environ before subprocess exec
    """
    enabled: bool = False
    mechanism: str = ""           # "anthropic_thinking" | "reasoning_effort" | "env_var"
    params: dict = field(default_factory=dict)
    max_tokens: int | None = None  # Anthropic only — required for thinking

    def to_anthropic_settings(self) -> "AnthropicModelSettings | None":
        """Convert to AnthropicModelSettings. Returns None if not Anthropic."""
        if self.mechanism != "anthropic_thinking" or not self.enabled:
            return None
        from pydantic_ai.models.anthropic import AnthropicModelSettings
        return AnthropicModelSettings(
            anthropic_thinking=self.params,
            max_tokens=self.max_tokens,
        )
```

**ThinkingAdapter:**

```python
class ThinkingAdapter:
    """Translates agent thinking_budget → provider-specific mechanism.

    Replaces the ad-hoc logic in model_builder.build_model_settings(),
    which currently only handles Anthropic and silently skips others.
    After Phase 4, build_model_settings() delegates entirely to this
    adapter and the _adaptive_models tuple in model_builder.py is removed.
    """

    def adapt(
        self,
        thinking_budget: dict[str, int] | None,
        capability: ModelCapability,
    ) -> ThinkingConfig:
        """Returns provider-specific thinking configuration."""

        if thinking_budget is None or capability.reasoning == ReasoningCapability.NONE:
            return ThinkingConfig(enabled=False)

        budget = thinking_budget.get("max_thinking_tokens", 10000)

        match capability.reasoning:
            case ReasoningCapability.ANTHROPIC_THINKING:
                # adaptive_thinking is config-driven (models.yaml),
                # NOT hardcoded by family name. Adding a new model
                # with adaptive thinking is a YAML change, not code.
                if capability.adaptive_thinking:
                    return ThinkingConfig(
                        enabled=True,
                        mechanism="anthropic_thinking",
                        params={"type": "adaptive"},
                        max_tokens=16384,
                    )
                max_tokens = budget + 8192
                return ThinkingConfig(
                    enabled=True,
                    mechanism="anthropic_thinking",
                    params={"type": "enabled", "budget_tokens": budget},
                    max_tokens=max_tokens,
                )

            case ReasoningCapability.REASONING_EFFORT:
                effort = _budget_to_effort(budget)
                return ThinkingConfig(
                    enabled=True,
                    mechanism="reasoning_effort",
                    params={"reasoning_effort": effort},
                )

            case ReasoningCapability.ENV_VAR:
                effort = _budget_to_effort(budget)
                return ThinkingConfig(
                    enabled=True,
                    mechanism="env_var",
                    params={"CLAUDE_CODE_EFFORT_LEVEL": effort},
                )


def _budget_to_effort(budget: int) -> str:
    """Map thinking token budget to effort level string."""
    if budget <= 5000:
        return "low"
    elif budget <= 15000:
        return "medium"
    return "high"
```

**How each mechanism is consumed** (not in the adapter — in the caller):

```python
# model_builder.py — Anthropic path (same as today, but via adapter):
thinking_config = ThinkingAdapter().adapt(agent_config.thinking_budget, capability)
model_settings = thinking_config.to_anthropic_settings()  # None if not Anthropic

# agent_executor.py — Copilot path:
# CopilotModel already accepts reasoning_effort in __init__().
# The ThinkingConfig.params dict is passed through when constructing
# the CopilotModel in _build_model().

# agent_executor.py — CLI path:
# thinking_config.params["CLAUDE_CODE_EFFORT_LEVEL"] is set as
# os.environ before subprocess exec (same as current cli_executor.py).
```

**Temperature validation note:** The constraint that `thinking_budget` requires `temperature >= 1.0` for Anthropic models stays in `config_schema.py` (`_validate_model_config`, line 213). That's a **config-time** check — it catches invalid YAML at load. The `ThinkingAdapter` is a **runtime** translator — it takes validated config and produces provider params. These are complementary, not overlapping.

### 7.2 Why NOT a Streaming Adapter

The current `agent_executor.py` already handles the engine split cleanly:

```python
engine = getattr(agent_config, "engine", "pydantic_ai")
if engine != "pydantic_ai":
    result = await engine_fn(**engine_kwargs)        # CLI path — no streaming
else:
    async with agent.run_stream(...) as stream:      # PydanticAI path
        async for text in stream.stream_text(delta=True):
            await event_emitter.emit_chunk(text)
```

Both `NATIVE` (Anthropic) and `BUFFERED` (Copilot) already use `agent.run_stream()` — `CopilotStreamedResponse` wraps the complete response as a single-chunk stream transparently. The existing 2-branch if/else is already clean. Wrapping it in a `StreamingAdapter` class would add indirection without changing behavior.

The capability layer's value for streaming is **validation**: ensuring that an agent requiring `streaming=required` isn't assigned to a CLI engine.

### 7.3 Why NOT a Structured Output Adapter

PydanticAI already owns structured output parsing via `output_type`, `output_retries`, and `output_validator`. When `CopilotModel.request()` returns a `TextPart` and the agent has `output_type=QaAuditResult`, PydanticAI attempts to parse the text as JSON and retries on failure — that's the framework's job.

**Verified:** PydanticAI's `AutoOutputSchema` sets a `text_processor` on all non-text output types. When a `TextPart` is received, `ObjectOutputProcessor.process()` strips markdown fences, calls `validate_json()` against the schema, and raises `ToolRetryError` on validation failure — triggering automatic retries with the validation error as feedback to the model. This works identically for Anthropic (native) and Copilot (text) responses. Source: `pydantic_ai/_output.py:620-632`, `pydantic_ai/_agent_graph.py:1051-1109`.

Adding a post-hoc `StructuredOutputAdapter` that also extracts JSON would create a "who parses?" conflict. Instead:

- **`native`** (Anthropic/OpenAI): PydanticAI handles it end-to-end.
- **`text_parse`** (Copilot): PydanticAI's `output_retries` handles it — the model returns text, PydanticAI tries to parse, retries if needed.
- **`none`** (CLI): Already blocked by `_validate_cli_engine_interface` in config_schema.py.

The capability layer's value for structured output is **validation**: warning that `text_parse` is fragile for complex schemas, and blocking `none` when the agent requires it.

### 7.4 Tool Calling — Validation Only

Tool adaptation is already handled by the existing architecture — no new adapter needed:

- **`native_pydanticai`**: PydanticAI's built-in tool loop (no change).
- **`native_copilot`**: `_ToolBridge` in `copilot_model.py` already converts `ToolDefinition` → Copilot `Tool` (Plan 59).
- **`cli_only`**: CLI executor already restricts to filesystem tools based on `scope_read`/`scope_write`.
- **`none`**: No tools passed to model.

The capability layer's role here is **validation only** — ensuring that an agent requiring custom tools isn't assigned to a `cli_only` or `none` provider.

### 7.5 Integration into Agent Executor

Only the `ThinkingAdapter` changes runtime behavior. The engine branching in `agent_executor.py` stays as-is:

```python
# model_builder.py — Phase 4 change:
# build_model_settings() delegates to ThinkingAdapter instead of
# doing its own ad-hoc provider detection.

def build_model_settings(agent_config: AgentConfigSchema) -> ModelSettings | None:
    capability = get_capability_registry().get_for_agent_config(agent_config)
    thinking_config = ThinkingAdapter().adapt(
        agent_config.thinking_budget, capability,
    )
    return thinking_config.to_anthropic_settings()  # None if not Anthropic

# agent_executor.py — no structural change needed.
# The engine branching (pydantic_ai vs CLI) stays as-is.
# Only model_settings construction changes (via model_builder above).
```

---

## 8. Model Lifecycle Management

### 8.1 Model Discovery

```
┌──────────────────────────────────────────────────┐
│                Discovery Sources                  │
│                                                  │
│  1. Static config (models.yaml)                  │
│     └── Loaded at startup, reloaded on refresh   │
│                                                  │
│  2. Copilot SDK list_models()                    │
│     └── Queried on startup + periodic refresh    │
│     └── Returns model IDs with reasoning caps    │
│                                                  │
│  3. Anthropic API models.list() (future)         │
│     └── Could auto-discover new model releases   │
│                                                  │
│  Resolution: Static config wins for known models │
│  Dynamic discovery fills gaps for new models     │
│  Provider defaults are the ultimate fallback     │
└──────────────────────────────────────────────────┘
```

### 8.2 Copilot Model Discovery

```python
async def discover_copilot_models(registry: ModelCapabilityRegistry) -> None:
    """Query Copilot SDK for available models and register them."""
    from copilot import CopilotClient

    client = CopilotClient(auto_start=True)
    await client.start()

    try:
        models = await client.list_models()
        for model in models:
            model_id = model.id
            # Skip if already in static config
            if registry.has(provider="copilot", model_id=model_id):
                continue

            # Register with provider defaults + model-specific overrides
            capability = ModelCapability(
                model_id=model_id,
                provider="copilot",
                display_name=model.display_name or model_id,
                model_family=_infer_family(model_id),
                # Provider defaults
                tool_calling=ToolCallingCapability.NATIVE_COPILOT,
                structured_output=StructuredOutputCapability.TEXT_PARSE,
                streaming=StreamingCapability.BUFFERED,
                # Model-specific from SDK metadata
                reasoning=_infer_reasoning(model),
                context_window=getattr(model, "context_window", 200_000),
                vision=getattr(model, "vision", False),
                billing_multiplier=0.0,
                cost_per_m_input=0.0,
                cost_per_m_output=0.0,
            )
            registry.register(capability)
    finally:
        await client.stop()
```

### 8.3 Staleness Detection

When an agent references a model that no longer exists:

```python
def check_model_staleness(registry: ModelCapabilityRegistry) -> list[StalenessIssue]:
    """Check all agent configs for stale model references."""
    agent_registry = get_registry()
    agent_registry._ensure_loaded()
    issues = []

    for config in agent_registry._agents.values():
        provider, model_id = parse_model_ref(config.model)
        capability = registry.get(provider, model_id)

        if capability is None:
            issues.append(StalenessIssue(
                agent_name=config.agent_name,
                model_ref=f"{provider}:{model_id}",
                issue="Model not found in capability registry",
                suggestion="Run 'mc admin refresh-models' or update agent config",
            ))
        elif capability.deprecated:
            issues.append(StalenessIssue(
                agent_name=config.agent_name,
                model_ref=f"{provider}:{model_id}",
                issue=f"Model is deprecated",
                suggestion=f"Migrate to {capability.successor}" if capability.successor else "Choose a replacement model",
            ))

    return issues
```

### 8.4 Refresh Lifecycle

```
Startup:
  1. Load models.yaml → static capabilities
  2. Discover Copilot models → dynamic capabilities
  3. Validate all agent configs → log warnings

Periodic (configurable, default 6h):
  1. Re-query Copilot list_models()
  2. Register new models, mark missing ones
  3. Re-validate agent configs

Admin action (mc admin refresh-models):
  1. Full refresh from all sources
  2. Print compatibility report
  3. Flag stale references
```

---

## 9. File Layout

```
modules/backend/core/
├── capabilities.py              # Enums, ModelCapability, AgentRequirements,
│                                # CompatibilityResult, parse_model_ref()
├── capability_registry.py       # ModelCapabilityRegistry singleton
├── capability_validator.py      # CapabilityValidator + validation rules
├── capability_inference.py      # infer_requirements() from AgentConfigSchema
├── thinking_adapter.py          # ThinkingAdapter (the only runtime adapter)
├── copilot_model.py             # (existing) CopilotModel — unchanged
├── model_providers.py           # (existing) Provider factory — unchanged
└── ...

config/settings/
├── providers.yaml               # (existing) Auth config — unchanged
└── models.yaml                  # NEW — model capability registry

modules/backend/agents/
├── config_schema.py             # Add optional model_requirements field
└── mission_control/
    ├── registry.py              # Add validation on load
    └── helpers/
        ├── model_builder.py     # Refactor build_model_settings() → ThinkingAdapter
        └── agent_executor.py    # No structural change (engine branch stays)
```

---

## 10. Migration Plan

### Phase 1: Data Models + Registry (no behavior change)

**Goal:** Introduce `models.yaml`, capability data models, and the registry. Everything is additive — existing code paths are unchanged.

**Files created:**
- `config/settings/models.yaml` — static capability definitions
- `modules/backend/core/capabilities.py` — data models (enums, `ModelCapability`, `AgentRequirements`, `CompatibilityResult`, `parse_model_ref()`)
- `modules/backend/core/capability_registry.py` — `ModelCapabilityRegistry` with `get()`, `list_models()`, `refresh()`

**Quick win:** `parse_model_ref()` in `capabilities.py` replaces 4+ ad-hoc `model_name.split(":", 1)` calls across `config_schema.py`, `model_builder.py`, `gate.py`, and `cost.py`. Update those call sites to use the shared function.

**Files modified:**
- `modules/backend/agents/config_schema.py` — use `parse_model_ref()` instead of inline split
- `modules/backend/agents/mission_control/helpers/model_builder.py` — same
- `modules/backend/agents/mission_control/gate.py` — same
- `modules/backend/agents/mission_control/cost.py` — same

**Validation:** Registry loads at startup, logs model count. Existing behavior unchanged; split logic consolidated.

### Phase 2: Inference + Validation (warnings only)

**Goal:** Infer agent requirements from existing configs. Validate at boot and log warnings. No blocking behavior.

**Files created:**
- `modules/backend/core/capability_inference.py` — `infer_requirements()`
- `modules/backend/core/capability_validator.py` — `CapabilityValidator` with `validate()`

**Files modified:**
- `modules/backend/agents/config_schema.py` — add optional `model_requirements: AgentRequirements | None` field to `AgentConfigSchema`
- `modules/backend/agents/mission_control/registry.py` — call validator in `_load_from_db()`, log warnings

**Validation:** Boot-time log shows `✅ 10/12 agents compatible, ⚠️ 2 warnings, ❌ 0 errors`.

### Phase 3: Admin API Integration (blocking validation)

**Goal:** Add `validate_assignment()` to the admin model-change endpoint. Errors block the change.

**Files modified:**
- Admin API endpoint for model reassignment — add validation call
- `modules/backend/models/agent_catalog.py` — no schema change, validation is in the API layer

**New CLI command:** `mc admin validate-agents` — prints compatibility report.

### Phase 4: Thinking Adapter (refactor model_builder)

**Goal:** Replace ad-hoc thinking logic in `model_builder.py` with `ThinkingAdapter`. This is the only runtime adapter needed — streaming and structured output are already handled cleanly by PydanticAI's model interface and the existing engine branch in `agent_executor.py`.

**Files created:**
- `modules/backend/core/thinking_adapter.py` — `ThinkingAdapter` with `adapt()` method

**Files modified:**
- `modules/backend/agents/mission_control/helpers/model_builder.py` — `build_model_settings()` delegates to `ThinkingAdapter`. The `_adaptive_models` tuple (line 47) and the entire provider-detection block (lines 40-67) are removed — the adapter uses `capability.reasoning` and `capability.model_family` from the registry instead of string matching against model names.

**Not changed:**
- `agent_executor.py` — the engine branch (`pydantic_ai` vs CLI) stays as-is. No `StreamingAdapter` or `StructuredOutputAdapter` — these would add indirection around code that's already clean.

**Validation:** All existing tests pass. Behavior is identical but thinking config routes through the adapter.

### Phase 5: Dynamic Discovery (Copilot model refresh)

**Goal:** Query Copilot SDK `list_models()` at startup and periodically to discover new models.

**Files modified:**
- `modules/backend/core/capability_registry.py` — add `discover_copilot_models()` async method
- Startup sequence — call discovery after registry load

**Validation:** New Copilot models appear in registry without config changes.

### Phase Summary

| Phase | Scope | Risk | Can Ship Independently |
|-------|-------|------|----------------------|
| 1 | Data models + config + `parse_model_ref()` consolidation | Zero — pure additions + mechanical refactor | ✅ Yes |
| 2 | Inference + boot-time warnings | Low — warnings only | ✅ Yes |
| 3 | Admin API blocking | Low — only affects admin endpoint | ✅ Yes |
| 4 | ThinkingAdapter (refactor model_builder only) | Low — single file change | ✅ Yes |
| 5 | Dynamic discovery | Low — additive | ✅ Yes |

Each phase is independently shippable and testable. Phases 1-3 add safety without changing behavior. Phase 4 is a focused refactor of one function (`build_model_settings`). Phase 5 is an enhancement.

---

## 11. Model Pricing Consolidation

The current `model_pricing` section in `mission_control.yaml` duplicates cost information:

```yaml
# Current (mission_control.yaml)
model_pricing:
  "anthropic:claude-sonnet-4-6":
    input: 3.00
    output: 15.00
```

With the capability registry, pricing moves to `models.yaml` via `cost_per_m_input` and `cost_per_m_output`. The `compute_cost_usd()` function in `cost.py` queries the registry instead of reading `mission_control.yaml`:

```python
# After migration
def compute_cost_usd(input_tokens: int, output_tokens: int, model_ref: str) -> float:
    provider, model_id = parse_model_ref(model_ref)
    capability = registry.get(provider, model_id)
    return (
        (input_tokens / 1_000_000) * capability.cost_per_m_input
        + (output_tokens / 1_000_000) * capability.cost_per_m_output
    )
```

**Migration:** Keep `model_pricing` in `mission_control.yaml` as a fallback during Phase 1-3. Remove it in Phase 4 when the registry is the single source of truth.

---

## 12. What This Does NOT Change

- **Individual agent modules** — No changes to any `create_agent()` factory. The capability layer operates above the agent layer.
- **PydanticAI Model interface** — `request()` and `request_stream()` contracts are unchanged. `CopilotModel` and `AnthropicModel` remain as-is.
- **Provider authentication** — `providers.yaml` and `model_providers.py` are unchanged. Auth is orthogonal to capabilities.
- **Event bus** — Event types and streaming protocol are unchanged.
- **Agent YAML structure** — Existing YAML configs work without modification. The optional `model_requirements` field is additive.

---

## 13. Example Scenarios

### Scenario 1: Admin assigns GPT-4.1 to Planning Agent

```
Admin: PATCH /api/agents/system.planning.agent/model {"model": "copilot:gpt-4.1"}

Validator:
  Agent requires: reasoning=required (has thinking_budget)
  GPT-4.1 provides: reasoning=none

  → ❌ ERROR: "system.planning.agent requires reasoning, but copilot:gpt-4.1
     does not support reasoning. Models with reasoning: copilot:claude-opus-4.6,
     copilot:claude-sonnet-4.6, copilot:gpt-5.4"

  Assignment blocked.
```

### Scenario 2: Admin assigns Copilot Sonnet to Verification Agent

```
Admin: PATCH /api/agents/system.verification.agent/model {"model": "copilot:claude-sonnet-4.6"}

Validator:
  Agent requires: structured_output=required (has interface.output)
  Copilot Sonnet provides: structured_output=text_parse

  → ⚠️ WARNING: "system.verification.agent requires structured output, but
     copilot:claude-sonnet-4.6 only supports text_parse. The model must produce
     valid JSON in its response for the output schema to be extracted. This may
     fail for complex schemas."

  Assignment allowed with warning.
```

### Scenario 3: Admin assigns Copilot Sonnet to Summarization Agent

```
Admin: PATCH /api/agents/system.summarization.agent/model {"model": "copilot:claude-sonnet-4.6"}

Validator:
  Agent requires: tools=none, structured_output=required, streaming=none, reasoning=none
  Copilot Sonnet provides: tools=native_copilot, structured_output=text_parse, streaming=buffered, reasoning=reasoning_effort

  → ⚠️ WARNING: structured_output text_parse (same as above)
  → All other dimensions: ✅ compatible

  Assignment allowed with warning.
```

### Scenario 4: New model release (Claude Sonnet 4.7)

```
1. Anthropic releases claude-sonnet-4-7-20260501

2. Admin updates one agent's YAML: model: anthropic:claude-sonnet-4-7-20260501

3. Capability registry lookup:
   - Exact match? No entry for claude-sonnet-4-7-20260501
   - Family match? model_family "claude-sonnet-4" → inherits Sonnet 4.6 capabilities
   - Provider default? Not needed — family matched

4. Agent boots with full capability profile. No models.yaml change needed.

5. (Optional) Admin adds explicit entry to models.yaml if capabilities differ.
```

---

## Appendix A: Glossary

| Term | Definition |
|------|-----------|
| **Provider** (auth) | Authentication layer in `providers.yaml`: `anthropic`, `openai` |
| **Provider** (capability) | Execution path in `models.yaml`: `anthropic`, `openai`, `copilot`, `cli`. Combines auth + transport + tool protocol to determine capabilities. See §4.2. |
| **Engine** | Execution mechanism in agent config: `pydantic_ai` (in-process), `claude_code`/`codex`/`copilot` (subprocess). All CLI engines map to capability provider `cli`. |
| **Model** | The LLM itself: `claude-sonnet-4-6`, `gpt-5.4`, etc. |
| **Model family** | A group of models sharing capabilities: `claude-sonnet-4` covers all Sonnet 4.x releases across naming formats |
| **Capability** | What a `(provider, model)` pair can deliver: tool calling, streaming, etc. |
| **Requirement** | What an agent needs: `required`, `preferred`, or `none` for each capability |
| **Adaptation** | Translating an agent's config into provider-specific parameters at runtime (only needed for thinking) |

## Appendix B: Decision Log

| Decision | Rationale |
|----------|-----------|
| Infer requirements from existing config instead of requiring manual declaration | Avoids second source of truth, existing agents work without changes |
| Use `model_family` for capability inheritance | New model releases work without config changes; cross-provider naming normalized |
| Provider defaults as ultimate fallback | Unknown models get conservative capabilities instead of errors |
| Warnings at boot, errors at assignment | Don't break startup for existing configs; block new mistakes |
| Separate config from code for model definitions | Adding a model is a YAML change, not a code change |
| Phase adapters last (Phase 4) | Safety (validation) ships before refactoring (adapters) |
| Only ThinkingAdapter — no StreamingAdapter or StructuredOutputAdapter | Streaming already works cleanly via PydanticAI's model interface + engine branch. Structured output is PydanticAI's responsibility via `output_type`/`output_retries` (verified in source: `AutoOutputSchema` parses TextPart as JSON and retries on failure). Adding adapters would wrap code that's already clean. |
| All CLI engines share one `cli` provider default | Capability constraints come from the subprocess boundary, not the underlying CLI binary. claude_code, codex, and copilot CLIs all have the same capability profile: cli_only tools, no streaming, no structured output. |
| Extract `parse_model_ref()` in Phase 1 | Quick win — replaces 4+ duplicated `model_name.split(":", 1)` patterns across the codebase. `parse_model_ref()` is a pure string parser; CLI engine remapping lives in `get_for_agent_config()` which has the engine context. |
| Temperature validation stays in config_schema.py | Config-time check (catches bad YAML early). ThinkingAdapter is runtime translation (takes validated config, produces provider params). Complementary, not overlapping. |
| `adaptive_thinking` as explicit config field, not family name matching | The whole point of the capability layer is to make model properties config-driven. Hardcoding family names in the ThinkingAdapter would replicate the problem being solved. New models with adaptive thinking are a YAML change. |
| `_infer_family()` uses prefix table, not heuristic parsing | Model naming conventions vary too much across providers for a general algorithm. A prefix table is explicit, testable, and only used for Copilot dynamic discovery. Static config always sets `model_family` explicitly. |
| No `vision` dimension | No agent currently requires vision. Adding it when the first vision-requiring agent arrives avoids premature abstraction. |
| `ThinkingConfig` is a dataclass, not a polymorphic settings object | Each provider mechanism is consumed differently (ModelSettings, __init__ param, env var). A polymorphic `to_model_settings()` would paper over these real differences. The adapter returns a typed config; the caller applies it provider-appropriately. |
