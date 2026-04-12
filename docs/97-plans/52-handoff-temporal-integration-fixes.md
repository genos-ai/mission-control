# Plan 52 Handoff — Temporal Integration Fixes

## Context

Plan 52 activated Temporal as the execution backbone for Mission Control. The infrastructure is shipped (4 workflows, 11 activities, worker registered, feature flag on) but the `ChatTurnWorkflow` path has two integration bugs that need fixing before the frontend works correctly.

The legacy inline SSE path (Temporal disabled) still works. The bugs are only on the Temporal-enabled path.

## Bug 1: Duplicate Messages

### What happens
When a user sends a message in the web Chat tab, they see:
- Their message appears twice
- The assistant response appears twice

### Root cause
Three activities persist messages independently, AND `handle()` also persists internally:

1. `persist_user_message` activity writes the user message (Activity 1)
2. `execute_chat_turn` activity runs `handle()` which persists BOTH user + assistant at step 11 (Activity 2)
3. `persist_assistant_message` activity writes the assistant message (Activity 3)

Result: user message written by Activity 1 + Activity 2 step 11 = duplicate. Assistant message written by Activity 2 step 11 + Activity 3 = duplicate.

### Files involved
- `modules/backend/temporal/chat_activities.py` — the three activities
- `modules/backend/agents/mission_control/mission_control.py` — `handle()` function, step 11 (around line 440) persists messages via `_persist_messages()`

### Fix
Add a `skip_persistence: bool = False` parameter to `handle()`. When `True`, skip step 11 (message persistence). The `execute_chat_turn` Activity passes `skip_persistence=True` since the workflow's own activities handle persistence. The CLI (`mc_chat.py`) and legacy SSE endpoint (when Temporal is disabled) pass the default `False` so they keep working.

The change to `handle()` is small — wrap the step 11 block in `if not skip_persistence:`.

### Verify
- Send a message in the web Chat tab → user message appears once, assistant response appears once
- Same via `mc.py chat` (CLI, direct path) → messages still persist correctly
- Check `session_messages` table → no duplicate rows for the same session + content + timestamp

---

## Bug 2: No Streaming on Temporal Path

### What happens
When a user sends a message, nothing appears for several seconds (no "thinking" indicator, no streaming text). Then the complete response appears all at once after the Temporal workflow finishes. Before the Temporal change, the user saw real-time streaming (thinking → tool calls → text chunks → complete).

### Root cause
The `execute_chat_turn` Activity passes a real `SessionEventBus` to `handle()` which publishes events to Redis Pub/Sub. But the frontend's EventSource subscription may not be receiving them because:

1. **Channel mismatch**: The Activity publishes to `{prefix}:{session_id}` but the frontend opens EventSource on `/streams/runs/{session_id}`. The `/streams/runs/` endpoint subscribes to the same channel format, so this SHOULD work — but needs verification that the `session_id` UUID format matches exactly (the Activity uses the session_id string from `ChatTurnInput`, the frontend uses the session_id from the session creation response).

2. **Timing**: The frontend sends POST, gets 202 JSON back, THEN opens EventSource. But the Activity may have already started publishing events before the EventSource connection is established. Early events are lost because Redis Pub/Sub is fire-and-forget.

3. **EventSource URL**: The frontend code in `chat-tab.tsx` (around line 456) opens `new EventSource(${API_BASE}/streams/runs/${sessionId})`. This endpoint requires auth but `EventSource` doesn't support custom headers. Check if the endpoint accepts query params for auth or if it's unauthenticated.

### Files involved
- `modules/frontend/src/pages/mission/tabs/chat-tab.tsx` — `sendMessage()` function, the Temporal path (around line 453-500). Look for `contentType.includes('application/json')` branch.
- `modules/backend/api/v1/endpoints/streams.py` — `stream_run_events()` endpoint. Check auth requirements and channel subscription.
- `modules/backend/temporal/chat_activities.py` — `execute_chat_turn()` Activity. Check the `session_id` format passed to `SessionEventBus`.
- `modules/backend/events/bus.py` — `SessionEventBus.publish()` and `subscribe()`. Check channel name format.

### Fix approach
1. **Verify channel alignment**: Add a debug log in the Activity showing the exact channel name it publishes to. Add a debug log in the SSE endpoint showing the exact channel name it subscribes to. Compare.

2. **Fix timing**: The frontend should open the EventSource BEFORE sending the POST. This way the subscription is active when the first event arrives. Change the order in `sendMessage()`:
   ```
   // 1. Open EventSource first
   const source = new EventSource(...)
   // 2. Then POST to start the workflow
   const response = await fetch(...)
   ```

3. **Auth on EventSource**: Check if `/streams/runs/{session_id}` requires auth. If yes, the `EventSource` API doesn't support `Authorization` headers. Options:
   - Make the endpoint accept a query param `?token=...`
   - Or make it unauthenticated (it's read-only, session-scoped)
   - Check how the existing mission-level SSE endpoint handles auth

### Verify
- Send a message → "thinking" indicator appears immediately
- Streaming text chunks appear in real-time as the agent works
- Tool calls show inline during the response
- Complete response finalizes normally
- Navigate away during streaming → come back → response is persisted (the whole point of Temporal)

---

## Current state of the codebase

### Temporal infrastructure (all working)
- `config/settings/temporal.yaml` — `enabled: true`, server at `127.0.0.1:7233`
- `modules/backend/temporal/workflow.py` — `AgentMissionWorkflow` (Plan 16, production-ready)
- `modules/backend/temporal/chat_workflow.py` — `ChatTurnWorkflow` (Plan 52 Phase B)
- `modules/backend/temporal/chat_activities.py` — 3 activities: `persist_user_message`, `execute_chat_turn`, `persist_assistant_message`
- `modules/backend/temporal/mission_run_workflow.py` — `MissionRunWorkflow` (supervisor loop)
- `modules/backend/temporal/supervisor_activities.py` — 4 activities for supervisor decisions
- `modules/backend/temporal/scheduled_workflow.py` — `ScheduledMissionCheckWorkflow` (daemon replacement)
- `modules/backend/temporal/worker.py` — registers 4 workflows + 11 activities, calls `setup_logging()`

### Endpoint change
- `modules/backend/api/v1/endpoints/sessions.py` — `send_message()` (was `send_message_stream`). When Temporal enabled: starts `ChatTurnWorkflow`, returns JSON. When disabled: falls back to legacy inline SSE `StreamingResponse`.

### Frontend change
- `modules/frontend/src/pages/mission/tabs/chat-tab.tsx` — `sendMessage()` detects JSON vs SSE response by content-type. JSON path opens EventSource on `/streams/runs/{sessionId}`. SSE path reads inline as before.

### What to start with
Start the full stack:
```bash
temporal server start-dev --port 7233 --ui-port 8233
python -m modules.backend.temporal.worker  # separate terminal
python services.py start                   # backend + frontend
```

Open the web frontend Chat tab on any mission. Send "hi" to the Director. Observe the duplicate messages and lack of streaming. Then fix both bugs.

### Tests
- `scripts/test_autonomy_loop_e2e.py` — API-driven test, 8/10 passing. The 2 failures are the chat SSE tests (supervisor + director) which need the streaming fix.
- `scripts/verify_autonomy_loop.py` — 15/15 passing (supervisor decision matrix, doesn't test SSE).
- `scripts/verify_followup_primitive.py` — 8/8 passing (followup primitive, may be removed when Plan 52 Phase E cleanup completes).

### Logs
All logs go to `var/logs/system.jsonl` (backend + worker share the same logging pipeline). Check there for errors.

### Don't change
- The Temporal workflow/activity architecture is correct — don't restructure it
- The supervisor decision matrix (`gate_post_run.py`) is working — don't touch it
- The `mc.py chat` CLI path uses `handle()` directly and should keep working without Temporal
