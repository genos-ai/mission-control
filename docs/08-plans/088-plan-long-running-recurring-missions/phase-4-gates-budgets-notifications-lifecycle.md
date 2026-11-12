## Phase 4: Gates, budgets, notifications and lifecycle

This phase lets a recurring mission run unattended without overspending, and it gives the owner effective control over a mission while runs are in flight. Phase 4 adds:

- **Budget control:** `llm_calls` plus `llm_call_daily_aggregates` form the single ledger, and every run is held to a per-run cap, a per-calendar-month cap and an optional lifetime cap.
- **Durable gates:** a gate that survives restarts, escalates on its first timer and pauses on its second.
- **Notifications:** per-mission notifications on Telegram, plus Approve and Reject buttons sent back from Telegram by a confirmed, linked account.
- **Lifecycle:** pause, resume, archive and cancel now act on the Temporal schedule and workflow handles as well as on Postgres, and the web exposes them.

The phase covers decisions 6, 7, 9 and 10. Every file:line below was checked against `a28ca771`; backend and config are identical to `9adaa69d` and `777cd5c5`, and the frontend lines were re-read at `a28ca771`. Phases 0 to 3 rewrite some of the cited files. Where a line has moved, locate it by the symbol named beside it. Code that this plan already rewrote is cited by its owning step, not by a line number.

**Entry criteria:** Phases 0 to 3 are merged to main. Stop if any of the following is false:

1. **Migrations.** `python admin.py migrate current` reports `plan88_003a` (88.3.4's data-only learning repair). `plan88_002` created `llm_calls.mission_run_id`, `llm_calls.task_id`, `ix_llm_calls_mission_run_id` and `ix_llm_calls_mission_created`.
2. **Models.** `MissionRun`, `MissionSchedule`, `MissionRunDigest`, `GateMode`, `MissionMemberRole` and `MissionRunStateError` exist.
3. **Operator rule.** `MissionService.is_operator(mission, user)` and `require_mission_operator` exist (88.0.9) and guard `PATCH /missions/{id}/plan`, the run endpoints (88.1.12) and the gate decide endpoint (88.0.13).
4. **Workflow.** `MissionRunWorkflow` has `@workflow.init`, `_end_run(status, reason, detail)`, the module functions `_exec(fn, arg, p)` and `_cause_type(e)`, the handler-owned fields `_approved_seq`, `_pause_requested`, `_paused` and `_decision` (88.1.8), `_layer_boundary(self) -> str | None` (88.2.6, which holds the duration check), the `_gate(point, task_id)` seam returning `"continue"` (88.2.6) and `_maybe_continue_as_new` (88.2.7). It takes a `RunConfigSnapshot`, runs one `execute_plan_task` per task and contains no budget branch.
5. **Versioning.** `temporal/versioning.PATCH_IDS` contains `p88-run-memory`. `tests/unit/backend/temporal/test_replay_histories.py` and `scripts/record_workflow_history.py` exist (88.2.9).
6. **Deleted code.** `temporal/workflow.py` (`AgentMissionWorkflow`), `execute_mission`, `persist_mission_outcome`, the `send_notification` activity, `NotificationPayload`, `POST /executions/{id}/execute` and `/approve` are gone (88.2.6). `rg -n "AgentMissionWorkflow|send_notification\b|NotificationPayload" modules --glob '!modules/backend/migrations/**'` prints nothing.
7. **Runs and schedules.** `MissionRunService.start_run`, `begin`, `finalise` (writing `cost_usd` from the ledger) and `cancel_run` exist, and `build_run_config_snapshot()` in `temporal/config_snapshots.py` (88.1.5; fields extended by 88.2.2) is the only builder of `RunConfigSnapshot`. `begin` ends a run `FAILED/START_FAILED` with detail "owner not a platform user" when `missions.owner_id` is not an existing user id (contracts 3.0.2), and `FAILED/INVALID_GATE_MODE` for an invalid mode; both raise `RunStartRejectedError` (88.1.7, in `NON_RETRYABLE`). `TemporalWorkflowGateway` (88.0.3) has `start_mission_run` (88.1.7) and `signal` (88.1.9). Outside it and `TemporalScheduleGateway`, no code calls `start_workflow` or `get_workflow_handle` for `MissionRunWorkflow`, `MissionScheduleTickWorkflow`, `ReconcilerWorkflow` or `RetentionWorkflow`; other workflows (chat, tool fork, plan refine, human input, workflow-run) are out of scope. `MissionScheduleService.claim_occurrence` and `sync_to_temporal` work without a budget rule.
8. **Ledger attribution.** `record_llm_call` and `TokenEconomicsService.record_call` accept and write `mission_run_id` and `task_id` (88.2.3).
9. **Memory.** `write_run_digest` exists and `_end_run` calls compaction, the digest and `finalise_mission_run` in that order (88.3.8).
10. **Reconciler and Telegram.** `RunReconciliationService` reconciles `mission_runs` (88.1.10a). The Telegram allowlist fails closed and the webhook secret is mandatory (88.0.14).
11. **Web gate route.** `modules/frontend/src/hooks/use-gates.ts` exports `useGateRequest` and `useDecideGate` (88.0.13).
12. **Clean suite.** `pytest tests/unit tests/integration` is green.
13. **Clean tree.** `git status --porcelain` lists no changes under `modules/`, `config/`, `tests/`, `requirements*.txt`, `pyproject.toml`, `mc.py`, `admin.py` or `services.py`. Uncommitted work in progress (for example the model-provider changes in progress at the time of writing) is committed or stashed first. If such work is committed, re-verify by symbol the line citations in the files it touched before starting this phase.

All commits use the prefix `Plan 88 Phase 4:`, one commit per step. Phase 4 is released as one deploy; intermediate commits are not deployed (Risk 6).

**Patch rule (contracts 3.0.2).** Each step that introduces `workflow.patched("<id>")` adds the id to `temporal/versioning.PATCH_IDS`, records one history for the new branch with `python scripts/record_workflow_history.py record --workflow-id mission-run-<uuid> --name <id>` into `tests/fixtures/temporal_histories/mission_run/<id>.json`, and adds `<id>` to `REQUIRED` in `tests/unit/backend/temporal/test_replay_histories.py`. Existing fixtures stay. The ids in this phase are `p88-lifecycle-signals` (88.4.5), `p88-budget-caps` (88.4.6) and `p88-durable-gate` (88.4.8). Run-end and tick notifications are sent under `p88-lifecycle-signals`.

**Wire format (3.0.2).** Every Temporal DTO string field in this phase carries the lowercase enum value: `_end_run("budget_stopped", "budget_run_cap", None)`, `RunStatusUpdate(run_id, "paused", "user_pause", None)`, `NotificationRequest(kind="budget_paused", …)`. Uppercase names appear only in SQL.

**Events.** Every event this phase adds goes in `events/mission_run_types.py` (exists since 88.1.6, importing `SessionEvent` from `events.base`) and is registered in `EVENT_TYPE_MAP` in `events/types.py`, so `events/types.py` gains only map entries and stays under 1000 lines.

---

### 88.4.1 Budget caps schema, ledger repository and BudgetService (`plan88_004`)

**Files**
- create `modules/backend/migrations/versions/plan88_004_budget_caps.py`
- create `modules/backend/models/llm_call_daily_aggregate.py`, `modules/backend/services/budget.py`, `modules/backend/schemas/budget.py`, `modules/backend/api/v1/endpoints/missions_budget.py`
- create `modules/frontend/src/hooks/use-mission-budget.ts`, `modules/frontend/src/types/budget.ts`
- modify (exists since 88.1.7) `modules/backend/repositories/llm_ledger.py`
- modify `modules/backend/models/mission_plan.py`, `modules/backend/models/mission.py`, `modules/backend/models/__init__.py`, `modules/backend/migrations/env.py`, `modules/backend/core/config_schema.py`, `config/settings/missions.yaml`
- modify `modules/backend/schemas/mission.py`, `modules/backend/schemas/mission_plan.py`, `modules/backend/services/mission.py`, `modules/backend/services/mission_plan.py`, `modules/backend/services/mission_run.py`, `modules/backend/services/mission_plan_orchestrator.py`, `modules/backend/repositories/mission_plan.py`, `modules/backend/repositories/task.py`
- modify `modules/backend/temporal/supervisor_activities.py`, `modules/backend/agents/mission_control/gate_post_run.py`, `modules/backend/agents/mission_control/helpers/agent_executor.py`, `modules/backend/agents/mission/director/agent.py`, `modules/backend/agents/mission/director/tools/get_mission_info.py`, `modules/backend/agents/mission/director/tools/refine_plan.py`, `modules/backend/agents/adapters/plan_introspection.py`
- modify `modules/backend/api/v1/endpoints/missions.py`, `modules/backend/api/v1/endpoints/missions_plan.py`
- modify `modules/frontend/src/types/mission.ts`, `modules/frontend/src/types/index.ts`, `modules/frontend/src/hooks/use-mission-plan.ts`, `modules/frontend/src/components/mission/mission-edit-modal.tsx`, `modules/frontend/src/components/workspace/plan-board-top-bar.tsx`, `modules/frontend/src/components/dashboard/mission-card.tsx`, `modules/frontend/src/pages/mission/overview.tsx`, `modules/frontend/src/pages/mission/tabs/costs-tab.tsx`, `modules/frontend/src/pages/mission/new.tsx`
- modify `modules/clients/cli/mc_mission.py`, `modules/clients/cli/mc_groups/mission.py`, `modules/clients/cli/mc_status.py`, `modules/clients/cli/mc_plan.py`, `modules/clients/cli/mc_run.py`, `modules/clients/cli/mission_cmds.py`

**Current state**
- **Two diverging ledgers.** `MissionPlan.budget_usd_ceiling` and `total_spent_usd` are at `models/mission_plan.py:142,148`. `Mission.budget_ceiling_usd` is at `models/mission.py:89`.
- **Dispatch is gone.** `dispatch_approved` and `mission_plan_dispatch.py` were deleted in 88.2.6. `gate_post_run.py:121-130` holds breaker #1.
- **Spend and budget in the orchestrator.** `services/mission_plan_orchestrator.py:169,338` read `plan.budget_usd_ceiling`. The other baseline references (`:368,387,404-412`) sat inside `run_objective`, which 88.1.7 deleted.
- **Supervisor.** 88.2.6 item 8 made `_do_evaluate_post_run` (`temporal/supervisor_activities.py`) set `GateContext.total_cost_usd` from `MissionPlanService.total_task_cost_usd` and `budget_usd` from `plan.budget_usd_ceiling`.
- **Other readers:**
  - `agents/mission/director/agent.py:157-159`
  - `agents/mission/director/tools/get_mission_info.py:44`
  - `agents/mission/director/tools/refine_plan.py:72`
  - `agents/adapters/plan_introspection.py:47-48`
  - `repositories/mission_plan.py:52,65-66`
  - `services/mission_plan.py:150`
  - `services/mission.py:67,88` and `api/v1/endpoints/missions.py:72`
  - `schemas/mission.py:51,87,110`
  - `schemas/mission_plan.py:58,141-142,186` (`:165` belonged to the run-objective request deleted in 88.1.12)
  - `core/config_schema.py:472` (`default_budget_ceiling_usd`)
- **Layering break.** `api/v1/endpoints/missions_plan.py:117-119` writes `plan.budget_usd_ceiling` from the endpoint, and `:184` reads it in the dispatch endpoint.
- **Ledger write failures are swallowed** at `helpers/agent_executor.py:346-362` (agent calls) and `:635-649` (planning agent).
- **Clients.**
  - `mc`: `mc_mission.py:22,34-35,123-124,189-194`, `mc_groups/mission.py:37-50,115-125`, `mc_status.py:52-66`, `mc_plan.py:61-66`, `mc_run.py:154,190-191` (an ignored field on the workflow-run POST), `:341,363,413` (cost read from `total_spent_usd`).
  - Admin: `mission_cmds.py:25,60,78,103,205-206`.
  - Web: `types/mission.ts:19,40,48`, `hooks/use-mission-plan.ts:68-69,86,135`, `mission-edit-modal.tsx:18,31-32,45,93-104`, `plan-board-top-bar.tsx:60-62,129-133`, `mission-card.tsx:54,116-119`, `overview.tsx:62,148-152`, `costs-tab.tsx:57`, `new.tsx:43,68,148-160`.

**Change**
1. **Migration `plan88_004_budget_caps`** (`revision = "plan88_004"`, `down_revision = "plan88_003a"`). It never calls `get_app_config()`. The backfill values are module constants:
   ```python
   DEFAULT_PER_RUN_USD = 5.00  # missions.budgets.default_per_run_usd at plan88_004
   DEFAULT_PER_MONTH_USD = 100.00  # missions.budgets.default_per_month_usd at plan88_004
   ```
   `upgrade()` runs, in order:
   1. Add `mission_plans.budget_per_run_usd` and `budget_per_month_usd` as nullable `NUMERIC(12,6)`. `UPDATE mission_plans SET budget_per_run_usd = :run, budget_per_month_usd = :month` with the two constants, then `ALTER … SET NOT NULL` on both.
   2. Add `ck_mission_plans_per_run_pos CHECK (budget_per_run_usd > 0)`, `ck_mission_plans_per_month_pos CHECK (budget_per_month_usd > 0)` and `ck_mission_plans_month_ge_run CHECK (budget_per_month_usd >= budget_per_run_usd)`.
   3. Rename `budget_usd_ceiling` to `budget_lifetime_usd`. Run `UPDATE mission_plans SET budget_lifetime_usd = NULL WHERE budget_lifetime_usd <= 0`, then add `ck_mission_plans_lifetime_pos CHECK (budget_lifetime_usd IS NULL OR budget_lifetime_usd > 0)`.
   4. Drop `mission_plans.total_spent_usd` and `missions.budget_ceiling_usd`.
   5. Backfill the run cap of active runs: `UPDATE mission_runs r SET budget_cap_usd = p.budget_per_run_usd FROM mission_plans p WHERE r.plan_id = p.id AND r.budget_cap_usd IS NULL AND r.status IN ('PENDING','RUNNING','AWAITING_GATE','PAUSED')`.
   6. Create `llm_call_daily_aggregates` exactly as 3.1.11, with `uq_llm_daily` (`postgresql_nulls_not_distinct=True`) and `ix_llm_daily_mission_day (mission_id, day)`.

   `downgrade()` reverses the structure only (drops the table, restores the dropped columns as nullable, renames back, drops the checks and new columns). It adds no `llm_calls` column or index.
2. **Aggregate model.** `models/llm_call_daily_aggregate.py` defines `LlmCallDailyAggregate(Base)`, exactly as in 3.1.11:
   - `id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)`;
   - `created_at` as `DateTime(timezone=True)` with `server_default=func.now()`;
   - `day` as `Date`, `mission_id` as `PgUUID(as_uuid=False)` (nullable), `agent_name` as `String(200)`, `model` as `String(100)`, `provider` as `String(50)`;
   - `call_count` as `Integer`; `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_5m_tokens`, `cache_write_1h_tokens` and `thinking_tokens` as `BigInteger`; `cost_usd` as `Numeric(14,6, asdecimal=False)`;
   - `__table_args__`: `UniqueConstraint("day", "mission_id", "agent_name", "model", "provider", name="uq_llm_daily", postgresql_nulls_not_distinct=True)` and `Index("ix_llm_daily_mission_day", "mission_id", "day")`.

   Register it in `models/__init__.py` and `migrations/env.py`. 88.5.2 adds `plan88_008_retention_indexes`; 88.5.3 adds `LlmLedgerRepository.rollup_day`.
3. **Plan and mission models.** `MissionPlan` loses `budget_usd_ceiling` and `total_spent_usd` and gains `budget_per_run_usd: float`, `budget_per_month_usd: float` (both NOT NULL) and `budget_lifetime_usd: float | None`, all `Numeric(12,6, asdecimal=False)`. `Mission` loses `budget_ceiling_usd`.
4. **Config.** Append the `budgets:` block from 3.4.2 to `missions.yaml` and add `BudgetDefaultsSchema` (3.4.6) to `MissionsSchema` as `budgets`. Delete `MissionsSchema.default_budget_ceiling_usd` (`config_schema.py:472`).
5. **`LlmLedgerRepository.sum_cost` (exists since 88.1.7) gains the aggregates branch** (`repositories/llm_ledger.py`).
   ```python
   async def sum_cost(self, mission_id: str, *, since: datetime | None, until: datetime | None,
                      mission_run_id: str | None = None) -> float: ...
   ```
   - **Raw rows.** `SUM(llm_calls.cost_usd)` filtered by `mission_id`, `created_at >= since` when `since` is set, `created_at < until` when `until` is set and, when given, `mission_run_id`.
   - **Aggregates.** When `mission_run_id is None`, add `SUM(llm_call_daily_aggregates.cost_usd)` filtered by `mission_id`, `day >= since.date()` when `since` is set and `day < until.date()` when `until` is set. The table exists from `plan88_004`, so there is no existence check. Run-scoped sums never read aggregates, because retention never rolls up rows of a non-terminal run (3.1.11).
   - Both sums use `coalesce(…, 0)`. `rollup_day` is added by 88.5.3.
6. **`BudgetService` (`services/budget.py`), following 3.5.1.**
   - **Month window.** `month_start = utc_now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)`; `month_end` is the first instant of the next month, computed as `(month_start + timedelta(days=32)).replace(day=1)` (OPEN item 5).
   - **`get_status(mission_id) -> BudgetStatus`.** Caps from the plan; `month_spent_usd = sum_cost(mission_id, since=month_start, until=month_end)`; `lifetime_spent_usd = sum_cost(mission_id, since=None, until=None)`; `active_run_spent_usd = sum_cost(mission_id, since=None, until=None, mission_run_id=active.id)`, or `0.0` when there is no active run; `breach`.
   - **Breach precedence.** `breach` is the first of `MissionPauseReason.BUDGET_RUN_CAP` (active run spend >= that run's cap), `BUDGET_MONTHLY_CAP` (month spend >= per-month cap) and `BUDGET_LIFETIME_CAP` (lifetime cap set and lifetime spend >= it), else `None`.
   - **`@staticmethod mission_cap_breach(status: BudgetStatus) -> MissionPauseReason | None`.** Returns `BUDGET_MONTHLY_CAP` or `BUDGET_LIFETIME_CAP` from the month and lifetime fields directly, ignoring the run cap. `resume_mission` (88.4.5) and the claim rule (88.4.6) use it.
   - **`check_run(run_id) -> BudgetCheckResult`.** The run cap is `coalesce(run.budget_cap_usd, plan.budget_per_run_usd)`. `headroom_usd = max(0.0, min(candidates))`, where `candidates` holds `run_cap - run_spent`, `per_month - month_spent` and, when the lifetime cap is set, `lifetime - lifetime_spent`. `breach` follows the precedence above, with this run's spend in place of the active run's.
   - **`@staticmethod validate_caps(per_run: float, per_month: float, lifetime: float | None) -> None`.** Rules: `0 < per_run <= missions.budgets.max_per_run_usd`, `per_run <= per_month <= missions.budgets.max_per_month_usd`, and `lifetime is None or lifetime > 0`. Any failure raises `ValidationError` naming the rule.
   - **`update_caps(mission_id, data, user_id)`.** Calls `validate_caps`, writes the plan, commits, and returns `get_status`. It never resumes the mission; resume is a separate act (88.4.5).
7. **Fatal ledger writes in run context.** At `agent_executor.py:346-362` and `:635-649`, when `mission_run_id is not None` the exception propagates instead of being logged and swallowed. The ledger is the enforcement source, so a lost row is a budget bypass. With `mission_run_id is None` (chat, in-process paths) today's warning and `SystemEvent` stay.
8. **Run cap snapshot.** `MissionRunService.begin` sets `run.budget_cap_usd = plan.budget_per_run_usd` in the same write that snapshots `gate_mode`.
9. **Schemas and mission creation.**
   - **`MissionCreate`** (`schemas/mission.py:51`) loses `budget_ceiling_usd` and gains `budget_per_run_usd: float | None`, `budget_per_month_usd: float | None` and `budget_lifetime_usd: float | None`. `gate_mode` has been required since 88.1.0.
   - **`MissionUpdate`** loses `budget_ceiling_usd` (`:87`), and `MissionResponse` loses it too (`:110`).
   - **`create_mission`** (`services/mission.py:58`) loses `budget_ceiling_usd` and takes the three caps. `None` per-run and per-month caps are filled from `missions.budgets.default_per_run_usd` and `default_per_month_usd`. It calls `BudgetService.validate_caps` before any insert and passes the caps to the eager plan creation added in 88.1.0. `api/v1/endpoints/missions.py:72` passes the three fields.
   - **`MissionPlanRepository.create_for_mission`** (`repositories/mission_plan.py:47-68`) takes `budget_per_run_usd`, `budget_per_month_usd` and `budget_lifetime_usd`, and drops `total_spent_usd` and `budget_usd_ceiling`.
   - **Plan schemas.** `MissionPlanUpdate` (`schemas/mission_plan.py:58`) loses `budget_usd_ceiling`. `MissionPlanResponse` (`:141-142`) loses `budget_usd_ceiling` and `total_spent_usd`. `DispatchApprovedResponse` (`:186`) loses `new_total_spent_usd`.
   - **Endpoint.** Delete `missions_plan.py:117-119`. At `:184` the dispatch endpoint calls `start_run` (88.1.12), so the `mission_budget_usd` argument is deleted with its `get_default_budget_usd` import if unused.
10. **Reader rewiring (P3).**
    - **Orchestrator.** At `mission_plan_orchestrator.py:169,338`, `budget = mission_budget_usd`.
    - **Breaker #1.** Delete `gate_post_run.py:121-130`. The remaining `rule=` values are not renumbered.
    - **Supervisor activity.** `_do_evaluate_post_run` calls `BudgetService(session).check_run(mission_run_id)` and sets `GateContext.total_cost_usd = check.run_spent_usd` and `GateContext.budget_usd = check.run_spent_usd + check.headroom_usd`, so `_check_budget_headroom` (`gate_post_run.py:487-519`) measures remaining headroom. Delete the `total_task_cost_usd` and `plan.budget_usd_ceiling` reads 88.2.6 added, and delete `MissionPlanService.total_task_cost_usd` and `TaskRepository.sum_cost_by_plan`.
    - **Director and introspection** (`director/agent.py:157-159`, `get_mission_info.py:44`, `refine_plan.py:72`, `plan_introspection.py:47-48`) read `BudgetService(session).get_status(mission_id)` and present `per_run_usd`, `per_month_usd`, `month_spent_usd` and `lifetime_usd`. `refine_plan.py:72` passes `mission_budget_usd=status.per_run_usd`.
    - **`services/mission_plan.py:150`** drops the field.
11. **API.** `missions_budget.py` holds `GET /missions/{id}/budget` (`require_existing_mission_access`) and `PUT /missions/{id}/budget` (`require_mission_operator`, exists since 88.0.9). Both return `BudgetStatusResponse` in `ApiResponse`, with `breach` as the lowercase `MissionPauseReason` value or `null`. Include the router in `api/v1/endpoints/missions.py` after `missions_gates`.
12. **mc and admin clients.**
    - `mc mission create` replaces `--budget` (`mc_groups/mission.py:37`) with `--budget-per-run FLOAT`, `--budget-per-month FLOAT` and `--budget-lifetime FLOAT`, all optional; `mc_mission.create` (`:22,34-35`) sends them as `budget_per_run_usd`, `budget_per_month_usd` and `budget_lifetime_usd` when given.
    - `mc mission budget` calls `GET /budget` and renders the caps, spend and breach with `report.py` primitives. `mc mission set-budget --per-run X --per-month Y [--lifetime Z | --no-lifetime]` calls `PUT /budget` and replaces `set_budget` (`mc_mission.py:189-194`, `mc_groups/mission.py:115-125`).
    - `mc_mission.py:123-124` and `mc_status.py:52-66` print `per_month_usd` and `month_spent_usd` from `GET /budget`. `mc_plan.py:61-66` drops the spent and ceiling fields.
    - `mc_run.py`: delete the `budget` parameter of the workflow path (`:154,190-191`); 88.1.13 already removed `--budget` from the `mc run` options. At `:341` delete the `mission_plan.run.completed` branch. At `:363-371` and `:413-421` delete the cost segment of the "Plan complete" line; `mc runs show SEQ` shows run cost.
    - Admin `mission_cmds.py`: drop the `budget` parameter (`:25,60,78,103`). `:205-206` print the caps from `BudgetService(session).get_status` (in-process; the admin CLI runs inside the backend trust boundary).
13. **Web.**
    - `types/budget.ts` mirrors `BudgetStatusResponse` and `BudgetCapsUpdate`; export them from `types/index.ts`. `hooks/use-mission-budget.ts` exports `useMissionBudget(missionId)` (GET, query key `['missions', missionId, 'budget']`).
    - `types/mission.ts:19,40,48`: delete `budget_ceiling_usd`; `MissionCreateRequest` gains `gate_mode` (since 88.1.0) plus optional `budget_per_run_usd`, `budget_per_month_usd` and `budget_lifetime_usd`.
    - `hooks/use-mission-plan.ts:68-69,86,135`: delete `budget_usd_ceiling`, `total_spent_usd` and `new_total_spent_usd`.
    - `pages/mission/new.tsx:43,68,148-160`: replace the "Budget ceiling" field with three fields (per run, per month, lifetime with placeholder "No limit"), sent only when filled.
    - `mission-edit-modal.tsx:18,31-32,45,93-104`: delete the budget field and its state; the modal edits description, brief and environment. Budget editing arrives in 88.4.10.
    - `plan-board-top-bar.tsx:60-62,129-133`: read `useMissionBudget`; the meter shows `month_spent_usd` of `per_month_usd` with the title "Spent this month of the monthly cap".
    - `overview.tsx:62,148-152`: the same monthly figure from `useMissionBudget`.
    - `costs-tab.tsx:57`: `ceiling={budget?.lifetime_usd ?? null}`.
    - `mission-card.tsx:54,116-119`: delete the ceiling and progress bar; the card shows `spent_usd` only (no per-card budget query).

**Tests**
- `tests/unit/backend/services/test_budget_service.py`:
  - `test_month_window_is_utc_calendar_month`: a row at `2026-10-31T23:59Z` is excluded from November, and `2026-11-01T00:00Z` is included.
  - `test_breach_precedence_run_then_month_then_lifetime`: with all three exceeded, `breach == MissionPauseReason.BUDGET_RUN_CAP`.
  - `test_mission_cap_breach_ignores_run_cap`: run and month exceeded gives `BUDGET_MONTHLY_CAP`.
  - `test_headroom_is_min_of_three_and_never_negative`.
  - `test_lifetime_none_ignored`.
  - `test_check_run_uses_plan_cap_when_snapshot_null`.
  - `test_update_caps_rejects_month_below_run`: `ValidationError`.
  - `test_update_caps_rejects_above_configured_max`.
- `tests/unit/backend/repositories/test_llm_ledger.py`:
  - `test_sum_cost_filters_by_run_and_window`.
  - `test_sum_cost_adds_aggregates_only_without_run`.
- `tests/unit/backend/agents/mission_control/test_agent_executor_ledger.py`:
  - `test_ledger_failure_propagates_in_run_context`
  - `test_ledger_failure_swallowed_without_run`
  - `test_planning_ledger_failure_propagates_in_run_context`
- `tests/integration/backend/services/test_mission_run_service.py::test_begin_snapshots_run_cap`.
- `tests/integration/backend/migrations/test_plan88_004.py`:
  - `test_backfills_caps_from_constants`
  - `test_rename_preserves_lifetime_value`
  - `test_active_run_cap_backfilled`
  - `test_uq_llm_daily_nulls_not_distinct`: two rows with `mission_id=NULL` and an identical key raise `IntegrityError`.
  - `test_downgrade_restores_columns`
- `tests/integration/backend/api/test_missions_budget.py`:
  - `test_get_budget_member_ok`
  - `test_put_budget_viewer_forbidden`
  - `test_put_budget_maintainer_ok_envelope`
  - `test_breach_serialised_lowercase`: `data.breach == "budget_monthly_cap"`.
- `tests/unit/clients/cli/test_mc_mission_budget.py`:
  - `test_create_sends_budget_flags`
  - `test_set_budget_puts_caps`

**Done when**
- `rg -n "total_spent_usd|budget_usd_ceiling|budget_ceiling_usd|default_budget_ceiling_usd" modules config --glob '!modules/backend/migrations/**'` returns nothing.
- `python admin.py migrate upgrade head`, then `python admin.py migrate downgrade plan88_003a`, then `python admin.py migrate upgrade head` succeeds.
- `cd modules/frontend && npm run build && npm run lint` passes.
- The listed tests pass.

---

### 88.4.2 Lifecycle schema and removal of plan status (`plan88_005`)

**Files**
- create `modules/backend/migrations/versions/plan88_005_lifecycle.py`
- modify `modules/backend/models/mission.py`, `modules/backend/models/mission_plan.py`, `modules/backend/models/__init__.py`, `modules/backend/schemas/mission.py`, `modules/backend/schemas/mission_plan.py`, `modules/backend/repositories/task.py`, `modules/backend/repositories/mission_plan.py`, `modules/backend/services/mission_plan.py`, `modules/backend/api/v1/endpoints/missions_plan.py`, `modules/backend/temporal/supervisor_activities.py`
- modify `modules/clients/cli/mc_status.py`, `modules/clients/cli/mc_plan.py`
- modify `modules/frontend/src/hooks/use-mission-plan.ts`, `modules/frontend/src/components/workspace/plan-board-top-bar.tsx`, `modules/frontend/src/components/mission/mission-top-bar.tsx`, `modules/frontend/src/types/mission.ts`

**Current state**
- **The plan has its own status.** `MissionPlanStatus` is at `models/mission_plan.py:28` and the column at `:125-129`. It is read at:
  - `repositories/task.py:118`
  - `repositories/mission_plan.py:63`
  - `services/mission_plan.py:210-224` (`set_plan_status`) and `:574-586`
  - `api/v1/endpoints/missions_plan.py:36,112-116`
  - `schemas/mission_plan.py:12,56`
  - `models/__init__.py:27,73`
  - clients: `mc_status.py:73-81`, `mc_plan.py:59`, `hooks/use-mission-plan.ts:27,66,134`, `plan-board-top-bar.tsx:52,65`, `mission-top-bar.tsx:43-44,96-105`.

  `mission_plan_dispatch.py:350` sat inside the inline-supervisor branch that 88.1.7 deleted. `check_plan_active` (`supervisor_activities.py`) reads plan status and is still called by `_supervise` (88.2.6).
- **Iteration columns.** `supervisor_iteration_count` and `max_supervisor_iterations` are at `models/mission_plan.py:167-188`.
- **Mission `PAUSED` is never set** with a reason (`models/mission.py:38`).
- **Any member can change status.** `MissionUpdate.status` (`schemas/mission.py:85`) lets any member set it.

**Change**
1. **Migration `plan88_005_lifecycle`** (`revision = "plan88_005"`, `down_revision = "plan88_004"`).
   - **`missions` columns.** Add `paused_reason VARCHAR(32) NULL`, `paused_at TIMESTAMPTZ NULL` and `paused_by_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL`.
   - **Backfill.** `UPDATE missions SET paused_reason = 'USER', paused_at = now() WHERE status = 'PAUSED'`.
   - **Constraint.** `ck_missions_pause_consistent CHECK ((status = 'PAUSED') = (paused_reason IS NOT NULL))`.
   - **Drop plan columns:** `mission_plans.status`, `supervisor_iteration_count` and `max_supervisor_iterations`.
   - `downgrade()` reverses the structure; restored `mission_plans.status` gets `server_default 'ACTIVE'`.
2. **Models.** Add `MissionPauseReason` (3.1.2) and the three columns to `Mission`. Delete `MissionPlanStatus`, its column and the two iteration columns, and remove them from `models/__init__.py`.
3. **Schemas.** `MissionResponse` gains `paused_reason: MissionPauseReason | None` and `paused_at: datetime | None` (serialised as lowercase values). Delete `MissionUpdate.status` (`schemas/mission.py:85`); `MissionUpdate` keeps `extra="forbid"`.
4. **Reader replacement rules.**
   - **`repositories/task.py:118`.** Replace the plan-status filter with `Mission.status != MissionStatus.ARCHIVED`, joining `Mission` on `Task.mission_id`.
   - **`repositories/mission_plan.py:63`.** Drop the `status=` argument.
   - **`services/mission_plan.py:210-224` `set_plan_status`.** Delete it.
   - **`services/mission_plan.py:574-586`.** If the mission is `ARCHIVED`, raise `ValidationError("Cannot add tasks to an archived mission")`. Delete the COMPLETED reactivation.
   - **`check_plan_active`** (`supervisor_activities.py`) returns `mission.status == MissionStatus.ACTIVE`: this step rewrites its body only. Its activity name and signature are unchanged, so the workflow is unchanged. 88.4.5 stops calling it under `p88-lifecycle-signals`; it is deleted in 88.4.5 only when no caller remains.
   - **`pause_all_autonomous_plans`** sets `missions.status = PAUSED`, `paused_reason = USER` and `paused_at = utc_now()` for every `ACTIVE` mission whose plan `gate_mode = GateMode.AUTONOMOUS`, instead of writing plan status. It stays because `admin.py:835` still calls it; 88.4.5 deletes it.
   - **`api/v1/endpoints/missions_plan.py:36,112-116`** and **`schemas/mission_plan.py:12,56`.** Delete status handling.
5. **Clients.**
   - `mc_status.py:73-81`: the plan line prints the mission status and, when paused, its `paused_reason`; delete the supervisor iteration count (it lives on runs: `mc runs show`). `mc_plan.py:59`: print the mission status.
   - `hooks/use-mission-plan.ts:27,66,134`: delete `MissionPlanStatus` and both `status` fields. `plan-board-top-bar.tsx:52`: `useLastSupervisorDecision(missionId, mission.status)` with `mission` from `useMission(missionId)`; `:65` reads `mission.status === 'paused'`.
   - `mission-top-bar.tsx:43-44,96-105`: delete `planRunning`, `planPaused` and the "Plan paused" link. Replace the "Plan running · done of total" pill with the active run's progress: `GET /missions/{id}/runs?status=running` (or the run detail) supplies `sequence`, `completed_task_count` and `task_count` from the backend, the pill reads "Run #{sequence} · {completed} of {total}", and nothing renders when no run is active. Delete `lib/plan-progress.ts` and move `plan-board-top-bar.tsx`'s count to the same run fields, so no client counts tasks. `types/mission.ts` gains `MissionPauseReason` (`'user' | 'budget_run_cap' | 'budget_monthly_cap' | 'budget_lifetime_cap' | 'gate_timeout'`), `paused_reason: MissionPauseReason | null` and `paused_at: string | null` on `MissionListItem`, and loses `status` from `MissionUpdateRequest` (`:47`).

**Tests**
- `tests/integration/backend/migrations/test_plan88_005.py`:
  - `test_paused_missions_get_user_reason`
  - `test_check_rejects_paused_without_reason`
- `tests/unit/backend/repositories/test_task_repository.py::test_pending_counts_exclude_archived_missions`.
- `tests/unit/backend/temporal/test_supervisor_activities.py::test_check_plan_active_reads_mission_status`: a `PAUSED` mission returns `False`.
- `tests/unit/backend/schemas/test_mission_schema.py::test_mission_update_rejects_status`: `extra="forbid"` raises.

**Done when**
- `rg -n "MissionPlanStatus|plan\.supervisor_iteration_count|mission_plans\.supervisor_iteration_count|max_supervisor_iterations|set_plan_status" modules --glob '!modules/backend/migrations/**'` returns nothing. The `PostRunEvalInput` and `GateContext` fields named `supervisor_iteration_count` stay and are not matched.
- The migration round-trips (`downgrade plan88_004`, `upgrade head`).
- `npm run build && npm run lint` in `modules/frontend` passes, and the tests pass.

---

### 88.4.3 Durable gate and notification schema (`plan88_006`, `plan88_007`)

**Files**
- create `modules/backend/migrations/versions/plan88_006_gate_requests_durable.py`, `modules/backend/migrations/versions/plan88_007_notifications.py`
- create `modules/backend/models/user_channel_identity.py`, `modules/backend/models/action_token.py`, `modules/backend/models/notification.py` (holding `MissionNotificationRecipient`, `NotificationDelivery`, `NotificationKind` and `NotificationDeliveryStatus`)
- create `modules/backend/repositories/user_channel_identity.py`, `action_token.py`, `mission_notification_recipient.py`, `notification_delivery.py`, `gate_request.py` (absent at baseline)
- modify `modules/backend/models/gate_request.py`, `modules/backend/models/__init__.py`, `modules/backend/migrations/env.py`, `modules/backend/services/mission.py`

**Current state**
- **Gate request status.** `GateRequestStatus` has PENDING, DECIDED, TIMED_OUT and CANCELLED (`models/gate_request.py:25-29`), stored by an `Enum(native_enum=False)` column with no explicit length (`:75-80`). There is no run link, no escalation timestamps and no decision channel; `timed_out_at` exists (`:99`).
- **Column naming.** The column holding the gate point is `gate_type` (`:64-69`).
- **No channel identity.** No channel identity, token or recipient tables exist.
- **Owner id type.** `missions.owner_id` is `String(200)` (`models/mission.py:75`), and the admin CLI passes free strings (`mission_cmds.py:97-102`).

**Change**
1. **Migration `plan88_006_gate_requests_durable`** (`revision = "plan88_006"`, `down_revision = "plan88_005"`).
   - **Columns:** add the 3.1.8 `gate_requests` columns (`mission_run_id` with FK and index, `task_id`, `escalate_at`, `pause_at`, `escalated_at`, `decision_channel`, `ai_recommendation_json`).
   - **Widen.** `ALTER COLUMN status TYPE VARCHAR(32)`.
   - **Legacy rows.** `UPDATE gate_requests SET status = 'CANCELLED' WHERE status IN ('PENDING','TIMED_OUT') AND mission_run_id IS NULL`.
   - **Model.** Add `ESCALATED` to `GateRequestStatus`, add `DecisionChannel` (3.1.2) and the new mapped columns. The column keeps the name `gate_type`; every DTO field named `gate_point` maps to it.
2. **Migration `plan88_007_notifications`** (`revision = "plan88_007"`, `down_revision = "plan88_006"`). Create the four tables in 3.1.10 with every named constraint, with two differences from the 3.1.10 text (contracts 3.1.10):
   - `user_channel_identities.verified_at` is `TIMESTAMPTZ NULL`; NULL means unconfirmed.
   - `user_channel_identities.external_username VARCHAR(64) NULL` holds the Telegram `@username` captured at redeem, so web and `mc` can show it before confirmation.

   Backfill the owner recipient rows with a module constant, never `get_app_config()`:
   ```python
   DEFAULT_KINDS_JSON = '["run_succeeded", "run_failed", "gate_waiting", "gate_escalated", "gate_timeout_paused", "budget_paused", "run_skipped", "run_missed"]'  # notifications.default_kinds at plan88_007
   ```
   ```sql
   INSERT INTO mission_notification_recipients (id, mission_id, user_id, channel, kinds, created_at, updated_at)
   SELECT gen_random_uuid(), m.id, u.id, 'TELEGRAM', CAST(:kinds AS jsonb), now(), now()
   FROM missions m JOIN users u ON u.id::text = m.owner_id
   ON CONFLICT ON CONSTRAINT uq_recipient DO NOTHING;
   ```
   The join on `u.id::text` skips owners that are not user ids without a cast error.
3. **Stored kinds.** `kinds` stores `NotificationKind` values (lowercase), as 3.1.10 states. It is a JSONB list of data, not an enum column. The service converts to and from `NotificationKind` members; API bodies and YAML use the same lowercase values (contracts 3.0.2).
4. **Repositories.** Implement exactly the methods in 3.5.2, plus:
   - `UserChannelIdentityRepository.get_verified_by_external(channel, external_id)`, `get_verified_for_user(user_id, channel)`, `get_for_user_by_id(user_id, identity_id)` and `delete_unverified(user_id, channel, external_id)`;
   - `MissionNotificationRecipientRepository.get_for_mission(mission_id, recipient_id)` (`WHERE id = :rid AND mission_id = :mid`).
   - **`ActionTokenRepository.consume`** is the single `UPDATE … RETURNING` in 3.5.1.
   - **`consume_siblings`** sets `consumed_at = now`, `consumed_action = 'SUPERSEDED'` and `consumed_ref = NULL` for every unconsumed token of that gate.
   - **`list_for_kind(mission_id, kind)`** filters `kinds ? :kind_value` (JSONB key existence on the lowercase value).
   - **`GateRequestRepository(BaseRepository[GateRequest])`** (`repositories/gate_request.py`) is created here with `has_undecided(mission_id) -> bool` (any row with `status IN ('PENDING','ESCALATED','TIMED_OUT')`) and `cancel_undecided(mission_id) -> int` (`UPDATE … SET status = 'CANCELLED' WHERE mission_id = :mid AND status IN ('PENDING','ESCALATED','TIMED_OUT')`, returning the row count). 88.4.5 uses both; 88.4.8 adds the decision methods.
5. **Create-mission default recipient.** `create_mission` inserts the owner `TELEGRAM` recipient with `kinds` from `notifications.default_kinds` only when `owner_id` is the id of an existing user (`UserRepository.get_by_id` after `uuid.UUID(owner_id)` parses; a `ValueError` counts as not a user). Otherwise it inserts no recipient and logs `mission.recipient_skipped` with `owner_id` at warning. Such a mission cannot run anyway (entry criterion 7).

**Tests**
- `tests/integration/backend/migrations/test_plan88_006.py::test_legacy_pending_gates_cancelled`.
- `tests/integration/backend/migrations/test_plan88_007.py`:
  - `test_owner_recipient_backfilled_once`
  - `test_non_uuid_owner_skipped`
  - `test_action_token_check_requires_gate_for_gate_decision`
  - `test_identity_verified_at_nullable`
- `tests/integration/backend/repositories/test_action_token_repository.py`:
  - `test_consume_single_use`: the second consume returns `None`.
  - `test_consume_rejects_expired`.
  - `test_consumed_ref_unique_blocks_replay`.
- `tests/integration/backend/repositories/test_gate_request_repository.py`:
  - `test_has_undecided_counts_escalated_and_timed_out`
  - `test_cancel_undecided_leaves_decided_rows`
- `tests/unit/backend/services/test_mission_service.py`:
  - `test_create_mission_adds_owner_telegram_recipient`
  - `test_create_mission_non_user_owner_no_recipient`

**Done when** both migrations round-trip (`downgrade plan88_005`, `upgrade head`) and the tests pass.

---

### 88.4.4 NotificationService, Telegram delivery, redaction and the `send_mission_notification` activity

**Files**
- create `modules/backend/services/notification.py`, `modules/backend/services/channel_identity.py`, `modules/backend/services/action_token.py`, `modules/backend/temporal/notification_activities.py`, `modules/backend/schemas/notification.py`, `modules/backend/api/v1/endpoints/missions_notifications.py`, `modules/clients/cli/mc_notify.py`, `modules/clients/cli/mc_groups/notify.py`
- modify `modules/backend/gateway/adapters/telegram.py`, `modules/backend/temporal/worker.py`, `modules/backend/temporal/human_input_activities.py`, `modules/backend/services/workflow_run_steps/io.py`, `modules/backend/services/workflow_run.py`, `modules/backend/core/config_schema.py`, `config/settings/notifications.yaml`, `modules/backend/events/mission_run_types.py`, `modules/backend/events/types.py` (`EVENT_TYPE_MAP`), `modules/backend/api/v1/endpoints/missions.py`, `mc.py` (group registration)
- delete `modules/backend/services/run_notifier.py`, `modules/clients/telegram/services/notifications.py` and its export from `modules/clients/telegram/services/__init__.py`, and `tests/unit/backend/services/test_run_notifier.py`

**Current state**
- **Broadcast delivery.** `RunNotifierService` sends to every entry in `application.telegram.authorized_users` (`run_notifier.py:206-247`, loop at `:235-237`).
- **Layering break.** It imports a client module from a backend service (`run_notifier.py:214`).
- **Other callers:** `_dispatch_to_channels` at `human_input_activities.py:92` and `workflow_run_steps/io.py:38`; `RunNotifierService` at `workflow_run.py:763-789`. The caller at `tasks/workflow_scheduler.py:150` was deleted with that module in 88.1.3.
- **Adapter capability.** `TelegramAdapter` (`gateway/adapters/telegram.py:23`) has only `deliver_response`. `get_adapter(channel_name)` is at `gateway/registry.py:49`.
- **Secrets in error text.** aiogram and aiohttp error strings can contain `https://api.telegram.org/bot<TOKEN>/…`. `redact_secrets` (88.1.6) covers schedule sync errors only; nothing redacts notification delivery errors before storage or SSE.

**Change**
1. **Config.** Replace `notifications.yaml` with 3.4.4 and `NotificationsSchema` (`config_schema.py:393`) with the 3.4.6 classes. `default_kinds` holds lowercase values (`[run_succeeded, run_failed, gate_waiting, gate_escalated, gate_timeout_paused, budget_paused, run_skipped, run_missed]`) and is typed `list[NotificationKind]`, imported from `models/notification.py`. The cross-file check `gate_decision_ttl_seconds >= gate.durable.pause_after_seconds` is added in 88.4.8, where `gate.durable` lands.
2. **Redaction.** `core/redaction.py` exists since 88.1.6 (pattern from 3.5.5), which already applies it to `mission_schedules.temporal_sync_error` and `MissionScheduleSyncFailedEvent.error`. This step imports `redact_secrets` and applies it to every stored `notification_deliveries.error` and to `NotificationDeliveryFailedEvent.error`. It does not create or change the module.
3. **`TelegramAdapter.send_notification`.**
   ```python
   async def send_notification(self, chat_id: int, text: str,
                               actions: list[tuple[str, str]] | None) -> str: ...
   ```
   - **Escaping.** HTML-escape `text` with `html.escape`, because the bot uses `ParseMode.HTML` (`clients/telegram/bot.py:46-49`).
   - **Truncation.** Truncate to `notifications.message_max_chars`.
   - **Actions.** Build an `InlineKeyboardMarkup` with one row of buttons from `actions` (label, callback_data).
   - **Return** `f"{chat_id}:{message.message_id}"`.
   - **Edit support.** Add `async def edit_notification(self, message_ref: str, text: str) -> None`, which edits the text and removes the keyboard.
4. **`NotificationService.notify(request)`.** For each recipient from `list_for_kind(mission_id, kind)`:
   1. **Dedupe.** `dedupe_key = f"{kind}:{subject_id}:{recipient_user_id}:{channel}"` with the lowercase kind value. `get_or_create(dedupe_key=dedupe_key, mission_id=request.mission_id, mission_run_id=request.mission_run_id, kind=kind, recipient_user_id=recipient.user_id, channel=recipient.channel)`. If the row status is `SENT`, skip it.
   2. **Disabled channel.** If `notifications.enabled` is false, or `channels.telegram.enabled` is false, or `get_adapter("telegram") is None`, set `SKIPPED_DISABLED`.
   3. **No identity.** `identity = await ChannelIdentityService(session).get_for_user(recipient.user_id, ChannelKind.TELEGRAM)`, which returns only confirmed identities (`verified_at IS NOT NULL`, item 10). If it is `None`, set `SKIPPED_NO_IDENTITY`.
   4. **Action buttons.** Added only for `GATE_WAITING`, `GATE_ESCALATED` and `GATE_TIMEOUT_PAUSED`, and only when all three hold:
      - `inbound_approvals_enabled` is true;
      - `MissionService.is_operator(mission, user)` is true for the recipient now;
      - `request.gate_request_id` is set.

      Each button carries a fresh token from `ActionTokenService.issue(purpose=ActionTokenPurpose.GATE_DECISION, user_id=recipient.user_id, channel=ChannelKind.TELEGRAM, gate_request_id=request.gate_request_id, ttl_seconds=notifications.action_tokens.gate_decision_ttl_seconds)`. Approve is `("Approve", f"g:{token}:a")` and Reject is `("Reject", f"g:{token}:r")`. Store `channel_message_ref` on both tokens after sending. Both services are created in item 10 of this step.
   5. **Send.** `ref = await adapter.send_notification(int(identity.external_id), text, actions)` and increment `attempt_count`.
      - **On success:** `SENT`, `sent_at`, `provider_message_ref = ref`.
      - **On exception:** `FAILED`, `error = redact_secrets(str(exc))`, emit `NotificationDeliveryFailedEvent` with the redacted error, and continue with the next recipient. After all recipients, raise `ExternalServiceError(f"{failed} notification deliveries failed")` when any failed, so the activity retry covers the failed recipients only (the dedupe makes `SENT` rows no-ops).
   6. **SSE.** Publish the payload to Redis `notify:mission:{mission_id}`, moving the logic from `run_notifier.py:160-205`.

   **Message text** is built by `_render(kind, payload)` in the same module, with one fixed template per kind. It always includes the mission name, run sequence, status and cost. For `RUN_SUCCEEDED` and `RUN_FAILED` it also states the digest generator.
5. **`send_ad_hoc(mission_id, title, body, level) -> None`.** Replaces `_dispatch_to_channels` for `human_input_activities.py:92` and `workflow_run_steps/io.py:38`, and `RunNotifierService` for `workflow_run.py:763-789`. It publishes SSE and sends Telegram to the mission's TELEGRAM recipients with confirmed identities. It writes no `notification_deliveries` row and has no dedupe; failures are logged with `redact_secrets` applied and never raised. `notify_budget_warning` is deleted with no replacement; caps are enforced in 88.4.6.
6. **Recipients.** `list_recipients`, `add_recipient` and `remove_recipient`, following 3.5.1.
   - **Request body.** `NotificationRecipientCreate{user_email: str, channel: ChannelKind, kinds: list[NotificationKind] | None}`, values lowercase. The service resolves `user_email` with `UserRepository.get_by_email`; an unknown email raises `NotFoundError`.
   - **Membership.** `add_recipient` checks the user is the owner or a mission member, else `ValidationError`.
   - **Kinds.** `kinds` defaults to `notifications.default_kinds`; stored as lowercase values (88.4.3).
   - **Scoping.** `remove_recipient(mission_id, recipient_id, actor_id)` loads with `get_for_mission(mission_id, recipient_id)` (`WHERE id = :rid AND mission_id = :mid`), else `NotFoundError`.
   - **Response.** `NotificationRecipientResponse{id, user_id, user_email, channel, kinds}`.
7. **Activity.** `send_mission_notification(request: NotificationRequest) -> list[str]` in `temporal/notification_activities.py` opens a session and calls `NotificationService.notify`. Register it in `worker.py`. The workflows start calling it in 88.4.5.
8. **API and mc.** `missions_notifications.py` adds the three recipient endpoints from 3.5.3 (GET access; POST and DELETE `require_mission_owner`); include it in `api/v1/endpoints/missions.py`. `mc notify recipients list|add EMAIL [--kind K]…|remove EMAIL` calls them; `remove` finds the recipient id by `user_email` in the list response. Register the `notify` group in `mc.py`.
9. **Event.** Add `NotificationDeliveryFailedEvent` (3.6.1).
10. **Identity and token services.**
    - **`ChannelIdentityService` (`services/channel_identity.py`).** Create it with `get_for_user(user_id, channel)` and `resolve(channel, external_id)`. Both return confirmed rows only (`verified_at IS NOT NULL`), via `UserChannelIdentityRepository.get_verified_for_user` and `get_verified_by_external` (88.4.3), else `None`. 88.4.9 adds the linking methods.
    - **`ActionTokenService` (`services/action_token.py`).** Create it with `issue(*, purpose, user_id, channel, gate_request_id, ttl_seconds) -> str` (3.5.1): `raw = base64.urlsafe_b64encode(secrets.token_bytes(16)).rstrip(b"=").decode()`; store `hashlib.sha256(raw.encode()).hexdigest()` with `expires_at = utc_now() + timedelta(seconds=ttl_seconds)`; return `raw`. Raw tokens are never logged. 88.4.9 adds `consume`.

**Tests**
- `tests/unit/backend/services/test_notification_service.py`:
  - `test_notify_dedupes_on_sent`: the second call sends nothing.
  - `test_notify_skips_without_identity`: status `SKIPPED_NO_IDENTITY`.
  - `test_notify_skips_unconfirmed_identity`: an identity with `verified_at IS NULL` gives `SKIPPED_NO_IDENTITY`.
  - `test_notify_disabled_channel_skips`.
  - `test_gate_waiting_buttons_only_for_operators_with_inbound_enabled`.
  - `test_failed_recipient_reraises_after_others_sent`.
  - `test_delivery_error_redacts_bot_token`: the adapter raises with `https://api.telegram.org/bot123:ABC-def/sendMessage` in the message; the stored `error` and the event contain `<redacted>` and not `123:ABC-def`.
  - `test_message_html_escaped_and_truncated`.
  - `test_publishes_sse_channel`.
- `tests/unit/backend/services/test_action_token_service.py::test_issue_returns_22_char_raw_and_stores_hash_only`.
- `tests/unit/backend/services/test_channel_identity_service.py::test_resolve_ignores_unconfirmed`.
- `tests/unit/backend/gateway/test_telegram_adapter.py`:
  - `test_send_notification_returns_chat_message_ref`
  - `test_callback_data_under_64_bytes`
- `tests/integration/backend/api/test_missions_notifications.py`:
  - `test_add_recipient_non_member_rejected`
  - `test_add_recipient_by_email`
  - `test_remove_recipient_owner_only`
  - `test_remove_other_missions_recipient_404`
  - `test_kinds_accept_lowercase_values`
- `tests/unit/clients/cli/test_mc_notify.py::test_recipients_add_calls_endpoint`.

**Done when**
- `rg -n "run_notifier|RunNotifierService|_dispatch_to_channels" modules --glob '!modules/backend/migrations/**'` returns nothing.
- The tests pass.

---

### 88.4.5 MissionLifecycleService, cancel and pause reaching Temporal

**Files**
- create `modules/backend/services/mission_lifecycle.py`, `modules/backend/api/v1/endpoints/missions_lifecycle.py`
- modify `modules/backend/services/mission.py`, `modules/backend/services/mission_plan.py`, `modules/backend/services/mission_run.py`, `modules/backend/api/v1/endpoints/admin.py`, `modules/backend/api/v1/endpoints/executions.py`, `modules/backend/api/v1/endpoints/missions.py`, `modules/backend/temporal/mission_run_workflow.py`, `modules/backend/temporal/mission_schedule_tick_workflow.py`, `modules/backend/temporal/mission_run_activities.py`, `modules/backend/temporal/mission_run_models.py`, `modules/backend/temporal/versioning.py`, `modules/backend/temporal/worker.py`, `modules/backend/events/mission_run_types.py`, `modules/backend/events/types.py` (`EVENT_TYPE_MAP`)
- modify `modules/clients/cli/mc_mission.py`, `modules/clients/cli/mc_groups/mission.py`, `modules/clients/cli/mission_cmds.py`
- create `tests/fixtures/temporal_histories/mission_run/p88-lifecycle-signals.json`; modify `tests/unit/backend/temporal/test_replay_histories.py`

**Current state**
- **Archive is a status write.** `archive_mission` and `unarchive_mission` (`services/mission.py:465-477`) only write status. `mission_cmds.py:248-260` calls the service in-process. `mc_mission.py:146-169` PATCHes `status`, which 88.4.2 removed.
- **No mc pause or resume.** `mc_groups/mission.py` has no `pause` or `resume` command.
- **Cancel.** `MissionRunService.cancel_run` (88.1.7) raises `ConflictError` on a terminal run and has no NOT_FOUND or unreachable handling. `POST /executions/{id}/cancel` goes through `ExecutionCancellationService` (88.0.9), which marks an ExecutionRecord cancelled without touching its `mission_runs` row.
- **Emergency stop is plan-based.** `admin.py:835` calls `pause_all_autonomous_plans` (`services/mission_plan.py:226-245`), which 88.4.2 rewrote to pause missions directly.
- **Mission delete** reaches Temporal since 88.0.9 and 88.1.11; this step does not change it.

**Change**
1. **Operator rule.** `MissionService.is_operator` and `require_mission_operator` exist since 88.0.9. Apply `require_mission_operator` to `POST /missions/{id}/pause` and `/resume` below. No other route changes here.
2. **`MissionLifecycleService`** (3.5.1, side effects as 3.2.2):
   - **`pause_mission(mission_id, *, reason, user_id)`.** Calls `_apply_pause`, commits, calls `MissionScheduleService.sync_mission(mission_id)`, then, when `reason == MissionPauseReason.USER` and the active run is `RUNNING` or `AWAITING_GATE`, signals `request_pause`. It emits `MissionLifecycleChangedEvent` and sends no notification (callers send `BUDGET_PAUSED` and `GATE_TIMEOUT_PAUSED`).
   - **`_apply_pause(self, mission: Mission, reason: MissionPauseReason, user_id: str | None) -> None`** sets `status = PAUSED` and the `paused_*` columns and flushes, with no commit and no Temporal call. `claim_occurrence` uses it inside its transaction (88.4.6).
   - **`resume_mission(mission_id, user_id: str | None)`.**
     - **Preconditions.** `ConflictError` when `paused_reason == GATE_TIMEOUT` and `GateRequestRepository.has_undecided(mission_id)` (88.4.3) is true (`gate_requests.status IN ('PENDING','ESCALATED','TIMED_OUT')`). `ConflictError` naming the cap value (for example `budget_monthly_cap`) when `BudgetService.mission_cap_breach(get_status(mission_id))` is not `None`.
     - **Pause slots.** Before clearing the pause, save `paused_at = mission.paused_at` and `now = utc_now()` to locals. For each `ACTIVE` schedule of the mission (`MissionScheduleRepository.list_by_mission(mission_id, include_archived=False)` filtered to `status == MissionScheduleStatus.ACTIVE`, each locked with `MissionScheduleRepository.lock(schedule_id)`), call `TemporalScheduleGateway.list_matching_times(sched.temporal_schedule_id, paused_at, now)` (Temporal `ListScheduleMatchingTimes`). For each `t` with `paused_at < t <= now` that has no row (`MissionRunRepository.get_by_slot(schedule_id, t)`), insert `MISSED/NOT_FIRED` with `insert_occurrence(..., sequence=await increment_run_sequence(mission_id))`, exactly as 88.1.6 allocates sequences. Then set `sched.last_claimed_scheduled_for = now`. No pause-interval table exists. Schedule-level pause slots are not recorded, because `resume_schedule` resets the watermark (88.1.6).
     - **Effects.** In the same transaction as the pause slots, clear `status` and `paused_*`; commit; `sync_mission(mission_id)`; then signal `resume` to the active run whatever its status. Emit `MissionLifecycleChangedEvent`. The gateway call runs with the schedule row locks held, the same deliberate exception as `claim_occurrence` (88.1.6).
   - **`archive_mission` and `unarchive_mission`** follow 3.2.2 rows 4 and 5. Archive cancels the active run through `MissionRunService.cancel_run(..., reason=MissionRunStatusReason.MISSION_ARCHIVED)` and sets undecided gate requests to `CANCELLED` with `GateRequestRepository.cancel_undecided(mission_id)` (88.4.3).
   - **Signal mechanics.** `gateway = await TemporalWorkflowGateway.connect()`, then `await gateway.signal(mission_run_workflow_id(run_id), "request_pause", PauseRequest(requested_by_user_id=user_id, reason=reason.value))` and `await gateway.signal(mission_run_workflow_id(run_id), "resume", ResumeRequest(requested_by_user_id=user_id))`. A `WorkflowState.NOT_FOUND` result is logged and ignored, because the reconciler owns orphans. `ExternalServiceError` from the gateway propagates after the DB commit; the DB state stands and the run picks up the mission state at its next boundary.
   - **Emergency stop.** `async def pause_all_active(self, user_id: str) -> int` calls `pause_mission(reason=MissionPauseReason.USER, user_id=user_id)` for every `ACTIVE` mission whose plan `gate_mode = GateMode.AUTONOMOUS`. `admin.py:809-845` calls it; its docstring states that running runs pause at their next layer boundary. Delete `MissionPlanService.pause_all_autonomous_plans` (`services/mission_plan.py:226-245`).
   - **Delete** `MissionService.archive_mission` and `unarchive_mission` (`services/mission.py:465-477`).
3. **`MissionRunService.cancel_run(mission_id, run_id, user_id, reason)`** replaces the 88.1.7 body and changes its semantics in two ways: a terminal run is a no-op (88.1.7 raised `ConflictError`), and a `PENDING` run whose workflow has not begun is cancelled through the workflow (88.1.7 transitioned it to `CANCELLED` directly).
   1. **Lock and check.** `SELECT … FROM mission_runs WHERE id = :run_id AND mission_id = :mission_id FOR UPDATE`; no row raises `NotFoundError`. A terminal run is returned unchanged.
   2. **Record the request.** If `cancel_requested_at IS NULL`, set it, `cancel_requested_by_user_id` and `cancel_reason`. Save `run_id` and `status` to locals, then commit.
   3. **Cancel in Temporal.** `gateway = await TemporalWorkflowGateway.connect()`, then `state = await gateway.cancel(mission_run_workflow_id(run_id))`. When `state == WorkflowState.NOT_FOUND`:
      - **PENDING:** `transition(run_id, CANCELLED, cancel_reason, "cancelled before start")` and commit.
      - **Otherwise:** reload the run (the commit expired it), then `await RunMemoryService(self._session, event_bus=self._event_bus).write_digest(run_id, status=MissionRunStatus.CANCELLED, reason=run.cancel_reason, narrator=None)` (`MissionRunStatus.CANCELLED` is the value `"cancelled"`; `narrator=None` makes the digest deterministic), then `finalise(run_id, CANCELLED, cancel_reason, "workflow not found at cancel")`.
   4. **Temporal unreachable.** The gateway raises `ExternalServiceError` on any other `RPCError` or connection error, and it propagates. The DB keeps `cancel_requested_at`, so a later begin or the reconciler honours it.
   5. **Late start.** `begin` checks `cancel_requested_at IS NOT NULL` first: it transitions `PENDING → CANCELLED` with `cancel_reason`, commits and raises `RunStartRejectedError("run cancelled before start")` (88.1.7, in `NON_RETRYABLE`). The workflow's begin handler (88.1.8) checks `_cause_type(e) == "RunStartRejectedError"` and returns `"failed"` without calling `_end_run`. This is existing 88.1.8 behaviour and needs no patch.
4. **Execution cancel.** In `executions.py` `cancel_execution` (exists since 88.0.9), when `record.mission_run_id` is set, delegate to `MissionRunService.cancel_run(record.mission_id, record.mission_run_id, user_id, MissionRunStatusReason.CANCELLED_BY_USER)` and return its status. Records without `mission_run_id` keep the 88.0.9 `ExecutionCancellationService` path.
5. **Workflow (`mission_run_workflow.py`), patch id `p88-lifecycle-signals`.** The handlers touch only the `@workflow.init` fields (contracts 3.3.3):
   ```python
   @workflow.signal
   def request_pause(self, req: PauseRequest) -> None:
       self._pause_requested = True

   @workflow.signal
   def resume(self, req: ResumeRequest) -> None:
       self._pause_requested = False
       if self._state is None or self._state.pending_gate is None:
           self._paused = False

   async def _pause_point(self) -> None:
       if not workflow.patched("p88-lifecycle-signals") or not self._pause_requested:
           return
       await _exec(set_mission_run_status,
                   RunStatusUpdate(self._input.mission_run_id, "paused", "user_pause", None), self._input.config.persistence)
       self._paused = True
       paused_at = workflow.now()
       await workflow.wait_condition(lambda: not self._paused)
       self._state.excluded_wait_seconds += int((workflow.now() - paused_at).total_seconds())
       await _exec(set_mission_run_status,
                   RunStatusUpdate(self._input.mission_run_id, "running", None, None), self._input.config.persistence)
   ```
   - **Supervisor loop.** In `_supervise`, wrap the `check_plan_active` call in `if not workflow.patched("p88-lifecycle-signals"):`; pause now arrives through `request_pause`. `check_plan_active` is deleted in this step only when no caller remains. The unpatched branch still calls it, so the function (body rewritten by 88.4.2) and its `worker.py` registration stay for executions on the old branch.
   - `_layer_boundary()` (88.2.6) calls `await self._pause_point()` first, before the duration check. A layer boundary is reached only after the previous chunk's `execute_plan_task` futures have resolved, so in-flight tasks finish before the run pauses.
   - **Notifications.** Add `_notify`, the only way the workflow sends a notification; a failure is logged and never propagated (contracts 3.3.3):
     ```python
     async def _notify(self, req: NotificationRequest) -> None:
         try:
             await _exec(send_mission_notification, req, self._input.config.notify)
         except ActivityError as e:
             workflow.logger.warning("notification failed", extra={"kind": req.kind, "cause": _cause_type(e)})
     ```
     In `_end_run`, after `finalise_mission_run` returns `result`, run `await self._notify(result.notification)` when `workflow.patched("p88-lifecycle-signals")`. In `MissionScheduleTickWorkflow` (3.3.2 step 3, which 88.1.8 replaced with a log line), send each returned notification the same way under the same patch id, before the child start.
   - A `resume` that arrives before the boundary clears `_pause_requested`, so the run never pauses.
   - Cancellation needs no change here: the 88.1.8 handler runs `_end_run`, and `finalise` uses `run.cancel_reason`. In-flight `execute_plan_task` activities (`WAIT_CANCELLATION_COMPLETED`, 88.2.4) mark their task `FAILED` with `failure_reason="cancelled"`.
   - Follow the patch rule: add `p88-lifecycle-signals` to `PATCH_IDS`, record `p88-lifecycle-signals.json` from a run that pauses and resumes once, and add it to `REQUIRED`.
6. **Activity `pause_mission_for_run(input: PauseForRunInput) -> None`** in `mission_run_activities.py`, with `PauseForRunInput(mission_run_id: str, reason: str)` (a lowercase `MissionPauseReason` value, 3.0.2) added to `temporal/mission_run_models.py`. It loads the run's mission and calls `MissionLifecycleService.pause_mission(mission_id, reason=MissionPauseReason(input.reason), user_id=None)`. If the mission is already `PAUSED` or `ARCHIVED`, it returns without change. Register it in `worker.py`. 88.4.6 and 88.4.8 call it.
7. **Endpoints (`missions_lifecycle.py`),** included in `api/v1/endpoints/missions.py`:
   - `POST /missions/{id}/pause` and `/resume` (`require_mission_operator`);
   - `POST /missions/{id}/archive` and `/unarchive` (`require_mission_owner`).

   `POST /missions/{id}/runs/{run_id}/cancel` exists since 88.1.12 and now reaches the new `cancel_run`.
8. **Events.** Add `MissionLifecycleChangedEvent` (3.6.1).
9. **Clients.**
   - **mc.** Add `mc mission pause` and `mc mission resume` to `mc_groups/mission.py`, posting to the new routes. Rewrite `archive` and `unarchive` (`mc_mission.py:146-169`) to POST. `mc runs cancel SEQ` exists since 88.1.13.
   - **Admin.** `mission_cmds.py:248-260` calls `MissionLifecycleService(session).archive_mission` in-process.
   - **Web** controls arrive in 88.4.10.

**Tests**
- `tests/unit/backend/services/test_mission_lifecycle.py`:
  - `test_pause_sets_columns_commits_then_syncs`: call order asserted with a mocked gateway.
  - `test_pause_user_signals_running_run`.
  - `test_pause_user_signals_awaiting_gate_run`.
  - `test_pause_sends_no_notification`.
  - `test_resume_signals_running_run_with_pending_pause`: the run is `RUNNING`; `resume` is signalled.
  - `test_resume_rejects_gate_timeout_with_undecided_gate`.
  - `test_resume_allows_gate_timeout_without_undecided_gate`.
  - `test_resume_rejects_when_monthly_cap_breached`: the `ConflictError` message contains `budget_monthly_cap`.
  - `test_resume_advances_watermark_to_now`: after resume, every `ACTIVE` schedule of the mission has `last_claimed_scheduled_for` equal to the resume time.
  - `test_archive_archives_schedules_deletes_temporal_cancels_run_cancels_gates`.
  - `test_unarchive_leaves_schedules_archived_mission_paused_user`.
  - `test_pause_all_active_only_autonomous`.
- `tests/integration/backend/services/test_mission_lifecycle_schedules.py::test_mission_pause_slots_backfilled`: an hourly schedule; the mission is paused at T and resumed at T+5h. `resume_mission` records `MISSED/NOT_FIRED` for every matching slot in `(T, T+5h]`, each with its own sequence, and the tick for T+6h records exactly one RUN and no further `MISSED` row. Every slot during a mission pause is `MISSED/NOT_FIRED`.
- `tests/unit/backend/services/test_mission_run_cancel.py`:
  - `test_cancel_terminal_is_noop`
  - `test_cancel_other_missions_run_404`
  - `test_cancel_pending_not_found_transitions_cancelled`
  - `test_cancel_pending_unstarted_run_goes_through_workflow`: a `PENDING` run with `started_at IS NULL` and a live workflow stays `PENDING` with `cancel_requested_at` set, and `gateway.cancel` is awaited.
  - `test_cancel_running_calls_handle_cancel`
  - `test_temporal_unreachable_keeps_request_and_raises`
  - `test_begin_honours_cancel_requested`: `begin` raises `RunStartRejectedError` and the run is `CANCELLED`.
- **88.1.7 test updates** in `tests/integration/backend/services/test_mission_run_service.py`, made in this commit because the semantics change:
  - Delete `test_cancel_pending_unstarted_run_is_immediate`; its expectation (immediate `CANCELLED` without Temporal) no longer holds, and `test_cancel_pending_unstarted_run_goes_through_workflow` above replaces it.
  - Any 88.1.7 assertion that `cancel_run` raises `ConflictError` on a terminal run is changed to assert the run is returned unchanged (`test_cancel_terminal_is_noop`).
  - `test_cancel_other_missions_run_404` is unchanged.
- `tests/unit/backend/temporal/test_mission_run_lifecycle_workflow.py`, using `WorkflowEnvironment.start_time_skipping()` and stub activities:
  - `test_pause_waits_for_inflight_layer_then_pauses`: two tasks in flight finish before `set_mission_run_status(PAUSED)`.
  - `test_resume_before_boundary_cancels_pause`.
  - `test_resume_continues_next_layer`.
  - `test_signal_before_begin_completes`: `request_pause` sent before `begin_mission_run` returns does not fail the workflow task.
  - `test_cancel_runs_digest_then_finalise_cancelled`.
  - `test_run_end_notification_sent`: `send_mission_notification` runs after `finalise_mission_run`.
  - `test_notify_failure_does_not_fail_run`: `send_mission_notification` raises on every attempt; the run still ends `SUCCEEDED`.
- `tests/integration/backend/temporal/test_mission_schedule_tick_workflow.py::test_tick_sends_skip_notification`.
- `tests/integration/backend/api/test_missions_lifecycle.py`:
  - `test_viewer_cannot_pause`
  - `test_maintainer_can_pause`
  - `test_maintainer_cannot_archive`
  - `test_execution_cancel_delegates_to_run`
- `tests/unit/backend/temporal/test_replay_histories.py` passes with `p88-lifecycle-signals` in `REQUIRED`.

**Done when**
- `rg -n "def archive_mission|def unarchive_mission" modules/backend/services/mission.py` and `rg -n "pause_all_autonomous_plans" modules --glob '!modules/backend/migrations/**'` return nothing.
- The tests pass.

---

### 88.4.6 Budget enforcement in runs, claims and agent execution

**Files**
- modify `modules/backend/temporal/mission_run_activities.py`, `modules/backend/temporal/mission_run_workflow.py`, `modules/backend/temporal/mission_run_models.py`, `modules/backend/temporal/task_activities.py`, `modules/backend/temporal/versioning.py`, `modules/backend/temporal/worker.py`, `modules/backend/agents/mission_control/helpers/agent_executor.py`, `modules/backend/agents/mission_control/gate.py`, `modules/backend/temporal/supervisor_activities.py`, `modules/backend/services/mission_schedule.py`, `modules/backend/services/mission_schedule_claim.py`, `modules/backend/services/mission_run.py`, `modules/backend/temporal/run_memory_activities.py`, `modules/backend/events/mission_run_types.py`, `modules/backend/events/types.py` (`EVENT_TYPE_MAP`)
- create `tests/fixtures/temporal_histories/mission_run/p88-budget-caps.json`; modify `tests/unit/backend/temporal/test_replay_histories.py`

**Current state**
- **No budget point in the run.** Phase 2 (88.2.6) and Phase 3 contain no budget branch. `ExecuteTaskInput.budget_headroom_usd` carries the Phase 2 value.
- **The executor's spend counter guards nothing.** `cumulative_cost_usd` in `_make_agent_executor` (`agent_executor.py:52-70`) has no guard.
- **Gate LLM calls are not recorded.** `LlmGateReviewer.review` records no ledger row (`gate.py:94-125`), has the hardcoded default model `"copilot:claude-haiku-4.5"` (`gate.py:51`), and swallows every exception into ABORT (`:115-125`).
- **Digest generator choice** (88.3.7) ignores the budget.
- **`claim_occurrence` has no budget rule** (88.1.6).

**Change**
1. **Activity `check_run_budget(mission_run_id: str) -> BudgetCheckResult`** in `mission_run_activities.py` calls `BudgetService.check_run`. `breach` is the lowercase `MissionPauseReason` value or `None` (3.0.2). Register it in `worker.py`.
2. **Agent-level guard.** `_make_agent_executor` gains `budget_headroom_usd: float | None` (it has `mission_run_id` and `task_id` since 88.2.3).
   - **Before each agent call:** if `budget_headroom_usd is not None and cumulative_cost_usd >= budget_headroom_usd`, raise `BudgetExceededError(f"task headroom {budget_headroom_usd:.4f} exhausted")`.
   - **After recording the ledger row:** the same check, then raise.
   - **Accepted overshoot.** It is bounded to one LLM call per task.
3. **`execute_plan_task`.**
   - It passes `ExecuteTaskInput.budget_headroom_usd` to `build_dispatch_runtime` and from there to the executor.
   - `BudgetExceededError` raised by the executor guard is handled by the 88.2.3b machinery.
     - **Classification.** The retry handler's classifier maps it to `control(FailureClass.BUDGET_EXCEEDED, "budget_exceeded")` (contracts 3.8.3 step 1). The class is never retryable, so the task ends at once.
     - **Recording.** `execute_plan_task` records the failed `TaskResult` like any other failure. The `tasks` row gets `failure_reason="budget_exceeded"` and the enum members `CONTROL` and `BUDGET_EXCEEDED`.
     - **Result.** It returns `ExecuteTaskResult(status="failed", failure_reason="budget_exceeded", failure_origin="control", failure_class="budget_exceeded", ...)`.
     - **No retry.** Nothing is raised, so Temporal never retries the task.

     The workflow's chunk check compares `failure_class == "budget_exceeded"`. `failure_reason` is redacted in committed replay histories (88.2.9), so no workflow branch reads it (contracts 3.8.1 item 5).
4. **Workflow budget points, patch id `p88-budget-caps`.** `self._headroom_usd: float | None = None` is set in `__init__` (it is not handler-owned).
   ```python
   async def _budget_point(self) -> str | None:
       if not workflow.patched("p88-budget-caps"):
           return None
       check = await _exec(check_run_budget, self._input.mission_run_id, self._input.config.persistence)
       self._headroom_usd = check.headroom_usd
       if check.breach is None:
           return None
       return await self._budget_stop(check.breach)

   async def _budget_stop(self, breach: str) -> str:
       status = await self._end_run("budget_stopped", breach, None)
       await _exec(pause_mission_for_run, PauseForRunInput(self._input.mission_run_id, breach), self._input.config.persistence)
       await self._notify(NotificationRequest(
           kind="budget_paused", mission_id=self._input.mission_id, mission_run_id=self._input.mission_run_id,
           gate_request_id=None, subject_id=self._input.mission_run_id, payload={"cap": breach},
       ))
       return status
   ```
   - **Checkpoints.** `_layer_boundary()` calls `_budget_point()` after `_pause_point()` and the duration check, so it runs before the first layer and before each chunk.
   - **Headroom split.** Each chunk of n tasks passes `budget_headroom_usd = None if self._headroom_usd is None else self._headroom_usd / n`.
   - **After a chunk.** When `workflow.patched("p88-budget-caps")` and any result has `failure_class == "budget_exceeded"`, run `check_run_budget` once and return `await self._budget_stop(check.breach or "budget_run_cap")`. The chunk's other futures have already resolved, and no new task starts.
   - **`_notify`** exists since 88.4.5.
   - **`finalise`.** For status `BUDGET_STOPPED`, `MissionRunService.finalise` emits `MissionRunBudgetBreachedEvent(cap=reason, spent_usd=…, cap_usd=…)`, taking the spend and cap that match the reason from `BudgetService.get_status`. `_end_run` (88.3.8) already writes a deterministic digest for `BUDGET_STOPPED`.
   - Follow the patch rule: add `p88-budget-caps` to `PATCH_IDS`, record `p88-budget-caps.json` from a run stopped by a run cap, and add it to `REQUIRED`.
5. **Claim rule.** In `MissionScheduleService.claim_occurrence` (`services/mission_schedule_claim.py`, 88.1.6), insert the 3.3.2 rule "monthly or lifetime cap breached" between the `max_runs` rule and RUN:
   - **Record the skip.** `breach = BudgetService.mission_cap_breach(await BudgetService(session).get_status(mission_id))`. When it is not `None`, insert `SKIPPED/BUDGET_CAP_REACHED` through the same savepoint and sequence path as the other SKIPPED outcomes (contracts 3.3.3).
   - **Pause in the same transaction.** `await MissionLifecycleService(session)._apply_pause(mission, breach, None)`.
   - **Notify.** Append `NotificationRequest(kind="budget_paused", mission_id=mission_id, mission_run_id=None, gate_request_id=None, subject_id=f"{schedule_id}:{scheduled_for.isoformat()}", payload={"cap": breach.value})` to the result; the tick workflow sends it under `p88-lifecycle-signals` (88.4.5 item 5).
   - **Sync after commit.** The `claim_occurrence` activity calls `MissionScheduleService.sync_mission(mission_id)` after the commit when the claim paused the mission.
6. **Digest budget conditions.** The budget-aware narrator choice lives in the `write_run_digest` activity (`temporal/run_memory_activities.py`, 88.3.7), not in `RunMemoryService.write_digest`, whose signature `write_digest(run_id, *, status, reason, narrator)` is unchanged. The activity opens its session, calls `check = await BudgetService(db).check_run(input.mission_run_id)`, and passes `narrator=generate_digest_narrative` only when `not input.force_deterministic`, `check.breach is None` and `check.headroom_usd >= registry.get(digest.agent_name).max_budget_usd`; otherwise it passes `narrator=None`, which makes the digest `DETERMINISTIC`.
7. **Gate LLM spend.**
   - **Required constructor arguments.** `LlmGateReviewer.__init__` takes `model`, `temperature` and `max_tokens` with no defaults (`gate.py:49-53`). `ConfigurableGate._get_llm` (`gate.py:157-165`) already passes config.
   - **Run context.** `GateContext` gains `mission_run_id: str | None` and `session_id: str | None`. After `agent.run`, `review` calls:
     ```python
     await record_llm_call(
         session_id=context.session_id,
         mission_id=context.mission_id,
         agent_name="gate.reviewer",
         agent_role="gate",
         model=self.model_name,
         usage=result.usage(),
         cost_usd=compute_cost_usd(usage.input_tokens, usage.output_tokens, self.model_name),
         latency_ms=0,
         tool_count=0,
         mission_run_id=context.mission_run_id,
         task_id=None,
     )
     ```
     with `usage = result.usage()` assigned first.
   - **Failure.** The `except Exception` at `gate.py:115-125` narrows to `(ProviderError, ValidationError)`, and the ABORT stays. Ledger failures propagate.
   - **Supervisor.** `evaluate_post_run` records any LLM call of `AutonomousPostRunReviewer` (`_classify_with_haiku`, `gate_post_run.py:343`) the same way, with `agent_name="gate.post_run"`.

**Tests**
- `tests/unit/backend/agents/mission_control/test_agent_executor_budget.py`:
  - `test_raises_before_call_when_headroom_exhausted`
  - `test_raises_after_call_that_crosses_headroom_and_row_recorded`
- `tests/unit/backend/temporal/test_task_activities_budget.py::test_budget_exceeded_marks_task_failed_without_retry`.
- `tests/unit/backend/temporal/test_mission_run_budget_workflow.py` (time-skipping):
  - `test_breach_before_layer_stops_without_dispatch`: `execute_plan_task` is never called.
  - `test_breach_mid_layer_waits_inflight_then_budget_stopped`.
  - `test_breach_calls_digest_then_finalise_then_pause_then_notify`: activity order asserted.
  - `test_headroom_split_across_parallel_batch`.
  - `test_budget_notify_failure_does_not_fail_run`: `send_mission_notification` raises on every attempt; the workflow still returns `"budget_stopped"`.
- `tests/unit/backend/services/test_mission_schedule_claim_budget.py`:
  - `test_monthly_breach_skips_and_pauses_and_returns_notification`
  - `test_sync_called_after_commit_not_inside`: the mock asserts `session.in_transaction()` is false at sync.
- `tests/unit/backend/temporal/test_run_memory_activities_budget.py` (`write_digest` patched to capture its kwargs):
  - `test_budget_breach_forces_deterministic`: `narrator` is `None`.
  - `test_insufficient_headroom_forces_deterministic`: `narrator` is `None`.
  - `test_headroom_sufficient_passes_narrator`.
- `tests/unit/backend/agents/mission_control/test_gate_llm_ledger.py`:
  - `test_gate_review_records_llm_call`
  - `test_llm_gate_reviewer_requires_model`
- `tests/unit/backend/temporal/test_replay_histories.py` passes with `p88-budget-caps` in `REQUIRED`.

**Done when**
- The tests pass.
- `rg -n '"copilot:claude-haiku-4.5"' modules --glob '!modules/backend/migrations/**'` returns nothing.

---

### 88.4.7 Schedule end date and max runs completion

**Files**
- modify `modules/backend/services/mission_schedule.py`, `modules/backend/temporal/reconciler_activities.py`, `modules/backend/events/types.py`

**Current state:** 88.1.6 delivers `claim_occurrence` with `MAX_RUNS_REACHED` completion (3.3.2 rule 3). `END_DATE_REACHED` and `COMPLETED → ACTIVE` reactivation (3.2.3) are owned here.

**Change**
1. **Complete expired schedules.** In `sync_all`, before syncing, select schedules with `status IN ('ACTIVE','PAUSED') AND ends_at IS NOT NULL AND ends_at < now()`. For each one:
   1. set `COMPLETED/END_DATE_REACHED`;
   2. commit;
   3. call `TemporalScheduleGateway.delete`;
   4. emit `MissionScheduleChangedEvent`.
2. **Reactivate on update.** In `update_schedule`, when `status == COMPLETED` and either `(completed_reason == MAX_RUNS_REACHED and (new max_runs is None or new max_runs > executed_run_count))` or `(completed_reason == END_DATE_REACHED and (new ends_at is None or new ends_at > now))`, set `ACTIVE`, clear `completed_reason`, commit, and call `sync_to_temporal`, which recreates the schedule.
3. **Archive.** `archive_schedule` sets `ARCHIVED`, commits and deletes the Temporal schedule. This holds from any status except `ARCHIVED`, which raises `ConflictError`.

**Tests**
- `tests/unit/backend/services/test_mission_schedule_completion.py`:
  - `test_sync_all_completes_end_date_and_deletes_temporal`
  - `test_update_raising_max_runs_reactivates`
  - `test_update_future_end_date_reactivates`
  - `test_update_completed_without_relief_stays_completed`
  - `test_archive_archived_conflict`

**Done when** the tests pass.

---

### 88.4.8 Durable gates: GateDecisionService, activities and the workflow gate

**Files**
- create `modules/backend/services/gate_decision.py`, `modules/backend/temporal/gate_activities.py`, `modules/backend/temporal/gate_vocabulary.py`
- modify `modules/backend/temporal/mission_run_workflow.py`, `modules/backend/temporal/mission_run_models.py`, `modules/backend/temporal/mission_run_activities.py`, `modules/backend/temporal/worker.py`, `modules/backend/temporal/versioning.py`, `modules/backend/temporal/workflow_gateway.py` (`execute_update`), `modules/backend/temporal/config_snapshots.py` (`build_run_config_snapshot`), `modules/backend/services/mission_lifecycle.py`, `modules/backend/services/run_memory.py`, `modules/backend/services/mission_plan.py`, `modules/backend/services/attention.py`, `modules/backend/repositories/gate_request.py` (exists since 88.4.3)
- modify `modules/backend/agents/mission_control/gate.py`, `modules/backend/agents/mission_control/gate_post_run.py`, `modules/backend/core/config_schema.py`, `modules/backend/core/config.py`, `modules/backend/core/dependencies.py`, `config/settings/gate.yaml`, `modules/backend/events/mission_run_types.py`, `modules/backend/events/types.py` (`EVENT_TYPE_MAP`), `modules/backend/api/v1/endpoints/missions_gates.py`, `modules/backend/schemas/` (the module defining `GateRequestSummary` and `GateRequestDetail`)
- modify `modules/clients/cli/mc_gate.py`, `modules/clients/cli/api_client.py`, `modules/clients/cli/admin_groups/workflow.py`
- modify `modules/frontend/src/lib/api.ts`, `modules/frontend/src/hooks/use-gates.ts`, `modules/frontend/src/components/mission/active-run-card.tsx`
- delete `modules/backend/agents/mission_control/gate_manual.py`, `tests/unit/backend/agents/mission_control/test_gate_manual.py`, `modules/clients/cli/gate.py` (`CliGateReviewer`, used only by `gate.py:167-175`)
- create `tests/fixtures/temporal_histories/mission_run/p88-durable-gate.json`; modify `tests/unit/backend/temporal/test_replay_histories.py`

**Current state**
- **Process-local manual gate.** After 88.0.13, `gate_manual.py` polls the DB for a decision inside the process that runs the dispatch loop. Since 88.2.6 no Temporal path runs it; only in-process callers can. The post-run manual branch is `gate_post_run.py:87-101`.
- **Gate seam.** `MissionRunWorkflow._gate(point, task_id)` returns `"continue"` (88.2.6); `verification_failed`, `post_task` and `post_layer` call it.
- **Durable pattern.** The signal, `wait_condition` and escalation-timer pattern lives in the deleted `AgentMissionWorkflow`; read it at `a28ca771:modules/backend/temporal/workflow.py` (`_wait_for_approval_with_escalation`, `:187-245`).
- **Unknown modes.** 88.0.5 changed the unknown-mode branch (`gate.py:282-286`) to ABORT. The `interactive` branch (`gate.py:262-263`) and the `ai_assisted` branch (`:268-271`) use `CliGateReviewer`, imported from a client at `gate.py:169`. The `manual` branch is `:265-266` with `_get_manual` at `:177-196`.
- **Vocabulary.** 88.0.13 moved the action check into `MissionPlanService.allowed_gate_actions`, with the standard set `{continue, skip, retry, abort}` and the post-run set `{wait, advance_approved, advance_refine, propose_complete, escalate}`. Both differ from 3.3.6. `mc_gate.py:43-56` duplicates a third version client-side.
- **Gate queries in the plan service.** `MissionPlanService.list_pending_gate_requests`, `get_gate_request`, `get_pending_gate_request`, `record_gate_decision`, `create_gate_request`, `mark_gate_request_timed_out` and `mark_gate_request_cancelled` (`services/mission_plan.py:250-375`) serve `missions_gates.py` and `gate_manual.py`. `services/attention.py:50` calls `list_pending_gate_requests`.
- **Decision channel.** `RequestContextMiddleware` reads `X-Frontend-ID` into `request.state.source` (`core/middleware.py:56-63`), but neither the `mc` API client (`clients/cli/api_client.py:83-86`) nor the web `api` wrapper (`frontend/src/lib/api.ts:63-65`) sends it.
- **Web.** `use-gates.ts` (88.0.13) exports `useGateRequest` and `useDecideGate`. `active-run-card.tsx` finds a pending gate only from live `gate.request.opened` events, so a gate opened before the page loaded is invisible.

**Change**
1. **Config.** In `gate.yaml`, replace `manual:` with `durable:` (3.4.3), and update the mode comments so that `manual` reads "durable human decision via web, mc or Telegram". Replace `class GateManualSchema` (`core/config_schema.py`, `:611-620` at `a28ca771`; locate by symbol), including the `poll_interval_seconds` 88.0.2 added, and the `GateSchema.manual` field with `GateDurableSchema` as `GateSchema.durable`. In `AppConfig.__init__` add the cross-file check `notifications.action_tokens.gate_decision_ttl_seconds >= gate.durable.pause_after_seconds`. `build_run_config_snapshot()` (`temporal/config_snapshots.py`, 88.1.5) fills `gate_escalate_after_seconds` and `gate_pause_after_seconds` from `gate.durable.*` instead of `temporal.approval_timeout_seconds` and `escalation_timeout_seconds`.
2. **Mode set.** `AUTO_APPROVE_GATE_MODES` is unchanged since 88.1.0. Add `test_auto_approve_modes_autonomous_only` asserting `AUTO_APPROVE_GATE_MODES == frozenset({GateMode.AUTONOMOUS})`.
3. **Vocabulary (`temporal/gate_vocabulary.py`).** A pure module with no imports beyond the standard library, used by the workflow and the service:
   ```python
   GATE_ACTIONS: dict[str, tuple[str, ...]] = {
       "pre_dispatch": ("continue", "abort"),
       "pre_layer": ("continue", "abort"),
       "post_task": ("continue", "abort"),
       "post_layer": ("continue", "abort"),
       "verification_failed": ("retry", "skip", "abort"),
       "post_run": ("advance_approved", "advance_refine", "propose_complete", "abort"),
   }


   def allowed_actions(gate_point: str) -> tuple[str, ...]:
       return GATE_ACTIONS[gate_point]


   def telegram_action(gate_point: str, short_action: str, recommended_action: str | None) -> str:
       if short_action == "r":
           return "abort"
       if gate_point == "verification_failed":
           return "retry"
       if gate_point != "post_run":
           return "continue"
       if recommended_action is None:
           raise ValueError("post_run gate has no recommended action")
       return recommended_action
   ```
   Delete `MissionPlanService.allowed_gate_actions` with the two action sets 88.0.13 moved into it, `_validate_action_for_gate_type` (`missions_gates.py:268`; the decide path calls `allowed_actions` inside `GateDecisionService.decide` instead), and `VALID_ACTIONS_BY_GATE` (`mc_gate.py:43-56`).
4. **`ConfigurableGate` (in-process paths only: `admin_groups/workflow.py:82` and the dispatch loop's in-process callers).**
   - Delete the `interactive`, `manual` and `ai_assisted` branches, `_get_cli`, `_get_manual`, the `console`, `verbose` and `session_factory` parameters of `ConfigurableGate.__init__` and `create_gate`, and the `modules.clients.cli.gate` import (contracts 3.0.2). Delete `modules/clients/cli/gate.py`.
   - Validate `effective_mode` with `GateMode(effective_mode)`. A `ValueError` raises `ValidationError(f"unknown gate mode {effective_mode!r}")` (`core/exceptions.py`), replacing the 88.0.5 ABORT branch. Start rejection uses `RunStartRejectedError` (88.1.7).
   - `MANUAL`, `AI_ASSISTED` and `INTERACTIVE` raise `ValidationError("human gates run only inside MissionRunWorkflow")`. `AUTONOMOUS` keeps the auto-rule then `LlmGateReviewer` path.
   - `admin_groups/workflow.py:66-71`: the `--gate` choices become `["off", "autonomous"]`.
5. **Post-run supervisor.** Delete the manual branch at `gate_post_run.py:87-101`. `evaluate_post_run` returns the supervisor's action, and the workflow gates it (item 9).
6. **`GateDecisionService` (`services/gate_decision.py`), following 3.5.1 with these additions.**
   - **`get(mission_id, gate_request_id) -> GateRequest`** loads `WHERE id = :gid AND mission_id = :mid`, else `NotFoundError`. It replaces `MissionPlanService.get_gate_request`.
   - **`list_open(mission_ids) -> list[GateRequest]`** returns statuses PENDING, ESCALATED and TIMED_OUT, oldest first. It replaces `list_pending_gate_requests`; `services/attention.py:50` calls it.
   - **`evaluate(data: EvaluateGateInput) -> EvaluateGateResult`.** The mode is `run.gate_mode`, loaded from the run (the workflow does not pass it).
     - **`post_run`** (`data.recommended_action` set, no LLM call): `AUTONOMOUS` gives `human_required=False` and `action = recommended_action`. `MANUAL` and `AI_ASSISTED` give `human_required=True`, `action = recommended_action`, `recommendation_json = {"action": recommended_action}`.
     - **Other points.** The `GateContext` is built from the run's tasks: `pending_tasks` from `TaskRepository.list_by_run(run_id, APPROVED)`, plus the `task_result` and `verification` of `task_id`, with `mission_run_id` and `session_id` set.
     - **`AUTONOMOUS`.** `should_auto_continue(context, rules)` (moved out of `ConfigurableGate._should_auto_continue` into a module function in `gate.py`) gives `continue`. Otherwise `LlmGateReviewer.review`; when its action is in `allowed_actions(point)`, `human_required=False` with that action; when it is not, `human_required=True` with `recommendation_json = {"action": action, "reason": reason}`.
     - **`AI_ASSISTED`.** `LlmGateReviewer.review`, then `human_required=True` with `recommendation_json = {"action": action, "reason": reason}`.
     - **`MANUAL`.** `human_required=True`, `recommendation_json=None`, no LLM call.
     - **Anything else.** `MissionRunStateError(f"run {run_id} has gate mode {mode!r}")`, which is in `NON_RETRYABLE`. `begin` already rejects such modes with `RunStartRejectedError` (88.1.7), so this branch guards an invariant only.
   - **`open_gate(data: OpenGateInput) -> GateRequest`.** `INSERT … ON CONFLICT (id) DO NOTHING RETURNING id` with `id = data.gate_request_id`, `mission_id`, `mission_run_id`, `task_id`, `gate_type = data.gate_point`, `context_json`, `escalate_at`, `pause_at` and `ai_recommendation_json`. When a row was inserted and `data.human_required`, it transitions the run to `AWAITING_GATE` and emits `GateRequestOpenedEvent`. On conflict (an activity retry) it does neither. It commits and issues no tokens and no notification.
   - **`mark_status(id, status)`** runs `UPDATE gate_requests SET status = :s, escalated_at|timed_out_at = now() WHERE id = :id AND status IN ('PENDING','ESCALATED')` and emits `GateRequestEscalatedEvent` or `GateRequestTimedOutEvent` only when a row changed.
   - **`close(id, status, decision)`** runs `UPDATE … WHERE id = :id AND status IN ('PENDING','ESCALATED','TIMED_OUT')` and writes `decision_json`, `decision_channel`, `decided_at` and `decided_by_user_id`. When `decision.channel == "workflow"`, `decided_by_user_id` is `mission.owner_id`, a user id by entry criterion 7, never an agent name (`pattern_agent_tool_user_id`). It then calls `ActionTokenRepository.consume_siblings(id, now)` and emits `GateRequestDecidedEvent` (channel and `mission_run_id` included). It is idempotent.
   - **`decide(mission_id, gate_request_id, *, action, reason, user_id, channel)`** follows 3.3.3 ordering exactly:
     1. Lock with `SELECT … WHERE id = :gid AND mission_id = :mid FOR UPDATE`; no row raises `NotFoundError`. Validate the gate can be decided (3.2.4); otherwise `ConflictError`.
     2. `action not in allowed_actions(row.gate_type)` raises `ValidationError`.
     3. `gateway = await TemporalWorkflowGateway.connect()`, then `await gateway.execute_update(mission_run_workflow_id(row.mission_run_id), "decide_gate", GateDecisionUpdate(gate_request_id, action, reason, user_id, channel.value), rpc_timeout=timedelta(seconds=temporal.mission_run.activities.persistence.start_to_close_seconds))`.
     4. On acceptance, write `DECIDED` and commit.
     5. The gateway raises `ConflictError` on `WorkflowUpdateFailedError` or `RPCError` NOT_FOUND; `decide` lets it propagate and rolls back, so the DB is unchanged.

     It does not resume a `GATE_TIMEOUT` mission; the workflow does (item 9).
   - **Audit trail.** Identical for every channel: the `gate_requests` row (`decided_by_user_id`, `decision_channel`, `decision_json`, `decided_at`), `GateRequestDecidedEvent`, and `logger.info("gate.decided", extra={"gate_request_id": gid, "mission_id": mission_id, "mission_run_id": run_id, "action": action, "channel": channel.name, "user_id": user_id})`.
   - **Delete** the seven gate methods from `MissionPlanService` (`services/mission_plan.py:250-375`).
   - **Repository.** `GateRequestRepository` exists since 88.4.3 (`has_undecided`, `cancel_undecided`). This step adds `get_for_mission(mission_id, gate_request_id)`, `lock_for_mission(mission_id, gate_request_id)` (`FOR UPDATE`), `list_open(mission_ids)`, `list_decided_for_run(mission_run_id)`, `insert_if_absent(...)` (`ON CONFLICT (id) DO NOTHING RETURNING id`), `mark_status(gate_request_id, status, now)` and `close(gate_request_id, status, decision, now)`. `GateDecisionService` reaches `gate_requests` only through it, and `MissionLifecycleService.resume_mission` and `resume_mission_for_run` use `has_undecided` for the undecided-gate check. 88.5.7 adds `pending_summary`.
   - **Gateway.** Add `async def execute_update(self, workflow_id: str, name: str, payload: object, rpc_timeout: timedelta) -> object` to `TemporalWorkflowGateway` (`temporal/workflow_gateway.py`, 88.0.3), the only place that opens a `MissionRunWorkflow` handle. It calls `execute_update` on the workflow handle, raises `ConflictError` on `WorkflowUpdateFailedError` or `RPCError` NOT_FOUND, and raises `ExternalServiceError` on any other `RPCError`. No module outside the two gateways calls `start_workflow` or `get_workflow_handle` for `MissionRunWorkflow`, `MissionScheduleTickWorkflow`, `ReconcilerWorkflow` or `RetentionWorkflow`.
7. **Activities.**
   - `gate_activities.py`: `evaluate_gate`, `open_gate_request`, `update_gate_request` and `close_gate_request` (3.3.5), each opening a session and calling the service. None of them sends a notification.
   - `mission_run_activities.py`: `resume_mission_for_run(mission_run_id: str) -> bool` loads the run's mission. When the mission is `PAUSED` with `paused_reason == GATE_TIMEOUT` and has no undecided gate, it calls `MissionLifecycleService.resume_mission(mission_id, user_id=None)` and returns `True`. A `ConflictError` naming a cap is logged as `mission.resume_after_gate_blocked` and returns `False`; the mission stays `PAUSED/GATE_TIMEOUT`, which `resume_mission` accepts once caps allow, and the run's next `check_run_budget` stops it. Any other state returns `False`.
   - Register all five in `worker.py`.
8. **Digest decisions.** `RunMemoryService.write_digest` (88.3.7 omitted `decisions`) fills `decisions` from the run's `DECIDED` gate requests as `{gate_request_id, gate_point: gate_type, action: decision_json["action"], channel: decision_channel value, decided_by_user_id}`.
9. **Workflow gate, patch id `p88-durable-gate`.** `_exec`, `_cause_type`, `_end_run` and the `@workflow.init` fields (`self._input`, `_approved_seq`, `_pause_requested`, `_paused`, `_decision`) are those of 88.1.8; the run id is `self._input.mission_run_id` and the config snapshot is `self._input.config`.
   ```python
   @workflow.update
   def decide_gate(self, upd: GateDecisionUpdate) -> GateDecisionAck:
       self._decision = upd
       return GateDecisionAck(gate_request_id=upd.gate_request_id, accepted=True)

   @decide_gate.validator
   def _validate_decide_gate(self, upd: GateDecisionUpdate) -> None:
       pending = None if self._state is None else self._state.pending_gate
       if pending is None or upd.gate_request_id != pending.gate_request_id:
           raise ApplicationError("gate is not pending", non_retryable=True)
       if self._decision is not None:
           raise ApplicationError("gate already decided", non_retryable=True)
       if upd.action not in allowed_actions(pending.gate_point):
           raise ApplicationError(f"action {upd.action!r} not allowed at {pending.gate_point}",
                                  non_retryable=True)

   def _gate_notice(self, kind: str, gid: str, point: str) -> NotificationRequest:
       return NotificationRequest(kind=kind, mission_id=self._input.mission_id, mission_run_id=self._input.mission_run_id,
                                  gate_request_id=gid, subject_id=gid, payload={"gate_point": point})

   async def _wait_decision(self, timeout: timedelta) -> bool:
       try:
           await workflow.wait_condition(lambda: self._decision is not None, timeout=timeout)
       except asyncio.TimeoutError:
           pass
       return self._decision is not None

   async def _gate(self, point: str, task_id: str | None, recommended: str | None = None) -> str:
       if not workflow.patched("p88-durable-gate"):
           return "continue"
       if not self._input.config.gate_points_enabled[point]:
           return "continue" if recommended is None else recommended
       ev = await _exec(evaluate_gate,
                        EvaluateGateInput(mission_run_id=self._input.mission_run_id, gate_point=point, task_id=task_id,
                                          recommended_action=recommended),
                        self._input.config.evaluate_gate)
       if not ev.human_required:
           if ev.action != "continue" and point != "post_run":
               await self._record_workflow_decision(point, task_id, ev)
           return ev.action
       return await self._human_gate(point, task_id, ev)

   async def _record_workflow_decision(self, point: str, task_id: str | None, ev: EvaluateGateResult) -> None:
       gid = str(workflow.uuid4())
       await _exec(open_gate_request,
                   OpenGateInput(gate_request_id=gid, mission_run_id=self._input.mission_run_id, gate_point=point,
                                 task_id=task_id, context_json={"reason": ev.reason},
                                 recommendation_json=ev.recommendation_json, escalate_at=None, pause_at=None,
                                 human_required=False),
                   self._input.config.persistence)
       await _exec(close_gate_request,
                   CloseGateInput(gate_request_id=gid, status="decided",
                                  decision=GateDecisionUpdate(gate_request_id=gid, action=ev.action,
                                                              reason=ev.reason, decided_by_user_id=None,
                                                              channel="workflow")),
                   self._input.config.persistence)

   async def _human_gate(self, point: str, task_id: str | None, ev: EvaluateGateResult) -> str:
       gid = str(workflow.uuid4())
       opened = workflow.now()
       escalate = timedelta(seconds=self._input.config.gate_escalate_after_seconds)
       pause = timedelta(seconds=self._input.config.gate_pause_after_seconds)
       self._decision = None
       await _exec(open_gate_request,
                   OpenGateInput(gate_request_id=gid, mission_run_id=self._input.mission_run_id, gate_point=point,
                                 task_id=task_id,
                                 context_json={"recommended_action": ev.action, "reason": ev.reason},
                                 recommendation_json=ev.recommendation_json,
                                 escalate_at=opened + escalate, pause_at=opened + pause, human_required=True),
                   self._input.config.persistence)
       self._state.pending_gate = PendingGate(gate_request_id=gid, gate_point=point, task_id=task_id,
                                              opened_at=opened, escalated=False, timed_out=False)
       await self._notify(self._gate_notice("gate_waiting", gid, point))
       if not await self._wait_decision(escalate):
           await _exec(update_gate_request, UpdateGateInput(gate_request_id=gid, status="escalated"),
                       self._input.config.persistence)
           self._state.pending_gate.escalated = True
           if self._decision is None:
               await self._notify(self._gate_notice("gate_escalated", gid, point))
           if not await self._wait_decision(pause - escalate):
               await _exec(update_gate_request, UpdateGateInput(gate_request_id=gid, status="timed_out"),
                           self._input.config.persistence)
               if self._decision is None:
                   self._state.pending_gate.timed_out = True
                   await _exec(set_mission_run_status,
                               RunStatusUpdate(self._input.mission_run_id, "paused", "gate_timeout", None),
                               self._input.config.persistence)
                   await _exec(pause_mission_for_run, PauseForRunInput(self._input.mission_run_id, "gate_timeout"),
                               self._input.config.persistence)
                   await self._notify(self._gate_notice("gate_timeout_paused", gid, point))
                   await workflow.wait_condition(lambda: self._decision is not None)
       decision = self._decision
       timed_out = self._state.pending_gate.timed_out
       await _exec(close_gate_request, CloseGateInput(gate_request_id=gid, status="decided", decision=decision),
                   self._input.config.persistence)
       self._state.pending_gate = None
       self._decision = None
       self._state.excluded_wait_seconds += int((workflow.now() - opened).total_seconds())
       if timed_out:
           await _exec(resume_mission_for_run, self._input.mission_run_id, self._input.config.persistence)
       if decision.action != "abort":
           await _exec(set_mission_run_status, RunStatusUpdate(self._input.mission_run_id, "running", None, None),
                       self._input.config.persistence)
       return decision.action
   ```
   - **Re-checks.** Every timeout is followed by a check of `self._decision` before escalating or pausing, and again after the `TIMED_OUT` activity, so a decision that races the timer never pauses the mission. `mark_status` is guarded in SQL, so a `DECIDED` row is never overwritten.
   - **`_end_run`.** Before compaction, when `self._state is not None and self._state.pending_gate is not None and workflow.patched("p88-durable-gate")`, run `close_gate_request(CloseGateInput(gate_request_id=self._state.pending_gate.gate_request_id, status="cancelled", decision=None))` and clear `pending_gate`. The cancellation handler reaches this through `_end_run`.
   - **Gate points.** Under the patch:
     - `pre_dispatch` runs before the first layer when `self._state.iteration == 1`;
     - `pre_layer` runs before each layer, after `_layer_boundary()`;
     - `post_task` and `verification_failed` keep their 88.2.6 call sites; `retry` and `skip` keep their 88.2.6 handling;
     - `post_layer` runs after each layer;
     - `post_run` runs in `_supervise` after `evaluate_post_run`: `wait` goes to the idle wait with no gate, `escalate` ends the run with `await self._end_run("failed", "supervisor_escalated", None)`, and any other action becomes `await self._gate("post_run", None, decision.action)`, whose result is then routed.
   - **`abort`** from any gate ends the run with `await self._end_run("cancelled", "gate_rejected", None)`; the digest is deterministic for `CANCELLED` (88.3.8).
   - **Continue-as-new** stays skipped while `pending_gate is not None` (88.2.7).
   - **Replay.** The unpatched branch of `_gate` keeps the 88.2.6 `"continue"` return, so histories recorded before this step replay unchanged. `_notify` exists since 88.4.5.
   - Follow the patch rule: add `p88-durable-gate` to `PATCH_IDS`, record `p88-durable-gate.json` from a MANUAL run whose `pre_dispatch` gate escalates and is then decided, and add it to `REQUIRED`.
10. **Mode check.** `begin_mission_run` rejects `INTERACTIVE`, NULL or unknown modes with `FAILED/INVALID_GATE_MODE` and raises `RunStartRejectedError` (88.1.7). This step asserts it in a test.
11. **API.**
    - **`decide`** (`missions_gates.py:176-255`, operator-only since 88.0.13) calls `GateDecisionService.decide(..., channel=channel)`. The channel comes from a new `RequestSource` dependency in `core/dependencies.py` that reads `request.state.source`: `web` gives `DecisionChannel.WEB`, `cli` gives `CLI`, anything else gives `API`. The header is client-asserted, so it labels the audit record only and never feeds an authorisation decision. The response data is `{id, action, run_status}` with lowercase values.
    - **`GET /missions/{id}/gates/pending`** (`missions_gates.py:109-140`) calls `GateDecisionService.list_open([mission_id])` and returns `GateRequestSummary` with `mission_run_id`, `gate_point`, `status`, `escalate_at`, `pause_at` and `allowed_actions`.
    - **`GET /missions/{id}/gates/{gid}`** (`:142-174`) calls `GateDecisionService.get`; `allowed_actions` comes from `allowed_actions(row.gate_type)`.
12. **Clients.**
    - **Headers.** `clients/cli/api_client.py:83-86` constructs `httpx.AsyncClient(..., headers={"X-Frontend-ID": "cli"})`. `frontend/src/lib/api.ts:63-65` adds `'X-Frontend-ID': 'web'` to the headers object.
    - **mc.** `decide` and `pending` (`mc_gate.py:148-222`) render `allowed_actions` from the server.
    - **Web.** `use-gates.ts` (exists since 88.0.13) adds `usePendingGates(missionId)`, which GETs `/missions/${missionId}/gates/pending` with query key `['missions', missionId, 'gates', 'pending']`; `useDecideGate` invalidates that key on success. `active-run-card.tsx` takes the oldest entry of `usePendingGates(missionId)` instead of scanning live events, and passes its `id` as `requestId` to `GateApproval` (props unchanged since 88.0.13). `live-results-panel.tsx` keeps the 88.0.13 event store.

**Tests**
- `tests/unit/backend/models/test_gate_mode.py::test_auto_approve_modes_autonomous_only`.
- `tests/unit/backend/temporal/test_gate_vocabulary.py`:
  - `test_actions_match_contract_table`
  - `test_telegram_approve_post_run_uses_recommendation`
  - `test_telegram_reject_is_abort`
- `tests/unit/backend/services/test_gate_decision_service.py`:
  - `test_decide_rejects_action_outside_vocabulary`
  - `test_decide_other_missions_gate_404`
  - `test_decide_conflict_when_update_rejected_db_unchanged`
  - `test_decide_conflict_when_workflow_closed`
  - `test_decide_commits_after_ack`
  - `test_decide_does_not_resume_mission`
  - `test_open_gate_retry_single_row`: two `open_gate` calls with the same id give one row and one `AWAITING_GATE` transition.
  - `test_mark_status_never_overwrites_decided`
  - `test_close_idempotent_and_consumes_sibling_tokens`
  - `test_close_workflow_channel_uses_owner_user_id`
  - `test_decide_rejects_legacy_gate_without_run`
  - `test_evaluate_unknown_mode_raises`
  - `test_evaluate_ai_assisted_requires_human_with_recommendation`
  - `test_evaluate_autonomous_disallowed_action_requires_human`
  - `test_evaluate_post_run_autonomous_applies_recommendation`
- `tests/unit/backend/temporal/test_mission_run_gate_workflow.py` (time-skipping, stub activities):
  - `test_manual_gate_escalates_then_pauses_then_decision_resumes`: activity order is `update_gate_request(ESCALATED)`, `update_gate_request(TIMED_OUT)`, `set_mission_run_status(PAUSED)`, `pause_mission_for_run`, then after the update `close_gate_request(DECIDED)`, `resume_mission_for_run` and `set_mission_run_status(RUNNING)`.
  - `test_decision_racing_timeout_resumes_mission`: the update arrives while the `update_gate_request(TIMED_OUT)` stub is running; neither `set_mission_run_status(PAUSED)` nor `pause_mission_for_run` runs.
  - `test_decision_after_pause_resumes_mission`: the update arrives after `pause_mission_for_run`; `resume_mission_for_run` runs after `close_gate_request`.
  - `test_notify_failure_does_not_fail_run`: `send_mission_notification` always raises; the gate still completes on decision.
  - `test_update_validator_rejects_wrong_gate_id`.
  - `test_abort_cancels_with_gate_rejected`.
  - `test_autonomous_non_continue_recorded_as_workflow_channel`.
  - `test_disabled_point_skips_evaluate`.
  - `test_no_continue_as_new_while_gate_pending`.
  - `test_cancel_closes_pending_gate`.
  - `test_worker_restart_mid_gate_replays`: run, stop worker, start new worker, send update, completes.
- `tests/unit/backend/services/test_run_memory_digest.py::test_decisions_listed_from_decided_gates`.
- `tests/integration/backend/services/test_mission_run_activities.py`:
  - `test_resume_for_run_resumes_gate_timeout_mission`
  - `test_resume_for_run_noop_when_user_paused`
- `tests/unit/backend/agents/mission_control/test_gate.py`:
  - `test_unknown_mode_raises_validation_error`
  - `test_manual_mode_rejected_outside_workflow`
  - `test_ai_assisted_mode_rejected_outside_workflow`
- `tests/integration/backend/api/test_missions_gates.py`:
  - `test_decide_requires_operator`
  - `test_decide_records_channel_from_frontend_id`
  - `test_pending_includes_allowed_actions`
- `tests/unit/backend/services/test_mission_run_begin.py::test_begin_rejects_interactive_mode`: the run is `FAILED/INVALID_GATE_MODE` and `RunStartRejectedError` is raised.
- `tests/unit/backend/temporal/test_workflow_gateway.py::test_execute_update_maps_failures`: `WorkflowUpdateFailedError` and `RPCError` NOT_FOUND give `ConflictError`; any other `RPCError` gives `ExternalServiceError`.
- `tests/unit/clients/cli/test_mc_gate.py`:
  - `test_decide_uses_server_allowed_actions`
  - `test_client_sends_frontend_id_cli`
- `tests/unit/backend/temporal/test_replay_histories.py` passes with `p88-durable-gate` in `REQUIRED`.

**Done when**
- `rg -n "gate_manual|ManualGateReviewer|CliGateReviewer|clients\.cli\.gate|VALID_ACTIONS_BY_GATE|allowed_gate_actions|_validate_action_for_gate_type|list_pending_gate_requests|defaulting to CONTINUE" modules --glob '!modules/backend/migrations/**'` returns nothing. `defaulting to CONTINUE` is absent since 88.0.5 made the unknown gate action in `gate_prompt.py` fail closed to ABORT.
- `rg -n "start_workflow|get_workflow_handle" modules --glob '!modules/backend/temporal/workflow_gateway.py' --glob '!modules/backend/temporal/schedule_gateway.py' --glob '!modules/backend/migrations/**' | rg -i "MissionRun|MissionScheduleTick|Reconciler|Retention|mission_run_workflow_id"` returns nothing. Other workflows (chat, tool fork, plan refine, human input, workflow-run) are out of scope.
- `cd modules/frontend && npm run build && npm run lint` passes.
- The tests pass.

---

### 88.4.9 Telegram identity linking (two-step) and inbound Approve/Reject

**Files**
- create `modules/backend/api/v1/endpoints/auth_channels.py`, `modules/backend/schemas/channel_identity.py`, `modules/clients/telegram/callbacks/gate.py`, `modules/clients/telegram/handlers/gate.py`, `modules/clients/telegram/handlers/link.py`
- modify (exists since 88.4.4) `modules/backend/services/channel_identity.py`, `modules/backend/services/action_token.py`
- modify `modules/backend/services/gate_decision.py`, `modules/clients/telegram/handlers/setup.py`, `modules/clients/telegram/bot.py`, `modules/clients/telegram/webhook.py`, `modules/clients/cli/mc_notify.py`, `modules/clients/cli/mc_groups/notify.py`, `modules/backend/api/v1/__init__.py`

**Current state**
- **Allowlist and webhook secret.** Both fail closed since 88.0.14 (`middlewares/auth.py`, `webhook.py:58`).
- **Handlers cover only the basics.** `/start`, `/help`, `/cancel` and `/status` (`handlers/setup.py:24-26`).
- **Rate limiting exists.** `RateLimitMiddleware` is registered for `callback_query` (`middlewares/setup.py:36`), in memory and per process.
- **Webhook logging.** The debug log at `webhook.py:73-83` records `update_id`, `update_type` and the sender id, and not the callback data.

**Change**
1. **`ActionTokenService.consume`** (3.5.1; `issue` exists since 88.4.4).
   - **Consume.**
     - **`expected_user_id` mismatch:** `AuthorizationError`, checked first with `SELECT … FOR UPDATE` on the hash.
     - **Zero rows from the `UPDATE … RETURNING`:** `ConflictError("Action expired or already used")`.
   - **Logging.** Raw tokens are never logged.
2. **`ChannelIdentityService`** (3.5.1 plus contracts 3.1.10; `get_for_user` and `resolve` exist since 88.4.4) gains `create_link_code`, `redeem_link_code`, `confirm_identity`, `list_identities` and `unlink`:
   - **`create_link_code(user_id, channel) -> tuple[str, datetime]`** issues an `ActionToken(purpose=CHANNEL_LINK, ttl=channel_link_ttl_seconds)` and returns the raw token and its expiry.
   - **`redeem_link_code(channel, external_id, external_username, code, ref) -> UserChannelIdentity`:**
     1. `int(external_id) in application.telegram.authorized_users`, else `AuthorizationError`;
     2. consume the token with `expected_user_id=None`; the identity belongs to `token.user_id`;
     3. a confirmed identity for `(token.user_id, channel)` or `(channel, external_id)` raises `ConflictError("Telegram account already linked")`;
     4. `delete_unverified(token.user_id, channel, external_id)` removes stale unconfirmed rows for that user or that Telegram account;
     5. insert the identity with `verified_at = NULL`, `external_id` and `external_username`.
   - **`confirm_identity(user_id, identity_id) -> UserChannelIdentity`** loads with `get_for_user_by_id` (`WHERE id = :iid AND user_id = :uid`), else `NotFoundError`. A confirmed row is returned unchanged. A row older than `channel_link_ttl_seconds` raises `ConflictError("Link expired; request a new code")`. Otherwise it sets `verified_at = utc_now()`.
   - **`list_identities(user_id)`** returns every row with a `verified` flag; **`unlink(user_id, identity_id)`** deletes `WHERE id = :iid AND user_id = :uid`, else `NotFoundError`.
3. **`decide_with_action_token`** follows 3.5.1 steps 1 to 5 in one transaction.
   - **Order of checks.** `ChannelIdentityService.resolve(TELEGRAM, external_id)` (confirmed only, else `AuthorizationError`), then token consume with `expected_user_id=identity.user_id`, then `user.is_active` and `MissionService.is_operator(mission, user)` evaluated now, then `telegram_action(gate.gate_type, short_action, gate.context_json.get("recommended_action"))`, then `decide(gate.mission_id, gate.id, action=…, reason=None, user_id=user.id, channel=DecisionChannel.TELEGRAM)`.
   - **Atomic rollback.** `decide` commits only after the workflow accepts the update, so a rejected update rolls back the token consumption.
   - **Message edit.** After commit, `TelegramAdapter.edit_notification(token.channel_message_ref, f"{action} by {user.email} at {decided_at:%Y-%m-%d %H:%M} UTC")`.
4. **Telegram client (thin; it runs inside the backend trust boundary and calls services in-process, contracts 3.0.2).**
   - **Callback data.** `callbacks/gate.py` defines `GateActionCallback(CallbackData, prefix="g")` with `token: str` and `a: str`.
   - **Decision handler.** `handlers/gate.py` filters `GateActionCallback.filter(F.a.in_({"a", "r"}))`, opens a session with `get_session_factory()`, calls `GateDecisionService(session).decide_with_action_token(raw_token=callback_data.token, short_action=callback_data.a, external_id=str(callback.from_user.id), callback_ref=callback.id)`, and answers the callback with the result.
   - **Error mapping.** `ConflictError` gives "Already decided or expired"; `AuthorizationError` gives "Not authorised"; any other `ApplicationError` gives "Failed".
   - **Kill switch.** If `inbound_approvals_enabled` is false, the handler answers "Approvals by Telegram are disabled" and calls nothing.
   - **Linking.** `handlers/link.py` handles `/link CODE` in private chats only (otherwise it replies "Use a private chat"). It calls `redeem_link_code(ChannelKind.TELEGRAM, str(message.from_user.id), message.from_user.username, code, ref=f"{message.chat.id}:{message.message_id}")` and replies "Linked as pending. Confirm it on your Mission Control profile page or with `mc notify confirm ID`."
   - **Registration.** Add both routers to `get_all_routers()` (`handlers/setup.py:24-26`).
   - **Bot username.** `bot.py` calls `getMe` at startup and stores the username for `POST /auth/me/channel-links/telegram` (OPEN item 4).
   - **Webhook log.** `webhook.py:73-83` keeps its three fields. Add a comment and a test asserting that the log never includes `callback_query.data` or message text.
5. **Rate limiting.**
   - **Callbacks.** The existing per-Telegram-user `RateLimitMiddleware` covers callbacks.
   - **Brute force.** Token guessing is infeasible (128-bit, bound to one user, single-use). No new limiter is added.
   - **Multi-worker deployments.** The per-process limit is listed under Risks.
6. **API (`auth_channels.py`)** and **mc.**
   - **Endpoints.** `POST /auth/me/channel-links/telegram` returns `{code, expires_at, bot_username}`. `GET /auth/me/channel-identities` returns `{identities: [{id, channel, external_id, external_username, verified, created_at}]}`. `POST /auth/me/channel-identities/{iid}/confirm` returns the identity. `DELETE /auth/me/channel-identities/{iid}` returns `{id}`. All use `CurrentUser`.
   - **mc.** `mc notify link-telegram` prints `Send "/link {code}" to @{bot_username} within {minutes} minutes, then run mc notify confirm ID`, with `code` and `bot_username` from the response and `minutes` as the whole minutes until `expires_at`. `mc notify identities` lists id, username, Telegram id and confirmation state. `mc notify confirm ID` and `mc notify unlink ID` call the matching endpoints.

**Tests**
- `tests/unit/backend/services/test_action_token_service.py`:
  - `test_consume_wrong_user_authorization_error`
  - `test_consume_replay_conflict`
  - `test_consume_expired_conflict`
- `tests/unit/backend/services/test_channel_identity_service.py`:
  - `test_redeem_requires_allowlisted_external_id`
  - `test_redeem_creates_unverified_identity_with_username`
  - `test_redeem_single_use`
  - `test_duplicate_confirmed_link_conflict`
  - `test_redeem_replaces_stale_unverified_row`
  - `test_confirm_other_users_identity_404`
  - `test_confirm_after_ttl_conflict`
- `tests/integration/backend/services/test_gate_decision_telegram.py`:
  - `test_unlinked_telegram_user_rejected`
  - `test_unconfirmed_identity_cannot_decide`
  - `test_token_for_other_user_rejected`
  - `test_viewer_demoted_after_issue_rejected`: the operator check runs at decision time.
  - `test_approve_maps_to_continue_and_writes_same_audit_as_web`: the row fields equal the web path except `decision_channel`.
  - `test_replayed_callback_id_rejected`.
  - `test_rejected_update_leaves_token_unconsumed`.
  - `test_post_run_approve_uses_recommended_action`.
- `tests/unit/clients/telegram/test_gate_callback.py`:
  - `test_callback_data_roundtrip_under_64_bytes`
  - `test_disabled_flag_short_circuits`
- `tests/unit/clients/telegram/test_webhook_logging.py::test_debug_log_excludes_callback_data`.
- `tests/integration/backend/api/test_auth_channels.py`:
  - `test_link_code_flow_end_to_end`: code, redeem, confirm, then `get_for_user` returns the identity.
  - `test_confirm_requires_current_user`.

**Done when**
- The tests pass.
- With `inbound_approvals_enabled: true` in a dev environment, a linked and confirmed operator receives a MANUAL mission's gate notification with buttons, Approve resumes the run, and a second tap answers "Already decided or expired".

---

### 88.4.10 Web lifecycle, budget, recipients and Telegram link UI

**Files**
- modify `modules/frontend/src/hooks/use-missions.ts`, `modules/frontend/src/hooks/use-mission-budget.ts`, `modules/frontend/src/types/index.ts`
- modify `modules/frontend/src/components/mission/mission-top-bar.tsx`, `modules/frontend/src/components/mission/archive-mission-button.tsx`, `modules/frontend/src/components/dashboard/mission-card.tsx`, `modules/frontend/src/components/workspace/run-row-detail.tsx`, `modules/frontend/src/components/workspace/mission-settings-drawer.tsx`, `modules/frontend/src/pages/profile.tsx`
- create `modules/frontend/src/types/notification.ts`, `modules/frontend/src/hooks/use-notification-recipients.ts`, `modules/frontend/src/hooks/use-channel-identities.ts`, `modules/frontend/src/components/workspace/mission-budget-section.tsx`, `modules/frontend/src/components/workspace/notification-recipients-section.tsx`, `modules/frontend/src/components/profile/telegram-link-panel.tsx`

**Current state**
- **Header.** `mission-top-bar.tsx:106-117` pauses and resumes through `useUpdateMission({status})`, which 88.4.2 removed from the API.
- **Archive.** `archive-mission-button.tsx:18-31` and `mission-card.tsx:26-33` PATCH `{status: 'archived'}`. No web control unarchives.
- **Run cancel.** `useCancelMissionRun` exists since 88.1.14 but nothing mounts it.
- **Budget, recipients and Telegram.** No web surface exists; 88.4.1 removed the old budget field from `mission-edit-modal.tsx`.

**Change**
1. **Hooks (`use-missions.ts`).** Add `usePauseMission(id)`, `useResumeMission(id)`, `useArchiveMission(id)` and `useUnarchiveMission(id)`. Each POSTs to `/missions/${id}/pause|resume|archive|unarchive`, sets `missionKeys.detail(id)` from the response and invalidates `missionKeys.all`.
2. **Header (`mission-top-bar.tsx`).** For the owner (`isOwner`, as today):
   - `active`: Pause (`usePauseMission`) and Archive (opens the existing archive `ConfirmDialog`).
   - `paused`: Resume (`useResumeMission`) and Archive. When `paused_reason === 'gate_timeout'`, the Resume button is disabled with the title "Decide the pending gate first". The `StatusPill` title shows the pause reason.
   - `archived`: Unarchive (`useUnarchiveMission`).

   Mutation errors show `toast.error(err.message)`; the server returns 409 with the reason (for example a breached cap).
3. **Archive call sites.** `archive-mission-button.tsx` and `mission-card.tsx:26-33` use `useArchiveMission`.
4. **Run cancel (`run-row-detail.tsx`).** When the run status is in `['pending', 'running', 'awaiting_gate', 'paused']`, render a secondary "Cancel run" `Button` that opens a `ConfirmDialog` ("Cancel run #{sequence}? In-flight tasks finish their current step, then the run ends cancelled."). Confirm calls `useCancelMissionRun(missionId).mutate(run.id)`.
5. **Budget (`mission-budget-section.tsx`).** Rendered in `mission-settings-drawer.tsx` above the archive button. It shows `month_spent_usd` of `per_month_usd`, the active run spend of `per_run_usd`, the lifetime spend and cap, and `breach` when set. Owners edit the three caps (lifetime empty means no cap) and save with `useUpdateMissionBudget(missionId)`, added to `use-mission-budget.ts`, which PUTs `/missions/${missionId}/budget` and invalidates the budget key. Validation errors from the server are shown inline.
6. **Recipients (`notification-recipients-section.tsx`).** Rendered in `mission-settings-drawer.tsx` below the budget section. It lists `useNotificationRecipients(missionId)` (email, channel, kinds) and, for the owner, adds a recipient by email with a kinds multi-select (lowercase values) and removes one. `use-notification-recipients.ts` exports `useNotificationRecipients`, `useAddNotificationRecipient` and `useRemoveNotificationRecipient`.
7. **Telegram link (`telegram-link-panel.tsx` on `pages/profile.tsx`).**
   - "Link Telegram" calls `POST /auth/me/channel-links/telegram` and shows `Send "/link CODE" to @bot_username` with the expiry time.
   - The identity list from `useChannelIdentities()` shows each row's `@username` and Telegram id. An unconfirmed row has a "Confirm" button (`useConfirmChannelIdentity`) with the text "Confirm only if this is your Telegram account." A confirmed row has "Unlink" (`useUnlinkChannelIdentity`).
   - `use-channel-identities.ts` exports `useCreateTelegramLinkCode`, `useChannelIdentities`, `useConfirmChannelIdentity` and `useUnlinkChannelIdentity`.
8. **Types.** `types/notification.ts` holds `NotificationKind` (lowercase union), `NotificationRecipient`, `NotificationRecipientCreate`, `ChannelIdentity` and `TelegramLinkCode`; export them from `types/index.ts`.

**Tests:** the frontend has no unit test harness. The gates are `npm run build` and `npm run lint` with zero warnings, plus the browser checks in Verification.

**Done when**
- `cd modules/frontend && npm run build && npm run lint` passes.
- `rg -n "status: 'archived'|status: 'paused'|status: 'active'" modules/frontend/src/components modules/frontend/src/hooks` returns nothing outside type and tone definitions.

---

### Verification

```bash
cd /Users/herman.young/development/mission-control
python admin.py migrate upgrade head
python admin.py migrate downgrade plan88_003a && python admin.py migrate upgrade head
pytest tests/unit -q -p no:cacheprovider
pytest tests/integration -q -p no:cacheprovider
pytest tests/unit/backend/temporal -q -k "gate or budget or lifecycle or replay or patch_ids"
pytest tests/unit/backend/temporal/test_no_config_in_workflows.py -q
rg -n "total_spent_usd|budget_usd_ceiling|budget_ceiling_usd|MissionPlanStatus|gate_manual|CliGateReviewer|run_notifier|pause_all_autonomous_plans|VALID_ACTIONS_BY_GATE|defaulting to CONTINUE" modules config --glob '!modules/backend/migrations/**'   # expect no output
python mc.py tree | rg -n "notify|mission (pause|resume|archive|unarchive|budget|set-budget)"
python admin.py tree | rg -n "reconcile|schedules sync"
cd modules/frontend && npm run build && npm run lint && cd ../..
python scripts/code_quality.py --scope modules/ tests/
```

**Manual smoke test** (dev stack, Telegram inbound on):
1. Link and confirm a Telegram account on the profile page.
2. Create a mission with `mc mission create smoke-budget --description "Phase 4 smoke" --gate-mode manual --budget-per-run 0.05`.
3. Run `mc runs start --objective "Summarise the repository README"`.
4. Approve the `pre_dispatch` gate from Telegram.
5. Confirm the run ends `budget_stopped/budget_run_cap`, the mission is `paused/budget_run_cap`, `temporal schedule describe` shows paused, and one `BUDGET_PAUSED` delivery row is `SENT`.
6. In the web header, Resume is accepted only after the per-run cap is raised in the budget section, and Cancel run on a new run ends it `cancelled`.

### Risks

1. **An update RPC sits inside an open DB transaction** (`GateDecisionService.decide`, the 3.3.3 exception), so a slow Temporal holds a row lock. **Mitigation:**
   - `execute_update` uses `rpc_timeout=timedelta(seconds=temporal.mission_run.activities.persistence.start_to_close_seconds)`;
   - the lock covers one `gate_requests` row only;
   - `close_gate_request` converges the DB if the commit fails after the acknowledgement.
2. **Parallel tasks can overshoot the run cap** by up to one LLM call per concurrent task. **Mitigation:**
   - headroom is split per chunk and checked before and after every agent call;
   - `max_parallel_tasks` is 4;
   - the 7-day acceptance run checks run cost against the ledger, with the tolerance taken as the largest observed single-call cost.
3. **Telegram rate limiting is per process** (`middlewares/rate_limit.py`), so N bot workers give N times the limit. **Mitigation:**
   - approval safety rests on single-use, user-bound, 128-bit tokens and confirmed identities, not on rate limiting;
   - inbound approvals stay off by default (`inbound_approvals_enabled: false`, P8).
4. **Making the ledger write fatal** in run context can fail tasks during a DB blip, and a retry re-spends. **Mitigation:**
   - the `execute_task` retry policy (3 attempts) and the 3.1.9 idempotency limit the re-spend to the interrupted task;
   - the dead attempt's spend stays attributed through `task_id`, so enforcement never under-counts.
5. **A `GATE_TIMEOUT` mission whose caps are breached by the time of the decision stays paused** (`resume_mission_for_run` returns `False`). **Mitigation:** the run stops on its next `check_run_budget`, the mission keeps `PAUSED/GATE_TIMEOUT` with no undecided gate, and `resume_mission` accepts that state once the owner raises the cap.
6. **Intermediate commits are not deployable.** Between 88.4.2 and 88.4.5, `mc mission archive|unarchive` and the web lifecycle controls send `status` to `PATCH /missions/{id}` and get 422; the web stays so until 88.4.10. **Mitigation:** Phase 4 ships as one deploy after 88.4.10. Every workflow change in this phase is behind a patch id, so in-flight runs replay and no drain is required. Until that deploy, production keeps `missions.recurrence.enabled: false` and dispatches no MANUAL or AI_ASSISTED missions (Phase 2 operational rule); the Phase 4 deploy is the point at which production sets `missions.recurrence.enabled: true`, restarts the worker and the API (the flag is read once per process; the worker's startup sync recreates the schedules), and confirms with `python admin.py schedules sync`.
