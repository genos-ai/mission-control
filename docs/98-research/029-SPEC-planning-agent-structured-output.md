# SPEC: Planning Agent Structured Output

**Version:** 1.1.0
**Status:** Draft — revised after codebase review
**Author:** Herman Young
**Date:** 2026-05-01
**Module:** `modules/backend/agents/mission/planning/`

---

## 1.0 Summary

The Planning Agent produces TaskPlan JSON that fails Pydantic validation ~70% of the time on complex workflows (security scanning, multi-agent orchestration) and ~10% on simpler ones (research). The root cause is not the prompt — it is the output mode. The agent currently uses `output_type=str` (default), produces JSON inside `<task_plan>` XML tags, and relies on regex extraction followed by Pydantic validation. Extended thinking is disabled because it conflicts with the old `ToolOutput` approach.

This spec replaces XML tag parsing with `NativeOutput(TaskPlan, strict=True)` backed by Anthropic's constrained decoding beta (`structured-outputs-2025-11-13`). The grammar compiles the TaskPlan schema at request time and constrains token generation — the model physically cannot emit schema-violating output. Extended thinking re-enabled via adaptive mode on Opus 4.6.

**Target:** ≤3% TaskPlan validation failure rate across all workflow types, down from ~70% on complex workflows.

---

## 2.0 Architecture

### 2.1 Current State (What Changes)

| Component | Current | Target |
|---|---|---|
| Planning Agent `output_type` | `str` (default) | `NativeOutput(TaskPlan, strict=True)` |
| JSON extraction | Regex on `<task_plan>…</task_plan>` tags | PydanticAI handles natively |
| Schema enforcement | Prompt-only (85-line JSON example in system prompt) | Token-level constrained decoding via Anthropic `output_format` |
| Retry error format | Raw `ValidationError.errors()` (verbose) | Compacted JSON-pointer format (≤10 lines) |
| Normaliser | `model_validator(mode="before")` on ~8 aliases | Retained, extended to cover known drift patterns |
| Anthropic betas header | Not sent | `anthropic-beta: structured-outputs-2025-11-13` via YAML config |
| Planning call streaming | `agent.run_stream()` with text streaming | `agent.run()` non-streaming (PydanticAI #3393 — ModelRetry crashes in run_stream validators) |
| Extended thinking | Disabled (commented out in YAML) | Re-enabled — adaptive mode on Opus 4.6 |
| Model | `anthropic:claude-sonnet-4-6` | `anthropic:claude-opus-4-6` |

### 2.2 Execution Flow

```
Mission Control (mission_dispatch.py)
  │
  ├─ 1. Derives roster, assembles context
  │
  ├─ 2. Calls _call_planning_agent() [agent_executor.py]
  │     │
  │     ├─ _build_model("anthropic:claude-opus-4-6")
  │     │   └─ AnthropicModel + get_anthropic_provider() [already direct, no Copilot SDK]
  │     │
  │     ├─ create_agent(model) → Agent with NativeOutput(TaskPlan, strict=True)
  │     │   └─ build_model_settings() passes anthropic_betas from agent YAML
  │     │
  │     ├─ _build_planning_prompt() → assembled prompt string (unchanged signature)
  │     │
  │     ├─ agent.run(planning_prompt, model_settings=...) [non-streaming]
  │     │   ├─ PydanticAI sends output_format={type:"json_schema", schema:TaskPlan}
  │     │   ├─ Anthropic compiles schema → grammar
  │     │   ├─ Extended thinking runs unconstrained in thinking blocks
  │     │   └─ Final tokens are grammar-constrained → TaskPlan JSON
  │     │
  │     ├─ output_validator fires (semantic checks: cycles, dangling refs, format)
  │     │   └─ On failure: compact ModelRetry (≤10 lines) — up to output_retries=2
  │     │
  │     └─ Returns {"task_plan": result.output.model_dump(), "thinking_trace": ..., "usage": ...}
  │
  ├─ 3. mission_dispatch.py: TaskPlan.model_validate(planning_result["task_plan"])
  │     └─ Unchanged — model_validate accepts a dict or model instance
  │
  └─ 4. validate_plan() → dispatch loop [unchanged]
```

### 2.3 Files Changed

9 targeted changes across existing files. No new files created.

| # | File | Change |
|---|---|---|
| 1 | `config/agents/mission/planning/agent.yaml` | Model → opus-4-6, uncomment thinking_budget, add betas flag |
| 2 | `modules/backend/schemas/agent_config.py` | (a) Add `betas: list[str]` to `AgentModelSchema`; (b) relax `_validate_model_config` — remove temperature ≥ 1.0 constraint for adaptive-capable models (4.x) |
| 3 | `modules/backend/core/model_builder.py` | Read `model.betas` from config, pass as `anthropic_betas` into `AnthropicModelSettings` |
| 4 | `modules/backend/schemas/task_plan.py` | `Literal["normal","high","critical"]` for `priority`; move `ge`/`le` Field constraints to output_validator |
| 5 | `modules/backend/agents/mission/planning/agent.py` | `NativeOutput(TaskPlan, strict=True)` for dispatch mode; `_register_output_validator()`; remove `run_agent()` + `extract_task_plan_json()` |
| 6 | `modules/backend/agents/mission_control/helpers/agent_executor.py` | Switch `_call_planning_agent()` to `agent.run()`; remove `extract_task_plan_json` import |
| 7 | `config/prompts/agents/mission/planning/system.md` | Remove 85-line JSON example; concise field reference + `<output_contract>` block |
| 8 | `modules/backend/agents/mission_control/helpers/prompt_builder.py` | Replace `## Output Format` section with `<output_contract>` block |

### 2.4 What Does NOT Change

- `modules/backend/agents/mission_control/mission_dispatch.py` — interface unchanged; `planning_result["task_plan"]` remains a dict
- `modules/backend/schemas/task_plan.py` schema structure — no field additions or removals
- Chat mode in `agent.py` — stays as `output_type=str` with tools (save_plan, get_roster etc.) — NativeOutput is dispatch-only
- `modules/backend/agents/mission_control/plan_validator.py` — 11 semantic rules unchanged
- All downstream dispatch, roster, verification code — TaskPlan schema contract unchanged

### 2.5 Skipped (vs. original spec draft)

| Item | Why |
|---|---|
| New `provider.py` in planning package | `_build_model("anthropic:...")` already uses `get_anthropic_provider()` — direct Anthropic, no Copilot SDK involved |
| New `schemas.py` in planning package | `TaskPlan` lives in `modules/backend/schemas/task_plan.py` — shared by dispatch, API, tests — correct location |
| New `prompts.py` in planning package | `_build_planning_prompt()` already in `prompt_builder.py` |
| `planning_audit` table (PostgreSQL) | Separate DB migration — out of scope; thinking trace already captured in `persist_mission_results()` |
| `PlanningRefusalError` | Add only if `stop_reason="refusal"` is observed in production |
| Two-stage generation (Approach C) | Not needed — direct Anthropic path supports constrained decoding |

---

## 3.0 Model

**Model:** `anthropic:claude-opus-4-6`

Changed from `claude-sonnet-4-6`. Rationale: the Planning Agent performs multi-agent task decomposition with dependency graph reasoning, verification tier decisions, and cost estimation across a heterogeneous roster. This is a pure reasoning task where Opus earns its cost. The planning step runs once per mission — at Opus 4.6 pricing it is single-digit cents per call.

**Why not Opus 4.7:** Opus 4.7 removes `temperature` and `budget_tokens`, which the planning agent depends on. Neither headline 4.7 feature (high-resolution vision, step-change agentic coding) applies here.

**Thinking:** Adaptive mode (`type: "adaptive"`). Adaptive is the correct setting for Opus 4.6 — `budget_tokens` is deprecated. Compatible with `output_format` constrained decoding (grammar applies only to final content tokens; thinking blocks are unconstrained).

**Temperature:** 0.2. Reduces output variance on structured JSON. Not available on Opus 4.7 — this is a migration blocker noted for future reference.

---

## 4.0 Schema Shaping Rules

Anthropic's grammar compiler has hard limits. Violations produce `400 Schema too complex` at request time.

### 4.1 Constraints

| Constraint | Limit | Current TaskPlan status |
|---|---|---|
| `additionalProperties: false` | Required on every object | Already enforced via `extra="forbid"` ✓ |
| Recursive types | Not supported | None in current schema ✓ |
| `minimum` / `maximum` on numbers | Silently stripped | `ge=0.0` on `estimated_cost_usd`, `estimated_duration_seconds`; `ge=0.0, le=1.0` on `min_success_threshold` — **must move to output_validator** |
| `minLength` / `maxLength` on strings | Silently stripped | None currently ✓ |
| Nesting depth | >4 levels risks grammar-too-complex | TaskPlan is 4 levels deep — do not add depth |
| Discriminated unions | Supported via `Literal` discriminator | `priority: str` → change to `Literal["normal", "high", "critical"]` |

### 4.2 Changes to `task_plan.py`

**Add `Literal` for priority** (grammar-enforced vocabulary):
```python
from typing import Literal

class TaskConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timeout_override_seconds: int | None = None
    priority: Literal["normal", "high", "critical"] = "normal"
```

**Move `ge`/`le` constraints to output_validator** (grammar strips them):
```python
# Before (silently stripped by grammar compiler)
estimated_cost_usd: float = Field(default=0.0, ge=0.0)
estimated_duration_seconds: int = Field(default=0, ge=0)

# After (no Field constraints; validated in output_validator)
estimated_cost_usd: float = 0.0
estimated_duration_seconds: int = 0
```

`evaluator_agent: str | None` stays as-is — making it `Literal["verification_agent"]` would break valid `None` values. The semantic rule (must be "system.verification.agent" when `requires_ai_evaluation=True`) is enforced in the output_validator.

---

## 5.0 Agent Definition

### 5.1 `create_agent()` Changes

`NativeOutput` is applied only for dispatch mode. Chat mode keeps `output_type` unset (defaults to `str`) because it produces conversational responses and uses `save_plan` tool to persist plans.

```python
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.output import NativeOutput

from modules.backend.schemas.task_plan import TaskPlan

def create_agent(
    model: str | Model,
    tool_names: list[str] | None = None,
    *,
    chat_mode: bool = False,
) -> Agent:
    if isinstance(model, str):
        model = _build_model(model)

    base_prompt = assemble_instructions("mission", "planning")
    if chat_mode:
        chat_prompt = assemble_instructions("mission", "planning", variant="chat")
        system_prompt = f"{base_prompt}\n\n{chat_prompt}"
    else:
        system_prompt = base_prompt

    if chat_mode:
        agent = Agent(model, system_prompt=system_prompt, deps_type=PlanningAgentDeps)
        _register_chat_tools(agent)
    else:
        agent = Agent(
            model,
            output_type=NativeOutput(TaskPlan, strict=True),
            system_prompt=system_prompt,
            deps_type=PlanningAgentDeps,
            output_retries=2,
        )
        _register_output_validator(agent)

    return agent
```

### 5.2 Output Validator

Handles semantic rules the grammar cannot enforce. Compact error format ensures retry convergence.

**Note on overlap with `plan_validator.py`:** The output_validator intentionally rechecks some of the same rules (DAG cycles, dependency consistency, tier_3 completeness) that `plan_validator.py` also checks. This is correct — the output_validator gives the model targeted `ModelRetry` feedback immediately, with a budget of 2 retries, before the plan ever reaches `validate_plan()`. `plan_validator.py` remains the authoritative gate before dispatch and is unchanged.

```python
def _register_output_validator(agent: Agent) -> None:

    @agent.output_validator
    async def validate_plan(ctx: RunContext[PlanningAgentDeps], plan: TaskPlan) -> TaskPlan:
        errors: list[str] = []

        # Validate estimated values are non-negative (ge constraint moved here)
        if plan.estimated_cost_usd < 0:
            errors.append(f"estimated_cost_usd must be >= 0, got {plan.estimated_cost_usd}")
        if plan.estimated_duration_seconds < 0:
            errors.append(f"estimated_duration_seconds must be >= 0, got {plan.estimated_duration_seconds}")

        # Validate task_id format
        import re
        id_pattern = re.compile(r"^v\d+-task-\d{3}$")
        for task in plan.tasks:
            if not id_pattern.match(task.task_id):
                errors.append(
                    f"tasks[{task.task_id}].task_id: must match v{{N}}-task-{{NNN}}, "
                    f"got '{task.task_id}'"
                )

        # Validate dependency references exist
        all_ids = {t.task_id for t in plan.tasks}
        for task in plan.tasks:
            for dep in task.dependencies:
                if dep not in all_ids:
                    errors.append(
                        f"tasks[{task.task_id}].dependencies: '{dep}' not in plan"
                    )

        # Validate from_upstream refs are in dependencies
        for task in plan.tasks:
            for field_name, ref in task.inputs.from_upstream.items():
                refs = ref if isinstance(ref, list) else [ref]
                for r in refs:
                    if r.source_task not in task.dependencies:
                        errors.append(
                            f"tasks[{task.task_id}].inputs.from_upstream[{field_name}]: "
                            f"source_task '{r.source_task}' not in dependencies"
                        )

        # Validate DAG (no cycles)
        visited: set[str] = set()
        in_stack: set[str] = set()
        task_map = {t.task_id: t for t in plan.tasks}

        def has_cycle(tid: str) -> bool:
            if tid in in_stack:
                return True
            if tid in visited:
                return False
            visited.add(tid)
            in_stack.add(tid)
            for dep in task_map.get(tid, task_map[tid]).dependencies:
                if has_cycle(dep):
                    return True
            in_stack.discard(tid)
            return False

        for t in plan.tasks:
            if t.task_id not in visited and has_cycle(t.task_id):
                errors.append(f"TaskPlan contains a dependency cycle at '{t.task_id}'")
                break

        # Validate tier_3 consistency
        for task in plan.tasks:
            t3 = task.verification.tier_3
            if t3.requires_ai_evaluation:
                if not t3.evaluation_criteria:
                    errors.append(
                        f"tasks[{task.task_id}].verification.tier_3: "
                        f"requires_ai_evaluation=true but evaluation_criteria is empty"
                    )
                if t3.evaluator_agent != "system.verification.agent":
                    errors.append(
                        f"tasks[{task.task_id}].verification.tier_3: "
                        f"evaluator_agent must be 'system.verification.agent', "
                        f"got '{t3.evaluator_agent}'"
                    )

        if errors:
            # Cap at 10 errors — full dump dilutes the correction signal
            capped = errors[:10]
            if len(errors) > 10:
                capped.append(f"… and {len(errors) - 10} more errors")
            raise ModelRetry("\n".join(f"- {e}" for e in capped))

        return plan
```

### 5.3 Dead Code Removal

`run_agent()` and `extract_task_plan_json()` in `agent.py` are no longer called once `_call_planning_agent()` uses `agent.run()`. Remove both.

---

## 6.0 `_call_planning_agent()` Rewrite

In `modules/backend/agents/mission_control/helpers/agent_executor.py`.

**Current:** `agent.run_stream()` → stream text → `extract_task_plan_json(full_content)` → returns dict

**Target:** `agent.run()` → `result.output` is a typed `TaskPlan` → `result.output.model_dump()` → returns same dict shape

Return shape is unchanged so `mission_dispatch.py` requires no edits:

```python
# Key change — replace the run_stream block with:
result = await agent.run(
    planning_prompt,
    deps=deps,
    model_settings=planning_model_settings,
)
plan_dict = result.output.model_dump()

# Thinking trace extraction unchanged (same all_messages() API)
# Cost recording unchanged (same usage() API)

return {
    "task_plan": plan_dict,        # same key, same shape
    "thinking_trace": thinking_trace,
    "usage": result.usage(),
}
```

Streaming of planning progress (the `AgentResponseChunkEvent` loop) is removed. The planning call is typically 5–15 seconds; non-streaming is acceptable for a step whose output is consumed by deterministic code, not displayed to a user. A `AgentThinkingEvent` is emitted at start and `AgentResponseCompleteEvent` at end — the UI sees the planning agent "thinking" until the plan arrives.

---

## 7.0 Beta Header — YAML and `build_model_settings()`

The `anthropic-beta: structured-outputs-2025-11-13` header must be sent with the planning agent's requests. It is **not** sent globally — only agents that declare it in their YAML config get it.

### 7.1 YAML change (`agent.yaml`)

```yaml
model:
  name: "anthropic:claude-opus-4-6"
  temperature: 0.2
  max_tokens: 16000
  betas:
    - "structured-outputs-2025-11-13"

thinking_budget:
  max_thinking_tokens: 10000   # value not used mechanically for 4.x adaptive models;
                               # documents intent and satisfies the schema field requirement
```

### 7.2 Schema change (`agent_config.py`)

**Two changes:**

**a) Add `betas` to `AgentModelSchema`:**

```python
class AgentModelSchema(_StrictBase):
    name: str = Field(...)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0, ...)
    max_tokens: int = Field(default=4096, ge=1, ...)
    betas: list[str] = Field(default_factory=list)   # ← add this
```

**b) Relax `_validate_model_config` — remove the temperature ≥ 1.0 block only:**

The current validator (lines 224–230) rejects any agent that has both `thinking_budget` and `temperature < 1.0`. This was correct for Claude 3.x extended thinking, which required `temperature=1.0`. For Claude 4.x (Sonnet 4.6, Opus 4.6) with adaptive thinking, Anthropic dropped this constraint. The validator is wrong for 4.x models and is the reason thinking has been commented out in the planning agent YAML.

Remove only this block — the rest of `_validate_model_config` stays:

```python
# DELETE only these lines from _validate_model_config:
        if self.thinking_budget and isinstance(self.model, AgentModelSchema):
            if provider == "anthropic" and self.model.temperature < 1.0:
                raise ValueError(
                    f"Agent '{self.agent_name}' has thinking_budget but temperature "
                    f"{self.model.temperature} < 1.0. Anthropic requires temperature=1.0 "
                    f"when extended thinking is enabled."
                )
```

All other validator logic (provider prefix check, known provider check, invocation tier constraints) is unchanged. This is a safe removal — all current agents with `thinking_budget` use Opus 4.6 or Sonnet 4.6, which use adaptive mode where temperature is irrelevant to thinking activation.

### 7.3 `build_model_settings()` change

```python
# After existing cache_kwargs and max_tokens setup:
betas = []
if isinstance(agent_config.model, AgentModelSchema):
    betas = agent_config.model.betas or []

settings_kwargs = {**cache_kwargs, "max_tokens": max_tokens}
if thinking_config:
    settings_kwargs["anthropic_thinking"] = thinking_config
if betas:
    settings_kwargs["anthropic_betas"] = betas

return AnthropicModelSettings(**settings_kwargs)
```

---

## 8.0 Prompt Changes

### 8.1 System Prompt (`config/prompts/agents/mission/planning/system.md`)

Remove the 85-line JSON schema example block (lines 17–85). Replace with a concise field reference. The schema is now enforced by the grammar — duplicating it in the prompt wastes context and creates drift risk when the Pydantic model changes.

Add at the end of the file:

```
Your output is enforced by JSON Schema via constrained decoding. Only emit fields defined
in the TaskPlan schema. Use exact enum spellings for `priority`. Use exact agent names and
versions from the Available Agents roster. Reason in your thinking blocks; the final JSON
is grammar-constrained.
```

Remove the instruction: "You MUST return a TaskPlan as JSON within `<task_plan>` XML tags."

### 8.2 Planning Prompt (`_build_planning_prompt()`)

Replace the `## Output Format` section (currently "Return your task plan as JSON within `<task_plan>` tags") with an `<output_contract>` block:

```python
parts.append(
    "<output_contract>"
    "This response is enforced by JSON Schema via constrained decoding. "
    "Only emit fields defined in the TaskPlan schema. "
    "Use exact enum spellings for priority (normal | high | critical). "
    "Use exact agent names and versions from the roster above. "
    "Every source_task in from_upstream must appear in that task's dependencies."
    "</output_contract>"
)
```

---

## 9.0 Behavioural Invariants

| ID | Invariant | Test method |
|---|---|---|
| SO-01 | Dispatch mode agent has `output_type=NativeOutput(TaskPlan, strict=True)` | Unit: inspect `agent.output_type` |
| SO-02 | Chat mode agent has no `output_type` set (defaults to str) | Unit: inspect `agent.output_type` |
| SO-03 | `build_model_settings()` passes `anthropic_betas` when YAML declares them | Unit: mock config with betas, assert AnthropicModelSettings.anthropic_betas |
| SO-04 | `_call_planning_agent()` returns `{"task_plan": dict, ...}` (not a TaskPlan instance) | Unit: assert isinstance(result["task_plan"], dict) |
| SO-05 | Normaliser converts `plan_version: 1` → `version: "1.0.0"` | Unit: TaskPlan.model_validate({"plan_version": 1, ...}) |
| SO-06 | Normaliser strips unknown top-level keys without error | Unit: TaskPlan.model_validate({"approach": "...", "version": "1.0.0", ...}) |
| SO-07 | Output validator raises ModelRetry for dependency cycle | Unit: construct cyclic plan, call validator |
| SO-08 | Output validator raises ModelRetry for dangling from_upstream reference | Unit: construct dangling ref, assert ModelRetry |
| SO-09 | Output validator compacts to ≤10 lines per retry | Unit: plan with 20 errors, assert message line count |
| SO-10 | Tier 3 with `requires_ai_evaluation=True` and wrong evaluator_agent raises ModelRetry | Unit: construct task, assert validator catches it |
| SO-11 | `extract_task_plan_json` is not importable from agent.py (removed) | Unit: assert ImportError or AttributeError |

---

## 10.0 Migration Sequence

1. `agent_config.py` — (a) add `betas` to `AgentModelSchema`; (b) remove temperature ≥ 1.0 validator block
2. `task_plan.py` — `Literal` for priority, move `ge`/`le` out of Field
3. `model_builder.py` — read `model.betas`, pass as `anthropic_betas` into `AnthropicModelSettings`
4. `agent.yaml` — opus-4-6, uncomment thinking_budget, add betas list
5. `agent.py` — `NativeOutput` dispatch mode, `_register_output_validator()`, remove `run_agent()` + `extract_task_plan_json()`
6. `agent_executor.py` — switch `_call_planning_agent()` to `agent.run()`, remove `extract_task_plan_json` import
7. `system.md` — remove 85-line JSON example, add concise field reference + `<output_contract>`
8. `prompt_builder.py` — replace `## Output Format` section with `<output_contract>` block
9. Verify: `AgentConfigSchema` loads the updated `agent.yaml` without validation error
10. Run unit tests (normalisers, output_validator, model_settings, betas passthrough)
11. Run integration test against live Anthropic for research + security workflow types
12. Deploy; run 10 missions in staging, measure failure rate
13. Confirm `extract_task_plan_json` is unreachable (no remaining callers)

---

## 11.0 Error Handling

| Error | Source | Handling |
|---|---|---|
| `ValidationError` from Pydantic | Schema field/type mismatch | PydanticAI retries with compact error (output_retries=2) |
| `ModelRetry` from output_validator | Semantic rule violation | PydanticAI retries with validator message |
| `400 Schema too complex` | Anthropic grammar compiler | Fatal — log, fail planning. Indicates a schema change violated §4.1 constraints. |
| `anthropic.APIError` (429, 500) | Rate limit / transient | Retried by Anthropic SDK's built-in exponential backoff |
| `ValueError` from extract (removed) | Was raised when `<task_plan>` tags missing | No longer applicable — NativeOutput handles extraction |

---

## 12.0 Out of Scope

- **`planning_audit` table** — DB migration + model + repository for 7-year retention of thinking traces. Tracked separately. Thinking trace is currently captured in `persist_mission_results()` — not lost, just not in a dedicated table.
- **Schema changes to TaskPlan** — this spec changes enforcement, not structure.
- **Other agents** — only the Planning Agent gets `NativeOutput`. Worker agents continue using their current output configurations.
- **Streaming planning progress** — deferred. Non-streaming is acceptable for v1. Blocked by PydanticAI #3393 (ModelRetry + run_stream crash).
- **`PlanningRefusalError`** — add only if `stop_reason="refusal"` observed in staging.
