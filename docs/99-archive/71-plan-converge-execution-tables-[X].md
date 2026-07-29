# Plan 71 — Converge Execution Tables: Drop `executions`, Keep `execution_records`

**Version:** 1.0.0
**Date:** 2026-05-03
**Author:** Herman + Claude
**Status:** Ready to implement
**Depends on:** Plan 62 (unified execution path — confirms plan path is the canonical entry point)
**Branch:** feature/incremental-plan-building (convergence prep already landed)

---

## 0. Problem Statement

Mission Control has two tables that track "a run happened":

| Table | Created by | Purpose |
|-------|-----------|---------|
| `executions` | `ExecutionService` (Plan 12 era) | Live state machine for workflow steps |
| `execution_records` | `ExecutionPersistenceService` (Plan 13 era) | Audit trail with full outcome, task detail, cost breakdown |

Both tables have the same core columns (session_id, mission_id, status, total_cost_usd, started_at, completed_at). But `execution_records` is strictly richer — it has TaskPlan JSON, ExecutionOutcome JSON, planning thinking trace, child tables (task_executions, execution_decisions, task_attempts), and background task tracking fields.

**Every code path already writes to `execution_records`** via `persist_mission_results()`. The `executions` table is redundant — it was the original execution model before `execution_records` was added as the persistence layer. Plan 62 deprecated the ad-hoc path, making the `executions` table even less relevant.

### What was done in the prep phase (already landed)

1. `run_execution()` now creates an early `ExecutionRecord` (RUNNING status) before dispatching, so `execution_records` has live state for all paths
2. `list_all_runs()` on `ExecutionPersistenceService` reads `execution_records` only — no merge logic
3. Director's `get_execution_history` switched to `execution_records`
4. Platform director agent switched to `execution_records`
5. `ExecutionService` read methods marked DEPRECATED
6. Dispatch adapter threads `execution_record_id` through to `handle_mission`

### What remains

The `executions` table is still written to by the workflow engine and read by 3 API endpoints. This plan removes all remaining dependencies and drops the table.

---

## 1. Scope

### In scope
- Remove `Execution` model (the table, not the `WorkflowRun` model in the same file)
- Remove `ExecutionRepository`
- Remove `ExecutionService` (replace with `ExecutionPersistenceService` for remaining callers)
- Migrate workflow engine to use `ExecutionRecord` for step tracking
- Migrate API endpoints to use `execution_records` exclusively
- DB migration to drop the `executions` table
- Move `WorkflowRun` / `WorkflowRunState` out of `models/execution.py` (they share the file but are a separate table — `workflow_runs`)

### Out of scope
- Dropping `execution_records` child tables (task_executions, task_attempts, execution_decisions) — these are valuable audit data
- Changing the `workflow_runs` table — it serves a different purpose (workflow lifecycle, not individual step execution)
- Rewriting the workflow engine architecture — we're just swapping which table it writes to

---

## 2. Current Dependency Map

### Writers to `executions`

| Caller | Method | Action |
|--------|--------|--------|
| `workflow_run_waves._execute_step()` | `ExecutionService.create_execution_from_step()` | INSERT — creates step execution |
| `workflow_run_waves._execute_step()` | `ExecutionService.run_execution()` | UPDATE — PENDING → RUNNING → COMPLETED/FAILED |
| `workflows.py` API | `ExecutionService.create_adhoc_execution()` | INSERT — ad-hoc (DEPRECATED by Plan 62) |
| `executions.py` API | `ExecutionService.cancel_execution()` | UPDATE — cancellation |

### Readers of `executions`

| Caller | Method | Can switch? |
|--------|--------|-------------|
| `executions.py` API list | `ExecutionService.list_live_executions()` | Yes — read `execution_records` |
| `executions.py` API get | `ExecutionService.get_execution_or_none()` | Yes — read `execution_records` |
| `executions.py` API execute | `ExecutionService.run_execution()` | Removed when writer is removed |
| `executions.py` API cancel | `ExecutionService.cancel_execution()` | Yes — cancel via `execution_records` |
| `workflows.py` API | `ExecutionService.create_adhoc_execution()` | Plan 62 deprecated this — remove endpoint |
| `workflow_run_waves.py` | `ExecutionService.extract_outputs()` | Read from `execution_records.execution_outcome_json` |
| `ExecutionRepository.count_active()` | Concurrency limiter | Rewrite against `execution_records` |

---

## 3. Implementation Phases

### Phase A: Move `WorkflowRun` to its own file

The `WorkflowRun` and `WorkflowRunState` models live in `models/execution.py` alongside `Execution`. They must be extracted before we can delete `Execution`.

**Files changed:**
- Create `modules/backend/models/workflow_run.py` — move `WorkflowRun`, `WorkflowRunState` here
- `modules/backend/models/execution.py` — only `Execution`, `ExecutionState`, `ExecutionEnvironment` remain
- `modules/backend/models/__init__.py` — update re-exports
- All files that import `WorkflowRun` from `models.execution` — update import paths:
  - `repositories/workflow_run.py`
  - `services/workflow_run.py`
  - `services/workflow_run_waves.py`
  - `services/platform_metrics.py`
  - `temporal/human_input_activities.py`
  - `api/v1/endpoints/missions_workflows.py`
  - `migrations/env.py`

**Test:** All existing tests pass. No schema change — just file reorganization.

### Phase B: Add missing columns to `execution_records`

`Execution` has columns that `ExecutionRecord` doesn't. Only add the ones the workflow engine actually needs for step tracking — not a 1:1 copy of every column.

| Column | Type | Purpose | Needed? |
|--------|------|---------|---------|
| `workflow_run_id` | UUID FK → workflow_runs.id | Links step to parent workflow run | **Yes** — step→run linkage |
| `workflow_step_id` | String(100) | Step ID within the workflow definition | **Yes** — step identity |
| `execution_environment` | String(20) | local / worktree / container | **Yes** — env tracking |
| `cost_ceiling_usd` | Numeric(12,6) | Per-step budget cap | **Yes** — budget enforcement |

**NOT added (already covered or unnecessary):**
- `upstream_context` — ephemeral dispatch-time data, not needed in audit trail. Passed to `handle_mission()` directly.
- `error_data` — error info is already captured in `execution_outcome_json` by `persist_mission_results()`. No separate column needed.
- `objective` → already exists as `objective_statement`
- `roster_ref` → already exists as `roster_name`
- `execution_outcome` → already exists as `execution_outcome_json` (richer)

**Migration file:** `20260503_plan71_execution_record_columns.py`

**Test:** Migration runs cleanly up and down. All new columns are nullable (backward-compatible).

### Phase C: Migrate workflow engine writes

Replace `ExecutionService` usage in the workflow engine with direct `ExecutionRecord` creation via `ExecutionPersistenceService`.

**`workflow_run_waves._execute_step()`** currently does:
```python
execution = await execution_service.create_execution_from_step(...)
execution = await execution_service.run_execution(execution.id)
outputs = execution_service.extract_outputs(execution, output_mapping)
```

Replace with:
```python
# 1. Create early ExecutionRecord (RUNNING) — save_execution() already
#    exists on ExecutionPersistenceService; extend it to accept the new
#    workflow columns (workflow_run_id, workflow_step_id) added in Phase B.
record = await persistence_service.save_execution(
    session_id=..., status="running",
    mission_id=..., roster_name=...,
    objective_statement=...,
    workflow_run_id=run.id,
    workflow_step_id=step.id,
)

# 2. Dispatch via handle_mission (already writes outcome to this record)
outcome = await handle_mission(
    ..., execution_record_id=record.id,
)

# 3. Extract outputs — move extract_outputs() from ExecutionService to
#    ExecutionPersistenceService. The method reads execution_outcome JSON
#    (same shape in both tables, column name changes from execution_outcome
#    to execution_outcome_json — trivial rename).
outputs = persistence_service.extract_outputs(record, output_mapping)
```

**Dual-write transition:** Phase C does NOT dual-write. The early ExecutionRecord created in `run_execution()` (landed in prep phase) already ensures `execution_records` has the data. The `executions` table continues to be written to by the existing code path until Phase E deletes it. Both tables have rows for the same run — this is harmless and already the case.

**Concurrency limiter:** `count_active()` currently counts `executions` rows with PENDING/RUNNING status. Replace with:
```python
count = await session.execute(
    select(func.count())
    .select_from(ExecutionRecord)
    .where(ExecutionRecord.status.in_(['PENDING', 'RUNNING']))
)
```

**Behavioral change (intentional):** The new `count_active()` counts ALL in-flight runs (plan dispatches, research, workflow steps), not just workflow steps. This is more correct — the concurrency limiter protects system resources regardless of run origin. If per-type limits are needed later, add a `task_type` filter.

**Files changed:**
- `services/workflow_run_waves.py` — replace ExecutionService calls
- `services/workflow_run.py` — replace ExecutionService factory usage
- `services/execution_persistence.py` — extend `save_execution()` with new columns, add `count_active()`, move `extract_outputs()` from ExecutionService
- `tasks/workflow_scheduler.py` — replace ExecutionService import

**Test:** Run a workflow end-to-end. Steps create `execution_records` rows. Outputs extract correctly. Concurrency limiter works.

### Phase D: Migrate API endpoints

**`executions.py` endpoints:**

| Endpoint | Current | New |
|----------|---------|-----|
| `GET /executions` (list) | Reads execution_records + merges executions | Read execution_records only (via `list_all_runs()`) |
| `GET /executions/{id}` (detail) | Reads execution_records with executions fallback | Read execution_records only |
| `POST /executions/{id}/execute` | Calls `ExecutionService.run_execution()` | Call `ExecutionPersistenceService` + `handle_mission` directly |
| `POST /executions/{id}/cancel` | Updates executions, fallback to execution_records | Update execution_records only |
| `GET /executions/{id}/status` | Temporal query + DB fallback | Temporal query + execution_records fallback |
| `GET /executions/{id}/decisions` | Reads execution_records | No change |
| `GET /executions/{id}/cost` | Reads execution_records | No change |

**`workflows.py` endpoint:**

| Endpoint | Current | New |
|----------|---------|-----|
| `POST /workflows/{id}/execute` | `ExecutionService.create_adhoc_execution()` | Remove the route — DEPRECATED by Plan 62. FastAPI returns 404 naturally. |

**Director tool `get_execution_detail` (line ~419):**
Currently tries `ExecutionService` then falls back to `ExecutionPersistenceService`. Remove the `ExecutionService` path — read `execution_records` only.

**Files changed:**
- `api/v1/endpoints/executions.py` — remove inline merge, remove ExecutionService imports
- `api/v1/endpoints/workflows.py` — remove `create_execution` endpoint (or return 410)
- `agents/mission/director/agent.py` — simplify `get_execution_detail` to read execution_records only

**Test:** All API endpoints return correct data from `execution_records`.

### Phase E: Delete the old code

With all consumers migrated:

1. Delete `modules/backend/models/execution.py` (only `Execution`, `ExecutionState`, `ExecutionEnvironment` remain — `WorkflowRun` was moved in Phase A)
2. Delete `modules/backend/repositories/execution.py` (`ExecutionRepository`)
3. Delete `modules/backend/services/execution.py` (`ExecutionService`)
4. Delete `modules/backend/services/execution_dispatch.py` (`ExecutionDispatchMixin`)
5. Delete `modules/backend/agents/mission_control/dispatch_adapter.py` (`MissionControlDispatchAdapter`) — the adapter is only needed because `run_execution()` uses a protocol. With direct `handle_mission` calls, it's unnecessary.
6. Remove `ExecutionDispatchProtocol` from `core/protocols.py`
7. Update `modules/backend/models/__init__.py` — remove `Execution` re-export

**Test:** Grep for "from modules.backend.models.execution import" — only `WorkflowRun` imports should remain, pointing at the new file. Grep for "ExecutionService" — zero results.

### Phase F: Drop the table

**Migration file:** `20260503_plan71_drop_executions_table.py`

```python
def upgrade():
    op.drop_table("executions")

def downgrade():
    # Recreate the table for rollback safety
    op.create_table("executions", ...)
```

**Safety:** Run `SELECT count(*) FROM executions WHERE status IN ('PENDING','RUNNING')` before deploying. If any rows are in-flight, wait for them to complete.

**Test:** Migration runs cleanly. Application starts without errors. All /runs page data comes from execution_records.

---

## 4. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Workflow steps fail to create execution_records | Workflows break | Phase C has integration tests; early record creation pattern is already proven in dispatch_approved |
| Output extraction from execution_records differs from Execution | Workflow step outputs don't propagate | Extract_outputs already reads `execution_outcome` JSON — same data is in `execution_outcome_json` |
| Concurrency limiter counts change | Too many or too few concurrent runs | Intentional: counts ALL in-flight runs (more correct). If per-type limits are needed, add `task_type` filter later. |
| Frontend expects Execution response shape | /runs page breaks | API endpoints already return ExecutionRecordResponse — the frontend already consumes this shape |
| In-flight executions during deployment | Stuck in RUNNING | No dual-write needed — prep phase already creates early ExecutionRecords. Phase F only runs after monitoring confirms zero in-flight rows in `executions`. |

---

## 5. Verification Checklist

- [ ] `WorkflowRun` imports updated — no references to `models.execution` for WorkflowRun
- [ ] Workflow engine creates `execution_records` rows for steps
- [ ] Concurrency limiter queries `execution_records`
- [ ] API `/executions` returns data from `execution_records` only
- [ ] Director `get_execution_history` returns all runs (plan dispatch + workflow + research)
- [ ] Director `get_execution_detail` reads execution_records only (no fallback)
- [ ] Director `check_background_tasks` continues to work
- [ ] No code imports `ExecutionService`, `ExecutionRepository`, or `Execution` model
- [ ] Migration drops `executions` table with rollback support
- [ ] Grep `executions` table name in codebase — only migration files and this plan
- [ ] /runs page shows research, plan dispatch, AND workflow runs

---

## 6. Phase Ordering and Dependencies

```
Phase A (extract WorkflowRun) ──┐
                                 ├──→ Phase B (add columns) ──→ Phase C (migrate writers)
                                 │                                       │
                                 │                              Phase D (migrate API) ──→ Phase E (delete code) ──→ Phase F (drop table)
                                 │
                                 └── Can be done independently, no DB changes
```

- **Phases A + B** are safe, backward-compatible changes (no behavior change)
- **Phase C** is the critical phase — workflow engine must work with execution_records
- **Phase D** depends on C (API reads what C writes)
- **Phase E** is pure deletion — safe once D is verified
- **Phase F** is the final migration — safe once E is verified and monitoring confirms zero in-flight executions

---

## 7. Estimated Effort

| Phase | Scope | Files |
|-------|-------|-------|
| A | Extract WorkflowRun model | ~8 files (import path changes) |
| B | Migration + model columns | 2 files (migration + model) |
| C | Workflow engine rewrite | 4 files (workflow_run, waves, persistence, scheduler) |
| D | API endpoint migration | 3 files (executions endpoint, workflows endpoint, director) |
| E | Delete old code | 6 files deleted, 2 updated |
| F | Drop table migration | 1 migration file |

Total: ~24 files touched across 6 phases. Each phase is independently deployable and testable.
