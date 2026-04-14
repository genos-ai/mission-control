# ADR-004: Unified Async Architecture — Tier-Based Execution Model

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-14 |
| **Deciders** | Platform team |
| **Supersedes** | Ad-hoc mix of Temporal, TaskIQ, FastStream, asyncio.create_task |

---

## Context

Mission Control accumulated five overlapping async/messaging technologies:

| Technology | Original Purpose | Actual Usage |
|-----------|-----------------|-------------|
| **Temporal** | Durable workflow execution | Active — mission runs, supervisor loop, scheduled dispatch |
| **Redis Pub/Sub** | Real-time event streaming | Active — SSE stream, MissionEventHandler |
| **FastStream** | Redis Streams consumer groups | Config only — never became load-bearing |
| **TaskIQ** | Background task broker | In requirements — barely used |
| **asyncio.create_task** | Fire-and-forget background work | Active — Director tool calls (fragile) |

This fragmentation caused real user-facing problems:

1. **Invisible errors** — Temporal activity failures only logged to files, not streamed to the user
2. **Lost context on navigation** — Director chat responses streamed via SSE disappear when the user navigates away, because the work is tied to the HTTP connection
3. **Latency confusion** — Simple "hi" messages routed through Temporal added 300-400ms overhead
4. **No clear decision framework** — Developers couldn't determine which technology to use for new features

## Decision

Adopt a **tier-based execution model** aligned with the reference architecture (doc 46, §Graduated Complexity). Each tier uses exactly one execution mechanism. No tier requires choosing between multiple technologies.

### The Four Tiers

| Tier | Pattern | Execution | Event Delivery | Durability |
|------|---------|-----------|---------------|------------|
| **1: Stateless CRUD** | Request → response | In-request | None | DB transaction |
| **2: Stateless agent** | Request → SSE stream | In-request | SSE | DB write at end |
| **3: Interactive session** | Persist-first SSE | In-process async | Redis Pub/Sub → SSE | DB writes during stream |
| **4: Autonomous execution** | Temporal workflow | Temporal worker | Redis Pub/Sub → SSE | Temporal replay + DB |

### Tier 3 — The Chat Path (New)

The critical change: **chat is Tier 3, not Tier 4.**

When a user sends a chat message:

1. User message persisted to DB immediately (already done)
2. Director runs in-process — same as today's SSE stream
3. Director's response chunks are **persisted as they stream** (incremental DB writes)
4. All events emit to Redis Pub/Sub (real-time) AND persist to `mission_events` (durable)
5. If the SSE connection drops, the backend **continues to completion** (response coroutine is not cancelled)
6. When the frontend reconnects, it loads the full conversation from DB — including any in-progress or completed response it missed

**No Temporal involvement.** The session + event stream provide sufficient durability for interactive chat. If the backend process crashes mid-response, the user sees a partial response and can retry — acceptable for chat.

### Tier 3→4 Boundary Crossing

When a Tier 3 chat message triggers long-running work (e.g., Director calls `design_workflow` → Architect runs for 30+ seconds):

1. The Director's tool handler **persists a "task started" record** to DB
2. The tool **forks the work** as a Temporal workflow (Tier 4) or a durable background task
3. The Director returns immediately: "I've asked the Architect to redesign the workflow — you'll see updates in the stream"
4. The Tier 4 work emits events to Redis Pub/Sub independently of the chat SSE connection
5. When the work completes, it persists the result and emits a completion event
6. The Director can be asked about the result in a subsequent message

The user sees: immediate response → stream events during background work → completion notification. Navigation-safe at every step.

### What Gets Removed

| Technology | Action | Reason |
|-----------|--------|--------|
| **FastStream** | Remove from dependencies and config | Never used. Redis Pub/Sub serves the same purpose. |
| **TaskIQ** | Remove from dependencies and config | Temporal handles Tier 4. Tier 3 doesn't need a task broker. |
| **asyncio.create_task** for tool calls | Replace with Tier 4 fork pattern | Fire-and-forget is fragile — no persistence, no error visibility. |

### What Stays

| Technology | Responsibility | Tier |
|-----------|---------------|------|
| **Temporal** | Durable execution: mission runs, supervisor loop, workflow runs, scheduled dispatch | Tier 4 only |
| **Redis Pub/Sub** | Real-time event broadcasting to all channels | Tier 3 + 4 |
| **PostgreSQL** | Persistence: messages, events, execution records | All tiers |
| **SSE** | Client-side event consumption (transport layer) | Tier 3 + 4 |

## Decision Framework

For any new feature, one question:

> **"Does this work need to survive a backend process crash?"**

- **No** → Tier 3. In-process async. Persist-first SSE. Redis Pub/Sub for events.
- **Yes** → Tier 4. Temporal workflow. Redis Pub/Sub for events.

Chat messages, tool calls that complete in <30s, single-agent tasks → Tier 3.
Mission plan dispatch, multi-step workflows, scheduled jobs, autonomous loops → Tier 4.

## Consequences

**Positive:**
- One decision question, not five technology choices
- Chat latency drops to zero overhead (no Temporal scheduling hop)
- Navigation-safe: all state persisted, events survive reconnection
- Simpler dependency tree (remove FastStream, TaskIQ)
- MissionEventHandler already bridges logger→events (built in Plan 53)

**Negative:**
- Tier 3 work doesn't survive process crashes (acceptable for chat)
- Tier 3→4 boundary crossing adds complexity to tool handlers
- Existing `asyncio.create_task` calls in Director tools need migration
- Two execution models to understand (Tier 3 vs Tier 4) instead of one

**Risks:**
- The Tier 3→4 fork pattern must be carefully implemented — if the Director doesn't return a meaningful message before forking, the user sees a spinner then nothing
- The persist-first SSE pattern requires careful handling of partial responses in the DB

## References

- Doc 46: Event-Driven Session Architecture (§Graduated Complexity)
- Doc 14: Background Tasks (TaskIQ — superseded by Temporal for Tier 4)
- Doc 21: Event Architecture (two-bus model: Streams + Pub/Sub)
- Doc 40: Agentic Architecture (orchestration patterns)
- Plan 53: Workflow DB + centralised MissionEventHandler (prerequisite)
