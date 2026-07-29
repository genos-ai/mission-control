# Plan 48 — Convergence Loop + Branch Automation + Final Verification

| Field | Value |
|-------|-------|
| **Status** | Stub (not yet scheduled) |
| **Created** | 2026-04-11 |
| **Extracted from** | [Plan 37 — Execution Environments](37-plan-execution-environments.md) §5 Phases 6, 7, 9 |
| **Depends on** | Plan 37 Phases 1–5 (✅ done), Plan 22 (Step-Through Gate, ✅ done), Plan 19 (Quality Agent / PQI, ✅ done) |
| **Out of** | [Plan 46 — Autonomous Mission Roadmap](46-plan-autonomous-mission-roadmap.md) — deliberately out of scope; picked up opportunistically after the roadmap closes, or whenever the convergence loop becomes load-bearing for a specific mission |
| **Target** | `modules/backend/agents/mission_control/dispatch/convergence.py`, `modules/backend/schemas/task_plan.py`, `modules/backend/services/container_backend.py` |

---

## 1  Why this plan exists

During [Plan 46](46-plan-autonomous-mission-roadmap.md) Phase 1 scope review, Plan 37
was found to bundle two logically separable concerns:

1. **The execution environments foundation** — agent isolation via containers. This
   is what Plan 46 §3 DoD item 3 ("tasks run in isolated execution environments")
   actually requires. Plan 37 Phases 1–5 cover it and are done.

2. **Iterative QA cycles + branch/PR automation + fresh-container verification** —
   a different capability that happens to build on the execution environments
   backend. Plan 37 itself notes *"The convergence loop is environment-agnostic —
   it works in `local`, `container`, or (later) `worktree` mode"* — it's not part
   of the isolation layer, it's a higher-level orchestration pattern that could
   just as easily have been its own plan from day one.

To avoid blocking Plan 46 Phase 1 on this second capability (which is multi-week
work), concern #2 has been extracted here. Plan 48 inherits Plan 37 §5 Phases 6,
7, and 9 as its content; Plan 37 retains Phases 1–5 + Phase 8.

This plan is **deliberately out of Plan 46's roadmap scope**. It does not block
autonomous missions — it adds a specific iterative-QA capability on top of them.
It gets picked up when:

- A real mission needs the iterative QA cycle pattern (code-fix missions, quality
  convergence missions), OR
- Plan 46 closes and we have bandwidth to address capability gaps, OR
- A downstream plan (e.g. Plan 39 Guardian Mission, Plan 40 Deep Research) turns
  out to need the convergence primitive specifically.

Until then, missions that need iterative QA either run the cycle manually (user
reviews, re-approves) or use the existing dispatch loop's per-task retry
behaviour.

---

## 2  What this plan contains

The three phases extracted from Plan 37 §5. The content below is a pointer to
the source material in [Plan 37](37-plan-execution-environments.md), not a
duplication — read the Plan 37 sections to get the full design. This file exists
to own the work, not to re-specify it.

### 2.1  Convergence Loop Pattern (was Plan 37 §5 Phase 6)

**Goal:** The plan engine supports iterative QA/fix cycles with configurable
convergence conditions, max iterations, per-cycle audit trails, and gate
integration for human/AI override at cycle boundaries.

**Source:** [Plan 37 §5 Phase 6](37-plan-execution-environments.md#phase-6-convergence-loop-pattern) —
the file `modules/backend/agents/mission_control/dispatch/convergence.py` already
exists on the current branch (~441 lines, not yet wired) and is the starting
point.

**Work units** (copied from Plan 37 §5 Phase 6 so this file is self-contained):

1. Finish wiring `dispatch/convergence.py` into `dispatch/loop.py` — when a task
   type is `convergence_loop`, delegate to `convergence.py` instead of the
   normal `execute_with_step_events` path.
2. Add `convergence_loop` task type to `modules/backend/schemas/task_plan.py`.
3. Add convergence events to `modules/backend/events/types.py`
   (`ConvergenceCycleStartedEvent`, `ConvergenceCycleCompletedEvent`,
   `ConvergenceLoopConvergedEvent`, `ConvergenceLoopAbortedEvent`).
4. Integrate with the existing gate system (`gate.py`): at each
   `"convergence_cycle"` checkpoint, invoke `GateReviewer` — reviewer can
   `CONTINUE` (next cycle), `ABORT` (stop loop), or `MODIFY` (adjust the
   convergence condition). Do NOT create a parallel decision framework.
5. Use PQI service directly for `quality_threshold` convergence conditions
   (`modules/backend/services/pqi/types.py` → `PQIResult.composite_score`).
   Don't reinvent scoring.

**Deliverable:** A plan task of type `convergence_loop` runs an iterative
edit→verify→decide cycle up to a configurable max_iterations, stopping early
when the convergence condition is met. Environment-agnostic.

### 2.2  Branch Strategy + PR Automation (was Plan 37 §5 Phase 7)

**Goal:** Agent branches follow `agent/{mission-id}/{task-type}` convention;
PRs are opened automatically when missions complete; stale branches are pruned.

**Source:** [Plan 37 §5 Phase 7](37-plan-execution-environments.md#phase-7-branch-strategy--pr-automation)

**Work units:**

1. Implement the `agent/{mission-id}/{task-type}` naming convention inside
   `ContainerBackend` git operations (the branch is created when the container
   spins up; this is where the naming gets enforced).
2. Implement the cleanup policy in the existing
   `cleanup_stale_environments` scheduled task (already exists; extend it to
   also prune stale branches matching the `agent/*` prefix beyond a TTL).
3. Implement PR automation — push, open PR via GitHub API, assign reviewer
   from the mission's team config, apply the appropriate label.

**Deliverable:** When a mission completes successfully in container mode, its
agent branch is pushed and a PR is opened against the default branch with the
correct reviewer assignment.

### 2.3  Final Verification Pattern (was Plan 37 §5 Phase 9)

**Goal:** The platform can prove a branch is deployable from zero before any
human sees the PR.

**Source:** [Plan 37 §5 Phase 9](37-plan-execution-environments.md#phase-9-final-verification-pattern)

**Work units:**

1. Implement the "ephemeral per mission + final clean verification" pattern
   inside `convergence.py` (or a sibling module if it grows).
2. After the convergence loop completes, optionally spin up a fresh container,
   check out the agent's branch, bootstrap from zero, and run the full test
   suite.
3. On pass → proceed to PR creation (§2.2). On fail → flag for human review
   via the mission's notification channel (which requires Plan 46 Phase 3
   to be done first for the notification adapter).

**Deliverable:** A "clean room" verification step at the end of every
successful mission that catches "works in the dev container, breaks on a
fresh checkout" regressions before a human ever sees the PR.

### 2.4  What this plan does NOT contain

- **Phase 8 (Worktree Backend)** stays on Plan 37 — its prerequisite is
  "containers are too slow for frequent lightweight tasks", not "we need the
  convergence loop". Different dependency graph, different timing.
- **Plan 16 (Temporal integration)** is a separate production-grade concern
  that could replace the convergence loop's executor wholesale. Plan 48's
  executor maps 1:1 to Temporal activities, so migration is straightforward —
  but that's Plan 16's job, not this plan's.
- **Cross-mission branch management** (long-lived feature branches shared
  across missions) is explicitly out of scope — this plan only covers
  per-mission `agent/*` branches created and destroyed with the container.

---

## 3  Exit criteria (when to mark this plan Done)

Only applies once the plan actually gets scheduled:

1. A plan task of type `convergence_loop` runs to completion against a
   synthetic code-quality mission, with PQI as the convergence condition and
   `max_iterations = 5`.
2. The gate system pauses at the `convergence_cycle` checkpoint and a human
   can `CONTINUE`, `ABORT`, or `MODIFY` from the CLI or UI.
3. A successful mission in container mode automatically pushes its
   `agent/{mission-id}/{task-type}` branch and opens a PR with the correct
   reviewer.
4. The fresh-container final verification runs, passes for a known-good
   branch, and fails cleanly for a branch with a missing dependency.
5. Stale `agent/*` branches older than the configured TTL are pruned by the
   scheduled cleanup task.

---

## 4  References

- [Plan 37 — Execution Environments](37-plan-execution-environments.md) §5
  Phases 6, 7, 9 — source material for this plan
- [Plan 46 — Autonomous Mission Roadmap](46-plan-autonomous-mission-roadmap.md) —
  the coordination document that carved this plan out
- [Plan 22 — Step-Through Gate](../97-plans-archive/22-plan-step-through-gate-[X].md) — gate system
  this plan reuses for convergence cycle decisions
- [Plan 19 — Quality Agent + PQI](19-plan-quality-agent-pqi-codemap.md) — PQI
  scoring used for quality_threshold convergence conditions
- [Plan 16 — Temporal Integration](../97-plans-archive/16-plan-temporal-integration-[X].md) — the
  eventual production path for the convergence executor
