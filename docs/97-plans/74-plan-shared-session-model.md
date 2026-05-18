# Plan 74: Shared Session Model — One Session Per Mission Working Context

## Problem Statement

Sessions are currently scoped per-agent: chatting with the Director creates one session, switching to the research agent creates another, and so on. This was an accidental artifact of routing being tied to `session.agent_id`. The result:

- **Fragmented history** — cross-agent narrative is lost. The Director cannot see what the research agent produced.
- **Session proliferation** — a mission with 8 agents generates 8+ sessions from normal chat usage.
- **Inconsistency** — autonomous dispatch (Temporal) already uses one session for multi-agent plan execution, while the chat path creates N sessions.
- **Diluted cost tracking** — no single place to see "how much this working session cost."
- **Broken memory compression** — rolling summary per agent captures fragments, not the full narrative.

## Target State

A **session** represents the user's active working context within a mission. All agents share the same session unless the user explicitly creates a new one ("new thread"). Agent routing is a per-message parameter, not a session identity property.

```
Mission
  └── Session (the user's working context)
        ├── messages: user→director, director→user, user→researcher, researcher→user...
        ├── cost: accumulated across ALL agent interactions in this working session
        ├── rolling_summary: full narrative of the work session
        └── channels: web, cli, telegram (unchanged)
```

- `session.agent_id` remains as the **default/fallback** agent (Director), not a routing lock.
- When sending a message, the caller specifies `target_agent` explicitly (or omits it to use the default).
- History loading becomes agent-aware: SQL query filters by `sender_id` before injecting into `message_history`.
- "New session" = explicit user action, not a side effect of switching agents.

## Principles

- **P15**: The session is the transport primitive — one per working context, not per agent.
- **P3**: Breaking changes are free during dev.
- **P14**: Modular, reusable, elegant, robust — decouple routing from session identity.

## Codebase Constraints (read before implementing)

- **Enum storage**: `Enum(SomeEnum, native_enum=False)` stores the enum **NAME** (e.g. `ACTIVE`), not the value (`active`). All status comparisons in SQLAlchemy queries MUST use `SessionStatus.ACTIVE`, never raw strings like `"active"`. See `feedback_enum_status_uppercase.md`.
- **Layer discipline**: API endpoints never access `service.repo` directly. All data access goes through service methods. No existing endpoint breaks this rule.
- **`tool_result` messages**: `model_messages_to_session_creates()` in `history.py` does NOT set `sender_id` on `tool_result` messages (only on `assistant` and `tool_call`). Any SQL filter on `sender_id` must account for `tool_result` having `sender_id = NULL`.
- **`handle()` callers**: There are exactly 3 call sites — `agents.py`, `sessions.py`, and `temporal/chat_activities.py`. All must be verified.

---

## Phase 1: Backend — Decouple Routing from Session Identity

### 1.1 Add `target_agent` parameter to `handle()`

**File**: `modules/backend/agents/mission_control/mission_control.py`

Current signature (line ~127):
```python
async def handle(
    session_id: str,
    message: str,
    *,
    mission_id: str,
    session_service: SessionServiceProtocol,
    event_bus: EventBusProtocol = NoOpEventBus(),
    channel: str = "api",
    sender_id: str | None = None,
    mission_brief: str | None = None,
    db_session: Any | None = None,
    skip_persistence: bool = False,
) -> AsyncIterator[SessionEvent]:
```

Add `target_agent: str | None = None`:
```python
async def handle(
    session_id: str,
    message: str,
    *,
    mission_id: str,
    session_service: SessionServiceProtocol,
    event_bus: EventBusProtocol = NoOpEventBus(),
    channel: str = "api",
    sender_id: str | None = None,
    target_agent: str | None = None,
    mission_brief: str | None = None,
    db_session: Any | None = None,
    skip_persistence: bool = False,
) -> AsyncIterator[SessionEvent]:
```

### 1.2 Update `_resolve_agent()` to accept explicit override

**File**: `modules/backend/agents/mission_control/helpers/routing.py`

Change signature and logic:
```python
def _resolve_agent(
    session: "SessionResponse",
    message: str,
    target_agent: str | None = None,
) -> str:
    """Determine which agent handles this message.

    Priority: explicit target_agent > session.agent_id > keyword routing > fallback.
    """
    registry = get_registry()

    if target_agent and registry.has(target_agent):
        return target_agent

    if session.agent_id and registry.has(session.agent_id):
        return session.agent_id

    router = RuleBasedRouter(registry)
    request = MissionControlRequest(user_input=message)
    agent_name = router.route(request)
    if agent_name is not None:
        return agent_name

    mc_config = _load_mission_control_config()
    fallback = mc_config.routing.fallback_agent
    if fallback and registry.has(fallback):
        return fallback

    available = ", ".join(c["agent_name"] for c in registry.list_all()) or "none"
    raise ValidationError(f"No agent matched. Available agents: {available}.")
```

### 1.3 Update `handle()` call site

**File**: `modules/backend/agents/mission_control/mission_control.py` (line ~195)

```python
# BEFORE:
agent_name = _resolve_agent(session, message)

# AFTER:
agent_name = _resolve_agent(session, message, target_agent=target_agent)
```

### 1.4 `collect()` — no change needed

`collect()` uses `**kwargs` to forward to `handle()`. Callers that pass `target_agent` will have it forwarded automatically.

### 1.5 `handle_cli_chat` — no change needed

The CLI engine handler (line ~220) already receives the resolved `agent_name`. It is called AFTER `_resolve_agent()` resolves the target, so it works correctly without modification.

### 1.6 `temporal/chat_activities.py` — no change needed

The Temporal chat activity (line ~109) calls `handle()` without `target_agent`. This is correct: Temporal chat uses `session.agent_id` for routing (the session was created with a specific agent). The new `target_agent` parameter defaults to `None`, which preserves the existing fallback chain.

---

## Phase 2: Backend — Agent-Aware History Loading (SQL-Level)

The key insight: filter at the database query level, not in Python. This avoids loading all messages into memory and filtering them down.

**Critical**: `tool_result` messages have `sender_id = NULL` (see `history.py` `model_messages_to_session_creates()` — only `assistant` and `tool_call` messages get `sender_id`). The SQL filter must include `tool_result` in the always-included roles to avoid breaking PydanticAI's message history (a `ToolCallPart` without its matching `ToolReturnPart` is invalid).

### 2.1 Add `sender_ids` filter to `SessionRepository.get_messages()`

**File**: `modules/backend/repositories/session.py`

```python
async def get_messages(
    self,
    session_id: str,
    limit: int = 100,
    offset: int = 0,
    sender_ids: list[str] | None = None,
) -> list[SessionMessage]:
    """Get messages for a session, ordered by creation time.

    Args:
        sender_ids: If provided, return only messages where:
            - role is 'user', 'system', or 'tool_result' (always included), OR
            - sender_id is in the provided list (matches assistant + tool_call)
          This enables agent-aware history loading for shared sessions.

          Why tool_result is always included: tool_result messages have
          sender_id=NULL (set by model_messages_to_session_creates in
          history.py). They must be included to pair with their preceding
          tool_call messages, otherwise PydanticAI gets ToolCallPart
          without matching ToolReturnPart — an invalid message history.
    """
    stmt = (
        select(SessionMessage)
        .where(SessionMessage.session_id == session_id)
        .order_by(SessionMessage.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    if sender_ids is not None:
        from sqlalchemy import or_
        stmt = stmt.where(
            or_(
                SessionMessage.role.in_(["user", "system", "tool_result"]),
                SessionMessage.sender_id.in_(sender_ids),
            )
        )
    result = await self.session.execute(stmt)
    return list(result.scalars().all())
```

### 2.2 Add `sender_ids` to `SessionService.get_messages()`

**File**: `modules/backend/services/session.py` (line ~415)

```python
async def get_messages(
    self,
    session_id: str,
    limit: int = 100,
    offset: int = 0,
    sender_ids: list[str] | None = None,
) -> tuple[list, int]:
    """Get messages for a session with optional sender filtering."""
    await self.repo.get_by_id(session_id)
    messages = await self.repo.get_messages(
        session_id, limit=limit, offset=offset, sender_ids=sender_ids,
    )
    total = await self.repo.count_messages(session_id)
    return messages, total
```

### 2.3 Update `SessionServiceProtocol`

**File**: `modules/backend/core/protocols.py` (line ~71)

```python
async def get_messages(
    self, session_id: str, limit: int = ..., offset: int = ...,
    sender_ids: list[str] | None = ...,
) -> tuple[list, int]: ...
```

### 2.4 Update history loading in `handle()`

**File**: `modules/backend/agents/mission_control/mission_control.py` (line ~269)

```python
# BEFORE:
history_messages, _ = await session_service.get_messages(session_id, limit=100)
model_history = session_messages_to_model_history(history_messages)

# AFTER:
history_messages, _ = await session_service.get_messages(
    session_id, limit=100, sender_ids=[agent_name],
)
model_history = session_messages_to_model_history(history_messages)
```

This loads: user messages + system messages + tool_result messages + this agent's own assistant and tool_call messages. Other agents' assistant/tool_call messages are excluded from the context window.

### 2.5 No changes to `history.py`

`session_messages_to_model_history()` converts whatever list it receives. The filtering is upstream at the SQL level. No new functions needed in `history.py`.

---

## Phase 3: Backend — Session Resolution

### 3.1 Add `find_active_for_mission()` to `SessionRepository`

**File**: `modules/backend/repositories/session.py`

A dedicated method using enum members (not strings) for status comparison. Follows the same pattern as `get_active_by_user()` (line 26).

```python
async def find_active_for_mission(
    self,
    mission_id: str,
) -> Session | None:
    """Find the most recently active session for a mission.

    Returns the single most recent ACTIVE or SUSPENDED session
    scoped to this mission, ordered by last_activity_at DESC.
    """
    result = await self.session.execute(
        select(Session)
        .where(
            Session.mission_id == mission_id,
            Session.status.in_([
                SessionStatus.ACTIVE,
                SessionStatus.SUSPENDED,
            ]),
        )
        .order_by(Session.last_activity_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
```

### 3.2 Add `find_active_for_mission()` to `SessionService`

**File**: `modules/backend/services/session.py`

```python
async def find_active_for_mission(self, mission_id: str) -> Session | None:
    """Find the most recently active session for a mission."""
    return await self.repo.find_active_for_mission(mission_id)
```

### 3.3 Keep `ensure_session()` unchanged

**File**: `modules/backend/services/session.py`

No changes. The method retains its current simple signature and behavior. It remains available for internal callers (Temporal activities) that already have a session_id.

---

## Phase 4: Backend — API Endpoint Changes

### 4.1 Update `POST /agents/chat` and `POST /agents/chat/stream`

**File**: `modules/backend/api/v1/endpoints/agents.py`

Session resolution and `target_agent` forwarding:

```python
# BEFORE (in both agent_chat and agent_chat_stream):
service = SessionService(db)
session_id = await service.ensure_session(
    data.session_id, agent_id=data.agent, goal=data.message,
)

# AFTER:
service = SessionService(db)
session_id = data.session_id
if not session_id:
    existing = await service.find_active_for_mission(data.mission_id)
    if existing:
        session_id = existing.id
    else:
        session = await service.create_session(
            SessionCreate(
                agent_id="mission.director.agent",
                mission_id=data.mission_id,
                goal="Mission Chat",
            ),
        )
        session_id = session.id
```

In the `_run_agent()` closure of `agent_chat_stream()`:
```python
# BEFORE:
async for event in handle(
    session_id, data.message,
    mission_id=data.mission_id,
    session_service=bg_service,
    event_bus=event_bus,
    db_session=bg_db,
    skip_persistence=True,
):

# AFTER:
async for event in handle(
    session_id, data.message,
    mission_id=data.mission_id,
    target_agent=data.agent,
    session_service=bg_service,
    event_bus=event_bus,
    db_session=bg_db,
    skip_persistence=True,
):
```

In `agent_chat()` (non-streaming):
```python
result = await collect(
    session_id,
    data.message,
    mission_id=data.mission_id,
    target_agent=data.agent,
    session_service=service,
    db_session=db,
)
```

### 4.2 Update `POST /sessions/{session_id}/messages` — add `target_agent` query param

**File**: `modules/backend/api/v1/endpoints/sessions.py`

```python
@router.post(
    "/{session_id}/messages",
    summary="Send message and stream events",
)
async def send_message(
    session_id: str,
    mission_id: str,
    data: SessionMessageCreate,
    db: DbSession,
    target_agent: str | None = Query(default=None, description="Route to a specific agent"),
):
```

And pass through:
```python
async for event in handle(
    session_id,
    data.content,
    mission_id=mission_id,
    target_agent=target_agent,
    session_service=bg_service,
    event_bus=event_bus,
    sender_id=data.sender_id,
    db_session=bg_db,
    skip_persistence=True,
):
```

### 4.3 `SessionMessageCreate` schema — NO changes

`target_agent` is transient routing information. It belongs as a query parameter on the endpoint, NOT as a field on the persisted message schema. The schema remains unchanged.

---

## Phase 5: Backend — Message Attribution (Verify Only)

No code changes required. Verify existing behavior is correct:

- `handle()` creates streaming messages with `sender_id=agent_name` (line ~307: `create_streaming_message(session_id, sender_id=agent_name)`)
- `_persist_messages()` passes `sender_id` on assistant messages
- `handle_cli_chat()` persists with `sender_id=agent_name`
- `model_messages_to_session_creates()` sets `sender_id=agent_id` on `assistant` and `tool_call` messages, but NOT on `tool_result` messages (this is why Phase 2.1 includes `tool_result` in the always-included roles)

All paths already attribute assistant messages to the responding agent. The shared session model relies on this existing `sender_id` attribution to distinguish which agent said what.

---

## Phase 6: CLI Changes

### 6.1 Update `mc_chat.py` — session resolution

**File**: `modules/clients/cli/mc_chat.py` (lines 36-52)

```python
# BEFORE:
session_id = None
if not new_thread:
    params: dict = {"mission_id": mission_id, "limit": 1, "agent_id": agent_name}
    sessions = await api.get("/sessions", params=params)
    session_list = sessions if isinstance(sessions, list) else sessions.get("items", [])
    if session_list:
        session_id = session_list[0].get("id")

if not session_id:
    goal = f"{agent_name.split('.')[-2]} Chat" if "." in agent_name else f"{agent_name} Chat"
    session = await api.post("/sessions", body={
        "goal": goal,
        "agent_id": agent_name,
        "mission_id": mission_id,
    })
    session_id = session.get("id")

# AFTER:
session_id = None
if not new_thread:
    # Find the mission's active session (shared across all agents)
    params: dict = {"mission_id": mission_id, "limit": 1}
    sessions = await api.get("/sessions", params=params)
    session_list = sessions if isinstance(sessions, list) else sessions.get("items", [])
    if session_list:
        session_id = session_list[0].get("id")

if not session_id:
    session = await api.post("/sessions", body={
        "goal": "Mission Chat",
        "agent_id": "mission.director.agent",
        "mission_id": mission_id,
    })
    session_id = session.get("id")
```

### 6.2 CLI chat body — no change needed

Line 89 already sends `"agent": agent_name` in the request body. The backend's `ChatRequest.agent` field maps to `target_agent` in the `handle()` call (Phase 4.1). This works as-is.

---

## Phase 7: Frontend Changes

### 7.1 Update `ChatTab` root — shared session at top level

**File**: `modules/frontend/src/pages/mission/tabs/chat-tab.tsx`

The fundamental change: session management moves from `AgentChatPanel` (per-agent) to `ChatTab` (per-mission). Agent selection controls routing, not session identity.

Do NOT use `key={activeAgent}` on `AgentChatPanel` — the session is shared, so unmounting on agent switch would cause unnecessary message re-fetching and flicker. The `Conversation` component stays mounted; only `targetAgent` changes.

```tsx
export default function ChatTab() {
  const { id: missionId } = useParams<{ id: string }>()
  const [rightOpen, setRightOpen] = useState(true)
  const [activeAgent, setActiveAgent] = useState<string>(DEFAULT_CHAT_AGENT)
  const { user } = useAuthStore()

  // Shared session for the mission (one session, all agents)
  const { data: sessions, isLoading: loadingSessions } = useSessions({ mission_id: missionId })
  const createSession = useCreateSession()
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)

  // Auto-select the most recent session
  useEffect(() => {
    if (sessions && sessions.length > 0 && !activeSessionId) {
      setActiveSessionId(sessions[0].id)
    }
  }, [sessions])

  // Reset agent and session on mission change
  const prevId = useRef<string | null>(null)
  useEffect(() => {
    if (missionId && missionId !== prevId.current) {
      prevId.current = missionId
      setActiveAgent(DEFAULT_CHAT_AGENT)
      setActiveSessionId(null)
    }
  }, [missionId])

  async function handleNewThread() {
    if (!user || !missionId) return
    const session = await createSession.mutateAsync({
      goal: 'Mission Chat',
      mission_id: missionId,
      agent_id: DEFAULT_CHAT_AGENT,
    })
    setActiveSessionId(session.id)
  }

  return (
    <div className="flex h-full overflow-hidden">
      <LeftPanel missionId={missionId!} activeAgent={activeAgent} onAgentClick={setActiveAgent} />
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden border-l">
        <ThreadSelector
          sessions={sessions ?? []}
          activeSessionId={activeSessionId}
          onSelect={setActiveSessionId}
          onNewThread={handleNewThread}
          loading={loadingSessions || createSession.isPending}
        />
        <AgentChatPanel
          missionId={missionId!}
          agentName={activeAgent}
          sessionId={activeSessionId}
          onReturnToDirector={() => setActiveAgent(DEFAULT_CHAT_AGENT)}
        />
      </div>
      {rightOpen ? (
        <ArtifactsPanel missionId={missionId!} onClose={() => setRightOpen(false)} />
      ) : (
        <button onClick={() => setRightOpen(true)} /* ... */ />
      )}
    </div>
  )
}
```

### 7.2 Simplify `AgentChatPanel` — receives shared session

**File**: `modules/frontend/src/pages/mission/tabs/chat-tab.tsx`

No session management, no thread picker, no `useEffect` for session creation. Pure rendering.

```tsx
function AgentChatPanel({
  missionId,
  agentName,
  sessionId,
  onReturnToDirector,
}: {
  missionId: string
  agentName: string
  sessionId: string | null
  onReturnToDirector: () => void
}) {
  const agentShort = agentName.endsWith('.agent') ? agentName.slice(0, -6) : agentName
  const isDirector = agentName === DEFAULT_CHAT_AGENT

  return (
    <>
      <div className="flex h-9 shrink-0 items-center gap-2 border-b px-3">
        {!isDirector && (
          <button
            onClick={onReturnToDirector}
            className="shrink-0 text-muted-foreground hover:text-foreground transition-colors"
            title="Back to Director"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>
        )}
        {isDirector
          ? <Brain className="h-3.5 w-3.5 text-primary" />
          : <Bot className="h-3.5 w-3.5 text-muted-foreground" />}
        <span className="text-xs font-semibold">
          {isDirector ? 'Director' : agentShort}
        </span>
      </div>
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {sessionId ? (
          <Conversation sessionId={sessionId} missionId={missionId} targetAgent={agentName} />
        ) : (
          <div className="flex flex-1 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        )}
      </div>
    </>
  )
}
```

### 7.3 Add `ThreadSelector` component (inline)

**File**: `modules/frontend/src/pages/mission/tabs/chat-tab.tsx`

```tsx
function ThreadSelector({
  sessions,
  activeSessionId,
  onSelect,
  onNewThread,
  loading,
}: {
  sessions: SessionListItem[]
  activeSessionId: string | null
  onSelect: (id: string) => void
  onNewThread: () => void
  loading: boolean
}) {
  return (
    <div className="flex h-8 shrink-0 items-center gap-2 border-b px-3 bg-muted/30">
      <span className="text-[10px] font-medium text-muted-foreground">Thread:</span>
      <select
        value={activeSessionId ?? ''}
        onChange={(e) => onSelect(e.target.value)}
        className="h-6 appearance-none rounded border bg-transparent pl-2 pr-6 text-[10px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        {sessions.map((s) => (
          <option key={s.id} value={s.id}>
            {s.goal || s.id.slice(0, 12)} · {formatUtc(s.last_activity_at)}
          </option>
        ))}
      </select>
      <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0" onClick={onNewThread} disabled={loading} title="New thread">
        {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
      </Button>
    </div>
  )
}
```

### 7.4 Update `Conversation` — accept `targetAgent`, pass to API

**File**: `modules/frontend/src/pages/mission/tabs/chat-conversation.tsx`

Add prop:
```tsx
export function Conversation({
  sessionId,
  missionId,
  targetAgent,
}: {
  sessionId: string
  missionId: string
  targetAgent?: string
}) {
```

Update `sendMessage()` fetch URL:
```tsx
// BEFORE:
const response = await fetch(
  `${API_BASE}/sessions/${sessionId}/messages?mission_id=${missionId}`,
  { method: 'POST', ... }
)

// AFTER:
const params = new URLSearchParams({ mission_id: missionId })
if (targetAgent) params.set('target_agent', targetAgent)
const response = await fetch(
  `${API_BASE}/sessions/${sessionId}/messages?${params}`,
  { method: 'POST', ... }
)
```

### 7.5 Show agent attribution on messages

**File**: `modules/frontend/src/pages/mission/tabs/chat-conversation.tsx`

In the message bubble rendering, add a sender badge for assistant messages:
```tsx
{msg.role === 'assistant' && msg.sender_id && (
  <Badge variant="outline" className="text-[10px]">
    {msg.sender_id.replace('.agent', '').split('.').pop()}
  </Badge>
)}
```

### 7.6 Remove old per-agent session logic

**File**: `modules/frontend/src/pages/mission/tabs/chat-tab.tsx`

Delete from the old `AgentChatPanel`:
- `const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)`
- `const sessions = allSessions?.filter((s) => s.agent_id === agentName) ?? []`
- The `useEffect` that auto-selects per-agent sessions
- The `handleNewChat` function
- The per-agent `<select>` thread picker and `<Button>` for new chat

All of this is replaced by `ThreadSelector` at the `ChatTab` level (Phase 7.3).

---

## Phase 8: Cleanup & Documentation

### 8.1 Update `SessionCreate` schema documentation

**File**: `modules/backend/schemas/session.py`

```python
agent_id: str | None = Field(
    default=None,
    max_length=100,
    description="Default/primary agent for this session (fallback routing). Not a routing lock.",
    examples=["mission.director.agent"],
)
```

### 8.2 Data migration — NOT needed

Existing per-agent sessions remain valid and queryable. They simply won't be auto-created anymore. No DB schema changes.

### 8.3 Keep `agent_id` filter on list endpoint

**File**: `modules/backend/api/v1/endpoints/sessions.py`

The `list_sessions` endpoint retains its `agent_id` query filter for backward compatibility. It's just no longer used by the frontend or CLI for session resolution.

### 8.4 Verify rolling summary handles multi-agent content

**File**: `modules/backend/services/session_memory.py`

`SessionMemoryService.compress_if_needed()` summarizes all messages in the session. With a shared session, it now summarizes cross-agent conversation. Verify the summarizer prompt doesn't assume single-agent content. If it does, update the prompt to say "This session contains messages from multiple agents identified by sender_id."

---

## File Change Summary

| File | Change | Description |
|------|--------|-------------|
| `modules/backend/agents/mission_control/mission_control.py` | Modify | Add `target_agent` to `handle()`, pass to `_resolve_agent()`, filter history by `sender_ids=[agent_name]` |
| `modules/backend/agents/mission_control/helpers/routing.py` | Modify | Add `target_agent` param to `_resolve_agent()` |
| `modules/backend/repositories/session.py` | Modify + Add | Add `sender_ids` filter to `get_messages()`, add `find_active_for_mission()` |
| `modules/backend/services/session.py` | Modify + Add | Pass `sender_ids` through in `get_messages()`, add `find_active_for_mission()` |
| `modules/backend/core/protocols.py` | Modify | Add `sender_ids` to `SessionServiceProtocol.get_messages()` |
| `modules/backend/api/v1/endpoints/agents.py` | Modify | Session resolution via `find_active_for_mission()`, pass `target_agent` |
| `modules/backend/api/v1/endpoints/sessions.py` | Modify | Add `target_agent` query param to `send_message()` |
| `modules/backend/schemas/session.py` | Modify | Update `agent_id` field description |
| `modules/clients/cli/mc_chat.py` | Modify | Remove `agent_id` filter from session lookup |
| `modules/frontend/src/pages/mission/tabs/chat-tab.tsx` | Rewrite | Shared session at top, agent as routing target, ThreadSelector |
| `modules/frontend/src/pages/mission/tabs/chat-conversation.tsx` | Modify | Accept `targetAgent` prop, pass to API URL, show sender badges |

---

## What NOT to Change

- `session.agent_id` column — retains as default/fallback agent
- Session DB schema — no migration
- Temporal workflow inputs — already pass explicit session_id
- Temporal `chat_activities.py` — `handle()` call defaults `target_agent=None`, uses session.agent_id fallback
- Event bus — events carry session_id correctly
- Session lifecycle state machine (ACTIVE -> SUSPENDED -> COMPLETED)
- Cost budget enforcement — still per-session, now covers all agents
- Channel bindings — multi-channel support unchanged
- `ensure_session()` in service layer — remains simple, used by Temporal
- `handle_cli_chat()` — receives resolved agent_name, works as-is
- `session_messages_to_model_history()` — converts whatever list it gets, no changes
- `SessionMessageCreate` schema — `target_agent` is transient, NOT persisted

---

## Verification Checklist

1. **Chat with Director** — reuses existing mission session, responses attributed to Director
2. **Switch to research agent** — same session, messages routed to research agent via `target_agent`
3. **Switch back to Director** — Director's history loads only user + system + tool_result + Director messages (SQL filter)
4. **New thread** — creates a fresh session for the mission, clean slate
5. **CLI `mc chat --agent software.quality.agent`** — reuses mission's active session, routes to quality agent
6. **CLI `mc chat --new`** — creates new session regardless
7. **Frontend message timeline** — shows all messages with sender badges
8. **Cost tracking** — single session accumulates cost from all agents
9. **Autonomous dispatch (Temporal)** — unchanged, already creates one shared session
10. **Temporal chat activity** — unchanged, `target_agent` defaults to None, session.agent_id used
11. **Rolling summary** — captures full cross-agent narrative
12. **Tool call / tool result pairing** — agent history includes tool_results (NULL sender_id) alongside its own tool_calls
