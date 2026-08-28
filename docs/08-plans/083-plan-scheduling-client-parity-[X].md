# Plan 83 — Scheduling Client Parity (Web + `mc.py`)

**Status:** Complete (2026-08-28) — web (edit modal, per-workflow trigger, Schedules
section) and `mc.py` (`mc schedule` group) were already implemented in an earlier WIP pass
(commit `6ff9750`) and survived the Plan 84 `mc.py` split intact; this pass verified all of
it against the Definition of Done and closed the one real gap — endpoint-level test coverage
(`tests/unit/backend/api/test_mission_schedules_api.py`). §2.3 (`created_by`) intentionally
not applied — see §11.
**Owner:** unassigned
**Depends on:** Plan 54 (unify-scheduling-under-temporal — shipped). No new backend infrastructure.
**Related:** feedback_thin_clients (clients are thin; logic stays in the service layer), P18 (entry files expose `tree`), rule 008.x (thin-client enforcement), rule 010.1 (entry discoverability).

---

## 1. Context & problem statement

Cron-based scheduling of **workflows** is fully implemented on the backend and reachable from the `admin.py` CLI, but it is **unreachable from the two surfaces end users actually use**:

| Surface | State today | Gap |
|---|---|---|
| Backend REST | ✅ Complete — `GET/POST /missions/{id}/schedules`, `PATCH/DELETE /missions/{id}/schedules/{sid}` in [missions_workflows.py:569–681](../../modules/backend/api/v1/endpoints/missions_workflows.py) | — |
| Backend service | ✅ Complete — `WorkflowScheduleService` (`list_by_mission`, `create_schedule`, `update_schedule`, `toggle_enabled`, `delete_schedule`) | — |
| `admin.py` CLI | ✅ Complete — `admin schedule list/create/enable/disable/delete` (service-based, admin-only) | Admin-only; not for end users |
| Web frontend | ◐ **Orphaned** — hooks (`useSchedules/useCreateSchedule/useUpdateSchedule/useDeleteSchedule`) and `ScheduleModal` exist but **nothing mounts them**. No route, no button, no list. Only `useCreateSchedule` is consumed. | Unreachable |
| `mc.py` CLI | ❌ **Absent** — no `schedule` group at all | Missing |

**Goal:** give the web client and `mc.py` full, reachable scheduling parity with `admin.py`, using the already-built backend REST API. This is a **last-mile wiring task**, not new infrastructure.

### 1.1 Critical design constraint — thin clients

- `mc.py` is a **strict thin client**: its module docstring states *"All commands go through the API server. Zero backend service imports."* It talks to the backend only via [`CliApiClient`](../../modules/clients/cli/api_client.py).
- `admin.py`'s [`schedule_cmds.py`](../../modules/clients/cli/schedule_cmds.py) imports `WorkflowScheduleService` **directly** (`.factory()`). This is acceptable for `admin.py` (service-adjacent ops tool) but **MUST NOT be reused for `mc.py`**. Do **not** import `schedule_cmds.py` or any `modules.backend.services.*` from `mc.py` code paths — rule 008.x / the fast rule checker will reject it, and it violates the thin-client principle.
- The web frontend is already thin (React Query hooks → REST). Keep it that way.

---

## 2. Scope

### 2.1 In scope
1. **Web:** mount the existing `ScheduleModal`; add a per-workflow "Schedule" trigger; add a mission-level **Schedules** list with enable/disable toggle, delete, and edit. Wire the three currently-unused hooks.
2. **`mc.py`:** new `mc schedule` command group (`list`, `create`, `enable`, `disable`, `delete`) implemented as a thin API-client renderer.
3. Tests for both surfaces + backend endpoint integration coverage (if missing).

### 2.2 Out of scope (do NOT do)
- Any change to the scheduler execution engine, Temporal workflows, or the `workflow_schedules` table.
- Scheduling a **free-form mission objective** (vs. a defined workflow). The scheduled unit is a `workflow_definition_id`; that is unchanged here. (Tracked separately — see §8.)
- Refactoring `admin.py` scheduling or `schedule_cmds.py`.
- Cron-expression *builder* UI (natural-language → cron). Freeform cron string with helper text only.

### 2.3 Secondary / optional (flag, do not block on)
- **`created_by` correctness (backend):** `create_mission_schedule` at [missions_workflows.py:621](../../modules/backend/api/v1/endpoints/missions_workflows.py) hardcodes `created_by="user:api"`, ignoring `current_user`. This is a pre-existing wart (violates "no hardcoded values"). If touched, thread `current_user.id`. **Optional** — keep in a separate commit; not required for parity.

---

## 3. Reference: the contract the clients consume

**Endpoints** (all require `require_mission_access`; responses wrapped in `ApiResponse`, so the web `api` helper and CLI `_request` both unwrap `json.data`):

| Method | Path | Body | Returns (`data`) |
|---|---|---|---|
| GET | `/missions/{mission_id}/schedules?enabled_only=false` | — | `{ schedules: WorkflowSchedule[], total: number }` |
| POST | `/missions/{mission_id}/schedules` | `WorkflowScheduleCreateRequest` | `WorkflowSchedule` |
| PATCH | `/missions/{mission_id}/schedules/{schedule_id}` | `WorkflowScheduleUpdateRequest` | `WorkflowSchedule` |
| DELETE | `/missions/{mission_id}/schedules/{schedule_id}` | — | `{ deleted: string }` |

**Schemas** ([workflow_schedule.py](../../modules/backend/schemas/workflow_schedule.py)):
- `WorkflowScheduleCreateRequest`: `workflow_definition_id` (req), `cron_expression` (req, 5-field, `min_length=9`), `timezone` (default `"UTC"`), `description`, `budget_per_run_usd` (≥0.01), `max_iterations` (≥1), `cooldown_seconds` (≥0, default 0). `extra="forbid"`.
- `WorkflowScheduleUpdateRequest`: all optional — `cron_expression`, `timezone`, `enabled`, `description`, `budget_per_run_usd`, `max_iterations`, `cooldown_seconds`.
- `WorkflowScheduleResponse`: adds `id`, `mission_id`, `enabled`, `iteration_count`, `last_fired_at`, `next_fire_at`, `created_by`, `created_at`, `updated_at`.

**TS mirror already exists** ([types/workflow.ts:142–179](../../modules/frontend/src/types/workflow.ts)): `WorkflowSchedule`, `WorkflowScheduleCreateRequest`, `WorkflowScheduleUpdateRequest`. No type changes needed.

---

## 4. Target parity matrix

| Action | `admin.py` (today) | Web (target) | `mc.py` (target) |
|---|---|---|---|
| List schedules for mission | ✅ | ✅ Schedules section | ✅ `mc schedule list` |
| Create schedule for a workflow | ✅ | ✅ modal (exists) | ✅ `mc schedule create` |
| Enable | ✅ | ✅ toggle | ✅ `mc schedule enable` |
| Disable | ✅ | ✅ toggle | ✅ `mc schedule disable` |
| Delete | ✅ | ✅ (confirm) | ✅ `mc schedule delete` |
| Edit cron/budget/etc. | ➖ (delete+recreate) | ✅ modal edit mode | ➖ (enable/disable + delete/recreate) |

Edit mode is web-only (the modal already exists and it's cheap to extend); `mc.py` matches `admin.py` exactly.

---

## 4.5 Reuse audit (do NOT re-implement existing code)

Everything below already exists and **must be reused**, not recreated:

| Need | Reuse this | Location |
|---|---|---|
| REST calls (CLI) | `CliApiClient.get/post/patch/delete`, `api_client()` ctx-mgr | [api_client.py](../../modules/clients/cli/api_client.py) |
| Active-mission id (CLI) | `require_mission(api)` — returns the id string | [api_client.py:391](../../modules/clients/cli/api_client.py) |
| Short-id → full-id (CLI) | `resolve_short_id(...)` (keyword-only) | [api_client.py:431](../../modules/clients/cli/api_client.py) |
| Table + console (CLI) | `build_table`, `get_console` | `modules/clients/common/display` |
| REST calls (web) | `useSchedules/useCreateSchedule/useUpdateSchedule/useDeleteSchedule` | [use-workflows.ts:193](../../modules/frontend/src/hooks/use-workflows.ts) |
| Create/edit form (web) | `ScheduleModal` (extend, don't rewrite) | [schedule-modal.tsx](../../modules/frontend/src/components/workflow/schedule-modal.tsx) |
| Date formatting (web) | `formatUtc` / `formatUtcTime` | [format-date.ts](../../modules/frontend/src/lib/format-date.ts) |
| Row/section/confirm-delete/`IconButton` patterns (web) | copy in-file from `MissionWorkflowRow` | [workflows-panel.tsx](../../modules/frontend/src/components/workspace/workflows-panel.tsx) |
| TS types | `WorkflowSchedule*` (no changes) | [types/workflow.ts:142](../../modules/frontend/src/types/workflow.ts) |

**`resolve_mission` is NOT the right helper** — it returns a mission *dict* by name lookup, not the active-mission id. Use `require_mission`.

**Do NOT reuse `schedule_cmds.py`** — it is service-based (admin-only). `mc_schedule.py` is a new, deliberately separate thin renderer. This is the one intentional near-duplication: the ~15-line schedule **table layout** appears in both `schedule_cmds.py` (renders ORM objects) and the new `mc_schedule.py` (renders API dicts). Extracting a shared renderer would force admin's ORM path and mc's dict path onto one shape and couple two independent surfaces — **not worth it**. Accept the small duplication; do not refactor `admin.py`. (If a shared `render_schedules_table(rows: list[dict])` is ever wanted, that's a separate cleanup, and admin would convert ORM→dict at the call site.)

## 5. Implementation — Web frontend

All work in `modules/frontend/src/`. Follow existing patterns in [workflows-panel.tsx](../../modules/frontend/src/components/workspace/workflows-panel.tsx) (row layout, `IconButton`, toast, confirm-then-delete). No new dependencies.

### Phase W1 — Extend `ScheduleModal` to support edit
File: [components/workflow/schedule-modal.tsx](../../modules/frontend/src/components/workflow/schedule-modal.tsx)

1. Add an optional prop `schedule?: WorkflowSchedule`. When present, the modal is in **edit** mode:
   - Prefill state from `schedule` (`cron_expression`, `timezone`, `description`, `budget_per_run_usd`, `max_iterations`, `cooldown_seconds`).
   - Title becomes `"Edit Schedule"`; submit button `"Save"`.
   - **Rules-of-Hooks note (do not get this wrong):** you cannot call a hook conditionally. Call **both** `const createMutation = useCreateSchedule(missionId)` and `const updateMutation = useUpdateSchedule(missionId, schedule?.id ?? '')` unconditionally at the top of the component (the update mutation with a fallback `''` id is harmless — it simply never fires in create mode). Branch only inside `handleSubmit`: if `schedule` is set, fire `updateMutation.mutate(updateRequest)`; else `createMutation.mutate(createRequest)`. Build the `WorkflowScheduleUpdateRequest` from changed/nonempty fields.
2. `workflowDefinitionId` stays required for create; ignored in edit mode (a schedule is already bound to a workflow).
3. Keep the existing create path unchanged when `schedule` is undefined.
4. Toast: `"Schedule created"` / `"Schedule updated"`.

### Phase W2 — Per-workflow "Schedule" trigger
File: [workflows-panel.tsx](../../modules/frontend/src/components/workspace/workflows-panel.tsx), component `MissionWorkflowRow`.

1. Add a `Clock` icon (from `lucide-react`) `IconButton` next to the existing Run/Edit/Delete buttons (the `<div className="flex shrink-0 items-center gap-1">` block, ~line 238), `tone="muted"`, title `"Schedule this workflow"`.
2. Local state `const [showSchedule, setShowSchedule] = useState(false)`.
3. On click → `setShowSchedule(true)`. Render `{showSchedule && <ScheduleModal missionId={missionId} workflowDefinitionId={workflow.id} onClose={() => setShowSchedule(false)} />}`.
   - Note: `workflow.id` (the `MissionWorkflow.id`) is the `workflow_definition_id` — same id used by the Edit route and delete mutation in this file.

### Phase W3 — Mission-level Schedules section
File: [workflows-panel.tsx](../../modules/frontend/src/components/workspace/workflows-panel.tsx).

1. In `WorkflowsPanel`, call `const { data: schedules, isLoading: loadingSchedules } = useSchedules(missionId)`.
2. Add a new `<SchedulesSection missionId={missionId} schedules={schedules} workflows={missionWorkflows} loading={loadingSchedules} />` inside the body, between `MissionWorkflowsSection` and `TemplatesSection` (~line 100). Pass `missionWorkflows` so the section can resolve `workflow_definition_id → workflow.name`.
3. New `SchedulesSection` component (same file, mirror `MissionWorkflowsSection` styling):
   - Header `"Schedules"` + count `Badge`.
   - Empty state: dashed box, `"No schedules. Use the clock icon on a workflow to create one."`
   - One `ScheduleRow` per schedule.
4. New `ScheduleRow` component:
   - Left icon: enabled → `CheckCircle2` emerald; disabled → `Circle` muted (mirror `MissionWorkflowRow`).
   - Primary line: resolved workflow name (fallback to `workflow_definition_id` if not found) + `Badge` with `cron_expression`.
   - Secondary line: `next_fire_at` and `last_fired_at` formatted with the **existing** `formatUtc` from [`@/lib/format-date`](../../modules/frontend/src/lib/format-date.ts) (do **not** hand-roll date formatting or emit raw ISO) + iterations `iteration_count`(`/max_iterations` if set) + timezone.
   - Actions (`IconButton`s):
     - **Toggle**: `Power`/`PowerOff` icon → `useUpdateSchedule(missionId, s.id).mutate({ enabled: !s.enabled })`; toast `"Schedule enabled/disabled"`.
     - **Edit**: `Pencil` → open `ScheduleModal` in edit mode with `schedule={s}`.
     - **Delete**: `Trash2` with the same confirm-then-confirm pattern as `MissionWorkflowRow.handleDelete` → `useDeleteSchedule(missionId).mutateAsync(s.id)`; toast.
5. All mutations already invalidate `workflowKeys.schedules(missionId)` (see [use-workflows.ts:210–244](../../modules/frontend/src/hooks/use-workflows.ts)) — the list refreshes automatically. No manual refetch.

### Phase W4 — Verify hook/type wiring
- Confirm `@/types` barrel re-exports the schedule types (it must — `ScheduleModal` already imports `WorkflowScheduleCreateRequest` from `@/types`). If `WorkflowSchedule` isn't exported, add `export * from './workflow'` coverage.
- `useUpdateSchedule` is `(missionId, scheduleId)` — construct it per-row (hooks-in-map is fine here because each `ScheduleRow` is its own component, so the hook is called at component top level, not inside a loop).

**Web acceptance:** From a mission's Workflows tab, a user can (a) click the clock on a workflow to create a schedule, (b) see it appear in the Schedules section, (c) toggle it on/off, (d) edit its cron/budget, (e) delete it — all without a page reload, with toasts on success/error.

---

## 6. Implementation — `mc.py` CLI

Strict thin client. Two files: a new handler module + group registration in `mc.py`.

### Phase C1 — New handler `modules/clients/cli/mc_schedule.py`
Mirror [mc_gate.py](../../modules/clients/cli/mc_gate.py) **exactly** for structure and the mission-resolution contract. Module docstring with a `Commands:` block, `from __future__ import annotations`, imports from `modules.clients.cli.api_client` (`ApiError`, `CliApiClient`, `resolve_short_id`) and `modules.clients.common.display` (`build_table`, `get_console`). **No `modules.backend.services` imports. No `api_client()` open inside the handlers.**

**Follow the established idiom (verified against the `gate` group, [mc.py:561–662](../../mc.py)):** the *command wrapper in `mc.py`* opens the client and resolves the active mission; each handler here receives an already-open `api` and a resolved `mission_id`. Handlers do **not** open `api_client()` and do **not** resolve the mission themselves — that avoids duplicating the client/auth/mission plumbing across five functions.

Handler signatures (all `async def ... (api: CliApiClient, *, mission_id: str, ...)`):
- `list_schedules(api, *, mission_id, output_format="human")` → `await api.get(f"/missions/{mission_id}/schedules", params={"enabled_only": "false"})`; render with `build_table` (columns: Enabled, Cron, Workflow, Iterations, Next Fire, Description — mirror [schedule_cmds.py:73–96](../../modules/clients/cli/schedule_cmds.py)). Empty → dim "No schedules." Honour `output_format="json"` by printing the raw `data`.
- `create_schedule(api, *, mission_id, workflow, cron, description, budget, max_iterations, cooldown)` → build a `WorkflowScheduleCreateRequest`-shaped dict and **omit keys whose value is `None`** (backend schema is `extra="forbid"` and rejects nulls on optional numeric fields); `await api.post(f"/missions/{mission_id}/schedules", body=payload)`. Print new id + cron + `next_fire_at`.
- `set_enabled(api, *, mission_id, schedule_id, enabled: bool)` → resolve id (below), then `await api.patch(f"/missions/{mission_id}/schedules/{sid}", body={"enabled": enabled})`. Shared by `enable`/`disable`.
- `delete_schedule(api, *, mission_id, schedule_id)` → resolve id, then `await api.delete(f"/missions/{mission_id}/schedules/{sid}")`. Print confirmation.

**Short-id resolution** — add a module-local helper mirroring `mc_gate._resolve_gate_id` ([mc_gate.py:221](../../modules/clients/cli/mc_gate.py)), calling the keyword-only `resolve_short_id` with its exact signature:
```python
async def _resolve_schedule_id(api: CliApiClient, mission_id: str, prefix: str) -> str:
    return await resolve_short_id(
        api,
        list_url=f"/missions/{mission_id}/schedules?enabled_only=false",
        list_field="schedules",
        prefix=prefix,
        not_found_hint="Run `mc schedule list` to see ids.",
    )
```

Error handling: on `ApiError` print a red, actionable message and `sys.exit(1)` (match `mc_gate.py`). Do not swallow (rule 002.3 / 014).

### Phase C2 — Register the `schedule` group in `mc.py`
File: [mc.py](../../mc.py). Add after the `gate` group (~line 663), copying the `gate` idiom **verbatim in shape**: group uses `@click.pass_context`; each subcommand uses `@click.pass_obj` and an inner `_run()` that does `async with api_client() as api: mid = await require_mission(api); await <handler>(api, mission_id=mid, ...)`. The mission is always the **active mission** (via `require_mission`) — no `--mission` flag, matching `mc gate`/`mc plan`/`mc status`. Schedule ids are positional arguments (matches `mc gate decide <id>`); create params are `--options`.

```python
@mc.group("schedule", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def schedule(ctx):
    """Recurring workflow runs (cron) for the current mission.

    Examples:
        mc schedule list
        mc schedule create --workflow <id> --cron "0 9 * * *"   # daily 09:00
        mc schedule create --workflow <id> --cron "0 9 * * 1"   # weekly Mon
        mc schedule enable <schedule_id>
        mc schedule disable <schedule_id>
        mc schedule delete <schedule_id>
    """
    if ctx.invoked_subcommand is None:
        from modules.clients.cli.mc_schedule import list_schedules
        async def _run():
            async with api_client() as api:
                mid = await require_mission(api)
                await list_schedules(api, mission_id=mid)
        asyncio.run(_run())

@schedule.command("list")
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output.")
@click.pass_obj
def schedule_list(ctx, as_json):
    """List schedules for the current mission."""
    from modules.clients.cli.mc_schedule import list_schedules
    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await list_schedules(api, mission_id=mid,
                                 output_format="json" if as_json else "human")
    asyncio.run(_run())

@schedule.command("create")
@click.option("--workflow", required=True, help="Workflow definition id to schedule.")
@click.option("--cron", required=True, help='5-field cron: "min hour day month weekday".')
@click.option("--description", default="", help="Optional description.")
@click.option("--budget", type=float, default=None, help="USD ceiling per run.")
@click.option("--max-iterations", type=int, default=None, help="Total runs (unlimited if omitted).")
@click.option("--cooldown", type=int, default=0, help="Min seconds between runs.")
@click.pass_obj
def schedule_create(ctx, workflow, cron, description, budget, max_iterations, cooldown):
    """Create a cron schedule for a workflow."""
    from modules.clients.cli.mc_schedule import create_schedule
    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await create_schedule(api, mission_id=mid, workflow=workflow, cron=cron,
                                  description=description, budget=budget,
                                  max_iterations=max_iterations, cooldown=cooldown)
    asyncio.run(_run())

# enable / disable / delete follow the same wrapper shape; each resolves
# `mid = await require_mission(api)` then calls set_enabled(..., enabled=True|False)
# or delete_schedule(...). `schedule_id` is a positional @click.argument.
```

Keep imports lazy inside commands (matches every other `mc.py` group). Do not add module-level backend imports. `api_client` and `require_mission` are already imported at the top of `mc.py` (used by every group) — reuse them, don't re-import.

### Phase C3 — `tree` / discoverability (P18, rule 010.1)
Click auto-includes the new group in `mc.py tree`. After implementing, run `python mc.py tree` and confirm the `schedule` group and all five subcommands + their flags appear. No hand-maintained list.

**`mc.py` acceptance:** `mc schedule create --workflow <id> --cron "0 9 * * *"` on the active mission creates a daily schedule; `mc schedule list` shows it; `mc schedule disable <id>` / `enable <id>` toggle it; `mc schedule delete <id>` removes it — all via the REST API, zero backend-service imports.

---

## 7. Testing (P11/P12 — real infra, no LLM calls)

### Backend (verify/patch)
- File: `tests/integration/backend/api/` (co-locate with existing mission/workflow endpoint tests).
- If not already present, add integration tests hitting real Postgres for all four endpoints: create → list (found) → patch enabled=false (reflected) → delete → list (gone). Assert `ApiResponse` envelope and `require_mission_access` (403 for a non-member).

### Web
- If the frontend has a component-test harness (check for `vitest`/`@testing-library` in [package.json](../../modules/frontend/package.json)): add a `schedule-modal` test (create + edit submit shapes) and a `SchedulesSection` render/toggle/delete test with mocked hooks. If **no** harness exists, do **not** introduce one for this plan — instead document a manual verification checklist in the PR/commit message and rely on the backend + CLI tests. (State which path was taken.)

### `mc.py` CLI
- File: `tests/integration/clients/test_mc_schedule.py` (real API, per P12) OR a `click.testing.CliRunner` test that drives the group against a live test server. Cover: `list` empty, `create` (assert printed id), `enable`/`disable` round-trip, `delete`. Assert the handler makes **no** `modules.backend.services` import (a static check: `assert "modules.backend.services" not in Path("modules/clients/cli/mc_schedule.py").read_text()`), enforcing thin-client compliance.

### Gate
- `python scripts/code_rules_fast.py --all` must show **no new errors** (esp. 008.x thin-client, 002.3 swallowed-except, 014.x error visibility). Warnings count must not increase for the touched files.

---

## 8. Known limitation to surface (not fixed here)

Scheduling binds to a **`workflow_definition_id`**, so only *defined workflows* can be scheduled — not a free-form mission objective (`mc run "<objective>"`). If product wants "run this objective every morning," that requires either (a) wrapping the objective as a saved single-step workflow, or (b) a new `mission_objective_schedules` path. **Out of scope for Plan 83** — call it out in the delivery notes so it's a conscious deferral, not a silent gap.

---

## 9. Definition of Done

- [x] Web: clock trigger on each workflow row opens the create modal bound to that workflow.
- [x] Web: Schedules section lists all mission schedules with workflow name, cron, next fire, iterations; toggle, edit, delete all work with toasts; list auto-refreshes.
- [x] Web: `ScheduleModal` supports both create and edit; `useUpdateSchedule`/`useDeleteSchedule`/`useSchedules` are all now consumed (no orphaned hooks).
- [x] `mc.py`: `mc schedule list/create/enable/disable/delete` implemented as a thin API-client renderer; `mc_schedule.py` has zero backend-service imports.
- [x] `python mc.py tree` shows the `schedule` group and all subcommands/flags.
- [x] Backend endpoint integration tests pass against real Postgres; CLI + (optional) web tests pass.
- [x] `scripts/code_rules_fast.py --all` shows no new errors and no new warnings on touched files.
- [x] Delivery notes state the free-form-objective limitation (§8) and whether the optional `created_by` fix (§2.3) was applied.

---

## 11. Delivery notes (2026-08-28)

**What this pass found:** the web and `mc.py` client work (§5, §6) was already built in an
earlier WIP commit (`6ff9750`, 2026-07-16) and remained intact through the Plan 84 `mc.py`
file split. This plan's own Status/gap-analysis in §1 had gone stale — a documentation-status
drift, not a code gap. Verified directly against source rather than trusting the doc:

- `ScheduleModal` edit mode, per-workflow clock trigger, and `SchedulesSection`
  (toggle/edit/delete, toasts, auto-refresh via query invalidation) all present in
  `workflows-panel.tsx` / `schedule-modal.tsx`. `npx tsc --noEmit` is clean.
- `mc schedule list/create/enable/disable/delete` present in `mc_groups/schedule.py` +
  `mc_schedule.py`, zero backend-service imports, `mc.py tree` lists the group.
- The one real gap: no endpoint-level test existed for
  `GET/POST/PATCH/DELETE /missions/{id}/schedules*`. Added
  `tests/unit/backend/api/test_mission_schedules_api.py`, mirroring the existing
  `test_executions_api.py` convention (mocked service + real FastAPI app + `ApiResponse`
  envelope assertions), including a 403-for-non-member case via `require_mission_access`.
  Real-Postgres service-layer behaviour was already covered by
  `tests/unit/backend/services/test_workflow_schedule.py` (P12) — not duplicated here.
- No frontend test harness exists in this repo (`package.json` has no vitest/testing-library,
  zero `*.test.ts*` files anywhere) — per §7's fallback, no harness was introduced; web
  coverage relies on `tsc` + the backend/CLI tests above plus this note as the manual-check
  record.
- §2.3 (`created_by` hardcoded to `"user:api"` instead of `current_user.id`) was **not**
  applied — left as a pre-existing, separately-fixable wart per the plan's own "optional,
  keep in a separate commit" framing.
- §8's free-form-objective limitation stands as documented — scheduling still binds to a
  `workflow_definition_id`, not an ad-hoc mission objective.

## 10. Suggested commit sequence
1. `mc.py schedule group + mc_schedule.py (thin API client)` + CLI test.
2. `web: extend ScheduleModal (edit mode)`.
3. `web: mount schedule trigger + Schedules section in workflows-panel`.
4. `tests: backend schedule endpoint integration coverage` (if missing).
5. *(optional)* `fix: create_mission_schedule uses current_user, not hardcoded user:api`.
