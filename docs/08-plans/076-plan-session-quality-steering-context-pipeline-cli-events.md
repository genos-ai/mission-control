# Plan 76: Session Quality — Steering, Context Pipeline, and CLI Event Streaming

**Status:** Pending
**Priority:** Medium
**Dependencies:** Plan 74 (Shared Session Model), Plan 65 (Tool Registry)
**Branch:** `feature/76-session-quality`

---

## Background

This plan captures architectural improvements derived from studying the pi coding agent
SDK (`@earendil-works/pi-coding-agent`). The pi SDK is not used directly (it is
TypeScript; MC is Python), but three of its design patterns are clearly superior to
MC's current equivalents and are worth back-porting.

**What pi does better:**

1. **Mid-stream steering** — inject a message into an already-running agent turn,
   either to redirect it (`steer`) or queue follow-up work (`followUp`). MC has no
   equivalent; a user can only wait for the turn to finish.

2. **Context injection as a transform chain** — each concern (mission brief, team
   roster, task plan) is an independent contributor that appends its slice.
   MC's `_prepend_mission_context()` is a 50-line monolith that does all three
   in one function with no extension point.

3. **Structured event streaming from CLI agents** — pi emits `tool_execution_start`,
   `tool_execution_update`, and `tool_execution_end` events during execution.
   MC's CLI executors (`execute_claude_code`, `execute_codex`, `execute_copilot`)
   are opaque: they run a subprocess and return the final output as a string.
   The frontend sees nothing while a CLI agent is working.

Additionally, **session forking** (branching history to retry dispatch steps) is
worth adding as a fourth improvement enabled by the shared session model from Plan 74.

---

## Problem Statements

### P1 — No mid-stream steering

Once `handle()` calls `agent.run()`, there is no mechanism to inject a message
until the turn completes. Long-running dispatch steps (coding agents, research agents)
can run for minutes. If the user sees a tool call going wrong, or if an approval gate
fires (Plan 75 decision nodes), there is no way to interrupt or redirect the agent
without aborting the entire turn.

### P2 — Monolithic context injection

`_prepend_mission_context()` in
`modules/backend/agents/mission_control/mission_control.py:70` does five things in
one function: loads mission, loads team, formats mission text, formats team text,
prepends to message. Adding a new context slice (e.g. active plan state, workspace
files, recent failures) means editing this function. `chat_cli_handler.py` imports
and calls it directly (line 94), so there are two hard call sites and no extension
point.

### P3 — CLI agents are invisible during execution

`execute_claude_code()` iterates the `query()` async generator from `claude_agent_sdk`
but only collects `TextBlock` content into `response_parts`. Tool call events
(`ToolCallBlock`, `ToolResultBlock`) are silently discarded. The `execute_codex()`
and `execute_copilot()` executors capture only final stdout. The event bus receives
nothing until the subprocess exits. The frontend shows a spinner with no visibility
into what the coding agent is doing.

### P4 — No session checkpoint / retry

When a dispatch step fails mid-run, the only recovery option is to re-run the entire
plan from the beginning. A failed step cannot be retried from its last successful
checkpoint because session history is linear and append-only.

---

## Design

---

### Phase A — Context Injection Transform Pipeline

**Goal:** Replace `_prepend_mission_context()` with a composable, testable
contributor chain that any call site can extend without touching a central function.

#### A.1 — Define `ContextContributor` protocol

**New file:**
`modules/backend/agents/mission_control/context/contributors.py`

```python
from typing import Protocol

class ContextBundle:
    """Mutable accumulator passed through the contributor chain."""
    mission_id: str
    session_id: str
    agent_name: str
    raw_message: str           # original user message, never mutated
    parts: list[str]           # contributors append sections here

class ContextContributor(Protocol):
    async def __call__(self, bundle: ContextBundle) -> None:
        """Append zero or more sections to bundle.parts."""
        ...
```

Contributors are async callables that mutate `bundle.parts`. They never touch
`bundle.raw_message`. The final message is assembled by the runner as
`"\n\n".join(bundle.parts) + "\n\n" + bundle.raw_message`.

#### A.2 — Implement built-in contributors

**New file:**
`modules/backend/agents/mission_control/context/builtin_contributors.py`

Three contributors, each replacing one concern from `_prepend_mission_context()`:

```python
async def mission_context_contributor(bundle: ContextBundle) -> None:
    """Append [Mission Context] block: name, description, brief."""

async def team_context_contributor(bundle: ContextBundle) -> None:
    """Append team roster with capabilities, tools, and scope."""

async def plan_state_contributor(bundle: ContextBundle) -> None:
    """Append active task plan summary if session has a running plan."""
```

#### A.3 — `build_context_message()` replaces `_prepend_mission_context()`

**New file:**
`modules/backend/agents/mission_control/context/__init__.py`

```python
DEFAULT_CONTRIBUTORS: list[ContextContributor] = [
    mission_context_contributor,
    team_context_contributor,
    plan_state_contributor,
]

async def build_context_message(
    mission_id: str,
    session_id: str,
    agent_name: str,
    message: str,
    *,
    contributors: list[ContextContributor] | None = None,
) -> str:
    """Run contributor chain and return the fully assembled context message."""
    bundle = ContextBundle(
        mission_id=mission_id,
        session_id=session_id,
        agent_name=agent_name,
        raw_message=message,
        parts=[],
    )
    for contributor in (contributors or DEFAULT_CONTRIBUTORS):
        try:
            await contributor(bundle)
        except Exception:
            logger.warning("Context contributor failed", extra={"contributor": contributor.__name__})
    if not bundle.parts:
        return message
    return "\n\n".join(bundle.parts) + "\n\n" + message
```

#### A.4 — Replace call sites

- `mission_control.py:278` — replace `_prepend_mission_context(mission_id, message)`
  with `await build_context_message(mission_id, session_id, agent_name, message)`
- `chat_cli_handler.py` — replace its equivalent inline context build with the same call
- Delete `_prepend_mission_context()` from `mission_control.py`

#### A.5 — Tests

`tests/unit/agents/mission_control/context/test_contributors.py`

- Each contributor tested in isolation with a mock `ContextBundle`
- `build_context_message()` tested with a stub contributor list
- Failure in one contributor does not propagate (swallowed with warning)

---

### Phase B — Mid-Stream Steering

**Goal:** Allow a caller to inject a steering message into an in-progress agent turn.
The agent checks for pending steers between tool calls and incorporates the message
before its next LLM response.

#### B.1 — Steering queue per session

The active `handle()` coroutine for a session is already bound to a Redis channel
(the event bus). Add a complementary **inbound steer queue** in Redis:

```
Key: session:steer:{session_id}
Type: Redis List (LPUSH to write, BRPOP to read with timeout 0)
TTL:  5 minutes (auto-expires if not consumed)
```

Only one `handle()` runs per session at a time (enforced by existing budget checks).
The steer queue is consumed by whichever handle() call is currently active.

#### B.2 — `SteerService`

**New file:** `modules/backend/services/steer.py`

```python
class SteerService:
    async def push(self, session_id: str, message: str, mode: Literal["steer", "follow_up"]) -> None:
        """Write a steer message to the session's inbound queue."""

    async def pop_pending(self, session_id: str) -> SteerMessage | None:
        """Non-blocking read — returns None if queue is empty."""

    async def clear(self, session_id: str) -> None:
        """Drain and discard all pending steers (called on handle() exit)."""
```

`SteerMessage` is a dataclass: `{text: str, mode: "steer" | "follow_up", created_at: datetime}`.

#### B.3 — Interruption and re-entry model

PydanticAI's `agent.run()` is a single opaque async call. Exceptions raised inside
event callbacks do not propagate to the caller in a controlled way. The correct
approach is:

1. **Poll the steer queue after each `FunctionToolResultEvent`** in `_stream_handler`
   (same hook point as before), but instead of raising, set a flag.
2. If a steer is found, **cancel the running `asyncio.Task`** that wraps `agent.run()`.
3. Catch the `CancelledError` in `handle()`, extract the partial message history from
   the already-emitted events, then **re-enter `agent.run()`** with the steer text
   prepended to the next user message and `message_history` set to the partial history.

```python
# In handle(), wrap agent.run() in a Task so it can be cancelled:
run_task = asyncio.create_task(_run_agent(...))
steer_check_task = asyncio.create_task(_poll_steer_queue(steer_service, session_id))

done, pending = await asyncio.wait(
    {run_task, steer_check_task}, return_when=asyncio.FIRST_COMPLETED
)

if steer_check_task in done and not run_task.done():
    steer = steer_check_task.result()
    run_task.cancel()
    await asyncio.gather(run_task, return_exceptions=True)
    # Re-enter with steer text as next user message
    message = steer.text
    # loop continues — handle() already loops for follow_up
```

`_poll_steer_queue()` is a coroutine that blocks on BRPOP with a short timeout
(1s), returning the steer message or None on timeout, looping until the run_task
is done.

For `follow_up` mode: steer text is stored in `SteerService` and handled **after**
the current turn completes, as the next iteration of the `handle()` loop. No
cancellation needed.

#### B.4 — New API endpoint

**File:** `modules/backend/api/v1/endpoints/sessions.py`

```
POST /api/v1/sessions/{session_id}/steer
Body: { "message": str, "mode": "steer" | "follow_up" }
Response: 202 Accepted (fire-and-forget; agent picks it up between tool calls)
```

Auth: same session ownership check as other session endpoints.

Guards:
- `handle()` sets Redis key `session:active:{session_id}` (with 10-minute TTL) on
  entry and deletes it on exit. The steer endpoint checks this key and returns 409
  with reason "no active agent turn" if it is absent.
- `SteerService.clear()` is called in `handle()`'s `finally` block, ensuring the
  steer queue is drained even if the turn fails.
- Steer queue max depth: 3 messages. Return 429 if full.

#### B.5 — New event type

**File:** `modules/backend/events/types.py`

```python
class AgentSteerReceivedEvent(SessionEvent):
    type: Literal["agent_steer_received"] = "agent_steer_received"
    text: str
    mode: Literal["steer", "follow_up"]
```

Frontend renders this as a distinct bubble in the chat thread (e.g. "↩ Steering:
…") so the user can see that their mid-stream message was received.

#### B.6 — Tests

`tests/unit/services/test_steer_service.py`
`tests/integration/agents/test_mid_stream_steer.py`

- Steer message pushed while agent is mid-turn gets picked up at next tool boundary
- follow_up mode queues after turn completion, not mid-turn
- Queue expiry and depth limit are enforced

---

### Phase C — CLI Executor Event Streaming

**Goal:** Emit structured `AgentToolCallEvent` and `AgentToolResultEvent` events
to the mission event bus while CLI agents are running, giving the frontend the same
visibility it has for PydanticAI agents.

#### C.1 — Claude Code executor (immediate)

`execute_claude_code()` already iterates the `query()` async generator from
`claude_agent_sdk`. The generator yields typed message objects. Extend the loop to
emit events for each message type:

**File:** `modules/backend/agents/mission_control/helpers/cli_executor.py`

Field names on the existing event types (`AgentToolCallEvent`, `AgentToolResultEvent`,
`AgentResponseChunkEvent`) match [events/types.py](modules/backend/events/types.py#L80).
Note `tool_args` (not `tool_input`) and the required `agent_id` and `tool_call_id` fields.

```python
# Track tool_use_id → tool_name so ToolResultBlock can emit the right name
pending_tool_calls: dict[str, str] = {}  # tool_call_id → tool_name

async for message in query(prompt=user_message, options=options):
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock):
                response_parts.append(block.text)
                if event_bus and session_id:
                    await event_bus.publish(AgentResponseChunkEvent(
                        session_id=session_id,
                        agent_id=agent_name,
                        content=block.text,
                    ))
            elif isinstance(block, ToolUseBlock):
                pending_tool_calls[block.id] = block.name
                if event_bus and session_id:
                    await event_bus.publish(AgentToolCallEvent(
                        session_id=session_id,
                        agent_id=agent_name,
                        tool_name=block.name,
                        tool_args=block.input,
                        tool_call_id=block.id,
                    ))
            elif isinstance(block, ToolResultBlock):
                tool_name = pending_tool_calls.pop(block.tool_use_id, block.tool_use_id)
                if event_bus and session_id:
                    await event_bus.publish(AgentToolResultEvent(
                        session_id=session_id,
                        agent_id=agent_name,
                        tool_name=tool_name,
                        tool_call_id=block.tool_use_id,
                        result=str(block.content),
                        status="error" if block.is_error else "success",
                    ))
```

The `event_bus` and `session_id` are already accepted as parameters by
`execute_claude_code()` but not used — wire them up here.

#### C.2 — Codex and Copilot executors

Both use `_run_subprocess()` which captures stdout only after process exit.
Extend `_run_subprocess()` to support **line-by-line stdout streaming**:

```python
async def _stream_subprocess(
    cmd: list[str],
    *,
    cwd: str,
    on_line: Callable[[str], Awaitable[None]],
    ...
) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    lines = []
    async for line in proc.stdout:
        decoded = line.decode("utf-8", errors="replace").rstrip()
        lines.append(decoded)
        await on_line(decoded)
    await proc.wait()
    return "\n".join(lines)
```

For Codex and Copilot, the stdout is free-form text (not structured events).
Parse line prefixes to emit approximate events:

- Lines starting with `[tool]` or `>` → emit `AgentToolCallEvent` with tool_name
  extracted from the prefix
- Lines starting with `[result]` → emit `AgentToolResultEvent`
- All other lines → accumulate as response text, emit `AgentResponseChunkEvent`

This is a best-effort heuristic. The important thing is that the frontend shows
*something* during a 10-minute Codex run rather than a silent spinner.

#### C.3 — `_cli_result` carries token metadata

Currently `_cli_result()` returns zeros for all token counts. Extend the Claude Code
executor to extract usage from the `claude_agent_sdk` response (it exposes usage on
the final message) and pass it through `_meta`:

```python
return {
    "output": "\n".join(response_parts),
    "_meta": {
        "cost_usd": _compute_sdk_cost(usage),
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "thinking_tokens": getattr(usage, "thinking_tokens", 0),
    },
}
```

This feeds real cost data into the cost dashboard (Plan 60) for CLI-backend agents.

#### C.4 — Tests

`tests/unit/agents/mission_control/helpers/test_cli_executor.py`

- Mock `query()` generator yields `TextBlock`, `ToolUseBlock`, `ToolResultBlock`
- Assert `event_bus.publish` is called with correct event types in sequence
- Codex/Copilot: mock subprocess stdout with sample line prefixes, assert events emitted

---

### Phase D — Session Forking

**Goal:** Allow a dispatch step to be retried from the last successful checkpoint
without replaying the entire session, by forking the session history at a specific
message.

This phase depends on Plan 74's shared session model being fully live.

#### D.1 — Fork tracking at session level (no message-level tree)

The fork is tracked entirely at the session level via two new nullable columns on
`sessions`. There is no `parent_message_id` on `session_messages` — that would be
a separate, more complex in-session branching feature. Session-level pointers are
sufficient for the dispatch retry use case.

History loading for a forked session:
1. Load all messages from `forked_from_session_id` up to and including `forked_from_message_id`
2. Append messages from the new session's own rows
3. This is a UNION query, not a copy — no rows are duplicated

`SessionService.get_messages()` must accept an optional `forked_from` tuple
`(parent_session_id, cutoff_message_id)` and execute the cross-session query.

#### D.2 — `SessionService.fork()`

**File:** `modules/backend/services/session.py`

```python
async def fork(
    self,
    session_id: str,
    from_message_id: str,
    *,
    label: str | None = None,
) -> str:
    """
    Create a new session that shares history up to from_message_id.
    Returns the new session_id. The fork is lightweight: the new session
    points at the same message chain, it does not copy rows.
    """
```

Implementation:
1. Validate `from_message_id` exists in `session_id`
2. Create a new `Session` row with `forked_from_session_id = session_id` and
   `forked_from_message_id = from_message_id`
3. History loading for the new session: load all messages from the original session
   up to (and including) `from_message_id`, then messages from the new session

#### D.3 — `SessionService.branch_with_summary()`

```python
async def branch_with_summary(
    self,
    session_id: str,
    from_message_id: str,
    summary: str,
) -> str:
    """
    Fork + replace full history with a compacted summary as the first
    message. The LLM sees one assistant message ("Here is what happened
    so far: ...") instead of the full message chain. Cheaper for long sessions.
    """
```

#### D.4 — API endpoints

```
POST /api/v1/sessions/{session_id}/fork
Body: { "from_message_id": str, "label": str | null }
Response: { "session_id": str }  (new forked session)

POST /api/v1/sessions/{session_id}/branch
Body: { "from_message_id": str, "summary": str }
Response: { "session_id": str }
```

#### D.5 — Dispatch step retry

**File:** `modules/backend/agents/mission_control/dispatch/step_executor.py`

In `execute_task()`, when a step fails with a retryable error and the agent recorded
at least one successful tool call, emit a `StepRetryFromCheckpointEvent` instead of
immediately failing. The dispatch supervisor (or the Director via a decision node)
can call `fork()` on the session at the last successful tool call's message, then
re-run the step against the forked session.

#### D.6 — DB migration

```
alembic revision --autogenerate -m "session_fork_tracking"
```

New columns on `sessions` table only:
- `forked_from_session_id UUID FK sessions.id NULLABLE`
- `forked_from_message_id UUID FK session_messages.id NULLABLE`

No changes to `session_messages` table.

---

## Implementation Order

Phases are independent and can be built in any order. Recommended sequence:

| Phase | Effort | Risk | Value | Suggested order |
|-------|--------|------|-------|-----------------|
| A — Context Pipeline | S | Low | High | First — zero breakage, immediately improves extensibility |
| C — CLI Event Streaming | M | Low | High | Second — Claude Code wiring is one afternoon; Codex/Copilot heuristic is optional |
| B — Mid-Stream Steering | M | Medium | Medium | Third — requires Redis queue and PydanticAI interrupt handling |
| D — Session Forking | L | Medium | Medium | Last — needs Plan 74 fully live and a migration |

---

## Files Touched

| File | Change |
|------|--------|
| `modules/backend/agents/mission_control/mission_control.py` | Replace `_prepend_mission_context()` call with `build_context_message()`; add steer check in `_stream_handler` |
| `modules/backend/agents/mission_control/context/` | **New package** — `ContextBundle`, `ContextContributor`, built-in contributors, `build_context_message()` |
| `modules/backend/agents/mission_control/helpers/cli_executor.py` | Emit events from `execute_claude_code()`; add `_stream_subprocess()` for Codex/Copilot |
| `modules/backend/agents/mission_control/chat_cli_handler.py` | Replace inline context build with `build_context_message()` |
| `modules/backend/services/steer.py` | **New** — `SteerService` with Redis-backed queue |
| `modules/backend/services/session.py` | Add `fork()` and `branch_with_summary()` |
| `modules/backend/events/types.py` | Add `AgentSteerReceivedEvent` |
| `modules/backend/api/v1/endpoints/sessions.py` | Add `POST /steer`, `POST /fork`, `POST /branch` |
| `modules/backend/models/session.py` | Add `forked_from_session_id`, `forked_from_message_id` |
| `alembic/versions/` | Migration for fork columns on `sessions` table only |

---

## Principles

- **P1 (thin clients):** All context assembly logic stays in `context/` package.
  No context logic in API endpoints or frontend.
- **P6 (infrastructure not intelligence):** `handle()` remains a router.
  Steering is a signal it handles, not a decision it makes.
- **P3 (breaking changes are free):** `_prepend_mission_context()` can be deleted
  cleanly — it has two call sites, both in `mission_control/`.
- **Fail fast:** `build_context_message()` swallows individual contributor failures
  with a warning but never silently drops the user message.
- **No silent fallbacks:** `SteerService.push()` raises if the session has no active
  handle() (409). It does not silently discard the steer.
