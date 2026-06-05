# Copilot SDK Integration — Complete Handoff

A self-contained explanation of how Mission Control runs PydanticAI agents through the GitHub Copilot Enterprise SDK. All code referenced is inlined — you do not need to read other files to understand the integration.

---

## 0. Disambiguation — there are two "copilots" in this codebase

| Concept | What it is | Where |
|---|---|---|
| **CopilotModel** *(this doc)* | A PydanticAI `Model` adapter wrapping the `github-copilot-sdk` Python package. Every agent with `engine: pydantic_ai` (the default) and a `copilot:...` model name runs through this. | `modules/backend/core/copilot_model.py` |
| **`copilot` engine** *(different thing)* | Subprocess shelling out to the `copilot -p` CLI binary. Only used by agents that explicitly set `engine: copilot` in their YAML. Rare. | `modules/backend/agents/mission_control/helpers/cli_executor.py` |

Everything below is about **CopilotModel**.

---

## 1. Why route through Copilot at all

We have a GitHub Copilot Enterprise subscription. The `github-copilot-sdk` Python package lets us call Copilot's hosted models (Claude Opus/Sonnet/Haiku, GPT-4.1, etc.) at **$0 marginal cost** — Anthropic API keys are not in play for production traffic.

Anthropic, OpenAI, and Azure Foundry adapters still exist for A/B work or future fallback, but `models.yaml` aliases all point at `copilot:` today:

```yaml
# config/settings/models.yaml
aliases:
  quick:         "copilot:claude-haiku-4.5"
  moderate:      "copilot:claude-sonnet-4.6"
  comprehensive: "copilot:claude-opus-4.6"

registry:
  copilot:
    - claude-opus-4.6
    - claude-sonnet-4.6
    - claude-haiku-4.5
```

Individual agents declare a model in their YAML:

```yaml
# config/agents/platform/director/agent.yaml
model:
  name: "copilot:claude-opus-4.6"
  temperature: 1.0
```

The `agent_catalog` DB table is authoritative at runtime — YAML is seed-only. To change a model live, use `python admin.py catalog ...`, not YAML edits.

---

## 2. The dispatch chain

When an agent runs:

1. `_make_agent_executor` loads the agent's config from the registry.
2. `_build_model(agent_config.model)` inspects the prefix and constructs the right PydanticAI `Model`.
3. The agent module's `create_agent(model, tool_names=...)` builds a normal `pydantic_ai.Agent` instance backed by that model.
4. PydanticAI then talks to the model via the standard `Model.request()` / `Model.request_stream()` interface — which `CopilotModel` implements.

So **agent code itself doesn't know about Copilot**. Each agent just sees a PydanticAI `Model`. The adapter is the only thing that imports from the `copilot` SDK package.

The dispatcher:

```python
# modules/backend/core/model_builder.py

def _build_model(config_model: str | AgentModelSchema) -> Model:
    """Construct a PydanticAI Model from config string, alias, or AgentModelSchema."""
    if isinstance(config_model, AgentModelSchema):
        model_name = config_model.name
    else:
        model_name = config_model

    model_name = _resolve_model_alias(model_name)

    if model_name.startswith("anthropic:"):
        bare_name = model_name.split(":", 1)[1]
        from modules.backend.core.model_providers import get_anthropic_provider
        provider = get_anthropic_provider()
        return AnthropicModel(bare_name, provider=provider)

    if model_name.startswith("openai:"):
        bare_name = model_name.split(":", 1)[1]
        from pydantic_ai.models.openai import OpenAIModel
        from modules.backend.core.model_providers import get_openai_provider
        provider = get_openai_provider()
        return OpenAIModel(bare_name, provider=provider)

    if model_name.startswith("copilot:"):
        bare_name = model_name.split(":", 1)[1]
        from modules.backend.core.copilot_model import CopilotModel
        return CopilotModel(model_id=bare_name)

    if model_name.startswith("foundry:"):
        bare_name = model_name.split(":", 1)[1]
        from pydantic_ai.models.openai import OpenAIModel
        from modules.backend.core.model_providers import get_foundry_provider
        provider = get_foundry_provider()
        profile = _build_profile(config_model)
        return OpenAIModel(bare_name, provider=provider, profile=profile)

    raise ValidationError(
        f"Unsupported model provider in '{model_name}'. "
        "Expected 'anthropic:...', 'openai:...', 'copilot:...', or 'foundry:...'."
    )
```

`_resolve_model_alias` expands `quick`/`moderate`/`comprehensive` against `models.yaml` and fails loudly on unknown aliases — no silent fallbacks.

---

## 3. CopilotModel internals

`copilot_model.py` exists because three things mismatch between PydanticAI's expectations and the Copilot SDK's protocol.

### Mismatch A: tool execution direction

PydanticAI normally drives the tool loop — it calls the model, gets back a tool-call, executes the tool itself, then re-prompts with the result.

The Copilot SDK inverts this: **Copilot drives the loop**. You register tools as native Copilot `Tool` objects with async handlers. When the LLM emits a tool call, Copilot's runtime fires your handler via `asyncio.ensure_future` and keeps the LLM session waiting for that handler to return.

The bridge between the two:

```python
# modules/backend/core/copilot_model.py

@dataclass
class _ToolBridge:
    """Bridges tool calls between Copilot and PydanticAI.

    Flow:
      1. LLM calls tool → Copilot fires handler via ensure_future
      2. Handler puts ToolInvocation on pending_calls queue
      3. Handler awaits a Future in results dict
      4. CopilotModel.request() reads pending_calls → returns ToolCallPart
      5. PydanticAI executes tool → calls request() with ToolReturnPart
      6. request() resolves the Future with the tool result
      7. Handler unblocks → returns ToolResult to Copilot
      8. LLM gets the result and continues
    """
    pending_calls: asyncio.Queue = field(default_factory=asyncio.Queue)
    results: dict[str, asyncio.Future] = field(default_factory=dict)


def _make_copilot_tools(
    function_tools: list[ToolDefinition],
    output_tool_names: set[str],
    bridge: _ToolBridge,
) -> list[Any]:
    """Convert PydanticAI ToolDefinitions to native Copilot Tools."""
    from copilot.tools import Tool, ToolInvocation, ToolResult

    tools: list[Tool] = []

    for tool_def in function_tools:
        is_output_tool = tool_def.name in output_tool_names

        async def handler(
            invocation: ToolInvocation,
            _bridge: _ToolBridge = bridge,
            _is_output: bool = is_output_tool,
        ) -> ToolResult:
            if _is_output:
                # Output sentinel (final_result) — push to queue so
                # CopilotModel.request returns the ToolCallPart to PydanticAI
                # (which captures args as typed output and terminates).
                # No tool return will come back; do not await a Future.
                await _bridge.pending_calls.put(invocation)
                return ToolResult(
                    text_result_for_llm="OK",
                    result_type="success",
                    error=None,
                )

            # Function tool — round-trip via PydanticAI execution.
            loop = asyncio.get_running_loop()
            future: asyncio.Future[str] = loop.create_future()
            _bridge.results[invocation.tool_call_id] = future
            await _bridge.pending_calls.put(invocation)

            try:
                from modules.backend.core.config import get_app_config
                tool_timeout = get_app_config().application.timeouts.tool_bridge
                result_text = await asyncio.wait_for(future, timeout=tool_timeout)
            except asyncio.TimeoutError:
                return ToolResult(
                    text_result_for_llm="Tool execution timed out",
                    result_type="timeout",
                    error="Timed out waiting for tool result",
                )

            return ToolResult(
                text_result_for_llm=str(result_text),
                result_type="success",
                error=None,
            )

        tools.append(Tool(
            name=tool_def.name,
            description=tool_def.description or "",
            handler=handler,
            parameters=tool_def.parameters_json_schema,
            skip_permission=True,
        ))

    return tools
```

The invariant that makes this work: Copilot's v3 protocol launches handlers with `ensure_future`, so the event loop stays free while a handler awaits its Future. If a future SDK version made that a blocking call, this design would deadlock.

### Mismatch B: structured output

The Copilot SDK does **not** support `response_format: json_schema` — there is no native JSON-schema enforcement on the response.

PydanticAI offers two fallback modes for output types:

- **`prompted`** — inject the schema as text into the system prompt, parse the model's free-form reply.
- **`tool`** — create a hidden `final_result` tool whose parameters *are* the output schema. The model "calls" that tool; PydanticAI captures the args as the typed output and ends the run.

We use **`tool` mode** by default. The override happens in `__init__`:

```python
class CopilotModel(Model):
    def __init__(
        self,
        model_id: str = "claude-sonnet-4.6",
        *,
        reasoning_effort: str | None = None,
        working_directory: str | None = None,
        profile: "ModelProfile | None" = None,
    ) -> None:
        from pydantic_ai.profiles import ModelProfile

        # Copilot SDK doesn't support native JSON schema output (response_format),
        # but DOES validate tool-call argument schemas end-to-end (P17). Using
        # 'tool' mode makes PydanticAI create a hidden `final_result` tool whose
        # parameters ARE the output schema — validated by Pydantic on each call.
        self._profile = profile or ModelProfile(
            supports_json_schema_output=False,
            default_structured_output_mode='tool',
        )
        self._model_id = model_id
        self._reasoning_effort = reasoning_effort
        self._working_dir = working_directory
        # Per-turn state (persists across tool round-trips)
        self._active_session: Any = None
        self._tool_bridge: _ToolBridge | None = None
        self._response_text: str = ""
        self._response_ready: asyncio.Event | None = None
        self._usage_data: dict[str, int] = {}
```

**Subtle bit**: `final_result` is an *output tool*, not a function tool. When the model calls it, the run ends — PydanticAI never sends back a `ToolReturnPart`, so the Future would never resolve. That's why the handler short-circuits for output tools (the `if _is_output` branch above).

`_handle_new_turn` merges `params.function_tools + params.output_tools` and marks the output-tool names so the handler knows which branch to take. Forgetting `output_tools` was a real bug — the model would never see `final_result` and would fall back to free-form text.

### Mismatch C: JSON repair for prompted-mode legacy

A few code paths still hit `prompted` mode (older agents, or models without a profile override). The LLM occasionally produces near-valid JSON with trailing commas or missing braces. The repair runs before Pydantic validation:

```python
def _repair_json_in_text(text: str) -> str:
    """Attempt to repair malformed JSON in LLM responses."""
    try:
        from json_repair import repair_json
    except ImportError:
        return text

    import re

    # Find JSON block (possibly wrapped in ```json ... ```)
    json_match = re.search(r"```json\s*([\s\S]*?)```", text)
    if json_match:
        raw_json = json_match.group(1).strip()
        repaired = repair_json(raw_json)
        if repaired != raw_json:
            return text[:json_match.start(1)] + repaired + text[json_match.end(1):]
        return text

    # Try to find a top-level JSON object or array
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        raw_json = text[first_brace:last_brace + 1]
        try:
            json.loads(raw_json)
            return text  # Already valid
        except json.JSONDecodeError:
            repaired = repair_json(raw_json)
            if repaired and repaired != raw_json:
                return text[:first_brace] + repaired + text[last_brace + 1:]

    return text
```

Belt-and-braces — most agents now use tool mode and never hit this.

---

## 4. Session lifecycle

For every `Agent.run()` call:

1. `_ensure_client()` lazily creates a **process-wide `CopilotClient`** (singleton, locked by `asyncio.Lock`). Auto-started once.
2. `_handle_new_turn` builds a fresh session via `client.create_session(...)`.
3. With tools: `send(user_message)`, then loop in `_wait_for_response()` racing tool calls against session completion.
4. Without tools: `send_and_wait(user_message, timeout=300)` — single blocking call.
5. Each turn cleans up via `session.disconnect()`. The client persists across sessions.

### The singleton client

```python
class CopilotModel(Model):
    _client: Any = None
    _started: bool = False
    _lock: asyncio.Lock | None = None

    async def _ensure_client(self) -> None:
        if CopilotModel._lock is None:
            CopilotModel._lock = asyncio.Lock()
        async with CopilotModel._lock:
            if CopilotModel._client is None:
                try:
                    from copilot import CopilotClient
                except ImportError:
                    raise ImportError(
                        "github-copilot-sdk is required for copilot: models. "
                        "Install with: pip install github-copilot-sdk"
                    )
                CopilotModel._client = CopilotClient(auto_start=True)
            if not CopilotModel._started:
                await CopilotModel._client.start()
                CopilotModel._started = True
```

### The main request method

```python
async def request(
    self,
    messages: list[ModelMessage],
    model_settings: ModelSettings | None,
    model_request_parameters: ModelRequestParameters,
) -> ModelResponse:
    # Resolve output_mode (auto → prompted/tool), merge settings, inject
    # schema into instructions. Must happen before _handle_new_turn reads
    # the messages — the prompted output schema is appended to the
    # instructions field by PydanticAI's base prepare_request.
    model_settings, model_request_parameters = self.prepare_request(
        model_settings, model_request_parameters,
    )

    await self._ensure_client()

    # Tool return continuation?
    tool_returns = _has_tool_returns(messages)
    if tool_returns and self._active_session and self._tool_bridge:
        return await self._handle_tool_return(tool_returns)

    # New turn
    return await self._handle_new_turn(messages, model_request_parameters)
```

### Building a session — note the identity sections API

```python
async def _handle_new_turn(
    self,
    messages: list[ModelMessage],
    params: ModelRequestParameters,
) -> ModelResponse:
    _, user_message = _extract_messages(messages)
    if not user_message:
        return self._empty_response()

    # Use PydanticAI's _get_instructions which appends the prompted
    # output schema (JSON schema instructions) to the base instructions.
    system_prompt = self._get_instructions(messages, params) or ""

    # Reset turn state
    self._response_text = ""
    self._response_ready = asyncio.Event()
    self._usage_data = {}

    # Merge function tools + output tools (final_result for structured
    # output in 'tool' mode). Without output_tools, the model never sees
    # final_result and falls back to prompted text.
    all_tools = list(params.function_tools or [])
    output_tool_names: set[str] = set()
    if params.output_tools:
        all_tools.extend(params.output_tools)
        output_tool_names = {t.name for t in params.output_tools}
    has_tools = bool(all_tools)

    if has_tools:
        self._tool_bridge = _ToolBridge()
        copilot_tools = _make_copilot_tools(
            all_tools, output_tool_names, self._tool_bridge,
        )
    else:
        self._tool_bridge = None
        copilot_tools = None

    # Build session
    session_kwargs: dict[str, Any] = {
        "on_permission_request": lambda *a, **k: True,
        "model": self._model_id,
        "on_event": self._on_event,
    }
    if copilot_tools:
        session_kwargs["tools"] = copilot_tools
    if self._reasoning_effort:
        session_kwargs["reasoning_effort"] = self._reasoning_effort
    if self._working_dir:
        session_kwargs["working_directory"] = self._working_dir
    if system_prompt:
        # Use the sections API (public preview, April 2026) to fully
        # replace the Copilot CLI's default identity. The old top-level
        # "type": "replace" format is ignored by newer SDK versions,
        # leaving the default "I'm GitHub Copilot CLI" identity.
        session_kwargs["system_message"] = {
            "mode": "customize",
            "sections": {
                "identity": {"action": "replace", "content": system_prompt},
            },
        }

    self._active_session = await CopilotModel._client.create_session(
        **session_kwargs,
    )

    if not has_tools:
        return await self._simple_request(user_message)

    # Has tools — use send + wait for tool calls or completion
    await self._active_session.send(user_message)
    return await self._wait_for_response()
```

**Identity replacement matters**: the sections API is the only form that works on current SDK versions. The older top-level `{"type": "replace", ...}` form is silently ignored, leaving Copilot's default "I'm GitHub Copilot CLI" identity in place. If you see agents introducing themselves as the Copilot CLI, this is why.

### Event handling

```python
def _on_event(self, event: Any) -> None:
    etype = str(getattr(event, "type", ""))

    if "USAGE" in etype and hasattr(event, "data"):
        d = event.data
        self._usage_data["input"] = getattr(d, "input_tokens", 0) or 0
        self._usage_data["output"] = getattr(d, "output_tokens", 0) or 0

    elif "ASSISTANT_MESSAGE" in etype and "DELTA" not in etype:
        data = getattr(event, "data", None)
        text = getattr(data, "message", None) or getattr(data, "content", None)
        if text:
            self._response_text = str(text)

    elif "SESSION_IDLE" in etype or "SESSION_ERROR" in etype:
        if self._response_ready:
            self._response_ready.set()
```

### The race loop

```python
async def _wait_for_response(self) -> ModelResponse:
    """Race between a tool call from the bridge and session completion."""
    tool_task = asyncio.ensure_future(self._tool_bridge.pending_calls.get())
    idle_task = asyncio.ensure_future(self._response_ready.wait())

    try:
        done, pending = await asyncio.wait(
            {tool_task, idle_task},
            timeout=300.0,
            return_when=asyncio.FIRST_COMPLETED,
        )
    except Exception:
        tool_task.cancel()
        idle_task.cancel()
        raise

    for t in pending:
        t.cancel()

    if not done:
        await self._cleanup_session()
        return self._empty_response()

    if tool_task in done:
        # Tool call — return to PydanticAI for execution
        invocation = tool_task.result()
        args = invocation.arguments
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (json.JSONDecodeError, TypeError):
                args = {"raw": args}

        return ModelResponse(
            parts=[ToolCallPart(
                tool_name=invocation.tool_name,
                args=args,
                tool_call_id=invocation.tool_call_id,
            )],
            usage=RequestUsage(),
            model_name=self._model_id,
            timestamp=datetime.now(timezone.utc),
        )

    # Session idle — final response
    response = self._extract_final_response()
    await self._cleanup_session()
    return response
```

### Resolving futures when PydanticAI returns tool results

```python
async def _handle_tool_return(self, tool_returns: list[ToolReturnPart]) -> ModelResponse:
    """PydanticAI executed tools — resolve the Futures so handlers unblock."""
    for part in tool_returns:
        future = self._tool_bridge.results.pop(part.tool_call_id, None)
        if future and not future.done():
            future.set_result(part.model_response_str())

    # Wait for next tool call or final response
    self._response_ready.clear()
    return await self._wait_for_response()
```

---

## 5. Streaming

CopilotModel does **not** have real token streaming. `send_and_wait` returns the full response. To satisfy PydanticAI's `request_stream` contract (used when `event_stream_handler` is passed to `agent.run`), we wrap the completed `ModelResponse` and yield it as one chunk:

```python
@dataclass
class CopilotStreamedResponse(StreamedResponse):
    """Wraps a completed ModelResponse as a single-chunk stream."""

    _model_response: ModelResponse = field(default=None)
    _model_id: str = ""
    _timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def model_name(self) -> str:
        return f"copilot:{self._model_id}"

    @property
    def provider_name(self) -> str:
        return "copilot"

    async def _get_event_iterator(self) -> AsyncIterator[ModelResponseStreamEvent]:
        for part in self._model_response.parts:
            event = self._parts_manager.handle_part(
                vendor_part_id=None,
                part=part,
            )
            yield event
        self._usage = self._model_response.usage


# Called from request_stream:
@asynccontextmanager
async def request_stream(self, messages, model_settings, model_request_parameters, run_context=None):
    response = await self.request(messages, model_settings, model_request_parameters)
    streamed = CopilotStreamedResponse(
        model_request_parameters=model_request_parameters,
        _model_response=response,
        _model_id=self._model_id,
    )
    streamed._usage = response.usage
    yield streamed
```

UX-wise the user sees the response appear all at once, not token-by-token.

---

## 6. Usage / cost accounting

The `USAGE` event from Copilot carries `input_tokens` / `output_tokens` (captured in `_on_event` above). These attach to the `RequestUsage` on the `ModelResponse`, and `cost_recorder.record_llm_call` records them. Copilot SDK calls cost **$0** in our cost table, but token counts are still useful for budget limits and observability.

Known follow-up: `compute_cost_usd` silently returns `0.0` for unknown models instead of failing fast. Should raise.

---

## 7. End-to-end flow with a structured-output agent

Pulling it all together — what happens when an agent with `output_type=SomeSchema` and one function tool runs:

```
agent.run("do the thing")
  └─> PydanticAI builds ModelRequestParameters with:
        function_tools=[my_tool]
        output_tools=[final_result]   ← schema for SomeSchema as tool args
  └─> CopilotModel.request(messages, settings, params)
        ├─> prepare_request → resolves output_mode='tool'
        ├─> _ensure_client → singleton CopilotClient, started
        └─> _handle_new_turn
              ├─> all_tools = [my_tool, final_result]
              │   output_tool_names = {"final_result"}
              ├─> _make_copilot_tools(...) → [Tool(my_tool), Tool(final_result)]
              │     ↑ final_result handler short-circuits, my_tool handler awaits Future
              ├─> create_session(model=..., tools=[...], system_message={sections})
              ├─> session.send("do the thing")
              └─> _wait_for_response (race)
                    ├─ LLM calls my_tool
                    │   ├─> handler queues ToolInvocation, creates Future, awaits
                    │   ├─> request() returns ToolCallPart to PydanticAI
                    │   ├─> PydanticAI runs my_tool, calls request() with ToolReturnPart
                    │   ├─> _handle_tool_return resolves Future
                    │   ├─> handler unblocks, returns ToolResult to Copilot
                    │   └─> back to race loop
                    └─ LLM calls final_result with structured args
                        ├─> handler queues ToolInvocation, returns "OK" immediately
                        ├─> request() returns ToolCallPart(final_result, args=...)
                        ├─> PydanticAI captures args as SomeSchema, ends run
                        └─> session.disconnect() in cleanup
  └─> agent.run() returns SomeSchema-typed result
```

---

## 8. Things that will bite you

- **Don't add a Copilot/Anthropic provider fallback for "missing model config".** We fail fast on purpose — no silent fallbacks.
- **The CopilotClient is a process-wide singleton.** Don't construct one yourself or close it mid-run. Tests that need to stub it should patch the import inside `_ensure_client`.
- **Tool handlers run inside the Copilot session's task group.** Don't access PydanticAI deps from inside the handler — only the queue/Future. PydanticAI executes the actual tool with deps on its own side.
- **The bridge requires that PydanticAI re-enters `request()` with the `ToolReturnPart` for every function-tool call.** If you ever short-circuit the agent run mid-loop, the Future never resolves and the handler trips the tool-bridge timeout.
- **The `system_message` sections API matters.** Copy-pasting an older `{"type": "replace"}` example will silently no-op. Always use the sections form.
- **`copilot:` model IDs use dots, not hyphens** (`claude-haiku-4.5`, not `claude-haiku-4-5`). Anthropic uses hyphens. The model registry in `models.yaml` reflects this.
- **Output tools must be merged into the tools list.** Forgetting `params.output_tools` means the model never sees `final_result` and structured-output runs silently degrade to free-form text.

---

## 9. TL;DR

CopilotModel is a PydanticAI `Model` subclass that runs an async bridge between PydanticAI's "model returns tool calls, host executes them" loop and the Copilot SDK's "host registers tool handlers, runtime drives the loop" model. Tool mode for structured output, sections-API for identity replacement, singleton client, one fresh session per `agent.run()`. The whole adapter lives in `modules/backend/core/copilot_model.py` (~680 lines).
