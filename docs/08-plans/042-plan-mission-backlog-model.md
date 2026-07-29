# Plan 42 — Mission Plan Persistence (Long-Lived Plans + Autonomy Modes)

| Field | Value |
|-------|-------|
| **Status** | Draft |
| **Created** | 2026-04-10 |
| **Revision** | v2.1 — adds §10 Implementation Mechanics after a second review surfaced 7 mechanical gaps behind v2's reuse claims |
| **Depends on** | Plan 13 (Mission Control Dispatch), Plan 15 (Plan Persistence — done), Plan 22 (Step-Through Gate — done), Plan 36 (Mission Director), Plan 41 (Mission Workspace Redesign) |
| **Supersedes** | Nothing — extends Plan 15 forward in time (pre-execution + cross-run) and Plan 22 upward in scope (plan-level gate mode) |
| **Target** | `modules/backend/`, `modules/frontend/`, `config/agents/mission/director/` |

---

## 1  Motivation

### The gap in one sentence

**Today's `TaskPlan` is born when a run starts and dies when the run ends.** The user wants
plans that exist *before* the first run, survive *across* runs, and can be edited,
reviewed, and approved between runs — the conversational loop described in Plan 41:

> Land on mission → Director greets → user describes the goal → Director proposes a plan →
> user reviews → approves → watches it run → reviews results → adds more tasks → iterates.

### What already exists (so we don't duplicate it)

1. **`TaskPlan` schema** (`schemas/task_plan.py`, Plan 13) — a rich DAG with `TaskDefinition`,
   dependencies, inputs, upstream chaining, file manifests, three verification tiers,
   constraints, and execution hints. This is the canonical plan shape.
2. **`ExecutionRecord` + `TaskExecution` + `TaskAttempt`** (Plan 15, done) — persistence
   for post-execution audit. `ExecutionRecord.task_plan_json` already stores a snapshot
   of the TaskPlan that ran. This plan **extends** that forward in time — same JSON
   shape, different lifecycle.
3. **Gate system** (`agents/mission_control/gate.py` + `config/settings/gate.yaml`,
   Plan 22) — four modes (`off` / `interactive` / `ai_assisted` / `autonomous`), with
   `NoOpGate`, `CliGateReviewer`, `LlmGateReviewer` implementations and a
   `GateReviewer` protocol. **This is exactly the autonomy-mode knob** Plan 41 wanted,
   and Plan 42 should expose it, not reinvent it.
4. **Planning Agent** (`system.planning.agent`) — produces TaskPlans from a brief +
   team. It already knows how to shape a plan; Plan 42 asks it to shape drafts instead
   of just just-in-time plans.
5. **`WorkflowRunService`** — wave-based dependency dispatch, parallel steps within a
   wave, output chaining, aggregate cost tracking. This is the multi-step execution
   engine. Plan 42 dispatches through it.
6. **Mission Director** (Plan 36) — the conversational interface. Plan 36 explicitly
   says: _"The Mission Director is a tool-using interface that delegates to existing
   code infrastructure — it does not orchestrate agents itself."_ Plan 42 honours
   this: the Director delegates plan authoring to the Planning Agent via a single
   refinement tool; it never edits individual tasks.

### What's genuinely missing

1. A place to store a **live, mutable** TaskPlan that isn't tied to a completed run.
2. A way to track **per-task status across multiple runs** (a task can be proposed
   today, approved tomorrow, executed next week, failed, retried, completed).
3. A **plan-level gate mode** so autonomy is a property of the plan, not a global CLI
   flag (which is what Plan 22's gate system assumes today).
4. A **conversational entry point** for the Director to delegate "refine this plan"
   to the Planning Agent based on chat context.
5. A Plan tab that renders the live backlog instead of the ephemeral in-run kanban.

That's the entire scope of this plan.

---

## 2  Model

### 2.1 Two new tables, nothing else

Everything else reuses existing infrastructure.

#### `mission_plans` (one row per mission, lazily created)

| Column          | Type         | Notes                                               |
|-----------------|--------------|-----------------------------------------------------|
| `id`            | UUID         | PK                                                  |
| `mission_id`    | UUID         | FK → missions, `UNIQUE`                             |
| `task_plan_json`| JSONB        | A live `TaskPlan` serialized as JSON. Null when empty. |
| `gate_mode`     | VARCHAR(20)  | `off` / `interactive` / `ai_assisted` / `autonomous` (mirrors `config/settings/gate.yaml` values exactly) |
| `status`        | VARCHAR(20)  | `active` / `paused` / `completed` / `archived`     |
| `budget_usd_ceiling` | NUMERIC | Nullable cap for autonomous dispatch                |
| `veto_window_sec` | INTEGER    | Nullable. When non-null + `gate_mode = ai_assisted`, auto-approved tasks wait this long before queueing so the user can veto |
| `created_at`    | TIMESTAMP   |                                                     |
| `updated_at`    | TIMESTAMP   |                                                     |

**Key decision:** the live plan body is a `TaskPlan` JSON blob — the *same shape* that
`ExecutionRecord.task_plan_json` already stores. No parallel task schema. When the
Planning Agent refines the plan, it produces a new TaskPlan and the entire blob is
replaced (with an audit trail — see §2.4).

#### `plan_task_states` (per-task cross-run status)

| Column             | Type         | Notes                                                      |
|--------------------|--------------|------------------------------------------------------------|
| `id`               | UUID         | PK                                                         |
| `mission_plan_id`  | UUID         | FK → mission_plans                                         |
| `task_id`          | VARCHAR(200) | The `task_id` inside the TaskPlan JSON (not a DB FK — it's a string key into the JSON) |
| `status`           | VARCHAR(20)  | See state machine §2.3                                     |
| `approved_by_user_id` | UUID      | Null until approved                                        |
| `approved_at`      | TIMESTAMP    |                                                            |
| `execution_record_id` | UUID      | FK → execution_records (Plan 15), nullable until executed  |
| `task_execution_id`| UUID         | FK → task_executions (Plan 15), nullable                   |
| `last_attempt_at`  | TIMESTAMP    |                                                            |
| `retry_count`      | INTEGER      | Default 0                                                  |
| `veto_expires_at`  | TIMESTAMP    | Non-null when `ai_assisted` auto-approved with a window    |
| `created_at`       | TIMESTAMP    |                                                            |
| `updated_at`       | TIMESTAMP    |                                                            |

**Composite unique index** on `(mission_plan_id, task_id)` so refining a plan can
upsert state for tasks that already exist.

**Key decision:** this table holds only the state that the TaskPlan JSON can't — the
TaskPlan JSON is immutable-ish (replaced atomically when refined), while task state is
mutable every time something happens. `execution_record_id` + `task_execution_id`
link back to the existing Plan 15 persistence, so the Runs tab and the Plan tab share
the same underlying data: clicking a completed task in Plan deep-links to its run
detail in Runs.

### 2.2 Nothing else in the schema

Explicitly *not* adding:

- ❌ New `plan_tasks` table — would duplicate `TaskDefinition` in `TaskPlan` JSON
- ❌ `plan_id` column on `executions` — the link goes `plan_task_states.execution_record_id`
  which is one-way and doesn't force executions to know about plans
- ❌ New `autonomy_mode` enum — `gate_mode` column uses the existing gate config values verbatim
- ❌ New task state columns on `execution_records` / `task_executions` — those stay as-is

### 2.3 Task state machine

State lives in `plan_task_states`, not in the TaskPlan JSON (which stays a pure
specification).

```
      proposed ─── user or auto approves ─────► approved
          │                                         │
     user rejects                              dispatcher selects
          │                                         │
          ▼                                         ▼
      cancelled                                 queued
                                                    │
                                        execution starts
                                                    │
                                                    ▼
                                                running
                                                    │
                          ┌─────────────────────────┼──────────────────────┐
                          │                         │                      │
                          ▼                         ▼                      ▼
                      completed                  failed                 skipped
                                                    │
                                          user clicks Retry
                                                    │
                                                    ▼
                                                approved (again)
```

| From      | To         | Trigger                                                         |
|-----------|------------|-----------------------------------------------------------------|
| `proposed`  | `approved` | User approves; OR auto-approved by `ai_assisted` + Director recommendation; OR auto-approved by `autonomous`/`off` mode |
| `proposed`  | `cancelled`| User rejects, OR Director removes during refinement             |
| `approved`  | `queued`   | User clicks "Run" (interactive); OR dispatcher tick in autonomous mode; OR veto window expires |
| `queued`    | `running`  | Dispatch loop claims the task for a real Execution              |
| `running`   | `completed`| Associated task_execution finishes successfully                 |
| `running`   | `failed`   | Execution errors or exceeds budget                              |
| `running`   | `skipped`  | User cancels the run while this task was in-flight              |
| `failed`    | `approved` | User clicks Retry                                               |

**Task status updates flow automatically** from the existing dispatch pipeline via a
post-execution webhook the persistence_bridge already has a seam for — see §3.4.

### 2.4 Autonomy = gate mode, lifted to plan level

`gate_mode` on `mission_plans` stores one of the existing values from
`config/settings/gate.yaml`. When dispatch starts a run from a MissionPlan, it
passes this value into the existing `GateReviewer` factory — no new gate code, just
a new caller.

| `gate_mode`   | Approval transition            | Dispatch trigger            | In-run gates              |
|---------------|--------------------------------|-----------------------------|---------------------------|
| `interactive` | Manual (user clicks Approve)   | Manual "Run" click          | `CliGateReviewer` honours all gates |
| `ai_assisted` | Auto by Director, with veto window | Auto when deps resolve + veto expired | `LlmGateReviewer` at gates |
| `autonomous`  | Auto by Director               | Continuous dispatcher loop  | `LlmGateReviewer` at high-risk gates |
| `off`         | Auto                           | Continuous dispatcher loop  | `NoOpGate`                |

**Default for new missions:** `interactive` (the safe one).

### 2.5 Audit trail

We need to know "when did the Director last refine the plan" and "what did the plan
look like before the refinement". Two options:

**Option A (chosen):** bump a `version` column on `mission_plans` each time `task_plan_json`
is replaced, and emit a `mission_plan.refined` SSE event with the new version. Prior
versions are reconstructable from the event history — which we already persist for audit.

**Option B (deferred):** a `mission_plan_versions` table with full snapshots. Heavier,
only needed if we start to diff plans or roll back. Add later if needed.

---

## 3  Backend changes

### 3.1 Migration

One Alembic migration:

- Create `mission_plans` (including `version` integer default 1)
- Create `plan_task_states` with composite unique index on `(mission_plan_id, task_id)`
- Index `plan_task_states(mission_plan_id, status)` for the Plan tab's grouped query

No changes to existing tables.

### 3.2 `MissionPlanService`

New file `modules/backend/services/mission_plan.py`. Thin orchestrator — holds no
execution logic itself; it delegates to `PlanningAgent`, `WorkflowRunService`,
`ExecutionService`, and the persistence bridge.

Methods:

- `get_or_create(mission_id) → MissionPlan`  — lazy initialization
- `get_task_states(plan_id) → list[PlanTaskState]`
- `refine(plan_id, instructions, actor_user_id) → MissionPlan`
  - Gathers context (mission brief, team, current `task_plan_json`, recent chat history)
  - Calls `PlanningAgent` to produce a new `TaskPlan`
  - Replaces `task_plan_json`, bumps `version`
  - Upserts `plan_task_states` for each `task_id`:
    - New tasks → `proposed`
    - Existing tasks that survived refinement → unchanged
    - Existing tasks no longer in the plan → `cancelled`
  - Emits `mission_plan.refined`
- `approve_task(plan_id, task_id, user_id) → PlanTaskState`
- `reject_task(plan_id, task_id, user_id) → PlanTaskState`
- `retry_task(plan_id, task_id, user_id) → PlanTaskState`  — `failed → approved`
- `set_gate_mode(plan_id, gate_mode) → MissionPlan`
- `dispatch_approved(plan_id, user_id) → ExecutionRecord`
  - Filters current `task_plan_json` to tasks whose state is `approved` with
    resolved dependencies
  - Generates a **derived TaskPlan** (same JSON shape, filtered task list)
  - Validates via existing `plan_validator`
  - Hands to `WorkflowRunService` / `ExecutionService` with the plan's `gate_mode`
  - Marks dispatched tasks `queued`, sets `veto_expires_at` if applicable
  - Returns the `ExecutionRecord` so the caller can navigate to it

Emits SSE events on every state change — see §3.5.

### 3.3 API endpoints

Under `/api/v1/missions/{mission_id}/plan`:

| Method | Path                                | Action                                  |
|--------|-------------------------------------|-----------------------------------------|
| GET    | `/`                                 | Return plan + all task states           |
| PATCH  | `/`                                 | Update `gate_mode`, `status`, `budget_usd_ceiling`, `veto_window_sec` |
| POST   | `/refine`                           | Call `MissionPlanService.refine`; body: `{ instructions }` |
| POST   | `/tasks/{task_id}/approve`          | Approve a proposed task                 |
| POST   | `/tasks/{task_id}/reject`           | Reject a proposed task                  |
| POST   | `/tasks/{task_id}/retry`            | Retry a failed task                     |
| POST   | `/dispatch`                         | `MissionPlanService.dispatch_approved`; returns `{ execution_record_id }` |

All endpoints gated by the same mission ownership/membership check used for other
`/missions/:id/...` endpoints.

### 3.4 Write-back from dispatch

When a `TaskExecution` completes (via persistence_bridge after execution), the
existing Plan 15 persistence path already writes the TaskExecution row. We add a
**single small hook**: after writing the row, if the execution's `ExecutionRecord`
originated from a MissionPlan dispatch (detected via a `plan_task_state_id` the
dispatcher sets when preparing the Execution), update the corresponding
`plan_task_states` row with status + `task_execution_id` + `completed_at`.

No new persistence layer — one row update in a hook that already runs.

**How does dispatch know it came from a MissionPlan?** When
`MissionPlanService.dispatch_approved` hands the derived TaskPlan to
`ExecutionService`, it passes a `source: "mission_plan"` marker + the mapping of
`task_id → plan_task_state_id`. `ExecutionService` stores this on the Execution's
existing `context` JSON column (no schema change). The persistence hook reads it
and writes back.

### 3.5 SSE events

Two-level namespace:

- **`plan.*`** — stays as-is, run-scoped, emitted by the dispatch loop (`plan.created`,
  `plan.step.started`, `plan.step.completed`). Unchanged.
- **`mission_plan.*`** — new, persistent-plan-scoped:
  - `mission_plan.refined` — `{ version, task_count }`
  - `mission_plan.task.status_changed` — `{ task_id, from, to, actor }`
  - `mission_plan.gate_mode_changed` — `{ from, to }`
  - `mission_plan.dispatched` — `{ execution_record_id, task_ids[] }`

Frontend subscribes to `mission_plan.*` alongside the existing mission stream.

### 3.6 Director tool (Plan 36-compatible)

One new tool registered for the Mission Director in
`modules/backend/agents/tools/mission_plan_tools.py`:

```python
async def refine_plan(instructions: str) -> dict:
    """Refine the current mission plan based on conversation context.

    The Director calls this when the user describes a goal, asks for changes,
    or accepts a proposed direction. Under the hood this invokes the Planning
    Agent with the mission's current brief, team, and existing TaskPlan — the
    Director does not author tasks itself.

    Returns: { version, task_count, summary }
    """
```

This is the **only** plan-authoring tool the Director gets. Plan 36 §1.1 is
preserved: Director conducts the conversation, Planning Agent produces the plan.

Separately, two **state-transition** tools the Director can use inside an
`ai_assisted` / `autonomous` mode plan (subject to gate enforcement):

- `approve_plan_tasks(task_ids: list[str])` — Director expresses "I recommend running
  these next" in `ai_assisted` mode; creates approvals with a veto window
- `dispatch_approved_plan_tasks()` — triggers an autonomous run; only valid if the
  plan's `gate_mode` allows unattended dispatch

These are state-transition tools, not task-editing tools — the Director still
doesn't shape task bodies.

The Director's system prompt gets a short addition explaining this loop.

### 3.7 Continuous dispatch loop (Phase 5)

When `gate_mode ∈ {autonomous, off}`, a background task polls for approved tasks with
resolved dependencies every N seconds and calls `dispatch_approved`. Reuses
`MissionPlanService` — not a second code path. Implementation is an asyncio task or
a Temporal workflow depending on `execution_environment` (see Plan 37). Budget
ceilings enforced via the existing cost tracker.

---

## 4  Frontend changes

### 4.1 New hook file `hooks/use-mission-plan.ts`

- `useMissionPlan(missionId)` — single query returning
  `{ plan, task_states, derived_task_plan }`. Subscribes to `mission_plan.*` SSE
  events for live updates.
- Mutations: `useRefinePlan`, `useApproveTask`, `useRejectTask`, `useRetryTask`,
  `useSetGateMode`, `useDispatchApproved`.

### 4.2 Rewrite `PlanBoard` (Plan 41)

The existing `PlanBoard` drives off `workspaceStore.planTasks` (SSE-only, ephemeral).
It becomes backend-driven.

**Idle / between runs:**

```
┌────────────────────────────────────────────────────────┐
│  Mission Plan              [interactive ▾]  v7    ⚙    │
│                                                        │
│  PROPOSED                                         [3]  │
│    ○ Analyze existing test coverage                    │
│      └ software.quality.agent       [Approve] [✕]      │
│    ○ Identify flaky tests to quarantine                │
│      └ software.quality.agent       [Approve] [✕]      │
│    ○ Draft CI matrix for Python 3.13                   │
│      └ platform.health.agent        [Approve] [✕]      │
│                                                        │
│  APPROVED                                         [2]  │
│    ● Audit config/agents/*.yaml for drift              │
│    ● Write a CI workflow for linting                   │
│                                                [Run 2] │
│                                                        │
│  RUNNING                                          [0]  │
│                                                        │
│  DONE                                             [5]  │
│    ✓ Seed agent catalog         (run #14)              │
│    ✓ Verify secrets handling    (run #14)              │
│    ✓ ...                                               │
└────────────────────────────────────────────────────────┘
```

Each row reads from the TaskPlan JSON (title, agent, dependencies, description) for
display and joins with `plan_task_states` for status + actions.

**Running:** during an active Execution that came from the plan, the running column
animates via the existing `plan.step.*` events (no change there), and on completion
the hook updates `plan_task_states` via the new `mission_plan.task.status_changed`.

**Empty state:** large CTA _"No plan yet — ask the Director to propose one"_ with a
button that jumps to Chat mode with the Director selected.

### 4.3 Gate-mode switcher

Dropdown in the Plan top bar. Switching into `autonomous` or `off` shows a confirm
dialog summarizing: budget ceiling, allowed agents, policy limits. Switching out of
`autonomous` immediately pauses any in-flight continuous dispatcher work.

### 4.4 Veto window UI (`ai_assisted`)

When the Director auto-approves a task with a veto window, the task row shows a
countdown (_"Veto in 47s"_) with a one-click Veto button. Expiring without veto
auto-queues the task. Implemented entirely from `plan_task_states.veto_expires_at`.

### 4.5 Runs tab integration

Each row in the existing `RunsPanel` gets a small annotation: _"From Mission Plan ·
3 tasks · 2 done, 1 failed"_ when the execution originated from a MissionPlan
dispatch. Links deep to the Plan tab scrolled to those tasks.

### 4.6 What gets deleted

- `IdleOverview` component — the Plan tab no longer shows "last 5 runs" (that's the
  Runs tab) or "last 3 artifacts" (that's the right panel)
- `workspaceStore.planTasks` + `planningPhase` — replaced by the backend-driven hook

---

## 5  Phases

Each phase is independently shippable and independently valuable.

### Phase 1 — Foundation (backend + minimal UI)

- Migration for `mission_plans` + `plan_task_states`
- `MissionPlanService` with `get_or_create`, `refine` (Planning Agent call),
  `approve_task`, `reject_task`, `retry_task`, `set_gate_mode`
- API endpoints above, excluding `/dispatch` and autonomous dispatch
- `useMissionPlan` hook + rewritten `PlanBoard` in read-only + manual-approval mode
- Users can see the plan, approve tasks, reject tasks — but dispatch still happens
  through the existing RunModal as today

**Deliverable:** the Plan tab renders a real, persistent backlog. The Director isn't
integrated yet, but a user can ask for a refine via a "Refine with Planning Agent"
button in the empty state and it works.

### Phase 2 — Director integration

- Add `refine_plan` tool to the Mission Director (Plan 36-compatible)
- Update Director system prompt
- Emit `mission_plan.refined` SSE events and wire the frontend to refresh
- The user chats with the Director → describes a goal → Director calls `refine_plan`
  → the Plan tab updates in real time

**Deliverable:** the conversational loop described in Plan 41 works end-to-end for
plan authoring.

### Phase 3 — Dispatch from plan

- Add `/dispatch` endpoint + `MissionPlanService.dispatch_approved`
- Wire the Plan tab's "Run approved" button
- Add the persistence-hook write-back from TaskExecution → plan_task_states
- Link Runs tab rows back to the Plan tab

**Deliverable:** approve tasks → click Run → watch them execute → results surface in
the Plan tab without a refresh.

### Phase 4 — Autonomy modes (`interactive`/`ai_assisted`)

- Gate-mode switcher UI
- `ai_assisted` mode: `approve_plan_tasks` Director tool with veto window
- Veto-window countdown UI
- Policy enforcement (agent allowlist, tool allowlist) wired through existing
  `GateReviewer` context

**Deliverable:** user can let the Director auto-approve with a veto window. Same
mission can toggle back to `interactive` at any time.

### Phase 5 — Continuous autonomous loop

- Background dispatcher task for `autonomous` / `off` gate modes
- Hard kill switch when the mission is paused or archived
- Activity digest: periodic summary notification (Plan 33 notification stream)
- Hard budget ceiling enforcement

**Deliverable:** set a plan to `autonomous`, walk away, come back to progress. The
mission's total cost is capped; the digest tells you what happened.

---

## 6  Open questions

1. **Refinement semantics.** When the Director refines, does it get a fresh TaskPlan
   from the Planning Agent or an incremental diff? Starting with full replacement —
   simpler, and the Planning Agent is already good at producing complete plans from
   the mission context. Revisit if we see unnecessary churn.

2. **Plans for missions that also have Workflows.** Missions can have both a
   MissionPlan and one or more WorkflowDefinitions. They serve different purposes:
   MissionPlan = conversational ad-hoc backlog; Workflow = reusable recipe. They
   coexist. The Plan tab shows the MissionPlan; workflows remain accessible via the
   Workflows button in the top bar.

3. **Backfilling historical data.** No backfill. Old `ExecutionRecord`s stay visible
   in the Runs tab with no MissionPlan link. New executions from Phase 3 onward will
   have the link.

4. **Multi-user approval.** Phase 1 through 4: anyone with mission write access can
   approve. Phase 4 may need per-plan approver policies — deferred until we see the
   need. Audit trail is already captured via `approved_by_user_id`.

5. **Veto window duration.** Configurable per plan (`veto_window_sec`). Default
   suggestion: 60 seconds for `ai_assisted` mode. Tunable without code changes.

6. **What happens to queued tasks when a mission is paused mid-run?** Existing
   pause logic stops dispatch. In-flight executions complete normally; queued tasks
   stay `queued` and resume when the mission is resumed.

7. **Relationship to WorkflowRun.** Phase 3 dispatches through `WorkflowRunService`
   by synthesizing a one-shot workflow definition from the approved subset. An
   alternative is to dispatch directly through `ExecutionService` bypassing
   WorkflowRun. Choose during Phase 3 implementation — whichever path is shorter and
   preserves wave-based dependency dispatch.

---

## 7  Success criteria

This plan is done when:

1. A new mission lands on the Plan tab showing an empty-state CTA. User chats with
   the Director, describes a goal, and sees the refined plan appear in real time.
2. User can approve, reject, retry, and reorder tasks, and switch the gate mode
   without writing YAML or restarting anything.
3. Clicking Run dispatches only the approved subset through the existing dispatch
   pipeline, with the existing gate behaviour honoured per-plan.
4. Task results flow back to the Plan tab automatically via a single hook in the
   persistence bridge — no manual refresh.
5. Switching the plan to `autonomous` and walking away produces progress within
   budget, with a resumable audit trail on return.
6. The old `IdleOverview` and `workspaceStore.planTasks` ephemeral state are gone.
7. No new code lives where existing code already solved the problem — `TaskPlan`,
   `GateReviewer`, `WorkflowRunService`, `persistence_bridge`, and
   `PlanningAgent` are all reused unchanged.

---

## 8  Reuse inventory (anti-duplication checklist)

Before merging any code from this plan, verify:

| Existing thing | How this plan reuses it | If this plan diverged |
|---|---|---|
| `schemas/task_plan.py::TaskPlan` | Stored verbatim in `mission_plans.task_plan_json` | We'd be creating a thinner task schema — regression |
| `schemas/task_plan.py::TaskDefinition` | The canonical task shape; display in Plan tab; filtered in `dispatch_approved` | We'd be duplicating task fields in `plan_task_states` |
| `agents/mission_control/gate.py` + `config/settings/gate.yaml` | Stored as `mission_plans.gate_mode`; passed to existing `GateReviewer` at dispatch time | We'd be inventing a parallel autonomy enum |
| `models/execution_record.py` (Plan 15) | `plan_task_states.execution_record_id` FK; persistence hook writes back | We'd be building a parallel persistence layer |
| `services/workflow_run.py::WorkflowRunService` | `dispatch_approved` hands derived TaskPlan to this service | We'd be writing a second orchestrator |
| `system.planning.agent` | `MissionPlanService.refine` delegates to this agent | We'd be teaching the Director to author plans — violates Plan 36 |
| `agents/mission_control/persistence_bridge.py` | New single hook writes plan_task_states on task completion | We'd be duplicating the completion pipeline |
| `plan.*` SSE events | Untouched; `mission_plan.*` added at a different semantic level | We'd be overloading a namespace |
| Plan 36 (Mission Director) tool-using contract | One new tool `refine_plan` that delegates to Planning Agent + two state-transition tools | We'd be giving the Director task-editing tools, breaking Plan 36's split |

---

## 9  What this supersedes / coexists with

- **Plan 15 (Plan Persistence — done)** — Plan 15 persists TaskPlans *after* execution
  for audit. This plan persists them *before* execution for drafting, and links
  cross-run state back to the Plan 15 tables. Complementary, not competing.
- **Plan 22 (Step-Through Gate — done)** — Plan 22 owns the gate *mechanism*. This plan
  lifts gate *mode selection* from a CLI flag / global config to a per-plan field.
  Same gate code runs underneath.
- **Plan 36 (Mission Director)** — Plan 36 defines the Director as a tool-using
  delegate. This plan adds one authoring tool (`refine_plan` → Planning Agent)
  plus two state-transition tools — all compatible with Plan 36's split.
- **Plan 41 (Mission Workspace Redesign)** — Plan 41 introduced the Plan tab with an
  ephemeral kanban and an `IdleOverview`. This plan replaces both with a
  backend-driven persistent backlog.

---

## 10  Implementation mechanics

A second quality review surfaced seven places where v2's "just reuses existing
things" claim was structurally correct but mechanically incomplete. This section
pins down each one with a concrete decision so Phase 1 can start without further
scoping passes.

### 10.1 `handle_mission` contract change

**Problem.** `handle_mission(mission_brief: str, ...)` always calls the Planning
Agent internally ([mission_control.py:528](modules/backend/agents/mission_control/mission_control.py)).
There's no parameter to inject a pre-built `TaskPlan`. The lower-level `dispatch()`
takes a plan but needs roster, context curator, context assembler, event bus, agent
executor, and environment handle — all loaded inside `handle_mission` before it calls
`dispatch`. Skipping `handle_mission` would mean duplicating ~80 lines of setup.

**Decision.** Add a single new keyword-only parameter to `handle_mission`:

```python
async def handle_mission(
    mission_run_id: str,
    mission_brief: str,
    *,
    precomputed_plan: TaskPlan | None = None,   # ← new
    ...
) -> tuple[ExecutionOutcome, str | None]:       # ← return expanded (see §10.6)
    ...
    if precomputed_plan is not None:
        plan = precomputed_plan
        thinking_trace = None
        await _phase("planning", "Using precomputed plan from MissionPlan")
    else:
        # existing 3-attempt Planning Agent retry loop stays untouched
        ...
    # ... rest of handle_mission (context, environment, dispatch, persist) unchanged
```

Roster, context, environment, event bus, dispatch, gate forwarding, persistence —
all stay inside `handle_mission` and are reused for free. When `precomputed_plan`
is supplied, the validated plan still flows through `validate_plan(plan, roster,
budget)` before dispatch so the same 11 rules apply.

**Cost.** ~5 lines in `handle_mission`. No change to `dispatch()`. No change to
`ExecutionService`. Call sites that pass a string continue to work unchanged.

### 10.2 Dependency-closure policy on approval

**Problem.** `_rule_3_dag_validation` and `_rule_4_dependency_consistency` in
`plan_validator.py` reject plans with dangling `dependencies` or `from_upstream`
refs. A naive filter `tasks where state == approved` will almost always produce an
invalid subset.

**Decision.** **Approval is dependency-transitive.** `MissionPlanService.approve_task`
auto-approves all transitive dependencies of the target task:

```python
async def approve_task(self, plan_id, task_id, user_id):
    plan = await self.get(plan_id)
    task_plan = TaskPlan.model_validate(plan.task_plan_json)
    task = task_plan.get_task(task_id)
    if task is None:
        raise NotFoundError(...)

    # Walk the dep graph upward, collect everything this task needs
    needed = _transitive_dependencies(task_plan, task_id)
    # Mark each dep approved if not already approved/running/completed
    for dep_id in needed:
        dep_state = await self._repo.get_state(plan_id, dep_id)
        if dep_state.status == PlanTaskStatus.PROPOSED:
            dep_state.status = PlanTaskStatus.APPROVED
            dep_state.approved_by_user_id = user_id
            dep_state.approved_at = utc_now()
    # Finally approve the requested task itself
    ...
```

The Plan tab UI reflects this by visually grouping "approved-with-me" deps on hover
before the click: _"Approving this task will also approve 2 dependencies."_ Same
behaviour as IDE Refactor tools that show a dependency preview.

**Rejection is the inverse**: rejecting a task also rejects all tasks that depend
on it (transitively). The UI warns before doing so.

### 10.3 Task ID stability across refinements

**Problem.** The Planning Agent regenerates plans from scratch. Task IDs will almost
certainly change between refinements, silently orphaning `plan_task_states` keyed by
`task_id`.

**Decision (default).** **Clean slate on refinement.** When the Planning Agent
produces a new TaskPlan:

1. Archive the current `plan_task_states` rows for all non-terminal states
   (`proposed`, `approved`, `queued`, `failed`) by setting `status = 'cancelled'`
   with a reason `'superseded_by_refinement_v<N>'`.
2. Preserve terminal-state rows (`completed`, `failed-then-done`, `skipped`) for
   historical reference — these point at executed runs and their `execution_record_id`
   must survive.
3. Create fresh `proposed` rows for every task in the new plan.
4. Bump `mission_plans.version`.
5. Emit `mission_plan.refined` with `{ version, task_count, cancelled_count }`.

**Tradeoff acknowledged.** A user who approves 5 tasks, then refines the plan with
a tiny tweak, loses those 5 approvals. This is surprising the first time but:
- Conversational refinement is infrequent compared to approvals
- Users learn to batch refinements before approving
- The alternative (content-hash matching or Planning Agent ID preservation) is fragile

**Escape hatch for later.** Once we observe this in practice, if the friction is
real, we can revisit with either:
- Prompt the Planning Agent to preserve task_ids when semantically unchanged (needs
  agent co-operation and a stable diff), OR
- Introduce a content-hash-based migration heuristic

Both are additive on top of the clean-slate default. Not part of Phase 1.

### 10.4 Refinement agent — Planning Agent vs Workflow Architect

**Problem.** v2 said "Director calls `refine_plan` which delegates to the Planning
Agent." But there are two candidate plan-producing agents with unclear division of
labour:

- `system.planning.agent` — not chat-enabled, designed for one-shot brief → TaskPlan,
  called internally by Mission Control
- `mission.workflow.agent` (Workflow Architect) — chat-enabled, Opus 4.6, configured
  explicitly as the **conversational** plan designer, produces `WorkflowDefinition`
  (saved step graphs)

**Spike (field-by-field comparison, resolved 2026-04-10).**

| Field | `WorkflowStepSchema` | `TaskDefinition` | Compatible? |
|---|---|---|---|
| Identifier | `id` | `task_id` | ✓ |
| Description | `description` | `description` | ✓ |
| Agent binding | `capability` (abstract, `analyze.code`) | `agent` + `agent_version` (concrete) | ✗ different granularity |
| Instructions | — | `instructions` (natural-language) | ✗ workflow has none |
| Inputs | `input: dict` | `inputs.static` + `inputs.from_upstream` + `inputs.file_manifest` | ✗ workflow missing file manifest, different upstream model |
| Upstream refs | producer-side `output_mapping` | receiver-side `from_upstream` | ✗ inverted data flow |
| Dependencies | `depends_on` | `dependencies` | ✓ |
| Timeout | `timeout_seconds` | `constraints.timeout_override_seconds` | ✓ |
| Verification | — | `verification` (3 tiers per task) | ✗ workflow has none |
| Step-level QA | `max_refinement_rounds`, `termination`, `max_iterations` | — | ✗ workflow-only |

**Key realization.** WorkflowStep and TaskDefinition are genuinely different
abstractions at different layers, not alternate shapes of the same thing:

```
Workflow (Workflow Architect designs) → WorkflowRunService
                                       → per step → handle_mission(step as brief)
                                                  → Planning Agent
                                                  → TaskPlan (fine-grained tasks)
                                                  → dispatch()
```

**Workflow steps aren't skipping the Planning Agent — each step triggers the
Planning Agent internally during its own execution.** WorkflowStep is *coarser* than
TaskDefinition. One step like "run code-quality audit" decomposes into N
TaskDefinitions at runtime.

**The user-facing "plan tasks" in Plan 42** (mockup shows rows like _"Analyze
existing test coverage"_ tagged with `software.quality.agent`) are clearly
**TaskDefinition-level**: concrete agent bindings, instruction-rich, one-to-one with
what dispatch executes. They are not WorkflowSteps.

**Decision — Path A: Planning Agent with refinement mode.**

- `mission_plans.task_plan_json` IS a `TaskPlan` (existing schema, verbatim)
- The refinement agent is the **Planning Agent** (`system.planning.agent`)
- Extend `_call_planning_agent` to accept optional `current_plan: TaskPlan | None`
  and `refinement_instructions: str | None`. When both are provided, the planning
  prompt gets a refinement-mode branch:
  > _"Here's the current TaskPlan. The user asked to refine it with these
  > instructions: `<instructions>`. Produce a new TaskPlan. Preserve task_ids when
  > the task's semantics are unchanged; generate new IDs for new tasks."_
- `chat_enabled: false` on the Planning Agent does not block this — the Director
  (chat-enabled) calls the Planning Agent via a backend tool, same pattern
  `handle_mission` uses today. It's a single inference call, not a chat session.
- The Workflow Architect stays in its lane designing coarse workflows. No
  compiler, no WorkflowDefinition → TaskPlan conversion, no new primitives.

**Implementation sketch:**

```python
# modules/backend/agents/mission_control/helpers/agent_executor.py

async def _call_planning_agent(
    prompt: str,
    roster: Roster,
    upstream_context: dict | None,
    *,
    event_bus: EventBusProtocol | None = None,
    session_id: str | None = None,
    current_plan: TaskPlan | None = None,          # ← new
    refinement_instructions: str | None = None,    # ← new
) -> dict:
    ...
    planning_prompt = _build_planning_prompt(
        mission_brief=prompt,
        mission_id="pending",
        roster_description=roster_desc,
        upstream_context=upstream_context,
        code_map=code_map,
        current_plan=current_plan,                 # ← new
        refinement_instructions=refinement_instructions,  # ← new
    )
    ...
```

And the prompt builder (`prompt_builder.py::_build_planning_prompt`) gets a
refinement-mode branch that, when `current_plan is not None`, injects a block like:

```
MODE: REFINEMENT

You are refining an existing TaskPlan. The current plan is:

<current_plan>
{current_plan.model_dump_json(indent=2)}
</current_plan>

The user's refinement instructions:

<refinement_instructions>
{refinement_instructions}
</refinement_instructions>

Produce a new TaskPlan that incorporates the instructions. Preserve task_id
strings for tasks whose semantics are unchanged so that state and audit
references survive. Generate new task_ids for new tasks. Removed tasks simply
do not appear in the output.
```

**Impact on other §10 sections:**

- §10.3 clean-slate policy stays as a **safety net**. If the Planning Agent
  successfully preserves task_ids, state survives refinement. If the Planning
  Agent changes task_ids (e.g. because the refinement was substantial), the
  clean-slate archiver catches it — no orphaned state.
- This means `MissionPlanService.refine` should compare the *new* task_ids to the
  existing `plan_task_states`, preserve state for matches, and clean-slate-cancel
  the rest.

**§10.4 is resolved. Phase 1 can start.**

### 10.5 Live task state during a run — no per-task write-back hook

**Problem.** v2 said "persistence_bridge writes plan_task_states on each task
completion". But [persistence_bridge.py](modules/backend/agents/mission_control/persistence_bridge.py)
runs **once at end-of-mission** — it's a terminal write, not a per-task hook. The
dispatch loop doesn't have a per-task callback today and adding one is invasive.

**Decision.** **Batch + SSE overlay.**

1. **At end-of-run:** after `handle_mission` returns, `MissionPlanService.dispatch_approved`
   iterates `outcome.task_results` and writes back to `plan_task_states`:

   ```python
   outcome, execution_record_id = await handle_mission(
       precomputed_plan=derived_plan,
       ...,
   )
   for task_result in outcome.task_results:
       await self._write_task_result(
           plan_id=plan.id,
           task_id=task_result.task_id,
           status=_map_task_result_status(task_result.status),
           execution_record_id=execution_record_id,
           completed_at=task_result.completed_at,
           retry_count=len(task_result.attempts),
       )
   ```

   This is the authoritative durable state. No changes to dispatch loop or
   persistence_bridge.

2. **During a run:** the frontend already receives `plan.step.started` and
   `plan.step.completed` SSE events from the dispatch loop. The Plan tab renders
   a **derived live status overlay**:

   ```
   effective_status(task) =
       overlay_from_sse_events(task_id)     if currently running
       plan_task_states[task_id].status     otherwise
   ```

   Implemented entirely on the frontend by joining `workspaceStore.liveTaskOverlay`
   (populated from SSE) with the backend `plan_task_states`.

3. **On page refresh mid-run:** the overlay is empty (no SSE events replayed), so
   the user briefly sees the pre-run `queued`/`approved` state. Within a few seconds
   of resubscribing, the next `plan.step.*` event re-populates the overlay. Acceptable
   UX — no backend work needed.

This completely avoids the need for a new per-task hook in the dispatch loop.

### 10.6 `handle_mission` return expansion

**Problem.** `handle_mission` returns only `ExecutionOutcome`. `MissionPlanService`
needs the `execution_record_id` to link `plan_task_states.execution_record_id`.

**Decision.** Expand the return signature:

```python
async def handle_mission(...) -> HandleMissionResult:
    ...
    record_id: str | None = None
    if db_session is not None:
        record_id = await persist_mission_results(
            outcome, ..., db_session=db_session,
        )  # ← currently returns None; change to return the inserted row id
    return HandleMissionResult(outcome=outcome, execution_record_id=record_id)
```

Where `HandleMissionResult` is a small dataclass:

```python
@dataclass
class HandleMissionResult:
    outcome: ExecutionOutcome
    execution_record_id: str | None
```

All existing call sites that only care about `outcome` destructure `result.outcome`
(or we provide a transitional attribute). `persist_mission_results` already has the
record in hand internally — exposing its id is a one-line change.

### 10.7 Cumulative budget for autonomous plans

**Problem.** The existing `mission_budget_usd` is per-execution. A `fully_autonomous`
plan running across multiple dispatched runs needs a **cumulative** ceiling across
all its runs.

**Decision.** Add one column to `mission_plans`:

| Column | Type | Notes |
|---|---|---|
| `total_spent_usd` | NUMERIC | Running total across all executions dispatched from this plan. Updated after each run. Default 0. |

Enforcement in `MissionPlanService.dispatch_approved`:

```python
remaining_budget = None
if plan.budget_usd_ceiling is not None:
    remaining = plan.budget_usd_ceiling - plan.total_spent_usd
    if remaining <= 0:
        raise BudgetExhaustedError(
            f"Plan {plan.id} has spent {plan.total_spent_usd} of "
            f"{plan.budget_usd_ceiling} ceiling"
        )
    remaining_budget = remaining

result = await handle_mission(
    ...,
    precomputed_plan=derived_plan,
    mission_budget_usd=remaining_budget or DEFAULT_RUN_BUDGET,
)

# After run completes, update the cumulative total
plan.total_spent_usd += result.outcome.total_cost_usd
await self._repo.save(plan)
```

Two budget layers coexist cleanly: per-execution budget (existing) and
per-plan cumulative ceiling (new). Both enforced.

### 10.8 Veto-window poller + continuous dispatcher (share one loop)

**Problem.** v2 added `veto_expires_at` and described a continuous dispatcher for
`fully_autonomous` plans, but didn't specify how either one actually runs. Two
candidates for a background loop, not two separate systems.

**Decision.** **One shared asyncio task per backend process** — a
`MissionPlanDaemon` that wakes every 5 seconds and:

1. For each `mission_plan` with `gate_mode ∈ {ai_assisted, autonomous, off}` and
   `status == active`:
   - **Veto expiry check** (all modes): find `plan_task_states` with
     `status == approved` and `veto_expires_at < now()`. Leave them as-is — they're
     already cleared to run.
   - **Continuous dispatch** (`autonomous` and `off` only): if there are any
     `approved` tasks with resolved dependencies and no currently-running dispatch
     for this plan, call `MissionPlanService.dispatch_approved`.

2. Single process lock per plan id (Redis key with TTL) so multi-instance deploys
   don't double-dispatch.

3. Graceful shutdown on SIGTERM — finish current dispatches, stop accepting new
   ones.

4. Future migration path: for production scale / durability, move this loop to a
   Temporal workflow (see Plan 16). Phase 5 deliverable, asyncio is fine for now.

**Where the code lives.** `modules/backend/services/mission_plan_daemon.py`,
started alongside the HTTP server in the backend bootstrap. Gated behind a config
flag so dev environments without autonomous plans don't spin up an idle loop.

### 10.9 Plan tab data flow (explicit)

To prevent three sources of truth colliding in the UI, the data flow is:

```
┌─────────────────────────────┐
│ mission_plans.task_plan_json │  ← task bodies (title, agent, deps, description)
│   (from GET /plan)           │     fetched once, refetched on mission_plan.refined
└─────────────────────────────┘
              │
              │ join by task_id
              ▼
┌─────────────────────────────┐
│ plan_task_states[]           │  ← durable per-task status
│   (from GET /plan)           │     refetched on mission_plan.task.status_changed
└─────────────────────────────┘
              │
              │ overlay by task_id
              ▼
┌─────────────────────────────┐
│ workspaceStore.liveOverlay   │  ← in-flight runtime state
│   (populated by SSE from     │     cleared after 3s of no events per task
│    plan.step.started, *.completed) │
└─────────────────────────────┘

effective_status(task) =
    liveOverlay[task.task_id]      if present
    plan_task_states[task.task_id] otherwise
```

The `liveOverlay` is a Zustand slice keyed by task_id, populated from the existing
`plan.step.*` events with an auto-expiry on inactivity. It's **additive** to the
existing `workspaceStore` — the ephemeral `planTasks[]` field (which v2 said to
delete) is what gets removed. The `liveOverlay` replaces it with a narrower role:
only transient in-flight states, never the authoritative task list.

### 10.10 Summary of mechanical changes needed

| Change | Location | Size |
|---|---|---|
| Add `precomputed_plan` param to `handle_mission` | `modules/backend/agents/mission_control/mission_control.py` | ~5 lines |
| Expand `handle_mission` return to `HandleMissionResult` | same | ~10 lines |
| Return inserted row id from `persist_mission_results` | `persistence_bridge.py` + `ExecutionPersistenceService.save_execution` | ~3 lines |
| Add `total_spent_usd` column + migration | `mission_plans` table | migration |
| `MissionPlanDaemon` asyncio background task | `services/mission_plan_daemon.py` (new) | ~150 lines |
| Transitive dependency walk for approval | `services/mission_plan.py` helper | ~30 lines |
| Clean-slate refinement archiver | `services/mission_plan.py` helper | ~20 lines |
| Frontend `liveOverlay` Zustand slice | `stores/workspace.ts` | ~40 lines |
| Investigate Planning Agent vs Workflow Architect | spike doc during Phase 1 kickoff | spike |

Everything else — validation, gate factory, roster loading, dispatch loop, budget
enforcement per-run, persistence, SSE events `plan.step.*` — is reused unchanged.

### 10.11 Phase 1 prerequisites (blockers)

Phase 1 cannot start until:

1. **§10.4 refinement-agent decision** is made (Path A / B / C).
2. **§10.1 `handle_mission` contract change** is landed on the branch Phase 1
   builds on. This is a tiny PR that can be merged independently before Phase 1
   begins — it's safe because `precomputed_plan=None` is the default.
3. **§10.6 return expansion** lands in the same tiny PR as §10.1.

Those three prerequisites form a "Phase 0" of roughly 30 lines of Python. Landing
them first de-risks the whole plan.
