# Plan 52 — Temporal as the Execution Backbone

| Field | Value |
|-------|-------|
| **Status** | Done (2026-04-18) |
| **Created** | 2026-04-12 |
| **Supersedes** | The deleted "Plan 52 — Decouple Chat Persistence from SSE" (asyncio.create_task approach), the `MissionPlanDaemon` polling loop, the `mission_plan_crash_recovery.py` module, and the `session_followups` table-based wake-on-event primitive |
| **Depends on** | Plan 16 (Temporal Integration — already shipped, feature flag off), Plan 51 (Autonomy Loop — supervisor decision matrix, gate checkpoint) |
| **Target** | Whole system — backend execution paths, daemon replacement, chat dispatch, frontend SSE model |

---

## 1  Why

We have a fully implemented Temporal integration (Plan 16 — 588 lines of workflow code, 330 lines of tests, 23 test cases passing) sitting behind `temporal.enabled: false` while we've built a parallel homegrown orchestration layer:

| Homegrown component | What it does | Lines | What Temporal gives you for free |
|---|---|---|---|
| `MissionPlanDaemon` | Polls DB for approved tasks, dispatches via asyncio | ~350 | Scheduled workflows with durable timers |
| `mission_plan_crash_recovery.py` | Reconciles orphaned tasks on restart | ~150 | Automatic workflow replay on worker restart |
| Redis distributed locking | Prevents concurrent dispatch of same plan | ~50 | Workflow ID deduplication (built-in) |
| Heartbeat monitoring | Tracks daemon liveness via Redis TTL | ~80 | Worker health built into Temporal server |
| `session_followups` table | Wake-on-event primitive for Director proactive updates | ~400 | Temporal Signals to running workflows |
| `try/finally` commit guards | Prevent message loss when SSE stream aborts | ~20 | Activities have their own execution lifecycle |
| Plan 52 (deleted) proposed `asyncio.create_task` | Background agent execution | ~200 (est.) | Activities run in worker processes, survive crashes |

**Total: ~1,250 lines of homegrown orchestration** replacing what Temporal does out of the box. Each component has its own failure modes, its own recovery mechanisms, and its own testing burden. The crash recovery module exists precisely because the daemon can't recover itself — which is the exact problem Temporal was designed to solve.

### The architectural violation

P9 states: *"Temporal Owns Orchestration, PostgreSQL Owns Domain."*

P10 states: *"Tier 4 (long-running autonomous) uses Temporal."*

We're building Tier 4 features (7-day unattended missions, supervisor autonomy loop, Director proactive followups) on Tier 2 infrastructure (asyncio polling, Redis pub/sub, manual crash recovery). This is the root cause of the message-loss bug, the navigate-away problem, the daemon's single-process limitation, and the growing maintenance burden.

---

## 2  What exists (Plan 16 — already shipped)

### Temporal infrastructure (production-ready, feature flag off)

| Component | File | Status |
|---|---|---|
| `AgentMissionWorkflow` | `temporal/workflow.py` (249 lines) | Complete — execute → persist → approval → escalation |
| `execute_mission` activity | `temporal/activities.py:22` | Complete — wraps `handle_mission()` with own DB session |
| `persist_mission_outcome` activity | `temporal/activities.py:92` | Complete — best-effort DB persistence |
| `send_notification` activity | `temporal/activities.py:129` | Stub — logs for now, ready for Slack/email |
| DTOs | `temporal/models.py` (84 lines) | Complete — `MissionWorkflowInput`, `MissionExecutionResult`, `ApprovalDecision`, `WorkflowStatus`, `NotificationPayload` |
| Client factory | `temporal/client.py` (55 lines) | Complete — cached connection, feature-flag gated |
| Worker | `temporal/worker.py` (54 lines) | Complete — registers workflow + 3 activities |
| Config | `config/settings/temporal.yaml` | Complete — 17 parameters, all with sensible defaults |
| API endpoints | `api/v1/endpoints/executions.py` | Complete — `/execute`, `/approve`, `/status` |
| Tests | `tests/unit/backend/temporal/` | Complete — 23 test cases |

### What Plan 16 does NOT cover

1. **Chat turn as a workflow.** `handle()` (the chat path) is not a Temporal workflow. Only `handle_mission()` (the dispatch path) is wrapped as an activity.
2. **Daemon replacement.** The daemon is an asyncio loop; Temporal's scheduled workflows could replace it.
3. **Supervisor routing.** Plan 51's `AutonomousPostRunReviewer` runs inline in `dispatch_approved`. It should be a workflow step.
4. **Director followups.** The `session_followups` table + `fire_matching` is a homegrown signal system. Temporal has real Signals.
5. **Event bus integration.** Activities don't publish to the Redis event bus — the frontend doesn't see execution events from Temporal-driven runs.

---

## 3  Target architecture

```
                    ┌──────────────────────┐
                    │   Temporal Server     │
                    │   (durable state)     │
                    └──────────┬───────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────▼──────┐ ┌──────▼───────┐ ┌──────▼───────┐
    │ ChatTurnWorkflow│ │MissionRunWF  │ │ScheduledWF   │
    │ (new)          │ │(existing)    │ │(new)         │
    └───────┬────────┘ └──────┬───────┘ └──────┬───────┘
            │                 │                │
    ┌───────▼────────────────▼────────────────▼───────┐
    │              Temporal Worker Process              │
    │                                                   │
    │  Activities:                                      │
    │    persist_user_message  (new)                    │
    │    execute_chat_turn     (new)                    │
    │    execute_mission       (existing)               │
    │    persist_mission_outcome (existing)             │
    │    evaluate_post_run     (new — supervisor)       │
    │    notify_director       (new — followup)         │
    │    send_notification     (existing — stub)        │
    └──────────────────────────────────────────────────┘

Frontend:
    POST /sessions/{id}/messages → starts ChatTurnWorkflow → returns 202
    GET /streams/runs/{session_id} → reads events from Redis Pub/Sub (unchanged)
    GET /streams/missions/{mission_id} → reads mission events (unchanged)
```

### Three workflows

**1. `ChatTurnWorkflow` (new)** — replaces the inline SSE generator in `send_message_stream`:
```
persist_user_message(session_id, content)     ← Activity, own DB commit
  → execute_chat_turn(session_id, message)    ← Activity, runs handle(), publishes events
  → persist_assistant_message(session_id, response) ← Activity, own DB commit
```
The browser can disconnect at any point. The workflow completes regardless. Events flow through Redis Pub/Sub to any connected SSE subscriber.

**2. `MissionRunWorkflow` (extends existing `AgentMissionWorkflow`)** — adds supervisor routing:
```
execute_mission(plan_id, task_ids)            ← Activity (existing)
  → persist_mission_outcome(...)              ← Activity (existing)
  → evaluate_post_run(plan_id, outcomes)      ← Activity (new — runs AutonomousPostRunReviewer)
  → based on decision:
      WAIT → workflow.sleep(poll_interval), then check for new approved tasks
      ADVANCE_APPROVED → approve tasks, loop back to execute_mission
      ADVANCE_REFINE → Signal to ChatTurnWorkflow (Director refines plan)
      PROPOSE_COMPLETE → Signal to ChatTurnWorkflow (Director asks user)
      ESCALATE → send_notification + start ChatTurnWorkflow for Director
```
This is the autonomy loop as a Temporal workflow. The supervisor decision becomes a workflow step, not an inline call. The loop is durable — if the worker crashes between `execute_mission` and `evaluate_post_run`, Temporal replays from the last completed activity.

**3. `ScheduledMissionWorkflow` (new)** — replaces the `MissionPlanDaemon`:
```
Temporal scheduled workflow, fires every N seconds (configurable per plan)
  → check_for_approved_tasks(mission_id)      ← Activity
  → if approved tasks exist:
      start MissionRunWorkflow as child workflow
  → else: complete (scheduled trigger fires again next interval)
```
No more asyncio polling loop. No more Redis locking. No more heartbeat monitoring. Temporal's scheduler handles timing, deduplication, and worker coordination natively.

### What gets deleted

| Component | Replaced by |
|---|---|
| `MissionPlanDaemon` (~350 lines) | `ScheduledMissionWorkflow` |
| `mission_plan_crash_recovery.py` (~150 lines) | Temporal durable execution (automatic) |
| Redis distributed locking for daemon | Temporal workflow ID deduplication |
| Heartbeat monitoring (Redis TTL) | Temporal worker health |
| `session_followups` table + `SessionFollowupService` (~600 lines) | Temporal Signals to running workflows |
| `try/finally` commit guards in SSE endpoints | Activities have own lifecycle |
| `_noop_agent_turn_runner` / `_create_agent_turn_runner` | `notify_director` Activity |
| Inline `_run_post_run_reviewer` in `dispatch_approved` | `evaluate_post_run` Activity |

### What stays

| Component | Why |
|---|---|
| `AutonomousPostRunReviewer` (gate_post_run.py) | The decision logic is correct — it becomes the body of the `evaluate_post_run` Activity |
| `mission.supervisor.agent` | The Haiku agent is called by the reviewer Activity; chat mode stays for user interaction |
| Event bus (Redis Pub/Sub) | SSE transport to frontend is unchanged — Activities publish to it |
| Plan board, Stream tab, Narrative tab | Frontend is unchanged — events arrive the same way |
| `handle()` function | Becomes the body of the `execute_chat_turn` Activity (not deleted, just wrapped) |
| `handle_mission()` function | Already wrapped as `execute_mission` Activity |

---

## 4  Implementation phases

### Phase A — Activate Temporal and verify existing infrastructure

**Goal:** Turn on the feature flag, start a Temporal server, run the existing `AgentMissionWorkflow` end-to-end, and verify Plan 16's code works in practice.

**Steps:**

1. **Install Temporal CLI** (one-time): `brew install temporal` on macOS, or `curl -sSf https://temporal.download/cli.sh | sh` on Linux. This provides the `temporal` binary for the dev server.

2. **Start Temporal dev server:** `temporal server start-dev` — starts an in-memory Temporal server on port 7233 with a web UI on port 8233. No Docker required for development. For production, use the official Temporal Docker Compose or managed Temporal Cloud.

3. **Set config:**
   ```yaml
   # config/settings/temporal.yaml
   enabled: true
   server_url: "localhost:7233"
   ```

4. **Start the worker** (separate terminal): `conda run -n mission-control python -m modules.backend.temporal.worker` — this process executes workflows and activities. It needs access to Redis (for event publishing) and PostgreSQL (for persistence activities). Both are resolved via the existing config (`get_redis_url()`, `get_async_session()`).

5. **Start the backend:** `python admin.py server start`

6. **Verify:** Trigger an execution via `POST /api/v1/executions/{id}/execute`. Check:
   - Temporal UI at `http://localhost:8233` shows the workflow
   - PostgreSQL has the execution record
   - The existing 23 Temporal test cases pass

**Dev experience note:** Phase A adds one extra process (the worker). A future `docker-compose.dev.yml` should start Temporal server + worker + backend + Redis + Postgres in one command. That's a follow-up, not a blocker.

**Files:**
- `config/settings/temporal.yaml` — flip `enabled: true`
- `docker-compose.dev.yml` (new, optional) — dev stack with Temporal

**Acceptance:** An `AgentMissionWorkflow` completes end-to-end via Temporal. The result is visible in the Temporal UI and persisted in the DB.

---

### Phase B — ChatTurnWorkflow (the core fix)

**Goal:** The chat turn runs as a Temporal workflow. The POST endpoint returns immediately. Messages survive browser disconnect, process crash, and navigate-away.

**New files:**
- `modules/backend/temporal/chat_workflow.py` — `ChatTurnWorkflow` definition
- `modules/backend/temporal/chat_activities.py` — `persist_user_message`, `execute_chat_turn`, `persist_assistant_message` activities

**Modified files:**
- `modules/backend/api/v1/endpoints/sessions.py` — `send_message_stream` becomes `send_message`, returns JSON (not `StreamingResponse`), starts `ChatTurnWorkflow`
- `modules/backend/api/v1/endpoints/agents.py` — `agent_chat_stream` same refactor
- `modules/backend/temporal/worker.py` — register new workflow + activities
- `modules/frontend/src/pages/mission/tabs/chat-tab.tsx` — `sendMessage()` switches from inline fetch-stream to `POST` + `EventSource` on `/streams/runs/{sessionId}`

**Critical design: how `handle()` works inside an Activity:**

`handle()` is an async generator that yields `SessionEvent` objects. Activities must return a value, not yield. The solution:

The `execute_chat_turn` Activity **drains** `handle()` internally — it consumes all yielded events in a loop. But `handle()` already publishes every event to the event bus via `_publish(event_bus, event)` at each step. The Activity constructs a real `SessionEventBus(redis)` and passes it as the `event_bus` parameter to `handle()`. Events flow to Redis Pub/Sub in real-time AS `handle()` yields them, not batched at the end.

```python
@activity.defn
async def execute_chat_turn(input: ChatTurnInput) -> ChatTurnResult:
    """Run a chat turn via handle(), publishing events to Redis in real-time."""
    from modules.backend.events.bus import SessionEventBus
    redis = AsyncRedis.from_url(get_redis_url())
    event_bus = SessionEventBus(redis)

    async with get_async_session() as db:
        session_service = SessionService(db)
        full_content = ""
        async for event in handle(
            input.session_id,
            input.message,
            mission_id=input.mission_id,
            session_service=session_service,
            event_bus=event_bus,        # ← events publish to Redis LIVE
            db_session=db,
        ):
            # handle() publishes internally; we just drain and accumulate
            if hasattr(event, "full_content"):
                full_content = event.full_content
        await db.commit()
    await redis.aclose()
    return ChatTurnResult(content=full_content, ...)
```

The frontend subscribes to `/streams/runs/{sessionId}` via `EventSource` (the endpoint already exists). Events arrive in real-time — same streaming UX, but the transport is Redis Pub/Sub instead of inline SSE from the POST response.

**Note:** The current `send_message_stream` endpoint does NOT pass an `event_bus` to `handle()` — it defaults to `NoOpEventBus`. This is why the Stream/Narrative tabs were empty during chat. The Activity fixes this by passing a real bus.

**Persist activities** use their own DB sessions — `persist_user_message` commits the user message before the agent starts, `persist_assistant_message` commits the response after the agent finishes. If either fails, Temporal retries independently.

**CLI path:** `mc.py chat` keeps the direct `handle()` call. The CLI is a blocking REPL — Temporal's crash recovery doesn't apply to a terminal session. The CLI is Tier 2 (interactive); browser + daemon paths are Tier 4 (durable). Document this as intentional.

**Acceptance:**
- Send a message, navigate away, come back — user message and assistant response both persisted
- Kill the worker process mid-agent-call, restart — Temporal replays from last completed activity, agent re-executes, response persists
- Two browser tabs open on same session — both see streaming events via SSE
- Stream and Narrative tabs show events during chat (event_bus is real, not NoOp)

---

### Phase C — MissionRunWorkflow with supervisor loop

**Goal:** The autonomy loop (dispatch → supervisor → advance/refine/escalate) runs as a Temporal workflow instead of inline code in `dispatch_approved`.

**New files:**
- `modules/backend/temporal/mission_run_workflow.py` — extends `AgentMissionWorkflow` with supervisor loop
- `modules/backend/temporal/supervisor_activities.py` — `evaluate_post_run` (wraps `AutonomousPostRunReviewer`), `approve_proposed_tasks`, `notify_director`

**Modified files:**
- `modules/backend/services/mission_plan.py` — `dispatch_approved` starts a `MissionRunWorkflow` instead of calling `handle_mission` inline. Remove `_run_post_run_reviewer`, `_apply_supervisor_decision`, `_noop_agent_turn_runner`, `_create_agent_turn_runner` — all replaced by workflow steps.
- `modules/backend/temporal/worker.py` — register new workflow + activities

**Key design decisions:**
- The supervisor decision is a workflow step, not an inline call. If the Haiku classification takes 10 seconds and the worker crashes at second 5, Temporal replays and retries.
- `ADVANCE_APPROVED` loops back within the workflow — the workflow calls `approve_proposed_tasks` activity (which flips proposed → approved in the DB, idempotent: checks status before approving), then calls `fetch_approved_task_ids` activity to get the new task list, then re-enters `execute_mission`. No daemon needed.
- `ADVANCE_REFINE` **starts a new `ChatTurnWorkflow`** for the Director (not signals an existing one — there may be no Director workflow running for an autonomous mission). The system-generated prompt includes outcome summaries and asks the Director to call `refine_plan`. The mission run workflow then polls for new proposed tasks via a `check_plan_has_proposed_tasks` activity with `workflow.sleep` intervals, up to a configurable timeout.
- `ESCALATE` starts a new `ChatTurnWorkflow` for the Director with an escalation prompt + sends a notification via `send_notification` activity.
- `PROPOSE_COMPLETE` starts a new `ChatTurnWorkflow` for the Director asking it to confirm completion with the user.
- The `session_followups` primitive becomes unnecessary — starting child workflows replaces the wake-on-event pattern. The Director is woken by being invoked, not by matching a followup row.

**Acceptance:**
- Create a plan with 2 waves. Approve wave 1. The workflow dispatches wave 1, supervisor evaluates, advances wave 2, dispatches wave 2, supervisor proposes completion. All without human intervention, all visible in the Temporal UI.
- Kill the worker mid-dispatch. Restart. Temporal replays and the mission continues from where it left off.

---

### Phase D — Replace the daemon with Temporal scheduling

**Goal:** Delete `MissionPlanDaemon` and `mission_plan_crash_recovery.py`. Temporal scheduled workflows handle polling.

**New files:**
- `modules/backend/temporal/scheduled_workflow.py` — `ScheduledMissionCheckWorkflow` that checks for approved tasks and starts `MissionRunWorkflow` child workflows

**Modified files:**
- `modules/backend/main.py` — remove daemon startup from lifespan; add Temporal schedule registration on first boot
- `config/settings/features.yaml` — remove `experimental_mission_plan_daemon_enabled`

**Deleted files:**
- `modules/backend/services/mission_plan_daemon.py` (~350 lines)
- `modules/backend/services/mission_plan_crash_recovery.py` (~150 lines)

**Acceptance:**
- No daemon process. No Redis heartbeat. No crash recovery module.
- Approved tasks are dispatched within the configured polling interval.
- Multi-worker deployment works out of the box (Temporal handles coordination).

---

### Phase E — Clean up homegrown orchestration

**Goal:** Remove the components that Temporal replaces.

**Deleted files:**
- `modules/backend/models/session_followup.py`
- `modules/backend/repositories/session_followup.py`
- `modules/backend/services/session_followup.py`
- `modules/backend/agents/tools/followup.py`
- `modules/backend/migrations/versions/20260411_plan51_session_followups.py` (migration to drop the table)

**Modified files:**
- `modules/backend/agents/mission/director/agent.py` — remove `schedule_run_completion_followup` tool; Director followups happen via Temporal Signals
- `config/prompts/agents/mission/director/system.md` — remove "Proactive Follow-ups" section; the Director is woken by Temporal, not by a followup row
- `modules/backend/events/types.py` — remove `SessionFollowupFiredEvent` (Temporal Signals replace it)
- `modules/backend/models/__init__.py` — remove `SessionFollowup`
- `modules/backend/services/mission_plan.py` — remove `_run_post_run_reviewer`, `_apply_supervisor_decision`, `_noop_agent_turn_runner`, `_create_agent_turn_runner`, and the inline fire_matching calls in `dispatch_approved`

**Acceptance:**
- `session_followups` table dropped.
- No references to `SessionFollowupService` or `fire_matching` in the codebase.
- All autonomy loop tests (`verify_autonomy_loop.py`, `test_autonomy_loop_e2e.py`) rewritten to use Temporal workflows.
- The Director's proactive chat updates work via Temporal Signals, not followup rows.

---

### Phase F — Event durability with Redis Streams (optional)

**Goal:** Events survive subscriber disconnects. SSE clients can replay missed events on reconnect.

**Modified files:**
- `modules/backend/events/bus.py` — dual-write: `XADD` to Redis Stream + `PUBLISH` to Pub/Sub
- `modules/backend/api/v1/endpoints/streams.py` — on reconnect, replay from cursor via `XREAD`

**Acceptance:** Disconnect SSE, reconnect 5 seconds later, all missed events replay seamlessly.

---

## 5  Exit criteria

Plan 52 is Done when:

1. `temporal.enabled: true` is the default, not an opt-in.
2. The `MissionPlanDaemon`, crash recovery module, and `session_followups` table are deleted.
3. Chat messages survive browser disconnect, navigate-away, process crash, and worker restart.
4. The autonomy loop (dispatch → supervisor → advance/escalate) runs as a durable Temporal workflow.
5. The Temporal UI shows every running workflow, its state, and its history.
6. Multi-worker deployment works without additional coordination code.
7. All existing test suites pass or are rewritten for the Temporal path.
8. The frontend SSE model is unchanged — events still arrive via Redis Pub/Sub, the source is just Activities instead of inline generators.

---

## 6  What this plan does NOT do

- **No Temporal Cloud.** Uses self-hosted Temporal for dev and staging. Cloud migration is a separate ops decision.
- **No workflow versioning strategy.** Long-running workflows (MissionRunWorkflow, potentially days) will break if workflow code changes between replays. Use Temporal's `workflow.patched()` for backward-compatible changes and `workflow.deprecate_patch()` for cleanup. Document the versioning protocol separately when the first schema evolution is needed.
- **No multi-tenancy in Temporal.** Single namespace, single task queue. Multi-tenant isolation is a future concern.
- **No replacement of Redis Pub/Sub for SSE.** Redis Pub/Sub remains the real-time transport to the frontend. Temporal is the orchestration layer, not the event bus.

---

## 7  References

### Existing Temporal code (Plan 16)
- `modules/backend/temporal/workflow.py` — `AgentMissionWorkflow` (249 lines)
- `modules/backend/temporal/activities.py` — 3 activities (145 lines)
- `modules/backend/temporal/models.py` — DTOs (84 lines)
- `modules/backend/temporal/client.py` — cached client factory (55 lines)
- `modules/backend/temporal/worker.py` — worker entry point (54 lines)
- `config/settings/temporal.yaml` — 17 configuration parameters
- `tests/unit/backend/temporal/` — 23 test cases

### Components this plan replaces
- `modules/backend/services/mission_plan_daemon.py` — polling loop (~350 lines)
- `modules/backend/services/mission_plan_crash_recovery.py` — orphan reconciliation (~150 lines)
- `modules/backend/models/session_followup.py` — followup model
- `modules/backend/repositories/session_followup.py` — followup queries
- `modules/backend/services/session_followup.py` — followup service (~300 lines)
- `modules/backend/agents/tools/followup.py` — schedule_followup tool

### Architectural principles restored
- **P6:** Mission Control routes and tracks — it does not run agents inline
- **P9:** Temporal owns orchestration, PostgreSQL owns domain
- **P10:** Tier 4 uses Temporal for durable execution
- **P2:** Deterministic over non-deterministic — workflow steps are explicit, not hidden in asyncio tasks
