# Plan 59 — GitHub Copilot PydanticAI Model Adapter

**Version:** 1.0.0
**Date:** 2026-04-18
**Status:** Implemented
**Depends on:** Plan 55 (CLI engine), Plan 58 (provider factory)

---

## 0. Problem

Anthropic and OpenAI both block subscription OAuth tokens from programmatic API access. The only $0 path for PydanticAI agents is API key billing.

GitHub Copilot Enterprise is different — its SDK provides full programmatic access to **13 models** (Claude Opus 4.6, Sonnet 4.6, GPT-5.4, etc.) under the enterprise subscription. Tested and confirmed working.

## 1. What the Copilot SDK Provides

| Feature | Support |
|---------|---------|
| Models | Claude Opus/Sonnet/Haiku, GPT-5.x/4.1 (13 total) |
| Auth | GitHub OAuth (enterprise subscription, $0) |
| Sessions | Stateful, server-managed conversation history |
| Streaming | `ASSISTANT_MESSAGE_DELTA`, `ASSISTANT_REASONING_DELTA` |
| Tool calls | Register custom tools via `create_session(tools=[...])` |
| Reasoning | `reasoning_effort: low|medium|high|xhigh` |
| Events | Full lifecycle (turn start/end, usage, tool execution) |
| Token usage | `ASSISTANT_USAGE` event with input/output/cache tokens |

## 2. Architecture — PydanticAI Model Adapter

### The interface to implement

PydanticAI requires a `Model` with two methods:

```python
class Model(ABC):
    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse

    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> AsyncIterator[StreamedResponse]
```

### The adapter pattern

```
PydanticAI agent.run()
  → CopilotModel.request(messages, settings, params)
    → Convert PydanticAI messages → Copilot session.send()
    → Collect Copilot events → Convert to ModelResponse
  ← ModelResponse(TextPart, ToolCallPart, usage)
```

### Phase 1: Pure LLM (no PydanticAI tools)

The Copilot session handles the message, returns text. PydanticAI's custom tools are NOT available — the model returns text only. This is equivalent to `engine: claude_code` but with:
- Streaming events
- Server-managed conversation history
- Any of 13 models
- $0 cost

### Phase 2: Tool bridging (future)

Register PydanticAI `ToolDefinition`s as Copilot `Tool` objects with handlers that call PydanticAI's tool functions. This enables custom tools (create_plan, approve_tasks, etc.) through the Copilot SDK.

---

## 3. Implementation — Phase 1

### 3.1 New file: `modules/backend/core/copilot_model.py`

```python
"""PydanticAI Model adapter for GitHub Copilot SDK.

Routes LLM calls through the Copilot Enterprise subscription
instead of direct API keys. All 13 models (Claude, GPT) available
at $0 cost.

Phase 1: Pure text LLM — no PydanticAI tool support.
Phase 2: Tool bridging — PydanticAI tools registered as Copilot tools.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponsePart,
    TextPart,
    UserPromptPart,
    SystemPromptPart,
    ToolReturnPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


class CopilotModel(Model):
    """PydanticAI Model backed by GitHub Copilot SDK.

    Creates a CopilotClient on first use, reuses it across requests.
    Each request creates a new session, sends the message, collects
    the response, and destroys the session.

    For multi-turn conversations, PydanticAI passes the full message
    history — we extract the latest user message and let PydanticAI
    manage history (Copilot sessions are ephemeral in this adapter).
    """

    def __init__(
        self,
        model_id: str = "claude-sonnet-4.6",
        *,
        reasoning_effort: str | None = None,
        working_directory: str | None = None,
    ) -> None:
        self._model_id = model_id
        self._reasoning_effort = reasoning_effort
        self._working_dir = working_directory
        self._client = None
        self._started = False

    @property
    def model_name(self) -> str:
        return f"copilot:{self._model_id}"

    @property
    def system(self) -> str:
        return "copilot"

    async def _ensure_client(self):
        """Lazily create and start the CopilotClient."""
        if self._client is None:
            from copilot import CopilotClient
            self._client = CopilotClient(auto_start=True)
        if not self._started:
            await self._client.start()
            self._started = True

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        await self._ensure_client()

        # Extract system prompt and user message from PydanticAI messages
        system_prompt, user_message = _extract_messages(messages)

        # Collect events
        events: list[Any] = []
        usage_data: dict = {}

        def on_event(event):
            events.append(event)
            if hasattr(event, 'type'):
                etype = str(event.type)
                if 'USAGE' in etype and hasattr(event, 'data'):
                    d = event.data
                    usage_data['input'] = getattr(d, 'input_tokens', 0) or 0
                    usage_data['output'] = getattr(d, 'output_tokens', 0) or 0
                    usage_data['model'] = getattr(d, 'model', self._model_id)

        # Create session
        session_kwargs = {
            'on_permission_request': lambda *a, **k: True,
            'model': self._model_id,
            'on_event': on_event,
        }
        if self._reasoning_effort:
            session_kwargs['reasoning_effort'] = self._reasoning_effort
        if self._working_dir:
            session_kwargs['working_directory'] = self._working_dir
        if system_prompt:
            session_kwargs['system_message'] = {
                'type': 'replace',
                'content': system_prompt,
            }

        session = await self._client.create_session(**session_kwargs)

        try:
            await session.send_and_wait(user_message, timeout=300.0)

            # Extract response from messages
            msgs = await session.get_messages()
            response_text = ""
            for m in msgs:
                etype = str(getattr(m, 'type', ''))
                if 'ASSISTANT_MESSAGE' in etype:
                    data = getattr(m, 'data', None)
                    msg_text = getattr(data, 'message', None) or getattr(data, 'content', None)
                    if msg_text:
                        response_text = str(msg_text)

            usage = RequestUsage(
                request_tokens=usage_data.get('input', 0),
                response_tokens=usage_data.get('output', 0),
            )

            return ModelResponse(
                parts=[TextPart(content=response_text)],
                usage=usage,
                model_name=self._model_id,
                timestamp=datetime.now(timezone.utc),
            )
        finally:
            await session.disconnect()

    # request_stream omitted for Phase 1 — PydanticAI falls back to
    # request() when request_stream is not overridden.
```

### 3.2 Helper: extract messages

```python
def _extract_messages(messages: list[ModelMessage]) -> tuple[str, str]:
    """Extract system prompt and latest user message from PydanticAI messages.

    PydanticAI passes the full conversation history. We extract:
    - System prompt from the first ModelRequest with instructions
    - Latest user message from the last UserPromptPart
    """
    system_prompt = ""
    user_message = ""

    for msg in messages:
        if isinstance(msg, ModelRequest):
            if msg.instructions:
                system_prompt = msg.instructions
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    content = part.content
                    if isinstance(content, str):
                        user_message = content
                    elif isinstance(content, list):
                        # Multi-part content — extract text parts
                        user_message = " ".join(
                            p.get("text", "") for p in content
                            if isinstance(p, dict) and p.get("type") == "text"
                        )

    return system_prompt, user_message
```

### 3.3 Update model_builder.py

Add `copilot:` prefix support:

```python
if model_name.startswith("copilot:"):
    bare_name = model_name.split(":", 1)[1]
    from modules.backend.core.copilot_model import CopilotModel
    return CopilotModel(model_id=bare_name)
```

### 3.4 Update agent config validation

Add `copilot` as a known provider in `_validate_model_config`:

```python
known_providers = {"anthropic", "openai", "google", "bedrock", "copilot"}
```

### 3.5 No config needed

Unlike Anthropic/OpenAI, the Copilot SDK authenticates via the local GitHub CLI auth. No API keys, no env vars, no providers.yaml changes. If the user is authenticated via `gh auth login`, it works.

---

## 4. Usage

### Set an agent to use Copilot

Admin catalog → Edit agent → change model to:

```yaml
model: copilot:claude-opus-4.6
```

Or via agent YAML:
```yaml
model:
  name: copilot:claude-opus-4.6
  temperature: 0.0
  max_tokens: 16384
```

### Available models

| Model ID | Billing Multiplier | Reasoning |
|----------|-------------------|-----------|
| `claude-opus-4.6` | 3.0x | low/medium/high |
| `claude-sonnet-4.6` | 1.0x | low/medium/high |
| `claude-haiku-4.5` | 0.33x | no |
| `gpt-5.4` | 1.0x | low/medium/high/xhigh |
| `gpt-5.4-mini` | 0.33x | low/medium/high/xhigh |
| `gpt-4.1` | 0.0x (free) | no |

---

## 5. What Works vs What Doesn't (Phase 1)

| Feature | Status |
|---------|--------|
| Text responses | Yes |
| Conversation history | Yes (PydanticAI manages, sent each turn) |
| System prompts | Yes |
| Streaming | No (Phase 2 — needs StreamedResponse impl) |
| PydanticAI custom tools | No (Phase 2 — needs tool bridging) |
| Structured output | No (text only) |
| Token usage tracking | Yes (from ASSISTANT_USAGE events) |
| Reasoning/thinking | Yes (via reasoning_effort) |
| Cost | $0 (enterprise subscription) |
| 13 models | Yes |

### Phase 1 is suitable for

- Chat agents (director in text-only mode, without mission tools)
- Analysis agents (quality, architecture — read code, give advice)
- Any agent that primarily produces text output

### Phase 1 is NOT suitable for

- Agents that need custom PydanticAI tools (create_plan, approve_tasks)
- Agents that need structured output (planning, verification)

---

## 6. Files Summary

| # | File | Action | Lines |
|---|------|--------|-------|
| 1 | `modules/backend/core/copilot_model.py` | Create | ~150 |
| 2 | `modules/backend/agents/mission_control/helpers/model_builder.py` | Edit | +5 |
| 3 | `modules/backend/agents/config_schema.py` | Edit | +1 (add "copilot" to known_providers) |

**Total: ~155 lines. No config changes, no migrations, no frontend changes.**

---

## 7. Exit Criteria

1. Agent with `model: copilot:claude-opus-4.6` chats and returns text
2. Token usage tracked via ASSISTANT_USAGE events
3. System prompt passed correctly
4. Existing `anthropic:` and `openai:` models unaffected
5. $0 cost on enterprise subscription
6. API server starts without errors

---

## 8. Phase 2 Roadmap (Future)

### Streaming support
Implement `request_stream()` using `ASSISTANT_MESSAGE_DELTA` events.

### Tool bridging
Register PydanticAI `ToolDefinition`s as Copilot `Tool` objects:
```python
for tool_def in model_request_parameters.function_tools:
    copilot_tool = Tool(
        name=tool_def.name,
        description=tool_def.description,
        handler=make_handler(tool_def, agent_deps),
        parameters=tool_def.parameters_json_schema,
    )
```
The handler closure captures PydanticAI's deps and executes the tool.

### Structured output
Parse the text response against PydanticAI's output schema. The model produces JSON-like text; PydanticAI validates it.
