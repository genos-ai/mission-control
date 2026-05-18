# Plan 72: Promote Task to First-Class Entity

## Status: Implemented

## Problem Statement

Task is Mission Control's operational primitive: the planner produces tasks,
the dispatcher iterates tasks, the Kanban shows tasks, agents execute tasks,
verification gates tasks. But Task is not a first-class database entity.

Today tasks exist in three fragmented forms:

1. **JSON blob** inside `mission_plans.task_plan_json` (TaskDefinition schema)
2. **Shadow table** `plan_task_states` tracking per-task status
3. **String references** in `task_executions.task_id`, `execution_decisions.task_id`, `context_changes.task_id`

### Consequences

- **Kanban pain**: rendering a card requires joining JSON + shadow table + execution data from three sources
- **Reconciliation overhead**: every refinement and execution needs JSON-to-relational back-patching (`_write_back_task_results`, `_reconcile_plan_task_states`)
- **No referential integrity**: `task_id` is a string everywhere — the DB cannot enforce that a referenced task exists
- **No cross-mission queries**: finding all failed tasks across missions means parsing JSON blobs
- **Drag-to-reorder**: mutating a JSON array instead of leveraging natural ordering
- **Duplicate storage**: `task_plan_json` lives on both `mission_plans` AND `execution_records`
- **Fragile identity**: task_ids encode plan version (`v1-task-001`) — every refinement kills all tasks and rebirths them with new ids, severing approvals, execution history, and artifact links
- **Plan 71 was a symptom**: converging execution tables was necessary because the real entity (Task) was missing

### Steenberg Diagnosis

This is anti-pattern #1 (Fighting the Primitive) combined with #14 (Choosing
Implementation as Primitive). The system treats a JSON blob as the primitive
when the actual primitive is the individual task within it. Promoting Task
to first-class resolves both.

Anti-pattern #13 (Confusing Structure with Primitive) also applies: encoding
plan version into task identity (`v1-task-001`) couples the primitive's
identity to the structure's lifecycle. Primitives must have stable identity
independent of structure.

---

## Design

### Architectural Principle

- **Task** = the primitive (what flows through the system)
- **Mission** = the scope (what contains tasks)
- **Session** = the transport (how humans interact with tasks)
- **ExecutionRecord** = the evidence (proof a task ran)

Task gets a table. Everything that references a task gets a proper FK.
No hacks, no fallbacks, no shadow tables.

### Task Identity

**UUID is the sole identity.** No secondary keys.

| Layer | Mechanism |
|---|---|
| **Database** | UUID primary key. FK target for all referencing tables. |
| **Planning Agent** | `add_task` tool generates UUID and returns it. LLM copies UUID into subsequent tool calls (`set_upstream_input`, `set_verification`, etc.). |
| **Dispatch loop** | `TaskDefinition.task_id` holds UUID string. `completed_outputs[uuid]` for upstream resolution. |
| **from_upstream** | `{"source_task": "a1b2c3d4-...", "source_field": "findings"}` — UUID string. |
| **CLI** | UUID prefix (8 chars) for disambiguation, like git. `mc plan approve a1b2c3d4` |
| **Kanban card** | Description is the primary label. UUID shown as small monospace reference. |
| **Display label** | Computed: `task-{N:03d}` derived from row position in query results. Never stored. |

**Why no `task_key` column:**
- UUID is already globally unique, stable across refinements, and works as FK target
- A secondary key adds a column, a unique constraint, counter maintenance, and key-to-UUID mapping everywhere
- LLMs copy returned strings reliably — UUID length is not a practical error source
- "task-001" is a display concern, not an identity concern — derive from query position

**Why no version prefix:**
- `v1-task-001` couples identity to structure (plan version)
- Every refinement kills all tasks and rebirths them — severing history
- With UUID identity, a refined task is UPDATED (same UUID), not replaced
- `created_at` / `updated_at` timestamps record provenance without encoding it in identity

### Build Session Pre-Population (Critical for Stable Identity)

During refinement, `build_session.py` must be pre-populated with existing
Task rows from the DB before the planning agent runs. Without this, the
planner would call `add_task()` for everything, generating all-new UUIDs,
and reconciliation would cancel all old tasks and create all new ones —
defeating stable identity entirely.

**Refinement flow:**

1. Orchestrator loads existing `Task` rows from DB for this plan
2. Pre-populates the build session with existing tasks (UUIDs, descriptions,
   dependencies, status)
3. Planning agent sees existing tasks and can:
   - `update_task(task_id=existing_uuid, ...)` — modify in place
   - `remove_task(task_id=existing_uuid)` — mark for cancellation
   - `add_task(...)` — generate new UUID for genuinely new work
4. `finalise_plan()` returns TaskPlan with mix of existing and new UUIDs
5. Orchestrator reconciles: existing UUIDs matched by PK, new UUIDs inserted

**First-time planning:** build session starts empty. All `add_task()` calls
generate new UUIDs. No reconciliation needed — all tasks are new.

### Dispatch Boundary

The dispatch loop takes a `TaskPlan` object and operates entirely in-memory.
This is correct — async DB calls don't belong in a tight execution loop.

The boundary is clean:

```
DB (source of truth) → load Task rows → materialize TaskPlan → dispatch(plan)
                                                                    ↓
                                                              ExecutionOutcome
                                                                    ↓
                                                        write results → DB
```

1. **Before dispatch**: load `Task` rows from DB, build `TaskPlan` + `TaskDefinition` objects
2. **During dispatch**: existing `topological_sort()`, `resolve_upstream_inputs()`, execution loop — unchanged
3. **After dispatch**: write `TaskExecution` rows with proper FK, update `Task.status` directly

The dispatch loop's internal mechanics (`dispatch/dag.py`, `dispatch/loop.py`)
stay unchanged. Only the data source and sink change.

---

### New Tables

#### `tasks`

The first-class task entity. Merges `TaskDefinition` (from JSON) with
`PlanTaskState` (shadow table) into a single source of truth.

```
tasks
  id                    UUID PK
  mission_id            FK -> missions (CASCADE)              NOT NULL
                        -- denormalized from plan -> mission for cross-plan queries
                        -- CHECK: must match mission_plans.mission_id via application-level
                        -- enforcement in TaskRepository.create() (no DB trigger needed —
                        -- single write path through repository guarantees consistency)
  plan_id               FK -> mission_plans (CASCADE)         NOT NULL

  -- Definition (from TaskDefinition) --
  agent                 String(200) NOT NULL
  description           Text NOT NULL
  instructions          Text NOT NULL DEFAULT ''
  inputs_json           JSON NOT NULL DEFAULT '{}'
                        -- {static: {}, from_upstream: {}, file_manifest: null}
                        -- from_upstream uses UUID strings as source_task
  verification_json     JSON NOT NULL DEFAULT '{}'
                        -- {tier_1: {}, tier_2: {}, tier_3: {}}
  constraints_json      JSON NOT NULL DEFAULT '{}'
                        -- {timeout_override_seconds: null, priority: "normal"}
  domain_tags           JSON NOT NULL DEFAULT '[]'

  -- State (from PlanTaskState) --
  status                Enum(TaskStatus) NOT NULL DEFAULT 'proposed'
                        -- proposed|approved|queued|running|completed|failed|skipped|cancelled
  approved_by_user_id   FK -> users (RESTRICT)                NULLABLE
  approved_at           DateTime(tz) NULLABLE
  veto_expires_at       DateTime(tz) NULLABLE
  retry_count           Integer NOT NULL DEFAULT 0
  last_attempt_at       DateTime(tz) NULLABLE

  -- Result (denormalized for Kanban rendering) --
  result_summary        Text NULLABLE
  failure_reason        Text NULLABLE
  cost_usd              Numeric(12,6) NOT NULL DEFAULT 0.0
  duration_seconds      Numeric(12,6) NOT NULL DEFAULT 0.0

  -- Timestamps --
  created_at            DateTime(tz) NOT NULL
  updated_at            DateTime(tz) NOT NULL

  INDEX(mission_id, status)
  INDEX(plan_id, status)
  INDEX(plan_id, created_at)         -- Kanban ordering
```

**Latest execution:** No `latest_execution_id` column. Query with
`ORDER BY created_at DESC LIMIT 1` on `task_executions` filtered by
`task_id`. A circular FK (tasks ↔ task_executions) would force two-step
inserts, complicate ORM relationships, and make cascades fragile.

**Ordering:** Tasks are ordered by `created_at` within a plan. The planning
agent typically creates tasks in dependency order (roots first, leaves last),
so creation time gives natural display ordering. No `sort_order` column needed.
If LLM ordering proves unreliable, a `sort_order` column can be added later
with a trivial migration — not worth adding speculatively.

#### `task_dependencies`

DAG edges between tasks. Replaces the `dependencies: list[str]` field
in the JSON TaskDefinition.

```
task_dependencies
  id                    UUID PK
  task_id               FK -> tasks (CASCADE) NOT NULL
  depends_on_id         FK -> tasks (CASCADE) NOT NULL

  UNIQUE(task_id, depends_on_id)
  CHECK(task_id != depends_on_id)
  INDEX(task_id)
  INDEX(depends_on_id)
```

---

### Modified Tables

#### `mission_plans` (thinned)

The plan becomes a metadata container. Tasks live in the `tasks` table.

```diff
  mission_plans
-   task_plan_json       JSON NULLABLE        -- REMOVE: tasks are in DB
+   summary              Text DEFAULT ''       -- from TaskPlan.summary
+   estimated_cost_usd   Numeric(12,6) DEFAULT 0.0
+   estimated_duration    Integer DEFAULT 0     -- seconds
+   execution_hints_json  JSON DEFAULT '{}'     -- {min_success_threshold, critical_path}
    -- all other columns unchanged --
```

#### `task_executions` (FK promotion)

```diff
  task_executions
-   task_id              String(200) NOT NULL   -- was string key into JSON
+   task_id              FK -> tasks (SET NULL) NULLABLE
                         -- proper FK; SET NULL so execution history
                         -- survives if plan (and its tasks) is deleted
    -- all other columns unchanged --
```

#### `execution_decisions` (FK promotion)

```diff
  execution_decisions
-   task_id              String(200) NULLABLE   -- was string
+   task_id              FK -> tasks (SET NULL) NULLABLE
```

#### `mission_artifacts` (add task FK)

```diff
  mission_artifacts
+   task_id              FK -> tasks (SET NULL) NULLABLE
                         -- direct link to the originating task
    task_execution_id    -- KEEP: which specific execution produced it
```

#### `context_changes` (FK promotion)

```diff
  context_changes
-   task_id              String(100) NULLABLE   -- was string
+   task_id              FK -> tasks (SET NULL) NULLABLE
```

#### `execution_records` (remove plan JSON)

```diff
  execution_records
-   task_plan_json       JSON NULLABLE          -- REMOVE: tasks are in DB
    execution_outcome_json  -- KEEP: immutable audit record of outcome
    -- all other columns unchanged --
```

Note: `execution_outcome_json` stores `TaskResult.task_id` as UUID strings.
Write-back resolves UUID string -> Task row via direct PK lookup.

---

### Dropped Tables

#### `plan_task_states` -- DROPPED

Entirely merged into `tasks`. No compatibility shim, no re-export.

---

### Unchanged Schemas

| Schema | Why kept |
|---|---|
| `TaskPlan` (Pydantic) | LLM output contract. Planning Agent produces this JSON. Orchestrator unpacks into task rows. |
| `TaskDefinition` (Pydantic) | Individual task parsed from agent output. `task_id` field now holds UUID string. |
| `ExecutionOutcome` (Pydantic) | Audit. `TaskResult.task_id` holds UUID string. Still stored in `execution_records.execution_outcome_json`. |

The `TaskPlan` schema becomes a **transient format** -- consumed at ingestion
and materialized before dispatch, never stored.

---

### State Machine

Task status transitions, formalized with a validator (adapted from
`session.py::_transition()` pattern):

```
proposed  -> approved | cancelled
approved  -> queued | cancelled
queued    -> running
running   -> completed | failed | skipped
failed    -> approved              (retry)
completed -> (terminal)
skipped   -> (terminal)
cancelled -> (terminal)
```

```python
VALID_TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PROPOSED:  frozenset({TaskStatus.APPROVED, TaskStatus.CANCELLED}),
    TaskStatus.APPROVED:  frozenset({TaskStatus.QUEUED, TaskStatus.CANCELLED}),
    TaskStatus.QUEUED:    frozenset({TaskStatus.RUNNING}),
    TaskStatus.RUNNING:   frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED}),
    TaskStatus.FAILED:    frozenset({TaskStatus.APPROVED}),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.SKIPPED:   frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}
```

---

## Data Flow Changes

### 1. Planning Agent -> Task Rows

**Before:**
```
Planning Agent -> TaskPlan JSON -> mission_plans.task_plan_json = JSON
                                -> create PlanTaskState shadow rows
```

**After:**
```
Planning Agent -> TaskPlan JSON -> validate (unchanged)
                                -> reconcile against existing Task rows
                                -> upsert Task rows + task_dependencies
                                -> store plan-level metadata in mission_plans
```

The orchestrator's `refine()` method:
1. Calls the Planning Agent -> gets `TaskPlan` JSON (task_ids are UUIDs)
2. Validates via `TaskPlan(**json)` (Pydantic, unchanged)
3. Reconciles existing tasks:
   - **Existing UUID in new plan**: task UPDATED (description, instructions, etc may change; `updated_at` bumped; if definition changed, status may reset to PROPOSED for re-approval)
   - **UUID in DB but not in new plan**: task CANCELLED (if non-terminal)
   - **New UUID in plan**: task row CREATED as PROPOSED
4. Rebuilds `task_dependencies` rows from `TaskDefinition.dependencies`
5. Updates `mission_plans` with summary, cost estimate, version bump

Adapts existing `_reconcile_task_states()` logic -- same semantics, different table.

### 2. Dispatch Loop

**Before:**
```
Read task_plan_json -> parse TaskPlan -> topological_sort -> iterate TaskDefinitions
-> execute -> write TaskExecution (string task_id) -> back-patch PlanTaskState
```

**After:**
```
Load Task rows -> materialize TaskPlan in-memory -> dispatch(plan) [unchanged]
-> execute -> write TaskExecution (FK task_id) -> update Task.status directly
```

The dispatch loop (`dispatch/loop.py`, `dispatch/dag.py`) is unchanged internally.
Only the orchestrator layer that builds the TaskPlan and persists results changes.

### 3. Kanban Board

**Before:**
```
GET /missions/{id}/plan -> API joins task_plan_json + plan_task_states + execution data
-> frontend merges three data shapes into cards
```

**After:**
```
GET /missions/{id}/plan/tasks -> API queries tasks table, ordered by created_at
-> frontend renders directly -- each row is a card
```

One query. One entity per card. Dependencies from `task_dependencies` join.

---

## Reuse Inventory

Existing utilities to ADAPT, not recreate:

| Utility | Location | Adaptation |
|---|---|---|
| `topological_sort(plan)` | `dispatch/dag.py:15-46` | Unchanged -- operates on materialized TaskPlan |
| `resolve_upstream_inputs()` | `dispatch/dag.py:49-79` | Unchanged -- uses `completed_outputs` dict keyed by task_id string (now UUID string) |
| `_reconcile_task_states()` | `mission_plan_orchestrator.py:256-323` | Adapt to reconcile Task rows instead of PlanTaskState rows |
| `approve_task()` / `reject_task()` / `approve_all_proposed()` | `mission_plan.py:234-395` | Adapt queries from PlanTaskState to Task table |
| `_transitive_dependencies()` / `_transitive_dependents()` | `mission_plan.py:552-623` | Can now use `task_dependencies` table for cleaner recursive queries |
| `get_task_states()` / `list_in_flight_task_states()` | `repositories/mission_plan.py:91-136` | Rename to task-centric queries against tasks table |
| `reconcile_orphaned_task_states()` | `mission_plan_crash_recovery.py:84-210` | Adapt to query tasks table; same RUNNING->FAILED, QUEUED->APPROVED logic |
| Session `_transition()` pattern | `services/session.py` | Adapt for `VALID_TASK_TRANSITIONS` enforcer on Task model |

---

## Bug Fix: ADVANCE_REFINE Guard

Pre-existing bug found during review: the ADVANCE_REFINE supervisor path
in `mission_plan_orchestrator.py` calls `refine()` WITHOUT calling
`check_no_active_tasks()`. If tasks are still finalizing from a previous
wave, refinement can cancel them mid-flight.

**Fix in Phase 2:** Add `check_no_active_tasks()` guard to the
ADVANCE_REFINE code path, matching the existing guard in `run_objective()`.

---

## Blast Radius

### Models (6 files)

| File | Change |
|---|---|
| `models/task.py` | **NEW** -- `Task`, `TaskDependency`, `TaskStatus` (renamed from `PlanTaskStatus`), `VALID_TASK_TRANSITIONS`. Reuse the existing enum values — do NOT create a second enum. Move `PlanTaskStatus` → `TaskStatus` here; delete original from `mission_plan.py`. |
| `models/mission_plan.py` | Remove `PlanTaskState`, remove `PlanTaskStatus` (moved to task.py), remove `task_plan_json`, add plan-level fields |
| `models/execution_record.py` | `TaskExecution.task_id` -> FK; `ExecutionDecision.task_id` -> FK; remove `task_plan_json` from `ExecutionRecord` |
| `models/mission_artifact.py` | Add `task_id` FK |
| `models/mission_context.py` | `ContextChange.task_id` -> FK |
| `models/__init__.py` | Update imports |

### Repositories (1 file)

| File | Change |
|---|---|
| `repositories/task.py` | **NEW** -- Task + TaskDependency CRUD, bulk upsert, status queries, dependency graph queries. Include `reconcile_tasks(plan_id, new_task_defs)` — moved from orchestrator's `_reconcile_task_states()` logic. |

### Services (12 files)

| File | Change |
|---|---|
| `services/mission_plan.py` | Adapt CRUD + approval for tasks table |
| `services/mission_plan_orchestrator.py` | `refine()` unpacks TaskPlan -> task rows; fix ADVANCE_REFINE guard |
| `services/execution_persistence.py` | Write-back to tasks directly |
| `services/mission_plan_crash_recovery.py` | Query tasks table instead of plan_task_states |
| `services/mission.py` | Minor -- task queries |
| `services/mission_learning.py` | Minor -- task references |
| `services/workflow_run.py` | Minor -- task references |
| `services/workflow_run_waves.py` | Minor -- task references |
| `services/workshop.py` | Minor -- task references |
| `services/summarization.py` | Minor -- task references |
| `services/platform_metrics.py` | Minor -- task references |
| `services/history_query.py` | Minor -- task references |

### Agents (7 files)

| File | Change |
|---|---|
| `agents/mission_control/dispatch/loop.py` | Unchanged internally -- receives materialized TaskPlan |
| `agents/mission_control/mission_dispatch.py` | Load tasks from DB, materialize TaskPlan, pass to dispatch |
| `agents/mission_control/persistence_bridge.py` | Write task_executions with FK, update Task.status |
| `agents/mission/planning/agent.py` | Unchanged (produces JSON) |
| `agents/mission/planning/build_session.py` | Generate UUID task_ids; pre-populate with existing Task rows during refinement |
| `agents/adapters/plan_introspection.py` | Read tasks from DB |
| `agents/mission/director/agent.py` | Minor -- plan introspection |

### API (2 files)

| File | Change |
|---|---|
| `api/v1/endpoints/missions_plan.py` | Return tasks from DB; simplify response shapes |
| `api/v1/endpoints/workflows.py` | Minor -- task references |

### Temporal (3 files)

| File | Change |
|---|---|
| `temporal/activities.py` | Task references |
| `temporal/scheduled_activities.py` | Task references |
| `temporal/plan_refine_activities.py` | Task references |

### Frontend (4 files)

| File | Change |
|---|---|
| `hooks/use-mission-plan.ts` | Simplified data fetch -- tasks are flat rows |
| `types/execution.ts` | Update types to match new API shape |
| `components/workspace/plan-board.tsx` | Simplified -- cards map 1:1 to task rows |
| `components/workspace/plan-board-types.ts` | Remove JoinedTask, update types |

### Total: ~36 files, 6 new/modified models, 1 repository, 1 Alembic migration, 1 validation script

---

## Migration

Single Alembic migration. Data migration included. No multi-step rollout.

### Pre-Migration Validation

Before running the migration, execute a validation script that:

1. Parses all `mission_plans.task_plan_json` and `execution_records.task_plan_json` blobs
2. Reports: total plans, total tasks, corrupt/unparseable JSON blobs, orphaned `plan_task_states` rows without matching JSON entries
3. Logs each problem record (plan_id, nature of corruption) to stdout
4. Exits non-zero if any corruption found — operator reviews before proceeding

This script lives in `scripts/validate_task_migration.py` and runs as a
pre-deploy step. It does NOT modify data — read-only audit.

### Steps

```python
# 1. Create new tables
op.create_table("tasks", ...)
op.create_table("task_dependencies", ...)

# 2. Add new columns to existing tables
op.add_column("mission_plans", Column("summary", Text, ...))
op.add_column("mission_plans", Column("estimated_cost_usd", ...))
op.add_column("mission_plans", Column("estimated_duration", ...))
op.add_column("mission_plans", Column("execution_hints_json", ...))
op.add_column("mission_artifacts", Column("task_id", PgUUID, ...))

# 3. Migrate current plan data:
#    For each mission_plan with task_plan_json:
#      a. Parse JSON into TaskDefinition objects
#      b. For each task: create Task row with new UUID
#      c. Build string-task-key -> UUID mapping for this plan
#      d. Create task_dependency rows
#      e. Copy state from matching plan_task_states row
#
# 4. Migrate historical execution data:
#    For each execution_record with task_plan_json (before dropping it):
#      a. Parse JSON to extract task_ids
#      b. Build string-task-key -> UUID mapping (reuse if task exists
#         from step 3, otherwise create Task row with terminal status)
#      c. Backfill task_id FKs in task_executions, execution_decisions,
#         context_changes, mission_artifacts by matching old string key -> UUID
#
#    Known limitation: if an execution_record references a task_id that
#    cannot be resolved (e.g. corrupt JSON, orphaned record), the FK
#    is left NULL. execution_outcome_json retains the string for audit.

# 5. Alter FK columns
#    - task_executions.task_id: drop old String column, add UUID FK column
#    - execution_decisions.task_id: drop old String column, add UUID FK column
#    - context_changes.task_id: drop old String column, add UUID FK column

# 6. Drop old tables and columns
op.drop_table("plan_task_states")
op.drop_column("mission_plans", "task_plan_json")
op.drop_column("execution_records", "task_plan_json")
```

---

## Implementation Phases

All phases are development milestones within a single branch. They ship
as **one atomic deployment** — the migration drops old tables that the
services reference, so partial deployment would break the application.

### Phase 1: Models + Migration

Create `Task` and `TaskDependency` models. Modify `MissionPlan`,
`TaskExecution`, `ExecutionDecision`, `MissionArtifact`, `ContextChange`.
Drop `PlanTaskState`. Write and test the Alembic migration with data
migration logic.

**Exit criteria:** Models compile. Migration tested against a dev data
dump in isolation (app does not need to start yet — services still
reference old models at this point).

### Phase 2: Service Layer

Adapt `MissionPlanService` for task CRUD. Update
`MissionPlanOrchestrator.refine()` to unpack `TaskPlan` -> task rows.
Update `execution_persistence` to write directly to tasks.
Fix ADVANCE_REFINE guard bug.

**Exit criteria:** Services compile against new models. Unit tests for
task CRUD, approval, reconciliation, and state transitions pass.

### Phase 3: Dispatch Pipeline

Update `mission_dispatch.py` to load tasks from DB, materialize `TaskPlan`,
pass to dispatch. Update `persistence_bridge` to write `TaskExecution`
with proper FK and update `Task.status` directly. Update `build_session.py`
for UUID generation and pre-population.

**Exit criteria:** Full dispatch cycle works end-to-end using task table.
Dispatch loop internals (`loop.py`, `dag.py`) unchanged. `mc run` succeeds.

### Phase 4: API + Frontend

Update API endpoints to return tasks from DB. Simplify response shapes.
Update frontend types. Simplify Kanban data fetching.

**Exit criteria:** Kanban board renders from single `tasks` query. Cards
are 1:1 with task rows. Ordered by `created_at`.

### Phase 5: Cleanup

Remove all string-based task_id lookups. Remove `PlanTaskState` imports.
Remove `task_plan_json` references. Remove dead normaliser code that only
existed for JSON-to-relational bridging. Remove `generate_task_id(version, seq)`
from `build_session.py`. Update `semantic_check()` in `build_session.py` to
validate UUID format instead of `v{N}-task-{NNN}` regex — the existing
`_TASK_ID_PATTERN` will reject every UUID and break all new plans. Update tests.

**Exit criteria:** `grep -r "task_plan_json\|PlanTaskState\|v[0-9]-task-" modules/` returns zero.

### Deployment

Single deploy: run `alembic upgrade head` then restart application.
All five phases must be complete before deploying.

---

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Large blast radius (~34 files) | Phased development within single branch; atomic deployment; each phase has clear exit criteria |
| Data migration on existing missions | Migration script tested against dev data before deploy |
| Planning Agent output changed (UUID task_ids) | `build_session.py` generates UUIDs instead of `v{N}-task-{NNN}`. Agent prompt unchanged. Tool return values change format only. |
| Dispatch loop coupling | Loop internals unchanged. Only the materialization boundary (load from DB -> TaskPlan) and persistence boundary (outcome -> DB) change. |
| Frontend breakage | API response shape changes -- frontend types updated in Phase 4 |
| ADVANCE_REFINE race condition | Fixed in Phase 2 with active task guard |

---

## What This Enables (Future)

Once Task is first-class:

- **Cross-mission task queries**: "show me all failed security scan tasks this week"
- **Task-level permissions**: approve/reject individual tasks by role
- **Task-level audit trail**: every FK chain from task -> executions -> attempts -> decisions is clean
- **Human tasks**: `agent: "human"` tasks that go to a human approval queue -- same lifecycle, same Kanban
- **Recurring tasks**: scheduled tasks that re-enter the proposed state on a cron
- **Task templates**: reusable task definitions across missions
- **Dependency visualization**: `task_dependencies` table enables DB-native DAG queries (transitive closure, critical path)
- **Task continuity across refinements**: updated tasks keep their UUID, preserving approval state, execution history, and artifact links

---

## Checklist

- [ ] New branch from clean main
- [ ] Pre-migration validation script (`scripts/validate_task_migration.py`)
- [ ] Phase 1: Models + Repository + Alembic migration
- [ ] Phase 2: Service layer adaptation + ADVANCE_REFINE fix
- [ ] Phase 3: Dispatch pipeline update
- [ ] Phase 4: API + frontend update
- [ ] Phase 5: Cleanup -- zero references to old patterns
- [ ] All tests pass
- [ ] Kanban board renders correctly
- [ ] `mc run` end-to-end works
- [ ] `mc plan` shows tasks from DB
