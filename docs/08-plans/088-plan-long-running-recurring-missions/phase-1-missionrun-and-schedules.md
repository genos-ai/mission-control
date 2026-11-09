## Phase 1: MissionRun and Temporal Schedules

**Goal:** Every occurrence of mission work becomes a numbered `MissionRun`. Each run starts from a durable `MissionRunWorkflow` with a pinned config snapshot. Recurrence moves onto one Temporal Schedule per `mission_schedules` row, with Postgres as the source of truth. The croniter minute evaluator, the 1-second `ScheduledMissionCheckWorkflow` poller, `RunObjectiveWorkflow` and the API-lifespan schedule registration are deleted. Approval events and explicit API calls now start or wake runs, and the worker reconciler fails runs whose workflow has gone.

**Entry criteria:**
- Phase 0 is merged to `main`, and `pytest tests/unit` and `pytest tests/integration` are green on it.
- `python admin.py migrate current` reports `plan87_002`. Phase 0 adds no migration; this phase adds `plan88_001`, `plan88_002` and `plan88_003`.
- `pytest tests/integration/backend/temporal/test_server_capabilities.py` (88.0.1) passes against the dev server, so `ListScheduleMatchingTimes` and Workflow Update are supported.
- **Baseline.** Code was verified at `a28ca771`. Backend and config are identical to `9adaa69d` and `777cd5c5`; later commits touch only the frontend, and every frontend line below was re-verified at `a28ca771`. Line numbers are at `a28ca771`. Where Phase 0 edits a file first, the step names the function or section instead of a line number.
- `git status --porcelain` lists no changes under `modules/`, `config/`, `tests/`, `requirements*.txt`, `pyproject.toml`, `mc.py`, `admin.py` or `services.py`. Uncommitted work in progress (for example the model-provider changes in progress at the time of writing) is committed or stashed first. If such work is committed, re-verify the line citations below in the files it touched (by symbol) before starting.
- If any item above is missing, stop. Do not start this phase.

**Phase boundaries.** These are fixed decisions. Phase 1 does not change them; the owning steps do.
- **Wave execution.** Waves still run through the existing `execute_mission` activity, which now takes run scope. The per-task activity, idempotency and per-task heartbeats belong to 88.2.3 and 88.2.4.
- **Loop bound and continue-as-new.** Phase 1 keeps a bounded loop and has no continue-as-new. The bound is the post-run reviewer's breaker #2 (`agents/mission_control/gate_post_run.py:131-139`), which escalates when `supervisor_iteration_count >= plan.max_supervisor_iterations`. 88.2.6 deletes the breaker (item 8); 88.2.7 adds continue-as-new.
- **Gates.** Gates still run inside dispatch. In MANUAL and AI_ASSISTED modes a run with only PROPOSED tasks waits, with no timeout, for the `tasks_approved` signal. The `_gate` seam is added in 88.2.6 and replaced by the durable gate in 88.4.8.
- **Budget.** Phase 1 adds no budget logic. `dispatch_approved` keeps its plan-level check (`services/mission_plan_dispatch.py:185-192`, as changed by 88.0.7). `claim_occurrence` has no budget rule; 88.4.6 adds it. `mission_runs.budget_cap_usd` stays NULL; 88.4.1 snapshots it in `begin`.
- **Run cost.** `finalise` writes `mission_runs.cost_usd` as the sum of `llm_calls.cost_usd` where `mission_run_id = run_id` (88.1.7). The column exists from `plan88_002`, but wave LLM calls carry `mission_run_id IS NULL` until 88.2.3 threads the run id into `record_llm_call`. Until then the figure covers only attributed calls.
- **Lifecycle.** `check_plan_active` stays in the loop. 88.4.2 rewrites its body to read `missions.status`; 88.4.5 stops calling it under patch id `p88-lifecycle-signals` (pause arrives through `request_pause`) and deletes it only when no caller remains.
- **Notifications.** Nothing is sent. `claim_occurrence` and `finalise_mission_run` build `NotificationRequest` objects and log them. 88.4.4 adds `send_mission_notification`; 88.4.5 sends run-end and tick notifications under patch id `p88-lifecycle-signals`.
- **Recurrence switch.** `missions.recurrence.enabled` (88.1.1) is required. When it is false, `create_schedule` refuses, `sync_to_temporal` removes every mission schedule from Temporal, and a tick that still arrives starts no run (88.1.6). Until Phase 4 is complete, production keeps it `false` and does not dispatch MANUAL or AI_ASSISTED missions, because budget enforcement and durable gates arrive in Phase 4.
- **Digests and the per-run MCD watermark.** `mission_run_digests` exists from `plan88_002`. Phase 3 writes digests. `context_version_start` and `context_version_end` are written from Phase 1 onwards.

**Commits:** one commit per step, with the message `Plan 88 Phase 1: 88.1.N <step title>`. The phase is pushed to `main` once, after Verification passes. Between steps the tree is deliberately inconsistent in two ways, which is acceptable only because nothing is pushed or run against shared data before the phase completes:
- between 88.1.3 and 88.1.14 the web schedule modal and `mc schedule` call deleted routes;
- between 88.1.8 and 88.1.10a the Phase 0 reconciler still judges task liveness by `mission-run-{plan_id}`, which no workflow uses any more.

---

### 88.1.0 GateMode enum and migration `plan88_001`

**Files:**
- **Create:**
  - `modules/backend/migrations/versions/plan88_001_gate_mode_enum.py`;
  - `tests/unit/backend/models/test_gate_mode_enum.py`;
  - `tests/unit/backend/api/test_missions_api.py`;
  - `tests/unit/clients/cli/test_mc_mission.py`;
  - `tests/integration/backend/test_plan88_001_migration.py`.
- **Delete:**
  - `tests/unit/backend/models/test_gate_mode_resolution.py` (created by 88.0.5);
  - `modules/frontend/src/hooks/use-veto-countdown.ts`.
- **Modify (backend):**
  - `models/mission_plan.py`, `models/mission.py`, `models/task.py`;
  - `schemas/mission.py`, `schemas/mission_plan.py`;
  - `services/mission.py`, `services/mission_plan.py`, `repositories/mission_plan.py`;
  - `api/v1/endpoints/missions.py`, `api/v1/endpoints/missions_plan.py`;
  - `agents/adapters/plan_introspection.py`, `agents/mission/director/tools/get_mission_info.py`;
  - `core/config_schema.py` (`GateSchema.mode`), `agents/mission_control/gate_post_run.py` (comment at `:88`);
  - every other module under `modules/backend` that the Done-when grep lists.
- **Modify (clients):**
  - `modules/clients/cli/mc_groups/mission.py`, `modules/clients/cli/mc_mission.py`, `modules/clients/cli/mission_cmds.py`, `modules/clients/cli/mc_gate.py`, `modules/clients/cli/mc_plan.py`;
  - `modules/frontend/src/types/mission.ts`, `src/hooks/use-mission-plan.ts`, `src/pages/mission/new.tsx`, `src/components/workspace/plan-board-top-bar.tsx`, `src/components/workspace/plan-board.tsx`, `src/components/workspace/plan-board-task-card.tsx`.

**Current state:**
- `VALID_GATE_MODES` is a frozenset of lowercase strings, and `AUTO_APPROVE_GATE_MODES = {"ai_assisted", "autonomous"}` (`models/mission_plan.py:48-59`). Phase 0 added `FAIL_CLOSED_GATE_MODE` and `resolve_gate_mode` after `:59` (88.0.5).
- `missions.gate_mode` (`models/mission.py:101-106`) and `mission_plans.gate_mode` (`models/mission_plan.py:116-123`) are nullable `String(20)`.
- `mission_plans.veto_window_sec` (`models/mission_plan.py:156`) and `tasks.veto_expires_at` (`models/task.py:186-190`) serve the AI_ASSISTED veto window, which the contract removes.
- `MissionCreate` (`schemas/mission.py:12-75`) has no `gate_mode`. `POST /missions` (`api/v1/endpoints/missions.py:65-76`) never passes one, so new plans inherit NULL.
- The plan is created lazily: `MissionPlanService.get_or_create_plan` (`services/mission_plan.py:139-158`) copies `mission.gate_mode` on first access.
- `mc mission create --gate` is optional (`mc_groups/mission.py:30-36`), and `mc_mission.create` sets the mode through a second `PATCH /plan` call (`mc_mission.py:43-48`).
- `mc_gate.py:71` and `mc_plan.py:60` display `plan.get("gate_mode") or "autonomous"`, which misreports a NULL mode.
- The web create page (`pages/mission/new.tsx:63-70`) sends no gate mode. `plan-board-top-bar.tsx:115` displays `plan.gate_mode ?? 'interactive'`.

**Change:**
1. **Enum (`models/mission_plan.py`).**
   ```python
   class GateMode(str, enum.Enum):
       INTERACTIVE = "interactive"
       MANUAL = "manual"
       AI_ASSISTED = "ai_assisted"
       AUTONOMOUS = "autonomous"

   AUTO_APPROVE_GATE_MODES: frozenset[GateMode] = frozenset({GateMode.AUTONOMOUS})
   ```
   - Delete `VALID_GATE_MODES`, `FAIL_CLOSED_GATE_MODE` and `resolve_gate_mode` (P3). Each caller of `resolve_gate_mode` uses the column value directly, because the column is now NOT NULL and constrained to the enum.
   - `MissionPlan.gate_mode` becomes `mapped_column(Enum(GateMode, native_enum=False, length=32), nullable=False)`.
   - Delete `MissionPlan.veto_window_sec`.
2. **Other models.** Delete `Mission.gate_mode` (`models/mission.py:101-106`) and `Task.veto_expires_at` (`models/task.py:186-190`).
3. **Comparisons.** Every gate-mode comparison under `modules/backend` uses `GateMode` members, never string literals. This is required, not cosmetic: with `Enum(GateMode)` an SQL predicate such as `MissionPlan.gate_mode == "autonomous"` binds a value that is not an enum name and raises `LookupError`. Every function parameter that carries a gate mode is typed `GateMode`, not `str | None`.
   - `core/config_schema.py`: `GateSchema.mode: _GateMode = Field(...)`. It is required, with no hardcoded default; `config/settings/gate.yaml:18` already sets `mode: "autonomous"`.
   - Reword the comment at `agents/mission_control/gate_post_run.py:88` (`# When the mission's gate_mode is "manual", ...`) to name `GateMode.MANUAL` instead of the string literal.
4. **Boundary conversion.** Service methods that receive a gate mode from a client convert it with `GateMode(value)`, and an unknown value raises `ValidationError`. This covers `MissionService.create_mission` and `MissionPlanService.set_gate_mode`. API schemas type the field as `GateMode`, so Pydantic validates the lowercase value (contracts 3.0.2 wire format).
5. **Schemas.**
   - `MissionCreate.gate_mode: GateMode = Field(..., description="Plan gate mode")`. It is required.
   - In `schemas/mission_plan.py`: the PATCH schema (`:50`) types `gate_mode: GateMode | None`; the plan response (`:138`) types `gate_mode: GateMode`; delete `veto_window_sec` (`:63`, `:143`) and `veto_expires_at` (`:96`). `RunObjectiveRequest.gate_mode` (`:164`) becomes `GateMode | None`; the class is deleted in 88.1.12.
6. **Eager plan creation (`services/mission.py`).**
   - `create_mission(..., gate_mode: str, ...)` is required and keyword-only. After the `missions` insert it calls `MissionPlanRepository(self._session).create_for_mission(mission_id=mission.id, gate_mode=GateMode(gate_mode), budget_usd_ceiling=budget_ceiling_usd)` in the same transaction.
   - Delete `MissionService.set_gate_mode` (`services/mission.py:453-463`). The admin `mission gate` action (`mission_cmds.py:409-426`) calls `MissionPlanService.set_gate_mode(plan.id, gate_mode)` instead.
   - `POST /missions` passes `gate_mode=data.gate_mode`.
7. **`get_or_create_plan` (`services/mission_plan.py:139-158`).** Delete the create branch. When no plan exists it raises `NotFoundError(f"Mission {mission_id} has no plan")`. The name is kept because 33 call sites and later phases use it; every mission has a plan after `plan88_001`. Every test fixture that inserts a `missions` row without `create_mission` also inserts its `mission_plans` row (`grep -rn "Mission(" tests` lists them).
8. **Repository and readers.** `create_for_mission` drops `veto_window_sec` and types `gate_mode: GateMode`. Delete the `veto_window_sec` handling at `missions_plan.py:120-121` and the key at `plan_introspection.py:49`. `get_mission_info.py:43` reads the plan's gate mode.
9. **Migration `plan88_001_gate_mode_enum.py`** (`revision="plan88_001"`, `down_revision="plan87_002"`). It never calls `get_app_config()`. Operations, in order:
   1. `UPDATE mission_plans p SET gate_mode = m.gate_mode FROM missions m WHERE p.mission_id = m.id AND p.gate_mode IS NULL`.
   2. Insert one `mission_plans` row for each mission that has none: `id=gen_random_uuid()`, `gate_mode=m.gate_mode`, `status='ACTIVE'`, `version=1`, `total_spent_usd=0`, `budget_usd_ceiling=m.budget_ceiling_usd`, `created_at=now()`, `updated_at=now()`. Every other column takes its server default.
   3. `UPDATE mission_plans SET gate_mode = 'manual' WHERE gate_mode IS NULL OR gate_mode NOT IN ('interactive','manual','ai_assisted','autonomous')`. This covers `workflow_managed` and fails closed. Log the row count with `get_logger(__name__)`.
   4. `UPDATE mission_plans SET gate_mode = upper(gate_mode)`.
   5. `ALTER COLUMN mission_plans.gate_mode TYPE VARCHAR(32), SET NOT NULL`.
   6. Drop `missions.gate_mode`, `mission_plans.veto_window_sec` and `tasks.veto_expires_at`.
   7. `downgrade()` reverses 6 to 4 structurally: re-add the three columns as nullable, make `gate_mode` nullable `VARCHAR(20)` with `lower(gate_mode)` values, and copy the plan value back into `missions.gate_mode`. It does not delete the plans inserted in step 2.
10. **Clients.**
    - `mc mission create`: the `--gate` option becomes `--gate-mode`, `required=True`, `type=click.Choice(["interactive", "manual", "ai_assisted", "autonomous"])`. Clients do not import backend models, so the list stays literal. `mc_mission.create` sends `gate_mode` in the `POST /missions` body and drops the follow-up `PATCH /plan`.
    - The admin `mission create` command makes its gate-mode option required and passes it to `create_mission`.
    - `mc_gate.py:71` and `mc_plan.py:60` print `plan["gate_mode"]` with no fallback.
    - Web: move the `GateMode` type from `hooks/use-mission-plan.ts:29` to `types/mission.ts`, and `use-mission-plan.ts` imports it. `MissionCreateRequest` (`types/mission.ts:34`) gains `gate_mode: GateMode`. `pages/mission/new.tsx` adds a required gate-mode field using `components/ui/select.tsx`, with the four values, no preselected value, and submit disabled until one is chosen. `use-mission-plan.ts:65` types `gate_mode: GateMode` (not nullable); delete `veto_expires_at` (`:47`) and `veto_window_sec` (`:70`, `:136`). `plan-board-top-bar.tsx:115` uses `plan.gate_mode`. `plan-board.tsx:387` drops the null guard. `plan-board-task-card.tsx:33,69-70` drops the veto countdown, and `hooks/use-veto-countdown.ts` is deleted.
    - Out of scope: the TUI create path (`clients/tui/services/service_bridge.py:89`) already omits the required `owner_id` at `a28ca771` and is not repaired here.

**Tests:**
- `test_gate_mode_enum.py`:
  - `test_values_are_lowercase_names`: `[m.value for m in GateMode] == ["interactive", "manual", "ai_assisted", "autonomous"]`.
  - `test_auto_approve_only_autonomous`.
  - `test_enum_stores_name` (DB): a plan flushed with `GateMode.AI_ASSISTED` reads back `'AI_ASSISTED'` through raw SQL.
  - `test_create_mission_creates_plan_with_mode` (DB): `create_mission(..., gate_mode="manual")` leaves exactly one plan with `GateMode.MANUAL`.
  - `test_create_mission_rejects_unknown_mode`: `gate_mode="bogus"` raises `ValidationError`.
  - `test_get_or_create_plan_raises_when_absent`.
  - `test_gate_schema_mode_required`: validating a `gate.yaml` mapping without `mode` raises `pydantic.ValidationError`.
- `tests/unit/backend/api/test_missions_api.py::test_create_requires_gate_mode`: a POST without `gate_mode` returns 422.
- `test_plan88_001_migration.py` (real Postgres, seeded at `plan87_002`):
  - `test_plan_null_inherits_mission_mode`: mission `autonomous`, plan NULL gives `AUTONOMOUS`.
  - `test_workflow_managed_becomes_manual`.
  - `test_unknown_and_null_become_manual`.
  - `test_mission_without_plan_gets_plan`.
  - `test_roundtrip`: `upgrade plan88_001`, `downgrade plan87_002`, `upgrade plan88_001` all succeed.
- `tests/unit/clients/cli/test_mc_mission.py::test_create_sends_gate_mode_in_post`: the POST body contains `gate_mode`, and no PATCH is sent.

**Done when:**
- `python admin.py migrate upgrade head` reaches `plan88_001`, and the tests pass.
- `grep -rnE --exclude-dir=migrations '"(interactive|manual|ai_assisted|autonomous|workflow_managed)"' modules/backend --include=*.py` prints only the `GateMode` values in `models/mission_plan.py`, the `_GateMode` literal for `gate.yaml` in `core/config_schema.py`, and the `hasattr(self._config, "manual")` attribute check in `agents/mission_control/gate.py`.
- `grep -rn --exclude-dir=migrations "resolve_gate_mode\|VALID_GATE_MODES\|veto_window_sec\|veto_expires_at" modules --include=*.py --include=*.ts --include=*.tsx` is empty.
- `cd modules/frontend && npm run build && npm run lint` passes.

---

### 88.1.1 Config deltas: recurrence and unread keys

**Files:**
- Modify: `config/settings/temporal.yaml`, `config/settings/missions.yaml`, `modules/backend/core/config_schema.py`, `tests/unit/backend/temporal/test_config.py`.
- Create: `tests/unit/backend/core/test_config_schema_plan88_phase1.py`.

**Current state:**
- 88.0.2 already added the `mission_run:`, `reconciler:` and `system_schedules:` blocks (the last with only `reconciler`) and their schema classes. This step does not touch them.
- Three `temporal.yaml` keys are never read outside `tests/unit/backend/temporal/test_config.py:18-20`: `workflow_execution_timeout_days`, `activity_start_to_close_seconds` and `activity_retry_max_attempts` (`temporal.yaml:8-10`). `refine_poll_interval_seconds` (`:25`) has no reader at all.
- Two knowledge cron keys are unread: `KnowledgeEmbeddingSchema.backfill_schedule_cron` (`config_schema.py:416`, `missions.yaml:36`) and `KnowledgeOfficerSchema.schedule_cron` (`config_schema.py:451`, `missions.yaml:59`).

**Change:**
1. **`temporal.yaml` and `TemporalSchema`.** Delete `workflow_execution_timeout_days`, `activity_start_to_close_seconds`, `activity_retry_max_attempts` and `refine_poll_interval_seconds` from both.
2. **Recurrence config.** Add `RecurrenceSchema` verbatim from contract 3.4.6, including the required `enabled: bool = Field(...)` and its validator (`default_catch_up_window_seconds <= max_catch_up_window_seconds`). Add `recurrence: RecurrenceSchema = Field(...)` on `MissionsSchema`, and append the `recurrence:` block from contract 3.4.2 to `missions.yaml`. Do not add `budgets`, `digest` or `context_packet`; Phases 3 and 4 add them.
3. **Knowledge cron keys.** Delete `backfill_schedule_cron` and `schedule_cron` from the two schemas and from `missions.yaml:36,59`.
4. **Deltas owned by later steps.** Each key below is changed in the step that removes its reader or needs it, so every step leaves the tree loadable:

   | Key | Step | Reason |
   |---|---|---|
   | `workflows.max_scheduled_runs_per_day`, `workflows.schedule_evaluation_interval_seconds` | 88.1.3 | readers deleted with `services/workflow_schedule.py` |
   | `temporal.wait_action_sleep_seconds`, `refine_poll_max_seconds`, `max_supervisor_iterations` | 88.1.8 | readers in `mission_run_workflow.py` are rewritten |
   | `temporal.dispatch_check_interval_seconds` | 88.1.10 | reader `main.py:125` is deleted |
   | the eight further `system_schedules` keys and the equality validator | 88.1.10 | Phase 0's `_BUILDERS` raises for keys it cannot build |
   | `cli.yaml` | 88.1.13 | read only by `mc runs list` |

   `budget_timeout_multiplier_seconds`, the three `execution_retry_*` keys and `notification_timeout_seconds` stay. 88.2.6 deletes them with `AgentMissionWorkflow` (`temporal/workflow.py:72,86-91`).

**Tests:**
- `test_config_schema_plan88_phase1.py`:
  - `test_recurrence_requires_every_field`: omitting `min_interval_seconds` raises `ValidationError`, and so does omitting `enabled`.
  - `test_recurrence_default_window_le_max`: `default_catch_up_window_seconds=700000` with `max_catch_up_window_seconds=604800` raises.
  - `test_deleted_temporal_keys_rejected`: `TemporalSchema` with `refine_poll_interval_seconds=1` raises, because the schema is strict.
  - `test_repo_yaml_loads`: `get_app_config()` loads the real `config/settings/*.yaml`, and `missions.recurrence.default_catch_up_window_seconds == 21600`.
- `test_config.py`: delete the assertions at `:18-20`.

**Done when:** `pytest tests/unit/backend/core tests/unit/backend/temporal/test_config.py -q` passes, and `grep -rn --exclude-dir=migrations "workflow_execution_timeout_days\|activity_start_to_close_seconds\|refine_poll_interval_seconds\|backfill_schedule_cron\|schedule_cron" modules config tests` returns nothing.

---

### 88.1.2 MissionRun models and migration `plan88_002`

**Files:**
- Create: `modules/backend/models/mission_run.py`, `modules/backend/models/mission_run_digest.py`, `modules/backend/migrations/versions/plan88_002_mission_runs.py`, `tests/unit/backend/models/test_mission_run.py`, `tests/integration/backend/test_plan88_002_migration.py`.
- Modify:
  - `modules/backend/models/mission.py`, `models/task.py`, `models/execution_record.py`, `models/mission_context.py`, `models/llm_call.py`, `models/__init__.py`;
  - `modules/backend/migrations/env.py`, `modules/backend/core/exceptions.py`;
  - `modules/backend/repositories/execution_record.py`, `services/execution_persistence.py`, `schemas/execution_record.py`;
  - `tests/conftest.py`.

**Current state:**
- `ExecutionRecord.parent_execution_record_id` (`models/execution_record.py:159-165`) is never written. Its only reader is `get_replan_chain` (`repositories/execution_record.py:142-158`), delegated to by `execution_persistence.py:618-620`. The parameter is threaded through `execution_persistence.py:87,129`, and the schema field is at `schemas/execution_record.py:91`.
- `tasks` has no run column. `Task.transition_status` is at `models/task.py:256-268`.
- `llm_calls` has `mission_id` and `execution_record_id` but no run or task attribution (`models/llm_call.py:26-34`).
- `context_changes` has `context_id`, `version` and `mission_id` (`models/mission_context.py:125-159`). Legacy rows from `tools/update_context.py` and `SummarizationService` have `mission_id IS NULL`, so range reads must key on `context_id`.

**Change:**
1. **`models/mission_run.py`.** Define these enums from contract 3.1.2, each as `str, enum.Enum` with lowercase values:
   - `MissionRunTrigger`, `MissionRunStatus` and `MissionRunStatusReason`.
   - `ACTIVE_RUN_STATUSES` (frozenset of PENDING, RUNNING, AWAITING_GATE and PAUSED) and `TERMINAL_RUN_STATUSES`.
   - `VALID_RUN_TRANSITIONS: dict[MissionRunStatus, frozenset[MissionRunStatus]]`, copied from the 3.2.1 table.
   - `class MissionRun(UUIDMixin, TimestampMixin, Base)`, with every column, index and check from 3.1.6. Use `Enum(X, native_enum=False, length=32)`; `status_reason` and `cancel_reason` use `length=40`; `gate_mode` uses `Enum(GateMode, native_enum=False, length=32)`.
   - `def transition_status(self, target: MissionRunStatus, reason: MissionRunStatusReason | None, detail: str | None) -> None`. It raises `MissionRunStateError` when `target not in VALID_RUN_TRANSITIONS[self.status]`. It sets `started_at=utc_now()` on entering RUNNING from PENDING, and `ended_at=utc_now()` on entering a terminal status.
2. **`models/mission_run_digest.py`.** `DigestGenerator` and `MissionRunDigest`, per contract 3.1.7.
3. **Exceptions.** In `core/exceptions.py`, add `class MissionRunStateError(ApplicationError)`. The class name matches its `NON_RETRYABLE` string in 3.3.4. `RunStartRejectedError` is added in 88.1.7.
4. **Model columns.**
   - `Mission.run_sequence_counter`: `Integer`, `server_default="0"`, NOT NULL.
   - `Task.mission_run_id`, `ExecutionRecord.mission_run_id`, `TaskExecution.mission_run_id`, `TaskExecution.idempotency_key` and `ContextChange.mission_run_id`, per 3.1.8.
   - `LlmCall.mission_run_id: Mapped[str | None]` and `LlmCall.task_id: Mapped[str | None]`, both `PgUUID(as_uuid=False)` with no FK, matching the existing table style.
   - The failure columns on `tasks` and `task_executions` (3.1.8, decision 15) are **not mapped here**. The migration creates them; 88.2.3b maps them with the `FailureOrigin` and `FailureClass` enums, which do not exist until then. Phase 1 code never reads or writes them.
   - Delete `ExecutionRecord.parent_execution_record_id`, `get_replan_chain` in the repository and in `execution_persistence.py:618-620`, the `parent_execution_record_id` parameter (`execution_persistence.py:87,129`) and the schema field (`schemas/execution_record.py:91`).
5. **Migration `plan88_002_mission_runs.py`** (`revision="plan88_002"`, `down_revision="plan88_001"`). Operations, in order:
   1. `op.add_column("missions", sa.Column("run_sequence_counter", sa.Integer(), server_default="0", nullable=False))`.
   2. `op.create_table("mission_runs", ...)` with every column from 3.1.6, using `server_default="PENDING"` for `status`, `'{}'::jsonb` for the JSONB columns, and `0` for the counters and `cost_usd`.
   3. Create `uq_mission_runs_mission_sequence`, `uq_mission_runs_schedule_slot`, the UNIQUE constraint on `temporal_workflow_id`, and the partial unique index `uq_mission_runs_one_active ON mission_runs (mission_id) WHERE status IN ('PENDING','RUNNING','AWAITING_GATE','PAUSED')`. Create `ix_mission_runs_nonterminal (status, updated_at)` with the same predicate, `ix_mission_runs_mission_created (mission_id, created_at DESC)` and `ck_mission_runs_schedule_slot`.
   4. **Deferred FK.** `mission_runs.schedule_id` is a plain UUID column with an index and no FK here. `plan88_003` adds the FK, because `mission_schedules` does not exist yet.
   5. `op.create_table("mission_run_digests", ...)` per 3.1.7.
   6. Add the 3.1.8 columns on `tasks`, `execution_records`, `task_executions` and `context_changes`, with `ix_tasks_run_status (mission_run_id, status)`, `uq_execution_records_run` (partial, `WHERE mission_run_id IS NOT NULL`), `ix_task_executions_mission_run_id`, `uq_task_executions_idempotency_key` and `ix_context_changes_mission_run_id`.
   7. Create `ix_context_changes_context_version ON context_changes (context_id, version)`.
   7a. Add the failure columns (3.1.8): `failure_origin` VARCHAR(32), `failure_class` VARCHAR(40) and `failure_fingerprint` VARCHAR(64) on both `tasks` and `task_executions`, all nullable, plus `task_executions.failure_json` JSONB nullable and `ix_task_executions_failure_fingerprint (failure_fingerprint)`. No backfill: existing FAILED rows keep NULL.
   8. Add `llm_calls.mission_run_id` and `llm_calls.task_id` (UUID, nullable, no FK), with `ix_llm_calls_mission_run_id (mission_run_id)`, `ix_llm_calls_task_id (task_id)` and `ix_llm_calls_mission_created (mission_id, created_at)`.
   9. Drop the FK `execution_records_parent_execution_record_id_fkey`, then the `parent_execution_record_id` column.
   10. `downgrade()` reverses steps 9 to 1 structurally.

   `gate_requests.*` columns are not in this migration; they arrive in `plan88_006` (88.4.3).
6. **Registration.** Register both new models in `models/__init__.py`, `migrations/env.py` and `tests/conftest.py`.

**Tests:**
- `test_mission_run.py`:
  - `test_valid_transitions_match_contract`: the dict equals the 3.2.1 table, entry by entry.
  - `test_transition_rejects_running_to_pending`: raises `MissionRunStateError`.
  - `test_transition_sets_started_and_ended_at`.
  - `test_enum_stores_name`: after a flush, `SELECT status FROM mission_runs` returns `'PENDING'`.
- `test_plan88_002_migration.py` (integration, real Postgres):
  - `test_upgrade_downgrade_roundtrip`: `upgrade plan88_002`, `downgrade plan88_001` and `upgrade plan88_002` all succeed.
  - `test_one_active_run_per_mission`: a second insert with status `RUNNING` for the same mission raises `IntegrityError` naming `uq_mission_runs_one_active`; inserting `SKIPPED` succeeds.
  - `test_schedule_slot_check`: a `trigger='SCHEDULE'` row with NULL `scheduled_for` violates `ck_mission_runs_schedule_slot`.
  - `test_llm_calls_attribution_columns_exist`: `information_schema.columns` lists `llm_calls.mission_run_id` and `llm_calls.task_id`.
  - `test_context_version_index_exists`: `pg_indexes` lists `ix_context_changes_context_version` on `(context_id, version)`.
  - `test_failure_columns_exist`: `information_schema.columns` lists the seven failure columns of 3.1.8, and `pg_indexes` lists `ix_task_executions_failure_fingerprint`.

**Done when:**
- `python admin.py migrate upgrade head` reaches `plan88_002`.
- The tests pass.
- `grep -rn --exclude-dir=migrations "parent_execution_record_id\|get_replan_chain" modules --include=*.py` is empty.

---

### 88.1.3 MissionSchedule model, migration `plan88_003`, and deletion of the croniter engine

**Files:**
- **Create:**
  - `modules/backend/models/mission_schedule.py`;
  - `modules/backend/migrations/versions/plan88_003_mission_schedules.py`;
  - `tests/integration/backend/test_plan88_003_migration.py`.
- **Delete:**
  - `modules/backend/models/workflow_schedule.py`;
  - `modules/backend/repositories/workflow_schedule.py`;
  - `modules/backend/services/workflow_schedule.py`;
  - `modules/backend/schemas/workflow_schedule.py`;
  - `modules/backend/tasks/workflow_scheduler.py`;
  - `modules/clients/cli/schedule_cmds.py`;
  - `modules/clients/cli/admin_groups/schedule.py`;
  - `tests/unit/backend/services/test_workflow_schedule.py`;
  - `tests/unit/backend/tasks/test_workflow_scheduler.py`;
  - `tests/unit/backend/api/test_mission_schedules_api.py`;
  - `tests/unit/clients/cli/test_mc_schedule.py`.
- **Modify:**
  - `models/__init__.py:43,96`, `migrations/env.py:56`, `tests/conftest.py:57`;
  - `temporal/maintenance_workflow.py` (delete `EvaluateWorkflowSchedulesWorkflow`, `:87-96`) and `temporal/maintenance_activities.py` (delete `run_evaluate_workflow_schedules`, `:119-135`);
  - `temporal/worker.py:41,49,111,153`;
  - `main.py:68,162-167`;
  - `api/v1/endpoints/missions_workflows.py` (delete the `# ---- Workflow schedules ----` section, `:619-737` at `a28ca771`, and the `schemas.workflow_schedule` import at `:24-28`);
  - `tasks/__init__.py:9`, `admin.py:42,247`;
  - `services/mission.py` (the `direct_tables` list in `delete_mission`), `services/database_admin.py` (`PROJECT_TABLES` and `RUN_TABLES`);
  - `core/config_schema.py`, `core/config.py:350-353`, `config/settings/workflows.yaml`, `modules/clients/cli/admin_cmds.py:151`;
  - `tests/unit/clients/cli/test_admin_cmds.py:149`, `tests/unit/backend/api/test_admin_api.py:245-246`;
  - `services/workflow_run_waves.py:58` and `services/workflow_run_steps/helpers.py:11` (comment edits only: both name `workflow_scheduler.py`);
  - `modules/frontend/src/lib/cron.ts:11`, a comment naming `workflow_schedule.py`.

Phase 0 steps 88.0.9 and 88.0.11 edit the schedule section of `missions_workflows.py`, so delete it by section, not by line number.

**Current state:** `workflow_schedules` is defined at `models/workflow_schedule.py:30-119`:
- **Wrong target.** `workflow_definition_id` is NOT NULL with ON DELETE CASCADE (`:43-48`), and the unique constraint is on `(definition, mission, cron)` (`:34-41`).
- **Columns with no successor.** `description` (`:72`) and `budget_per_run_usd` (`:77`) have no `mission_schedules` column.
- **No cron evaluation.** 88.0.12 made `_compute_next_fire` raise, because croniter is in neither requirements file.
- **Lost fires.** The 60s local-activity evaluator (`maintenance_workflow.py:87-96`) runs due schedules one after another, and `record_fire` commits before each run starts (`tasks/workflow_scheduler.py:43-45,71-110`).
- **Readers of the workflow schedule config keys.** `max_scheduled_runs_per_day` and `schedule_evaluation_interval_seconds` (`config_schema.py:382-383`, `workflows.yaml`) are read by `services/workflow_schedule.py:261`, `config.py:350-353` and `admin_cmds.py:151`.

**Change:**
1. **`models/mission_schedule.py`.**
   - Define `MissionScheduleKind`, `MissionScheduleStatus`, `MissionScheduleCompletedReason` and `TemporalSyncState` (lowercase values).
   - Define `class MissionSchedule(UUIDMixin, TimestampMixin, Base)` with every column and constraint from 3.1.5.
   - Add `@property temporal_id` that returns `f"mission-schedule-{self.id}"`. The column `temporal_schedule_id` is set from it at insert.
2. **Migration `plan88_003_mission_schedules.py`** (`revision="plan88_003"`, `down_revision="plan88_002"`). It never calls `get_app_config()`:
   ```python
   DEFAULT_CATCH_UP_WINDOW_SECONDS = 21600  # missions.recurrence.default_catch_up_window_seconds at plan88_003
   ```
   1. Create `mission_schedules` with every column, index and check from 3.1.5.
   2. Create FK `fk_mission_runs_schedule_id` from `mission_runs.schedule_id` to `mission_schedules.id`, ON DELETE SET NULL.
   3. **Creator pre-check.** Select every `workflow_schedules` row whose creator cannot be resolved: `ws.created_by` does not match `^user:([0-9a-f-]{36})$` naming an existing user, and `m.owner_id` is not an existing user id. If any exist, raise `RuntimeError` listing their ids. Nothing is written. Verification step 0 runs the same query before deploy.
   4. **Data migration in Python, inside `upgrade()`.** For each row of `SELECT ws.*, m.owner_id FROM workflow_schedules ws JOIN missions m ON m.id = ws.mission_id`:
      - `new_id = str(uuid4())`.
      - **Time zone.** Validate `ws.timezone` with `zoneinfo.ZoneInfo`. If it raises, set `status='ARCHIVED'`, `time_zone_name='UTC'` and `temporal_sync_error='plan88_003: invalid time zone ' || ws.timezone`.
      - **Completed rows.** If the time zone is valid and `ws.max_iterations IS NOT NULL AND ws.iteration_count >= ws.max_iterations`, set `status='COMPLETED'` and `completed_reason='MAX_RUNS_REACHED'`.
      - **Everything else** gets `status='PAUSED'`, so the owner must resume it under the new time-zone semantics.
      - **Insert** with `kind='WORKFLOW_DEFINITION'`, `name='wf-' || left(ws.id::text, 8)`, `workflow_definition_id=ws.workflow_definition_id` and `workflow_parameters='{}'`. Copy the cron. Set `time_zone_name` as above, `max_runs=ws.max_iterations`, `executed_run_count=least(ws.iteration_count, coalesce(ws.max_iterations, ws.iteration_count))`, `catch_up_window_seconds=DEFAULT_CATCH_UP_WINDOW_SECONDS`, `temporal_schedule_id='mission-schedule-' || new_id` and `temporal_sync_state='PENDING'`.
      - **Creator.** `created_by_user_id` is the UUID parsed from `ws.created_by` when it matches `^user:([0-9a-f-]{36})$` and that user exists. Otherwise it is `m.owner_id`.
      - **Dropped columns (P3).** `ws.description` and `ws.budget_per_run_usd` are not carried over. Log at warning the count of rows with `budget_per_run_usd IS NOT NULL`.
   5. `op.drop_table("workflow_schedules")`.
   6. `downgrade()` recreates the `workflow_schedules` structure from the old model, empty, then drops the FK and `mission_schedules`.
3. **Legacy deletions.** Delete the files listed above and every import of them. `admin schedule` is deleted in full because it is replaced by `admin schedules sync` (88.1.13).
4. **Workflow schedule config keys.** Delete `max_scheduled_runs_per_day` and `schedule_evaluation_interval_seconds` from `WorkflowsSchema`, from `workflows.yaml`, from the `config.py:350-353` display dict and from `admin_cmds.py:151`, and delete the mocks at `test_admin_cmds.py:149` and `test_admin_api.py:245-246`.
5. **Table-name lists.**
   - `services/mission.py`, `direct_tables` in `delete_mission`: remove `"workflow_schedules"` and insert `"mission_runs", "mission_schedules"` immediately before `"mission_plans"`. `mission_runs` and `mission_schedules` reference `workflow_definitions` with ON DELETE RESTRICT, so they must go before it.
   - `services/database_admin.py`: in `PROJECT_TABLES`, replace `"workflow_schedules"` with `"mission_schedules"`. In `RUN_TABLES`, insert `"mission_run_digests", "mission_runs"` immediately after `"tasks"`, so children are cleared before parents.

**Tests:**
- `test_plan88_003_migration.py` (integration). Each test seeds a `workflow_schedules` row at `plan88_002`, then upgrades.
  - `test_row_migrates_paused`: `timezone='Europe/London'`, `iteration_count=3` and `max_iterations=10` give a mission schedule with `status='PAUSED'`, `executed_run_count=3`, `max_runs=10`, `kind='WORKFLOW_DEFINITION'` and `catch_up_window_seconds=21600`.
  - `test_exhausted_row_completes`: `iteration_count=10` and `max_iterations=10` give `COMPLETED/MAX_RUNS_REACHED`.
  - `test_invalid_timezone_archived`: `timezone='Mars/Base'` gives `ARCHIVED` with the error text set.
  - `test_created_by_parsed`: `created_by='user:<existing uuid>'` maps to that user, and `'user:api'` maps to the owner.
  - `test_unresolvable_creator_aborts`: owner `'cli-user'` (not a user) and `created_by='user:api'` raise, and `workflow_schedules` still exists.
  - `test_workflow_schedules_dropped`.

**Done when:**
- `python admin.py migrate upgrade head` reaches `plan88_003`.
- `grep -rn --exclude-dir=migrations --include=*.py --include=*.yaml "croniter\|workflow_scheduler\|WorkflowSchedule\|EvaluateWorkflowSchedules\|max_scheduled_runs_per_day\|schedule_evaluation_interval_seconds" modules/backend tests config` returns nothing. The web client (`types/workflow.ts`, `hooks/use-workflows.ts`, `components/workflow/schedule-modal.tsx`, `components/workspace/workflows-panel.tsx`) and `clients/cli/mc_schedule.py` still match until 88.1.14 and 88.1.13, whose Done when cover them.
- `python admin.py tree | grep -c "schedule  —"` is `0`.
- `pytest tests/unit -q` passes.

---

### 88.1.4 Repositories

**Files:**
- Create: `modules/backend/repositories/mission_run.py`, `repositories/mission_schedule.py`, `repositories/mission_run_digest.py`, `tests/integration/backend/repositories/test_mission_run_repository.py`, `tests/integration/backend/repositories/test_mission_schedule_repository.py`.
- Modify: `repositories/mission.py`, `repositories/task.py`.

**Current state:** `TaskRepository.get_by_plan_id` (`repositories/task.py:43`) is the only plan-scoped reader. `reconcile_tasks` (`:217-316`) works across the whole plan.

**Change:** method contracts. Repositories use `self.session` (`repositories/base.py`).

`MissionRepository.increment_run_sequence(mission_id) -> int`:
```python
stmt = (
    update(Mission)
    .where(Mission.id == mission_id)
    .values(run_sequence_counter=Mission.run_sequence_counter + 1)
    .returning(Mission.run_sequence_counter)
)
return (await self.session.execute(stmt)).scalar_one()
```
The row lock taken by the UPDATE makes this race-free. Every `mission_runs` row, including SKIPPED and MISSED, consumes a sequence number, and an increment rolls back with the transaction or savepoint that contains it.

`MissionRunRepository`:
- `get_for_mission(mission_id, run_id) -> MissionRun | None`: `WHERE id=:id AND mission_id=:mid`.
- `lock_for_mission(mission_id, run_id) -> MissionRun | None`: the same predicate, `with_for_update()`.
- `get_active_for_mission(mission_id) -> MissionRun | None`: `status IN ACTIVE_RUN_STATUSES`.
- `get_latest_with_digest(mission_id) -> MissionRun | None`: joins `mission_run_digests`, ordered by `sequence DESC`.
- `get_by_sequence(mission_id, seq)`.
- `get_by_slot(schedule_id, scheduled_for)`.
- `insert_occurrence(*, id, mission_id, plan_id, schedule_id, sequence, scheduled_for, status, status_reason, status_detail, objective, workflow_definition_id, workflow_parameters, temporal_workflow_id, config_snapshot) -> MissionRun | None`. This is `INSERT ... ON CONFLICT ON CONSTRAINT uq_mission_runs_schedule_slot DO NOTHING RETURNING *`, returning `None` on conflict. `id` is generated by the caller so that `temporal_workflow_id` can be written in the same statement; it is NULL for SKIPPED and MISSED rows.
- `list_active_older_than(cutoff) -> list[MissionRun]`: `status IN ACTIVE_RUN_STATUSES AND updated_at < cutoff`.
- `list_for_mission(mission_id, *, statuses, limit, before_sequence)`: ordered by `sequence DESC`.

`MissionScheduleRepository`:
- `get_for_mission(mission_id, schedule_id) -> MissionSchedule | None`: `WHERE id=:sid AND mission_id=:mid`. The service raises `NotFoundError` on `None`.
- `lock(schedule_id) -> MissionSchedule | None`: `SELECT ... FOR UPDATE`.
- `list_by_mission(mission_id, include_archived)`.
- `list_syncable()`: every row whose `temporal_sync_state != 'SYNCED'`, plus every row with status ACTIVE or PAUSED.
- `count_non_archived(mission_id)`.

Other repositories:
- `MissionRunDigestRepository.get_by_run(run_id)`.
- `TaskRepository.list_by_run(run_id, status=None)`.
- `TaskRepository.adopt_backlog(plan_id, run_id, statuses: list[TaskStatus]) -> list[str]`: `UPDATE tasks SET mission_run_id=:run WHERE plan_id=:plan AND mission_run_id IS NULL AND status IN (...) RETURNING id`.
- `TaskRepository.release_to_backlog(run_id, statuses: list[TaskStatus]) -> int`: `UPDATE tasks SET mission_run_id=NULL WHERE mission_run_id=:run AND status IN (...)`.
- `TaskRepository.reconcile_tasks` gains keyword-only `scope_run_id: str | None` and `assign_run_id: str | None`. When `scope_run_id` is set, existing tasks are restricted to `mission_run_id = scope_run_id OR mission_run_id IS NULL`. New rows get `mission_run_id=assign_run_id`.

**Tests:**
- `test_mission_run_repository.py`:
  - `test_increment_run_sequence_concurrent`: 20 concurrent sessions each call `increment_run_sequence`, and the returned values are exactly `1..20`.
  - `test_increment_rolled_back_with_savepoint`: an increment inside `begin_nested()` that is rolled back leaves the counter unchanged.
  - `test_insert_occurrence_conflict_returns_none`.
  - `test_get_active_for_mission_ignores_terminal`.
  - `test_get_for_mission_rejects_other_mission`.
  - `test_list_for_mission_paginates_by_sequence`.
- `test_mission_schedule_repository.py`:
  - `test_get_for_mission_rejects_foreign_schedule`: a schedule of mission B, requested under mission A, returns `None`.
  - `test_lock_blocks_second_session`: a second `lock` waits until the first transaction commits.

**Done when:** `pytest tests/integration/backend/repositories -q -k "mission_run or mission_schedule"` passes.

---

### 88.1.5 Temporal DTOs, snapshot builders and `TemporalScheduleGateway`

**Files:**
- Modify (exists since Phase 0): `modules/backend/temporal/mission_run_models.py`.
- Modify (exists since 88.0.2): `modules/backend/temporal/config_snapshots.py`, `tests/unit/backend/temporal/test_config_snapshots.py`.
- Create: `modules/backend/temporal/schedule_gateway.py`, `tests/integration/backend/temporal/test_schedule_gateway.py`, `tests/integration/backend/temporal/conftest.py` (Phase 0 creates no conftest there).

**Current state:**
- 88.0.2 created `temporal/activity_options.py` with `retry_policy(p: RetrySnapshot)` and `activity_kwargs(p: ActivityPolicySnapshot)`, and the snapshot dataclasses. 88.0.10 added `ReconcilerInput{config_hash, orphan_grace_seconds, activity}`, `ReconcileInput`, `ScheduleSyncStats{synced, failed, deleted_orphans, completed}` and `ReconcileStats` (with `schedule_sync: ScheduleSyncStats | None`, always `None` until 88.1.10). This step adds no retry helper; every Plan 88 workflow imports those two functions.
- Nothing wraps the Temporal Schedule APIs: `main.py:79-115` calls `create_schedule` directly and swallows `ScheduleAlreadyRunningError` at `:111`.

**Change:**
1. **`mission_run_models.py` (add).** Copy from contract 3.3.4: `RunConfigSnapshot`, `TickConfigSnapshot`, `PendingGate`, `MissionRunWorkflowInput`, `MissionScheduleTickInput`, `GateDecisionUpdate`, `GateDecisionAck`, `PauseRequest`, `ResumeRequest`, `TasksApprovedSignal` and `MissionRunWorkflowStatus`, with these Phase 1 rules:
   - `RunConfigSnapshot` has exactly the fields `config_hash`, `task_queue`, the eight run activity policies (every `mission_run.activities` key except `claim`, which goes to `TickConfigSnapshot`), `gate_escalate_after_seconds`, `gate_pause_after_seconds`, `gate_points_enabled`, `refine_wait_seconds`, `continue_as_new_after_iterations` and `max_parallel_tasks`. 88.2.2 adds `max_run_duration_seconds` and `task_heartbeat_interval_seconds`.
   - `MissionRunWorkflowState` has exactly these fields in Phase 1: `iteration: int`, `session_id: str`, `execution_record_id: str`, `context_version_start: int`, `pending_gate: PendingGate | None`, `pause_requested: bool`, `paused: bool`, `last_supervisor_action: str | None`, `approved_seq: int` (contracts 3.3.3 wake-up counter) and `decision: GateDecisionUpdate | None`. 88.2.7 adds `last_can_iteration`; Phase 2 adds its own fields.

   Add these Phase 1 dataclasses, with fields from the 3.3.5 table:
   - `ClaimOccurrenceInput`, `ClaimOccurrenceResult` and `NotificationRequest`;
   - `BeginRunInput`, `BeginRunResult`, `PlanRunInput`, `PlanRunResult` and `RunTaskGraph`;
   - `RunStatusUpdate`, `FinaliseRunInput` and `FinaliseRunResult`. Their `status` and `reason` fields carry `MissionRunStatus` and `MissionRunStatusReason` **values** (lowercase strings), and `reason` is `str | None`. Every DTO status, reason, kind, channel and phase string is the lowercase enum value (3.0.2), including `PlanRunResult.status` (`"planned"`, `"empty"`, `"failed"`), `MissionRunWorkflowStatus.phase` and `NotificationRequest.kind`; activities parse with `Enum(value)`, never `Enum[name]`;
   - `DirectorTurnInput`;
   - `ExecuteWaveInput{mission_run_id: str, session_id: str, execution_record_id: str}`.

   `ScheduleSyncStats` exists since 88.0.10 and is not redefined.
2. **`config_snapshots.py` (add).** It is not a workflow module, so it may read config. `config_hash` and `policy_snapshot` exist since 88.0.2 and are not redefined.
   - Create `def build_run_config_snapshot() -> RunConfigSnapshot` and `def build_tick_config_snapshot() -> TickConfigSnapshot`. These are the only places the two snapshots are built. Map `temporal.mission_run` 1:1 into the dataclasses with `policy_snapshot`. `gate_escalate_after_seconds` is `temporal.approval_timeout_seconds` and `gate_pause_after_seconds` is `temporal.escalation_timeout_seconds` until 88.4.8 switches them to `gate.durable.*`. `gate_points_enabled` comes from `gate.yaml points.*.enabled`. Set `config_hash` last with `config_hash(...)`.
   - 88.2.2 extends `build_run_config_snapshot` with the fields marked `# 88.2.2` and adds `build_workflow_timeouts_snapshot()` to this module. No `MissionRunService` method builds a snapshot at any step.
3. **`schedule_gateway.py` (create).**
   ```python
   class TemporalScheduleGateway:
       """The only module, besides system_schedules.py, that imports temporalio.client.Schedule*."""

       def __init__(self, client: Client, task_queue: str) -> None:
           self._client = client
           self._task_queue = task_queue

       @classmethod
       async def create(cls) -> "TemporalScheduleGateway":
           """get_temporal_client() and get_app_config().temporal.task_queue."""
           ...

       async def upsert(self, schedule_id: str, schedule: Schedule) -> None:
           """create_schedule; on ScheduleAlreadyRunningError,
           handle.update(lambda _: ScheduleUpdate(schedule=schedule))."""
           ...

       async def set_paused(self, schedule_id: str, paused: bool, note: str) -> None:
           """handle.pause(note=note) or handle.unpause(note=note)."""
           ...

       async def delete(self, schedule_id: str) -> None:
           """RPCError NOT_FOUND returns normally."""
           ...

       async def describe(self, schedule_id: str) -> ScheduleDescription | None:
           """RPCError NOT_FOUND returns None."""
           ...

       async def list_matching_times(self, schedule_id: str, start: datetime, end: datetime) -> list[datetime]:
           """client.workflow_service.list_schedule_matching_times(ListScheduleMatchingTimesRequest(
           namespace=client.namespace, schedule_id=schedule_id, start_time=start, end_time=end)),
           returned as timezone-aware UTC datetimes."""
           ...

       async def list_ids(self, prefix: str | None) -> list[str]:
           """Iterates client.list_schedules(); filters on prefix when given."""
           ...

       async def validate_spec(self, spec: ScheduleSpec, window: timedelta) -> list[datetime]:
           """Creates a paused probe schedule with id f"mission-schedule-probe-{uuid4().hex}" whose action is
           ScheduleActionStartWorkflow("MissionScheduleProbe", id=f"{probe_id}-wf", task_queue=self._task_queue).
           Returns list_matching_times(probe_id, now, now + window). Deletes the probe in finally.
           RPCError INVALID_ARGUMENT raises ValidationError(str(err.message))."""
           ...
   ```
   The probe is paused, so its workflow type is never started and need not exist.

**Tests:**
- `test_config_snapshots.py`:
  - `test_build_run_config_snapshot_hash_matches`: `snap.config_hash == config_hash(snap)`.
  - `test_build_tick_config_snapshot_hash_matches`.
- `test_schedule_gateway.py` (integration). `conftest.py` provides a session-scoped `temporal_env` fixture from `WorkflowEnvironment.start_local(namespace="default")`; the binary is prefetched in CI by 88.0.1.
  - `test_upsert_creates_then_updates`: upsert with cron `0 * * * *`, then `30 * * * *`. `describe().schedule.spec.cron_expressions` holds the second value. This is the fix for `main.py:111-115`.
  - `test_delete_missing_is_noop`.
  - `test_list_matching_times_respects_time_zone`: cron `0 6 * * 1`, `Europe/London`, 14-day window. Two results, each at 06:00 London time converted to UTC.
  - `test_validate_spec_rejects_bad_cron`: `"61 * * * *"` raises `ValidationError`, and `list_ids("mission-schedule-probe-")` is empty afterwards.
  - `test_validate_spec_returns_times_and_cleans_up`.

**Done when:** both test files pass, `grep -rn "def config_hash\|def policy_snapshot" modules` lists only `temporal/config_snapshots.py`, and `grep -rlnE "client\.create_schedule|\.get_schedule_handle\(|ScheduleHandle" modules/backend --include=*.py` lists only `temporal/schedule_gateway.py`, `temporal/system_schedules.py` and `main.py` (the API-lifespan registration, which drops out in 88.1.10).

---

### 88.1.6 `MissionScheduleService`, including `claim_occurrence`

**Files:**
- Create: `modules/backend/services/mission_schedule.py`, `modules/backend/services/mission_schedule_claim.py`, `modules/backend/schemas/mission_schedule.py`, `modules/backend/core/redaction.py`, `modules/backend/events/base.py`, `modules/backend/events/mission_run_types.py`, `tests/unit/backend/core/test_redaction.py`, `tests/integration/backend/services/test_mission_schedule_service.py`, `tests/integration/backend/services/test_claim_occurrence.py`.
- Modify: `modules/backend/events/types.py`.

`mission_schedule_claim.py` holds `claim_occurrence`, which keeps `mission_schedule.py` under 500 lines. `core/redaction.py` is created here, and only here, because this step stores the first external error text (`temporal_sync_error`); 88.4.4, 88.4.8 and 88.4.9 import it. The new events go in `events/mission_run_types.py` because `events/types.py` is already 918 lines (3.6.1).

**Current state:**
- **No validation of the schedule target.** The deleted create path accepted any definition and hard-coded `created_by="user:api"` (`missions_workflows.py:674` at `a28ca771`).
- **No schedule or run events.** `MissionPlanDispatchedEvent` is at `events/types.py:517`, `MissionPlanRunCompletedEvent` at `:589`, `SessionEvent` at `:31-41` and `EVENT_TYPE_MAP` at `:823`.

**Change:**
1. **Redaction (`core/redaction.py`).**
   ```python
   _PATTERNS = (
       (re.compile(r"bot\d+:[A-Za-z0-9_-]+"), "bot<redacted>"),
       (re.compile(r"g:[A-Za-z0-9_-]{22}:"), "g:<redacted>:"),
   )

   def redact_secrets(text: str) -> str:
       for pattern, replacement in _PATTERNS:
           text = pattern.sub(replacement, text)
       return text
   ```
   The patterns, their order and the replacements are those of 3.5.5. 88.4.4 imports this module and adds `test_delivery_error_redacts_bot_token` to its notification tests; no later step redefines it. Every service in this phase that stores exception text (`temporal_sync_error`, `mission_runs.status_detail`) or puts it in an event payload passes it through `redact_secrets` first.
2. **Schemas (`schemas/mission_schedule.py`).** Enum fields use lowercase values on the wire (contracts 3.0.2).
   - **`MissionScheduleCreate`** carries the fields from 3.5.3:
     - `name` matches `^[a-z0-9][a-z0-9-]{0,99}$`;
     - `kind: MissionScheduleKind`;
     - `cron_expression` has exactly 5 whitespace-separated fields (validator), and `@` forms are rejected;
     - `time_zone_name` is validated with `zoneinfo.ZoneInfo`;
     - `catch_up_window_seconds: int | None`.
   - **`MissionScheduleUpdate`** has the same fields, all optional, without `kind`; `extra="forbid"` makes a `kind` key a 422.
   - **`MissionScheduleResponse`** (`from_attributes`) carries every column plus `next_fire_times: list[datetime]`.
   - **`OccurrenceClaim`** (internal dataclass): `outcome`, `run`, `notifications` and `recorded: list[MissionRun]`.
3. **Spec construction.** A private `_build_spec(cron_expression, time_zone_name, starts_at, ends_at) -> ScheduleSpec` returns `ScheduleSpec(cron_expressions=[cron_expression], time_zone_name=time_zone_name, start_at=starts_at, end_at=ends_at)`. `create_schedule`, `update_schedule` and `sync_to_temporal` all use it.
4. **`create_schedule(mission_id, data, user_id)`.** Order:
   1. **Recurrence enabled.** `recurrence.enabled` must be true, else `ValidationError("recurrence disabled")`. This is a config read, not DB access, so it precedes the probe.
   2. **Spec probe, before any DB access.** `times = await self._gateway.validate_spec(_build_spec(...), window=timedelta(days=8))`. If any consecutive gap is less than `min_interval_seconds`, raise `ValidationError(f"cron fires every {gap}s; minimum {minimum}s")`. With fewer than two times in the window there is no gap to check.
   3. **Mission status.** The mission `status != ARCHIVED`.
   4. **Gate mode.** `plan = await MissionPlanService(self._session).get_or_create_plan(mission_id)`. If `plan.gate_mode == GateMode.INTERACTIVE`, raise `ValidationError`.
   5. **Schedule limit.** `count_non_archived(mission_id) < max_schedules_per_mission`.
   6. **Target.**
      - **OBJECTIVE.** `len(objective_template) <= objective_template_max_chars`. Placeholders are parsed with `string.Formatter().parse` and must be a subset of `{scheduled_for, sequence, mission_name}`, with no format spec and no conversion.
      - **WORKFLOW_DEFINITION.** The definition exists and belongs to the mission or is a system template (`mission_id IS NULL`). It is enabled. Every step has `node_type == "agent_step"`, else `ValidationError` naming the offending step ids (OPEN 3.7.2). `validate_workflow_parameters(schema.parameters, data.workflow_parameters)` returns no errors.
   7. **Catch-up window.** `catch = data.catch_up_window_seconds` when not None, else `recurrence.default_catch_up_window_seconds`; `catch <= max_catch_up_window_seconds`.
   8. **Insert.** Insert with `status=ACTIVE`, `temporal_sync_state=PENDING`, `created_by_user_id=user_id` and `last_claimed_scheduled_for=utc_now()`. Save `schedule_id` to a local, then commit.
   9. **Sync.** `await self.sync_to_temporal(schedule_id)`, then emit `MissionScheduleChangedEvent(from_status=None, to_status="active")`.
5. **`update_schedule`.**
   - Load with `get_schedule(mission_id, schedule_id)`, copy the effective spec fields (new value when present, else stored) to locals, and commit to end the read transaction.
   - When `cron_expression`, `time_zone_name`, `starts_at` or `ends_at` is present, run the step 4.2 probe and gap check on the effective spec.
   - Reload with `lock`, apply the create-time checks for the fields present, and write.
   - If `cron_expression`, `time_zone_name` or `starts_at` changes, set `last_claimed_scheduled_for = utc_now()`. This stops the next claim backfilling MISSED slots generated by the new spec.
   - **Reopening a completed schedule.** `COMPLETED` moves to `ACTIVE` when `max_runs` is raised above `executed_run_count`, or when `ends_at` moves into the future (3.2.3). Clear `completed_reason` when it does.
   - Commit, then sync.
6. **`pause_schedule`, `resume_schedule`, `archive_schedule`.** Each loads with `get_schedule(mission_id, schedule_id)`, checks the 3.2.3 transition and writes. `resume_schedule` also sets `last_claimed_scheduled_for = utc_now()` and re-checks the gate-mode rule, so slots during a schedule pause are not backfilled. Commit, sync and emit `MissionScheduleChangedEvent`.
7. **`sync_to_temporal(schedule_id) -> TemporalSyncState`.**
   - Reload the schedule and its mission with no lock, save the fields to locals, and commit.
   - **Target state.** Absent when `status in {COMPLETED, ARCHIVED}` or `recurrence.enabled` is false. Otherwise present, with `paused = not (schedule.status == ACTIVE and mission.status == ACTIVE)` (3.2.2).
   - **Absent.** `gateway.delete(temporal_schedule_id)`.
   - **Present.** Build the `Schedule` from 3.3.2 with `_build_spec`. The action input is `MissionScheduleTickInput(mission_schedule_id=schedule_id, config=snapshot)` where `snapshot = build_tick_config_snapshot()` (`temporal/config_snapshots.py`, 88.1.5). `note` is `"mission_" + mission.status.value` when the mission is not ACTIVE, else `schedule.status.value`; 88.4.5 switches the mission case to `mission.paused_reason`. Call `gateway.upsert`.
   - **Record the result.** On success write `temporal_sync_state=SYNCED`, `temporal_synced_at=utc_now()`, `temporal_sync_error=None` and `tick_config_hash=snapshot.config_hash`. On `RPCError` or `ExternalServiceError` write `FAILED` and `temporal_sync_error=redact_secrets(str(err))`, log at error, emit `MissionScheduleSyncFailedEvent` and return `FAILED`; nothing is raised. Commit.
8. **`sync_mission(mission_id)`.** Calls `sync_to_temporal` for each non-archived schedule and sums the results into `ScheduleSyncStats`.
9. **`sync_all()`.**
   1. For each `list_syncable()` row with `ends_at < now` and status ACTIVE or PAUSED, set `COMPLETED/END_DATE_REACHED` and commit.
   2. Call `sync_to_temporal` for every syncable row.
   3. **Orphan sweep.** `ids = await gateway.list_ids("mission-schedule-")`. Delete every id with no matching `mission_schedules.temporal_schedule_id` row; this includes `mission-schedule-probe-*`. Count them as `deleted_orphans`. Rows that are `COMPLETED` or `ARCHIVED` were already removed by step 2.
10. **`next_fire_times(schedule, count)`.** `describe(...).info.next_action_times[:count]`, or `[]` when the schedule is absent.
11. **`claim_occurrence(schedule_id, scheduled_for) -> OccurrenceClaim`** (`services/mission_schedule_claim.py`). It runs in one transaction and implements the 3.3.2 algorithm with these specifics:
    - **Lock and duplicate check.** `sched = await repo.lock(schedule_id)`; a missing row raises `NotFoundError`. Duplicate: `get_by_slot(schedule_id, scheduled_for)` returns `DUPLICATE` with that row. `run_input` is set only when that row is PENDING, so the tick can start it.
    - **Recurrence disabled.** After the duplicate check, when `recurrence.enabled` is false the claim refuses the tick: it inserts no backfill, records this slot as `SKIPPED/SCHEDULE_NOT_ACTIVE` with an allocated sequence, advances the watermark, leaves `run_input` as `None` and logs at warning. The tick workflow therefore starts no run.
    - **Backfill.** `now = utc_now()`, `lower = sched.last_claimed_scheduled_for or sched.created_at`, `upper = min(scheduled_for, now - timedelta(seconds=sched.catch_up_window_seconds))`. When `lower < upper`, insert `MISSED/NOT_FIRED` for each `t` in `list_matching_times(sched.temporal_schedule_id, lower, upper)` with `lower < t < upper`, using `insert_occurrence(..., sequence=await increment_run_sequence(mission_id))`. Only slots that Temporal will never deliver are backfilled; slots inside the catch-up window are left to their own ticks. The bound is `now`-relative, not `scheduled_for`-relative: when ticks buffered during an outage arrive earliest first, the first tick advances the watermark, and a `scheduled_for`-relative bound would leave the oldest undelivered slots unrecorded. The gateway call happens with the row lock held; this is the one deliberate external call inside a transaction, bounded by the `claim` activity's 60s timeout.
    - **Outcome rules,** first match wins (3.3.2 step 3 without the budget rule, which 88.4.6 adds): `SKIPPED/SCHEDULE_NOT_ACTIVE`, `SKIPPED/MISSION_NOT_ACTIVE`, `MISSED/OUTSIDE_CATCHUP_WINDOW` (`now - scheduled_for > catch_up_window_seconds`), `MISSED/SUPERSEDED` (any matching time in `(scheduled_for, now]`, from `list_matching_times(id, scheduled_for + timedelta(microseconds=1), now)`), `SKIPPED/OVERLAP` (an active run exists), `SKIPPED/MAX_RUNS_REACHED`, else RUN.
    - **Run insert.**
      - **Objective.** `objective_template.format(scheduled_for=scheduled_for.astimezone(ZoneInfo(tz)).isoformat(), sequence=seq, mission_name=mission.name)`.
      - **Savepoint.** Inside one `session.begin_nested()`: `seq = await increment_run_sequence(mission_id)`, generate `run_id = str(uuid4())`, and insert `trigger=SCHEDULE`, `status=PENDING`, `plan_id=plan.id`, `temporal_workflow_id=mission_run_workflow_id(run_id)`, `config_snapshot=dataclasses.asdict(snapshot)`, and `workflow_definition_id` and `workflow_parameters` copied from the schedule.
      - **Overlap race.** On `IntegrityError` whose constraint is `uq_mission_runs_one_active`, the savepoint rolls back, including the increment. Then `seq = await increment_run_sequence(mission_id)` again and insert `SKIPPED/OVERLAP` with that sequence. This covers a manual `start_run` racing the claim, and leaves no sequence gap.
      - Increment `executed_run_count`.
    - **Completion on max runs.** When `executed_run_count == max_runs` after the increment, set `COMPLETED/MAX_RUNS_REACHED`. After commit the activity calls `sync_to_temporal`, which deletes the Temporal schedule.
    - **Watermark.** `last_claimed_scheduled_for = max(existing, scheduled_for)`.
    - **Return.**
      - The run, when one was inserted.
      - `run_input = MissionRunWorkflowInput(mission_run_id=run_id, mission_id=mission_id, plan_id=plan.id, config=snapshot)`, where `snapshot = build_run_config_snapshot()` (`temporal/config_snapshots.py`, 88.1.5).
      - Notifications: one `RUN_MISSED` whose `payload["count"]` is the number of MISSED rows this claim inserted, and one `RUN_SKIPPED` when this tick was skipped. `subject_id` is `f"{schedule_id}:{scheduled_for.isoformat()}"`.
      - Emit `MissionRunCreatedEvent` for a RUN, and `MissionRunOccurrenceRecordedEvent` (with `count`) for SKIPPED and MISSED, after commit.
12. **Events (`events/base.py`, `events/mission_run_types.py`).** Move `SessionEvent` verbatim from `events/types.py:31-41` to `events/base.py`; `events/types.py` imports it from there. Add `MissionRunCreatedEvent`, `MissionRunStatusChangedEvent`, `MissionRunOccurrenceRecordedEvent`, `MissionScheduleChangedEvent` and `MissionScheduleSyncFailedEvent` exactly as in 3.6.1 to `events/mission_run_types.py`, importing `SessionEvent` from `events.base`, and register them in `EVENT_TYPE_MAP` in `events/types.py`. `MissionPlanDispatchedEvent` and `MissionPlanRunCompletedEvent` are deleted in 88.1.7 and 88.1.8, with their emitters.

**Tests:**
- `test_redaction.py`:
  - `test_redacts_bot_token`: `"https://api.telegram.org/bot123:AA-b_c/sendMessage"` contains no `123:AA-b_c`.
  - `test_redacts_action_token`.
  - `test_redacts_provider_key`, `test_redacts_bearer`, `test_redacts_url_credentials`, `test_redacts_key_value_secret`, `test_redacts_github_token` and `test_redacts_aws_key`: one input per 3.5.5 pattern 3 to 8, which decision 15 needs (contracts 3.8.1).
  - `test_redacts_env_style_names`: every `NAME=` line of `config/.env.example`, given a value, is redacted in both `NAME=value` and `NAME: value` form.
- `test_mission_schedule_service.py`. Integration tests with a real DB; `TemporalScheduleGateway` is replaced by an in-memory `FakeScheduleGateway` defined in the test module.
  - `test_create_rejects_when_recurrence_disabled`: with `recurrence.enabled` patched to false, `ValidationError` is raised and the fake's `validate_spec` is never called.
  - `test_create_rejects_interactive_gate_mode`.
  - `test_create_rejects_unknown_placeholder`: `"{foo}"` raises `ValidationError`.
  - `test_create_rejects_non_agent_steps`: a definition with a `human_input` step raises, and the message names the step.
  - `test_create_rejects_sub_minimum_interval`: the fake returns times 60s apart, and `min_interval_seconds=300` raises.
  - `test_create_probes_before_db_access`: the fake's `validate_spec` raises; the session has executed no statement (asserted with a SQLAlchemy `before_cursor_execute` listener).
  - `test_create_commits_before_sync`: the fake's `upsert` asserts the row is visible from a second session.
  - `test_sync_failure_marks_failed_and_returns_row`: `upsert` raises `RPCError` whose message contains `bot123:secret`. The row is `FAILED`, `temporal_sync_error` contains `<redacted>` and not `123:secret`, and no exception propagates.
  - `test_effective_state_paused_when_mission_paused`.
  - `test_get_for_other_mission_404`.
  - `test_update_cron_resets_watermark`.
  - `test_resume_resets_watermark`.
  - `test_sync_all_completes_end_date_and_deletes_orphans`: a `mission-schedule-<random uuid>` id with no row and a `mission-schedule-probe-x` id are deleted; an id with a row is kept.
- `test_claim_occurrence.py`. Integration tests with the fake gateway and a patched `utc_now`:
  - `test_run_outcome_inserts_pending_and_increments`: the row has `temporal_workflow_id == mission_run_workflow_id(run.id)` and a non-empty `config_snapshot`.
  - `test_recurrence_disabled_skips_tick`: with `recurrence.enabled` patched to false, the slot is `SKIPPED/SCHEDULE_NOT_ACTIVE`, no MISSED row is inserted and `run_input` is `None`.
  - `test_duplicate_slot_returns_duplicate`.
  - `test_duplicate_pending_returns_run_input`.
  - `test_overlap_records_skipped`.
  - `test_outside_catch_up_window_records_missed`.
  - `test_superseded_when_later_slot_due`.
  - `test_backfill_records_only_undeliverable_slots`: hourly slots, watermark `T-10h`, `catch_up_window_seconds=7200`, claim of `scheduled_for=T` at `now=T+10s`. Rows `MISSED/NOT_FIRED` exist for `T-9h` to `T-2h` (8 rows), no row exists for `T-1h`, the `T` tick is RUN, and the `RUN_MISSED` payload count is 8.
  - `test_out_of_order_ticks_record_every_slot`: hourly slots, watermark `T-10h`, window 6h, `now=T+10s`; ticks for `T-5h` to `T` are claimed earliest first. Every slot from `T-9h` to `T` has exactly one row; `T-9h` to `T-6h` are `MISSED/NOT_FIRED`, `T-5h` to `T-1h` are `MISSED/SUPERSEDED`, and `T` is the only RUN.
  - `test_max_runs_completes_schedule`.
  - `test_concurrent_claims_serialise`: two sessions claim adjacent slots concurrently, and exactly one RUN row exists. The later slot is RUN and the earlier is MISSED/SUPERSEDED, or the earlier is RUN and the later is SKIPPED/OVERLAP.
  - `test_manual_run_race_records_overlap`: an active MANUAL run is inserted inside the claim's savepoint window. The result is SKIPPED/OVERLAP with no exception, and the mission's sequences are contiguous.
  - `test_sequence_monotonic_across_outcomes`.

**Done when:** the three test files pass, `wc -l modules/backend/services/mission_schedule*.py` shows each file at 500 lines or fewer, and `grep -n "^class SessionEvent" modules/backend/events/types.py` is empty.

---

### 88.1.7 `MissionRunService` and run-scoped tasks

**Files:**
- Create: `modules/backend/services/mission_run.py`, `modules/backend/services/workflow_task_mapping.py`, `modules/backend/schemas/mission_run.py`, `modules/backend/repositories/llm_ledger.py`, `tests/integration/backend/services/test_mission_run_service.py`, `tests/integration/backend/temporal/test_workflow_gateway.py`, `tests/unit/backend/services/test_workflow_task_mapping.py`, `tests/unit/backend/mission_control/test_mission_dispatch.py`.
- Modify:
  - `services/mission_plan_dispatch.py`, `services/mission_plan_orchestrator.py`, `services/mission_plan_taskio.py`, `services/workflow_run.py`;
  - `temporal/workflow_ids.py` (exists since 88.0.3), `temporal/workflow_gateway.py` (exists since 88.0.3);
  - `temporal/activities.py` (`persist_mission_outcome`), `events/types.py`, `core/exceptions.py`;
  - `agents/mission_control/mission_dispatch.py` (`handle_mission`) and every `handle_mission(` call site (`grep -rn "handle_mission(" modules`).
- **Deviation (Phase 1 verification):** `mission_run.py` reached 707 lines against the 500-line limit in Verification item 2. `begin`, `plan`, `approve_proposed`, `task_graph`, `finalise` and `_start_for_raced_approvals`, with `_notification_kind` and the `RUN_*` kinds, moved verbatim to `services/mission_run_lifecycle.py` as `MissionRunLifecycleMixin`, mixed into `MissionRunService` (the `WorkflowRunWavesMixin` pattern). The public API is unchanged; `RUN_SUCCEEDED` is now imported from `mission_run_lifecycle`.
- Delete: `services/mission_plan_supervisor.py`, `scripts/verify_budget_enforcement.py`.

**Current state:**
- **Plan-keyed workflow id.** 88.0.3 made every run of a plan share `mission_run_workflow_id(plan_id)`. A run model needs one id per run.
- **One ExecutionRecord per wave.** `dispatch_approved` creates a record for every wave through `create_early_execution_record` (`mission_plan_dispatch.py:240-249,381-426`).
- **Duplicate record fallback.** `persist_mission_results` already updates the given record and never calls `save_execution` when `execution_record_id` is passed (`agents/mission_control/persistence_bridge.py:62-80`). But the `persist_mission_outcome` fallback (`temporal/activities.py:265-273`) calls it without an id, which inserts a second record (`services/execution_persistence.py:76`).
- **Synchronous planning in `run_objective`.** `MissionPlanOrchestrator.run_objective` (`mission_plan_orchestrator.py:360-481`) plans synchronously and then starts a workflow.
- **Plan-wide scope.** `refine` feeds the whole plan to the planner (`mission_plan_orchestrator.py:189` via `materialize_plan_dict`, `mission_plan_taskio.py:25-57`) and reconciles plan-wide (`:73-120`).
- **Step-to-task mapping buried in a private method.** It lives in `WorkflowRunService._persist_workflow_as_plan` (`workflow_run.py:442-520`), loop body `:466-486`. 88.0.6 already deleted the `workflow_managed` assignment.
- **Dead inline supervisor.** `dispatch_approved`'s inline branch (`mission_plan_dispatch.py:344-362`) runs only when `skip_post_run_supervisor` is false. Its only callers are `execute_mission` (which passes `True`) and `scripts/verify_budget_enforcement.py:218`, so `services/mission_plan_supervisor.py` has no other caller.
- **Workflow handles.** `TemporalWorkflowGateway` (88.0.3) has `state`, `cancel` and `terminate`, but cannot start a run workflow. For `MissionRunWorkflow`, `MissionScheduleTickWorkflow`, `ReconcilerWorkflow` and `RetentionWorkflow`, it and `TemporalScheduleGateway` are the only owners of workflow handles; no other module calls `client.start_workflow` or `get_workflow_handle` for them. Other existing workflows (chat, tool fork, plan refine, human input, workflow-run) are out of scope and untouched.
- **Misnamed `handle_mission` parameter.** Its first positional is called `mission_run_id` (`agents/mission_control/mission_dispatch.py:46`), but every caller passes a plan id or a label such as `f"mission-{session_id}"`. Phase 1 introduces real MissionRun ids, so the name becomes misleading here.

**Change:**
1. **Workflow id (`temporal/workflow_ids.py`).** `mission_run_workflow_id(mission_run_id: str) -> str` returns `f"mission-run-{mission_run_id}"`. Every call site in this plan passes a run id; the plan-keyed call sites are deleted in 88.1.7, 88.1.8, 88.1.10a and 88.1.11. The 88.0.3 Done-when grep stays valid: no other module writes the `mission-run-{` literal.
2. **Gateway (`temporal/workflow_gateway.py`).** Add `async def start_mission_run(self, inp: MissionRunWorkflowInput) -> None`. It calls `self._client.start_workflow(MissionRunWorkflow.run, inp, id=mission_run_workflow_id(inp.mission_run_id), task_queue=inp.config.task_queue, id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE)` and raises `ExternalServiceError` on `RPCError` or `WorkflowAlreadyStartedError`. 88.1.9 adds `signal`.
2a. **Start rejection (`core/exceptions.py`).** Add `class RunStartRejectedError(ValidationError)`. `begin` raises it for an invalid gate mode (`FAILED/INVALID_GATE_MODE`) and for an owner who is not a platform user (`FAILED/START_FAILED`). `NON_RETRYABLE` in `temporal/activity_options.py` (3.3.4) already carries the string `"RunStartRejectedError"` since 88.0.2. There is no `GateModeInvalidError`.
2b. **`handle_mission` rename (P3, no alias).** Rename the first parameter of `handle_mission` from `mission_run_id` to `execution_label`, and every use inside the function body. Change every `mission_run_id=` argument at the `handle_mission(` call sites to `execution_label=` (`services/mission_plan_dispatch.py:292`, `services/workflow_run_waves.py:656`, `agents/mission_control/mission_control.py:166`, `api/v1/endpoints/executions.py:300`, `clients/cli/execution_cmds.py:153,216`, `clients/tui/services/service_bridge.py:156`; `mission_plan_supervisor.py:211` is deleted below). 88.3.5 adds a separate keyword `mission_run_id: str | None` for the real run id.
3. **`schemas/mission_run.py`.** Enum fields use lowercase values on the wire (contracts 3.0.2).
   - `MissionRunCreate{objective: str}`, length 1 to `recurrence.objective_template_max_chars`.
   - `MissionRunResponse`, with every column of the run.
   - `MissionRunDetailResponse{run, digest: MissionRunDigestResponse | None, tasks: list[TaskSummary]}`. 88.4.8 adds `gates`.
   - `MissionRunListResponse{runs, next_before_sequence: int | None}`.
4. **`services/workflow_task_mapping.py`.**
   - `def steps_to_task_definitions(workflow: WorkflowSchema, parameters: dict) -> list[TaskDefinition]`. Move the loop body from `workflow_run.py:466-486` here.
     - **Parameters.** Each task's `inputs.static = {**(step.input or {}), "workflow_parameters": resolved}`, where `resolved = {p.key: parameters.get(p.key, p.default) for p in workflow.parameters}`.
     - **Step types.** Any step whose `node_type != "agent_step"` raises `ValidationError` naming the step.
   - `_persist_workflow_as_plan` calls this function.
5. **`services/mission_plan_taskio.py`.**
   - `materialize_plan_dict(plan, *, mission_run_id: str | None)` includes only tasks with `mission_run_id == mission_run_id` or `mission_run_id IS NULL`. A NULL argument means backlog only.
   - `reconcile_tasks(orchestrator, plan, new_plan, *, mission_run_id: str | None)` passes `scope_run_id=mission_run_id` and `assign_run_id=mission_run_id`. When `mission_run_id` is None it looks up `MissionRunRepository.get_active_for_mission` and uses that run's id, so tasks created by a Director refine during an active run join the run.
6. **`MissionPlanOrchestrator`.**
   - `refine` and `_persist_plan` gain a keyword-only `mission_run_id: str | None`, threaded to item 5.
   - Delete `run_objective` (`:360-481`), `dispatch_autonomous` (`:484-495`) and the `dispatch_approved` wrapper's `skip_post_run_supervisor` parameter (`:497-517`).
7. **`mission_plan_dispatch.py`.**
   - Delete `dispatch_autonomous`, `start_temporal_run_workflow`, `create_early_execution_record` and the `MissionPlanDispatchedEvent` emit (`:332-342`). Delete `MissionPlanDispatchedEvent` from `events/types.py:517` and `EVENT_TYPE_MAP`.
   - `dispatch_approved(orchestrator, mission_run_id: str, user_id: str, *, session_id: str, execution_record_id: str)`:
     - Load the run and its plan.
     - Approved tasks are `TaskRepository.list_by_run(mission_run_id, status=APPROVED)`.
     - Pass `execution_record_id` to `handle_mission`, so inline persistence updates the run's record.
     - Delete the inline-supervisor branch (`:344-362`) and the `skip_post_run_supervisor` parameter. Delete `services/mission_plan_supervisor.py`, whose only entry point that branch was.
   - The budget check (`:185-192`), derivation (`:285-287`) and spend accumulation (`:318`) stay until 88.4.1.
8. **`persist_mission_outcome` (`temporal/activities.py`).** Its signature becomes `(mission_run_id: str, session_id: str, outcome_json: dict, mission_id: str, execution_record_id: str)`. The fallback path calls `persist_mission_results(..., roster_name=None, execution_record_id=execution_record_id)`, so it updates the run's record and never inserts. `AgentMissionWorkflow` (`temporal/workflow.py:101-102,163-164`) also calls it; that path already fails at `a28ca771` (item 2 of 88.1.8's Current state) and is deleted in 88.2.6.
9. **Delete `scripts/verify_budget_enforcement.py`.** It tests the deleted daemon query and the old `dispatch_approved` signature. Budget enforcement is re-specified and tested in 88.4.6.
10. **`services/mission_run.py`.** Implement the 3.5.1 `MissionRunService` signatures, with these exact behaviours. Every stored exception text goes through `redact_secrets`.
    - **`start_run(mission_id, *, trigger, objective, user_id, session_id)`.**
      - **Preconditions.** The mission is ACTIVE, else `ConflictError`. `user_id` parses as a UUID and names an existing user (`UserRepository.get_by_id_or_none`), else `ValidationError("user is not a platform user")`. `plan = await get_or_create_plan(mission_id)`.
      - **Insert** in the session's transaction: `seq = await increment_run_sequence(mission_id)`, `run_id = str(uuid4())`, then `PENDING` with `objective`, `session_id`, `triggered_by_user_id=user_id`, `temporal_workflow_id=mission_run_workflow_id(run_id)` and `config_snapshot=dataclasses.asdict(snapshot)`, where `snapshot = build_run_config_snapshot()` (`temporal/config_snapshots.py`, 88.1.5).
      - **Conflict.** On `IntegrityError` naming `uq_mission_runs_one_active`, `await self._session.rollback()`, which also rolls back the counter increment, then load the active run in a fresh transaction and raise `ConflictError(f"run #{active.sequence} is {active.status.value}")`. No savepoint is used.
      - **Commit, then start.** `await gateway.start_mission_run(MissionRunWorkflowInput(mission_run_id=run_id, mission_id=mission_id, plan_id=plan.id, config=snapshot))`, where `gateway = await TemporalWorkflowGateway.connect()`.
      - **Failures.** On any exception from the start, call `transition(run_id, FAILED, START_FAILED, redact_secrets(str(err)))` and raise `ExternalServiceError`.
    - **`on_tasks_approved`** is added in 88.1.9, with the gateway's `signal`.
    - **`get_run(mission_id, run_id_or_sequence)`.** All digits resolve through `get_by_sequence`; anything else through `get_for_mission`. `None` raises `NotFoundError`.
    - **`cancel_run(mission_id, run_id, user_id, reason)`.** Load with `lock_for_mission(mission_id, run_id)`; `None` raises `NotFoundError` (contracts 3.0.2). The run must be active, else `ConflictError`.
      - **Record the request.** Set `cancel_requested_at`, `cancel_requested_by_user_id` and `cancel_reason`.
      - **PENDING with no workflow start yet** (`started_at IS NULL`): transition to `CANCELLED/CANCELLED_BY_USER` and commit. A workflow that starts later fails `begin` with `MissionRunStateError`.
      - **Otherwise:** save `temporal_workflow_id`, commit, then `gateway.cancel(workflow_id)`.
    - **`transition(run_id, target, reason, detail)`.**
      - Lock the row (`FOR UPDATE`) and call `MissionRun.transition_status`.
      - **Terminal targets.** Also set the run's ExecutionRecord status: SUCCEEDED gives COMPLETED; FAILED and BUDGET_STOPPED give FAILED; CANCELLED gives CANCELLED. Set its `completed_at`.
      - Emit `MissionRunStatusChangedEvent` with `session_id = run.session_id or mission_id`, then commit.
    - **`begin(run_id) -> BeginRunResult`.** Idempotent: if the status is already RUNNING, return the stored values. In order:
      1. **State.** A status other than PENDING raises `MissionRunStateError`.
      2. **Owner.** `mission.owner_id` must parse as a UUID and name an existing user, else `transition(FAILED, START_FAILED, "owner not a platform user")`, commit, and raise `RunStartRejectedError`.
      3. **Gate mode.** If `plan.gate_mode` is not one of `{MANUAL, AI_ASSISTED, AUTONOMOUS}`, `transition(FAILED, INVALID_GATE_MODE)`, commit, and raise `RunStartRejectedError`.
      4. **Session.** When `run.session_id` is NULL, `SessionService.create_session(SessionCreate(mission_id=..., agent_id="mission.supervisor.agent", goal=f"Mission run #{seq}"), user_id=owner_id)`. This is the pattern at `temporal/activities.py:86-104`.
      5. **ExecutionRecord.** Create one with `status=RUNNING`, `mission_run_id=run_id`, `temporal_workflow_id=mission_run_workflow_id(run_id)`, `objective_statement=run.objective or "Approved backlog"` and `task_params={"mission_run_id": run_id}`. The stamped id lets the reconciler resolve the record (contracts 3.0.1, 88.1.10a).
      6. **Adopt backlog.** When `WorkflowRunRepository.list_active_for_mission(mission_id)` is empty, `adopt_backlog(plan_id, run_id, [TaskStatus.APPROVED])`; otherwise adopt nothing and log at info.
      7. **Previous run and watermark.** `previous_run_id` from `get_latest_with_digest`, and `context_version_start` = the mission's MCD version (0 when no MCD exists).
      8. **Write and commit.** Snapshot `gate_mode`, set the fields, transition to RUNNING and commit.
    - **`plan(run_id, session_id) -> PlanRunResult`.**
      - **Status values.** `PlanRunResult.status` is the lowercase string `"planned"`, `"empty"` or `"failed"` (3.0.2, 3.3.5).
      - **Backlog dispatch** (`objective IS NULL` and `workflow_definition_id IS NULL`): `"planned"` when the run has approved or proposed tasks, else `"empty"`.
      - **Objective runs:** `orchestrator.refine(plan.id, run.objective, owner_id, mission_run_id=run_id)`.
      - **Workflow-definition runs:** `steps_to_task_definitions` followed by `orchestrator._persist_plan(plan, task_plan, source="mission_schedule", mission_run_id=run_id)`.
      - **Approval.** When `run.gate_mode == GateMode.AUTONOMOUS`, approve every PROPOSED task in the run with `mission.owner_id`.
      - **Errors.** `ValidationError` returns `"failed"` with `detail=redact_secrets(str(err))`. Objective and workflow-definition runs that plan without error return `"planned"`. Every other exception propagates, and the activity retries it.
    - **`task_graph(run_id)`.** Kahn layering over the run's APPROVED tasks using `task_dependencies`, ignoring dependencies already COMPLETED, plus the counts.
    - **`finalise(run_id, status, reason, detail) -> FinaliseRunResult`.** In one transaction, after loading the run and its `mission` and saving `owner_id = mission.owner_id` to a local:
      1. For `status == CANCELLED`, the reason is `run.cancel_reason`, falling back to `reason` only when NULL.
      2. Fail every QUEUED or RUNNING task in the run with `failure_reason=reason`.
      3. `release_to_backlog(run_id, [PROPOSED, APPROVED])` returns undispatched tasks to the backlog (contracts 3.3.3).
      4. Set the task counts from `list_by_run`, `context_version_end` from the current MCD version, and `cost_usd = LlmLedgerRepository.sum_cost(mission_id, since=None, until=None, mission_run_id=run_id)`. `LlmLedgerRepository` is created here with `sum_cost` over raw `llm_calls` only; 88.4.1 adds the aggregate table to the same method.
      5. `transition(...)`, which commits.
      6. **Raced approvals.** After commit, if APPROVED backlog exists, `plan.gate_mode == GateMode.AUTONOMOUS`, the mission is ACTIVE and no WorkflowRun is active, call `start_run(mission_id, trigger=MANUAL, objective=None, user_id=owner_id, session_id=None)`. `begin` already guarantees `owner_id` is a platform user (step 2 of `begin`); `owner_id` is the local saved before the commit in step 5, because the commit expires ORM attributes. A `ConflictError` here is logged at info and not raised.
      7. Return `FinaliseRunResult(cost_usd=cost, notification=NotificationRequest(...))`; the kind follows 3.6.2.
    - **Snapshots.** `MissionRunService` builds no snapshot itself; it imports `build_run_config_snapshot` from `temporal/config_snapshots.py` (88.1.5).

**Tests:**
- `test_workflow_task_mapping.py`:
  - `test_parameters_resolved_with_defaults`.
  - `test_human_input_step_rejected`.
  - `test_dependencies_mapped_to_uuids`.
- `test_mission_run_service.py`. Integration tests; the Temporal client and `TemporalWorkflowGateway` are `AsyncMock`s.
  - `test_start_run_conflict_when_active`.
  - `test_conflict_leaves_no_sequence_gap`: `start_run` raises `ConflictError` with run #1 active; after run #1 ends, the next `start_run` gets sequence 2.
  - `test_start_run_failed_start_marks_start_failed`.
  - `test_workflow_id_format`: `gateway.start_mission_run` is awaited once with an input whose `mission_run_id == run.id`, and `run.temporal_workflow_id == mission_run_workflow_id(run.id)`.
  - `tests/integration/backend/temporal/test_workflow_gateway.py::test_start_mission_run_rejects_duplicate` (`start_local`): a second `start_mission_run` with the same input raises `ExternalServiceError`.
  - `test_begin_invalid_gate_mode_fails_closed`: with the plan's gate mode set to `INTERACTIVE` by direct SQL, the run is FAILED/INVALID_GATE_MODE and `RunStartRejectedError` is raised.
  - `test_begin_owner_not_user_fails_start_failed`: `owner_id='cli-user'` gives FAILED/START_FAILED with detail `"owner not a platform user"` and raises `RunStartRejectedError`.
  - `test_begin_adopts_backlog_and_is_idempotent`.
  - `test_begin_skips_backlog_when_workflow_run_active`.
  - `test_begin_creates_one_execution_record`: two calls give one ExecutionRecord, whose `temporal_workflow_id` is `mission_run_workflow_id(run.id)`.
  - `test_wave_reuses_run_execution_record`: two `dispatch_approved` waves with `handle_mission` patched to call `persist_mission_results(..., execution_record_id=...)`, then one `persist_mission_outcome` fallback call, leave exactly one `execution_records` row with that `mission_run_id`.
  - `test_refine_scoped_to_run`: tasks from run #1 (COMPLETED) are absent from the planner's `current_plan` for run #2, asserted through a patched `_call_planning_agent` capturing its kwargs.
  - `test_reconcile_does_not_cancel_other_runs_tasks`.
  - `test_cancel_other_missions_run_404`.
  - `test_cancel_pending_unstarted_run_is_immediate`. 88.4.5 changes `cancel_run` (a terminal run becomes a no-op; an unstarted PENDING run is cancelled through the workflow) and updates this test's expectation by name.
  - `test_finalise_fails_inflight_tasks_and_sets_counts`.
  - `test_finalise_writes_ledger_cost`: two `llm_calls` rows with the run id (0.25 and 0.50) and one without give `cost_usd == 0.75`, and the result returns it.
  - `test_approval_racing_finalise_starts_next_run`: an APPROVED task in the run when `finalise(SUCCEEDED, NO_FURTHER_WORK)` runs returns to the backlog, and `gateway.start_mission_run` is awaited for a new run with sequence + 1.
- `tests/unit/backend/mission_control/test_mission_dispatch.py::test_handle_mission_takes_execution_label` (create): `inspect.signature(handle_mission).parameters` starts with `execution_label` and has no `mission_run_id`.

**Done when:**
- The test files above pass.
- `grep -rn --exclude-dir=migrations "dispatch_autonomous\|start_temporal_run_workflow\|create_early_execution_record\|skip_post_run_supervisor\|mission_plan_supervisor\|MissionPlanDispatchedEvent\|GateModeInvalidError" modules scripts` returns nothing.
- `rg -n "start_workflow|get_workflow_handle" modules --glob '!modules/backend/migrations/**' --glob '!modules/backend/temporal/workflow_gateway.py' --glob '!modules/backend/temporal/schedule_gateway.py' | rg -i "MissionRun|MissionTick|MissionScheduleTick|Reconciler|Retention|mission_run_workflow_id"` is empty; run workflows are started only through `TemporalWorkflowGateway`.
- `grep -rn -A3 "handle_mission(" modules | grep "mission_run_id="` is empty.

---

### 88.1.8 Run and tick workflows, activities and deletions

**Files:**
- **Create:**
  - `modules/backend/temporal/mission_run_activities.py`;
  - `modules/backend/temporal/mission_schedule_activities.py`;
  - `modules/backend/temporal/mission_schedule_tick_workflow.py`;
  - `tests/unit/backend/temporal/test_mission_run_workflow.py`;
  - `tests/unit/backend/temporal/test_mission_schedule_tick_workflow.py`;
  - `tests/unit/backend/temporal/test_no_config_in_workflows.py`.
- **Rewrite:** `modules/backend/temporal/mission_run_workflow.py`.
- **Modify:**
  - `temporal/activities.py` (`execute_mission`);
  - `temporal/supervisor_activities.py`;
  - `temporal/activity_helpers.py`;
  - `temporal/worker.py`;
  - `agents/mission_control/gate_post_run.py`, `services/execution_persistence.py`;
  - `events/types.py`;
  - `config/settings/temporal.yaml`, `core/config_schema.py`;
  - `modules/clients/cli/mc_trace.py:46-54`;
  - `tests/unit/backend/mission_control/test_gate_post_run.py`.
- **Delete:**
  - `temporal/scheduled_workflow.py`;
  - `temporal/scheduled_activities.py`;
  - `temporal/run_objective_workflow.py`;
  - `temporal/run_objective_activities.py`;
  - `temporal/run_objective_models.py`;
  - the tests of those modules (`tests/unit/backend/temporal/test_scheduled_activities.py`, `tests/integration/backend/temporal/test_scheduled_mission_check.py`).

**Current state:**
1. **Config read at run start.** `MissionRunWorkflow.run` reads `get_app_config()` at `mission_run_workflow.py:66`, so replay depends on the worker's config. The 25-iteration cap is at `:80`, the WAIT sleep at `:184-191`, the refine wait at `:233,244`, and the stub notification calls at `:307-318` and `:349-360`.
2. **`AgentMissionWorkflow` already broken for waves.** It calls `execute_mission` (`temporal/workflow.py:81-82,152-153`) with `mission_run_id=execution_id` (`api/v1/endpoints/executions.py:245-247`), which `dispatch_approved` loads as a plan id. Changing `execute_mission`'s input breaks no working path; 88.2.6 deletes `AgentMissionWorkflow`.
3. **Poller.** `ScheduledMissionCheckWorkflow` (`scheduled_workflow.py:26-98`) starts plan-keyed children every second. Nothing else starts runs for approved backlog; 88.1.9 wires the replacement triggers.
4. **Post-run decision cache.** `AutonomousPostRunReviewer` returns a cached decision keyed only by `execution_record_id` before any breaker runs (`gate_post_run.py:103-116`, `execution_persistence.py:421-436`). With one ExecutionRecord per run (88.1.7), iteration 1's decision would be replayed for every later iteration and breaker #2 would never fire, so an `advance_refine` decision would loop without bound. The fix therefore lands here, not in Phase 2.
5. **Events.** `fire_supervisor_followups` (`supervisor_activities.py:272-330`) emits `MissionPlanRunCompletedEvent` per wave. Its clients are `mc_run.py:340-341` and `frontend/src/components/narrative/narrative-groups.ts:92-95`, updated in 88.1.13 and 88.1.14.
6. **Query.** `get_loop_status` is at `mission_run_workflow.py:54-61`; its caller is `mc_trace.py:46-54`.

**Change:**
1. **Activity helper (`activity_helpers.py`).** Add `heartbeat_every(interval_seconds: int, phase: str)`, an async context manager that starts an asyncio task calling `activity.heartbeat({"phase": phase})` every `interval_seconds` and cancels it on exit. Activities read `get_app_config().temporal.mission_run.task_heartbeat_interval_seconds` for the interval; workflows never read config.
2. **`mission_run_activities.py`.** `@activity.defn` functions `begin_mission_run`, `plan_mission_run`, `fetch_run_task_graph`, `set_mission_run_status` and `finalise_mission_run`, with the 3.3.5 I/O.
   - Each opens `get_async_session()`, builds a `SessionEventBus` and calls the matching `MissionRunService` method.
   - `plan_mission_run` runs inside `heartbeat_every(interval, "planning")`.
   - `finalise_mission_run` logs `result.notification` at info with `extra={"kind": result.notification.kind, "subject_id": result.notification.subject_id}` and returns the `FinaliseRunResult`. 88.4.5 sends it under patch id `p88-lifecycle-signals`.
3. **`mission_schedule_activities.py`.**
   - `claim_occurrence(input: ClaimOccurrenceInput) -> ClaimOccurrenceResult` calls `MissionScheduleService.claim_occurrence`, commits, and then, when the schedule became COMPLETED, calls `sync_to_temporal`.
   - `sync_mission_schedules(mission_id: str | None) -> ScheduleSyncStats` calls `sync_mission` or `sync_all`. 88.1.10 moves it into `reconciler_activities.py`.
4. **`execute_mission`.** Its input becomes `ExecuteWaveInput`.
   - Delete the session-creation branch (`activities.py:86-104`); `begin` owns the session.
   - Call `orchestrator.dispatch_approved(input.mission_run_id, mission.owner_id, session_id=input.session_id, execution_record_id=input.execution_record_id)` inside `heartbeat_every(interval, "executing")`.
   - Its exception handling is as 88.0.8 left it.
5. **`supervisor_activities.py`.**
   - **`PostRunEvalInput`** becomes `{mission_id: str, mission_run_id: str, execution_record_id: str, supervisor_iteration_count: int, session_id: str}` with no defaults. `_do_evaluate_post_run` loads `run.gate_mode`, `mission.brief`, `plan.max_supervisor_iterations`, `plan.budget_usd_ceiling` and `plan.total_spent_usd` from the DB. Phase 4 moves the last three.
   - **`SupervisorFollowupInput`** (new dataclass): `{mission_id, mission_run_id, execution_record_id, action, reason, reviewer, wave_status, wave_cost_usd, failure_reason: str | None}`. `fire_supervisor_followups(input: SupervisorFollowupInput)` emits only `SupervisorDecisionEmittedEvent` and fires followups. Delete `MissionPlanRunCompletedEvent` from `events/types.py:589` and `EVENT_TYPE_MAP`.
   - **Rename.** `approve_proposed_tasks(mission_id)` becomes `approve_run_proposed_tasks(mission_run_id: str) -> int`. It approves the run's PROPOSED tasks with `mission.owner_id` only when `run.gate_mode == GateMode.AUTONOMOUS`, and returns 0 otherwise.
   - **Replacement.** Delete `fetch_plan_task_counts` and `PlanTaskCounts`; `fetch_run_task_graph` replaces them.
   - **Director turn.** `start_director_turn(input: DirectorTurnInput)`.
   - `check_plan_active` stays. 88.4.2 rewrites its body to read `missions.status`; 88.4.5 stops calling it under `p88-lifecycle-signals` and deletes it only when no caller remains.
6. **Decision cache scoped to iteration** (moved from 88.2.6 item 6, because 88.1.7 creates the condition).
   - `ExecutionPersistenceService.get_cached_decision_by_type(execution_record_id, decision_type, *, iteration: int)` returns only a decision whose decoded `decision_reasoning` meta has `iteration == iteration`.
   - `AutonomousPostRunReviewer` writes `iteration` into that meta, and `_get_cached_decision(execution_record_id, iteration)` passes `context.supervisor_iteration_count`.
7. **`mission_run_workflow.py` (rewrite).** No `get_app_config` import. Activity modules are imported inside `workflow.unsafe.imports_passed_through()`, as today.
   ```python
   def _cause_type(e: ActivityError) -> str:
       cause = e.cause
       if isinstance(cause, ApplicationError):
           return cause.type or type(cause).__name__
       return type(cause).__name__


   async def _exec(fn, arg, p: ActivityPolicySnapshot):
       return await workflow.execute_activity(fn, arg, **activity_kwargs(p))


   @workflow.defn
   class MissionRunWorkflow:
       @workflow.init
       def __init__(self, inp: MissionRunWorkflowInput) -> None:
           self._input = inp
           self._state: MissionRunWorkflowState | None = inp.state
           self._phase = "planning"
           self._approved_seq = inp.state.approved_seq if inp.state is not None else 0
           self._pause_requested = inp.state.pause_requested if inp.state is not None else False
           self._paused = inp.state.paused if inp.state is not None else False
           self._decision: GateDecisionUpdate | None = inp.state.decision if inp.state is not None else None
           self._refinement_done = False

       @workflow.signal
       def tasks_approved(self, s: TasksApprovedSignal) -> None:
           self._approved_seq += 1

       @workflow.signal
       def refinement_complete(self) -> None:
           self._refinement_done = True

       @workflow.query
       def get_run_state(self) -> MissionRunWorkflowStatus:
           s = self._state
           return MissionRunWorkflowStatus(
               mission_run_id=self._input.mission_run_id,
               iteration=s.iteration if s is not None else 0,
               phase=self._phase,
               pending_gate_id=None,
               pause_requested=self._pause_requested,
               last_supervisor_action=s.last_supervisor_action if s is not None else None,
           )

       @workflow.run
       async def run(self, inp: MissionRunWorkflowInput) -> str:
           c = inp.config
           try:
               if self._state is None:
                   try:
                       b = await _exec(begin_mission_run, BeginRunInput(inp.mission_run_id), c.persistence)
                   except ActivityError as e:
                       if _cause_type(e) == "RunStartRejectedError":
                           return "failed"
                       raise
                   self._state = MissionRunWorkflowState(
                       iteration=0, session_id=b.session_id, execution_record_id=b.execution_record_id,
                       context_version_start=b.context_version_start, pending_gate=None,
                       pause_requested=self._pause_requested, paused=self._paused,
                       last_supervisor_action=None, approved_seq=self._approved_seq, decision=None,
                   )
                   try:
                       p = await _exec(plan_mission_run, PlanRunInput(inp.mission_run_id, b.session_id), c.plan_run)
                   except ActivityError as e:
                       return await self._end_run("failed", "planning_failed", _cause_type(e))
                   if p.status == "failed":
                       return await self._end_run("failed", "planning_failed", p.detail)
               s = self._state
               while True:
                   seen = self._approved_seq
                   g = await _exec(fetch_run_task_graph, inp.mission_run_id, c.persistence)
                   if g.approved == 0:
                       if g.proposed == 0:
                           return await self._end_run("succeeded", "no_further_work", None)
                       self._phase = "awaiting_gate"
                       await workflow.wait_condition(lambda: self._approved_seq > seen)
                       continue
                   s.iteration += 1
                   self._phase = "executing"
                   try:
                       wave = await _exec(
                           execute_mission,
                           ExecuteWaveInput(inp.mission_run_id, s.session_id, s.execution_record_id),
                           c.execute_task,
                       )
                   except ActivityError as e:
                       return await self._end_run("failed", "task_failures", _cause_type(e))
                   await workflow.execute_activity(
                       persist_mission_outcome,
                       args=[inp.mission_run_id, s.session_id, wave.outcome_json, inp.mission_id, s.execution_record_id],
                       **activity_kwargs(c.persistence),
                   )
                   self._phase = "supervising"
                   try:
                       ev = await _exec(
                           evaluate_post_run,
                           PostRunEvalInput(inp.mission_id, inp.mission_run_id, s.execution_record_id, s.iteration - 1, s.session_id),
                           c.evaluate_post_run,
                       )
                   except ActivityError as e:
                       return await self._end_run("failed", "supervisor_escalated", _cause_type(e))
                   s.last_supervisor_action = ev.action
                   await _exec(
                       fire_supervisor_followups,
                       SupervisorFollowupInput(
                           mission_id=inp.mission_id, mission_run_id=inp.mission_run_id,
                           execution_record_id=s.execution_record_id, action=ev.action, reason=ev.reason[:200],
                           reviewer=ev.reviewer, wave_status=wave.status, wave_cost_usd=wave.total_cost_usd,
                           failure_reason=(str(wave.outcome_json.get("abort_reason") or wave.outcome_json.get("error"))[:500] if (wave.outcome_json.get("abort_reason") or wave.outcome_json.get("error")) else None),
                       ),
                       c.persistence,
                   )
                   if not await _exec(check_plan_active, inp.mission_id, c.persistence):
                       return await self._end_run("cancelled", "cancelled_by_user", "plan paused")
                   if ev.action == "wait":
                       continue
                   if ev.action == "advance_approved":
                       await _exec(approve_run_proposed_tasks, inp.mission_run_id, c.persistence)
                       continue
                   if ev.action == "advance_refine":
                       self._refinement_done = False
                       await _exec(
                           start_director_turn,
                           DirectorTurnInput(inp.mission_id, inp.mission_run_id, s.session_id,
                                             REFINE_PROMPT.format(iteration=s.iteration), workflow.info().workflow_id),
                           c.director_turn,
                       )
                       try:
                           await workflow.wait_condition(lambda: self._refinement_done,
                                                         timeout=timedelta(seconds=c.refine_wait_seconds))
                       except asyncio.TimeoutError:
                           workflow.logger.warning("refinement signal not received")
                       after = await _exec(fetch_run_task_graph, inp.mission_run_id, c.persistence)
                       if after.proposed > 0:
                           await _exec(approve_run_proposed_tasks, inp.mission_run_id, c.persistence)
                       if after.proposed == 0 and after.approved == 0:
                           return await self._end_run("failed", "supervisor_escalated", "refine produced no tasks")
                       continue
                   if ev.action == "propose_complete":
                       await _exec(
                           start_director_turn,
                           DirectorTurnInput(inp.mission_id, inp.mission_run_id, s.session_id,
                                             COMPLETE_PROMPT.format(iteration=s.iteration), None),
                           c.director_turn,
                       )
                       return await self._end_run("succeeded", "objective_met", ev.reason[:500])
                   if ev.action == "escalate":
                       await _exec(
                           start_director_turn,
                           DirectorTurnInput(inp.mission_id, inp.mission_run_id, s.session_id,
                                             ESCALATE_PROMPT.format(reason=ev.reason[:200]), None),
                           c.director_turn,
                       )
                       return await self._end_run("failed", "supervisor_escalated", ev.reason[:500])
                   return await self._end_run("failed", "supervisor_escalated", f"unknown action {ev.action}")
           except asyncio.CancelledError:
               await self._end_run("cancelled", None, None)
               raise

       async def _end_run(self, status: str, reason: str | None, detail: str | None) -> str:
           self._phase = "finalising"
           await _exec(
               finalise_mission_run,
               FinaliseRunInput(self._input.mission_run_id, status, reason, detail),
               self._input.config.persistence,
           )
           return status
   ```
   - `REFINE_PROMPT`, `COMPLETE_PROMPT` and `ESCALATE_PROMPT` are module constants carrying the prompt text of `:216-223`, `:272-277` and `:291-295` with the cost figures removed; cost now comes from the ledger.
   - **Signal handling (contracts 3.3.3).** Handlers touch only the handler-owned fields (`approved_seq`, `pause_requested`, `paused`, `decision`) initialised in `@workflow.init` from `inp.state` or defaults. The wake-up uses the monotonic counter: `seen` is recorded before `fetch_run_task_graph`, so a `tasks_approved` signal delivered during that activity satisfies `approved_seq > seen` and is never lost.
   - **No cap, no continue-as-new.** Neither `max_loop_iterations` nor `continue_as_new` appears. The loop is bounded by breaker #2 now that item 6 makes it reachable. 88.2.6 deletes the breaker (item 8); 88.2.7 adds continue-as-new.
   - **Deletions in this file.** `get_loop_status`, both `send_notification` calls, the `workflow.sleep` WAIT and the budget-derived activity timeout.
   - **Names.** `_end_run`, `_exec` and `_cause_type` are the only names later phases use for these helpers.
   - **Casing.** Every string literal passed to `_end_run`, assigned to `_phase` or compared with a DTO `status` is a lowercase enum value (3.0.2). Phases are `"planning"`, `"awaiting_gate"`, `"executing"`, `"supervising"` and `"finalising"`.
   - **Start rejection.** `begin` raises `RunStartRejectedError` (88.1.7, in 3.3.4 `NON_RETRYABLE`) for `FAILED/INVALID_GATE_MODE` and for `FAILED/START_FAILED` (owner not a platform user). The workflow returns `"failed"` without calling `_end_run`, because `begin` already transitioned and committed the run. A `MissionRunStateError` from `begin` (the run is no longer PENDING, for example cancelled before start) is non-retryable and propagates; the run row is already terminal.
8. **`mission_schedule_tick_workflow.py`.** Contract 3.3.2 steps 1, 2 and 4; step 3 is a log line until 88.4.5 sends the notifications under patch id `p88-lifecycle-signals`.
   ```python
   SCHEDULED_START_TIME = SearchAttributeKey.for_datetime("TemporalScheduledStartTime")


   @workflow.defn
   class MissionScheduleTickWorkflow:
       @workflow.run
       async def run(self, inp: MissionScheduleTickInput) -> str:
           scheduled_for = workflow.info().typed_search_attributes.get(SCHEDULED_START_TIME)
           if scheduled_for is None:
               raise ApplicationError("NO_SCHEDULED_TIME", non_retryable=True)
           r = await workflow.execute_activity(
               claim_occurrence,
               ClaimOccurrenceInput(inp.mission_schedule_id, scheduled_for),
               **activity_kwargs(inp.config.claim),
           )
           workflow.logger.info("notifications pending phase", extra={"count": len(r.notifications)})
           if r.run_input is not None:
               try:
                   await workflow.start_child_workflow(
                       MissionRunWorkflow.run,
                       r.run_input,
                       id=mission_run_workflow_id(r.mission_run_id),
                       task_queue=inp.config.task_queue,
                       parent_close_policy=ParentClosePolicy.ABANDON,
                       id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                   )
               except WorkflowAlreadyStartedError:
                   workflow.logger.info("run workflow already started", extra={"mission_run_id": r.mission_run_id})
           return r.outcome
   ```
   `run_input` is set for RUN and for DUPLICATE of a PENDING row (88.1.6 item 11), which restarts a run whose tick died after commit.
9. **Config deltas.** Delete `wait_action_sleep_seconds`, `refine_poll_max_seconds` and `max_supervisor_iterations` from `temporal.yaml` and `TemporalSchema`; their readers are gone.
10. **`worker.py`.**
    - Remove `ScheduledMissionCheckWorkflow`, `RunObjectiveWorkflow`, `find_ready_plans`, `execute_run_objective`, `fetch_plan_task_counts` and `approve_proposed_tasks`.
    - Add `MissionScheduleTickWorkflow`, `begin_mission_run`, `plan_mission_run`, `fetch_run_task_graph`, `set_mission_run_status`, `finalise_mission_run`, `claim_occurrence`, `sync_mission_schedules` and `approve_run_proposed_tasks`.
11. **`mc_trace.py:46-54`.** Query `"get_run_state"` and print `iteration`, `phase`, `pending_gate_id` and `last_supervisor_action`. It keeps its existing `client.get_workflow_handle` call; 88.5.8 moves it onto the live-state API endpoint.
12. **`test_no_config_in_workflows.py`.** AST-parse `modules/backend/temporal/mission_run_workflow.py` and `mission_schedule_tick_workflow.py`, and fail on any `ImportFrom` of `get_app_config` or `get_default_budget_usd`. 88.2.2 widens the glob to `*workflow*.py`.

**Tests:** these use `WorkflowEnvironment.start_time_skipping()` with every activity replaced by a fake `@activity.defn(name=...)`.
- `test_mission_run_workflow.py`:
  - `test_begin_plan_execute_propose_complete_succeeds`: `finalise` is called with `("succeeded", "objective_met")`.
  - `test_invalid_gate_mode_returns_failed_without_finalise`: the begin fake raises `ApplicationError(type="RunStartRejectedError", non_retryable=True)`.
  - `test_owner_rejected_returns_failed_without_finalise`: the begin fake raises `ApplicationError("owner not a platform user", type="RunStartRejectedError", non_retryable=True)`.
  - `test_planning_failed_finalises`.
  - `test_no_tasks_finalises_no_further_work`.
  - `test_waits_for_tasks_approved_signal`: the graph returns `proposed=1, approved=0` and then `approved=1`. The workflow blocks until the signal, with no time-skipping sleep.
  - `test_signal_before_begin_completes`: `tasks_approved` is sent right after start while the begin fake blocks on an event. The workflow does not fail, and `get_run_state` reports `phase == "planning"`.
  - `test_signal_during_graph_fetch_not_lost`: the signal is sent while the first `fetch_run_task_graph` fake (returning `proposed=1, approved=0`) is blocked. The workflow proceeds to the second fetch without a second signal.
  - `test_refine_without_new_tasks_escalates`.
  - `test_cancel_finalises_cancelled`: `handle.cancel()` during the execute fake, then `finalise` is called with `"cancelled"` and reason `None`.
  - `test_get_run_state_query`.
  - `test_execute_task_policy_applied`: the fake raises a retryable error twice and succeeds the third time (`maximum_attempts=3`).
- `test_mission_schedule_tick_workflow.py`:
  - `test_missing_scheduled_time_fails_non_retryable`.
  - `test_run_outcome_starts_child_with_run_id`.
  - `test_duplicate_pending_starts_child`.
  - `test_skipped_outcome_starts_nothing`.
  - `test_child_already_started_is_success`.
- `test_no_config_in_workflows.py`: `test_workflows_do_not_import_config`.
- `test_gate_post_run.py::test_cache_scoped_to_iteration`: a decision cached for iteration 1 is not returned for iteration 2.

**Done when:**
- The test files above pass.
- `grep -rn --exclude-dir=migrations "ScheduledMissionCheckWorkflow\|find_ready_plans\|RunObjectiveWorkflow\|get_loop_status\|fetch_plan_task_counts\|MissionPlanRunCompletedEvent" modules` returns nothing.
- `grep -rn "max_supervisor_iterations" modules/backend/temporal config` matches only the DB read in `supervisor_activities.py`.
- `python -m modules.backend.temporal.worker` starts with no import errors.

---

### 88.1.9 Event-driven dispatch trigger points

**Files:**
- Modify:
  - `modules/backend/api/v1/endpoints/missions_plan.py`;
  - `modules/backend/agents/mission/director/tools/approve_plan_tasks.py`;
  - `modules/backend/agents/mission/director/tools/run_objective.py`;
  - `modules/backend/temporal/plan_refine_activities.py`;
  - `modules/backend/schemas/mission_plan.py`;
  - `modules/backend/temporal/workflow_gateway.py`, `modules/backend/services/mission_run.py`, `tests/integration/backend/services/test_mission_run_service.py`.
- Create: `tests/integration/backend/api/test_event_driven_dispatch.py`.

**Current state:** the 1-second poller deleted in 88.1.8 was the only thing that started runs for approved backlog tasks. The trigger points are listed below; this step wires each one. `require_mission_operator` exists since 88.0.9.

**Change:**
1. **Gateway (`temporal/workflow_gateway.py`).** Add `async def signal(self, workflow_id: str, signal: str, arg: object) -> WorkflowState`. It returns `NOT_FOUND` on `RPCError` NOT_FOUND (which Temporal also returns for a closed execution), raises `ExternalServiceError` on any other `RPCError`, and returns `RUNNING` after a delivered signal.
2. **`MissionRunService.on_tasks_approved(mission_id, task_ids, user_id)`.**
   - Commit first.
   - If there is an active run, `await gateway.signal(run.temporal_workflow_id, "tasks_approved", TasksApprovedSignal(task_ids))`. A `NOT_FOUND` result is logged at warning and the method returns; the run row is handled by finalise or the reconciler (88.1.10a).
   - With no active run, call `start_run(mission_id, trigger=MANUAL, objective=None, user_id=user_id, session_id=None)` when all of these hold: `plan.gate_mode == GateMode.AUTONOMOUS`, the mission is ACTIVE, and `WorkflowRunRepository.list_active_for_mission(mission_id)` (88.0.10) is empty. A workflow run owns its own materialised tasks (88.0.6 step 2), and this preserves that rule now the poller is gone.
3. **Triggers.** Each trigger calls the service after its own commit.

| # | Where | Today | Change |
|---|---|---|---|
| 1 | `POST /missions/{id}/plan/tasks/{task_id}/approve` (`missions_plan.py:352-397`) | approves (a waiting dispatcher polls the task row, 88.0.13a) | after the approval commits: `await MissionRunService(db, event_bus).on_tasks_approved(mission_id, [t.id for t in transitioned], current_user.id)` |
| 2 | `POST /missions/{id}/plan/tasks/{task_id}/retry` (`missions_plan.py:435-475`) | FAILED to APPROVED | after the retry commits: `on_tasks_approved(mission_id, [task.id], current_user.id)` |
| 3 | Director tool `approve_plan_tasks` (`approve_plan_tasks.py:144-156`) | `_approve_each`, then commit | after the commit at `:156`: `on_tasks_approved(mission_id, _dedupe_preserving_order(transitioned), mission.owner_id)` |
| 4 | `execute_plan_refine` activity (`plan_refine_activities.py:62-80`) | auto-approves when `refined.gate_mode == GateMode.AUTONOMOUS` (88.0.5, 88.1.0), then commits | after `db.commit()`, when `approved_ids` is not empty: `on_tasks_approved(input.mission_id, approved_ids, mission.owner_id)` |
| 5 | `POST /missions/{id}/plan/dispatch` (`missions_plan.py:269-307`) | `dispatch_autonomous` | `run = await MissionRunService(db, event_bus).start_run(mission_id, trigger=MissionRunTrigger.MANUAL, objective=None, user_id=current_user.id, session_id=None)`; response `MissionRunResponse`; auth `require_mission_operator`. Delete `DispatchApprovedResponse` from `schemas/mission_plan.py` |
| 6 | Director tool `run_objective` (`run_objective.py:26-71`) | `orchestrator.run_objective` | `run = await MissionRunService(db_session, event_bus).start_run(mission_id, trigger=MissionRunTrigger.DIRECTOR, objective=objective, user_id=acting_user_id, session_id=session_id)`; returns `{"mission_run_id", "sequence", "status"}` with the status value; the followup stays on `mission_plan.supervisor_decision`; the docstring says planning happens asynchronously in the run |
| 7 | `MissionRunWorkflow` supervisor `advance_approved` and `advance_refine` | inside the run | no external trigger; the loop re-reads the graph |

**Not a trigger:**
- **Schedule ticks** start runs only through `claim_occurrence`.
- **Rejecting tasks and adding manual tasks** (`POST /plan/tasks`) do not start runs.

**Tests:**
- `test_mission_run_service.py` (add; the gateway is an `AsyncMock`):
  - `test_on_tasks_approved_signals_active_run`.
  - `test_on_tasks_approved_starts_run_when_autonomous_and_idle`.
  - `test_on_tasks_approved_noop_when_manual_and_idle`.
  - `test_on_tasks_approved_signal_not_found_logs_and_returns`.

`test_event_driven_dispatch.py` (integration; `TemporalWorkflowGateway` is mocked):
- `test_approve_endpoint_starts_run_for_autonomous_idle_mission`: `gateway.start_mission_run` is awaited once with an input whose `mission_run_id == run.id`.
- `test_approve_endpoint_signals_active_run`: the gateway's `signal` is awaited with `"tasks_approved"`.
- `test_retry_endpoint_starts_run_for_autonomous_idle_mission`.
- `test_manual_mode_approve_does_not_start_run`.
- `test_dispatch_endpoint_conflict_when_active`: 409 through the `ConflictError` handler.
- `test_dispatch_endpoint_viewer_forbidden`: 403.
- `test_refine_activity_does_not_auto_approve_manual`.

**Done when:**
- The tests pass.
- `grep -rn "run_objective(" modules/backend/services` is empty.
- `grep -rln "MissionRunWorkflow.run" modules` lists only `temporal/workflow_gateway.py`, `temporal/mission_schedule_tick_workflow.py` and `temporal/worker.py` (registration).

---

### 88.1.10 System schedules registered through the gateway; `ReconcilerWorkflow` gains schedule sync

**Files:**
- Modify (exist since 88.0.10): `modules/backend/temporal/system_schedules.py`, `modules/backend/temporal/reconciler_workflow.py`, `modules/backend/temporal/reconciler_activities.py`, `tests/unit/backend/temporal/test_system_schedules.py`, `tests/integration/backend/temporal/test_reconciler_workflow.py`.
- Modify: `modules/backend/temporal/mission_schedule_activities.py`, `modules/backend/temporal/worker.py`, `modules/backend/main.py`, `config/settings/temporal.yaml`, `modules/backend/core/config_schema.py`.
- Create: `tests/integration/backend/temporal/test_system_schedules_live.py`.

**Current state:**
- **API lifespan registers schedules.** `main.py:48-196` registers 10 Temporal Schedules from the API lifespan, with crons written inline at `:117-192`.
- **Edits never reach Temporal.** `_register_schedule` (`main.py:79-115`) swallows `ScheduleAlreadyRunningError` at `:111` and never updates.
- **Swallowed failures.** Any failure is logged and swallowed (`:193-196`).
- **Phase 0 registration.** 88.0.10 registers only `system-reconciler` from the worker through `register_system_schedules(client: Client)`, with `_BUILDERS` holding one key. `ReconcilerWorkflow.run(inp: ReconcilerInput) -> ReconcileStats` runs `reconcile_mission_runs` only.

**Change:**
1. **Config.** Add the eight remaining `system_schedules` entries from contract 3.4.1 (`retention`, `hourly_health_check`, `weekly_report`, `metrics_aggregation`, `cleanup_environments`, `knowledge_extraction`, `knowledge_officer`, `embedding_backfill`) to `temporal.yaml`. Replace 88.0.2's subset validator on `TemporalSchema` with equality: raise when `set(system_schedules) != ALLOWED_SYSTEM_SCHEDULE_KEYS`. Delete `dispatch_check_interval_seconds` from `temporal.yaml` and `TemporalSchema`.
2. **`ReconcileStats.schedule_sync`.** The field exists since 88.0.10 and `reconcile_mission_runs` still returns it as `None`; the workflow fills `schedule_sync` from `sync_mission_schedules` (item 4). `mission_run_models.py` is not changed.
3. **`reconciler_activities.py`.** Move `sync_mission_schedules` here from `mission_schedule_activities.py`.
4. **`ReconcilerWorkflow.run(inp: ReconcilerInput) -> ReconcileStats`.**
   ```python
   stats = await workflow.execute_activity(
       reconcile_mission_runs,
       ReconcileInput(orphan_grace_seconds=inp.orphan_grace_seconds),
       **activity_kwargs(inp.activity),
   )
   sync = await workflow.execute_activity(sync_mission_schedules, None, **activity_kwargs(inp.activity))
   return dataclasses.replace(stats, schedule_sync=sync)
   ```
   The workflow is short-lived per fire, so this change needs no `workflow.patched`.
5. **`system_schedules.py`.** The signature becomes `register_system_schedules(gateway: TemporalScheduleGateway) -> None`; it no longer touches `Client`.
   ```python
   LEGACY_SCHEDULE_IDS = frozenset({
       "mission-plan-dispatch-schedule",
       "maintenance-daily-cleanup",
       "maintenance-hourly-health-check",
       "maintenance-weekly-report",
       "maintenance-metrics-aggregation",
       "maintenance-cleanup-environments",
       "maintenance-workflow-schedules",
       "knowledge-daily-extraction",
       "knowledge-officer-daily",
       "knowledge-embedding-backfill",
   })


   async def register_system_schedules(gateway: TemporalScheduleGateway) -> None:
       cfg = get_app_config().temporal
       if set(_BUILDERS) != set(cfg.system_schedules):
           raise RuntimeError("system schedule registry mismatch")
       for key, sched in cfg.system_schedules.items():
           fn, arg = _BUILDERS[key](cfg)
           action = ScheduleActionStartWorkflow(
               fn, args=[] if arg is None else [arg], id=f"system-{key}", task_queue=cfg.task_queue
           )
           await gateway.upsert(
               f"system-{key}",
               Schedule(
                   action=action,
                   spec=ScheduleSpec(cron_expressions=[sched.cron], time_zone_name="UTC"),
                   policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
               ),
           )
       for sid in await gateway.list_ids(None):
           if sid in LEGACY_SCHEDULE_IDS:
               logger.warning("Deleting legacy schedule", extra={"schedule_id": sid})
               await gateway.delete(sid)
   ```
   - `_BUILDERS` keeps the 88.0.10 `"reconciler"` builder unchanged and gains eight builders, each returning `(Workflow.run, None)`: `retention` maps to `DailyCleanupWorkflow` until 88.5.4 introduces `RetentionWorkflow`; the others map to `HourlyHealthCheckWorkflow`, `WeeklyReportWorkflow`, `MetricsAggregationWorkflow`, `CleanupEnvironmentsWorkflow`, `KnowledgeExtractionWorkflow`, `KnowledgeOfficerWorkflow` and `EmbeddingBackfillWorkflow`.
   - **Deletion scope (contracts 3.0.2).** Registration deletes only the ten literal legacy ids above, which are exactly the registrations at `main.py:118-191`. `MissionScheduleService.sync_all` deletes `mission-schedule-*` ids with no matching row. Nothing else in the namespace is ever deleted, and the namespace stays as configured.
   - **System schedules use SKIP.** A system job has no per-occurrence record to keep. The ALLOW_ALL policy in 3.3.2 applies only to mission schedules.
6. **`worker.py`.** Before `worker.run()`: `gateway = await TemporalScheduleGateway.create()`, `await register_system_schedules(gateway)`, then `await MissionScheduleService(session).sync_all()` in its own DB session. Exceptions propagate, so the worker fails to start (P8). Register `sync_mission_schedules` from its new module.
7. **`main.py`.** Delete the Temporal block at `:48-196` entirely. The API no longer touches Temporal at startup.

**Tests:**
- `test_system_schedules.py` (unit, modify; a fake gateway replaces the mock client):
  - `test_upserts_all_nine`: ids `system-reconciler` and the eight others; the reconciler action arg is a `ReconcilerInput` with `orphan_grace_seconds == 600`, and the others have no arg.
  - `test_deletes_only_legacy_ids`: the fake lists `mission-plan-dispatch-schedule`, `maintenance-workflow-schedules`, `mission-schedule-x` and `third-party-schedule`. Only the first two are deleted.
  - `test_registry_mismatch_raises`.
  - `test_system_schedules_keys_must_match` (schema): one missing key raises, and one extra key raises.
- `test_system_schedules_live.py` (integration, `start_local`):
  - `test_register_updates_changed_cron`: register, change `hourly_health_check.cron` in a patched config, register again; `describe` shows the new cron.
  - `test_register_keeps_mission_schedules`.
- `test_reconciler_workflow.py` (modify): `test_runs_reconcile_then_sync`: the stub activities record their order as `["reconcile_mission_runs", "sync_mission_schedules"]`, and the result's `schedule_sync` equals the sync stub's return.

**Done when:**
- `grep -n "create_schedule\|_register_schedule\|temporal" modules/backend/main.py` is empty.
- `grep -rlnE "client\.create_schedule|\.get_schedule_handle\(|ScheduleHandle" modules/backend --include=*.py` lists only `temporal/schedule_gateway.py` and `temporal/system_schedules.py`.
- After starting the worker against the dev server, `temporal schedule list` shows the nine `system-*` ids, any `mission-schedule-*` ids, and none of the ten legacy ids.

---

### 88.1.10a Mission-run reconciliation over `mission_runs`

**Files:**
- Modify (exist since 88.0.10): `modules/backend/services/run_reconciliation.py`, `tests/unit/backend/services/test_run_reconciliation.py`.
- Modify: `modules/backend/temporal/mission_run_models.py` (`ReconcileStats`), `modules/backend/api/v1/endpoints/admin.py`, `admin.py` (register the `reconcile` group), `tests/unit/backend/api/test_admin_api.py`.
- Create: `modules/clients/cli/admin_groups/reconcile.py`, `tests/integration/backend/services/test_run_reconciliation_runs.py`, `tests/unit/clients/cli/test_admin_reconcile.py`.

**Current state:**
- 88.0.10's `RunReconciliationService.reconcile` resolves task liveness by `state(mission_run_workflow_id(plan_id))`. Since 88.1.8 no workflow has that id, so every RUNNING task would resolve NOT_FOUND and be failed after the grace period.
- Nothing fails a `mission_runs` row whose workflow has gone. A tick that commits a PENDING run and dies before `start_child_workflow`, or a `start_run` process that dies between commit and start, leaves a PENDING row that holds `uq_mission_runs_one_active`; every later tick then becomes `SKIPPED/OVERLAP` for good.
- 88.1.7 already stamps the run's ExecutionRecord with `temporal_workflow_id = mission_run_workflow_id(run_id)`, so the record resolves through Temporal.
- The reconciler selects only execution records with `temporal_workflow_id IS NOT NULL OR workflow_run_id IS NOT NULL` (88.0.10 scope rule); in-process CLI and TUI rows are left alone.

**Change:**
1. **`ReconcileStats`.** Add `examined_mission_runs: int` and `failed_mission_runs: int` (3.3.4). The 88.0.10 fields, including `left_running` and `left_in_process`, are unchanged.
2. **Runs (new first pass of `reconcile`), implementing 3.5.1.**
   - **Collect.** `cutoff = utc_now() - timedelta(seconds=orphan_grace_seconds)`. `MissionRunRepository.list_active_older_than(cutoff)`; save `id`, `mission_id`, `status` and `temporal_workflow_id` to plain dataclasses, then commit. Increment `examined_mission_runs` per run.
   - **Resolve.** `state = await gateway.state(temporal_workflow_id)` for each, cached per id. Any `ExternalServiceError` propagates before any write.
   - **Decide.** RUNNING leaves the run alone and increments `left_running`. CLOSED gives reason `ORPHANED_WORKFLOW_CLOSED`; NOT_FOUND gives `ORPHANED_WORKFLOW_NOT_FOUND`.
   - **Write, one transaction per orphaned run.** Re-select the run with `with_for_update(skip_locked=True)` and the same status and `updated_at < cutoff` predicates; no row means it progressed, so skip it. Otherwise call `MissionRunService(self._session, self._event_bus).finalise(run_id, MissionRunStatus.FAILED, reason, f"workflow {wid} {state.value}")`. `finalise` fails the run's QUEUED and RUNNING tasks, returns PROPOSED and APPROVED tasks to the backlog, fails the ExecutionRecord through `transition`, commits, logs the `RUN_FAILED` request, and starts the next run when the 88.1.7 raced-approval rule holds. Increment `failed_mission_runs`.
3. **Tasks.** Delete the `mission_run_workflow_id(plan_id)` liveness branch. Then:
   - a task with `mission_run_id` set is decided by its run: skip it in this pass, because the runs pass handled it;
   - a task with `mission_run_id IS NULL` is live when any `list_active_for_mission` WorkflowRun is AWAITING_INPUT or resolves RUNNING, as in 88.0.10. Otherwise it is unknown and left alone, counted in `left_in_process`, matching the 88.0.10 rule for rows with no Temporal id.
4. **Execution records and workflow runs.** Unchanged from 88.0.10.
5. **Manual trigger (3.5.3, 3.5.4).**
   - **API.** `POST /admin/reconcile/run` in `api/v1/endpoints/admin.py`, guarded by `require_admin` (the `AdminRole` dependency, `core/dependencies.py:219,233`). It opens `TemporalWorkflowGateway.connect()`, builds the event bus exactly as the `reconcile_mission_runs` activity does (88.0.10), and returns `ApiResponse(data=await RunReconciliationService(db, gateway, event_bus).reconcile(get_app_config().temporal.reconciler.orphan_grace_seconds))`, where the data is the `ReconcileStats`.
   - **CLI.** `modules/clients/cli/admin_groups/reconcile.py` defines `@click.group("reconcile")` with the command `run`, registered in `admin.py` with `admin_cli.add_command(reconcile)`. `admin reconcile run` calls the same service in-process (contracts 3.0.2: `admin.py` runs inside the backend trust boundary) and renders the stats with `report.py` primitives (`build_table`, `get_console()`).

**Tests:**
- `test_run_reconciliation.py` (modify; DB plus a fake gateway):
  - `test_running_workflow_leaves_tasks_untouched`: a RUNNING run whose workflow resolves RUNNING keeps its RUNNING tasks and its status.
  - `test_closed_workflow_fails_run_and_tasks`: `FAILED/ORPHANED_WORKFLOW_CLOSED`; its RUNNING task is FAILED and its APPROVED task has `mission_run_id IS NULL`.
  - `test_runs_inside_grace_untouched`.
  - `test_backlog_task_without_workflow_run_untouched`.
  - `test_run_progressed_between_resolve_and_write_skipped`.
  - Delete `test_closed_workflow_fails_running_and_queued_tasks` and every other test that depends on the plan-keyed id.
- `test_run_reconciliation_runs.py` (integration):
  - `test_pending_run_without_workflow_failed_after_grace_and_next_tick_runs`: insert a PENDING SCHEDULE run with `updated_at = now - 700s` and no workflow (gateway NOT_FOUND). After `reconcile(600)` the run is `FAILED/ORPHANED_WORKFLOW_NOT_FOUND`, and `claim_occurrence` for the next slot returns RUN, not `SKIPPED/OVERLAP`.
- `test_admin_api.py` (add):
  - `test_admin_reconcile_requires_admin`: a non-admin user gets 403.
  - `test_admin_reconcile_returns_stats`: with `RunReconciliationService.reconcile` mocked, the response is `ApiResponse` whose `data` carries the `ReconcileStats` fields.
- `test_admin_reconcile.py`: `test_admin_reconcile_run_renders_stats` (`CliRunner`, service mocked).

**Done when:** the tests pass, `grep -rn --exclude-dir=migrations "mission_run_workflow_id(plan" modules` is empty, and `python admin.py tree` lists `reconcile` with `run`.

---

### 88.1.11 Mission deletion reaches runs and schedules

**Files:**
- Modify (exists since 88.0.9): `modules/backend/services/mission.py` (`delete_mission`), `tests/integration/backend/services/test_mission.py`.

**Current state:** 88.0.9 rewrote `delete_mission` to terminate `{mission_run_workflow_id(plan.id)}` plus the `temporal_workflow_id` values of the mission's PENDING and RUNNING execution records, after committing the read transaction and before any DB delete. It does not know about `mission_runs` or mission schedules.

**Change (delta on the 88.0.9 code):**
1. **Schedules first.** Before collecting workflow ids, `for s in await MissionScheduleService(self._session).list_schedules(mission_id, include_archived=True): await gateway.delete(s.temporal_schedule_id)`, with `gateway = await TemporalScheduleGateway.create()`. NOT_FOUND is success. Deleting schedules first stops a new tick starting a run during the delete.
2. **Run workflow id.** Replace `mission_run_workflow_id(plan.id)` in the id set with the active run's `temporal_workflow_id` from `MissionRunRepository.get_active_for_mission(mission_id)`, when one exists. The execution-record ids stay; the run's record carries the same id, and the set removes the duplicate.
3. **Stop, then delete.** Keep 88.0.9's `TemporalWorkflowGateway.terminate`. Cancellation would run the workflow's `CancelledError` handler, whose `finalise_mission_run` activity would then act on rows this method is about to delete. Archive (88.4.5) is the path that cancels, because its rows survive.
4. A Temporal error raises `ExternalServiceError`, and the delete aborts before any DB delete (P8, fail closed), as in 88.0.9.

**Tests (add to `test_mission.py`):**
- `test_delete_removes_temporal_schedules`.
- `test_delete_terminates_active_run`: the gateway's `terminate` is awaited with `mission_run_workflow_id(run.id)`.
- `test_delete_aborts_when_schedule_delete_fails`: the schedule gateway raises, and the mission row still exists.
- Update 88.0.9's `test_delete_mission_terminates_mission_run_workflow` to seed an active run instead of a plan-keyed id.

**Done when:** the tests pass.

---

### 88.1.12 API endpoints

**Files:**
- Create: `modules/backend/api/v1/endpoints/missions_schedules.py`, `modules/backend/api/v1/endpoints/missions_runs.py`, `tests/unit/backend/api/test_missions_schedules_api.py`, `tests/unit/backend/api/test_missions_runs_api.py`.
- Modify: `modules/backend/api/v1/endpoints/missions.py:28-35`, `api/v1/endpoints/admin.py`, `api/v1/endpoints/missions_plan.py`, `schemas/mission_plan.py`, `scripts/verify_unified_execution.py`.

**Current state:**
- **IDOR on schedules.** The deleted routes checked mission access but not schedule ownership; 88.0.11 patched them, and 88.1.3 deleted them.
- **`run-objective` route** is at `missions_plan.py:201-266`, with `RunObjectiveRequest` at `schemas/mission_plan.py:154`.
- **Access helpers.** `require_mission_access`, `require_existing_mission_access` and `require_mission_owner` are at `dependencies.py:277-321`. `require_mission_operator` exists since 88.0.9.
- `scripts/verify_unified_execution.py:400-405` posts to `run-objective`.

**Change:**
1. **`missions_schedules.py`.** Implements the seven schedule rows of the 3.5.3 table, with that table's auth (`require_mission_operator` for writes, `require_existing_mission_access` for reads).
   - Every handler calls `MissionScheduleService` only.
   - The response is `MissionScheduleResponse`, with `next_fire_times = await svc.next_fire_times(s, 5)` on GET of a single schedule and `[]` on lists.
   - **Sync-failure status code.** A create whose sync failed returns 201 with `temporal_sync_state="failed"`. The row exists and the reconciler retries.
2. **`missions_runs.py`.** Implements `POST /runs`, `GET /runs`, `GET /runs/{run_id_or_seq}` and `POST /runs/{run_id}/cancel`.
   - **Run lookup.** `MissionRunService.get_run(mission_id, run_id_or_seq)`, which scopes by mission (contracts 3.0.2).
   - **Cancel.** `cancel_run(mission_id, run_id, current_user.id, reason=MissionRunStatusReason.CANCELLED_BY_USER)`; another mission's run is 404.
   - **Detail response.** `MissionRunDetailResponse` without `gates`; 88.4.8 adds them.
   - **Paging.** `limit: int | None = Query(None, ge=1, le=200)`; when omitted the service uses 50. `before_sequence: int | None`.
   - **Status filter.** `status: list[MissionRunStatus] | None = Query(None)` takes repeated lowercase values (contracts 3.0.2), for example `?status=running&status=paused`.
3. **Router.** Include both routers in `missions.py` after `missions_workflows.router` (`:30`).
4. **Delete `run-objective`.** Delete `POST /{mission_id}/plan/run-objective` (`missions_plan.py:201-266`) and `RunObjectiveRequest`. Repoint `scripts/verify_unified_execution.py:400-405` to `POST /missions/{mission_id}/runs` with body `{"objective": ...}`.
5. **Admin sync route.** In `admin.py`, add `POST /admin/schedules/sync` with an optional `mission_id` body field (`require_admin`). It returns `ScheduleSyncStats` in `ApiResponse`. It exists for the web; `admin schedules sync` (88.1.13) calls the service in-process and never this route.

The default page size 50 is a service constant only until 88.1.13 introduces `cli.yaml`; the CLI always sends a limit.

**Tests** (unit, `httpx.AsyncClient` with service mocks, following `tests/unit/backend/api/test_admin_api.py`):
- `test_missions_schedules_api.py`:
  - `test_create_requires_operator`: a VIEWER member gets 403, and a MAINTAINER member gets 201.
  - `test_get_schedule_of_other_mission_404`.
  - `test_patch_rejects_kind`: 422.
  - `test_delete_returns_archived`.
  - `test_list_excludes_archived_by_default`.
  - `test_responses_use_api_envelope`.
  - `test_enum_fields_lowercase`: the response `status` is `"active"`.
- `test_missions_runs_api.py`:
  - `test_start_run_conflict_409`.
  - `test_get_by_sequence`.
  - `test_list_paginates_next_before_sequence`.
  - `test_list_status_filter_takes_values`: `?status=running` is accepted and `?status=RUNNING` returns 422.
  - `test_cancel_requires_operator`.
  - `test_cancel_other_missions_run_404`.
  - `test_run_objective_route_removed`: POST returns 404.

**Done when:**
- The tests pass.
- `curl -s localhost:8000/openapi.json | jq -r '.paths | keys[]' | grep -E 'missions/\{mission_id\}/(schedules|runs)|admin/schedules/sync'` lists exactly these eight paths under `/api/v1`:
  - `/missions/{mission_id}/schedules`;
  - `/missions/{mission_id}/schedules/{schedule_id}`;
  - `/missions/{mission_id}/schedules/{schedule_id}/pause`;
  - `/missions/{mission_id}/schedules/{schedule_id}/resume`;
  - `/missions/{mission_id}/runs`;
  - `/missions/{mission_id}/runs/{run_id_or_seq}`;
  - `/missions/{mission_id}/runs/{run_id}/cancel`;
  - `/admin/schedules/sync`.

---

### 88.1.13 `mc` and `admin` CLI

**Files:**
- **Create:**
  - `config/settings/cli.yaml`;
  - `modules/clients/cli/mc_groups/workflow_runs.py`;
  - `modules/clients/cli/mc_mission_runs.py`;
  - `modules/clients/cli/admin_groups/schedules.py`;
  - `tests/unit/clients/cli/test_mc_schedule.py` (new content);
  - `tests/unit/clients/cli/test_mc_mission_runs.py`;
  - `tests/unit/clients/cli/test_admin_schedules.py`.
- **Rewrite:**
  - `modules/clients/cli/mc_groups/schedule.py`;
  - `modules/clients/cli/mc_schedule.py`;
  - `modules/clients/cli/mc_groups/runs.py`.
- **Modify:**
  - `modules/backend/core/config_schema.py`, `modules/backend/core/config.py`;
  - `mc.py:229` (add `mc.add_command(workflow_runs)`) and `mc.py:179-228` (the `mc run` options);
  - `modules/clients/cli/mc_run.py:209-256` and `:340-341`;
  - `modules/clients/cli/mc_trace.py`;
  - `modules/clients/cli/mc_groups/status_history.py:136-140`;
  - `admin.py`.

**Current state:**
- **`mc runs`** is the WorkflowRun group, calling `/workflow-runs` (`mc_runs.py:30,74,103`).
- **`mc schedule`** has `--workflow` (an id), `--cooldown` and `enable`/`disable` (`mc_groups/schedule.py:64-135`).
- **`mc run --objective`** posts to `run-objective` with `--gate` and `--budget` (`mc_run.py:236-248`). Its progress stream reads `mission_plan.run.completed` (`mc_run.py:340-341`), deleted in 88.1.8.
- **Examples** in the `status_history.py:136-140` docstring use the old id format.
- `config/settings/cli.yaml` does not exist.

**Change:**
1. **CLI config.** Create `config/settings/cli.yaml`:
   ```yaml
   mc:
     runs_list_limit: 20
   ```
   Add to `config_schema.py`:
   ```python
   class CliMcSchema(_StrictBase):
       runs_list_limit: int = Field(..., ge=1, le=200)

   class CliSchema(_StrictBase):
       mc: CliMcSchema
   ```
   In `AppConfig.__init__`, `self._cli = _load_validated(CliSchema, "cli.yaml")` (required), with a `cli` property.
2. **Rename the WorkflowRun group.** Move the current `runs` group body to `mc_groups/workflow_runs.py` as `@click.group("workflow-runs")`, with no alias. `mc_runs.py` stays as its renderer.
3. **New `mc runs` group** (`mc_groups/runs.py` and the renderer `mc_mission_runs.py`):
   - `list [--status S]... [--limit N]`. `--limit` is optional. When omitted, the client sends `get_app_config().cli.mc.runs_list_limit`. `--status` takes lowercase values.
   - `show SEQ`, `digest SEQ` (prints `No digest yet` when `digest` is null), `cancel SEQ`, and `start --objective TEXT`.
   - Tables use `report.py` primitives: `build_table` and `get_console()`.
4. **`mc schedule`** (`mc_groups/schedule.py` and `mc_schedule.py`), exactly as in 3.5.4.
   - **Name resolution.** `NAME` is resolved by `GET /missions/{id}/schedules?include_archived=true` and an exact name match. No match exits 1 with `Schedule 'NAME' not found`.
   - **Workflow resolution.** `--workflow NAME` is resolved through `GET /missions/{id}/workflows` (`missions_workflows.py:36-40`) by exact `name`. `GET /workflows` lists YAML templates, which carry no `workflow_definition_id`.
   - **Parameters.** `--param k=v` is repeatable and builds `workflow_parameters`.
   - **Catch-up window.** `--catch-up-window` accepts `90s|15m|6h|2d` and is converted to seconds client-side, which is a presentation parse.
   - **Show.** `show` prints `next_fire_times` and `temporal_sync_state`. `failed` is printed in the error style with `temporal_sync_error`.
5. **`mc run --objective`.** It posts `POST /missions/{id}/runs {objective}` and prints `Run #{sequence} started`. Delete `--gate`, `--step` and `--budget`; gate mode is a plan setting and caps arrive in 88.4.1. `--dry-run` stays. Delete the `mission_plan.run.completed` branch at `mc_run.py:340-341`.
6. **`mc trace`.** Accepts `SEQ` (digits) as well as a workflow id. Digits resolve through `GET /missions/{id}/runs/{seq}` (active mission) to the response's `temporal_workflow_id`. Update the docstring examples at `status_history.py:136-140` to `mc trace 37` and `mc trace <temporal_workflow_id from mc runs show>`.
7. **`admin schedules sync [--mission ID]`** calls `MissionScheduleService.sync_mission(mission_id)` when `--mission` is given, else `sync_all()`, in-process (contracts 3.0.2: `admin.py` runs inside the backend trust boundary; it calls services, never repositories or models), and renders `ScheduleSyncStats` with `report.py` primitives. It makes no HTTP call. It replaces the `admin schedule` group deleted in 88.1.3.

**Tests:** `CliRunner` with `api_client` mocked.
- `test_create_objective_payload`: the body has `kind="objective"` and `catch_up_window_seconds=21600` for `--catch-up-window 6h`.
- `test_create_workflow_resolves_name_and_params`: the mock answers `GET /missions/{id}/workflows`.
- `test_unknown_name_exits_1`.
- `test_show_prints_sync_failed`.
- `test_runs_list_sends_configured_limit_when_omitted`: with `cli.mc.runs_list_limit` patched to 7, the request has `limit=7`.
- `test_runs_list_sends_explicit_limit`.
- `test_runs_show_by_sequence`.
- `test_workflow_runs_group_exists`.
- `test_mc_run_posts_runs_endpoint`.
- `tests/unit/clients/cli/test_admin_schedules.py::test_admin_schedules_sync_calls_service_in_process` (create): with `MissionScheduleService.sync_all` mocked and `api_client` patched to fail on use, the command renders the stats and makes no HTTP call.
- `test_tree_lists_new_groups`: `python mc.py tree` output contains `schedule`, `runs`, `workflow-runs` and `edit NAME`.
- `tests/unit/backend/core/test_config_schema_plan88_phase1.py::test_cli_yaml_loads`: `get_app_config().cli.mc.runs_list_limit == 20`.

**Done when:** the tests pass, `python mc.py tree` lists the new groups, `python admin.py tree` includes `schedules` with `sync [--mission]`, and `grep -rn "croniter\|workflow_scheduler\|WorkflowSchedule\|EvaluateWorkflowSchedules" modules/clients mc.py admin.py` returns nothing (the CLI part of the 88.1.3 check).

---

### 88.1.14 Web client

**Files:**
- Create: `modules/frontend/src/hooks/use-mission-runs.ts`, `modules/frontend/src/hooks/use-mission-schedules.ts`, `modules/frontend/src/types/mission-run.ts`.
- Modify:
  - `src/types/workflow.ts:142-180` (delete the `WorkflowSchedule*` types) and `src/types/index.ts`;
  - `src/hooks/use-workflows.ts:201-257` (delete the schedule hooks and their type imports at `:10-12`) and `src/hooks/use-executions.ts` (delete `useRunObjective`, `:110-128` at `a28ca771`);
  - `src/components/workflow/schedule-modal.tsx`, `src/components/workspace/workflows-panel.tsx` (`SchedulesSection` `:286-322`, `ScheduleRow` `:323-430`, imports `:28-32,38`, query `:73`), `src/components/workspace/runs-panel.tsx`, `src/components/workspace/run-row-detail.tsx`, `src/components/workspace/run-detail-panel.tsx`;
  - `src/components/mission/run-modal.tsx`;
  - `src/components/narrative/narrative-groups.ts:92-95`.

Phase 0 (88.0.9, 88.0.13) edits `use-executions.ts`, so locate `useRunObjective` by name.

**Current state:**
- **Wrong time-zone text.** `schedule-modal.tsx:240-245` offers a free-text time zone with a `"UTC"` placeholder, and the help text at `:245` says times use it, which the backend ignored.
- **Runs panel is execution-scoped.** `runs-panel.tsx` lists ExecutionRecords through `useExecutions` (`:10,54`).
- **Run modal targets a deleted route.** `run-modal.tsx:4,34` uses `useRunObjective`, which posts to `run-objective`.
- **Deleted event.** `narrative-groups.ts:92-95` reads `mission_plan.run.completed`.

**Change:**
1. **Types.** `types/mission-run.ts` mirrors `MissionRunResponse`, `MissionRunDetailResponse`, `MissionScheduleResponse`, `MissionScheduleCreate` and `MissionScheduleUpdate`. Status unions use the lowercase enum values the API returns.
2. **Hooks.** Every hook unwraps `ApiResponse`.
   - `use-mission-schedules.ts`: `useMissionSchedules(missionId, includeArchived)`, `useMissionSchedule`, `useCreateMissionSchedule`, `useUpdateMissionSchedule`, `usePauseMissionSchedule`, `useResumeMissionSchedule` and `useArchiveMissionSchedule`.
   - `use-mission-runs.ts`: `useMissionRuns(missionId, {statuses, limit, beforeSequence})`, `useMissionRun(missionId, runIdOrSeq)`, `useStartMissionRun` and `useCancelMissionRun`. 88.4.10 mounts `useCancelMissionRun` in the run detail row.
   - Each mutation invalidates `['mission-runs', missionId]` or `['mission-schedules', missionId]`.
3. **`schedule-modal.tsx`.**
   - **Fields.** A kind toggle (Objective or Saved workflow), and an objective textarea showing the allowed placeholders `{scheduled_for}`, `{sequence}` and `{mission_name}`, or a workflow `Select` plus parameter fields.
   - **Recurrence.** Cron with the existing `lib/cron.ts` presets. A required time-zone `Select` (`components/ui/select.tsx`), populated from `Intl.supportedValuesOf('timeZone')` and initialised to `Intl.DateTimeFormat().resolvedOptions().timeZone`, with no `"UTC"` placeholder. Starts at, ends at, max runs and a catch-up window in hours.
   - **Copy.** The help text becomes `Cron times are evaluated in this time zone, including daylight-saving changes.`
4. **`workflows-panel.tsx`.** The schedule list uses `useMissionSchedules`. Each row shows status, next fire (from `next_fire_times[0]` on the single-schedule query, loaded on expand) and a sync badge when `temporal_sync_state !== 'synced'`, with Pause, Resume and Archive actions.
5. **Runs panel.** `runs-panel.tsx` lists `useMissionRuns` with the columns `#sequence · status · trigger · objective · scheduled for · started · duration`.
   - **Filters.** `Running` maps to `pending|running|awaiting_gate|paused`, `Succeeded` to `succeeded`, `Failed` to `failed|budget_stopped|cancelled`, and `Skipped/Missed` to `skipped|missed`.
   - **Row detail.** `run-row-detail.tsx` and `run-detail-panel.tsx` load `useMissionRun` and show the run's tasks and the digest when present.
   - **Executions link.** The link to the execution record stays, through the run's record id in the detail response.
6. **`run-modal.tsx`.** Uses `useStartMissionRun` with only the `objective` field. The gate and budget overrides are removed.
7. **`narrative-groups.ts:92-95`.** Replace the `mission_plan.run.completed` case with `mission_run.status_changed`, setting `group.status = text(d.to_status)`.

**Tests:** the frontend has no unit test harness, so the gates are `npm run build` and `npm run lint` with zero warnings. The browser check is in Verification.

**Done when:**
- `cd modules/frontend && npm run build && npm run lint` passes.
- `grep -rn "run-objective\|WorkflowSchedule\|workflow_scheduler\|croniter\|mission_plan.run.completed\|useRunObjective" modules/frontend/src` is empty (this includes the frontend part of the 88.1.3 check).

---

### Verification

```bash
cd /Users/herman.young/development/mission-control

# 0a. Before deploying the rewritten MissionRunWorkflow: terminate open runs of the old shape (P3, no replay compatibility)
temporal workflow terminate --query 'WorkflowType="MissionRunWorkflow" AND ExecutionStatus="Running"' --reason "Plan 88 Phase 1 deploy"
temporal workflow terminate --query 'WorkflowType="ScheduledMissionCheckWorkflow" AND ExecutionStatus="Running"' --reason "Plan 88 Phase 1 deploy"

# 0b. plan88_003 creator pre-check: must return zero rows, otherwise fix the listed rows first
psql "$DATABASE_URL" -c "SELECT ws.id FROM workflow_schedules ws JOIN missions m ON m.id = ws.mission_id
  WHERE NOT EXISTS (SELECT 1 FROM users u WHERE 'user:' || u.id::text = ws.created_by)
    AND NOT EXISTS (SELECT 1 FROM users u WHERE u.id::text = m.owner_id);"

# 1. Migrations (revision ids, never filenames)
python admin.py migrate upgrade head
python admin.py migrate current                       # plan88_003
python admin.py migrate downgrade plan88_001 && python admin.py migrate upgrade head

# 2. Static checks
python scripts/code_quality.py --scope modules/ tests/
grep -rn --exclude-dir=migrations --exclude=test_plan88_003_migration.py "croniter\|workflow_schedules\|ScheduledMissionCheckWorkflow\|RunObjectiveWorkflow\|dispatch_autonomous\|get_loop_status\|resolve_gate_mode" modules config tests   # empty (the 88.1.3 migration test seeds workflow_schedules by design)
wc -l modules/backend/services/mission_run.py modules/backend/services/mission_schedule*.py modules/backend/temporal/mission_run_workflow.py   # each <= 500

# 3. Tests
pytest tests/unit -q
pytest tests/integration -q -k "plan88 or mission_run or mission_schedule or claim_occurrence or schedule_gateway or system_schedules or event_driven or run_reconciliation or test_mission"
cd modules/frontend && npm run build && npm run lint && cd ../..

# 4. Live check (API, worker and dev Temporal running; dev config has missions.recurrence.enabled: true)
python -m modules.backend.temporal.worker &           # registers system-* schedules, runs sync_all
temporal schedule list                                # the nine system-* ids; none of the ten legacy ids
python mc.py mission create --name p88-live --description "Phase 1 check" --gate-mode autonomous
python mc.py mission use p88-live
python mc.py schedule create every5 --cron "*/5 * * * *" --tz Europe/London --objective "Check {mission_name} run {sequence} at {scheduled_for}"
python mc.py schedule show every5                     # temporal_sync_state synced, 5 next fire times
temporal schedule describe --schedule-id mission-schedule-<id>   # cron, Europe/London, overlap ALLOW_ALL
# wait 11 minutes
python mc.py runs list --limit 5                      # >= 2 rows, sequences contiguous, trigger schedule
pkill -f modules.backend.temporal.worker; sleep 900; python -m modules.backend.temporal.worker &
# wait 2 minutes
python mc.py runs list --limit 10 --status missed     # each downtime slot is missed (superseded or not_fired) or the one run
python mc.py schedule pause every5 && temporal schedule describe --schedule-id mission-schedule-<id> | grep -i paused
python mc.py schedule delete every5 && temporal schedule describe --schedule-id mission-schedule-<id>   # NotFound
python mc.py trace <seq>                              # get_run_state renders
# Web: create a mission (gate mode required), open it; the Workflows tab shows schedule rows with a sync badge,
# and the Runs tab lists #sequence rows with the skipped/missed filter.
```

The SQL invariant checks return zero rows:
```sql
SELECT mission_id, count(*) FROM mission_runs
WHERE status IN ('PENDING','RUNNING','AWAITING_GATE','PAUSED') GROUP BY 1 HAVING count(*) > 1;
SELECT schedule_id, scheduled_for, count(*) FROM mission_runs WHERE schedule_id IS NOT NULL GROUP BY 1,2 HAVING count(*) > 1;
SELECT mission_run_id, count(*) FROM execution_records WHERE mission_run_id IS NOT NULL GROUP BY 1 HAVING count(*) > 1;
```

### Risks

1. **Legacy schedule cleanup.** `register_system_schedules` deletes the ten legacy ids, and `sync_all` deletes `mission-schedule-*` ids with no row. **Mitigation:** both lists are literal or prefix-and-row checked; any other schedule in the configured namespace is never touched, and every deletion is logged at warning with its id.
2. **Wave retries can re-execute LLM work.** `execute_mission` keeps the `execute_task` policy (3 attempts). A worker crash mid-wave re-dispatches the wave, as it does today. **Mitigation:** the run lock means at most one run's wave is retried. The per-task idempotency of 88.2.4 closes this before the 168-run acceptance test. Phase 1 acceptance uses short objectives, so a duplicate is cheap.
3. **`list_matching_times` inside the claim transaction.** A slow Temporal frontend holds the schedule row lock. **Mitigation:** the `claim` policy caps the activity at 60s with 5 attempts. The lock is per schedule, never per mission or global. A timeout rolls the whole claim back, including sequence increments, and the next attempt re-runs it idempotently through the slot unique key.
4. **Open runs of the old shape at deploy.** They cannot replay against the rewritten workflow. **Mitigation:** Verification step 0a terminates them. Their DB rows are plan-level, not `mission_runs`, so no new-model state is orphaned. This is a P3 break, accepted by the rule.
5. **MANUAL and AI_ASSISTED runs can wait indefinitely in Phase 1.** There is no gate timer until 88.4.8. **Mitigation:** the wait is visible in `mc runs list`, every later tick is recorded as `SKIPPED/OVERLAP` rather than lost, and `mc runs cancel SEQ` reaches Temporal. Schedule creation rejects INTERACTIVE. Production keeps `missions.recurrence.enabled: false` and dispatches no MANUAL or AI_ASSISTED mission until Phase 4 is complete, because budget enforcement and durable gates arrive there.
6. **AI_ASSISTED stops auto-approving.** `AUTO_APPROVE_GATE_MODES` becomes `{AUTONOMOUS}` (contract 3.1.2), so the Director's `approve_plan_tasks` refuses AI_ASSISTED missions and their runs wait for a human. **Mitigation:** this matches `gate.yaml`'s own definition of AI_ASSISTED. Verification step 4 lists missions by mode, and owners switch a mission that must run unattended to AUTONOMOUS.
7. **Fail-closed migration of gate modes.** `plan88_001` turns NULL, `workflow_managed` and unknown modes into MANUAL, and logs the count. **Mitigation:** Phase 0 already resolved these to MANUAL at runtime (88.0.5), so behaviour does not change at the migration.
