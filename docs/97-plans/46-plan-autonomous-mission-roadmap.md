# Plan 46 — Autonomous Mission Roadmap

| Field | Value |
|-------|-------|
| **Status** | Draft |
| **Created** | 2026-04-11 |
| **Type** | Roadmap / coordination (not a design doc) |
| **Depends on** | Plan 37 (Execution Environments), Plan 41 (Mission Workspace Redesign), Plan 42 (Mission Backlog Model) |
| **Coordinates** | Plan 43 (Persistent Artifacts — TODO candidate), Plan 44 (Plan Tasks Invoke Workflows — TODO candidate), Plan 45 (Rich Workflow Model + Visual Editor — TODO candidate) |
| **Supersedes** | Nothing — rolls up existing plans into a single delivery sequence |
| **Target** | Whole system |

---

## 1  Why this document exists

Across Plans 37/41/42/43/44/45 we now have enough committed + planned work that the
obvious failure mode is **drift** — hopping between plans, shipping half of several
things, never actually closing a plan out, and ending up with a UI that looks good but
where autonomous mode still can't be trusted overnight.

This document is a **roadmap**, not a design doc. It does three things and nothing else:

1. **Sequences** the existing plans + TODO candidates into phases with a clear
   dependency order.
2. **Defines observable exit criteria** per phase so we know when a phase is actually
   done versus feels-done.
3. **Codifies anti-drift rules** so that mid-phase discoveries don't become mid-phase
   pivots.

It deliberately does **not** re-specify any of the feature plans it references.
Plans 37, 43, 44, 45 keep their own design docs (or TODO-candidate entries until they
graduate); this roadmap only tells us which one to pick up next.

### The goal in one sentence

> A human can describe an ambitious goal, walk away for days, and return to trustworthy,
> durable output — without duplicating design work already scoped elsewhere.

### Non-goals

- **Not a design doc.** No new technical decisions, no new schemas, no new APIs.
- **Not comprehensive.** Plans 39 (Guardian Mission) and 40 (Deep Research) are
  specific mission *use cases* that consume this foundation. They're out of scope for
  the roadmap and will land on top of it once it's in place.
- **Not a feature wishlist.** Every item here either closes an existing plan or
  graduates a TODO candidate to its own plan doc. No speculative additions.

---

## 2  Current state snapshot (2026-04-11)

### Done and committed

| Concern | Status | Evidence |
|---|---|---|
| Persistent `mission_plans` + `plan_task_states` backend | ✅ Landed | Plan 42 §3–8, migration `plan42_001` |
| Planning Agent refinement mode (Path A from §10.4) | ✅ Landed | `services/mission_plan.py::refine`, `agents/system/planning/*` refinement branch |
| Transitive approve/reject, clean-slate reconciliation | ✅ Landed | `services/mission_plan.py::approve_task`, `reject_task`, `_reconcile_task_states` |
| `handle_mission(precomputed_plan=...)` contract + batch write-back | ✅ Landed | Plan 42 §10.1, §10.5 |
| `MissionPlanDaemon` (feature-flagged, per-plan Redis lock) | ✅ Landed | `services/mission_plan_daemon.py` |
| Director tools: `get_plan` / `refine_plan` / `approve_plan_tasks` | ✅ Landed | `agents/mission/director/agent.py` |
| `MissionPlan.*` SSE events + frontend SSE invalidation | ✅ Landed | `events/types.py`, `workspace.tsx` mission_plan handler |
| Workspace 3-panel layout + feed mode toggle | ✅ Landed | Plan 41 §3, `pages/mission/workspace.tsx` |
| Horizontal 4-column kanban restored on Plan 42 backend | ✅ Landed | commit `00a38e2`, `components/workspace/plan-board.tsx` |
| SSE wire format unified with history endpoint | ✅ Landed | commit `0dceeeb`, `services/console.py::format_event_for_sse` |
| Plan 45 Phase 1 placeholder (Workflows feed mode list view) | ✅ Landed | commit `39507f4`, `components/workspace/workflows-panel.tsx` |

### In flight

| Concern | Where | Notes |
|---|---|---|
| Plan 37 — Execution Environments | Current branch `plan/37-execution-environments` | Sandbox/container isolation so autonomous runs can write code without trashing the repo. Prerequisite for trusting overnight runs. |

### Outstanding — graduated to plan docs

| Plan | Status |
|---|---|
| Plan 41 — Mission Workspace Redesign | Partially shipped. Kanban polish items (§3.5a drag-to-reorder, §3.5a animations, §3.5b pre-run gate, §3.5a right-click menu, "+ Add task") still outstanding. Phase 4 below closes this. |
| Plan 42 — Mission Backlog Model | Backend fully shipped. Frontend kanban restored. Fully closes at the end of Phase 6 once multi-day unattended runs have been verified. |

### Outstanding — TODO candidates (not yet plan docs)

| Candidate | Where | Graduates to a plan in |
|---|---|---|
| Plan 43 — Persistent Mission Artifacts | `TODO.md` entry | Phase 2 |
| Plan 44 — Plan Tasks Invoke Workflows | `TODO.md` entry | Phase 5 |
| Plan 45 — Rich Workflow Model + Visual Editor | `TODO.md` entry | Phase 5 |

---

## 3  Definition of done (whole roadmap)

The roadmap is complete when **all** of the following are observably true:

1. A mission can be kicked off with a multi-day goal and left unattended.
2. The backend can crash and restart mid-run without corrupting plan or task state.
3. Tasks run in isolated execution environments (Plan 37).
4. Every run produces artifacts that survive page refresh, session end, and backend
   restart (Plan 43).
5. Per-task cost and duration are tracked in `plan_task_states` and visible on the
   kanban.
6. A returning user can see exactly what happened overnight via the Run History drawer
   and the persisted Narrative feed.
7. The user receives a channel notification (Telegram or equivalent) when a mission
   needs attention: completed, failed, awaiting human input, approaching budget,
   budget exhausted.
8. A plan can pause and resume across days — both via the UI button and via a
   `HumanInputNode` in a workflow.
9. A plan task can be a workflow invocation (Plan 44), and that workflow can contain
   deterministic tool calls, conditions, and human-input pauses (Plan 45).
10. The kanban matches the Plan 41 §3.5a spec visually: animations between columns,
    drag-to-reorder in Proposed, right-click menu, pre-run review gate, "+ Add task"
    prompt, color-coded agent badges.
11. At least one real 7+ day unattended mission has been run to completion, with
    multiple pause/resume cycles and at least one crash recovery.

If any of these is not observably true, the roadmap is not done.

---

## 4  Phases

Each phase below has:
- **Goal** — one sentence that describes the phase outcome
- **Work units** — concrete items, each linked to an existing plan or TODO entry
- **Exit criteria** — observable conditions that must all be true before the next
  phase can start
- **Explicitly not in this phase** — scope cuts to resist the "while we're here" tax

### Phase 1 — Trust (make the plumbing safe)

**Goal:** A daemon-dispatched run can crash, restart, and leave plan state sane; tasks
that write code do so in isolation.

**Work units:**
1. **Finish Plan 37 Phases 1–5 end-to-end.** Land and verify the sandbox/container
   isolation layer. Plan 37 documents nine phases internally, but on inspection the
   phases split cleanly:

   - **Phases 1–5** (*agent rename + invocation tiers / platform missions / execution
     environment model / container backend / dispatch integration*) are the
     "isolation foundation" — this is what §3 DoD item 3 ("tasks run in isolated
     execution environments") actually needs. All five are already landed on the
     current branch; this work unit is **verification** not fresh implementation.
   - **Phases 6, 7, 9** (*convergence loop / branch + PR automation / final
     verification pattern*) are logically separable capabilities that happen to
     share Plan 37's plan number. Plan 37 itself says the convergence loop is
     *"environment-agnostic — it works in local, container, or (later) worktree
     mode"* — it's a different feature riding on Plan 37's backend. These three
     phases are **extracted** into Plan 48 and deferred past Phase 1 of this
     roadmap so we can actually close Phase 1 in a focused session.
   - **Phase 8** (*worktree backend optimization*) stays deferred per Plan 37 §5
     ("only implement when agents run frequent lightweight tasks and the 5–30s
     container overhead becomes a measurable bottleneck") — not extracted, just
     parked.

   What this work unit actually involves:

   a. Run a real mission end-to-end in container mode: plan → approve → dispatch →
      container provisions → agent runs → branch state is isolated from the host
      repo → container persists for the next run → cleanup works.
   b. Fix any regressions surfaced by the end-to-end test.
   c. Update Plan 37's header with a close-out note pointing at Plan 48 for the
      extracted phases.
   d. Create `docs/97-plans/48-plan-convergence-loop-and-branch-automation.md` as
      the home for the extracted phases (seeded from Plan 37 §5 Phases 6/7/9).
2. **Daemon crash recovery.** On backend boot, reconcile any `plan_task_states` still
   in `running` or `queued` older than a threshold: mark them `failed` with
   `failure_reason = "backend restart — run orphaned"`, clear `task_execution_id`, and
   increment `retry_count` so the user can re-approve manually. One small service
   function called from the FastAPI startup event; not its own plan doc.
3. **Daemon liveness + observability.** `MissionPlanDaemon.start_daemon` publishes a
   heartbeat to Redis every N seconds. `GET /admin/daemon/status` returns the last
   heartbeat timestamp for each daemon. Not its own plan doc; fits inside the daemon
   service.
4. **Budget enforcement stress test.** Run the daemon against a synthetic plan with a
   low `budget_usd_ceiling`, verify the pre-batch cap from Plan 42 §10.7 actually
   refuses to dispatch when headroom is thin, and fix any gap discovered. Document
   the test script so it can be re-run after future changes.

**Exit criteria (all must be observably true):**
- Plan 37 Phases 1–5 verified end-to-end: a real mission dispatches through a
  container, the agent runs inside the container, branch state is isolated from
  the host repo, the container persists across executions within the mission, and
  cleanup works.
- Plan 37 is marked "Phases 1–5 done" in its header with a pointer to Plan 48 for
  the extracted phases; Plan 48 exists as a stub with Phases 6/7/9 described.
- Backend restart during a running plan task transitions that task to `failed` with
  `failure_reason = "backend restart — run orphaned"` and surfaces it on the kanban.
- `GET /admin/daemon/status` returns a heartbeat timestamp less than 30 seconds old
  while the daemon is enabled.
- Daemon refuses to dispatch a batch when `(budget_usd_ceiling - total_spent_usd) <
  per_searcher_cost_ceiling × batch_size` and logs the refusal with a clear message.
- The SSE wire format fix from commit `0dceeeb` has been validated against every
  `mission_plan.*` event type (no silent drops).

**Explicitly not in this phase:**
- No artifact persistence (Phase 2).
- No channel notifications (Phase 3).
- No kanban polish (Phase 4).
- No workflow rewrites (Phase 5).

---

### Phase 2 — Durable output

**Goal:** A returning user can see exactly what happened overnight — every run's
artifacts, costs, durations, and narrative survive page refresh and backend restart.

**Work units:**
1. **Graduate Plan 43 from TODO to plan doc.** Write
   `docs/97-plans/43-plan-persistent-mission-artifacts.md` using the existing TODO.md
   entry as the seed. Schema: `mission_artifacts` table linked to
   `mission_id`/`execution_record_id`/`task_execution_id`, typed variants
   (`report`/`finding`/`code`/`data`/`file`), extraction in
   `persistence_bridge.persist_mission_results` instead of ephemeral SSE,
   `GET /missions/:id/artifacts` API. Implement it.
2. **Per-task cost + duration columns.** Add `cost_usd` and `duration_seconds` to
   `plan_task_states`. Wire `_write_back_task_results` to populate them from the run
   outcome. Surface on Done cards in the kanban (already sketched in the plan-board
   rewrite commit as a deferred item).
3. **Run History drawer.** Finish `components/workspace/run-history-drawer.tsx`
   (currently uncommitted). Reads `GET /missions/:id/runs` + joins artifacts + task
   state per run. This is the **primary returning-user surface**; treat it with the
   same care the kanban got.
4. **Narrative feed reconciliation.** Resolve the TODO.md "Narrative feed / menu item"
   item — reconcile Plan 41 §3–4 spec (tool rows grouped/indented under narrative
   rows, tiered transparency) against the current `console.tsx`/`workspace.tsx`
   implementation. Either finish the missing spec pieces or rename/merge the mode.
   Outcome: one short decision note committed to Plan 41 closing that ambiguity.

**Exit criteria:**
- `GET /missions/:id/artifacts` returns persistent artifacts from a run completed the
  previous day after a backend restart.
- Done cards on the kanban show `$X.XX · Ns` from `plan_task_states` columns, not
  from ephemeral SSE.
- Run History drawer shows the last N runs with status, cost, duration, task count,
  and artifact links, and clicking a run opens its detail view.
- Narrative feed decision note is committed to Plan 41 and the drift item is closed
  out of TODO.md.
- Plan 43 is marked "Done" in its own header.

**Explicitly not in this phase:**
- No channel notifications (Phase 3).
- No layout animations or drag-to-reorder (Phase 4).
- No workflow rewrites (Phase 5).
- No file-artifact storage decisions beyond the minimum Plan 43 needs — blob vs
  filesystem vs object store can defer if the current use case only needs text
  artifacts.

---

### Phase 3 — Signaling

**Goal:** The user gets a channel notification when a mission needs their attention
and never has to poll the UI to know whether something happened.

**Work units:**
1. **Wire Telegram adapter to `mission_plan.*` events.** Subscribe to the mission
   event channel, map events to notification types:
   - `mission_plan.dispatched` → "Mission <name> started run with N tasks"
   - Run complete (via dispatch result) → "Mission <name> finished: M succeeded,
     K failed. Cost $X.XX"
   - `mission_plan.task.status_changed` where `to_status = failed` and
     `gate_mode = autonomous` → "Mission <name> task <task_id> failed after N
     retries: <reason>"
   - Budget approaching (80% via a new derived event) → "Mission <name> at 80%
     budget — $X.XX of $Y.YY"
   - Budget exhausted → "Mission <name> budget exhausted, daemon paused"
2. **Per-user channel configuration.** A small `users.notification_channels` JSON
   column or dedicated table for "which channel to send to, with which filter". Not
   a whole plan — a small migration + settings UI card.
3. **Notification read-state** so re-opening the UI clears the badge. Out-of-band
   signal separate from SSE.

**Exit criteria:**
- User receives a Telegram message within 10 seconds of a mission run completing in
  the daemon.
- User receives a Telegram message when a task fails in autonomous mode, with enough
  context to decide whether to re-approve.
- Budget warning fires exactly once per plan at 80% and again at 100%, never on
  intermediate updates.
- Disabling notifications per-user actually stops deliveries without restarting the
  backend.

**Explicitly not in this phase:**
- No Slack/Discord/email adapters — Telegram only. More adapters are a follow-up
  plan.
- No in-mission pause-on-notification-reply (that's `HumanInputNode` in Phase 5).
- No notification-history UI beyond read-state.

---

### Phase 4 — Kanban UX polish (close out Plan 41)

**Goal:** The kanban matches Plan 41 §3.5a visually; Plan 41 can be marked Done.

**Work units:**
1. **Layout animations between columns.** Add `framer-motion` to the frontend
   package. Wrap cards in `<motion.div layout>` so transitions between Proposed →
   Approved → Running → Done slide smoothly.
2. **Drag-to-reorder in Proposed column.** Add `@dnd-kit/core`. Wire a drag handler
   that calls a new `PATCH /plan/tasks/:id/reorder` endpoint (order is a new
   integer column on `plan_task_states`, or a JSON field on `mission_plans`).
3. **Right-click card menu.** Edit / Reassign / Cancel. Edit opens an inline editor;
   Reassign is a dropdown of available agents from the mission team; Cancel calls
   the existing reject endpoint.
4. **"+ Add task" prompt** at the bottom of the Proposed column. Single-line input +
   agent dropdown; on submit, sends a refinement instruction to the Director
   ("insert a task: ..."), same path as Plan 41 §3.5a describes.
5. **Pre-run review gate (Plan 41 §3.5b).** Non-blocking overlay on the first
   dispatch of the session, skippable with "don't ask again for this mission"
   persisted per-mission.
6. **Color-coded agent badges by domain.** Add `ui_color` column to `agent_catalog`;
   surface via existing team data. Health=sky, arch=violet, quality=amber, etc.
7. **Richer Running card.** Progress bar (tools done / expected), result preview
   line under the current tool name. Consumes the existing `agentStatuses` slice,
   no new backend data.

**Exit criteria:**
- Every visual element specified in Plan 41 §3.5a is implemented (checked off in the
  Plan 41 doc).
- Cards animate between columns without jank.
- User can drag a proposed task above/below another proposed task and the order
  persists across refresh.
- Pre-run review gate appears on first dispatch of a session and respects the "don't
  ask again" preference.
- Plan 41 is marked "Done" in its header with a dated close-out note.

**Explicitly not in this phase:**
- No workflow editor (Phase 5).
- No new agent capabilities.
- No overview or runs page changes beyond what the Run History drawer needed in
  Phase 2.

---

### Phase 5 — Deterministic workflows (Plans 45 + 44)

**Goal:** A mission plan task can be a workflow invocation, and that workflow can
contain deterministic tool calls, conditions, notifications, and human-input pauses
that actually pause the run for days.

**Work units:**
1. **Graduate Plan 45 from TODO to plan doc.** Write
   `docs/97-plans/45-plan-rich-workflow-model.md` using the existing TODO entry.
   Three layers: node schema (discriminated union — `AgentStepNode`, `ToolCallNode`,
   `LlmCallNode`, `ConditionNode`, `HumanInputNode`, `NotificationNode`,
   `BranchNode`/`MergeNode`, `SubWorkflowNode`), executor (rewrite of
   `WorkflowRunService` as a node-type dispatcher), visual editor (React Flow,
   replacing the current placeholder in `workflows-panel.tsx`).
2. **Plan 45 Phase 1 + 2** — node schema, variable binding language, executor.
3. **Plan 45 Phase 3** — `HumanInputNode` + channel gateway integration. Reuses
   the Telegram adapter from Phase 3 of this roadmap.
4. **Plan 45 Phase 4** — React Flow visual editor replacing the placeholder.
5. **Plan 45 Phase 5** — `SubWorkflowNode` for composition.
6. **Graduate Plan 44 from TODO to plan doc.** Write
   `docs/97-plans/44-plan-plan-tasks-invoke-workflows.md`. Discriminated
   `TaskDefinition.task_type: Literal["agent", "workflow"]`, dispatch loop branch,
   `plan_task_states.workflow_run_id` column, state mapping, budget reconciliation,
   refinement preservation policy, PlanBoard UI treatment.
7. **Implement Plan 44.** Depends on Plan 45 Phase 1 shipping the node schema.

**Exit criteria:**
- A workflow can be authored via the React Flow editor and saved.
- A plan task with `task_type: "workflow"` dispatches the saved workflow via the
  executor (not via `handle_mission(step.brief)`).
- A workflow containing a `HumanInputNode` pauses the run, sends a Telegram message,
  waits for the reply, and resumes — verified end-to-end on a real multi-day mission.
- `plan.total_spent_usd` reconciles correctly when a workflow task finishes.
- Plan 44 and Plan 45 are both marked "Done" in their headers.

**Explicitly not in this phase:**
- No tool catalog overhaul beyond what Plan 45 §1 needs.
- No Temporal migration (Plan 16) — the executor shape maps to Temporal activities
  1:1 but that's a follow-up.
- No agent-side changes to the Planning Agent prompt beyond what Plan 44 needs.

---

### Phase 6 — Endurance (verify the foundation under real load)

**Goal:** A real 7+ day unattended mission runs to completion, surviving restarts,
pauses, retries, budget policy, and channel interactions. This is the acceptance
test for the whole roadmap.

**Work units:**
1. **Context hardening for multi-day runs.** Stress-test the existing context curator
   against a mission with 1000+ events and multi-day history. Tune summarization
   thresholds, eviction policy, and compression as needed.
2. **Retry / escalation policy.** Per-task policy (default + override): retry N times
   with exponential backoff → escalate from `autonomous` to `ai_assisted` → escalate
   to human via Telegram. Wire into `retry_handler` + the daemon.
3. **Pause/resume on the plan.** One-click "pause until I get back" button on the
   Plan tab top bar. Flips `mission_plans.status` to `paused`; daemon respects it.
   Resume button flips back to `active`.
4. **Real long-running mission.** Pick a mission that would realistically take ~1
   week (e.g. the `pi-only long-running mission experiment` from TODO.md, or a
   similar concrete goal). Configure autonomous mode with a realistic budget.
   Observe.
5. **Post-mortem and close-out.** After the mission finishes (or fails interestingly),
   write a short retrospective: what broke, what surprised us, which roadmap phase's
   assumptions proved wrong, what to change. File issues for anything that broke.

**Exit criteria:**
- One real mission runs for ≥7 days in autonomous mode with at least one
  pause/resume cycle, at least one backend restart during its lifetime, and at least
  one Telegram notification delivered and acted on.
- Budget enforcement kept the mission inside its ceiling.
- Artifacts from day 1 are still retrievable on day 7.
- Plan 42 is marked "Done" in its header with a dated close-out note citing the
  real-mission verification.
- This roadmap (Plan 46) is marked "Done" with the same citation.

**Explicitly not in this phase:**
- No new features. If something breaks during the real mission, the fix goes into
  this phase; net-new capability goes into a new plan numbered 47+.

---

## 5  Anti-drift rules

These are the rules that keep the roadmap from becoming a wishlist we never finish.

1. **One phase in flight at a time.** No work starts on Phase N+1 until Phase N's
   exit criteria are all checked off in §4 above. If you catch yourself opening a
   file that belongs to a later phase, close it.

2. **No new plans get written until the current phase's exit criteria are met.** New
   ideas go to `TODO.md` as candidates. They only graduate to a `docs/97-plans/NN-*.md`
   plan doc when the current phase's exit criteria are met or when the current phase
   explicitly schedules them (e.g. Phase 2 graduates Plan 43).

3. **Exit criteria must be observable, not subjective.** "The kanban feels good" is
   not an exit criterion. "Every visual element in Plan 41 §3.5a is implemented" is.
   If you can't write the criterion as something an outside observer could verify,
   you don't yet know what you're building.

4. **Phase scope cuts are explicit and binding.** Each phase's "Explicitly not in
   this phase" list is the no-fly zone. If a piece of work is genuinely load-bearing
   for the current phase's exit criteria, it is in scope; otherwise, it goes on the
   deferred list below.

5. **TODO.md candidates surfaced mid-phase are deferred**, not acted on. Write them
   down, keep moving.

6. **Every committed change cites the phase it belongs to.** Commit message footer:
   `Phase N — <short description>` so `git log --grep "Phase 2"` can recover the
   full phase's history.

7. **At the start of every session, re-read this document.** The first five minutes
   should answer "which phase are we in, what's next in it, and is the work I'm
   about to do in that phase?" If the answer is "no", stop and talk about it before
   starting.

8. **If the answer to an exit criterion is "almost", the criterion is not met.** Do
   not move to the next phase with a partial check.

### Deferred-from-phase tracker

When a TODO.md candidate surfaces mid-phase, add it here with the phase it was
deferred from:

- _(none yet)_

---

## 6  Plan close-out tracker

Which plan docs get marked "Done" at the end of which phase:

| Plan | Closes at | Notes |
|---|---|---|
| Plan 37 — Execution Environments (Phases 1–5 only) | Phase 1 | Current branch. Phases 6/7/9 carved into Plan 48. Phase 8 (worktree) deferred per Plan 37 §5. |
| Plan 48 — Convergence Loop + Branch Automation | _out of roadmap_ | Stub created in Phase 1, implemented opportunistically after the roadmap or whenever the convergence loop becomes load-bearing for a specific mission. |
| Plan 43 — Persistent Artifacts | Phase 2 | Graduated from TODO candidate during Phase 2. |
| Plan 41 — Mission Workspace Redesign | Phase 4 | Kanban polish items close out the §3.5a spec. |
| Plan 45 — Rich Workflow Model | Phase 5 | Graduated from TODO candidate during Phase 5. |
| Plan 44 — Plan Tasks Invoke Workflows | Phase 5 | Graduated from TODO candidate during Phase 5, depends on Plan 45. |
| Plan 42 — Mission Backlog Model | Phase 6 | Backend + frontend already shipped; closes formally once a real 7+ day mission verifies it in anger. |
| Plan 46 — this roadmap | Phase 6 | Closes with the roadmap retrospective. |

No plan closes before its listed phase. If we find ourselves wanting to mark something
done early, that's a signal that our exit criteria were too loose; tighten them, don't
lower the bar.

---

## 7  Plans deliberately out of scope

These exist and are referenced from other plans but are *not* blocked by or blocking
the roadmap:

- **Plan 39 — Guardian Mission.** A specific mission use case that will run on top of
  this foundation. Land the roadmap first, then build Guardian on top.
- **Plan 40 — Deep Research System.** Same — a specific research-loop use case that
  consumes the workflow engine (Plan 45). Build on top of the roadmap, not inside it.
- **Plan 16 — Temporal Integration.** The obvious production path for the workflow
  executor once Plan 45 stabilizes. Deliberately deferred until after the roadmap.
- **Code review P1–P12** (in TODO.md — service↔agent import cycle, oversized files,
  hardcoded budgets, thin-client violations, etc). Quality debt, not roadmap work.
  Address opportunistically inside each phase where the relevant file is touched,
  but don't let it block a phase.

---

## 8  References

### Plan docs this roadmap coordinates

- [Plan 37 — Execution Environments](37-plan-execution-environments.md) (Phases 1–5 only)
- [Plan 41 — Mission Workspace Redesign](41-plan-mission-workspace-redesign.md)
- [Plan 42 — Mission Backlog Model](42-plan-mission-backlog-model.md)
- [Plan 48 — Convergence Loop + Branch Automation](48-plan-convergence-loop-and-branch-automation.md) — extracted from Plan 37 Phases 6/7/9, out of roadmap scope

### TODO candidates that graduate inside the roadmap

- `TODO.md` — Persistent mission artifacts (Plan 43 candidate) — Phase 2
- `TODO.md` — Plan tasks that invoke workflows (Plan 44 candidate) — Phase 5
- `TODO.md` — Rich workflow model + visual editor (Plan 45 candidate) — Phase 5

### Related but out of scope

- [Plan 39 — Guardian Mission](39-plan-guardian-mission.md)
- [Plan 40 — Deep Research System](40-plan-deep-research-system.md)
- [Plan 16 — Temporal Integration](16-plan-temporal-integration-[X].md)

### Commits cited as current state

- `00a38e2` — Plan 42 Plan tab: restore Plan 41 horizontal 4-column kanban
- `0dceeeb` — fix: SSE wire format mismatch — wrap events to match history endpoint
- `39507f4` — Plan 45 Phase 1 placeholder: Workflows feed mode
