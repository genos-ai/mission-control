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
7. When a run wave completes, the mission automatically routes to its next state —
   advancing approved tasks, refining the plan for a new wave, proposing completion,
   or escalating to the user — and Director chat updates surface the decision in
   the Chat tab without user action. See [Plan 51](51-plan-autonomy-loop-supervisor.md).
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

**Status:** ✅ **Complete (2026-04-11).** All four work units done, all exit criteria observably met. Phase 2 (durable output) is unblocked.

**Goal:** A daemon-dispatched run can crash, restart, and leave plan state sane; tasks
that write code do so in isolation.

**Work units:**
1. **✅ DONE (2026-04-11) — Finish Plan 37 Phases 1–5 end-to-end.** Land and verify
   the sandbox/container isolation layer. Plan 37 documents nine phases internally,
   but on inspection the phases split cleanly:

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

   What this work unit actually involved:

   a. Run a real mission end-to-end in container mode: plan → approve → dispatch →
      container provisions → agent runs → branch state is isolated from the host
      repo → container persists for the next run → cleanup works.
   b. Fix any regressions surfaced by the end-to-end test.
   c. Update Plan 37's header with a close-out note pointing at Plan 48 for the
      extracted phases.
   d. Create `docs/97-plans/48-plan-convergence-loop-and-branch-automation.md` as
      the home for the extracted phases (seeded from Plan 37 §5 Phases 6/7/9).

   **What actually happened (2026-04-11):** The scrutiny of Plan 37's shipped code
   surfaced a gap that was not anticipated when Phase 1 was originally scoped — the
   execution environments infrastructure was complete, but no agent was actually
   *using* it. Containers were provisioned, sat idle, and were cleaned up; every
   byte of agent work still happened on the host filesystem via host tools. This
   turned out to be the single biggest threat to the roadmap's whole purpose, and
   was surfaced as a critical blocker that graduated into its own plan —
   [Plan 47 — Agent Execution Isolation](47-plan-agent-execution-isolation.md).
   Plan 47 landed host-side git worktree + bind-mount isolation, a tier-guarded
   `project_root` redirect in the agent executor, and a repeatable verification
   script at [scripts/verify_isolation.py](../../scripts/verify_isolation.py) that
   now reports 14/14 checks passing against real Docker. With Plan 47 Done, this
   work unit is complete in fact (not just on paper) — §3 DoD item 3 ("tasks run
   in isolated execution environments") is observably satisfied for user-tier
   agents, and platform-tier agents continue to run unchanged. Plan 48 remains
   unopened as designed.
2. **✅ DONE (2026-04-11) — Daemon crash recovery.** On backend boot, reconcile any
   `plan_task_states` still in `running` or `queued`: mark `running → failed` with
   `failure_reason = "backend restart — run orphaned"`, mark `queued → approved`
   (safe to re-dispatch since queued means dispatched but never started). Landed in
   `services/mission_plan_crash_recovery.py` with a new
   `list_in_flight_task_states()` method on `MissionPlanRepository` and a startup
   hook in `main.py` lifespan that runs unconditionally before the daemon starts.
   Verified by `scripts/verify_crash_recovery.py` — 10/10 checks pass against the
   real DB (pre/post state, transitions, control rows untouched, idempotency).
3. **✅ DONE (2026-04-11) — Daemon liveness + observability.** The daemon publishes
   a JSON heartbeat to Redis (`mission_plan_daemon:heartbeat` key, 20-second TTL)
   after every tick with timestamp, tick_count, poll_interval_sec, and last_error.
   `GET /api/v1/admin/daemon/status` reads the heartbeat back and returns
   `enabled / alive / last_heartbeat_at / age_sec / tick_count / last_error / poll_interval_sec`.
   `alive = age < 30s` — matches the exit-criterion threshold. Verified by
   `scripts/verify_daemon_heartbeat.py` — 4/4 checks pass (heartbeat publishing,
   tick advancement, freshness under 30s, positive TTL on the key).
4. **✅ DONE (2026-04-11) — Budget enforcement stress test.** Plan 42 §10.7's
   defensive check in `MissionPlanService.dispatch_approved` (raises ValidationError
   when `budget_usd_ceiling - total_spent_usd <= 0`) was already in place. Stress
   testing surfaced one gap: the daemon kept retrying exhausted plans every poll
   cycle, producing stack-trace log noise. Fixed by adding a SQL-level budget filter
   to `MissionPlanDaemon._find_ready_plan_ids` so exhausted plans are excluded at
   query time. Service-layer check stays as the fail-safe. Verified by
   `scripts/verify_budget_enforcement.py` — 8/8 checks pass covering both layers
   and all four scenarios (healthy / at-ceiling / overshot / NULL ceiling).

**Exit criteria (all observably true as of 2026-04-11):**
- ✅ Plan 37 Phases 1–5 verified end-to-end: 14/14 checks in
  `scripts/verify_isolation.py`. User-tier agents execute in isolated host-side
  worktrees bind-mounted into per-mission containers; platform-tier agents
  unchanged; cleanup removes both.
- ✅ Plan 37 header marked "Phases 1–5 done" with a pointer to Plan 48; Plan 48
  stub exists at `docs/97-plans/48-plan-convergence-loop-and-branch-automation.md`.
- ✅ Backend restart reconciler: `services/mission_plan_crash_recovery.py` ships
  the transition logic, `main.py` lifespan calls it before the daemon starts,
  `scripts/verify_crash_recovery.py` verifies 10/10 against the real DB.
- ✅ `GET /api/v1/admin/daemon/status` returns a heartbeat younger than 30s when
  the daemon is enabled. Verified by `scripts/verify_daemon_heartbeat.py` (4/4).
- ✅ Daemon query filter in `MissionPlanDaemon._find_ready_plan_ids` excludes
  exhausted plans; service-layer ValidationError in `dispatch_approved` fires
  the refusal with a clear "Plan budget exhausted" message. Verified by
  `scripts/verify_budget_enforcement.py` (8/8).
- ✅ SSE wire format fix from commit `0dceeeb` validated — every
  `mission_plan.*` event flows through `format_event_for_sse` with a `data`
  wrapper matching the history endpoint shape. Plan board no longer drops
  events silently.

**Explicitly not in this phase:**
- No artifact persistence (Phase 2).
- No channel notifications (Phase 3).
- No kanban polish (Phase 4).
- No workflow rewrites (Phase 5).

---

### Phase 2 — Durable output

**Status:** ✅ **Complete (2026-04-11).** All four work units done, all exit criteria observably met. Phase 3 (signaling) is unblocked.

**Goal:** A returning user can see exactly what happened overnight — every run's
artifacts, costs, durations, and narrative survive page refresh and backend restart.

**Work units:**
1. **✅ DONE (2026-04-11) — Graduate Plan 43 from TODO to plan doc + implement.**
   Plan doc landed at [docs/97-plans/43-plan-persistent-mission-artifacts.md](43-plan-persistent-mission-artifacts.md).
   `mission_artifacts` table created via migration `plan43_001`, linked via
   mission_id (CASCADE) + execution_record_id / task_execution_id (SET NULL) so
   artifacts survive run archival. Typed variants ready (`report`/`finding`/`code`/
   `data`/`file`) with `report` the only one emitted today. Extraction wired in
   `persist_mission_results` — same `summary`/`result` heuristic the live SSE
   emission site uses, now persisted instead of ephemeral. New `GET /api/v1/missions/
   {id}/artifacts` endpoint returns newest-first with limit/type filters. Frontend
   `ArtifactsPanel` rewritten to use a react-query hook; SSE `mission.artifact.found`
   invalidates the query for live refresh; Zustand `artifacts` slice deleted. Verified
   via `scripts/verify_artifacts_persistence.py` — 7/7 checks pass against real DB
   including full FK-chain extraction test. Commits: `2e21874` (design doc),
   `c42ae8c` (backend A–D + verification F), `73d5859` (frontend E). Plan 43 marked
   Done in its own header.
2. **✅ DONE (2026-04-11) — Per-task cost + duration columns.** Migration
   `phase2_metrics` adds `cost_usd` + `duration_seconds` (both Float NOT NULL default
   0.0) to `plan_task_states`. `MissionPlanService._write_back_task_results`
   denormalises from `task_result.cost_usd` / `task_result.duration_seconds` at run
   completion. Plan board Done cards render `$X.XX · Ns` in the meta line, hidden
   for pre-run/running states to avoid `"$0.0000 · 0.0s"` noise. **Pre-existing FK
   bug caught and fixed during verification:** `TaskResult.execution_id` defaults to
   empty string `""`, and the write-back was passing `""` straight into the
   `task_execution_id` FK column, violating `plan_task_states_task_execution_id_fkey`.
   Normalised empty string → None in the write-back path. Verified end-to-end via a
   direct service-level test. Commits: `eeccab7` (migration + model), `b962663`
   (write-back + FK fix + schema + frontend types + plan-board rendering, bundled
   with parallel session's Phase 4 kanban polish work).
3. **✅ DONE (2026-04-11) — Run History view.** Exit criterion originally framed as
   a "drawer" — reconciled to the tab-based reality after Plan 49 consolidation: the
   Runs tab (`/missions/:id/runs`) is the primary returning-user surface, with
   `RunsPanel` showing the list and `RunDetailPanel` providing inline click-to-reveal
   detail. Phase 2 additions: backend `list_executions` query now eager-loads
   `task_executions` via `selectinload`, and `ExecutionRecordResponse` carries a new
   `task_count` field populated in the endpoint from the eager-loaded relationship.
   Frontend `HistoryRow` grew a metrics sub-line under the session ID showing
   `N tasks · Xs · K artifacts`, each part hidden when zero so a live run with no
   output yet renders cleanly. `RunsPanel` loads the mission-wide artifact list via
   `useMissionArtifacts` once and groups by `execution_record_id` client-side; each
   row's artifacts flow down to `HistoryDetail` for per-run artifact rendering (title
   + type badge + count overflow pill). Typecheck + lint + build clean. Commits for
   this work unit bundled with the Plan 43 artifact chain and the concurrent kanban
   polish session.
4. **✅ DONE (2026-04-11) — Narrative feed reconciliation.** Decision: **keep
   Narrative and Stream as separate tabs, accept the current v1 as satisfying Phase
   2, defer the remaining Plan 41 §3–4 polish (nested tool rows, tiered transparency
   slider) to Phase 4 which is the phase that closes Plan 41.** Investigation
   confirmed all intended `mission.narrative` event types are wired through
   `step_executor.py` and rendered by `tabs/narrative-tab.tsx` (narrative headlines +
   artifacts + tool calls + thinking + plan steps + run lifecycle). The divergence
   from the full spec is documented in the `TODO.md` entry which is now marked `[x]`
   with the full reconciliation note. Plan 40 §7's platform-primitive contract
   (`ResearchNarrativeEvent` → `MissionNarrativeEvent`) landed in commit `c575f95`.
   No code changes for this work unit — decision-note only.

**Exit criteria (all observably true as of 2026-04-11):**
- ✅ `GET /api/v1/missions/:id/artifacts` returns persistent artifacts across backend
  restarts. Verified by `scripts/verify_artifacts_persistence.py` (7/7 checks, full
  FK-chain extraction including post-persist read-back).
- ✅ Plan board Done cards render `$X.XX · Ns` from the new `plan_task_states.
  cost_usd` / `duration_seconds` columns, denormalised at run completion by
  `MissionPlanService._write_back_task_results`. Ephemeral-SSE path for the metrics
  is gone.
- ✅ Runs tab shows last N runs with status, cost, duration, task count, and
  artifact links. Each row's metrics sub-line (`N tasks · Xs · K artifacts`) is
  visible without expanding, and the expanded detail adds per-task breakdown +
  per-run artifact cards. Clicking the chevron opens the detail view in place; the
  side `RunDetailPanel` takes over for Events / Output / Cost drill-ins. ("Drawer"
  wording in the original exit criterion was written before Plan 49 consolidation
  landed the tab-based shell — the practical reality is the Runs tab + inline
  detail, which satisfies the UX intent.)
- ✅ Narrative feed reconciliation decision committed in `TODO.md` as a marked-done
  entry: Narrative and Stream stay as separate tabs; Plan 41 §3–4 nested tool rows +
  tiered transparency slider are deferred to Phase 4 (the phase that closes Plan 41).
- ✅ Plan 43 is marked "Done" in its own header (commits `2e21874` / `c42ae8c` /
  `73d5859` / `b498234`).

**Explicitly not in this phase:**
- No channel notifications (Phase 3).
- No layout animations or drag-to-reorder (Phase 4).
- No workflow rewrites (Phase 5).
- No file-artifact storage decisions beyond the minimum Plan 43 needs — blob vs
  filesystem vs object store can defer if the current use case only needs text
  artifacts.

---

### Phase 3 — Autonomy Loop

**Status:** Ready to start. Implementing plan drafted 2026-04-11: [Plan 51 — Autonomy Loop + Mission Supervisor Agent](51-plan-autonomy-loop-supervisor.md).

**Goal:** A mission keeps moving on its own between run waves — advancing the next
approved wave, refining the plan, proposing completion, or escalating to the user —
so a human can walk away after wave 1 and return to find the mission iterated
through many waves without hand-holding. Without this closed feedback loop, Phase 6
(the 7+ day endurance test) is architecturally impossible.

**Reframe note.** Phase 3 was originally "Signaling" — Telegram notifications so a
user would know when to return. Investigation during Phase 2 close-out surfaced that
the actual load-bearing gap was **iteration**, not notification: the `MissionPlanDaemon`
loops on already-approved tasks but has no authority to approve new ones, so a wave
completes and the mission sits inert until the user manually re-engages. This phase
closes that gap directly via Plan 51. Telegram is deferred to a future plan because
in-app Director chat updates (Plan 51 Phase E) cover v1 conversational continuity
without needing an external channel.

**Work units (all tracked in [Plan 51](51-plan-autonomy-loop-supervisor.md)):**
1. **Plan 51 Phase A — Session followup primitive.** Generic wake-on-event mechanism
   any agent can use to schedule itself on future events (`session_followups` table,
   service + dispatcher hook on event-bus publish). Folds in the previously deferred
   "Director proactive follow-up" TODO candidate as a first consumer.
2. **Plan 51 Phase B — Convergence loop runner.** Graduates Plan 48 Phase 6 only:
   wires the existing `agents/mission_control/dispatch/convergence.py` scaffold into
   dispatch/loop with declarative exit conditions (`score_threshold` /
   `boolean_predicate` / `max_iterations`). Handles the Karpathy "single measurable
   number" and IndyDevDan "till done" intra-task patterns. Plan 48's other phases
   remain deferred as originally scoped.
3. **Plan 51 Phase C — Post-run Gate checkpoint.** Extends Plan 22's `GateReviewer`
   protocol with a new `post_run` gate_type. Rules-first routing: 7 of 8 decision
   branches are deterministic Python (budget exhausted / max iterations / stall
   detected / approved remaining / proposed + gate_mode variants / plan exhausted),
   and the 8th uses Haiku for ambiguous classification. Four independent circuit
   breakers (max supervisor iterations, stall detection, duplicate detection, budget
   headroom) evaluate before any LLM call.
4. **Plan 51 Phase D — `mission.supervisor.agent`.** New mission-tier agent, sibling
   to `mission.director` and `mission.workflow`. Two invocation modes: event-triggered
   (structured output, called by the gate) and chat-triggered (natural language, so
   the user can ask *"why did you escalate wave 3?"* and get an audited answer).
   Model: `claude-haiku-4-5-20251001` — ~$0.003 per decision. Chat mode is read-only
   in v1; overriding decisions still goes through the Director.
5. **Plan 51 Phase E — Director followup integration.** Wires the session followup
   primitive so the Director surfaces supervisor decisions as assistant chat messages
   in the mission Chat tab without user action — replacing Telegram for v1.
6. **Plan 51 Phase F — End-to-end verification.** `scripts/verify_autonomy_loop.py`
   exercising a synthetic multi-wave mission through advance / refine / propose-
   complete / escalate paths, all four circuit breakers, and gate-mode interactions.

**Exit criteria (mirror Plan 51 §6):**
- Autonomy loop works end-to-end on a synthetic multi-wave mission: daemon
  dispatches → run completes → supervisor evaluates → advances → next wave
  dispatches → eventually proposes completion → Director posts chat updates
  throughout. Verified by `scripts/verify_autonomy_loop.py`.
- Each circuit breaker fires independently and is individually tested: budget
  exhaustion, stall detection, duplicate detection, max supervisor iterations.
- Gate-mode respect: the same mission in `interactive` mode always escalates
  instead of auto-advancing (short-circuit before the supervisor LLM is even
  invoked).
- Supervisor decisions are audited via `execution_decisions` rows with
  `decision_type = "post_run_supervisor"`, readable via existing decision queries.
- Chat mode works: the mission owner opens a chat with `mission.supervisor.agent`,
  asks "explain your last decision", and receives a natural-language answer that
  cites the audit trail. Chat mode makes no new decisions.
- In-app Director updates: after a supervisor-driven advance, a new assistant
  message appears in the mission's Chat tab without user action, visible via the
  SSE stream.
- Cost budget: total LLM cost of the supervisor across the verification run (≥4
  wakes) is under $0.05. Haiku class confirmed by the model field in logged
  decisions.
- Plan 48 Phase 6 (convergence loop runner) is wired and verified; Plan 48's other
  phases remain deferred.
- TODO.md "Director proactive follow-up" entry is marked `[x] DONE` with a pointer
  to Plan 51 Phase A.
- Plan 51 is marked "Done" in its own header.

**Explicitly not in this phase:**
- **No Telegram / Slack / Discord / email adapters.** Deferred to a follow-up plan.
  In-app Director chat covers v1 conversational continuity; ping-me-when-I'm-not-in-
  the-app becomes a later concern.
- **No workflow-step supervisor.** Plans 44/45 territory. If a plan task is a
  workflow invocation, the supervisor treats the whole workflow as a single
  task black-box.
- **No cross-mission learning.** The supervisor only knows its own mission's audit
  trail.
- **No auto-mark-complete.** The supervisor never flips `mission_plans.status` to
  `completed`. Completion always requires human confirmation via the Director —
  the non-negotiable runaway-mission safeguard.
- **No chat-mode overrides in v1.** Chatting with the supervisor is read-only.
  Forcing a new decision means opening a chat with the Director instead.
- **No kanban polish** — that's Phase 4.
- **No workflow rewrites** — that's Phase 5.

---

### Phase 4 — Kanban UX polish (close out Plan 41)

**Status:** ✅ **Complete (2026-04-11).** All work units done, exit criteria observably met. Plan 41 marked Done. Phase 5 (workflows) is unblocked.

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

- **Phase 1 → shipped ahead of schedule (2026-04-11):** *Consolidate mission
  navigation — legacy tab routes + new workspace feed modes.* Surfaced 2026-04-11
  when the user noticed that `/missions/:id/*` (legacy tab bar) and `/missions/:id`
  (new workspace) showed overlapping content in parallel navigation systems. Filed
  as a TODO + a handoff brief ([Plan 49](49-plan-mission-nav-consolidation-prompt-[X].md)),
  then handed off to another agent and **shipped in a 5-commit chain that same day**
  — ahead of its Phase 4 scheduling slot because a different session had bandwidth:
    - `ec981da` Delete Workshop tab (file, route, import, constant, tab entry)
    - `2d621c2` Mission nav consolidation — single shell, 9 URL-routed tabs
    - `386b2ad` Frontend polish: ESLint, collapsible panels, inline run detail
    - `d5d9aaf` Add resizable panels for Artifacts and Run Details
    - `9012857` Use structured output renderer in Run Details panel

  Shipped: `MissionLayout` outer shell with single SSE connection, 9 URL-routed
  tabs (Overview / Team / Chat / Plan / Narrative / Stream / Context / Runs /
  Workflows), Zustand `feedMode` slice deleted, Workshop fully removed, all open
  §4 decision points resolved cleanly (Stream reuses `ConsolePage` verbatim, Runs
  tab gains inline `RunDetailPanel` split — richer than the brief asked for,
  Context tab uses `ContextPanel` component). One intentional variance from the
  brief: the 3-panel agent sidebar + artifacts drawer lives *inside the Chat tab
  only*, not wrapping every tab — better judgment call because the sidebar +
  drawer only make semantic sense for chat context. Scrutiny pass confirmed all
  automated checks green (`tsc --noEmit`, `npm run lint`, `npm run build`) and
  dead-reference greps for `feedMode` / `Workshop` / `workspace.tsx` all return
  zero matches. Code-review P10 (`workspace.tsx` god-component decomposition) is
  subsumed — the 1269-line file no longer exists.

---

## 6  Plan close-out tracker

Which plan docs get marked "Done" at the end of which phase:

| Plan | Closes at | Notes |
|---|---|---|
| Plan 37 — Execution Environments (Phases 1–5 only) | Phase 1 ✅ (2026-04-11) | Phases 6/7/9 carved into Plan 48. Phase 8 (worktree) deferred per Plan 37 §5. |
| Plan 47 — Agent Execution Isolation | Phase 1 ✅ (2026-04-11) | Graduated mid-phase when scrutiny surfaced that Plan 37's infrastructure wasn't actually wired into agent execution. Host-side worktree + bind-mount + tier-guarded `project_root` redirect. 14/14 checks on `scripts/verify_isolation.py`. |
| Plan 48 — Convergence Loop + Branch Automation (Phase 6 only) | Phase 3 | Phase 6 (convergence loop runner) graduates in Plan 51 Phase B as the intra-task iteration layer the autonomy loop sits on top of. Plan 48's other phases (branch + PR automation, final verification) remain out of roadmap scope and land opportunistically when a specific mission needs them. |
| Plan 43 — Persistent Artifacts | Phase 2 ✅ (2026-04-11) | Graduated from TODO + implemented in a single focused session. Commits `2e21874` / `c42ae8c` / `73d5859`. `mission_artifacts` table, extraction path in `persist_mission_results`, `GET /missions/:id/artifacts` API, frontend `ArtifactsPanel` rewrite with react-query + SSE invalidation. 7/7 checks on `scripts/verify_artifacts_persistence.py`. |
| Plan 51 — Autonomy Loop + Mission Supervisor Agent | Phase 3 | Graduated 2026-04-11 as the implementing plan for Phase 3 after the reframe from Signaling → Autonomy Loop. Session followup primitive, post-run Gate checkpoint, `mission.supervisor.agent` (Haiku-class, chat-triggered + event-triggered), Director followup integration. Absorbs the "Director proactive follow-up" TODO candidate. |
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

- [Plan 37 — Execution Environments](37-plan-execution-environments.md) (Phases 1–5 only) ✅ Done 2026-04-11
- [Plan 41 — Mission Workspace Redesign](41-plan-mission-workspace-redesign.md)
- [Plan 42 — Mission Backlog Model](42-plan-mission-backlog-model.md)
- [Plan 47 — Agent Execution Isolation](47-plan-agent-execution-isolation.md) ✅ Done 2026-04-11 (graduated mid-Phase-1)
- [Plan 48 — Convergence Loop + Branch Automation](48-plan-convergence-loop-and-branch-automation.md) — extracted from Plan 37 Phases 6/7/9. Phase 6 (convergence loop runner) graduates inside Plan 51 Phase B; other phases remain out of roadmap scope.
- [Plan 51 — Autonomy Loop + Mission Supervisor Agent](51-plan-autonomy-loop-supervisor.md) — implementing plan for Phase 3 (autonomy loop). Session followup primitive, post-run Gate checkpoint, `mission.supervisor.agent`, Director followup integration.

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
