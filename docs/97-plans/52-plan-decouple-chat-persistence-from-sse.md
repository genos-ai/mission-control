# Plan 52 — Decouple Chat Persistence from SSE Stream Lifecycle

| Field | Value |
|-------|-------|
| **Status** | Draft |
| **Created** | 2026-04-12 |
| **Type** | Architecture refactor |
| **Depends on** | Plan 51 (Autonomy Loop — ships the followup primitive and event patterns this plan extends) |
| **Target** | `modules/backend/agents/mission_control/mission_control.py`, `modules/backend/api/v1/endpoints/sessions.py`, `modules/backend/api/v1/endpoints/agents.py`, `modules/frontend/src/pages/mission/tabs/chat-tab.tsx` |

---

## 1  The problem

Chat message persistence is coupled to the SSE stream lifecycle. If the user navigates away, refreshes the browser, or loses network connectivity while an agent is responding, both the user message and the assistant response are lost.

### Root cause

The `handle()` async generator in `mission_control.py` does three things in one coroutine:

1. **Executes the agent** (LLM calls, tool invocations)
2. **Publishes events** to the Redis event bus (for SSE subscribers)
3. **Persists messages** to the database (step 11, after the agent completes)

The SSE endpoint (`sessions.py:send_message_stream`) consumes `handle()` as an async generator inside a `StreamingResponse`. The database transaction is committed only when the generator completes. If the browser aborts the HTTP request (navigate away, close tab, network drop), the generator is cancelled, and the commit never fires.

### Why this matters now

The Plan 51 autonomy loop introduced daemon-driven dispatch where agents run independently of any browser connection. But the chat path — the primary user interaction surface — still ties agent execution to the browser tab. A user who sends "create a plan and approve it" to the Director, then switches to the Plan tab to watch cards move, loses the Director's response because the SSE stream was abandoned.

### What's affected

| Entry point | Protected? | Vulnerability |
|---|---|---|
| `POST /sessions/{id}/messages` (web UI) | Partially (try/finally) | Messages lost if abort happens before step 11 |
| `POST /agents/chat/stream` (REST API) | No | No try/finally — messages always lost on abort |
| `mc.py chat` (CLI) | No | Ctrl+C before commit loses messages |
| Daemon dispatch (`dispatch_approved`) | Yes | Own DB session, own commit — correct pattern |
| Followup runner (`_create_agent_turn_runner`) | Yes | Own DB session, own commit — correct pattern |

---

## 2  Design principles

1. **The POST endpoint is a command, not a session.** Sending a message is an action with a durable side effect. The user message must be persisted the moment the server receives it, before any agent execution begins.

2. **Agent execution is independent of observation.** Whether the user is watching the Stream tab, has the browser open, or has gone to lunch — the agent completes its work and the result is persisted. The SSE stream is a read-only view into an operation that is happening regardless.

3. **The event bus is the integration point.** All callers (web, CLI, daemon, followup) publish events to the same bus. All consumers (SSE endpoints, Stream tab, Narrative tab, future Telegram adapter) read from the same bus. No consumer owns the agent's lifecycle.

4. **Existing patterns are the blueprint.** The daemon dispatch path already works this way: own DB session, own commit, events flow through the bus, SSE subscribers see them live. The chat path should follow the same architecture.

---

## 3  Target architecture

```
User sends message
    │
    ▼
POST /sessions/{id}/messages
    │
    ├─ 1. Persist user message (own commit, immediate)
    ├─ 2. Return 202 Accepted { message_id, session_id }
    └─ 3. Spawn background agent turn (asyncio.create_task)
              │
              ├─ Opens own DB session (get_async_session)
              ├─ Constructs own EventBus (SessionEventBus)
              ├─ Calls handle() — events publish to bus
              ├─ Persists assistant message on completion
              ├─ Commits own transaction
              └─ On error: persists error message, commits

Frontend
    │
    ├─ On 202: add optimistic user message to local state
    └─ Subscribe to GET /streams/runs/{session_id} (already exists)
         │
         └─ Receives events from Redis Pub/Sub
              ├─ agent.thinking.started
              ├─ agent.response.chunk (streaming text)
              ├─ agent.tool.called / agent.tool.returned
              ├─ agent.response.complete (full_content + metadata)
              └─ session.cost.updated
```

### What changes

| Component | Before | After |
|---|---|---|
| `POST /sessions/{id}/messages` | Returns `StreamingResponse` with inline SSE | Returns `202 Accepted` JSON, spawns background task |
| `handle()` | Async generator yielding events | Refactored into `execute_chat_turn()` — a regular async function that publishes events to the bus and persists messages |
| User message persistence | Step 11 (end of agent execution) | Immediate, before agent starts (own commit) |
| Assistant message persistence | Step 11 (coupled to SSE stream) | In background task on agent completion (own commit) |
| Frontend `sendMessage()` | `fetch()` + read SSE from response body | `fetch()` POST → 202, then `EventSource` on `/streams/runs/{sessionId}` |
| `POST /agents/chat/stream` | Same inline SSE pattern | Same refactor: 202 + background task |
| CLI `mc_chat.py` | Consumes `handle()` generator directly | Calls `execute_chat_turn()`, subscribes to Redis Pub/Sub for CLI rendering |

---

## 4  Implementation phases

### Phase A — Eager user message persistence (backend only, no API change)

**Goal:** The user message is persisted the moment the server receives it, before the agent starts. The rest of the flow remains unchanged — this is a safe, incremental step that immediately reduces data loss.

**Changes:**

1. **`mission_control.py` — move user message persistence to step 3.5 (new).** After the `UserMessageEvent` is yielded and published (current step 3), immediately call `session_service.add_message(session_id, user_create)` and flush. The user message is now in the DB before the agent even starts thinking.

2. **`mission_control.py` — step 11 only persists the assistant message.** Remove the user message from the `_persist_messages` call. Add a deduplication guard: if the user message was already persisted (step 3.5 succeeded), skip it.

3. **`sessions.py` — commit eagerly after step 3.5.** The endpoint's `generate()` function needs an intermediate commit after the user message is persisted. This requires splitting the DB session or using savepoints. Simplest: `await db.flush()` after the user message, and rely on the final commit (try/finally) for the assistant message.

**Files:**
- `modules/backend/agents/mission_control/mission_control.py` — split step 11
- `modules/backend/agents/mission_control/helpers/event_emitter.py` — `_persist_messages` skip-if-already-persisted guard

**Acceptance:** Navigate away mid-response → come back → user message is visible in chat history. Assistant message is lost (expected — Phase B fixes this).

**Risk:** Low. The user message persist is best-effort (already wrapped in try/except). If it fails, the existing step 11 path catches it as a fallback.

---

### Phase B — Background agent execution (the core refactor)

**Goal:** Agent execution runs in a background task with its own DB session. The POST endpoint returns immediately after persisting the user message. The SSE stream is decoupled.

**Changes:**

1. **New module: `modules/backend/services/chat_turn.py`** — `ChatTurnService` that encapsulates one agent chat turn:

    ```python
    class ChatTurnService:
        """Manages one chat turn: persist user message, execute agent, persist result."""

        async def start_turn(
            self,
            session_id: str,
            message: str,
            *,
            mission_id: str,
            sender_id: str | None = None,
            agent_id: str | None = None,
        ) -> str:
            """Persist user message and spawn background agent execution.

            Returns the user message ID. The agent runs asynchronously;
            results are published to the event bus and persisted on completion.
            """
    ```

    Internally:
    - Opens its own `get_async_session()` for the user message → commit
    - Spawns `asyncio.create_task(self._execute_turn(...))` for the agent
    - `_execute_turn()` opens a SECOND `get_async_session()` for the agent work
    - Agent events are published via `SessionEventBus(redis)` to both session and mission channels
    - On completion: persist assistant message → commit
    - On error: persist error message → commit

2. **`sessions.py:send_message_stream`** — replace inline SSE with:

    ```python
    @router.post("/{session_id}/messages")
    async def send_message(
        session_id: str,
        mission_id: str,
        data: SessionMessageCreate,
        db: DbSession,
    ) -> ApiResponse:
        """Persist user message and start agent turn in background."""
        service = ChatTurnService()
        message_id = await service.start_turn(
            session_id, data.content,
            mission_id=mission_id,
            sender_id=data.sender_id,
        )
        return ApiResponse(
            success=True,
            data={"message_id": message_id, "session_id": session_id},
            metadata={"status": "accepted"},
        )
    ```

    Response code changes from 200 (streaming) to 200 (JSON). The frontend no longer reads SSE from this response.

3. **`agents.py:agent_chat_stream`** — same refactor. Both streaming endpoints converge on the same `ChatTurnService.start_turn()` pattern.

4. **Frontend `chat-tab.tsx:sendMessage()`** — change from:
    ```typescript
    const response = await fetch(`${API_BASE}/sessions/${sessionId}/messages?...`, { method: 'POST', ... })
    // read SSE from response body
    ```
    to:
    ```typescript
    const response = await fetch(`${API_BASE}/sessions/${sessionId}/messages?...`, { method: 'POST', ... })
    const { message_id } = await response.json()
    // SSE comes from the existing /streams/runs/{sessionId} EventSource subscription
    ```

    The `Conversation` component already has access to SSE events via the mission-level stream (through `useWorkspaceStore`). It needs to:
    - Listen for `agent.response.chunk` and `agent.response.complete` events on the session's channel
    - Accumulate streaming content the same way it does today
    - On `agent.response.complete`: add the assistant message to local state
    - On query invalidation: reconcile with server-side history

5. **CLI `mc_chat.py`** — calls `ChatTurnService.start_turn()` (which persists + spawns), then subscribes to Redis Pub/Sub for the session to render events in the terminal. Or: calls a lower-level `execute_chat_turn()` function directly (without background task) since the CLI is a blocking REPL anyway.

**Files:**
- `modules/backend/services/chat_turn.py` (new)
- `modules/backend/api/v1/endpoints/sessions.py` — refactor `send_message_stream`
- `modules/backend/api/v1/endpoints/agents.py` — refactor `agent_chat_stream`
- `modules/frontend/src/pages/mission/tabs/chat-tab.tsx` — `sendMessage()` refactor
- `modules/frontend/src/hooks/use-sse.ts` — may need per-session subscription hook
- `modules/clients/cli/mc_chat.py` — adapt to new service

**Acceptance:**
- Send a message via the web UI → navigate to Plan tab → navigate back → user message visible, assistant response visible (or still streaming if agent hasn't finished)
- Close the browser entirely during a Director tool call → reopen → user message persisted, assistant response persisted (agent completed in background)
- Send a message via CLI → Ctrl+C immediately → user message persisted in DB

**Risk:** Medium. This changes the HTTP contract (no more inline SSE from POST), the frontend fetch pattern, and the CLI integration. All three surfaces need coordinated updates.

---

### Phase C — Frontend SSE subscription refactor

**Goal:** The frontend subscribes to session-level events via `EventSource` instead of parsing inline SSE from the POST response. This is the frontend half of Phase B.

**Changes:**

1. **New hook: `useSessionStream(sessionId)`** — wraps an `EventSource` connection to `/streams/runs/{sessionId}`. Returns:
    - `streamingContent: string` — accumulated text from `agent.response.chunk` events
    - `streamingThinking: string` — accumulated thinking from chunks with `metadata.thinking`
    - `lastComplete: AgentResponseComplete | null` — the most recent complete event
    - `isStreaming: boolean` — true between first chunk and complete event

2. **`Conversation` component** — uses `useSessionStream` instead of manual fetch-stream parsing:
    ```typescript
    const { streamingContent, streamingThinking, lastComplete, isStreaming } = useSessionStream(selectedSessionId)

    // When lastComplete arrives, add assistant message to state
    useEffect(() => {
      if (lastComplete) {
        setMessages(prev => [...prev, {
          id: `resp-${Date.now()}`,
          role: lastComplete.metadata?.error ? 'error' : 'assistant',
          content: lastComplete.full_content,
          ...
        }])
      }
    }, [lastComplete])
    ```

3. **`sendMessage()`** simplifies to:
    ```typescript
    const sendMessage = useCallback(async () => {
      const content = input.trim()
      if (!content || sending) return
      setInput('')
      setSending(true)

      // Optimistic user message
      setMessages(prev => [...prev, { role: 'user', content, ... }])

      // POST fires the agent turn — no SSE parsing here
      try {
        await fetch(`${API_BASE}/sessions/${sessionId}/messages?mission_id=${missionId}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify({ content, role: 'user', sender_id: user?.id }),
        })
      } catch (err) {
        toast.error('Failed to send message')
      }
      setSending(false)
      // Events arrive via useSessionStream — no inline parsing needed
    }, [input, sending, sessionId, missionId, user?.id, token])
    ```

**Files:**
- `modules/frontend/src/hooks/use-session-stream.ts` (new)
- `modules/frontend/src/pages/mission/tabs/chat-tab.tsx` — simplify `Conversation`
- `modules/frontend/src/hooks/use-sse.ts` — `useSessionStream` may extend `useRunStream`

**Acceptance:** Same UX as before — streaming text appears in real-time, thinking shows in purple box, tool calls show inline, complete event finalises the message. But now: navigate away and back → stream reconnects → if agent is still running, streaming resumes. If agent finished, complete event is in history.

---

### Phase D — Event durability with Redis Streams (optional, future)

**Goal:** Events survive subscriber disconnects. A reconnecting SSE client can replay events it missed.

**Changes:**

1. **`bus.py:SessionEventBus`** — dual-write: `XADD` to a Redis Stream AND `PUBLISH` to Pub/Sub. Pub/Sub for real-time delivery, Streams for durability and replay.

2. **`streams.py:stream_run_events`** — on connect, read the Stream from the beginning (or from a cursor provided by the client via `Last-Event-ID` header). Then switch to Pub/Sub for real-time. On reconnect, replay from where the client left off.

3. **Stream TTL:** `XTRIM session_events:{session_id} MAXLEN ~ 1000` or a 24-hour EXPIRY so old events don't accumulate.

**Files:**
- `modules/backend/events/bus.py` — dual-write to Pub/Sub + Streams
- `modules/backend/api/v1/endpoints/streams.py` — cursor-based replay on reconnect

**Acceptance:** Disconnect SSE → reconnect 5 seconds later → all missed events replay seamlessly. The frontend shows no gap.

**Risk:** Low incremental risk (Pub/Sub path unchanged, Streams is additive). Redis Streams are a mature feature.

---

## 5  Exit criteria

Plan 52 is Done when:

1. A user can send a message, navigate away immediately, come back, and see their message persisted.
2. The agent completes its work and persists the response regardless of whether the browser is connected.
3. The Stream tab shows agent execution events during daemon-driven dispatch AND during chat-initiated dispatch using the same SSE path.
4. The `POST /sessions/{id}/messages` endpoint returns a JSON response (not `StreamingResponse`).
5. The `POST /agents/chat/stream` endpoint follows the same pattern.
6. The CLI `mc.py chat` works with the new architecture (direct call or Redis subscription).
7. No message data is lost on navigate-away, browser close, network drop, or Ctrl+C.
8. Existing test suites (`test_autonomy_loop_e2e.py`, `verify_followup_primitive.py`) pass.

---

## 6  What this plan does NOT do

- **No Temporal/Celery task queue.** Background tasks use `asyncio.create_task` within the same process. If the backend crashes mid-turn, the turn is lost. Temporal integration (Plan 16) is the future answer for cross-process durability.
- **No message editing or deletion.** Persisted messages are append-only.
- **No multi-device sync.** If a user has two tabs open, both see events via SSE, but there's no conflict resolution if both send simultaneously.
- **No retry of failed agent turns.** If the background agent errors, it persists an error message. The user must manually retry.

---

## 7  References

### Files this plan creates
- `modules/backend/services/chat_turn.py` — ChatTurnService
- `modules/frontend/src/hooks/use-session-stream.ts` — session-level SSE hook

### Files this plan modifies
- `modules/backend/agents/mission_control/mission_control.py` — split user message persistence to step 3.5
- `modules/backend/agents/mission_control/helpers/event_emitter.py` — dedup guard in `_persist_messages`
- `modules/backend/api/v1/endpoints/sessions.py` — replace `StreamingResponse` with JSON + background task
- `modules/backend/api/v1/endpoints/agents.py` — same refactor for `agent_chat_stream`
- `modules/frontend/src/pages/mission/tabs/chat-tab.tsx` — sendMessage + SSE subscription refactor
- `modules/frontend/src/hooks/use-sse.ts` — session-level subscription
- `modules/clients/cli/mc_chat.py` — adapt to ChatTurnService or direct execute

### Related plans
- [Plan 51 — Autonomy Loop](51-plan-autonomy-loop-supervisor.md) — followup primitive, daemon dispatch pattern
- [Plan 16 — Temporal Integration](16-plan-temporal-integration-[X].md) — future cross-process agent execution durability
