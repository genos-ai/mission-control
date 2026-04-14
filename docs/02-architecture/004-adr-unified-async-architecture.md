# ADR-004: Unified Async Architecture — Three-Layer Execution Model

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-14 |
| **Updated** | 2026-04-14 |
| **Deciders** | Platform team |
| **Supersedes** | Ad-hoc mix of Temporal, TaskIQ, FastStream, asyncio.create_task |

---

## Context

Mission Control accumulated five overlapping async/messaging technologies:

| Technology | Original Purpose | Actual Usage |
|-----------|-----------------|-------------|
| **Temporal** | Durable workflow execution | Active — mission runs, supervisor loop, scheduled dispatch |
| **Redis Pub/Sub** | Real-time event streaming | Active — SSE stream, MissionEventHandler |
| **FastStream** | Redis Streams consumer groups | Dormant — infrastructure built (Plan 10), feature flag off, zero consumers registered |
| **TaskIQ** | Background task broker / scheduler | Active — 6 cron tasks (cleanup, health checks, workflow schedule evaluation) |
| **asyncio.create_task** | Fire-and-forget background work | Active — Director tool calls (fragile, no persistence or error visibility) |

This fragmentation caused real user-facing problems:

1. **Invisible errors** — Temporal activity failures only logged to files, not streamed to the user
2. **Lost context on navigation** — Director chat responses streamed via SSE disappear when the user navigates away
3. **Latency overhead** — User-initiated chat routed through Temporal added 300-400ms scheduling overhead per message
4. **Two cron systems** — Temporal Schedules (plan dispatch every 5s) AND TaskIQ scheduler (6 maintenance cron tasks) run side by side for the same codebase
5. **No clear decision framework** — Developers couldn't determine which technology to use for new features

### Why FastStream was included (and why it's no longer needed)

The reference architecture (Doc 21) designed a two-bus event system:

- **Redis Pub/Sub** — ephemeral real-time events (agent lifecycle, SSE streaming)
- **Redis Streams via FastStream** — durable domain events with consumer groups, ACK, DLQ, and replay

This two-bus model is a microservices pattern: Service A publishes `order.completed`, Services B/C/D subscribe independently. Mission Control is a **monolith** — modules call each other directly through service layers. There are no independent subscribers that need decoupled event delivery.

Furthermore, Temporal now handles all durable cross-module orchestration (supervisor→Director turns, workflow dispatch, scheduled checks). The durable domain event bus that FastStream was meant to provide is architecturally superseded by Temporal workflows and activities. If Mission Control decomposes into microservices in the future, a durable event bus should be reconsidered — but that's a different architecture.

### Why TaskIQ overlaps with Temporal

TaskIQ runs 6 scheduled tasks via a separate scheduler process. Temporal already runs scheduled workflows (e.g., `ScheduledMissionCheckWorkflow` every 5 seconds). Both provide:

- Cron syntax scheduling
- Retry on failure
- Worker-based execution

Running two schedulers for the same codebase means two places to look for scheduled work, two processes to keep alive, and two failure modes to debug. Since Temporal is already the execution backbone, all scheduled work should consolidate there.

## Decision

Adopt a **three-layer execution model**. Each layer uses exactly one technology. No layer requires choosing between alternatives.

### The Three Layers

```
┌─────────────────────────────────────────────────────┐
│                     COMPUTE                          │
│                                                      │
│   In-process async          Temporal                 │
│   (user chat, fast tools)   (durable work)           │
│                              ├─ Workflows            │
│                              ├─ Regular activities    │
│                              │  (heavy: LLM, agents) │
│                              ├─ Local activities      │
│                              │  (light: DB writes,    │
│                              │   queries, state flips)│
│                              └─ Schedules             │
│                                 (all cron work)       │
├─────────────────────────────────────────────────────┤
│                   BROADCAST                          │
│                                                      │
│   Redis Pub/Sub                                      │
│   (real-time event fan-out to all listeners)         │
│                                                      │
├─────────────────────────────────────────────────────┤
│                   PERSISTENCE                        │
│                                                      │
│   PostgreSQL                                         │
│   (messages, events, execution records, everything)  │
│                                                      │
└─────────────────────────────────────────────────────┘
```

### Compute: The Decision Question

For any new feature, one question:

> **"Does this work need to survive a backend process crash?"**

- **No** → In-process async. Persist-first SSE. Redis Pub/Sub for events.
- **Yes** → Temporal workflow. Redis Pub/Sub for events.

Chat messages, tool calls that complete in <30s, single-agent tasks → in-process.
Mission plan dispatch, multi-step workflows, scheduled jobs, autonomous loops → Temporal.

### In-Process Path — User-Initiated Chat

When a user sends a chat message:

1. User message persisted to DB immediately (already done)
2. Director runs in-process — same as today's SSE stream
3. Director's response chunks are **persisted as they stream** (incremental DB writes)
4. All events emit to Redis Pub/Sub (real-time) AND persist to `mission_events` (durable)
5. If the SSE connection drops, the backend **continues to completion** (already implemented in sessions.py)
6. When the frontend reconnects, it loads the full conversation from DB — including any in-progress or completed response it missed

If the backend process crashes mid-response, the user sees a partial response and can retry — acceptable for interactive chat.

### Temporal Path — Durable Execution

Temporal handles all work that must survive crashes:

- **Workflows:** Mission runs, supervisor loop, workflow runs, system-initiated Director turns
- **Regular activities:** Heavy work (LLM calls, agent execution, multi-step dispatch) — scheduled through Temporal server, retryable, independently recoverable
- **Local activities:** Lightweight operations (DB writes, queries, state flips) — executed in the workflow worker process with no scheduling hop, still recorded in workflow history
- **Schedules:** All cron work (cleanup, health checks, workflow schedule evaluation, plan dispatch)

### In-Process → Temporal Boundary Crossing

When a chat message triggers long-running work (e.g., Director calls `design_workflow`):

1. The Director's tool handler **persists a "task started" record** to the DB
2. The tool **starts a Temporal workflow** for the heavy work
3. The Director returns immediately: "I've asked the Architect to redesign the workflow — you'll see updates in the stream"
4. The Temporal workflow emits events to Redis Pub/Sub independently of the chat SSE connection
5. When the work completes, it persists the result and emits a completion event
6. The Director can be asked about the result in a subsequent message

### ChatTurnWorkflow: System-Initiated vs User-Initiated

`ChatTurnWorkflow` remains for **system-initiated** Director turns (supervisor loop calls `start_director_turn`, scheduled triggers). These have no human watching for real-time tokens — durability matters more than latency.

**User-initiated** chat bypasses `ChatTurnWorkflow` and uses the in-process path. The human is watching tokens stream — low latency matters, and crash durability is unnecessary.

### Broadcast: Event Architecture

One path, two destinations:

```
  Something happens
  (agent responds, error occurs, task completes, workflow finishes)
        │
        ▼
  SessionEventBus.publish()
        │
        ├──▶ Redis Pub/Sub channel: mission_events:{mission_id}
        │         │
        │         ▼
        │    SSE endpoint subscribes → browser receives real-time
        │
        └──▶ PostgreSQL: mission_events table (configured types)
                  │
                  ▼
             Console history on page load / reconnect
```

No domain events, no consumer groups, no Streams. One publish call, two destinations (ephemeral + durable), two consumption patterns (live SSE + history query).

### What Gets Removed

| Technology | Action | Reason |
|-----------|--------|--------|
| **FastStream** | Remove dependency and config | Architecturally superseded by Temporal. Domain event consumers are a microservices pattern; Mission Control is a monolith. Zero consumers registered. |
| **TaskIQ** | Migrate 6 cron tasks to Temporal Schedules, then remove | Temporal already runs schedules. Two schedulers for one codebase is unnecessary complexity. |
| **asyncio.create_task** (fire-and-forget) | Replace with Temporal workflow start | Director tools (run_objective, run_workflow) lose results on crash. Fork to Temporal for durability. |
| **asyncio.create_task** (blocking tool calls) | Replace with Temporal workflow start | Director tools (design_workflow) block for 30+ seconds. Fork to Temporal so the Director returns immediately. |

### What Stays

| Technology | Responsibility |
|-----------|---------------|
| **Temporal** | All durable compute: workflows, activities (regular + local), schedules |
| **Redis Pub/Sub** | Real-time event broadcast to SSE listeners |
| **PostgreSQL** | Source of truth: messages, events, execution records, all state |
| **In-process async** | User-initiated chat, fast tool calls (<30s) |

### Temporal: Local Activities Optimisation

Activities that perform only lightweight I/O (DB writes, queries, state flips) should use `workflow.execute_local_activity` instead of `workflow.execute_activity`. This eliminates the Temporal server scheduling hop (~300ms) while still recording the operation in workflow history for replay.

| Activity | Type | Reason |
|---|---|---|
| `persist_user_message` | **Local** | Single DB write, <10ms |
| `persist_mission_outcome` | **Local** | Single DB write |
| `send_notification` | **Local** | Currently a stub (logs only) |
| `approve_proposed_tasks` | **Local** | Idempotent DB state flip |
| `fetch_plan_task_counts` | **Local** | DB query, returns counts |
| `find_ready_plans` | **Local** | DB query |
| `evaluate_post_run` | Regular | Runs LLM call, can take 30s+ |
| `execute_chat_turn` | Regular | Agent run, minutes |
| `execute_mission` | Regular | Full mission execution, hours |
| `start_director_turn` | Regular | Starts nested workflow |

This removes ~1 second of pure scheduling overhead per supervisor loop iteration (3 lightweight activities × ~300ms each).

## End State

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

Three technologies. Zero overlap. One decision question.

## Consequences

**Positive:**
- One decision question, not five technology choices
- Three technologies with zero overlap (Temporal, Redis Pub/Sub, PostgreSQL)
- Chat latency drops to near-zero (no Temporal scheduling hop for user messages)
- Navigation-safe: all state persisted, events survive reconnection
- Simpler dependency tree (remove FastStream, TaskIQ)
- Supervisor loop ~1s faster per iteration (local activities)
- One scheduler (Temporal) instead of two (Temporal + TaskIQ)
- MissionEventHandler already bridges logger→events (built in Plan 53)

**Negative:**
- In-process chat doesn't survive process crashes (acceptable for interactive use)
- In-process→Temporal boundary crossing adds complexity to tool handlers
- Existing Director tool calls need migration (create_task → Temporal, blocking → Temporal fork)
- Two compute models to understand (in-process vs Temporal)

**Risks:**
- The boundary crossing pattern must be carefully implemented — if the Director doesn't return a meaningful message before forking, the user sees a spinner then nothing
- The persist-first SSE pattern requires careful handling of partial responses in the DB
- Local activities share the workflow worker's thread — a slow "local" activity would block the worker. Only use for genuinely lightweight operations.

## References

- Doc 46: Event-Driven Session Architecture (§Graduated Complexity)
- Doc 14: Background Tasks (TaskIQ — superseded by Temporal Schedules)
- Doc 21: Event Architecture (two-bus model — Streams bus superseded by Temporal)
- Doc 40: Agentic Architecture (orchestration patterns)
- Plan 53: Workflow DB + centralised MissionEventHandler (prerequisite)
