# Plan 53 — Workflow DB as Source of Truth + Plan-Workflow Integration

| Field | Value |
|-------|-------|
| **Status** | Ready |
| **Created** | 2026-04-13 |
| **Depends on** | Plan 42 (Mission Backlog Model — done), Plan 52 (Temporal Backbone — done) |
| **Target** | Workflow service layer, plan dispatch, frontend plan board |

---

## 1  Problem

Two gaps block the workflow system from being useful:

1. **Workflows can't run from DB.** The Workflow Architect saves workflows to `workflow_definitions` (DB), but `WorkflowRunService.run_workflow()` reads from YAML files only. Any workflow created via the Director's `design_workflow` tool is saved but can never execute.

2. **Plans can't invoke workflows.** The dispatch loop handles single-agent tasks and convergence loops, but has no concept of a task that invokes a multi-step workflow. Users must choose between "plan with tasks" OR "run a workflow" — they can't compose them.

---

## 2  Target Architecture

```
YAML templates (config/workflow_templates/)
        │
        ▼ seed on first boot
workflow_definitions table ◄── Workflow Architect saves here too
        │
        ▼ runtime reads
WorkflowRunService.run_workflow()
        │
        ▼ also callable from
dispatch loop (task.type == "workflow")
        │
        ▼
plan_task_states (status tracking)
```

### Design decisions

- **DB is authoritative.** YAML seeds on first boot (same as agent catalog). Admin edits in DB persist across restarts. `--force` re-seeds from YAML.
- **Plan tasks can be agent OR workflow.** A `TaskDefinition` with `agent: "workflow:ops.health-check"` invokes the named workflow instead of a single agent. The dispatch loop detects the `workflow:` prefix and delegates to `WorkflowRunService`.
- **Workflow results map to task results.** The workflow's `ExecutionOutcome` (or `WorkflowRun` status) becomes the task's result in the plan. Cost, duration, and status roll up.
- **Frontend shows workflow tasks distinctly.** The plan board renders a workflow task with a different icon and shows the workflow's step count.

---

## 3  Phases

### Phase A — Workflow DB Seeder + Runner from DB

**Goal:** YAML templates seed `workflow_definitions` on first boot. `WorkflowRunService` reads from DB. Architect-created workflows are immediately runnable.

#### 3.1 Workflow Seeder

**New file:** `modules/backend/services/workflow_seeder.py`

Same pattern as `catalog_seeder.py`:

```python
async def seed_workflows(
    service: WorkflowDefinitionService,
    *,
    force: bool = False,
) -> dict[str, int]:
    """Seed workflow_definitions from YAML templates.

    Scans config/workflow_templates/**/*.yaml.
    Skips if table is non-empty (unless force=True).
    Each template creates a workflow_definition with:
      - mission_id = NULL (system template)
      - designed_by = "import:yaml_seed"
      - All fields mapped from WorkflowSchema

    Returns {"seeded": N, "skipped": M, "errors": E}
    """
```

**Rules:**
- System templates have `mission_id = NULL` — they're global, not mission-scoped
- Enabled flag from YAML is preserved
- Version from YAML is preserved
- `designed_by = "import:yaml_seed"` for audit trail
- Duplicate detection by `name` (unique constraint on `(mission_id, name)` — NULL mission_id + name is unique)

**Integration:**
- Call `seed_workflows()` in `modules/backend/main.py` lifespan, after agent catalog seeding
- Add `admin seed-workflows` CLI command (or extend `admin seed-catalog` to do both)

#### 3.2 WorkflowRunService Reads from DB

**Modified file:** `modules/backend/services/workflow_run.py`

Change `run_workflow()` to read from `workflow_definitions` table instead of YAML:

```python
async def run_workflow(
    self,
    workflow_name: str,
    triggered_by: str = "system:cli",
    mission_id: str | None = None,  # NEW — scope to mission
    context_overrides: dict | None = None,
    on_progress: Any = None,
    gate: object | None = None,
) -> WorkflowRun:
    """Run a workflow from the DB.

    Resolution order:
    1. Mission-scoped workflow (mission_id + workflow_name)
    2. System template (mission_id IS NULL + workflow_name)
    3. Raise NotFoundError
    """
```

**Changes:**
1. Replace `WorkflowService.get_workflow(workflow_name)` with `WorkflowDefinitionService.get_workflow(mission_id, workflow_name)` (falling back to `get_workflow(None, workflow_name)` for system templates)
2. Convert `WorkflowDefinition` DB model to the internal `WorkflowSchema` format that the execution engine expects. Add a `_definition_to_schema(defn: WorkflowDefinition) -> WorkflowSchema` converter method.
3. The rest of the execution pipeline (topological sort, wave execution, output chaining) stays the same — it operates on `WorkflowSchema` internally.

**Migration path:** The old `WorkflowService` (YAML loader) becomes a utility used only by the seeder. `WorkflowRunService` no longer imports it.

#### 3.3 Director `run_workflow` Tool Fix

**Modified file:** `modules/backend/agents/mission/director/agent.py`

Update the `run_workflow` tool's background task to pass `mission_id`:

```python
async def _run_in_background():
    async with WorkflowRunService.factory() as svc:
        await svc.run_workflow(
            workflow_name=workflow_name,
            triggered_by="mission_director",
            mission_id=ctx.deps.mission_id,  # ADD THIS
        )
```

#### 3.4 API Endpoint Updates

**Modified file:** `modules/backend/api/v1/endpoints/missions_workflows.py`

The existing workflow list/import endpoints read from YAML. Update them:
- `GET /missions/{id}/workflows` — read from `workflow_definitions` where `mission_id = {id}` OR `mission_id IS NULL`
- `POST /missions/{id}/workflows/import` — copy a system template (mission_id=NULL) into a mission-scoped copy (mission_id={id})
- `POST /missions/{id}/workflows/{name}/run` — NEW endpoint to run a workflow by name

#### 3.5 Delete Old YAML Loading from Runtime

**Modified file:** `modules/backend/services/workflow.py`

Keep the file but mark `load_workflows()` and `get_workflow()` as used only by the seeder. The runtime path (`WorkflowRunService`) no longer calls them. Add a deprecation comment.

Do NOT delete the file yet — the seeder uses it to parse YAML.

#### 3.6 Migration

**New file:** `modules/backend/migrations/versions/20260414_seed_workflows.py`

No schema change needed — `workflow_definitions` table already exists with all required columns. The migration is a data migration that seeds existing YAML templates if the table has no system templates (mission_id IS NULL).

#### 3.7 Tests

- Test that `seed_workflows` creates expected rows from YAML
- Test that `run_workflow` resolves mission-scoped before system template
- Test that `run_workflow` for a DB-saved workflow executes successfully
- Test that `run_workflow` raises `NotFoundError` for unknown names

**Acceptance:** `ops.health-check` (created by Workflow Architect) runs when the Director calls `run_workflow("ops.health-check")`.

---

### Phase B — Plan-Workflow Integration

**Goal:** Plan tasks can invoke workflows. The dispatch loop detects `agent: "workflow:<name>"` and delegates to `WorkflowRunService`.

#### 3.8 TaskDefinition Convention

**No schema change needed.** The existing `TaskDefinition.agent` field is a string. Use a prefix convention:

- `agent: "software.quality.agent"` — single agent task (existing)
- `agent: "workflow:ops.health-check"` — workflow task (NEW)

The dispatch loop checks for the `workflow:` prefix to route.

**Why not a new `type` field:** Adding a field to `TaskDefinition` requires changing the Planning Agent's output contract, all validators, the plan board types, and every consumer. The prefix convention is zero-schema-change and self-documenting.

#### 3.9 Dispatch Loop: Workflow Fork

**Modified file:** `modules/backend/agents/mission_control/dispatch/loop.py`

In `_execute_layer()`, after the convergence loop check (Plan 51 Phase B) and before the standard agent task path, add:

```python
# ── Workflow task fork ──────────────────────────────────────
if task.agent.startswith("workflow:"):
    workflow_name = task.agent.split(":", 1)[1]
    coros.append(
        _dispatch_workflow_task(
            task=task,
            workflow_name=workflow_name,
            mission_id=plan.mission_id,
            event_bus=event_bus,
            session_id=session_id,
            gate=gate,
        )
    )
    layer_tasks.append(task)
    continue
```

**New function in loop.py:**

```python
async def _dispatch_workflow_task(
    task: TaskDefinition,
    workflow_name: str,
    mission_id: str,
    event_bus: EventBusProtocol,
    session_id: str,
    gate: Any,
) -> TaskResult:
    """Execute a workflow as a plan task."""
    from modules.backend.agents.mission_control.helpers import _emit
    from modules.backend.events.types import PlanStepStartedEvent, PlanStepCompletedEvent

    await _emit(event_bus, PlanStepStartedEvent, ...)

    try:
        async with WorkflowRunService.factory() as svc:
            run = await svc.run_workflow(
                workflow_name=workflow_name,
                triggered_by="plan_dispatch",
                mission_id=mission_id,
                gate=gate,
            )

        status = TaskStatus.SUCCESS if run.status == "COMPLETED" else TaskStatus.FAILED
        return TaskResult(
            task_id=task.task_id,
            agent_name=f"workflow:{workflow_name}",
            status=status,
            output={"workflow_run_id": str(run.id), "status": run.status},
            cost_usd=run.total_cost_usd or 0.0,
            duration_seconds=...,
            token_usage=TokenUsage(),
        )
    except Exception as e:
        return TaskResult(
            task_id=task.task_id,
            agent_name=f"workflow:{workflow_name}",
            status=TaskStatus.FAILED,
            output={"error": str(e)},
        )
    finally:
        await _emit(event_bus, PlanStepCompletedEvent, ...)
```

#### 3.10 Director: Create Plan Tasks That Run Workflows

**Modified file:** `modules/backend/agents/mission/director/agent.py`

Update the Director's system prompt (or add guidance) so it knows it can use `workflow:` prefix in `refine_plan` instructions:

```
When the user asks to add a workflow as a plan task, use agent="workflow:<workflow_name>"
in the task specification. Example:
  Task: Run the health check workflow
  agent: workflow:ops.health-check
```

No code change needed — the Planning Agent generates `TaskDefinition` objects. If the Director's refinement instructions say `agent: "workflow:ops.health-check"`, the Planning Agent will include it in the plan.

#### 3.11 Plan Validator Update

**Modified file:** `modules/backend/agents/mission_control/plan_validator.py`

The validator checks that each task's `agent` exists in the roster. Workflow tasks won't be in the roster. Add an exception:

```python
# Skip roster check for workflow tasks — they resolve at dispatch time
if task.agent.startswith("workflow:"):
    continue
```

#### 3.12 Frontend: Workflow Task Rendering

**Modified file:** `modules/frontend/src/components/workspace/plan-board.tsx`

In `TaskCard`, detect workflow tasks and render differently:

```typescript
const isWorkflow = body.agent.startsWith('workflow:')
const workflowName = isWorkflow ? body.agent.slice(9) : null
```

Visual changes:
- Show a workflow icon (e.g. `GitBranch`) instead of the agent domain icon
- Show the workflow name instead of the agent name in the badge
- Add a "(workflow)" label or distinct border color

**Modified file:** `modules/frontend/src/hooks/use-mission-plan.ts`

No changes needed — `PlanTaskBody.agent` is already a string. The `workflow:` prefix is just a convention in the existing field.

#### 3.13 Tests

- Test that `_dispatch_workflow_task` runs a workflow and returns a `TaskResult`
- Test that a plan with mixed agent + workflow tasks dispatches correctly
- Test that the plan validator allows `workflow:` agents
- Test that workflow task results write back to `plan_task_states`

**Acceptance:** Create a plan with `agent: "workflow:ops.health-check"`, approve, dispatch. The workflow runs, results appear in the plan board, cost rolls up.

---

### Phase C — Polish

#### 3.14 Workflow Seeder CLI

**Modified file:** `admin.py`

Add `admin seed-workflows` command:

```python
@admin_cli.command("seed-workflows")
@click.option("--force", is_flag=True, help="Delete and reseed all system workflows")
def seed_workflows_cmd(ctx, force):
    """Seed workflow_definitions from YAML templates."""
    ...
```

#### 3.15 Workflow List in Director

**Modified file:** `modules/backend/agents/mission/director/agent.py`

Update `list_workflows` tool to read from DB instead of YAML:

```python
@agent.tool
async def list_workflows(ctx: RunContext[MissionDirectorDeps]) -> str:
    """List available workflows (mission-scoped + system templates)."""
    svc = WorkflowDefinitionService(ctx.deps.db_session)
    workflows = await svc.list_workflows(ctx.deps.mission_id, enabled_only=True)
    # Also include system templates
    system_wfs = await svc.list_workflows(None, enabled_only=True)
    ...
```

#### 3.16 Frontend Workflow Tab

**Modified file:** `modules/frontend/src/pages/mission/workflows.tsx` (or `modules/frontend/src/components/workspace/workflows-panel.tsx`)

Update to read from the DB-backed API instead of YAML templates. Show both mission-scoped workflows and system templates with a "clone" action.

---

## 4  Files Changed (Summary)

| Phase | File | Action |
|-------|------|--------|
| A | `modules/backend/services/workflow_seeder.py` | **New** — YAML→DB seeder |
| A | `modules/backend/services/workflow_run.py` | **Modify** — read from DB, add `_definition_to_schema()` |
| A | `modules/backend/services/workflow.py` | **Modify** — deprecation comment, used only by seeder |
| A | `modules/backend/main.py` | **Modify** — call `seed_workflows()` in lifespan |
| A | `modules/backend/agents/mission/director/agent.py` | **Modify** — pass `mission_id` to `run_workflow` |
| A | `modules/backend/api/v1/endpoints/missions_workflows.py` | **Modify** — read from DB |
| B | `modules/backend/agents/mission_control/dispatch/loop.py` | **Modify** — add `_dispatch_workflow_task()` |
| B | `modules/backend/agents/mission_control/plan_validator.py` | **Modify** — skip roster check for `workflow:` |
| B | `modules/frontend/src/components/workspace/plan-board.tsx` | **Modify** — workflow task rendering |
| C | `admin.py` | **Modify** — add `seed-workflows` command |
| C | `modules/backend/agents/mission/director/agent.py` | **Modify** — `list_workflows` reads DB |
| C | Frontend workflows panel | **Modify** — read from DB API |

---

## 5  What Gets Deleted

- Nothing deleted in Phase A-B. The YAML loader (`workflow.py`) is preserved for the seeder.
- In a future cleanup phase: remove `WorkflowService.load_workflows()` / `get_workflow()` calls from any remaining runtime paths. The seeder keeps them.

---

## 6  Exit Criteria

1. YAML templates seed `workflow_definitions` on first boot (mission_id=NULL, designed_by="import:yaml_seed")
2. `ops.health-check` (created by Workflow Architect) runs via `mc run ops.health-check` and from the Director's `run_workflow` tool
3. A plan task with `agent: "workflow:ops.health-check"` dispatches the workflow, reports results, and updates plan_task_states
4. The plan board shows workflow tasks with a distinct icon
5. Workflow list (Director tool + frontend) reads from DB
6. System templates can be cloned into mission-scoped copies
7. Admin edits to workflow definitions in DB survive server restarts (not overwritten by YAML seeder unless --force)

---

## 7  Estimated Effort

| Phase | Scope | Effort |
|-------|-------|--------|
| A | Seeder + DB runner + Director fix | ~3-4 hours |
| B | Dispatch loop + validator + frontend | ~2-3 hours |
| C | CLI + list tool + frontend polish | ~1-2 hours |
| **Total** | | **~6-9 hours** |
