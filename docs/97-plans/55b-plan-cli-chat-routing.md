# Plan 55b — CLI Engine Chat Routing

**Version:** 1.0.0
**Date:** 2026-04-18
**Parent plan:** 55-plan-cli-agent-engine-integration.md
**Status:** Ready to implement
**Problem:** Chat path (`handle()`) always uses PydanticAI regardless of agent's `engine` config. Agents set to `engine: claude_code` still hit the Anthropic API with an API key.

---

## 0. Design Decision

**Strategy Pattern** — not a refactor of `handle()`.

The existing `handle()` function is 440 lines of PydanticAI-specific streaming machinery (event_stream_handler callbacks, incremental persistence, tool call mapping). Refactoring it into an engine-agnostic layer would be a major rewrite with high regression risk.

Instead: **extract CLI chat into a separate async generator** that yields the same `SessionEvent` types, and add a 10-line engine check in `handle()` that delegates to it.

```
handle() (mission_control.py)
  ├── engine == pydantic_ai → existing PydanticAI path (unchanged, 430 lines)
  └── engine != pydantic_ai → yield from _handle_cli_chat() (new module)
```

Both paths:
- Accept the same inputs (session_id, message, mission_id, etc.)
- Yield the same event types in the same order
- Persist messages to the session
- Track costs

**Why this is the right approach:**
- `handle()` is untouched — zero regression risk on the PydanticAI path
- The CLI handler is a self-contained black box — testable in isolation
- Adding a new engine means adding one executor function, not touching `handle()`
- Follows P6: Mission Control is infrastructure, not intelligence — routing is infrastructure

---

## 1. Conversation History for CLI Engines

Claude Code's `query()` does not natively support conversation history. The solution: **serialize previous messages into the prompt as context**.

```python
# Example: history injected into the user message
[Previous conversation]
User: How should I structure the auth module?
Assistant: I recommend a service layer with JWT...
User: What about refresh tokens?
[End previous conversation]

What about refresh tokens?
```

This is standard for CLI agents — they don't have stateful sessions. The context window is large enough (200K+) that recent history fits easily.

---

## 2. New File: `chat_cli_handler.py`

**Path:** `modules/backend/agents/mission_control/chat_cli_handler.py`

A single async generator function that mirrors `handle()`'s event contract.

```python
"""CLI engine chat handler — routes chat messages to CLI agents.

Counterpart to the PydanticAI streaming path in handle().
Yields the same SessionEvent types so callers (SSE, TUI, Telegram)
see identical event streams regardless of engine.

Differences from PydanticAI path:
  - No real-time streaming (MVP limitation §3.7b) — yields complete response
  - Conversation history serialized into the prompt (CLI agents are stateless)
  - cost_usd always 0.0 (subscription-based, no API billing)
"""
```

### Event sequence (matches PydanticAI path):

1. `UserMessageEvent` — user message
2. `AgentThinkingEvent` — agent starting
3. `AgentResponseCompleteEvent` — full response (no chunks — MVP limitation)
4. `CostUpdateEvent` — cost_usd=0.0 (subscription)
5. Persist user + assistant messages to session

### Function signature:

```python
async def handle_cli_chat(
    session_id: str,
    message: str,
    *,
    agent_name: str,
    agent_config: AgentConfigSchema,
    mission_id: str,
    session_service: SessionServiceProtocol,
    event_bus: EventBusProtocol,
    channel: str = "api",
    sender_id: str | None = None,
    db_session: Any | None = None,
) -> AsyncIterator[SessionEvent]:
```

### Implementation:

```python
async def handle_cli_chat(...) -> AsyncIterator[SessionEvent]:
    sid = uuid.UUID(session_id)
    source = "mission_control"

    # 1. Yield UserMessageEvent
    yield UserMessageEvent(session_id=sid, source=source, content=message, channel=channel)

    # 2. Yield AgentThinkingEvent
    yield AgentThinkingEvent(session_id=sid, source=source, agent_id=agent_name)

    # 3. Load conversation history and serialize into prompt
    history_messages, _ = await session_service.get_messages(session_id, limit=50)
    history_text = _serialize_history(history_messages)

    # 4. Load system prompt
    system_prompt = load_agent_system_prompt(agent_name)

    # 5. Build full message with history context
    full_message = message
    if history_text:
        full_message = f"[Previous conversation]\n{history_text}\n[End previous conversation]\n\n{message}"

    # 6. Inject mission context on first turn
    if not history_messages:
        full_message = await _prepend_mission_context(mission_id, full_message)

    # 7. Execute via CLI engine
    engine_fn = {
        "claude_code": execute_claude_code,
        "codex": execute_codex,
        "copilot": execute_copilot,
    }[agent_config.engine]

    engine_kwargs = {
        "agent_name": agent_name,
        "instructions": full_message,
        "inputs": {},
        "system_prompt": system_prompt,
        "working_dir": str(find_project_root()),
        "event_bus": event_bus,
        "session_id": session_id,
    }
    if agent_config.engine == "claude_code":
        if agent_config.effort:
            engine_kwargs["effort"] = agent_config.effort
        engine_kwargs["scope_read"] = agent_config.scope.read
        engine_kwargs["scope_write"] = agent_config.scope.write

    result = await engine_fn(**engine_kwargs)
    output = result.get("output", "")

    # 8. Yield AgentResponseCompleteEvent
    yield AgentResponseCompleteEvent(
        session_id=sid,
        source=source,
        agent_id=agent_name,
        full_content=output,
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        model=f"cli:{agent_config.engine}",
    )

    # 9. Yield CostUpdateEvent (0.0 — subscription)
    session = await session_service.get_session(session_id)
    yield CostUpdateEvent(
        session_id=sid,
        source=source,
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        cumulative_cost_usd=session.total_cost_usd,
        budget_remaining_usd=(session.cost_budget_usd or 0) - (session.total_cost_usd or 0),
        model=f"cli:{agent_config.engine}",
    )

    # 10. Persist messages
    await _persist_messages(
        session_service, session_id,
        user_message=message, assistant_message=output,
        agent_name=agent_name, sender_id=sender_id,
    )
```

### History serializer:

```python
def _serialize_history(messages: list) -> str:
    """Serialize session messages into a text block for CLI agent context."""
    lines = []
    for msg in messages:
        role = getattr(msg, "role", "user")
        content = getattr(msg, "content", "")
        if role == "user":
            lines.append(f"User: {content}")
        elif role == "assistant":
            lines.append(f"Assistant: {content}")
    return "\n".join(lines)
```

---

## 3. Modify `handle()` — Engine Check (10 lines)

**File:** `modules/backend/agents/mission_control/mission_control.py`

**Location:** After line 193 (where `agent_config` is resolved via `get_registry().get(agent_name)`), before the budget enforcement.

Insert:

```python
        # ── Engine routing (Plan 55b) ────────────────────────────
        engine = getattr(agent_config, "engine", "pydantic_ai")
        if engine != "pydantic_ai":
            from modules.backend.agents.mission_control.chat_cli_handler import handle_cli_chat
            async for event in handle_cli_chat(
                session_id, message,
                agent_name=agent_name,
                agent_config=agent_config,
                mission_id=mission_id,
                session_service=session_service,
                event_bus=event_bus,
                channel=channel,
                sender_id=sender_id,
                db_session=db_session,
            ):
                yield event
                await _publish(event_bus, event)
            return
```

**Important:** This goes AFTER `agent_config` is resolved (line 193) but BEFORE `_build_model()` (line 237). The PydanticAI model/agent construction is skipped entirely for CLI engines.

**Budget enforcement:** The CLI path reports `cost_usd=0.0`, so budget enforcement is technically unnecessary. But to keep the contract consistent, `handle_cli_chat` should still call `session_service.enforce_budget()` before executing. This ensures budget-exhausted sessions are properly blocked even for free engines.

---

## 4. Files Summary

| # | File | Action | Lines |
|---|------|--------|-------|
| 1 | `modules/backend/agents/mission_control/chat_cli_handler.py` | Create | ~120 |
| 2 | `modules/backend/agents/mission_control/mission_control.py` | Edit | +15 (engine check) |

---

## 5. What NOT to Do

- Do NOT refactor `handle()` into an engine-agnostic layer (too much scope, high regression risk)
- Do NOT add streaming support for CLI engines (documented MVP limitation §3.7b)
- Do NOT modify the PydanticAI execution path in any way
- Do NOT change the `SessionEvent` types or their contracts
- Do NOT pass `model_history` (PydanticAI format) to CLI engines — use serialized text

---

## 6. Verification

1. Chat with a `pydantic_ai` agent — works exactly as before (regression test)
2. Chat with a `claude_code` agent — response comes from Claude Code subscription ($0 cost)
3. Conversation history is present in subsequent turns (serialized into prompt)
4. Events in SSE stream: UserMessage → Thinking → Complete → Cost (no chunks — expected)
5. Messages persisted to session (visible in chat history on page reload)

---

## 7. Known Limitations (MVP)

1. **No real-time streaming** — CLI engines return complete response, no chunks
2. **No tool call events** — CLI tools are invisible to the event stream
3. **History serialization** — full conversation is re-sent each turn (token-expensive for long chats, but fine for 200K+ context windows)
4. **No incremental persistence** — response persisted after completion, not during (risk of data loss on crash mid-response)

These are acceptable for MVP. Plan 55 Phase 2 can add Claude Code SDK streaming event mapping.
