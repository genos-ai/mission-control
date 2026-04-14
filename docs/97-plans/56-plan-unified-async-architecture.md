# Plan 56 — Unified Async Architecture: Three-Layer Execution Model

| Field | Value |
|-------|-------|
| **Status** | Ready |
| **Created** | 2026-04-14 |
| **Updated** | 2026-04-14 |
| **Depends on** | Plan 53 (MissionEventHandler — done), Plan 52 (Temporal Backbone — done) |
| **ADR** | docs/02-architecture/004-adr-unified-async-architecture.md |
| **Target** | Chat persistence, tool fork pattern, Temporal consolidation, dependency cleanup |

---

## 1  Problem

Five async technologies serve overlapping purposes. The user-facing symptoms:

1. **Director chat responses disappear on navigation** — the response streams via SSE tied to the HTTP connection. Navigate away → connection drops → response lost. The Architect's 30-second workflow redesign vanishes.

2. **Simple "hi" messages are slow through Temporal** — 300-400ms scheduling overhead for a message that needs zero durability.

3. **Two cron systems running side by side** — Temporal Schedules dispatch ready plans every 5s. TaskIQ scheduler runs 6 maintenance cron tasks (cleanup, health, workflow schedules). Same codebase, two schedulers, two processes.

4. **Lightweight Temporal activities waste scheduling hops** — `persist_user_message`, `approve_proposed_tasks`, `fetch_plan_task_counts` each round-trip through the Temporal server (~300ms) for a DB write that takes <10ms. The supervisor loop loses ~1s per iteration to scheduling overhead.

5. **No clear decision framework** — developers choose between Temporal, TaskIQ, FastStream, asyncio.create_task, and synchronous SSE based on gut feeling.

---

## 2  Target Architecture

Three layers. Three technologies. Zero overlap. One decision question.

```
COMPUTE
├── In-process async ──── user chat, fast tool calls (<30s)
└── Temporal
    ├── Workflows ──────── mission runs, supervisor loop, workflow runs
    ├── Local activities ── DB writes, queries, state flips (no scheduling hop)
    ├── Regular activities ─ LLM calls, agent execution (heavy, retryable)
    └── Schedules ───────── cleanup, health checks, workflow schedules, plan dispatch

BROADCAST
└── Redis Pub/Sub ──────── one channel per mission, real-time to SSE

PERSISTENCE
└── PostgreSQL ─────────── messages, events, execution records, everything

REMOVED
├── FastStream ─────────── architecturally superseded by Temporal
├── TaskIQ ─────────────── migrated to Temporal Schedules
└── Fire-and-forget create_task in Director tools ── forked to Temporal
```

**Decision question:** "Does this work need to survive a backend process crash?"
- **No** → In-process async. Persist-first SSE. Redis Pub/Sub for events.
- **Yes** → Temporal workflow. Redis Pub/Sub for events.

### Event Architecture

One path, two destinations:

```
  Something happens
  (agent responds, error occurs, task completes, workflow finishes)
        │
        ▼
  SessionEventBus.publish()
        │
        ├──▶ Redis Pub/Sub: mission_events:{mission_id}
        │         │
        │         ▼
        │    SSE endpoint → browser (real-time)
        │
        └──▶ PostgreSQL: mission_events table (configured types)
                  │
                  ▼
             Console history on page load / reconnect
```

No domain events, no consumer groups, no Streams. One publish, two destinations, two consumption patterns.

### ChatTurnWorkflow Decision

`ChatTurnWorkflow` **stays** for system-initiated Director turns (supervisor loop, scheduled triggers) where durability matters and nobody watches tokens stream.

User-initiated chat **bypasses** `ChatTurnWorkflow` and uses the in-process persist-first path. Low latency matters more than crash durability for interactive chat.

---

## 3  Phases

### Phase A — Persist-First Chat

**Goal:** Chat responses survive navigation. No new infrastructure — just persistence changes.

#### 3.1 Incremental Response Persistence

**Modified file:** `modules/backend/agents/mission_control/mission_control.py` (handle function)

Currently, the assistant message is persisted AFTER the full stream completes. If the backend crashes or the response coroutine is interrupted, the response is lost.

Change: persist incrementally during streaming.

```python
# Current: persist after stream completes
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
# Final persist — move content, mark complete
await session_service.finalize_response(session_id, accumulated)
```

**Schema change:** Add `status` column to `session_messages`:

```sql
ALTER TABLE session_messages ADD COLUMN status VARCHAR(20) DEFAULT 'complete';
-- Values: 'streaming', 'complete', 'failed'
```

During streaming, content is written directly to the `content` column with `status = 'streaming'`. On completion, `status` is set to `'complete'`. No dual-column confusion — one column for content, one for state.

#### 3.2 SSE Disconnect Handling

**Status: Already implemented** in `api/v1/endpoints/sessions.py:338-352`.

The background `_run_agent()` task already continues after `CancelledError`. It has its own DB session and Redis connection. **No code changes needed** — verify with a test only.

The new incremental persistence (3.1) means the response is written to DB as it streams, so even if the SSE drops, the data is already persisted. When the frontend reconnects and loads history, it sees the complete (or in-progress) response.

#### 3.3 Frontend: Load History on Reconnect

**Modified file:** `modules/frontend/src/pages/mission/tabs/chat-tab.tsx`

On mount or SSE reconnect, fetch the latest session messages from DB. If there's a message with `status = 'streaming'`, show it with a "still generating..." indicator.

The `useConsoleHistory` hook already loads from `/console/history`. Extend it to also load the latest session messages, or add a `useSessionMessages` hook.

#### 3.4 Tests

- Test that navigating away mid-response and returning shows the complete response
- Test that a streaming-status message is visible during generation
- Test that SSE disconnect doesn't cancel the Director's execution (verify existing behaviour)

**Acceptance:** Send a message, navigate away, come back — see the full response.

---

### Phase B — Tool Fork Pattern (In-Process → Temporal Boundary)

**Goal:** Long-running tool calls survive navigation by forking to Temporal.

#### 3.5 Tool Handler Fork Pattern

**Modified files:** Director agent tool handlers in `modules/backend/agents/mission/director/agent.py`

Three tools need migration:

| Tool | Current behaviour | Migration |
|---|---|---|
| `run_objective` (line 363) | `asyncio.create_task` — fire-and-forget | Fork to Temporal workflow |
| `run_workflow` (line 419) | `asyncio.create_task` — fire-and-forget | Fork to Temporal workflow |
| `design_workflow` (line 544) | **Synchronous `await`** — blocks Director for 30s+ | Fork to Temporal workflow |

For each tool, the pattern is:

```python
@agent.tool
async def design_workflow(ctx, name, description):
    # 1. Record the background work in ExecutionRecord
    record = await execution_service.create_record(
        mission_id=ctx.deps.mission_id,
        agent_name="workflow.architect.agent",
        task_type="design_workflow",
        params={"name": name, "description": description},
    )

    # 2. Start Temporal workflow
    await start_workflow(
        DesignWorkflowWorkflow.run,
        input=DesignWorkflowInput(...),
        id=f"design-workflow-{record.id}",
    )

    # 3. Return immediately — Director responds to user
    return json.dumps({
        "status": "started_in_background",
        "execution_id": record.id,
        "message": f"The Workflow Architect is redesigning '{name}'. "
                   "You'll see progress in the stream tab.",
    })
```

#### 3.6 Background Task Tracking

**Decision: Extend `ExecutionRecord` instead of creating a new `background_tasks` table.**

Plan 53 established ExecutionRecord as the universal "something ran" entity. Adding a second tracking table means two places to query "what's running for this mission?"

Add to ExecutionRecord:

```python
task_type = Column(String(100), nullable=True)   # design_workflow, run_objective, etc.
params = Column(JSON, nullable=True)              # input parameters
temporal_workflow_id = Column(String(200), nullable=True)
```

The Director's `check_background_tasks` tool queries ExecutionRecord. One table, one query, one concept.

#### 3.7 Temporal Workflows for Tool Work

**New files:**

- `modules/backend/temporal/design_workflow_workflow.py` — DesignWorkflowWorkflow
- `modules/backend/temporal/run_objective_workflow.py` — RunObjectiveWorkflow

Each workflow:
1. Updates ExecutionRecord status to "running"
2. Emits a "started" event to Redis Pub/Sub
3. Executes the actual work (Architect agent call, execution dispatch, etc.)
4. Persists the result to ExecutionRecord + relevant tables
5. Emits a "completed" event to Redis Pub/Sub
6. Updates ExecutionRecord status to "completed" / "failed"

#### 3.8 Director: Check Background Work Tool

**Modified file:** `modules/backend/agents/mission/director/agent.py`

New tool for the Director to check on forked work:

```python
@agent.tool
async def check_background_tasks(ctx) -> str:
    """Check the status of any background work (workflow design, executions, etc.)."""
    records = await execution_service.list_active(ctx.deps.mission_id)
    ...
```

#### 3.9 Tests

- Test that design_workflow returns immediately and the Architect runs in background
- Test that navigating away doesn't stop the Architect
- Test that the Director can check on background task status
- Test that completion events appear in the stream

**Acceptance:** Ask Director to redesign a workflow, navigate away, come back — see the completion event in the stream and the Director can report the result.

---

### Phase C — Temporal Consolidation + Dependency Cleanup

**Goal:** One scheduler, remove dead dependencies, optimise activity scheduling.

#### 3.10 Migrate TaskIQ Cron Tasks to Temporal Schedules

**Current TaskIQ tasks** (from `modules/backend/tasks/scheduled.py`):

| Task | Cron | Migration |
|---|---|---|
| `daily_cleanup` | `0 2 * * *` | Temporal Schedule → activity |
| `hourly_health_check` | `0 * * * *` | Temporal Schedule → activity |
| `weekly_report_generation` | `0 6 * * 0` | Temporal Schedule → activity |
| `metrics_aggregation` | `*/15 * * * *` | Temporal Schedule → activity |
| `cleanup_stale_environments` | `0 * * * *` | Temporal Schedule → activity |
| `evaluate_workflow_schedules` | `* * * * *` | Temporal Schedule → activity |

**Pattern:** Each task function is already a plain async function. Wrap it as a Temporal activity, create a one-activity workflow, register a Temporal Schedule. Same pattern as existing `ScheduledMissionCheckWorkflow`.

**New files:**
- `modules/backend/temporal/maintenance_workflow.py` — MaintenanceWorkflow (generic wrapper)
- `modules/backend/temporal/maintenance_activities.py` — Activity wrappers for each task

**Schedule creation:** Add to `modules/backend/main.py` lifespan alongside existing `mission-plan-dispatch-schedule`.

#### 3.11 Migrate Local Activities

Convert lightweight activities from regular to local:

| Activity | Change |
|---|---|
| `persist_user_message` | `execute_activity` → `execute_local_activity` |
| `persist_mission_outcome` | `execute_activity` → `execute_local_activity` |
| `send_notification` | `execute_activity` → `execute_local_activity` |
| `approve_proposed_tasks` | `execute_activity` → `execute_local_activity` |
| `fetch_plan_task_counts` | `execute_activity` → `execute_local_activity` |
| `find_ready_plans` | `execute_activity` → `execute_local_activity` |

**Modified files:** All workflow files that call these activities:
- `modules/backend/temporal/chat_workflow.py`
- `modules/backend/temporal/workflow.py`
- `modules/backend/temporal/mission_run_workflow.py`
- `modules/backend/temporal/scheduled_workflow.py`

**Important:** Local activities must use `schedule_to_close_timeout` instead of `start_to_close_timeout`. Set to 30 seconds for DB operations.

**Important:** Local activities still need to open their own DB sessions (they already do). They run in the workflow worker process but are NOT subject to Temporal's determinism constraints — they're allowed to do I/O.

#### 3.12 Remove FastStream

- Remove `faststream[redis]` from `pyproject.toml`
- Delete `modules/backend/events/broker.py` (FastStream RedisBroker setup)
- Delete `modules/backend/events/middleware.py` (EventObservabilityMiddleware)
- Delete `modules/backend/events/publishers.py` (EventPublisher — gated by disabled flag)
- Remove `event-worker` command from `admin.py`
- Remove `events_publish_enabled` feature flag from `config/settings/features.yaml`
- Keep `modules/backend/events/bus.py` (SessionEventBus — active, uses Redis Pub/Sub)
- Keep `modules/backend/events/types.py` (SessionEvent types — active)
- Verify no runtime code depends on removed files

#### 3.13 Remove TaskIQ

**After** Phase C.10 (cron migration to Temporal) is complete and verified:

- Remove `taskiq`, `taskiq-redis`, `taskiq-aiohttp` from `pyproject.toml`
- Delete `modules/backend/tasks/broker.py` (TaskIQ broker config)
- Delete `modules/backend/tasks/scheduler.py` (TaskIQ scheduler config)
- Keep `modules/backend/tasks/scheduled.py` — the task functions remain as plain async functions, now called from Temporal activities
- Keep `modules/backend/tasks/workflow_scheduler.py` — `evaluate_workflow_schedules()` stays as a function, called from Temporal activity
- Remove `worker` and `scheduler` CLI commands from `admin.py`
- Update any process management scripts / documentation

#### 3.14 Migrate asyncio.create_task Call Sites

After Phases A and B, migrate remaining fire-and-forget call sites:

| Call site | Current pattern | Migration |
|-----------|----------------|-----------|
| `director/agent.py:363` — run_objective | Fire-and-forget | Temporal workflow (Phase B) |
| `director/agent.py:419` — run_workflow | Fire-and-forget | Temporal workflow (Phase B) |
| `director/agent.py:544` — design_workflow | **Synchronous blocking** | Temporal workflow (Phase B) |
| `sessions.py:338` — send_message | Awaited (SSE streams) | Keep — add incremental persistence (Phase A) |
| `agents.py:156` — agent dispatch | Fire-and-forget | Temporal workflow |
| `executions.py:305` — execution start | Fire-and-forget | Temporal workflow |
| `mission_control.py:372` — handle() | Awaited (SSE streams) | Keep — add incremental persistence (Phase A) |
| `architecture/agent.py:163` — polling | Short-lived, in-request | **Keep** |
| `quality/agent.py:304` — polling | Short-lived, in-request | **Keep** |
| `mission_plan_daemon.py:124` — startup | Process lifecycle | **Keep** |

**Pattern classification:**
- **Fire-and-forget** → migrate to Temporal (no persistence, no error visibility)
- **Awaited** → keep, add incremental persistence
- **Short-lived / lifecycle** → keep (appropriate use of create_task)

#### 3.15 Update Reference Architecture

Update docs 14 and 21 to reflect the unified model:
- Doc 14: Replace TaskIQ with Temporal for background tasks and scheduling
- Doc 21: Clarify that Redis Streams (FastStream) are no longer used; Redis Pub/Sub is the sole event transport. Temporal replaces the durable domain event bus.

---

### Phase D — Frontend Polish

**Goal:** The frontend handles all states gracefully.

#### 3.16 Partial Response Rendering

The chat tab renders `status = 'streaming'` messages with a visual indicator:
- Pulsing border or "..." animation
- "Still generating..." label
- Auto-refresh when the message status becomes `'complete'`

#### 3.17 Background Task Indicators

The workspace header or sidebar shows active background tasks:
- "Workflow Architect: redesigning ops-health-check..." with a spinner
- Clicking navigates to the stream tab where events are visible
- Completion shows a toast

#### 3.18 Stream Tab Improvements

The stream tab already shows `system.info` events (Plan 53). Extend to show:
- Background task started/completed events
- Architect tool calls (browse_catalog, validate_workflow, save_workflow)
- Nested agent progress as collapsible groups

---

## 4  Files Changed (Summary)

| Phase | File | Action |
|-------|------|--------|
| A | `modules/backend/agents/mission_control/mission_control.py` | Incremental response persistence |
| A | `modules/backend/models/session.py` | Add `status` column to session_messages |
| A | `modules/backend/migrations/versions/` | Schema migration |
| A | `modules/frontend/src/pages/mission/tabs/chat-tab.tsx` | Load history on reconnect |
| B | `modules/backend/agents/mission/director/agent.py` | Tool fork pattern (3 tools) |
| B | `modules/backend/models/execution.py` | Add task_type, params, temporal_workflow_id to ExecutionRecord |
| B | `modules/backend/temporal/design_workflow_workflow.py` | New workflow |
| B | `modules/backend/temporal/run_objective_workflow.py` | New workflow |
| C | `modules/backend/temporal/maintenance_workflow.py` | New: generic cron wrapper workflow |
| C | `modules/backend/temporal/maintenance_activities.py` | New: activity wrappers for cron tasks |
| C | `modules/backend/main.py` | Register Temporal Schedules for cron tasks |
| C | `modules/backend/temporal/chat_workflow.py` | Local activities for lightweight ops |
| C | `modules/backend/temporal/workflow.py` | Local activities for lightweight ops |
| C | `modules/backend/temporal/mission_run_workflow.py` | Local activities for lightweight ops |
| C | `modules/backend/temporal/scheduled_workflow.py` | Local activities for lightweight ops |
| C | `pyproject.toml` | Remove FastStream, TaskIQ |
| C | `modules/backend/events/broker.py` | Delete |
| C | `modules/backend/events/middleware.py` | Delete |
| C | `modules/backend/events/publishers.py` | Delete |
| C | `modules/backend/tasks/broker.py` | Delete |
| C | `modules/backend/tasks/scheduler.py` | Delete |
| C | `modules/backend/admin.py` | Remove event-worker, worker, scheduler commands |
| C | `docs/99-reference-architecture/14-*.md` | Update |
| C | `docs/99-reference-architecture/21-*.md` | Update |
| D | `modules/frontend/src/` | Partial response UI, background task indicators |

---

## 5  What Gets Removed

| Item | Reason |
|------|--------|
| `faststream[redis]` dependency | Architecturally superseded by Temporal. Domain event consumers are a microservices pattern; Mission Control is a monolith. Feature flag off, zero consumers. |
| `modules/backend/events/broker.py` | FastStream RedisBroker config — no longer needed |
| `modules/backend/events/middleware.py` | FastStream observability middleware — no longer needed |
| `modules/backend/events/publishers.py` | EventPublisher gated by disabled flag — no longer needed |
| `taskiq`, `taskiq-redis` dependencies | Temporal Schedules replace. One scheduler, not two. |
| `modules/backend/tasks/broker.py` | TaskIQ broker config — no longer needed |
| `modules/backend/tasks/scheduler.py` | TaskIQ scheduler config — Temporal schedules replace |
| `asyncio.create_task` in Director tools | Fire-and-forget replaced by Temporal fork pattern |
| `asyncio.create_task` for blocking tools | Synchronous blocking replaced by Temporal fork pattern |
| `event-worker` CLI command | No FastStream consumer process needed |
| `worker` / `scheduler` CLI commands | No TaskIQ process needed |

---

## 6  Exit Criteria

1. User sends chat message, navigates away, returns — sees complete response
2. Director's design_workflow tool returns immediately; Architect work continues in background
3. Stream tab shows Architect progress events during background work
4. Completion toast appears when background work finishes
5. `pip install` no longer pulls FastStream or TaskIQ
6. All 6 TaskIQ cron tasks run via Temporal Schedules
7. Zero `asyncio.create_task` calls in agent tool handlers (fire-and-forget or blocking)
8. Lightweight activities use `execute_local_activity` (6 activities migrated)
9. Reference architecture docs updated to reflect unified model
10. One Temporal worker process, one scheduler — no TaskIQ processes

---

## 7  Decision Framework (from ADR-004)

For any new feature, ask one question:

> **"Does this work need to survive a backend process crash?"**

- **No** → In-process async. Persist-first SSE. Redis Pub/Sub for events.
- **Yes** → Temporal workflow. Redis Pub/Sub for events.

No other async technologies. No decision trees. One question, one answer.

---

## 8  Audit Notes (2026-04-14)

### Already exists — DO NOT rebuild

| Item | File | What exists |
|------|------|-------------|
| `ChatTurnWorkflow` | `temporal/chat_workflow.py` | Two-activity workflow: persist_user_message + execute_chat_turn. **Stays for system-initiated Director turns.** User-initiated chat bypasses it. |
| SSE disconnect handling | `api/v1/endpoints/sessions.py:338-352` | Background task already continues after SSE cancel. **No changes needed** — just add incremental persistence. |
| User message persistence | `api/v1/endpoints/sessions.py:303` | User message persisted synchronously before background task starts. |
| MissionEventHandler | `core/logging.py` | Plan 53 — logger→Redis→SSE bridge. All activities already emit via this. |
| `ScheduledMissionCheckWorkflow` | `temporal/scheduled_workflow.py` | Temporal Schedule fires every 5s. Pattern to follow for cron task migration. |

### Needs building (verified not present)

| Item | Details |
|------|---------|
| `status` column on session_messages | No streaming state tracking. New migration needed. |
| `task_type` / `params` on ExecutionRecord | No background task discrimination. Migration to extend existing model. |
| `DesignWorkflowWorkflow` | No Temporal workflow for Architect delegation. `design_workflow` tool currently **blocks synchronously** (not create_task). |
| `RunObjectiveWorkflow` | No Temporal workflow for execution dispatch from tools. Currently uses `asyncio.create_task` (fire-and-forget). |
| `MaintenanceWorkflow` | No generic cron wrapper workflow. Needed for TaskIQ migration. |
| Temporal Schedules for 6 cron tasks | Only `mission-plan-dispatch-schedule` exists. 6 TaskIQ tasks need schedule registration. |

### asyncio.create_task inventory (9 call sites)

| Call site | Pattern | Migration |
|-----------|---------|-----------|
| Director: run_objective (line 363) | Fire-and-forget | Temporal workflow (Phase B) |
| Director: run_workflow (line 419) | Fire-and-forget | Temporal workflow (Phase B) |
| Director: design_workflow (line 544) | **Synchronous blocking** | Temporal workflow (Phase B) |
| sessions.py: send_message (line 338) | Awaited | Keep — add incremental persistence (Phase A) |
| agents.py: agent dispatch (line 156) | Fire-and-forget | Temporal workflow (Phase C) |
| executions.py: start execution (line 305) | Fire-and-forget | Temporal workflow (Phase C) |
| mission_control.py: handle() (line 372) | Awaited | Keep — add incremental persistence (Phase A) |
| architecture agent: polling (line 163) | Short-lived, in-request | **Keep** |
| quality agent: polling (line 304) | Short-lived, in-request | **Keep** |
| mission_plan_daemon: startup (line 124) | Process lifecycle | **Keep** |

### TaskIQ cron task inventory (6 tasks)

| Task | Cron | File |
|------|------|------|
| `daily_cleanup` | `0 2 * * *` | `tasks/scheduled.py` |
| `hourly_health_check` | `0 * * * *` | `tasks/scheduled.py` |
| `weekly_report_generation` | `0 6 * * 0` | `tasks/scheduled.py` |
| `metrics_aggregation` | `*/15 * * * *` | `tasks/scheduled.py` |
| `cleanup_stale_environments` | `0 * * * *` | `tasks/scheduled.py` |
| `evaluate_workflow_schedules` | `* * * * *` | `tasks/workflow_scheduler.py` |

### Local activity candidates (6 activities)

| Activity | Current timeout | Why local |
|---|---|---|
| `persist_user_message` | 30s | Single DB write |
| `persist_mission_outcome` | 30s | Single DB write |
| `send_notification` | 60s | Stub — just logs |
| `approve_proposed_tasks` | — | Idempotent DB flip |
| `fetch_plan_task_counts` | — | DB query |
| `find_ready_plans` | 30s | DB query |
