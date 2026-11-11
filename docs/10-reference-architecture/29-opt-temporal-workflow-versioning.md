# 29 - Temporal Workflow Versioning (Optional Module)

*Version: 1.0.0*
*Author: Architecture Team*
*Created: 2026-11-11*

## Changelog

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

Patching is the default for every change. Draining is used only when a change replaces the activity graph wholesale, so that a patch would duplicate the entire workflow body. Plan 88 Phase 2 is the one such change: it ships without patches and uses the drain runbook (Plan 88 step 88.2.10). Every change after Phase 2 uses patches.

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
