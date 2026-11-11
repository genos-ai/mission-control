# 29 - Temporal Workflow Versioning (Optional Module)

*Version: 1.1.0*
*Author: Architecture Team*
*Created: 2026-11-11*

## Changelog

- 1.1.0 (2026-11-11): Drain procedure (section 5) for the Plan 88 Phase 2 release, with the dev-stack drill findings (Plan 88 step 88.2.10)
- 1.0.0 (2026-11-11): Initial standard. Patch-id registry, `workflow.patched` policy, no `deprecate_patch` inside the introducing plan, replay fixtures per patch (Plan 88 step 88.2.8)

---

## Module Status: Optional

This module is **optional**. Adopt it when your project runs Temporal workflows whose executions can outlive a deploy: long-running missions, recurring schedules, or anything that waits on a signal or a durable timer.

**Dependencies**: **14-core-background-tasks.md** (task and workflow placement) and **11-core-testing-standards.md** (test layout).

---

## Context

A Temporal worker rebuilds workflow state by replaying the recorded event history against the current code. If the new code issues a different sequence of commands for the same history, replay raises `NondeterminismError` and the execution is stuck until it is cancelled or the old code returns. A mission run can wait for days on a supervisor decision or a human gate, so "deploy when the queue is empty" does not hold.

There are two ways to ship a workflow change safely. **Patching** (`workflow.patched`) keeps the old and new branches side by side, so executions already in flight replay the old branch and new executions take the new one. **Draining** stops new starts, lets in-flight executions finish or cancels them, then deploys. Patching is the default; draining is reserved for wholesale replacement of an activity graph.

---

## 1. What Counts as a Command Change

Replay compares the commands a workflow issues, in order. A change needs a patch when it alters the **order, type or arguments** of any of these commands:

| Command | Typical call |
|---------|--------------|
| Activity | `workflow.execute_activity(...)`, `workflow.start_activity(...)` |
| Timer | `workflow.sleep(...)`, `workflow.wait_condition(..., timeout=...)` |
| Child workflow | `workflow.execute_child_workflow(...)`, `workflow.start_child_workflow(...)` |
| Signal sent | `handle.signal(...)` on an external workflow handle |
| Continue-as-new | `workflow.continue_as_new(...)` |

Changes that issue no command (pure computation on state already in the workflow, log lines, query handlers) do not need a patch. When in doubt, patch: an unnecessary patch costs one branch, a missing one strands every in-flight execution.

---

## 2. Policy

These rules apply to every module matching `modules/backend/temporal/*workflow*.py`. `tests/unit/backend/temporal/test_patch_ids.py` enforces rules 2.1, 2.2, 2.3 and 2.5.

### 2.1 Wrap command changes in `workflow.patched`

```python
if workflow.patched("p88-run-memory"):
    memory = await workflow.execute_activity(load_run_memory, ...)   # new
else:
    memory = None                                                     # old
```

The id is a **string literal** at the call site and is also registered in `PATCH_IDS` in `modules/backend/temporal/versioning.py`. That module is the only registry of patch ids. A computed id, or one missing from the registry, fails the test.

### 2.2 Id format

Ids are `p{plan}-{kebab-slug}`, matching `^p\d{2,3}-[a-z0-9]+(-[a-z0-9]+)*$`. Examples: `p88-run-memory`, `p88-budget-caps`.

An id is **never reused or renamed**. Temporal records the id in the history as a marker; renaming it makes every execution that recorded the old id take the old branch forever, or fail replay once that branch is removed.

### 2.3 No `deprecate_patch` inside the introducing plan

`workflow.deprecate_patch` is not called. An old branch is removed only by a later plan, and only after this query returns 0 for executions started before the patch was deployed:

```bash
temporal workflow count --query "WorkflowType='MissionRunWorkflow' AND ExecutionStatus='Running'"
```

Narrow the query with `AND StartTime < '<deploy time, RFC 3339>'` when newer executions are expected to be running. Removing the old branch then goes through `deprecate_patch` for one release before the call is deleted.

### 2.4 Patch or drain

Patching is the default for every change. Draining is used only when a change replaces the activity graph wholesale, so that a patch would duplicate the entire workflow body. Plan 88 Phase 2 is the one such change: it ships without patches and uses the drain procedure in section 5 (Plan 88 step 88.2.10). Every change after Phase 2 uses patches.

### 2.5 One commit per patch, with its replay history

A step that introduces `workflow.patched("<id>")` does three things in the same commit:

1. Adds `<id>` to `PATCH_IDS` in `modules/backend/temporal/versioning.py`.
2. Records one history that takes the new branch at `tests/fixtures/temporal_histories/mission_run/<id>.json`.
3. Adds `<id>` to `REQUIRED` in `tests/unit/backend/temporal/test_replay_histories.py`.

Histories that take the old branch are kept, so the replay suite proves both branches still replay. Planned Plan 88 ids: `p88-run-memory` (Phase 3; its pre-patch fixture is recorded from Phase 2 code), `p88-lifecycle-signals`, `p88-budget-caps` and `p88-durable-gate` (Phase 4).

---

## 3. Enforcement

| Check | Where |
|-------|-------|
| Every `workflow.patched(...)` argument is a string literal in `PATCH_IDS` | `test_patch_calls_use_registered_literal_ids` |
| Every registered id matches the pattern | `test_registered_ids_match_pattern` |
| Every registered id has a recorded history | `test_registered_ids_have_histories` |
| No `deprecate_patch` call in `temporal/` | `test_no_deprecate_patch` |
| Recorded histories still replay on current code | `test_replay_histories.py` (Plan 88 step 88.2.9) |

---

## 4. Checklist for a Workflow Change

1. Does the change alter the order, type or arguments of a command (section 1)? If not, no patch.
2. Choose a new id `p{plan}-{slug}`; confirm it has never been used.
3. Wrap the change in `if workflow.patched("<id>"): <new> else: <old>`.
4. Register the id, record the new-branch history, add the id to `REQUIRED` (rule 2.5).
5. Run `pytest tests/unit/backend/temporal -q`.
6. Leave the old branch in place. Removal belongs to a later plan, after the count in rule 2.3 is 0.

---

## 5. Drain Procedure

Run once for the Plan 88 Phase 2 release, in this order. Phase 1 `MissionRunWorkflow` executions carry the wave-activity graph and no Phase 2 state, so they raise `NondeterminismError` on Phase 2 code. `ChatTurnWorkflow`, `PlanRefineWorkflow`, `DesignWorkflowWorkflow` and `RunWorkflowWorkflow` inputs gained a required `timeouts` field, so an execution started before the deploy cannot decode its input afterwards. `AgentMissionWorkflow` no longer exists on the worker.

### 5.1 Preconditions

**Old code stays on disk until step 4.** The Temporal workflow sandbox re-imports workflow modules from the code directory each time it creates a workflow instance. A worker whose code directory has already moved to the new release is not running the old release: it fails every new or evicted workflow task with an import error, and it cannot finalise a cancelled run. Steps 1 to 3 must run while the old release is both loaded and on disk. On the dev stack, that means before checking out the new commit; with immutable images it holds by construction.

**A flag change needs a worker restart.** The worker syncs every mission schedule at startup and every 5 minutes through the reconciler (`sync_mission_schedules`), and both read `missions.recurrence.enabled` from the process's cached `get_app_config()`. Editing the YAML and running `admin.py schedules sync` alone is undone within 5 minutes: a worker that cached `true` recreates the schedules, and one that cached `false` deletes them again.

**CLI address.** The `temporal` CLI defaults to `localhost:7233`, which can resolve to `::1` while the server listens on IPv4. Set `export TEMPORAL_ADDRESS=<temporal.server_url>` (`config/settings/temporal.yaml`) before step 1.

### 5.2 Steps

1. Set `missions.recurrence.enabled: false` (`config/settings/missions.yaml`) on the running deployment, restart the worker and the API on the old release, then run `python admin.py schedules sync`. Every `mission-schedule-*` Temporal schedule is deleted; the `mission_schedules` rows are unchanged. Confirm with `temporal schedule list | grep -c mission-schedule`, which must print `0`, and again 5 minutes later.
2. Count open executions of the affected types, every 5 minutes for up to 2 hours:
   ```bash
   AFFECTED="ExecutionStatus='Running' AND WorkflowType IN ('MissionRunWorkflow','ChatTurnWorkflow','PlanRefineWorkflow','DesignWorkflowWorkflow','RunWorkflowWorkflow','AgentMissionWorkflow')"
   temporal workflow count --query "$AFFECTED"
   ```
3. Cancel whatever is still running, then wait until the count from step 2 is 0:
   ```bash
   temporal workflow list --query "$AFFECTED" -o json | jq -r '.[].execution.workflowId' | xargs -I{} temporal workflow cancel --workflow-id {}
   ```
   Each cancelled `MissionRunWorkflow` finalises itself as `CANCELLED` through its cancellation handler on the old worker. An execution whose workflow task is already failing (section 5.1) never processes the cancel; terminate it with `temporal workflow terminate --workflow-id <id> --reason "Plan 88 Phase 2 drain"`. The reconciler (Plan 88 step 88.1.10a) then fails its `mission_runs` row as orphaned after `temporal.reconciler.orphan_grace_seconds`. Until then the row is active, so every scheduled tick of that mission is recorded as skipped for overlap.
4. Record `DEPLOY_TIME` (RFC 3339, UTC). Stop the worker and the API, deploy, and start both. Phase 2 has no migration; `python admin.py migrate current` still shows `plan88_003`.
5. On the dev stack, set `missions.recurrence.enabled: true`, restart the worker and the API, and run `python admin.py schedules sync`. Production keeps `missions.recurrence.enabled: false` until Plan 88 Phase 4 is complete (Plan 88 Phase 2 Risk 6).
6. Check that `temporal schedule list` shows every expected `mission-schedule-*` with `Paused` false on the dev stack.

### 5.3 Done When

- The next scheduled tick on the dev stack produces a `MissionRun` that reaches `SUCCEEDED`.
- This count returns 0:
  ```bash
  temporal workflow count --query "WorkflowType='MissionRunWorkflow' AND ExecutionStatus='Running' AND StartTime < '$DEPLOY_TIME'"
  ```

### 5.4 Stored Outcomes Written by Phase 1 Workers

From Plan 88 step 88.2.3b, `TaskResult` rejects a `FAILED` or `TIMEOUT` result that carries no `failure`, so a Phase 1 outcome cannot be validated on Phase 2 code. The drain is what keeps such an outcome away from that validation:

- Phase 2 validates a `TaskResult` only inside `execute_plan_task`, on the result that the same activity attempt has just built (`RunTaskExecutionService.record`). No Phase 1 result reaches it.
- `persist_mission_outcome`, the Phase 1 activity that re-validated a run's whole outcome, was deleted in step 88.2.6. A Phase 1 run left in flight cannot reach it on the new worker: its input fails to decode (observed in the drill below), and any activity task it scheduled fails as an unregistered activity type.
- `execution_records.execution_outcome_json` values written by Phase 1 are read as raw JSON (`get_execution_detail`) and never re-validated.

The residual effect of skipping the drain is therefore a stuck execution, not a corrupt outcome. Steps 3 and 5.3 remove it.

### 5.5 Dev-Stack Drill (2026-11-11)

Run on the dev stack with the `p88-e2e` mission, one hourly schedule (`drain-hourly`, `0 * * * *`) and one manual run started on the Phase 1 API and worker after the Phase 2 code was already checked out.

| Check | Result |
|-------|--------|
| `mission-schedule-*` after step 1 | 1 before, 0 after |
| Affected executions, step 2 | 1 (`MissionRunWorkflow`, run #71), unchanged for 9 minutes |
| Run #71 on the Phase 1 worker | first workflow task failed: `cannot import name 'ExecuteTaskInput'` (section 5.1) |
| Run #71 on the Phase 2 worker | `RuntimeError: Failed decoding arguments` on every attempt |
| `migrate current` after step 4 | `plan88_003 (head)` |
| Schedule after step 1, without a worker restart | recreated at 10:25 and 10:30 by the Phase 1 worker's reconciler sync (section 5.1) |
| Schedule after step 5, without a worker restart | deleted again by the Phase 2 worker, which had cached `false` at its 10:32 start; the 11:00 tick never fired |
| `mission-schedule-*` after step 6, with the worker restarted | 1, not paused |
| 12:00 tick | run #72 `SKIPPED` for overlap: run #71 is still `PENDING` behind a workflow that is running but cannot decode its input; the reconciler leaves it because Temporal reports it running |
