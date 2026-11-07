# Plan 88: Long-Running and Recurring Missions

**Status:** Not started
**Owner:** unassigned
**Created:** 2026-11-07
**Baseline:** code verified at `a28ca771`. Backend and config are identical to `9adaa69d`; later commits change only the frontend.
**Depends on:** none. Phase 0 of this plan fixes the defects that would otherwise block it.
**Supersedes:**
- Plan 46 Phase 6 (the 7-day endurance run).
- The endurance items in Plan 61.
- The mission-objective scheduling item deferred in Plan 83 §8.
**Related:** ADR-004 (unified async architecture), ADR-005 (the mission is the domain primitive), principles P3 (breaking changes are free), P8 (secure by default), P9, P10, P15 and P17.

---

## 1. Problem statement

Mission Control describes missions that carry context "over months or years" and targets Tier 4 autonomy, meaning tasks that run for hours, days or weeks. The code does not support either. A request such as "run mission X every Monday at 06:00 for six months, each run building on the last" fails at five points today:

1. **Only workflow definitions can be scheduled.** `workflow_schedules.workflow_definition_id` is NOT NULL, and missions have no cadence field.
2. **Every schedule fires hourly.** `croniter` is not installed, and `services/workflow_schedule.py:84-87` falls back silently to "now + 1 hour". The stored timezone is never read.
3. **Scheduled runs are killed after 60 seconds.** Each one runs inline in a 60-second local activity with one attempt (`temporal/maintenance_workflow.py:92-95`). `record_fire` commits first, so a cancelled run is never retried.
4. **No memory passes between runs.** There is no run digest and no record of what changed since the previous run. Learnings are assembled and then dropped (`dispatch/loop.py:784-792`). The Mission Context Document (MCD) rejects writes above 20KB.
5. **Any deploy fails live work.** The API-startup reconcilers mark every RUNNING task, execution record and workflow run FAILED without asking Temporal (`services/mission_plan_crash_recovery.py:153-183`).

`MissionRunWorkflow` also has four durability gaps:
- **No liveness signal:** it sends no heartbeats.
- **Unbounded history:** it never calls continue-as-new.
- **Hard cap:** it stops after 25 supervisor iterations.
- **Unsafe deploys:** it reads YAML config inside workflow code, so a config change or deploy while a run is open can break replay.

Unattended operation is also unsafe:
- Only autonomous gate mode works in the worker.
- Escalation notifications are a stub.
- Cancel updates the database only, so the Temporal workflow keeps running.
- Several defaults fail open.

**Goal:** a mission can run on a schedule for months. Each run builds on the previous one. The mission survives worker crashes and deploys, stays inside defined spend limits, waits durably for human approval and notifies its owner. Every occurrence is recorded and auditable.

**Why now:** every later autonomy feature (Plans 85 and 86 and the Think Tank workflows) assumes missions that persist and recur. Building those features on top of the current defects would bake them in.

---

## 2. Agreed design decisions

The owner made these decisions on 2026-11-07. They are binding on the implementer and are not reopened here.

| # | Decision | Choice |
|---|---|---|
| 1 | What recurs | A mission-level schedule starts the durable `MissionRunWorkflow` from a fixed objective template. Saved-workflow scheduling moves onto the same engine, so there is one recurrence path. |
| 2 | Trigger | One Temporal Schedule per mission recurrence, with cron and `time_zone_name` evaluated by Temporal. Postgres is the source of truth. The croniter path and the minute poller are deleted. |
| 3 | Run shape | A new `MissionRun` row per occurrence holds the sequence, schedule, previous run, status, cost and digest. Tasks and execution records link to it. `MissionPlan` stays at one per mission and holds mission-level settings. |
| 4 | Memory between runs | A mandatory end-of-run digest. A per-run MCD watermark so each run sees what changed since the previous one. Learnings are wired into the context packet. Prior outputs are limited to the current run. MCD compaction is automatic instead of rejecting writes. |
| 5 | Crash recovery | The API-startup reconcilers are deleted. A periodic, Temporal-aware reconciler in the worker fails only rows whose workflow is closed or unknown. |
| 6 | Budget | `llm_calls` is the single ledger. Caps apply per run, per calendar month and optionally for the mission's lifetime. A breach stops the run cleanly, pauses the schedule and notifies the owner. |
| 7 | Gates | A durable gate in `MissionRunWorkflow` built on a signal, `wait_condition` and timers. On timeout it escalates and then pauses; it does not abort. A missing or unknown gate mode is rejected. |
| 8 | Overlap and catch-up | An overlapping occurrence is skipped and the skip is recorded. After downtime, the latest missed occurrence runs once if it is inside a per-mission catch-up window (default 6 hours); otherwise it is recorded as missed. |
| 9 | Notifications | Recipients are set per mission and default to the owner. Telegram is the first channel. Telegram supports inbound Approve and Reject. The approval must be bound to a verified platform identity, use a single-use expiring token and leave the same audit trail as a web approval. |
| 10 | Lifecycle | PAUSED pauses the schedule, and a run in progress pauses after its current step. ARCHIVED deletes the schedule and cancels the active run. Cancel reaches Temporal. A schedule can end on a date or after a maximum number of runs. |
| 11 | Activity granularity | One activity per task, with heartbeats. Timeouts come from config and are independent of budget. An idempotency key (run id and task id) prevents a retry from re-running or re-charging a completed task. |
| 12 | Versioning | The config snapshot is a workflow input. Code changes use `workflow.patched`. CI replays recorded histories. Continue-as-new replaces the 25-iteration cap. |
| 13 | Retention | A nightly job applies per-table retention periods from config. Digests, runs and audit records are kept permanently. Raw events and task outputs are kept for 90 days. `llm_calls` are rolled up to daily aggregates after 90 days. The 1-second poller is replaced by event-driven dispatch. |
| 14 | Delivery | Phase 0 bug fixes ship first. Phases 1 to 5 each ship to `main` once they pass. Acceptance requires a real 7-day hourly run (168 runs) with a worker kill and a redeploy, then a 4-week weekly mission. |

---

## 3. Global constraints for the implementing agent

These rules override any instinct to improvise.

1. **Read the shared contracts before any phase.** They are in [00-shared-contracts.md](088-plan-long-running-recurring-missions/00-shared-contracts.md). Every name, column, id format, config key and signature in the phases comes from there. If a phase needs something the contracts do not define, add it to the contracts in the same commit and say so in the commit message.
2. **Respect phase ownership.** The ownership table in section 3.0.1 of the contracts names the single step that creates each shared component. Later steps modify that component and never recreate it.
3. **Fail fast, fail closed.** No silent fallbacks and no hardcoded defaults. A missing required value raises an error. Empty allowlists deny access. Unknown enum values are rejected.
4. **P3 applies.** Replaced code is deleted in the same commit. Do not add shims, `_legacy` aliases or compatibility branches.
5. **One commit per step.** Commit message prefix `Plan 88 Phase N:` followed by the step id, for example `Plan 88 Phase 1: 88.1.6 MissionScheduleService`. Never commit a red build.
6. **Verify before every commit:**
   ```bash
   python scripts/code_rules_fast.py --all   # must exit 0
   pytest tests/unit -x -q                   # must pass
   ```
   Also run `pytest tests/integration -x -q` when the step touches services, repositories, migrations or API. It needs local Postgres, Redis and Temporal; `python services.py check` confirms they are up.
7. **House rules that recur in this plan:**
   - Absolute imports only.
   - Use `get_logger` for logging and `utc_now()` for timestamps.
   - Timestamp columns are `DateTime(timezone=True)`.
   - `Enum(native_enum=False)` stores the NAME (uppercase).
   - API responses use the `ApiResponse` envelope.
   - Layers are API → service → repository → model.
   - `mc` and the web are thin REST clients.
   - Files target about 500 lines, with a hard maximum of 1000.
8. **Temporal determinism.** Workflow code never reads config, the clock, randomness or the database directly. It uses workflow inputs, `workflow.now()`, `workflow.uuid4()` and activities. Every behavioural change to an existing workflow goes behind a registered `workflow.patched` id, as section 3.3 and step 88.2.8 describe.
9. **Start each phase from a clean tree.** `git status --porcelain` must list no changes under `modules/`, `config/`, `tests/`, `requirements*.txt`, `pyproject.toml`, `mc.py`, `admin.py` or `services.py`. Commit or stash other work in progress first. If that work has been committed since the baseline, re-check the line citations in the files it touched, finding the code by symbol name, before starting the phase.
10. **Line numbers drift.** Each phase's "Current state" cites lines at the baseline. If a line has moved, find the code by symbol name and carry on. If the code no longer exists, stop and report it.
11. **Phase exit gate.** A phase is complete only when its Verification block passes in full. Mark the phase done in the progress table (section 4) in the same commit as its last step.
12. **Production safety between phases.** Budget enforcement and durable gates arrive in Phase 4. Until Phase 4 is complete, production runs with `missions.recurrence.enabled: false`, and MANUAL and AI_ASSISTED missions are not dispatched unattended. Phases 1 to 3 may run with recurrence enabled in development and CI only.

---

## 4. Phase overview and progress

**Reading order:**
1. This index file.
2. The shared contracts.
3. One phase file at a time, in order.

Each phase file is self-contained apart from its references to the contracts.

| Phase | File | Outcome | Entry criterion | Status |
|---|---|---|---|---|
| (all) | [00-shared-contracts.md](088-plan-long-running-recurring-missions/00-shared-contracts.md) | Data model, state machines, Temporal contracts, config keys, service and API interfaces, phase ownership | n/a | n/a |
| 0 | [phase-0-correctness-fixes.md](088-plan-long-running-recurring-missions/phase-0-correctness-fixes.md) | State-corrupting defects fixed: reconciler, gate defaults, workflow ids, cancel and delete, IDOR, swallowed exceptions, Telegram fail-open | Baseline commit | Not started |
| 1 | [phase-1-missionrun-and-schedules.md](088-plan-long-running-recurring-missions/phase-1-missionrun-and-schedules.md) | `MissionRun` entity; mission schedules backed by Temporal Schedules; event-driven dispatch; run reconciliation; API, `mc` and web | Phase 0 done; Alembic head `plan87_002` | Not started |
| 2 | [phase-2-durable-execution.md](088-plan-long-running-recurring-missions/phase-2-durable-execution.md) | One activity per task with heartbeats and idempotency; config snapshot as input; `workflow.patched`; replay tests in CI; continue-as-new | Phase 1 done | Not started |
| 3 | [phase-3-memory-between-runs.md](088-plan-long-running-recurring-missions/phase-3-memory-between-runs.md) | Run digest, MCD delta and watermark, learnings in context, bounded prior outputs, automatic compaction | Phase 2 done | Not started |
| 4 | [phase-4-gates-budgets-notifications-lifecycle.md](088-plan-long-running-recurring-missions/phase-4-gates-budgets-notifications-lifecycle.md) | Budget caps on the single ledger; mission lifecycle reaching Temporal; durable gates; per-mission notifications; Telegram approvals; web lifecycle UI | Phase 3 done | Not started |
| 5 | [phase-5-retention-observability-acceptance.md](088-plan-long-running-recurring-missions/phase-5-retention-observability-acceptance.md) | Retention and rollup; health views; stale-gate sweep; endurance evaluator; CI endurance variant; the 7-day and 4-week acceptance runs | Phase 4 done | Not started |

**Definition of done for the plan:** acceptance runs 1 and 2 in Phase 5 both pass their criteria, and the evaluator reports the results recorded in step 88.5.15.

---
