# Plan 56 — Unified Async Architecture: Tier-Based Execution Model

| Field | Value |
|-------|-------|
| **Status** | Ready |
| **Created** | 2026-04-14 |
| **Depends on** | Plan 53 (MissionEventHandler — done), Plan 52 (Temporal Backbone — done) |
| **ADR** | docs/02-architecture/004-adr-unified-async-architecture.md |
| **Target** | Chat persistence, tool fork pattern, dependency cleanup |

---

## 1  Problem

Five async technologies serve overlapping purposes. The user-facing symptoms:

1. **Director chat responses disappear on navigation** — the response streams via SSE tied to the HTTP connection. Navigate away → connection drops → response lost. The Architect's 30-second workflow redesign vanishes.

2. **Simple "hi" messages are slow through Temporal** — 300-400ms scheduling overhead for a message that needs zero durability.

3. **Errors are invisible** — Temporal activity failures log to files but don't reach the SSE stream (partially fixed by Plan 53's MissionEventHandler).

4. **No clear decision framework** — developers choose between Temporal, TaskIQ, FastStream, asyncio.create_task, and synchronous SSE based on gut feeling.

---

## 2  Target Architecture

Align to the reference architecture's 4-tier graduated complexity model (doc 46):

```
Tier 1: Stateless CRUD        → in-request, DB transaction
Tier 2: Stateless agent call   → in-request, SSE stream
Tier 3: Interactive session    → persist-first SSE, Redis Pub/Sub
Tier 4: Autonomous execution   → Temporal workflow, Redis Pub/Sub
```

**Rule:** Tier 3 for chat. Tier 4 for autonomous work. Nothing else.

```
┌─────────────────────────────────────────────────┐
│                  Client                          │
│  (Browser, CLI, TUI, Telegram)                  │
└──────┬────────────────────────┬─────────────────┘
       │ POST message           │ SSE / reconnect
       ▼                        ▼
┌──────────────────────────────────────────────────┐
│              FastAPI Server                       │
│                                                   │
│  Tier 3: Chat path                               │
│  ┌─────────────────────────────────────────────┐ │
│  │ 1. Persist user message (DB)                │ │
│  │ 2. Run Director in-process                  │ │
│  │ 3. Persist response chunks as they stream   │ │
│  │ 4. Emit events → Redis Pub/Sub             │ │
│  │ 5. If tool needs Tier 4 → fork             │ │
│  └──────────────────────────┬──────────────────┘ │
│                              │ fork               │
│  Tier 4: Durable path       ▼                    │
│  ┌─────────────────────────────────────────────┐ │
│  │ Temporal Workflow                           │ │
│  │ (MissionRunWorkflow, WorkflowRunWorkflow)   │ │
│  │ Activities emit → Redis Pub/Sub            │ │
│  │ Results persist → DB                       │ │
│  └─────────────────────────────────────────────┘ │
│                                                   │
│  Event Bus: Redis Pub/Sub (one channel/mission)   │
│  Persistence: PostgreSQL (mission_events, msgs)   │
└──────────────────────────────────────────────────┘
```

---

## 3  Phases

### Phase A — Persist-First Chat (Tier 3 Foundation)

**Goal:** Chat responses survive navigation. No new infrastructure — just persistence changes.

#### 3.1 Incremental Response Persistence

**Modified file:** `modules/backend/agents/mission_control/mission_control.py` (handle function)

Currently, the assistant message is persisted AFTER the full stream completes. If the SSE drops mid-stream, the response is lost.

Change: persist incrementally.

```python
# Current: persist after stream
async for event in director.run_stream(...):
    yield event
# Only now does the message get saved to DB

# Target: persist during stream
accumulated = ""
async for event in director.run_stream(...):
    if isinstance(event, AgentResponseChunkEvent):
        accumulated += event.content
    yield event
# Periodic flush (every 500 chars or every 2 seconds)
if should_flush(accumulated):
    await session_service.update_partial_response(session_id, accumulated)
# Final persist
await session_service.finalize_response(session_id, accumulated)
```

**Schema change:** Add `partial_response` column to `session_messages`:

```sql
ALTER TABLE session_messages ADD COLUMN partial_response TEXT;
ALTER TABLE session_messages ADD COLUMN is_complete BOOLEAN DEFAULT TRUE;
```

When complete, `partial_response` is moved to `content` and `is_complete` is set to TRUE.

#### 3.2 Don't Cancel on SSE Disconnect

**Modified file:** `modules/backend/api/v1/endpoints/streams.py` or the chat endpoint

Currently, when the SSE connection drops, uvicorn raises `CancelledError` which propagates up and cancels the Director's execution.

Change: catch `CancelledError` in the SSE generator but let the Director coroutine continue in the background. The response still gets persisted and events still emit to Redis.

```python
async def chat_stream_generator(session_id, message, ...):
    task = asyncio.create_task(_run_director(session_id, message, ...))
    try:
        async for event in event_bus.subscribe(session_id):
            yield format_sse(event)
    except asyncio.CancelledError:
        # Client disconnected — but the director task continues
        pass
    # task runs to completion, persists response, emits events
```

#### 3.3 Frontend: Load History on Reconnect

**Modified file:** `modules/frontend/src/pages/mission/tabs/chat-tab.tsx`

On mount or SSE reconnect, fetch the latest session messages from DB. If there's a `partial_response` that's not yet complete, show it with a "still generating..." indicator.

The `useConsoleHistory` hook already loads from `/console/history`. Extend it to also load the latest session messages, or add a `useSessionMessages` hook.

#### 3.4 Tests

- Test that navigating away mid-response and returning shows the complete response
- Test that a partial response is visible during streaming
- Test that SSE disconnect doesn't cancel the Director's execution

**Acceptance:** Send a message, navigate away, come back — see the full response.

---

### Phase B — Tool Fork Pattern (Tier 3→4 Boundary)

**Goal:** Long-running tool calls (design_workflow, refine_plan, run_objective) survive navigation by forking to Tier 4.

#### 3.5 Tool Handler Fork Pattern

**Modified files:** Director agent tool handlers in `modules/backend/agents/mission/director/agent.py`

For each long-running tool, replace `asyncio.create_task` with a Temporal workflow start:

```python
@agent.tool
async def design_workflow(ctx, name, description):
    # 1. Persist "task started" to DB
    task_record = await create_background_task(
        mission_id=ctx.deps.mission_id,
        task_type="design_workflow",
        params={"name": name, "description": description},
    )

    # 2. Start Temporal workflow (Tier 4)
    await start_workflow(
        DesignWorkflowWorkflow.run,
        input=DesignWorkflowInput(
            mission_id=ctx.deps.mission_id,
            session_id=ctx.deps.session_id,
            name=name,
            description=description,
        ),
        id=f"design-workflow-{task_record.id}",
    )

    # 3. Return immediately to the Director
    return json.dumps({
        "status": "started_in_background",
        "task_id": task_record.id,
        "message": f"The Workflow Architect is redesigning '{name}'. "
                   "You'll see progress in the stream tab.",
    })
```

The Director responds to the user immediately. The Temporal workflow runs independently, emits events to Redis Pub/Sub, and persists the result.

#### 3.6 Background Task Tracking

**New model:** `modules/backend/models/background_task.py`

```python
class BackgroundTask(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "background_tasks"

    mission_id = Column(String(36), ForeignKey("missions.id"), nullable=False)
    session_id = Column(String(36), nullable=True)
    task_type = Column(String(100), nullable=False)  # design_workflow, run_objective, etc.
    status = Column(String(20), default="pending")   # pending, running, completed, failed
    params = Column(JSON, default=dict)
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    temporal_workflow_id = Column(String(200), nullable=True)
```

This gives the Director a way to check on background work: "Is the workflow redesign done yet?"

#### 3.7 Temporal Workflows for Tool Work

**New files:**

- `modules/backend/temporal/design_workflow_workflow.py` — DesignWorkflowWorkflow
- `modules/backend/temporal/run_objective_workflow.py` — RunObjectiveWorkflow

Each workflow:
1. Updates background_task status to "running"
2. Emits a "started" event to Redis Pub/Sub
3. Executes the actual work (Architect agent call, execution dispatch, etc.)
4. Persists the result to background_task + relevant tables
5. Emits a "completed" event to Redis Pub/Sub
6. Updates background_task status to "completed"

#### 3.8 Director: Check Background Task Tool

**Modified file:** `modules/backend/agents/mission/director/agent.py`

New tool for the Director to check on forked work:

```python
@agent.tool
async def check_background_tasks(ctx) -> str:
    """Check the status of any background work (workflow design, executions, etc.)."""
    tasks = await background_task_service.list_for_mission(
        ctx.deps.mission_id, status=["pending", "running"],
    )
    ...
```

#### 3.9 Tests

- Test that design_workflow returns immediately and the Architect runs in background
- Test that navigating away doesn't stop the Architect
- Test that the Director can check on background task status
- Test that completion events appear in the stream

**Acceptance:** Ask Director to redesign a workflow, navigate away, come back — see the completion event in the stream and the Director can report the result.

---

### Phase C — Dependency Cleanup

**Goal:** Remove dead async technologies, simplify the stack.

#### 3.10 Remove FastStream

- Remove `faststream[redis]` from `pyproject.toml`
- Delete any FastStream configuration from `config/settings/`
- Remove any FastStream imports (search for `faststream`)
- Verify no runtime code depends on it

#### 3.11 Remove TaskIQ

- Remove `taskiq` and `taskiq-redis` from `pyproject.toml`
- Remove `modules/backend/tasks/broker.py` and `modules/backend/tasks/scheduler.py`
- Keep task function implementations — they're just async functions, callable from Temporal activities
- Remove TaskIQ CLI commands from `admin.py`
- Verify no runtime code depends on it

#### 3.12 Remove asyncio.create_task for Background Work

After Phase B, all long-running background work uses Temporal. Migrate all 9 `asyncio.create_task` call sites:

| File | Line | Context | Migration |
|------|------|---------|-----------|
| `agents/mission/director/agent.py` | 363 | run_objective tool | Tier 4 fork (Phase B) |
| `agents/mission/director/agent.py` | 419 | run_workflow tool | Tier 4 fork (Phase B) |
| `api/v1/endpoints/sessions.py` | 338 | Chat send_message | Tier 3 persist-first (Phase A) |
| `api/v1/endpoints/agents.py` | 156 | Agent dispatch | Tier 4 fork |
| `api/v1/endpoints/executions.py` | 305 | Execution start | Tier 4 fork |
| `agents/mission_control/mission_control.py` | 372 | handle() agent run | Tier 3 persist-first (Phase A) |
| `agents/software/architecture/agent.py` | 163 | Status polling | Keep (short-lived, in-request) |
| `agents/software/quality/agent.py` | 304 | Status polling | Keep (short-lived, in-request) |
| `services/mission_plan_daemon.py` | 124 | Daemon startup | Keep (process lifecycle) |

#### 3.13 Update Reference Architecture

Update docs 14 and 21 to reflect the new unified model:
- Doc 14: Replace TaskIQ with Temporal for background tasks
- Doc 21: Clarify that Redis Streams (FastStream) are no longer used; Redis Pub/Sub is the sole event transport

---

### Phase D — Frontend Polish

**Goal:** The frontend handles all states gracefully.

#### 3.14 Partial Response Rendering

The chat tab renders `partial_response` messages with a visual indicator:
- Pulsing border or "..." animation
- "Still generating..." label
- Auto-refresh when the message becomes complete

#### 3.15 Background Task Indicators

The workspace header or sidebar shows active background tasks:
- "Workflow Architect: redesigning ops-health-check..." with a spinner
- Clicking navigates to the stream tab where events are visible
- Completion shows a toast

#### 3.16 Stream Tab Improvements

The stream tab already shows `system.info` events (Plan 53). Extend to show:
- Background task started/completed events
- Architect tool calls (browse_catalog, validate_workflow, save_workflow)
- Nested agent progress as collapsible groups

---

## 4  Files Changed (Summary)

| Phase | File | Action |
|-------|------|--------|
| A | `modules/backend/agents/mission_control/mission_control.py` | Incremental response persistence |
| A | `modules/backend/api/v1/endpoints/` (chat endpoint) | Don't cancel on SSE disconnect |
| A | `modules/backend/models/session.py` | Add partial_response column |
| A | `modules/backend/migrations/versions/` | Schema migration |
| A | `modules/frontend/src/pages/mission/tabs/chat-tab.tsx` | Load history on reconnect |
| B | `modules/backend/agents/mission/director/agent.py` | Tool fork pattern |
| B | `modules/backend/models/background_task.py` | New model |
| B | `modules/backend/temporal/design_workflow_workflow.py` | New workflow |
| B | `modules/backend/temporal/run_objective_workflow.py` | New workflow |
| C | `pyproject.toml` | Remove FastStream, TaskIQ |
| C | `modules/backend/tasks/broker.py` | Delete |
| C | `modules/backend/tasks/scheduler.py` | Delete |
| C | `docs/99-reference-architecture/14-*.md` | Update |
| C | `docs/99-reference-architecture/21-*.md` | Update |
| D | `modules/frontend/src/` | Partial response UI, background task indicators |

---

## 5  What Gets Deleted

| Item | Reason |
|------|--------|
| `faststream[redis]` dependency | Never used at runtime. Redis Pub/Sub serves the same purpose. |
| `taskiq`, `taskiq-redis` dependencies | Temporal replaces for Tier 4. Tier 3 doesn't need a broker. |
| `modules/backend/tasks/broker.py` | TaskIQ broker config — no longer needed |
| `modules/backend/tasks/scheduler.py` | TaskIQ scheduler config — Temporal schedules replace |
| `asyncio.create_task` in Director tools | Replaced by Tier 4 fork pattern |

---

## 6  Exit Criteria

1. User sends chat message, navigates away, returns — sees complete response
2. Director's design_workflow tool returns immediately; Architect work continues in background
3. Stream tab shows Architect progress events during background work
4. Completion toast appears when background work finishes
5. `pip install` no longer pulls FastStream or TaskIQ
6. Zero `asyncio.create_task` calls in agent tool handlers
7. Reference architecture docs updated to reflect unified model

---

## 7  Estimated Effort

| Phase | Scope | Effort |
|-------|-------|--------|
| A | Persist-first chat + SSE disconnect handling | ~3-4 hours |
| B | Tool fork pattern + background task model + Temporal workflows | ~4-5 hours |
| C | Remove FastStream, TaskIQ, create_task cleanup | ~1-2 hours |
| D | Frontend polish (partial response, task indicators) | ~2-3 hours |
| **Total** | | **~10-14 hours** |

---

## 8  Decision Framework (from ADR-004)

For any new feature, ask one question:

> **"Does this work need to survive a backend process crash?"**

- **No** → Tier 3. In-process async. Persist-first SSE. Redis Pub/Sub for events.
- **Yes** → Tier 4. Temporal workflow. Redis Pub/Sub for events.

No other async technologies. No decision trees. One question, one answer.

---

## 9  Audit Notes (2026-04-14)

### Already exists — DO NOT rebuild

| Item | File | What exists |
|------|------|-------------|
| `ChatTurnWorkflow` | `temporal/chat_workflow.py` | Two-activity workflow: persist_user_message + execute_chat_turn. Build on this, don't duplicate. |
| SSE disconnect handling | `api/v1/endpoints/sessions.py:338-352` | Background task already continues after SSE cancel. Needs incremental persistence added. |
| User message persistence | `api/v1/endpoints/sessions.py:303` | User message persisted synchronously before background task starts. |
| MissionEventHandler | `core/logging.py` | Plan 53 — logger→Redis→SSE bridge. All Tier 4 activities already emit via this. |

### Needs building (verified not present)

| Item | Details |
|------|---------|
| `partial_response` column | Not on `session_messages`. New migration needed. |
| `background_tasks` table | No generic task tracker exists. New model + migration. |
| `DesignWorkflowWorkflow` | No Temporal workflow for Architect delegation. Currently uses `asyncio.create_task`. |
| `RunObjectiveWorkflow` | No Temporal workflow for execution dispatch from tools. Currently uses `asyncio.create_task`. |

### asyncio.create_task inventory (9 call sites)

| Call site | Tier | Migration |
|-----------|------|-----------|
| Director: run_objective | 4 | New Temporal workflow |
| Director: run_workflow | 4 | New Temporal workflow |
| sessions.py: send_message | 3 | Persist-first pattern (Phase A) |
| agents.py: agent dispatch | 4 | New Temporal workflow |
| executions.py: start execution | 4 | New Temporal workflow |
| mission_control.py: handle() | 3 | Persist-first pattern (Phase A) |
| architecture agent: polling | Keep | Short-lived, in-request |
| quality agent: polling | Keep | Short-lived, in-request |
| mission_plan_daemon: startup | Keep | Process lifecycle |
