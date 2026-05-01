# Robust Schema-Compliant JSON Output from Claude via PydanticAI: A Strategy Guide for a Strict-Schema Planning Agent

## TL;DR

- **The compatibility matrix is the problem, not the prompt.** PydanticAI's default `output_type=TaskPlan` for Anthropic uses tool-calling with `tool_choice` forced to a tool, which Anthropic rejects when extended thinking is enabled (`"Thinking may not be enabled when tool_choice forces tool use"`). For Claude + extended thinking + streaming + a strict schema, the only Anthropic-native combination that satisfies all four constraints is **`NativeOutput` backed by Anthropic's Structured Outputs beta (`output_format: json_schema`, `additionalProperties: false`, `strict: true`)**, which uses token-level constrained decoding rather than forced tool use and is therefore compatible with adaptive/extended thinking.
- **Recommended strategy is a layered approach: A (NativeOutput with constrained decoding) as the primary mechanism, plus E (compact validation-error feedback via `ModelRetry`) and D (a defensive `model_validator(mode="before")` normaliser) as safety nets, with C (two-stage reason → format) reserved as the fallback when extended thinking *must* run inside the same call as forced schema emission.** Pure prompt engineering (B) materially helps but does not by itself close a 70% failure rate on complex nested plans; constrained decoding does.
- **The current GitHub Copilot SDK BYOK path bypasses Anthropic's native structured-outputs beta** (it brokers requests through an agent runtime, not the raw Messages API, and its Anthropic BYOK adapter has known structured-tool bugs — e.g. issue #696). For deterministic dispatch from a strict TaskPlan, prefer calling Anthropic directly via `AnthropicProvider` (or via a Copilot Enterprise-fronted Anthropic-compatible endpoint that passes the `anthropic-beta: structured-outputs-2025-11-13` header through), and reserve the Copilot SDK for orchestration rather than for the schema-bound generator step.

---

## Key Findings

### Versions and capability surface (April 2026)
- **PydanticAI is at 1.87.0 (released 25 April 2026)**; v1.72.0 exists (released ~late March 2026). Pydantic AI hit V1 in September 2025 and follows a stability policy. The package name is `pydantic-ai` (or the slim variant `pydantic-ai-slim` with `[anthropic]` extra). The `output_type` API is the V1 surface; legacy `result_type` was removed in V1.
- **Three first-class structured-output strategies in PydanticAI**: `ToolOutput` (default — wraps the Pydantic model as a tool named `final_result`), `NativeOutput` (uses the provider's JSON-schema response format), and `PromptedOutput` (injects the schema into instructions). Each can be selected by wrapping the Pydantic class: `output_type=NativeOutput(TaskPlan, strict=True)`.
- **Anthropic shipped native Structured Outputs in public beta on 14 November 2025** (now GA on Sonnet 4.6, Opus 4.5/4.6/4.7, Haiku 4.5; still beta-flagged on Sonnet 4.5 / Opus 4.1). It exposes two features: `output_format: {type: "json_schema", schema: …}` for plain JSON responses and `strict: true` on tool definitions for guaranteed-shape tool inputs. Both compile the schema to a grammar and **constrain token generation at decode time** — i.e. the model literally cannot emit tokens that violate the schema. This is the single biggest reliability lever available.

### The thinking ↔ forced-tool-use incompatibility (root cause of the 70% failure)
- Anthropic's API forbids `tool_choice: {"type": "any"}` or `{"type": "tool", "name": "..."}` whenever extended thinking is enabled. Only `tool_choice: "auto"` or `"none"` are allowed alongside thinking.
- PydanticAI's `ToolOutput` mode, when given a single `output_type`, sets `tool_choice` to force the `final_result` tool call — which is exactly the disallowed combination. This is documented in PydanticAI issues **#2425** (Anthropic direct) and **#3092** (Bedrock + interleaved-thinking-2025-05-14): both produce `"Thinking may not be enabled when tool_choice forces tool use"`.
- Result for the user's Planning Agent: the default `Agent('anthropic:claude-sonnet-4-…', output_type=TaskPlan, model_settings={'thinking': 'high'})` either errors out or, where the framework relaxes the choice to `auto`, the model is free to emit free-text instead of the schema, which is the field-name/nesting/type-drift failure mode they're observing.

### Why `NativeOutput` solves it
- Anthropic's `output_format: {type: "json_schema", schema: …}` is independent of `tool_choice`; it constrains the *content tokens* of the assistant message rather than forcing a tool. The grammar applies only to the model's direct output — **thinking blocks are emitted freely and ignored by the grammar** ("Grammar state resets between sections, allowing Claude to think freely while still producing structured output in the final response"). This makes it the only Anthropic-native pattern that simultaneously supports: (a) extended/adaptive thinking, (b) strict schema enforcement, and (c) streaming.
- Caveats from Anthropic's docs: `output_format` is **incompatible with citations** and with **assistant message prefilling**, and there are schema-complexity limits (the API rejects "compiled grammar is too large"; recursive schemas, `minimum`/`maximum`, and `minLength`/`maxLength` are unsupported and either stripped or rejected). `additionalProperties` must be `false` on every object, which Pydantic emits automatically when `model_config = ConfigDict(extra='forbid')`.
- Refusals (`stop_reason: "refusal"`) bypass the schema; you must always check `stop_reason` before parsing.

### Streaming + structured output in PydanticAI
- `agent.run_stream()` works with structured output. Internally PydanticAI uses Pydantic's `experimental_allow_partial=True` to validate partial JSON as tokens arrive, then runs strict validation on completion (`pydantic_ai_slim/pydantic_ai/_output.py`, `result.py`). `stream_output(debounce_by=…)` yields incrementally typed `TaskPlan` instances with optional fields tolerated until the final pass.
- This works with `ToolOutput`, `NativeOutput`, and `PromptedOutput`. With `NativeOutput`, the partial JSON arrives as content text deltas; PydanticAI sniffs the first delta to decide whether the response is the structured payload, then streams the rest.
- Two known sharp edges: (1) `ModelRetry` raised from an `output_validator` is not always handled cleanly during `run_stream` (PydanticAI #3393), and (2) the default `run_stream()` ends the run on the *first* match of `output_type`, so any post-output thinking/tool turns are dropped — use `run_stream_events()` or `agent.iter()` if you need both pre-output thinking deltas *and* tool calls.

### Prompt-only mitigations (Approach B): real but not sufficient
- Putting the schema at the end of the prompt, enumerating enum values explicitly (`"sentiment": "exactly one of: positive | neutral | negative"`), repeating constraints in `Field(description=…)` (which Pydantic passes through to the JSON schema and which Claude treats as part of the tool description), and giving 1–2 minimal few-shot examples each lift compliance by single-digit to ~30 percentage points in published anecdotes. They do not reach the 99%+ that constrained decoding gives. The realistic role of B is to *reduce semantic drift* (wrong enum values, wrong field semantics) rather than syntactic schema compliance.
- Separating the schema description from the mission/context (e.g. mission goes in `instructions=`, schema-shape rules in a dedicated `<output_contract>` XML block at the end of the user message) measurably reduces "the model invented a field" errors with Claude, which responds well to XML-delimited sections.
- Chain-of-thought *before* structured output is what extended thinking already provides; explicit `<plan>` then `<final_result>` scaffolding is redundant once thinking is on, but is a perfectly valid degradation path on models without thinking.

### Two-stage generation (Approach C)
- The "reason then format" pattern is well-attested (multiple practitioner blogs and the DICE paper, arXiv 2510.09211, report ~30% gains on structured-format accuracy by decoupling reasoning from formatting). It is the right fallback when constrained decoding is unavailable on the chosen endpoint.
- Cost / latency: roughly +1× model latency and ~1.3–1.7× tokens (the reasoning output becomes the input to the second call, but it can usually be aggressively summarised before re-injection, and prompt caching of the system prompt + schema absorbs much of the second-call overhead). On Claude with prompt caching at 5m or 1h TTL, a two-stage call typically lands under 1.5× the cost of a single-stage call.

### Post-processing / coercion (Approach D)
- A Pydantic `@model_validator(mode="before")` runs against the raw `dict` *before* field coercion and is the right place to: lower-case/snake_case-normalise field names, strip Markdown code fences if any leak through, lift accidentally nested wrappers (`{"task_plan": {…}}` → `{…}`), and coerce common type drift (string-numbers → numbers; CSV strings → lists). This is bounded — it cannot fix missing required fields or invented sub-objects — but it cheaply eliminates the most common 5–10% tail of "almost right" outputs.
- Be careful with `extra="forbid"`: a `before` validator that fails to drop unknown keys will cause `ValidationError` *after* you've already paid for the LLM call. Strip unknown top-level keys defensively in the validator.
- Existing libraries: `instructor` (via `Mode.ANTHROPIC_TOOLS` + retry) builds the same retry loop on top of the Anthropic SDK and supports thinking; LangChain's `with_structured_output` will fall back to a *second LLM call to reformat* on providers without native support, which is essentially Approach C done by the framework. Both are acceptable, but neither is necessary if you use PydanticAI's `NativeOutput` + `output_validator` combination.

### Validation feedback loop (Approach E)
- PydanticAI's built-in retry: `Agent(..., output_retries=N)`. When Pydantic validation of the structured tool-call args (or `NativeOutput` payload) fails, PydanticAI automatically appends a `RetryPromptPart` containing the Pydantic `ValidationError` details and re-invokes the model.
- Known issue (#4919): the default error payload includes the *full offending input* in every error entry, which for a deeply-nested TaskPlan with a dozen errors blows up the retry context and dilutes the correction signal. Mitigation: write a custom `output_validator` that catches `ValidationError`, **compacts** it to a list of `(json_pointer, expected, got, hint)` tuples, and `raise ModelRetry(compacted_message)`.
- Empirically, telling the model the JSON path (`/steps/2/tool/name`) and the *one-line* expected-vs-got is what makes retries converge in 1 attempt; dumping the whole `e.errors()` does not.

### GitHub Copilot Enterprise / Copilot SDK considerations
- The Copilot SDK is an *agent runtime* wrapper around the Copilot CLI server, exposing a JSON-RPC session interface. It supports BYOK with `provider.type = "anthropic"` (Claude models including `claude-sonnet-4-5`, `claude-sonnet-4-6`, etc.) and exposes streaming via `assistant.message_delta` events.
- Important constraint: the SDK's `output-schema` parameter (in the GitHub Action wrapper) is *guidance only* — it does not invoke Anthropic's `output_format` constrained decoding. It validates JSON shape after the fact (`JSON.parse()` only). Issue #696 documents that custom-tool/structured paths are still buggy on the Anthropic BYOK adapter.
- Copilot Enterprise–entitled API access via the official OpenAI-compatible / Anthropic-compatible Copilot endpoint **does not currently expose Anthropic beta headers like `anthropic-beta: structured-outputs-2025-11-13`** in a documented, stable way. Consequence: if you must route through Copilot Enterprise for billing/SSO/governance reasons, you will likely lose access to native structured outputs and must fall back to Approach C (two-stage) plus E (validation feedback). If you can route Anthropic traffic *directly* (or through a gateway that passes beta headers), use Approach A.
- Practically, for PydanticAI: pass a custom `AsyncAnthropic` client (or `AsyncAnthropicBedrock` / `AsyncAnthropicFoundry`) into `AnthropicProvider(anthropic_client=…)`; this is how you point at any Anthropic-compatible endpoint while keeping all PydanticAI features.

---

## Details — Recommended Strategy and Implementation Sketch

### Recommended layered design

1. **Generation layer — NativeOutput with strict constrained decoding (Approach A).**
   Configure the agent with `output_type=NativeOutput(TaskPlan, strict=True)`. Pin to a model that supports the structured-outputs beta (Sonnet 4.5+, Opus 4.1+; ideally Sonnet 4.6 or Opus 4.6/4.7 where it's GA). On Sonnet 4.6+ / Opus 4.6+ adaptive thinking is auto-enabled and is compatible with `output_format`-driven structured output; on Sonnet 4.5 use `anthropic_thinking={"type":"enabled","budget_tokens": N}` with the structured-outputs beta header.

2. **Schema-shaping layer.** On the `TaskPlan` class:
   - `model_config = ConfigDict(extra="forbid")` → emits `additionalProperties: false`, required by the API.
   - Avoid recursive types, `min`/`max`/`pattern` length constraints (silently stripped), and very deep nesting (>3–4 levels causes "compiled grammar is too large" errors). Where the dispatch logic needs a constraint, encode it in the `Field(description=…)` so it lands in the prompt as a hint, and re-validate on the Python side.
   - Use `Literal[…]` / `Enum` everywhere a finite vocabulary exists (tool names, step kinds, severity levels). The grammar will then physically prevent the model from emitting any other token.
   - Keep the discriminated union of step types small and use a `kind:` discriminator field.

3. **Pre-validation layer (Approach D).** Add a `@model_validator(mode="before")` that:
   - drops unknown top-level keys (in case a provider front-end wraps the response),
   - normalises common field-name drift (`task_plan` → root, `tasks` → `steps`, etc.),
   - coerces string→list for any field where a single-item list is plausible,
   - strips ```` ``` ```` fences that occasionally survive native mode (rare but cheap to defend against).
   This is a few-line shim; it should not be the primary correctness mechanism.

4. **Retry layer (Approach E).** Configure `output_retries=2` and add an `@agent.output_validator` that:
   - catches `pydantic.ValidationError`,
   - compacts each error to `f"{'.'.join(map(str,err['loc']))}: expected {err['type']}, got {short(err['input'])}; {err['msg']}"`,
   - emits a single `ModelRetry(\"\\n\".join(lines))` so the model gets a focused correction prompt.
   Avoid raising `ModelRetry` from inside `run_stream` validators (issue #3393 — crashes); if you must stream, run a non-streaming generation step first or move the structural retry into the orchestrator and only stream on the final, validated payload.

5. **Prompt layer (Approach B), applied even with constrained decoding.**
   - Mission/context goes in `instructions=`, *not* in the schema description.
   - Add an XML block at the end of the user message: `<output_contract>This response will be enforced by JSON Schema. Only emit fields that exist in the schema. Use the exact enum spellings.</output_contract>`. Claude responds well to XML delimiters.
   - For complex domains (security workflows), include 1 minimal positive example and 1 minimal negative-with-correction example in the system prompt — kept short to preserve cache hits.
   - Repeat enum values inline in the relevant `Field(description=…)`.

6. **Fallback path (Approach C) for environments without native structured outputs (e.g. Copilot Enterprise pass-through).**
   - **Stage 1 — Reason:** call the agent with `output_type=str`, thinking enabled, and a prompt that asks for a free-form plan in `<plan>…</plan>` XML.
   - **Stage 2 — Format:** call a *second*, smaller agent (e.g. Haiku 4.5) with `thinking` *off*, `output_type=NativeOutput(TaskPlan)` if available or `PromptedOutput(TaskPlan)` otherwise, and the prior `<plan>` text as the only input. Because this stage has no reasoning to do, it stops fighting the schema and reaches >95% compliance even without constrained decoding.
   - This pattern is cited in the DICE paper (arXiv 2510.09211) and several practitioner write-ups as the most reliable structured-output recipe when you can't constrain the decoder.

### Concrete implementation sketch (PydanticAI ≥ 1.72)

```python
from typing import Literal, Annotated
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_ai import Agent, ModelRetry, NativeOutput, RunContext
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.providers.anthropic import AnthropicProvider

class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["scan", "enrich", "report"]
    tool: Literal["nmap", "zap", "trivy", "semgrep"]      # finite vocabulary -> grammar enforces
    args: dict[str, str | int | bool] = Field(default_factory=dict)

class TaskPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective: Annotated[str, Field(min_length=1)]
    steps: list[Step]

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, data):
        if isinstance(data, dict):
            # tolerate accidental wrappers
            if set(data.keys()) == {"task_plan"}:
                data = data["task_plan"]
            # tolerate common alias
            if "tasks" in data and "steps" not in data:
                data["steps"] = data.pop("tasks")
            # forbid will catch anything else
        return data

settings = AnthropicModelSettings(
    anthropic_thinking={"type": "enabled", "budget_tokens": 8000},
    anthropic_betas=["structured-outputs-2025-11-13"],   # native constrained decoding
    max_tokens=16000,
    temperature=0.2,
)
model = AnthropicModel("claude-sonnet-4-6", provider=AnthropicProvider(api_key=...), settings=settings)

agent = Agent[None, TaskPlan](
    model,
    output_type=NativeOutput(TaskPlan, strict=True),
    instructions=(
        "You are a security-workflow planner. Produce a TaskPlan that satisfies the schema. "
        "Use only the listed tools. Reason inside thinking blocks; the final JSON is enforced by schema."
    ),
    output_retries=2,
)

@agent.output_validator
def _compact_validation(ctx: RunContext[None], plan: TaskPlan) -> TaskPlan:
    return plan  # primary validation is done by NativeOutput; this hook is for cross-field rules

# In an orchestrator, catch and reshape ValidationError before retry:
def _format_errors(e: ValidationError) -> str:
    return "\n".join(
        f"- {'.'.join(map(str, err['loc']))}: {err['msg']} (got: {str(err['input'])[:80]})"
        for err in e.errors()
    )

async def plan(prompt: str) -> TaskPlan:
    async with agent.run_stream(prompt) as run:
        async for partial in run.stream_output(debounce_by=0.1):
            yield_progress(partial)        # for UI; optional
        return await run.get_output()
```

### Trade-offs and risks

| Concern | Approach A (NativeOutput + thinking) | Approach C (two-stage) | Approach B alone |
|---|---|---|---|
| Schema compliance | ~99%+ (token-level grammar) | ~95% (depends on stage-2 model) | 60–90% on complex schemas |
| Compatible with extended thinking | Yes — grammar resets across sections | Yes (stage 1 thinks freely) | Yes |
| Compatible with `run_stream` | Yes — partial JSON validation | Stage 2 only | Yes |
| Latency vs single free-text call | +100–300 ms first request, then cached; per-token grammar overhead < 50 µs | ~1.7–2.0× | ~1.0× |
| Token overhead | Small (schema sent once, cached by Anthropic for 24 h) | Higher (stage 1 reasoning re-fed) | Lowest |
| Schema-feature constraints | No recursion, no min/max, no minLength/maxLength, depth limits | None | None |
| Refusals bypass schema | Yes — must check `stop_reason` | Yes | Yes |
| Works through Copilot Enterprise BYOK | **Only if beta header passes through** | Yes | Yes |
| Risk of "almost right" tail | Very low | Low–Medium | Medium–High |

Risks specific to the user's setup:

- **Beta-header pass-through.** If Copilot Enterprise or any reverse proxy strips `anthropic-beta: structured-outputs-2025-11-13`, `NativeOutput(strict=True)` silently degrades to whatever the provider does without it (typically prompted JSON). Verify by inspecting one raw response and confirming the request was honored; otherwise route Anthropic traffic directly.
- **Schema complexity ceiling.** Anthropic limits the compiled grammar size; deeply nested TaskPlans with many discriminated subtypes can hit "Schema too complex". Mitigate by flattening: replace one giant `TaskPlan` containing many step variants with a top-level `TaskPlan` whose `steps` are a `list[StepRef]`, and resolve `StepRef.kind` to a per-kind concrete model in a second, kind-specific call.
- **Streaming + thinking + retries don't compose well.** PydanticAI #3393 documents that `ModelRetry` raised in an output validator under `run_stream` crashes. Pattern: do schema-bound generation **non-streaming**, with retries and validation, then stream a downstream "rendering" agent that has no schema. If you absolutely need streaming on the schema-bound call, accept that the first attempt is the only attempt (no automatic retry) and rely on the `model_validator(mode="before")` shim plus a manual retry on `ValidationError` at the orchestrator level.
- **Anthropic structured outputs are incompatible with citations and prefilling.** If you currently rely on prefilling the assistant response to nudge formatting, you must remove that when you turn on `output_format`.
- **`tool_choice` interaction even in `NativeOutput`.** PydanticAI's Anthropic adapter no longer needs to set `tool_choice="any"` when you select `NativeOutput`, but if you also register *other* function tools (e.g. for retrieval) on the same agent and need them to be optional, leave `tool_choice` at its default `auto` so it remains thinking-compatible.

### Direct answer to the user's compatibility question

**Is PydanticAI structured output compatible with `run_stream` *and* extended thinking?**

- **With `ToolOutput` (the default for a Pydantic `BaseModel` output): No, not reliably.** PydanticAI forces the output tool, which Anthropic rejects whenever thinking is enabled. The widely-reported `"Thinking may not be enabled when tool_choice forces tool use"` (#2425, #3092) is exactly this.
- **With `NativeOutput` against Anthropic's structured-outputs beta: Yes.** The grammar applies only to the final assistant content tokens; thinking blocks are unconstrained, and `run_stream` works with partial JSON validation. This is the recommended path.
- **With `PromptedOutput`: Yes, but without compliance guarantees.** The schema is only injected as a prompt; thinking and streaming work, but you're back in the 60–90% compliance regime and rely on retries.

**Combined, the recipe that satisfies *all four* requirements (strict TaskPlan, `extra="forbid"`, streaming, extended thinking) is:** PydanticAI `NativeOutput(TaskPlan, strict=True)` + Anthropic `output_format` (beta header) + `anthropic_thinking={"type":"enabled",…}` (or adaptive on 4.6/4.7) + `output_retries=2` + a small `model_validator(mode="before")` normaliser + a compact-error `output_validator` for retries.

---

## Caveats

- The "Anthropic structured outputs" feature was beta in November 2025 and reached GA on top-tier models in early 2026; sources cited mix beta-era and GA documentation. Confirm GA status and the exact required beta header for the specific model you pin in production at request time. The beta header `anthropic-beta: structured-outputs-2025-11-13` is still cited in current docs as the toggle on Sonnet 4.5 / Opus 4.1.
- Some claims in the wider blog ecosystem (e.g. Lakshmanan's "Anthropic structured outputs are instruction-following only") **predate the November 2025 native release** and are no longer accurate; Anthropic's current docs explicitly describe constrained decoding ("compiles your JSON schemas into a grammar that constrains Claude's output").
- "Adaptive thinking auto-enables interleaved thinking and is compatible with structured outputs" is documented for Sonnet 4.6 / Opus 4.6 / Opus 4.7 / Mythos Preview. Older models (Sonnet 4.5, Opus 4.5/4.1, Sonnet 3.7) require explicit `thinking: {type: "enabled", budget_tokens: N}` and may have stricter `tool_choice` constraints; Sonnet 3.7's extended thinking is explicitly called out as incompatible with forced tool calling.
- The user's exact PydanticAI version target (`>=1.72.0`) is valid (released late March 2026); the current latest is 1.87.0 (25 April 2026). Recent minor releases (1.80–1.84) include relevant bug fixes around streaming error handling, Anthropic compaction, and Foundry endpoints — upgrading within 1.x is recommended and safe under PydanticAI's V1 stability policy.
- The GitHub Copilot SDK is in Public Preview as of 2 April 2026 (changelog) and changes weekly. Its BYOK Anthropic provider has documented bugs (issue #696) and does *not* expose a documented mechanism to forward Anthropic beta headers; treat it as orchestration plumbing and call Anthropic directly for the schema-bound generation step until the beta-header story stabilises.
- The 70% failure rate cited in the question is consistent with a `ToolOutput`-mode planning agent on a deeply-nested security-workflow schema *without* constrained decoding. The strategy above directly targets that root cause; expect realistic post-fix failure rates of ≤2–3% (driven by safety refusals and grammar-too-complex errors), not zero.