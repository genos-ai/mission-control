# Plan 62 — Unified Execution Path: All Runs Go Through Mission Plans

**Version:** 2.0.0
**Date:** 2026-04-21
**Author:** Herman + Architecture Review
**Status:** Implemented
**Depends on:** Plan 51 (autonomy loop), Plan 61 (hardening — confirms plan path works)
**Unlocks:** Reliable `mc run` with supervisor, budget tracking, resume, and audit trail

---

## 0. Problem Statement

There are two execution paths in Mission Control:

1. **Ad-hoc path** (`mc run` → `ExecutionService.create_adhoc_execution()` → `run_execution()`): Creates an `executions` row, calls `handle_mission()` inline, returns. No plan stored, no task states, no supervisor, no budget accumulation, no resume capability.

2. **Plan path** (chat → Director → `MissionPlanService.refine()` → `approve_task()` → `dispatch_approved()`): Creates a `mission_plans` row with `plan_task_states`, dispatches through the same `handle_mission()` but with full tracking — supervisor fires after completion, budget accumulates across waves, failed tasks can be re-approved and re-dispatched.

Both paths call the same `handle_mission()` at the core. The difference is what happens *around* it: plan creation, task state tracking, supervisor registration, and budget accumulation. The ad-hoc path skips all of this.

**This means:**
- `mc run` never triggers the supervisor → no autonomous multi-wave execution
- `mc run` creates no plan → can't resume, can't see task breakdown in Plan tab
- `mc run` has no cumulative budget tracking → budget exhaustion detection doesn't work
- `mc run` creates an `executions` row that nothing else references (orphan audit data)

**The fix:** Make `mc run` go through the plan path. A single-task objective creates a single-task plan. A complex objective creates a multi-task plan. Both get supervisor, budget tracking, and task states. One path, not two.

---

## 1. Design

### Principle: Every execution is a plan dispatch

A plan can have 1 task or 50 tasks. A plan can run in one wave or twenty. The infrastructure handles both. There is no reason for a separate "light" path — the overhead of creating a `mission_plans` row and `plan_task_states` rows is one DB write.

### Flow after unification

```
mc run "objective"           mc chat "run this"          Frontend "Run" button
       │                            │                            │
       │ (sync — blocks             │ (async — fire              │ (async — fire
       │  until complete)           │  and forget)               │  and forget)
       └────────────┬───────────────┘────────────────────────────┘
                    ▼
        MissionPlanService.run_objective(
            mission_id, objective, user_id,
            gate_mode, budget_ceiling_usd,
            async_dispatch=True|False
        )
                    │
                    ▼
        1. get_or_create_plan(mission_id)
        2. Guard: reject if plan has QUEUED/RUNNING tasks (concurrency safety)
        3. refine(plan_id, objective)        ← Planning Agent decomposes
        4. approve_all_tasks(plan_id)        ← auto-approve (gate mode permitting)
        5a. sync:  dispatch_approved()       ← blocks, returns outcome (CLI)
        5b. async: set tasks APPROVED, return ← daemon picks up next tick (chat, frontend)
                    │
                    ▼
        Supervisor fires → decides advance/escalate
        Director notified → posts chat update
```

### Two dispatch modes

Callers need different behaviour:

| Caller | Mode | Why |
|--------|------|-----|
| `mc run` (CLI) | **sync** (`async_dispatch=False`) | User is waiting at terminal, wants to see live progress and final result |
| Director tool (chat) | **async** (`async_dispatch=True`) | Chat session would time out if we block for 3+ minutes; return immediately, daemon dispatches |
| Frontend Run button | **async** (`async_dispatch=True`) | Same — UI should show "Plan created, dispatching..." and update via SSE |

In async mode, `run_objective()` returns after step 4 (approve). The Temporal `ScheduledMissionCheckWorkflow` (polling every 5 seconds) picks up the approved tasks and dispatches them. The supervisor fires after completion as normal.

### Concurrency guard

`get_or_create_plan()` returns **one plan per mission** (singleton). If a user calls `mc run` twice concurrently, the second `refine()` would clobber the first run's in-progress tasks via `_reconcile_task_states()`.

**Guard:** Before calling `refine()`, check `plan_task_states` for any tasks in QUEUED or RUNNING state. If found, raise `ConflictError("Plan has in-progress tasks — wait for completion or cancel first")`. This is a simple query, not a lock.

### New service method: `MissionPlanService.run_objective()`

```python
async def run_objective(
    self,
    mission_id: str,
    objective: str,
    user_id: str,
    *,
    session_id: str | None = None,
    gate_mode: str | None = None,
    budget_ceiling_usd: float | None = None,
    async_dispatch: bool = False,
) -> dict:
    """Create/refine a plan from an objective and dispatch it.

    This is the unified entry point for all execution — CLI, chat, frontend.
    Single-task objectives produce single-task plans. Complex objectives
    produce multi-task plans. Both go through the full plan infrastructure
    (task states, supervisor, budget tracking, audit trail).

    Args:
        async_dispatch: If False (default), calls dispatch_approved() and
            blocks until all tasks complete (CLI mode). If True, approves
            tasks and returns immediately — the Temporal daemon dispatches
            on its next 5-second tick (chat/frontend mode).

    Returns:
        dict with: plan_id, plan_version, task_count, outcome_status
        (sync: full dispatch result), dispatched_task_ids (sync only).
        In async mode, outcome_status is "dispatching".

    Raises:
        ConflictError: If the plan has tasks in QUEUED or RUNNING state.
        ValidationError: If the Planning Agent returns an invalid plan.
    """
```

### What gets deprecated

- `ExecutionService.create_adhoc_execution()` — no longer needed for user-facing execution
- `ExecutionService.run_execution()` — replaced by `dispatch_approved()`
- `MissionControlDispatchAdapter` — verify `dispatch_approved()` calls `handle_mission()` directly (not through the adapter). If it does use the adapter, keep it; if not, deprecate
- The `executions` table is **not removed** (workflow orchestration still uses it via `workflow_run_waves.py`), but `mc run` stops writing to it

### What stays the same

- `handle_mission()` — unchanged, still the core dispatch function
- `dispatch()` in `loop.py` — unchanged, still executes plans
- Planning Agent — unchanged, still decomposes objectives into TaskPlans
- Supervisor — unchanged, still fires on `MissionPlanRunCompletedEvent`
- All existing plan infrastructure — unchanged

---

## 2. Implementation Steps

### Phase A — Service layer: `run_objective()` (~2.5 hours)

- [ ] **A.1** Add concurrency guard: `MissionPlanService._check_no_active_tasks(plan_id)` — queries `plan_task_states` for QUEUED or RUNNING status. Raises `ConflictError` if any found. Called before `refine()`.
- [ ] **A.2** Add `MissionPlanService.run_objective()` method that chains: `get_or_create_plan()` → `_check_no_active_tasks()` → `refine()` → `approve_all_proposed()` → dispatch (sync or async)
- [ ] **A.3** Add `MissionPlanService.approve_all_proposed()` convenience method — approves all tasks in `proposed` state (calls `approve_task()` for each, respects gate_mode)
- [ ] **A.4** Implement `async_dispatch` parameter: when `False`, call `dispatch_approved()` and return full outcome. When `True`, leave tasks in APPROVED state and return `{"outcome_status": "dispatching"}` — the Temporal `ScheduledMissionCheckWorkflow` picks them up on its next 5-second tick
- [ ] **A.5** Handle gate_mode: if `interactive`, stop after refine and return plan summary (user must approve in UI). If `autonomous`/`off`/`ai_assisted`, auto-approve and dispatch
- [ ] **A.6** Handle budget: inherit `budget_ceiling_usd` from mission if not explicitly provided; pass to plan creation
- [ ] **A.7** Return value includes: plan_id, plan_version, task_count, outcome_status, total_cost_usd (sync), dispatched_task_ids (sync) — enough for all callers to render results

### Phase B — API endpoint: `POST /missions/{id}/plan/run-objective` (~30 min)

- [ ] **B.1** Add `POST /missions/{id}/plan/run-objective` endpoint in `api/v1/endpoints/missions_plan.py` that calls `MissionPlanService.run_objective()` — accepts `{objective, gate_mode?, budget_ceiling_usd?, async_dispatch?}`. Named `run-objective` (not `run`) to distinguish from the existing `/plan/dispatch` which dispatches already-approved tasks
- [ ] **B.2** This becomes the single API entry point for all execution — CLI, frontend, and Director all converge here. Frontend/Director callers set `async_dispatch: true`; CLI omits it (defaults to `false`)

### Phase C — CLI: rewire `mc run` and `mc retry` (~2 hours)

- [ ] **C.1** Replace `_run_adhoc()` in `mc_run.py`: instead of `ExecutionService.create_adhoc_execution()` + `run_execution()`, call `MissionPlanService.run_objective(async_dispatch=False)` — sync mode so the CLI blocks and shows live progress
- [ ] **C.2** Adapt the live display — `run_objective()` calls `dispatch_approved()` internally which publishes plan events. The `LiveExecutionDisplay` needs to subscribe to plan step events (`PlanStepStartedEvent`, `PlanStepCompletedEvent`) which are the same event types the dispatch loop already emits. Verify the event shapes are compatible; adapt if needed
- [ ] **C.3** After dispatch, show plan summary: tasks completed/failed, total cost, and suggest `mc status` for details
- [ ] **C.4** Handle `--gate` override: pass to `run_objective()` as `gate_mode` parameter
- [ ] **C.5** Preserve workflow auto-detection: `mc run <workflow-name>` still routes to `_run_workflow()` (no change to workflow path)
- [ ] **C.6** Rewire `mc retry`: instead of re-running the full objective as a new ad-hoc execution, call `MissionPlanService.retry_task()` on the plan's failed tasks then `dispatch_approved()`. This respects plan state — only failed tasks re-execute, completed tasks are preserved

### Phase D — Director tool: `run_objective` (~1 hour)

- [ ] **D.1** Add `run_objective` tool to the Director agent (`director/agent.py`) — calls `MissionPlanService.run_objective(async_dispatch=True)`. The Director currently has `run_workflow()` (for named workflows, also async) but no tool for ad-hoc objectives. The tool returns immediately with plan_id and task count; the daemon dispatches on its next tick
- [ ] **D.2** If gate_mode is `interactive`, Director returns "Plan created with N tasks, approve in Plan tab" instead of dispatching
- [ ] **D.3** The Director tool is a thin wrapper — `run_objective()` handles the full chain internally. Pattern matches existing `run_workflow()` tool (also fire-and-forget via Temporal)

### Phase E — Frontend: rewire Run button (~30 min)

- [ ] **E.1** `run-modal.tsx` currently calls `POST /workflows/missions` (ad-hoc path). Rewire `useCreateExecution()` hook in `use-executions.ts` to call `POST /missions/{id}/plan/run-objective` with `async_dispatch: true` — the UI shows "Plan created, dispatching..." and updates via SSE as the daemon executes tasks
- [ ] **E.2** Ensure the Plan tab reflects the new plan immediately after run (query invalidation on `plan` key)
- [ ] **E.3** Handle `ConflictError` (409) from the endpoint — show "Plan has tasks in progress, wait or cancel first" in the Run modal

### Phase F — Cleanup & tests (~1.5 hours)

- [ ] **F.1** Verify `dispatch_approved()` calls `handle_mission()` directly (not through `MissionControlDispatchAdapter`). If it uses the adapter, keep the adapter; if not, add deprecation marker to adapter
- [ ] **F.2** Mark `ExecutionService.create_adhoc_execution()` and `run_execution()` as deprecated. Known callers: `mc_run.py` (migrated in Phase C), `POST /workflows/missions` endpoint (migrated in Phase E), `workflow_run_waves.py` (keep — this is internal workflow orchestration, not user-facing)
- [ ] **F.3** Add tests for `run_objective()`:
  - Single-task plan: objective → 1-task plan → dispatched
  - Multi-task plan: complex objective → N-task plan → dispatched
  - Interactive gate: stops after refine, returns plan summary without dispatching
  - Budget propagation: inherits from mission when not explicitly provided
  - **Concurrency guard**: plan with QUEUED tasks → raises `ConflictError`
  - **Concurrency guard**: plan with RUNNING tasks → raises `ConflictError`
  - **Concurrency guard**: plan with only COMPLETED/FAILED tasks → proceeds (no conflict)
  - **Async dispatch**: `async_dispatch=True` → tasks set to APPROVED, returns `"dispatching"`, does NOT call `dispatch_approved()`
- [ ] **F.4** Verify existing `mc run` integration tests still pass (may need updating to expect plan-based output)
- [ ] **F.5** Run the endurance dry-run scenario from Plan 61 Phase C through the new `mc run` path to confirm parity

**Total effort:** ~8 hours

---

## 3. What This Enables

After unification, **every execution** gets:

| Capability | Before (ad-hoc) | After (unified) |
|-----------|-----------------|-----------------|
| Plan tab visibility | No | Yes — tasks, statuses, costs visible |
| Supervisor evaluation | No | Yes — fires after each wave |
| Director notifications | No | Yes — followup consumed after supervisor decision |
| Budget accumulation | Per-execution only | Cumulative across all waves |
| Resume on failure | Start over | Re-approve failed tasks, re-dispatch |
| Crash recovery | None | Temporal reconciles orphaned task states |
| Audit trail | `execution_records` only | + `plan_task_states` + `execution_decisions` |
| `mc status` detail | Minimal | Full task breakdown with costs and statuses |

Single-task objectives still work — they just create a 1-task plan. The overhead is negligible (one extra DB row for the plan, one for the task state).

---

## 4. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Concurrent `mc run` calls clobber in-progress plan | Medium | High | Phase A.1 — concurrency guard rejects `refine()` when tasks are QUEUED/RUNNING. Returns 409 Conflict |
| Director tool blocks chat session for minutes | High | High | Phase A.4 — `async_dispatch=True` for Director/frontend. Returns immediately; daemon dispatches |
| `run_objective()` adds latency from plan creation | Low | Low | One DB write (~5ms). Planning Agent call is the real latency, and it happens in both paths |
| Breaking existing `mc run` workflows | Medium | Medium | Phase F.4 — run existing tests, verify CLI output format is compatible |
| Live display needs event type adaptation | Medium | Medium | Phase C.2 — dispatch loop emits `PlanStepStartedEvent`/`PlanStepCompletedEvent`. Verify shapes match `LiveExecutionDisplay` |
| `mc retry` semantics change | Medium | Low | Phase C.6 — retry now re-approves failed tasks instead of re-running the full objective. Communicate in CLI output |
| Frontend Run button breaks during migration | Low | Medium | Phase E — single endpoint change + 409 error handling |

---

## 5. Non-Goals

- Removing the `executions` table (workflow orchestration still uses it via `workflow_run_waves.py`)
- Changing the Planning Agent or dispatch loop
- Changing how the supervisor or Director work
- Adding new gate modes or approval flows
- Migrating `workflow_run_waves.py` — this is internal workflow step execution, not user-facing

---

## 6. Files Changed (Expected)

### Phase A (service layer)
- `modules/backend/services/mission_plan.py` — add `run_objective()`, `approve_all_proposed()`, `_check_no_active_tasks()`

### Phase B (API endpoint)
- `modules/backend/api/v1/endpoints/missions_plan.py` — add `POST /missions/{id}/plan/run-objective`

### Phase C (CLI)
- `modules/clients/cli/mc_run.py` — rewire `_run_adhoc()` and `retry()` to use plan path

### Phase D (Director)
- `modules/backend/agents/mission/director/agent.py` — add `run_objective` tool (async mode)

### Phase E (Frontend)
- `modules/frontend/src/hooks/use-executions.ts` — rewire `useCreateExecution()` to call new endpoint
- `modules/frontend/src/components/mission/run-modal.tsx` — parameter adjustments + 409 error handling

### Phase F (Cleanup & tests)
- `modules/backend/services/execution.py` — deprecation markers on `create_adhoc_execution()`, `run_execution()`
- `modules/backend/agents/mission_control/dispatch_adapter.py` — verify usage, deprecate if unused by plan path
- `modules/backend/api/v1/endpoints/workflows.py` — deprecation marker on `POST /workflows/missions`
- `tests/unit/backend/mission_control/test_run_objective.py` — **NEW** tests (8 scenarios including concurrency guard + async mode)
