## 3.0 Shared contracts

Every phase builds against the contracts in this section. When a phase needs something this section does not define, the implementer adds it here first and then builds it. Where code is replaced, P3 applies: the replaced code is deleted in the same step, with no shims, aliases or compatibility branches.

**Baseline.** Every file:line reference in this plan was verified at commit `a28ca771`. Backend and config are identical to `9adaa69d` and `777cd5c5`; the later commits touch only `modules/frontend`. Re-verify any frontend line before editing it. Uncommitted working-tree edits are not part of the baseline. **Entry criterion for every phase:** `git status --porcelain` lists no changes under `modules/`, `config/`, `tests/`, `requirements*.txt`, `pyproject.toml`, `mc.py`, `admin.py` or `services.py`. Work in progress (for example the model-provider changes in progress at the time of writing) is committed or stashed first; if it is committed, the implementer re-verifies by symbol the line citations in the files it touched before starting the phase.

### 3.0.1 Phase ownership

Each item has exactly one owning step. A later step that touches the item says "modify (exists since 88.x.y)" and describes only its delta. It never re-creates the file, re-adds the config block or cites line numbers for code this plan has already rewritten.

| Item | Owning step | Later steps (delta only) |
|---|---|---|
| `temporal/activity_options.py`: `NON_RETRYABLE`, `retry_policy(p: RetrySnapshot)`, `activity_kwargs(p: ActivityPolicySnapshot)` | 88.0.2 creates | Every later step imports it; 88.2.3a adds `ExecutionEnvironmentError` to `NON_RETRYABLE`. No `activity_policy.py` and no retry helper anywhere else |
| `temporal/config_snapshots.py`: `policy_snapshot(schema)`, `config_hash(obj)` | 88.0.2 creates (both functions are needed by 88.0.10's `ReconcilerInput`) | 88.1.5 imports both and adds `build_run_config_snapshot()` and `build_tick_config_snapshot()`; 88.2.2 adds the fields marked `# 88.2.2` and `build_workflow_timeouts_snapshot()`. No other definition of `config_hash` or `policy_snapshot` |
| `temporal/mission_run_models.py` with `RetrySnapshot`, `ActivityPolicySnapshot` | 88.0.2 creates | 88.0.10 adds the reconciler DTOs; 88.1.5 adds the run and tick DTOs; later steps add the fields marked in 3.3.4 |
| `temporal.yaml` blocks `mission_run`, `reconciler`, `system_schedules` and `RetrySchema`, `ActivityPolicySchema`, `MissionRunActivitiesSchema`, `MissionRunSchema`, `ReconcilerSchema`, `SystemScheduleSchema` | 88.0.2 creates (`system_schedules` holds only `reconciler`) | 88.1.10 adds the other eight `system_schedules` keys and tightens the key validator to equality; 88.2.1 adds `mission_run.max_run_duration_seconds`; 88.5.1 and 88.5.5 add their keys (3.4.1) |
| `temporal/workflow_ids.py` `mission_run_workflow_id` | 88.0.3 creates (`plan_id` parameter) | 88.1.7 renames the parameter to `mission_run_id`; every call site uses the function, never an f-string |
| `temporal/workflow_gateway.py` `TemporalWorkflowGateway` (the only owner of `WorkflowHandle` outside workflow code) | 88.0.3 creates (`state`, `cancel`, `terminate`) | 88.1.7 adds `start_mission_run`; 88.1.9 adds `signal`; 88.2.9 adds `fetch_history`; 88.4.8 adds `execute_update`; 88.5.4 adds `start_retention`; 88.5.8 adds `describe_status` and `query_state`. No `temporal/run_gateway.py`. No direct `start_workflow` or `get_workflow_handle` for `MissionRunWorkflow`, `MissionScheduleTickWorkflow`, `ReconcilerWorkflow` or `RetentionWorkflow` (including any id from `mission_run_workflow_id`) outside this gateway and `TemporalScheduleGateway`. Other workflows (chat, tool fork, plan refine, human input, workflow-run) are out of scope and keep their existing call sites. 88.5.8 moves `clients/cli/mc_trace.py` off `get_workflow_handle` for mission runs: live state from `GET /missions/{id}/runs/{run_id_or_seq}/live`, history from `GET /missions/{id}/runs/{run_id_or_seq}/history` (served by `fetch_history`). |
| `MissionService.is_operator`, `require_mission_operator` | 88.0.9 creates; applies it to `PATCH /missions/{id}/plan` (test `test_patch_plan_gate_mode_viewer_forbidden`) | 88.0.11, 88.0.13, 88.1.9, 88.1.12, 88.4.5 apply it to their routes only |
| Mission delete reaching Temporal; deletion of the four unauthenticated `api/v1/endpoints/workflows.py:90-221` routes | 88.0.9 | 88.1.11 modifies `delete_mission` to delete mission schedules and terminate the active `mission_runs` workflow through the gateways; 88.4.5 changes nothing in delete beyond ARCHIVED semantics. 88.1.11 uses `terminate`, not `cancel`, deliberately: cancellation runs `finalise_mission_run` against rows deleted in the same call. Archive (88.4.5) is the cancelling path |
| `temporal/reconciler_workflow.py`, `temporal/reconciler_activities.py`, `temporal/system_schedules.py`, `RunReconciliationService`, `ReconcilerInput`, `ReconcileInput`, `ReconcileStats` | 88.0.10 creates, together with `ScheduleSyncStats` and `ReconcileStats.schedule_sync` (always `None` in Phase 0); `register_system_schedules(client: Client)` | 88.1.10 modifies: the signature becomes `register_system_schedules(gateway: TemporalScheduleGateway)`, the workflow fills `ReconcileStats.schedule_sync` (the field and `ScheduleSyncStats` exist since 88.0.10, with `schedule_sync=None` until this step), the workflow runs `reconcile_mission_runs` then `sync_mission_schedules`, and the eight other `system_schedules` YAML keys are added together with their `_BUILDERS` entries (never earlier); 88.1.10a adds `examined_mission_runs` and `failed_mission_runs`; 88.5.6 adds the gate sweep |
| `services/mission_plan_crash_recovery.py` and the already broken `scripts/verify_crash_recovery.py` | 88.0.10 deletes both | none |
| Reconciler scope for in-process work | 88.0.10 | Selects only rows with `temporal_workflow_id IS NOT NULL OR workflow_run_id IS NOT NULL`. CLI and TUI in-process runs are never selected (test `test_in_process_record_without_ids_untouched`) |
| Mission-run reconciliation over `mission_runs` | 88.1.10a (new) | Implements the run pass of 3.5.1 `reconcile()`; deletes the `mission-run-{plan_id}` liveness branch; relies on `begin` stamping `execution_records.temporal_workflow_id` (since 88.1.7) |
| Web gate route fix (`modules/frontend/src/hooks/use-gates.ts`) | 88.0.13 creates | 88.4.8 modifies (delta) |
| Telegram fail-closed allowlist (`clients/telegram/middlewares/auth.py:76-83`) and mandatory webhook secret (`clients/telegram/webhook.py:58`) | 88.0.14 (new) | 88.4.9 cites 88.0.14 |
| `GateMode`, `plan88_001`, `MissionCreate.gate_mode` (required), `mc mission create --gate-mode`, eager plan creation in `create_mission`, every gate-mode string comparison rewritten to `GateMode`, drop `missions.gate_mode`, `mission_plans.veto_window_sec`, `tasks.veto_expires_at` | 88.1.0 (new) | Phase 1 entry criterion: Alembic head is `plan87_002` |
| `RunConfigSnapshot` and `TickConfigSnapshot` dataclasses (`temporal/mission_run_models.py`) | 88.1.5 defines them | 88.2.2 adds the fields marked `# 88.2.2` in 3.3.4; 88.2.6 adds `max_failure_digests` |
| `RunConfigSnapshot` and `TickConfigSnapshot` builders (`build_run_config_snapshot`, `build_tick_config_snapshot`) in `temporal/config_snapshots.py`, the only builders | 88.1.5 | 88.2.2 adds the fields marked `# 88.2.2` and `build_workflow_timeouts_snapshot`; 88.2.6 adds `max_failure_digests`; 88.4.8 switches the gate fields in `build_run_config_snapshot`. No `MissionRunService.build_config_snapshot` exists at any step |
| `MissionRunWorkflow._layer_boundary(self) -> str \| None` | 88.2.6 adds it; the duration check moves into it | Phase 4 hooks the pause check (88.4.5) and the budget check (88.4.6) into it |
| `agents/mission_control/mission_dispatch.handle_mission` legacy positional renamed `execution_label` | 88.1.7 | 88.2.3 makes `handle_mission` pass `mission_run_id=None` to `build_dispatch_runtime` for in-process callers |
| `MissionContextManager.apply_updates(..., mission_run_id: str \| None = None)` keyword | 88.2.4 adds it with the default `None` | 88.3.2 uses it and removes the default, so the keyword is required |
| `events/base.py` (`SessionEvent`, moved from `events/types.py:31-41`) and `events/mission_run_types.py` | 88.1.6 creates both unconditionally | Later steps (88.3.3 included) only add classes to `events/mission_run_types.py` and register them in `EVENT_TYPE_MAP` |
| `LlmLedgerRepository` (`repositories/llm_ledger.py`) | 88.1.7 creates `sum_cost` over raw `llm_calls` | 88.4.1 adds aggregates; 88.5.3 adds the rollup methods |
| `GateRequestRepository` (`repositories/gate_request.py`) | 88.4.3 creates it with `has_undecided(mission_id) -> bool` and `cancel_undecided(mission_id) -> int` | 88.4.5 uses both; 88.4.8 adds `get_for_mission`, `lock_for_mission`, `list_open`, `list_decided_for_run`, `insert_if_absent`, `mark_status` and `close`; 88.5.7 adds `pending_summary` |
| `check_plan_active` | 88.4.2 rewrites its body to read `missions.status` | 88.4.5 stops calling it under `p88-lifecycle-signals`; it is deleted in 88.4.5 only when no caller remains, otherwise the activity stays registered for executions on the old branch |
| `MissionRunWorkflow` skeleton: `@workflow.init`, `_exec`, `_cause_type`, `_end_run(status, reason, detail)` | 88.1.8 | Phases 2 to 4 use these names only. No `_finish`, no `policy(...)` |
| `tests/unit/backend/temporal/test_no_config_in_workflows.py` | 88.1.8 creates (two files) | 88.2.2 widens the glob to `*workflow*.py` |
| `AgentMissionWorkflow` (`temporal/workflow.py`), `MissionWorkflowInput`, `POST /executions/{id}/execute`, `POST /executions/{id}/approve`, the approval code in `use-executions.ts`, and the config keys only they read (3.4.1) | 88.2.6 deletes them in one commit | 88.4.8 re-implements the signal, `wait_condition` and timer pattern inside `MissionRunWorkflow`, citing `a28ca771:modules/backend/temporal/workflow.py` |
| `_gate()` seam in `MissionRunWorkflow` | 88.2.6 adds it, returning `"continue"` | 88.4.8 replaces it under patch id `p88-durable-gate` |
| Continue-as-new | 88.2.7 only | Phase 1 has no continue-as-new (3.3.3) |
| Failure columns on `tasks` and `task_executions` (3.1.8) | 88.1.2 creates them in `plan88_002`, unmapped by type | 88.2.3b maps them with the 3.8 enums; 88.2.4 adds `TaskRepository.set_failure`, the only writer, called from `record`, `mark_cancelled`, `MissionRunService.finalise` (which also covers orphaned runs) and the WorkflowRun task-fail paths; 88.4.6's record arrives through the classifier (3.8.3 step 1); 88.5.3 nulls `failure_json` |
| Fail-closed execution boundary: `ExecutionEnvironmentError`, no local fallback in `build_dispatch_runtime` or `_validate_mode`, `mission_repo_root` passed from `workflow_run_waves`, worktree rejected by `MissionService`, `LocalBackend` deleted, `run_in_environment` as the single command path, `codex` and `copilot` deleted and rejected by `AgentConfigSchema`, `execute_claude_code(environment_handle=...)`, `chat_cli_handler` without a host fallback, the `pydantic_ai` write guard, `executions.yaml` required, `tool_runner._redact_secrets_in_text` replaced by `redact_secrets` (3.8.5, 3.4.10, 3.5.5) | 88.2.3a | none |
| `schemas/task_failure.py` (`FailureOrigin`, `FailureClass`, `FailureEvidence`, `TaskFailure`), `core/failure_classification.py` (`FailureClassifier`, `get_failure_classifier`), `config/settings/failures.yaml` and `FailuresSchema`, `WorkflowStepFailedError` (in `core/failure_classification.py`), `WorkflowHaltedError`, `UpstreamOutputMissingError`, `TaskResult.failure`, `RetryHistoryEntry.failure_class`, `failed_result(task, failure, *, status, ..., cost_usd, token_usage, duration_seconds)` | 88.2.3b creates | 88.2.3c removes `MODIFY` at `verification_failed`; 88.2.4 adds `TaskRepository.set_failure` and the failure fields of `ExecuteTaskResult`; 88.2.4a adds `materialize_task_states`; 88.2.6 adds `TaskFailureDigest`, `digest_failures`, `TaskRepository.failed_tasks_for_run` and the post-run `summary["failures"]` |
| `TaskFailedEvent` (3.6.1) | 88.2.4 adds it; `execute_plan_task` is its only publisher | none |
| Budget: `BudgetService`, `check_run`, `check_run_budget` activity, caps, `llm_call_daily_aggregates` | Phase 4: 88.4.1 schema, 88.4.6 enforcement under patch id `p88-budget-caps` | Phases 1 to 3 contain no budget branch in workflows, claims or activities |
| `mission_runs.cost_usd` | 88.1.7 (`finalise` writes it from the ledger) | Phase 4 adds aggregates to monthly and lifetime sums only |
| `mission_runs.budget_cap_usd` snapshot | 88.4.1 (`begin` writes it) | Runs begun earlier keep NULL; `check_run` uses `coalesce(run.budget_cap_usd, plan.budget_per_run_usd)` |
| `pause_all_autonomous_plans` deletion and `pause_all_active` | 88.4.5 | 88.4.2 rewrites its body to pause missions (plan status is dropped); 88.4.5 deletes it and adds `pause_all_active` |
| Digest `decisions` content | 88.4.8 | 88.3.7 writes `[]` |
| `gate_manual.py`, `GateManualSchema`, interim key `gate.manual.poll_interval_seconds` | 88.0.2 adds the key; 88.0.13 uses it | 88.4.8 deletes all three |
| `core/redaction.py` `redact_secrets` | 88.1.6 creates and applies it to `temporal_sync_error`, `mission_runs.status_detail` and `MissionScheduleSyncFailedEvent.error` | 88.4.4 applies it to `notification_deliveries.error` and `NotificationDeliveryFailedEvent.error`; 88.4.8 and 88.4.9 to their stored text |
| Sending run-end (`FinaliseRunResult.notification`) and tick (`claim_occurrence`) notifications | 88.4.5, under patch id `p88-lifecycle-signals` | Before 88.4.5 they are built and logged only. Gate notifications are sent under `p88-durable-gate` (88.4.8) |
| `missions.recurrence.enabled` (bool, required) | 88.1.1 | `MissionScheduleService.create_schedule` and the `claim_occurrence` activity of the tick workflow refuse when false. Operational rule: until Phase 4 is complete, production keeps it `false` and dispatches no MANUAL or AI_ASSISTED mission, because budget enforcement and durable gates arrive in Phase 4 |
| Web lifecycle UI | 88.4.10 (new) | none |

**Scoped workflow-handle check.** A step that asserts the gateway rule uses this form, which excludes the two gateways and migrations (integration tests sit outside `modules`):

```bash
rg -n "start_workflow|get_workflow_handle" modules \
  --glob '!modules/backend/migrations/**' \
  --glob '!modules/backend/temporal/workflow_gateway.py' \
  --glob '!modules/backend/temporal/schedule_gateway.py' \
  | rg -i "MissionRun|MissionScheduleTick|Reconciler|Retention|mission_run_workflow_id"
```

It returns nothing. Every absence grep in this plan excludes `modules/backend/migrations/` (`rg --glob '!modules/backend/migrations/**'`, `grep --exclude-dir=migrations`), because historic and `plan88_*` revisions name the columns and classes being removed.

### 3.0.2 Conventions

- **Enums.** Every new enum is a `str, enum.Enum` with lowercase values, mapped with `Enum(X, native_enum=False, length=32)`. The database stores the uppercase **name**.
- **Wire format.** API request and response bodies, query parameters, SSE event payloads, YAML config and Temporal DTO string fields use the lowercase enum **value** (`kind="objective"`, `?status=running`, `default_kinds: [run_failed]`, `RunStatusUpdate(status="failed", reason="planning_failed")`, `_end_run("failed", "planning_failed", detail)`). `PlanRunResult.status` is `"planned"`, `"empty"` or `"failed"`; `MissionRunWorkflowStatus.phase` is `"planning"`, `"awaiting_gate"`, `"executing"`, `"supervising"` or `"finalising"` (and `"paused"` from 88.4.5); `PauseForRunInput.reason` carries the lowercase `MissionPauseReason` value. Activities parse every such field with `Enum(value)`. Uppercase names appear only in SQL: server defaults, partial-index predicates, `CHECK` constraints and migration `UPDATE`s. Pydantic fields and config validators are typed with the enum (`list[NotificationKind]`), never with a `Literal` of names.
- **Columns.** UUID columns are `PgUUID(as_uuid=False)`. Timestamps are `DateTime(timezone=True)` written with `utc_now()`. Money is `Numeric(12,6, asdecimal=False)`. New JSON columns use `JSONB`.
- **Mixins.** Every new table uses `UUIDMixin` and `TimestampMixin` from `models/base.py`, giving `id`, `created_at` and `updated_at`. Only extra columns are listed below.
- **Migrations.** Files go in `modules/backend/migrations/versions/`. The chain is linear from `plan87_002`, exactly as 3.1.12. Alembic commands use revision ids (`python admin.py migrate downgrade plan88_003`), never filenames. A migration never calls `get_app_config()`: backfill values are module constants with a comment naming the config key and revision, for example `DEFAULT_PER_RUN_USD = 5.00  # missions.budgets.default_per_run_usd at plan88_004`.
- **Patch ids.** A step that introduces `workflow.patched("<id>")` in the same commit: adds the id to `temporal/versioning.PATCH_IDS`, records one history at `tests/fixtures/temporal_histories/mission_run/<id>.json`, and adds the id to the replay test's `REQUIRED` set. The ids are `p88-run-memory` (Phase 3, pre-patch fixture captured from Phase 2 code), `p88-lifecycle-signals`, `p88-budget-caps` and `p88-durable-gate` (Phase 4). `workflow.deprecate_patch` is never used in this plan.
- **Mission scoping.** Every by-id load of a row that belongs to a mission uses `WHERE id = :id AND mission_id = :mission_id` and raises `NotFoundError` when no row matches. This covers at least `MissionScheduleService.get_schedule`, `MissionRunService.cancel_run`, `GateDecisionService.decide` and `NotificationService.remove_recipient` (tests `test_cancel_other_missions_run_404`, `test_decide_other_missions_gate_404`, `test_remove_other_missions_recipient_404`).
- **Owner identity.** `missions.owner_id` is `String(200)` (`models/mission.py:75`), not a foreign key. Any code that needs the owner as a user resolves it with `UserRepository.get_by_id`. A mission whose `owner_id` is not an existing user UUID cannot run: `begin_mission_run` ends the run `FAILED/START_FAILED` with detail `"owner not a platform user"` (test `test_begin_owner_not_user_fails_start_failed`, 88.1.7).
- **Pseudocode.** Every code block in this plan is valid Python. No `...` as an argument or as a call body, and no `<placeholder>` expressions. The only permitted `...` is pydantic's required marker `Field(...)`. Interface listings (3.5.1) are fenced as `text`: they are signatures followed by comments, not code to copy.

### 3.1 Data model

#### 3.1.1 Decision: create `mission_schedules`, drop `workflow_schedules`

`workflow_schedules` is not evolved, for four reasons:
1. **Wrong target.** It is keyed to the wrong thing. `workflow_definition_id` is NOT NULL (`models/workflow_schedule.py:43-48`), and the unique key is `(workflow_definition_id, mission_id, cron_expression)` (`:34-41`).
2. **Poller artefacts.** Four of its columns exist only for the croniter minute poller that decision 2 deletes: `iteration_count`, `cooldown_seconds`, `last_fired_at` and `next_fire_at` (`:87-108`).
3. **Unsafe defaults.** `timezone` defaults to `"UTC"` and nothing reads it. `created_by` is a free string, not a foreign key (`:61-65`, `:109-113`).
4. **Wrong name.** After decision 1 the table schedules missions, so its name would be wrong.

Evolving it would rewrite the key, the target and most of the columns. That is a new table under an old name.

#### 3.1.2 Enums (new or changed)

| Enum (module) | Names (stored) | Introduced |
|---|---|---|
| `GateMode` (`models/mission_plan.py`, replaces `VALID_GATE_MODES` at `:49-56`) | `INTERACTIVE`, `MANUAL`, `AI_ASSISTED`, `AUTONOMOUS` | 88.1.0 |
| `MissionStatus` (`models/mission.py`, unchanged) | `ACTIVE`, `PAUSED`, `ARCHIVED` | exists |
| `MissionPauseReason` (`models/mission.py`) | `USER`, `BUDGET_RUN_CAP`, `BUDGET_MONTHLY_CAP`, `BUDGET_LIFETIME_CAP`, `GATE_TIMEOUT` | 88.4.2 |
| `MissionScheduleKind` (`models/mission_schedule.py`) | `OBJECTIVE`, `WORKFLOW_DEFINITION` | 88.1.3 |
| `MissionScheduleStatus` | `ACTIVE`, `PAUSED`, `COMPLETED`, `ARCHIVED` | 88.1.3 |
| `MissionScheduleCompletedReason` | `END_DATE_REACHED`, `MAX_RUNS_REACHED` | 88.1.3 |
| `TemporalSyncState` | `PENDING`, `SYNCED`, `FAILED` | 88.1.3 |
| `MissionRunTrigger` (`models/mission_run.py`) | `SCHEDULE`, `MANUAL`, `DIRECTOR` | 88.1.2 |
| `MissionRunStatus` | `PENDING`, `RUNNING`, `AWAITING_GATE`, `PAUSED`, `SUCCEEDED`, `FAILED`, `CANCELLED`, `BUDGET_STOPPED`, `SKIPPED`, `MISSED` | 88.1.2 |
| `MissionRunStatusReason` | `OBJECTIVE_MET`, `NO_FURTHER_WORK`, `SUPERVISOR_ESCALATED`, `TASK_FAILURES`, `PLANNING_FAILED`, `GATE_REJECTED`, `INVALID_GATE_MODE`, `CANCELLED_BY_USER`, `MISSION_ARCHIVED`, `BUDGET_RUN_CAP`, `BUDGET_MONTHLY_CAP`, `BUDGET_LIFETIME_CAP`, `START_FAILED`, `ORPHANED_WORKFLOW_CLOSED`, `ORPHANED_WORKFLOW_NOT_FOUND`, `USER_PAUSE`, `GATE_TIMEOUT`, `OVERLAP`, `MISSION_NOT_ACTIVE`, `SCHEDULE_NOT_ACTIVE`, `MAX_RUNS_REACHED`, `BUDGET_CAP_REACHED`, `OUTSIDE_CATCHUP_WINDOW`, `SUPERSEDED`, `NOT_FIRED`, `MAX_DURATION_EXCEEDED` | 88.1.2 (all members; `MAX_DURATION_EXCEEDED` is first used in 88.2.6) |
| `DigestGenerator` (`models/mission_run_digest.py`) | `AGENT`, `DETERMINISTIC` | 88.1.2 |
| `GateRequestStatus` (`models/gate_request.py:25-29`, changed) | `PENDING`, `ESCALATED`, `TIMED_OUT`, `DECIDED`, `CANCELLED` | `ESCALATED` in 88.4.3 |
| `DecisionChannel` (`models/gate_request.py`) | `WEB`, `CLI`, `API`, `TELEGRAM`, `WORKFLOW` | 88.4.3 |
| `ChannelKind` (`models/user_channel_identity.py`) | `TELEGRAM` | 88.4.3 |
| `ActionTokenPurpose` (`models/action_token.py`) | `GATE_DECISION`, `CHANNEL_LINK` | 88.4.3 |
| `NotificationKind` (`models/notification.py`) | `RUN_SUCCEEDED`, `RUN_FAILED`, `GATE_WAITING`, `GATE_ESCALATED`, `GATE_TIMEOUT_PAUSED`, `BUDGET_PAUSED`, `RUN_SKIPPED`, `RUN_MISSED` | 88.4.3 |
| `NotificationDeliveryStatus` | `SENT`, `FAILED`, `SKIPPED_NO_IDENTITY`, `SKIPPED_DISABLED` | 88.4.3 |
| `FailureOrigin` (`schemas/task_failure.py`) | `PLATFORM`, `PROVIDER`, `ENVIRONMENT`, `AGENT`, `UPSTREAM`, `CONTROL`, `UNKNOWN` | 88.2.3b (columns since `plan88_002`) |
| `FailureClass` (`schemas/task_failure.py`) | `TRANSIENT_PROVIDER`, `QUOTA_EXHAUSTED`, `AGENT_CONTRACT`, `AGENT_TOOL_ERROR`, `AGENT_REPORTED_FAILURE`, `VERIFICATION_FAILED`, `TIMEOUT`, `UPSTREAM_BLOCKED`, `PLATFORM_DEFECT`, `PLATFORM_DEPENDENCY_MISSING`, `PLATFORM_TRANSIENT`, `ORPHANED`, `ENV_UNAVAILABLE`, `CANCELLED`, `BUDGET_EXCEEDED`, `RUN_ABORTED`, `UNKNOWN`. `TARGET` origin and its classes arrive with the repair-loop plan (3.8.7) | 88.2.3b (columns since `plan88_002`) |

**Status meanings:**
- **Gate request `TIMED_OUT`.** The pause window passed and the run is PAUSED, but the gate can still be decided.
- **Decision channel `WORKFLOW`.** An AI or autonomous reviewer decided inside the workflow.
- **Run status reason `MAX_DURATION_EXCEEDED`.** Active execution time, excluding time spent waiting at a gate, reached `mission_run.max_run_duration_seconds` (88.2.6).

**Gate-mode rules:**
- `AUTO_APPROVE_GATE_MODES` (`models/mission_plan.py:59`, today `{"ai_assisted", "autonomous"}`) becomes `frozenset({GateMode.AUTONOMOUS})` in 88.1.0. AI_ASSISTED means the AI recommends and a human decides, which matches `gate.yaml`'s own definition.
- The `workflow_managed` pseudo-mode (`services/workflow_run.py:512-513`) is deleted in 88.0.6.
- Fail-open defaults are removed in 88.0.5: `temporal/scheduled_activities.py:84`, `agents/mission_control/gate.py:282-286`, `temporal/plan_refine_activities.py:63` (auto-approves after a refine unless the mode is `interactive`) and `agents/mission/director/agent.py:152`. Each resolves the mode through `resolve_gate_mode`, which maps NULL and unknown values to MANUAL. 88.1.0 retypes `resolve_gate_mode` to return `GateMode`.
- An unknown gate **action** fails closed from 88.0.5: `_parse_action` (`agents/mission_control/gate_prompt.py:145`) logs at warning and returns `GateAction.ABORT` instead of CONTINUE (test `test_unknown_gate_action_aborts`). No `defaulting to CONTINUE` text remains in `modules/backend`.
- `GateSchema.mode` becomes required (`Field(...)`, no hardcoded default) in 88.1.0 (test `test_gate_schema_mode_required`); the comment at `agents/mission_control/gate_post_run.py:88` is reworded to `GateMode.MANUAL`.

#### 3.1.3 `missions` (changed)

| Column | SQL type | Null | Default | FK / index / constraint | Migration |
|---|---|---|---|---|---|
| `run_sequence_counter` | INTEGER | NO | `0` (server) | none. Incremented by `UPDATE … RETURNING` to allocate `mission_runs.sequence` | `plan88_002` |
| `paused_reason` | VARCHAR(32) `MissionPauseReason` | YES | NULL | none | `plan88_005` |
| `paused_at` | TIMESTAMPTZ | YES | NULL | none | `plan88_005` |
| `paused_by_user_id` | UUID | YES | NULL | FK `users.id` ON DELETE SET NULL | `plan88_005` |

- **Constraint** (`plan88_005`): `ck_missions_pause_consistent CHECK ((status = 'PAUSED') = (paused_reason IS NOT NULL))`. Before adding it, the migration runs `UPDATE missions SET paused_reason = 'USER', paused_at = now() WHERE status = 'PAUSED'`.
- **Dropped (P3):**
  - `gate_mode` (`models/mission.py:101`, `plan88_001`): moves to `mission_plans.gate_mode`, NOT NULL.
  - `budget_ceiling_usd` (`models/mission.py:89`, `plan88_004`): moves to the `mission_plans` budget columns.
- **Schema rule:** `MissionUpdate.status` (`schemas/mission.py:85`) is deleted in 88.4.2. Status changes only through the lifecycle endpoints in 3.5.3.

#### 3.1.4 `mission_plans` (changed; still one row per mission, created eagerly in `create_mission` from 88.1.0)

| Column | SQL type | Null | Default | Constraint | Migration |
|---|---|---|---|---|---|
| `gate_mode` | VARCHAR(32) `GateMode` | **NO** | none (the service must supply it) | none | `plan88_001` |
| `budget_per_run_usd` | NUMERIC(12,6) | NO | none | `CHECK > 0` | `plan88_004` |
| `budget_per_month_usd` | NUMERIC(12,6) | NO | none | `CHECK > 0`, `CHECK >= budget_per_run_usd` | `plan88_004` |
| `budget_lifetime_usd` | NUMERIC(12,6) | YES | NULL (no lifetime cap) | `CHECK > 0`. Renamed from `budget_usd_ceiling` | `plan88_004` |

**Dropped (P3):**
- `veto_window_sec` (`plan88_001`): AI_ASSISTED no longer auto-approves.
- `total_spent_usd` (`plan88_004`): `llm_calls` is the ledger.
- `status` (`plan88_005`). The column and the whole `MissionPlanStatus` enum go, because `missions.status` is the only lifecycle. 88.4.2 rewrites `check_plan_active` to read `missions.status`; 88.4.5 stops calling it under `p88-lifecycle-signals`, and deletes it only when no caller remains (otherwise the activity stays registered for executions on the old branch). `pause_all_autonomous_plans` (`services/mission_plan.py:226`) is deleted in 88.4.5 and replaced by `MissionLifecycleService.pause_all_active`.
- `supervisor_iteration_count` and `max_supervisor_iterations` (`plan88_005`): the iteration count moves to `mission_runs.iteration_count` (written by `evaluate_post_run` from 88.2.6), and the cap is removed by decision 12.

**Migration rules for `gate_mode` (`plan88_001`), in order:**
1. Copy `missions.gate_mode` where the plan value is NULL.
2. Set `workflow_managed`, NULL and any value outside the four modes to `manual`. This fails closed.
3. Uppercase all values to names.
4. Create a `mission_plans` row with `gate_mode = 'MANUAL'` for every mission that has none, so the eager-creation invariant holds for existing data.

**Migration rule for budgets (`plan88_004`):** `budget_per_run_usd` and `budget_per_month_usd` are backfilled from module constants:
```python
DEFAULT_PER_RUN_USD = 5.00     # missions.budgets.default_per_run_usd at plan88_004
DEFAULT_PER_MONTH_USD = 100.00  # missions.budgets.default_per_month_usd at plan88_004
```

#### 3.1.5 `mission_schedules` (new, `plan88_003`)

| Column | SQL type | Null | Default | FK / index / constraint |
|---|---|---|---|---|
| `mission_id` | UUID | NO | none | FK `missions.id` ON DELETE CASCADE; index |
| `name` | VARCHAR(100) | NO | none | `uq_mission_schedules_mission_name (mission_id, name)` |
| `kind` | VARCHAR(32) `MissionScheduleKind` | NO | none | immutable after create |
| `objective_template` | TEXT | YES | none | required when kind=OBJECTIVE |
| `workflow_definition_id` | UUID | YES | none | FK `workflow_definitions.id` ON DELETE RESTRICT; required when kind=WORKFLOW_DEFINITION |
| `workflow_parameters` | JSONB | NO | `'{}'` | none |
| `cron_expression` | VARCHAR(100) | NO | none | 5-field cron, interpreted by Temporal |
| `time_zone_name` | VARCHAR(64) | NO | none | IANA name, validated with `zoneinfo.ZoneInfo`. No default |
| `starts_at` | TIMESTAMPTZ | YES | NULL | none |
| `ends_at` | TIMESTAMPTZ | YES | NULL | `CHECK (ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at)` |
| `max_runs` | INTEGER | YES | NULL | `CHECK (max_runs IS NULL OR max_runs > 0)` |
| `catch_up_window_seconds` | INTEGER | NO | none (the service sets it from config) | `CHECK > 0` |
| `status` | VARCHAR(32) `MissionScheduleStatus` | NO | `'ACTIVE'` (server) | index `(mission_id, status)` |
| `completed_reason` | VARCHAR(32) `MissionScheduleCompletedReason` | YES | NULL | `CHECK ((status='COMPLETED') = (completed_reason IS NOT NULL))` |
| `executed_run_count` | INTEGER | NO | `0` | counts claims that produced a RUN |
| `last_claimed_scheduled_for` | TIMESTAMPTZ | YES | NULL | missed-occurrence backfill watermark |
| `temporal_schedule_id` | VARCHAR(200) | NO | none | UNIQUE. Always `mission-schedule-{id}` |
| `temporal_sync_state` | VARCHAR(32) `TemporalSyncState` | NO | `'PENDING'` | none |
| `temporal_synced_at` | TIMESTAMPTZ | YES | NULL | none |
| `temporal_sync_error` | TEXT | YES | NULL | none. Written through `redact_secrets` from 88.1.6 |
| `tick_config_hash` | VARCHAR(64) | YES | NULL | SHA-256 of the `TickConfigSnapshot` registered in Temporal |
| `created_by_user_id` | UUID | NO | none | FK `users.id` ON DELETE RESTRICT |

**Constraint:** `ck_mission_schedules_target CHECK ((kind='OBJECTIVE' AND objective_template IS NOT NULL AND workflow_definition_id IS NULL) OR (kind='WORKFLOW_DEFINITION' AND workflow_definition_id IS NOT NULL AND objective_template IS NULL))`.

**Objective template placeholders:** only `{scheduled_for}` (ISO 8601 in the schedule's time zone), `{sequence}` and `{mission_name}` are allowed. Any other placeholder is rejected at create and update, by parsing with `string.Formatter`.

**Also in `plan88_003`:** the FK `mission_runs.schedule_id → mission_schedules.id` ON DELETE SET NULL, because `mission_schedules` does not exist at `plan88_002`.

**Dropped (P3), in 88.1.3:**
- The `workflow_schedules` table.
- Its model, repository and service: `models/workflow_schedule.py`, `repositories/workflow_schedule.py` and `services/workflow_schedule.py`.
- `tasks/workflow_scheduler.py`, `EvaluateWorkflowSchedulesWorkflow` and `run_evaluate_workflow_schedules`.
- The `admin schedule` CLI group (`admin_groups/schedule.py`, `schedule_cmds.py`), replaced by `admin schedules sync` (3.5.4).

**Data migration for existing `workflow_schedules` rows:** each row becomes a `mission_schedules` row with:
- `kind='WORKFLOW_DEFINITION'` and `status='PAUSED'`, so the owner must resume it under the new time-zone semantics.
- `name = 'wf-' || left(id::text, 8)`.
- `time_zone_name` taken from the old `timezone` column, with `max_runs = max_iterations`.
- `catch_up_window_seconds = DEFAULT_CATCH_UP_WINDOW_SECONDS`, a module constant `21600  # missions.recurrence.default_catch_up_window_seconds at plan88_003`.
- `created_by_user_id` parsed from `created_by` (`user:<uuid>`) when that UUID exists in `users`, or else the mission owner when `owner_id` is an existing user UUID. A row with neither is not migrated, and its id is logged.
- `budget_per_run_usd` (`models/workflow_schedule.py:77`) and `description` (`:72`) are dropped (P3). The migration logs the count of rows with a non-NULL `budget_per_run_usd`.

#### 3.1.6 `mission_runs` (new, `plan88_002`; one row per occurrence, kept permanently)

| Column | SQL type | Null | Default | FK / index / constraint |
|---|---|---|---|---|
| `mission_id` | UUID | NO | none | FK `missions.id` ON DELETE CASCADE |
| `plan_id` | UUID | NO | none | FK `mission_plans.id` ON DELETE CASCADE |
| `schedule_id` | UUID | YES | NULL | index. FK `mission_schedules.id` ON DELETE SET NULL, added in `plan88_003` |
| `sequence` | INTEGER | NO | none | `uq_mission_runs_mission_sequence (mission_id, sequence)` |
| `trigger` | VARCHAR(32) `MissionRunTrigger` | NO | none | none |
| `triggered_by_user_id` | UUID | YES | NULL | FK `users.id` ON DELETE SET NULL. NULL only when trigger=SCHEDULE |
| `scheduled_for` | TIMESTAMPTZ | YES | NULL | `uq_mission_runs_schedule_slot (schedule_id, scheduled_for)` |
| `previous_run_id` | UUID | YES | NULL | FK `mission_runs.id` ON DELETE SET NULL. Points to the latest earlier run that has a digest |
| `objective` | TEXT | YES | NULL | rendered template. NULL means a backlog dispatch (approved tasks only) |
| `workflow_definition_id` | UUID | YES | NULL | FK `workflow_definitions.id` ON DELETE RESTRICT |
| `workflow_parameters` | JSONB | NO | `'{}'` | none |
| `status` | VARCHAR(32) `MissionRunStatus` | NO | `'PENDING'` (server) | none |
| `status_reason` | VARCHAR(40) `MissionRunStatusReason` | YES | NULL | none |
| `status_detail` | TEXT | YES | NULL | none. Written through `redact_secrets` from 88.1.6 |
| `gate_mode` | VARCHAR(32) `GateMode` | YES | NULL | snapshot taken at `begin_mission_run`. NOT NULL once status leaves PENDING (checked by the service) |
| `temporal_workflow_id` | VARCHAR(200) | YES | NULL | UNIQUE (`uq_mission_runs_temporal_workflow_id`). Always `mission_run_workflow_id(id)` = `mission-run-{id}`. NULL for SKIPPED and MISSED |
| `session_id` | UUID | YES | NULL | FK `sessions.id` ON DELETE SET NULL |
| `context_version_start` | INTEGER | YES | NULL | MCD watermark, read at begin |
| `context_version_end` | INTEGER | YES | NULL | MCD version when the digest was written; set by write_run_digest. finalise_mission_run sets it only when NULL |
| `iteration_count` | INTEGER | NO | `0` | supervisor iterations, summed across continue-as-new. Written by `evaluate_post_run` from 88.2.6 |
| `budget_cap_usd` | NUMERIC(12,6) | YES | NULL | snapshot of `plan.budget_per_run_usd`, written by `begin` from 88.4.1. NULL for runs begun earlier |
| `cost_usd` | NUMERIC(12,6) | NO | `0` | written by `finalise` from 88.1.7 as `sum(llm_calls.cost_usd) WHERE mission_run_id = run.id` (test `test_finalise_writes_ledger_cost`) |
| `task_count` / `completed_task_count` / `failed_task_count` | INTEGER | NO | `0` | none |
| `config_snapshot` | JSONB | NO | `'{}'` | the `RunConfigSnapshot` used (3.3.4) |
| `cancel_requested_at` | TIMESTAMPTZ | YES | NULL | none |
| `cancel_requested_by_user_id` | UUID | YES | NULL | FK `users.id` ON DELETE SET NULL |
| `cancel_reason` | VARCHAR(40) `MissionRunStatusReason` | YES | NULL | limited to `CANCELLED_BY_USER` or `MISSION_ARCHIVED` |
| `started_at` / `ended_at` | TIMESTAMPTZ | YES | NULL | none |

**Indexes and constraints:**
- `ix_mission_runs_mission_created (mission_id, created_at DESC)`.
- **Mission-level overlap lock:** `uq_mission_runs_one_active` UNIQUE `(mission_id)` WHERE `status IN ('PENDING','RUNNING','AWAITING_GATE','PAUSED')`.
- `ix_mission_runs_nonterminal (status, updated_at)` WHERE `status IN ('PENDING','RUNNING','AWAITING_GATE','PAUSED')`, used by the reconciler.
- `ck_mission_runs_schedule_slot CHECK ((trigger='SCHEDULE') = (scheduled_for IS NOT NULL AND schedule_id IS NOT NULL))`.

**Sequence rule.** Every `mission_runs` row, including SKIPPED and MISSED, consumes exactly one sequence number from `missions.run_sequence_counter`. A rolled-back insert rolls back its increment too, so the sequence per mission is gap-free (3.5.1 `start_run` and `resume_mission`, 3.3.2 `claim_occurrence`; test `test_conflict_leaves_no_sequence_gap`).

#### 3.1.7 `mission_run_digests` (new, `plan88_002`; kept permanently)

| Column | SQL type | Null | Default | FK / index / constraint |
|---|---|---|---|---|
| `mission_run_id` | UUID | NO | none | FK `mission_runs.id` ON DELETE CASCADE; UNIQUE |
| `mission_id` | UUID | NO | none | FK `missions.id` ON DELETE CASCADE; index `ix_mission_run_digests_mission_created (mission_id, created_at DESC)` |
| `schema_version` | INTEGER | NO | none | starts at `1` |
| `generator` | VARCHAR(32) `DigestGenerator` | NO | none | none |
| `summary` | TEXT | NO | none | length ≤ `missions.digest.summary_max_chars` |
| `outcomes` | JSONB | NO | none | `[{task_id, agent, status, headline, artifact_ids}]` (statuses as lowercase values), at most `digest.max_outcomes` entries. `headline` ≤ `digest.headline_max_chars` |
| `decisions` | JSONB | NO | `'[]'` | `[{gate_request_id, gate_point, action, channel, decided_by_user_id}]`. 88.3.7 writes `[]`; 88.4.8 populates it from `gate_requests`. Written from Phase 4 (88.4.8); `[]` before then |
| `open_items` | JSONB | NO | `'[]'` | `[{text, source_task_id}]` |
| `context_changes` | JSONB | NO | `'[]'` | `[{version, change_type, path}]` for MCD changes in `(context_version_start, context_version_end]` |
| `metrics` | JSONB | NO | none | `{cost_usd, duration_seconds, task_count, completed_task_count, failed_task_count, iteration_count}` |
| `generation_cost_usd` | NUMERIC(12,6) | NO | `0` | none |

**Invariant (from 88.3.8):** every run that reached RUNNING has exactly one digest before it enters a terminal status.

**When the digest is `DETERMINISTIC`:**
- The digest agent failed after its retries.
- The run is `BUDGET_STOPPED`, because no LLM spend is allowed after a cap breach.
- The run is `CANCELLED`.

The run-finished notification states the generator.

#### 3.1.8 Linking columns on existing tables

| Table.column | SQL type | Null | FK / index | Migration |
|---|---|---|---|---|
| `tasks.mission_run_id` | UUID | YES (NULL means backlog, not yet dispatched) | FK `mission_runs.id` ON DELETE SET NULL; index `ix_tasks_run_status (mission_run_id, status)` | `plan88_002` |
| `execution_records.mission_run_id` | UUID | YES | FK `mission_runs.id` ON DELETE SET NULL; `uq_execution_records_run` UNIQUE `(mission_run_id)` WHERE NOT NULL. One ExecutionRecord per run, created in `begin_mission_run` | `plan88_002` |
| `task_executions.mission_run_id` | UUID | YES | FK `mission_runs.id` ON DELETE SET NULL; index | `plan88_002` |
| `task_executions.idempotency_key` | VARCHAR(100) | YES | UNIQUE. Format `{mission_run_id}:{task_id}:{task.retry_count}` | `plan88_002` |
| `tasks.failure_origin` / `task_executions.failure_origin` | VARCHAR(32) `FailureOrigin` | YES (NULL unless the row is FAILED) | none | `plan88_002` |
| `tasks.failure_class` / `task_executions.failure_class` | VARCHAR(40) `FailureClass` | YES (NULL unless the row is FAILED) | none | `plan88_002` |
| `tasks.failure_fingerprint` / `task_executions.failure_fingerprint` | VARCHAR(64) | YES | `ix_task_executions_failure_fingerprint (failure_fingerprint)` on `task_executions` only. `tasks` holds the current attempt; `task_executions` holds one row per attempt and survives `retry_task`, which clears the `tasks` columns | `plan88_002` |
| `task_executions.failure_json` | JSONB | YES | `TaskFailure.model_dump(mode="json")` (3.8.2), bounded by `failures.evidence`. Set to NULL with `output_data` after `retention.task_outputs_days`; the three classification columns are kept | `plan88_002` |
| `context_changes.mission_run_id` | UUID | YES | FK `mission_runs.id` ON DELETE SET NULL; index | `plan88_002` |
| `context_changes` index | n/a | n/a | `ix_context_changes_context_version (context_id, version)`. Keyed on `context_id` because legacy rows from `tools/update_context.py:37-48` and `services/summarization.py:101,162` have `mission_id IS NULL` | `plan88_002` |
| `llm_calls.mission_run_id` | UUID | YES | no FK, matching the existing table style (`models/llm_call.py:15-34`); index `ix_llm_calls_mission_run_id (mission_run_id)` | `plan88_002` |
| `llm_calls.task_id` | UUID | YES | no FK; index `ix_llm_calls_task_id (task_id)` | `plan88_002` |
| `llm_calls` index | n/a | n/a | `ix_llm_calls_mission_created (mission_id, created_at)`. Already created by revision `composite_indexes`; `plan88_002` does not recreate it, and the model now declares it | exists |
| `gate_requests.mission_run_id` | UUID | YES (NULL only on legacy rows) | FK `mission_runs.id` ON DELETE CASCADE; index | `plan88_006` |
| `gate_requests.task_id` | UUID | YES | none | `plan88_006` |
| `gate_requests.escalate_at` / `pause_at` / `escalated_at` | TIMESTAMPTZ | YES | none | `plan88_006` |
| `gate_requests.decision_channel` | VARCHAR(32) `DecisionChannel` | YES | none | `plan88_006` |
| `gate_requests.ai_recommendation_json` | JSONB | YES | none | `plan88_006` |
| `gate_requests.status` | VARCHAR(32) | NO | widened from the unsized column at `models/gate_request.py:75` | `plan88_006` |

**Gate point naming.** The `gate_requests` column holding the gate point keeps its name `gate_type` (`models/gate_request.py:64`). Every DTO field named `gate_point` maps to it.

**Dropped (P3):**
- `execution_records.parent_execution_record_id` (`plan88_002`), which is never set. Its reader `repositories/execution_record.py:142-160` (`get_replan_chain`), the schema field and the `services/execution_persistence.py:87,129` parameter go with it.
- `tasks.veto_expires_at` (`plan88_001`).

**Migration for gate requests (`plan88_006`):** legacy `gate_requests` rows with status `PENDING` or `TIMED_OUT` and `mission_run_id IS NULL` are set to `CANCELLED`. A gate request can be decided only when `mission_run_id IS NOT NULL` and the run is `AWAITING_GATE` or `PAUSED`.

#### 3.1.9 Idempotency (per task, 88.2.4)

`execute_plan_task` runs two short transactions. `claim` locks the `tasks` row (`SELECT … FOR UPDATE`), applies rules A and B, sets the task RUNNING and commits before the agent call. `record` locks the row again, re-checks the key, and makes the step 3 atomic write. The UNIQUE `idempotency_key` arbitrates between concurrent attempts. No row lock is held across the agent call, which can last up to `execute_task.start_to_close_seconds` (3,600s). In detail:
1. **Claim.** Lock the `tasks` row (`SELECT … FOR UPDATE`), apply rules A and B, transition the task to `RUNNING` when needed, and commit.
   - **A. Already finished.** If the task is `COMPLETED` or `SKIPPED`, or a `task_executions` row with the key exists, return the stored result with `idempotent_replay=True`. No LLM call is made and no spend is recorded.
   - **B. Interrupted attempt.** If the task is `RUNNING` (the previous attempt died), re-execute under the same key. Spend from the dead attempt stays in `llm_calls` and is attributed through `llm_calls.task_id`.
2. **Execute.** Run the agent with no transaction open.
3. **Record.** Lock the `tasks` row again and re-check the key. If a `task_executions` row with the key now exists, return it. Otherwise write the `task_executions` insert (with the key), the task status transition and `tasks.cost_usd` in one transaction. The UNIQUE `idempotency_key` arbitrates between concurrent attempts: an `IntegrityError` on it means another attempt recorded first, and the stored row is returned.

**Retry count.** `tasks.retry_count` is incremented only by `MissionPlanService.retry_task` (`services/mission_plan.py:539`). The write-back increments at `services/mission_plan_taskio.py:208,231` are deleted in 88.2.4, so the key changes exactly once per deliberate retry.

**Task transitions.** `VALID_TASK_TRANSITIONS[QUEUED]` gains `FAILED` (88.0.10, `models/task.py:61`). `VALID_TASK_TRANSITIONS[FAILED]` is `{APPROVED, SKIPPED}`: 88.2.6 adds `SKIPPED`, used by `resolve_failed_task`.

#### 3.1.10 Notifications and Telegram binding (new tables, `plan88_007`)

**`user_channel_identities`:**

| Column | SQL type | Null | Default | FK / constraint |
|---|---|---|---|---|
| `user_id` | UUID | NO | none | FK `users.id` ON DELETE CASCADE |
| `channel` | VARCHAR(32) `ChannelKind` | NO | none | none |
| `external_id` | VARCHAR(64) | NO | none | Telegram `from_user.id` as a decimal string |
| `external_username` | VARCHAR(64) | YES | NULL | Telegram `@username` at redeem time, shown to the user for confirmation |
| `verified_at` | TIMESTAMPTZ | **YES** | NULL | NULL until the user confirms the link (section 3.1.10) |

- **Unique:** `uq_channel_identity_external (channel, external_id)` and `uq_channel_identity_user (user_id, channel)`.
- **Two-step linking.** `redeem_link_code` inserts the row with `verified_at = NULL`. The user confirms it with `POST /auth/me/channel-identities/{iid}/confirm`, which sets `verified_at = utc_now()`. Only rows with `verified_at IS NOT NULL` resolve for delivery or for decisions. Redeeming again for the same `(user_id, channel)` replaces an unverified row and is rejected with `ConflictError` when a verified row exists (the user unlinks first).

**`action_tokens`** (single-use, expiring):

| Column | SQL type | Null | Default | FK / constraint |
|---|---|---|---|---|
| `purpose` | VARCHAR(32) `ActionTokenPurpose` | NO | none | none |
| `token_hash` | CHAR(64) | NO | none | UNIQUE. SHA-256 hex of the raw token. The raw token is never stored |
| `user_id` | UUID | NO | none | FK `users.id` ON DELETE CASCADE. The only user allowed to consume it |
| `channel` | VARCHAR(32) `ChannelKind` | NO | none | none |
| `gate_request_id` | UUID | YES | none | FK `gate_requests.id` ON DELETE CASCADE. Required when purpose=GATE_DECISION |
| `channel_message_ref` | VARCHAR(100) | YES | none | `"{chat_id}:{message_id}"`, so the message can be edited after the decision |
| `expires_at` | TIMESTAMPTZ | NO | none | index |
| `consumed_at` | TIMESTAMPTZ | YES | NULL | none |
| `consumed_action` | VARCHAR(32) | YES | NULL | none |
| `consumed_ref` | VARCHAR(100) | YES | NULL | UNIQUE. Telegram `callback_query.id`, giving replay protection |

- **Constraint:** `CHECK ((purpose='GATE_DECISION') = (gate_request_id IS NOT NULL))`.
- **Raw token:** 16 bytes from `secrets.token_bytes`, encoded base64url without padding (22 characters).
- **Telegram callback data:** `g:{token}:{a|r}` (at most 27 bytes, under the 64-byte limit).

**`mission_notification_recipients`:**

| Column | SQL type | Null | Default | FK / constraint |
|---|---|---|---|---|
| `mission_id` | UUID | NO | none | FK `missions.id` ON DELETE CASCADE |
| `user_id` | UUID | NO | none | FK `users.id` ON DELETE CASCADE |
| `channel` | VARCHAR(32) `ChannelKind` | NO | none | none |
| `kinds` | JSONB | NO | none | list of `NotificationKind` **values** (lowercase). Set at insert from `notifications.default_kinds` |

- **Unique:** `uq_recipient (mission_id, user_id, channel)`.
- **Default row:** from 88.4.3, `create_mission` inserts one row for the owner with channel `TELEGRAM` when `owner_id` is an existing user UUID.
- **Backfill (`plan88_007`):** one owner row per mission, joined on `users` so owners that are not user UUIDs are skipped. `kinds` comes from a module constant `DEFAULT_KINDS = ["run_succeeded", "run_failed", "gate_waiting", "gate_escalated", "gate_timeout_paused", "budget_paused", "run_skipped", "run_missed"]  # notifications.default_kinds at plan88_007`.
- **Membership rule:** a recipient must be the owner or a mission member, checked by the service.

**`notification_deliveries`** (audit and idempotency):

| Column | SQL type | Null | Default | FK / constraint |
|---|---|---|---|---|
| `mission_id` | UUID | NO | none | FK `missions.id` ON DELETE CASCADE; index `(mission_id, created_at)` |
| `mission_run_id` | UUID | YES | none | FK `mission_runs.id` ON DELETE SET NULL |
| `kind` | VARCHAR(32) `NotificationKind` | NO | none | none |
| `recipient_user_id` | UUID | NO | none | FK `users.id` ON DELETE CASCADE |
| `channel` | VARCHAR(32) `ChannelKind` | NO | none | none |
| `dedupe_key` | VARCHAR(200) | NO | none | UNIQUE. Format `{kind_value}:{subject_id}:{recipient_user_id}:{channel_value}` |
| `status` | VARCHAR(32) `NotificationDeliveryStatus` | NO | none | none |
| `attempt_count` | INTEGER | NO | `0` | none |
| `provider_message_ref` | VARCHAR(100) | YES | none | none |
| `error` | TEXT | YES | none | always written through `redact_secrets` |
| `sent_at` | TIMESTAMPTZ | YES | none | none |

`subject_id` is one of:
- `mission_run_id` for `RUN_*` and `BUDGET_PAUSED`;
- `gate_request_id` for `GATE_*`;
- `{schedule_id}:{claim_scheduled_for_iso}` for `RUN_SKIPPED` and `RUN_MISSED`. One notification is sent per claim, carrying a count of missed slots.

#### 3.1.11 Ledger aggregates (new, `plan88_004`; retention target)

**`llm_call_daily_aggregates`** has no UUIDMixin. It uses an `id` BIGSERIAL primary key plus `created_at` (`server_default=now()`). It is created in 88.4.1 so that `BudgetService` sums it unconditionally, with no runtime check for the table's existence. Rows are written only by the retention rollup (88.5.3).

| Column | SQL type | Null |
|---|---|---|
| `day` | DATE (UTC) | NO |
| `mission_id` | UUID | YES |
| `agent_name` | VARCHAR(200) | NO |
| `model` | VARCHAR(100) | NO |
| `provider` | VARCHAR(50) | NO |
| `call_count` | INTEGER | NO |
| `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_5m_tokens`, `cache_write_1h_tokens`, `thinking_tokens` | BIGINT | NO |
| `cost_usd` | NUMERIC(14,6) | NO |

- **Unique:** `uq_llm_daily UNIQUE NULLS NOT DISTINCT (day, mission_id, agent_name, model, provider)`. This needs Postgres 16, which CI uses (`.github/workflows/ci.yml:62`).
- **Index:** `ix_llm_daily_mission_day (mission_id, day)`.
- **Ledger rule:** `BudgetService` monthly and lifetime sums always add aggregates and raw rows. Retention never rolls up `llm_calls` rows whose `mission_run_id` belongs to a non-terminal run. `mission_runs.cost_usd` is read from raw rows only, which is safe because a run is terminal before its rows can be rolled up.

#### 3.1.12 Migrations (ids, chain and contents)

The chain is linear. No other `plan88_*` revisions exist. 88.3.2 creates no migration.

| Revision | `down_revision` | Step | Contents |
|---|---|---|---|
| `plan88_001_gate_mode_enum` | `plan87_002` | 88.1.0 | `mission_plans.gate_mode` NOT NULL enum (rules in 3.1.4, including the missing-plan insert); drop `missions.gate_mode`; drop `mission_plans.veto_window_sec` and `tasks.veto_expires_at` |
| `plan88_002_mission_runs` | `plan88_001` | 88.1.2 | `missions.run_sequence_counter`; `mission_runs` (without the `schedule_id` FK); `mission_run_digests`; `tasks.mission_run_id`; `execution_records.mission_run_id` and `uq_execution_records_run`; `task_executions.mission_run_id` and `idempotency_key`; the failure columns on `tasks` and `task_executions` and `ix_task_executions_failure_fingerprint` (3.1.8); `context_changes.mission_run_id` and `ix_context_changes_context_version`; `llm_calls.mission_run_id`, `llm_calls.task_id`, `ix_llm_calls_mission_run_id`, `ix_llm_calls_task_id`, `ix_llm_calls_mission_created`; drop `execution_records.parent_execution_record_id` |
| `plan88_003_mission_schedules` | `plan88_002` | 88.1.3 | `mission_schedules`; FK `mission_runs.schedule_id`; data migration from `workflow_schedules` (3.1.5), logging the count of rows with non-NULL `budget_per_run_usd`; drop `workflow_schedules` |
| `plan88_004_budget_caps` | `plan88_003` | 88.4.1 | `mission_plans.budget_per_run_usd` and `budget_per_month_usd` (backfilled from constants); rename `budget_usd_ceiling` to `budget_lifetime_usd`; drop `mission_plans.total_spent_usd` and `missions.budget_ceiling_usd`; create `llm_call_daily_aggregates`. No `llm_calls` columns |
| `plan88_005_lifecycle` | `plan88_004` | 88.4.2 | `missions.paused_reason`, `paused_at`, `paused_by_user_id`; backfill `USER` for PAUSED missions; `ck_missions_pause_consistent`; drop `mission_plans.status`, `supervisor_iteration_count`, `max_supervisor_iterations` |
| `plan88_006_gate_requests_durable` | `plan88_005` | 88.4.3 | the `gate_requests` columns in 3.1.8; widen `status` to VARCHAR(32); legacy row update |
| `plan88_007_notifications` | `plan88_006` | 88.4.3 | `user_channel_identities` (with nullable `verified_at` and `external_username`), `action_tokens`, `mission_notification_recipients` (owner backfill), `notification_deliveries` |
| `plan88_008_retention_indexes` | `plan88_007` | 88.5.2 | retention indexes only, created with `postgresql_concurrently=True` inside `autocommit_block()`: `ix_mission_events_created_at`, `ix_task_executions_completed_at`, `ix_execution_records_completed_at`, `ix_mission_runs_ended_at`, `ix_notification_deliveries_created_at` |

Each migration implements `downgrade()` structurally. Downgrade is not required to restore dropped data.

### 3.2 State machines

#### 3.2.1 MissionRun

Allowed transitions are held in `VALID_RUN_TRANSITIONS` in `models/mission_run.py`. They are enforced only by `MissionRun.transition_status()`, which raises `MissionRunStateError` (non-retryable), the same pattern as `Task.transition_status` (`models/task.py:256-268`). The full table is created in 88.1.2; the "First used" column says which step first drives each transition.

| From | To | Trigger | First used |
|---|---|---|---|
| (insert) | `PENDING` | `claim_occurrence` outcome RUN; `MissionRunService.start_run` | 88.1.6, 88.1.7 |
| (insert) | `SKIPPED` | claim: `OVERLAP`, `MISSION_NOT_ACTIVE`, `SCHEDULE_NOT_ACTIVE`, `MAX_RUNS_REACHED`; `BUDGET_CAP_REACHED` | 88.1.6; budget 88.4.6 |
| (insert) | `MISSED` | claim: `OUTSIDE_CATCHUP_WINDOW`, `SUPERSEDED`, `NOT_FIRED` (backfill) | 88.1.6 |
| `PENDING` | `RUNNING` | `begin_mission_run` | 88.1.7 |
| `PENDING` | `FAILED` | `START_FAILED` (Temporal start error, or owner not a platform user), `INVALID_GATE_MODE`, `ORPHANED_*` | 88.1.7; orphan 88.1.10a |
| `PENDING` | `CANCELLED` | cancel before begin | 88.1.12 |
| `RUNNING` | `AWAITING_GATE` | a durable gate opens for a human | 88.4.8 |
| `RUNNING` | `PAUSED` | `USER_PAUSE`, after the current layer's in-flight task activities finish | 88.4.5 |
| `RUNNING` | `SUCCEEDED` | `OBJECTIVE_MET`, `NO_FURTHER_WORK` | 88.1.8 |
| `RUNNING` | `FAILED` | `TASK_FAILURES`, `PLANNING_FAILED`, `SUPERVISOR_ESCALATED`, `ORPHANED_*`; `MAX_DURATION_EXCEEDED` | 88.1.8, 88.1.10a; 88.2.6 |
| `RUNNING` | `BUDGET_STOPPED` | `BUDGET_RUN_CAP`, `BUDGET_MONTHLY_CAP`, `BUDGET_LIFETIME_CAP` | 88.4.6 |
| `RUNNING` | `CANCELLED` | `CANCELLED_BY_USER`, `MISSION_ARCHIVED`, `GATE_REJECTED` (an AUTONOMOUS `abort`) | 88.1.8; archive 88.4.5; gate 88.4.8 |
| `AWAITING_GATE` | `RUNNING` | approve-type decision | 88.4.8 |
| `AWAITING_GATE` | `PAUSED` | `GATE_TIMEOUT` (after `gate_pause_after_seconds`), or `USER_PAUSE` delivered while the gate waits | 88.4.8, 88.4.5 |
| `AWAITING_GATE` | `CANCELLED` | `GATE_REJECTED`, `CANCELLED_BY_USER`, `MISSION_ARCHIVED` | 88.4.8 |
| `AWAITING_GATE` | `FAILED` | `ORPHANED_*` | 88.4.8 |
| `PAUSED` | `RUNNING` | `resume` signal, or a gate decision after `GATE_TIMEOUT` | 88.4.5, 88.4.8 |
| `PAUSED` | `CANCELLED` | `GATE_REJECTED`, `CANCELLED_BY_USER`, `MISSION_ARCHIVED` | 88.4.5 |
| `PAUSED` | `FAILED` | `ORPHANED_*` | 88.4.5 |

**Status sets:**
- **Terminal:** `SUCCEEDED`, `FAILED`, `CANCELLED`, `BUDGET_STOPPED`, `SKIPPED`, `MISSED`.
- **Active:** `PENDING`, `RUNNING`, `AWAITING_GATE`, `PAUSED`. These are the statuses covered by the partial unique index.

**Run end rules:**
- **One exit.** Every path from `RUNNING`, `AWAITING_GATE` or `PAUSED` to a terminal status goes through `MissionRunWorkflow._end_run(status, reason, detail)`. From 88.3.8 it runs `compact_mission_context`, `write_run_digest` and then `finalise_mission_run`; before 88.3.8 it runs only `finalise_mission_run`.
- **Supervisor escalation.** `SUPERVISOR_ESCALATED` ends the run as `FAILED`. It does not pause the mission.
- **Backlog return.** `finalise` sets `mission_run_id = NULL` on the run's PROPOSED and APPROVED tasks (3.5.1).

#### 3.2.2 Mission

| From | To | Service method | Side effects (in order) |
|---|---|---|---|
| `ACTIVE` | `PAUSED` | `MissionLifecycleService.pause_mission(reason=USER or a system reason)` | (1) `_apply_pause` sets `status` and `paused_*` and flushes; (2) commit; (3) `sync_mission(mission_id)` (Temporal paused, note = the pause reason value); (4) if reason=USER and the active run is `RUNNING` or `AWAITING_GATE`, send signal `request_pause`; (5) emit `mission.lifecycle_changed`. `pause_mission` sends no notification: the workflow sends `BUDGET_PAUSED` and `GATE_TIMEOUT_PAUSED`, and `claim_occurrence` returns `BUDGET_PAUSED` for the tick workflow to send |
| `PAUSED` | `ACTIVE` | `resume_mission(mission_id, user_id: str or None)` | **Preconditions:** if `paused_reason = GATE_TIMEOUT`, `GateRequestRepository.has_undecided(mission_id)` (no gate of the mission is `PENDING`, `ESCALATED` or `TIMED_OUT`) is false, otherwise `ConflictError`; `BudgetService.mission_cap_breach` is `None`, otherwise `ConflictError` naming the cap. **Effects:** (1) for each `ACTIVE` schedule of the mission, lock the row (`MissionScheduleRepository.lock`), list the matching times between `missions.paused_at` and now with `TemporalScheduleGateway.list_matching_times(schedule.temporal_schedule_id, paused_at, now)`, insert a `MISSED/NOT_FIRED` row for each slot that has none (sequence allocated as in `claim_occurrence`), then set `last_claimed_scheduled_for = now`; (2) clear `status` and `paused_*`; (3) commit; (4) `sync_mission`; (5) signal `resume` to the active run whatever its status; (6) emit `mission.lifecycle_changed`. Each schedule row is locked before its listing, and the gateway call runs with the lock held: the same deliberate exception as `claim_occurrence` (3.3.2, 3.5 layering) |
| `ACTIVE` or `PAUSED` | `ARCHIVED` | `archive_mission` (owner or admin) | (1) every non-ARCHIVED schedule becomes `ARCHIVED`; (2) commit; (3) delete the Temporal schedules; (4) cancel the active run with `cancel_reason=MISSION_ARCHIVED`; (5) undecided gate requests become `CANCELLED` through `GateRequestRepository.cancel_undecided(mission_id)`; (6) emit `mission.lifecycle_changed` |
| `ARCHIVED` | `PAUSED` (USER) | `unarchive_mission` (owner or admin) | Schedules stay `ARCHIVED`. The owner creates new ones and then resumes the mission |

After a gate that timed out is decided, `MissionRunWorkflow` runs `resume_mission_for_run`, which resumes a `PAUSED/GATE_TIMEOUT` mission that has no undecided gate. `GateDecisionService.decide` never resumes the mission.

- **Resume signal handling.** The workflow's `resume` handler clears `pause_requested` unconditionally, and clears `paused` when no gate is pending. A pause requested and resumed before the next layer boundary therefore never takes effect.
- **Backfill across pauses.** Every slot that falls inside a mission pause is recorded as `MISSED/NOT_FIRED` by `resume_mission` (88.4.5), because a paused Temporal schedule delivers no ticks and the claim backfill bound would leave in-window slots unrecorded (test `test_mission_pause_slots_backfilled`). No pause-interval table exists. Slots inside a schedule pause are not recorded, because `resume_schedule` resets the watermark (3.5.1).
- **Claim-initiated pause.** `claim_occurrence` cannot call `pause_mission`, which commits and calls Temporal. It calls `MissionLifecycleService._apply_pause(mission, reason, user_id=None)`, which sets the columns and flushes without commit or Temporal; the `claim_occurrence` activity calls `sync_mission(mission_id)` after its commit and returns a `BUDGET_PAUSED` notification for the tick workflow to send.
- **Emergency stop.** `MissionLifecycleService.pause_all_active(user_id) -> int` pauses every ACTIVE mission with reason USER and replaces the emergency stop at `api/v1/endpoints/admin.py:835` (88.4.5).
- **Delete.** `delete_mission` (owned by 88.0.9, modified by 88.1.11) runs before any DB delete: it deletes every Temporal schedule of the mission, then terminates the active run's workflow and any PENDING or RUNNING execution record's workflow. Termination, not cancellation, is used because the rows are deleted next and no finalise activity may run. `ExternalServiceError` aborts the delete (fail closed). `MissionService.archive_mission` and `unarchive_mission` (`services/mission.py:465-477`) are deleted in 88.4.5.

**Effective Temporal schedule state.** The Temporal schedule is **present and unpaused** only when `schedule.status = ACTIVE` and `mission.status = ACTIVE`. It is **present and paused** when `schedule.status ∈ {ACTIVE, PAUSED}` and the earlier condition does not hold. Otherwise it is **absent**.

#### 3.2.3 MissionSchedule

| From | To | Trigger |
|---|---|---|
| (create) | `ACTIVE` | `create_schedule` |
| `ACTIVE` | `PAUSED` | `pause_schedule` |
| `PAUSED` | `ACTIVE` | `resume_schedule` |
| `ACTIVE` or `PAUSED` | `COMPLETED` | `MAX_RUNS_REACHED` (inside `claim_occurrence`, when `executed_run_count == max_runs`); `END_DATE_REACHED` (`sync_all` in the reconciler, when `ends_at < now`, 88.4.7) |
| `COMPLETED` | `ACTIVE` | `update_schedule` that raises `max_runs` above `executed_run_count` or moves `ends_at` into the future |
| any except `ARCHIVED` | `ARCHIVED` | `archive_schedule` (`DELETE` endpoint); `archive_mission` |

- **Order of operations.** Every transition writes Postgres, commits, then calls `sync_to_temporal`.
- **Sync failure.** On failure the service sets `temporal_sync_state=FAILED` and `temporal_sync_error`, logs, and returns the row with that state. The reconciler retries.

#### 3.2.4 GateRequest (durable, 88.4.8)

| From | To | Trigger |
|---|---|---|
| (insert) | `PENDING` | `open_gate_request` |
| `PENDING` | `ESCALATED` | timer `gate_escalate_after_seconds`, through `mark_status` |
| `PENDING` or `ESCALATED` | `TIMED_OUT` | timer `gate_pause_after_seconds`, through `mark_status`. The run becomes `PAUSED/GATE_TIMEOUT` and the mission becomes `PAUSED/GATE_TIMEOUT` |
| `PENDING`, `ESCALATED` or `TIMED_OUT` | `DECIDED` | `GateDecisionService.decide` (web, CLI, API, Telegram) or `close_gate_request` (channel WORKFLOW) |
| `PENDING`, `ESCALATED` or `TIMED_OUT` | `CANCELLED` | run cancelled or mission archived |

- **Guarded writes.** `mark_status` is `UPDATE gate_requests SET status = :target WHERE id = :id AND status IN ('PENDING','ESCALATED')`. It never overwrites `DECIDED` or `CANCELLED`.
- **Decidable.** A gate can be decided only when its status is `PENDING`, `ESCALATED` or `TIMED_OUT`, `mission_run_id IS NOT NULL`, and the run status is `AWAITING_GATE` or `PAUSED`.

### 3.3 Temporal contracts

#### 3.3.1 Identifiers and queue

| Thing | Format | Policy |
|---|---|---|
| Task queue | `temporal.task_queue` (`agent-missions`), unchanged | single queue |
| Namespace | `temporal.namespace`, unchanged | The orphan-schedule sweep (3.3.2) is bounded by an explicit id list, not by the namespace |
| Run workflow id | `mission_run_workflow_id(mission_run_id)` = `mission-run-{mission_run_id}` (full UUID), from `temporal/workflow_ids.py` | `id_reuse_policy=REJECT_DUPLICATE`. The only scheme from 88.1.7. `mission_plan_dispatch.py:117` and `scheduled_workflow.py:73` are deleted |
| Mission schedule id | `mission-schedule-{mission_schedule_id}` | stored in `mission_schedules.temporal_schedule_id` |
| Schedule probe id | `mission-schedule-probe-{uuid4().hex}` | created and deleted by `TemporalScheduleGateway.validate_spec` |
| Tick workflow id (schedule action) | `mission-tick-{mission_schedule_id}` | Temporal appends the scheduled timestamp |
| System schedules | `system-{key}`, with `{key}` from `temporal.system_schedules` | workflow id `system-{key}` |
| Patch ids | `p88-{kebab-slug}`: `p88-run-memory`, `p88-lifecycle-signals`, `p88-budget-caps`, `p88-durable-gate` | `workflow.patched()` only, registered per 3.0.2 |

#### 3.3.2 Workflows

| Workflow | File | Status |
|---|---|---|
| `MissionRunWorkflow` | `temporal/mission_run_workflow.py` (rewritten in 88.1.8) | input `MissionRunWorkflowInput` |
| `MissionScheduleTickWorkflow` | `temporal/mission_schedule_tick_workflow.py` (new, 88.1.8) | input `MissionScheduleTickInput` |
| `ReconcilerWorkflow` | `temporal/reconciler_workflow.py` (new, 88.0.10) | input `ReconcilerInput`, returns `ReconcileStats` |
| `RetentionWorkflow` | `temporal/retention_workflow.py` (new, 88.5.4; replaces `DailyCleanupWorkflow`) | input `RetentionInput` (`temporal/retention_models.py`) |
| **Deleted (P3)** | n/a | 88.1.8: `ScheduledMissionCheckWorkflow` and `find_ready_plans`, `RunObjectiveWorkflow` (its planning moves to `plan_mission_run`); 88.1.3: `EvaluateWorkflowSchedulesWorkflow`; 88.2.6: `AgentMissionWorkflow` (`temporal/workflow.py`) with `POST /executions/{id}/execute` and `/approve`; 88.5.4: `DailyCleanupWorkflow` |

**Workflow rules:**
- **No config reads in workflow code.** No workflow module may import or call `get_app_config`, `get_default_budget_usd` or `get_settings`. `ChatTurnInput`, `PlanRefineInput`, `DesignWorkflowInput` and `RunWorkflowInput` (`chat_workflow.py:55`, `plan_refine_workflow.py:42`, `tool_fork_workflow.py:77,124`) each gain a required `timeouts: WorkflowTimeoutsSnapshot` field in 88.2.2, populated by the starter with `build_workflow_timeouts_snapshot()`. This replaces the config reads at `chat_workflow.py:57`, `plan_refine_workflow.py:44` and `tool_fork_workflow.py:78,125`. The hardcoded fallback `PlanRefineInput.mission_budget_usd: float = 10.0` is removed in 88.0.7: the field is required and the starter passes the value from the plan.
- **CI test.** `tests/unit/backend/temporal/test_no_config_in_workflows.py` parses the workflow modules with `ast` and fails on any forbidden name. 88.1.8 covers `mission_run_workflow.py` and `mission_schedule_tick_workflow.py`; 88.2.2 widens it to `modules/backend/temporal/*workflow*.py`.
- **System schedules.** The worker registers them at startup with create-or-update, using `handle.update` when the schedule exists. This replaces `main.py:79-115`, which swallows `ScheduleAlreadyRunningError` and never updates. 88.0.10 registers `reconciler` only; 88.1.10 moves the ten registrations at `main.py:118-187` into the worker and removes registration from the API lifespan. Until 88.5.4, `system_schedules.retention` starts `DailyCleanupWorkflow`.
- **Orphan-schedule sweep (88.1.10).** At registration the worker deletes only these Temporal schedule ids, each logged at warning:
  - the legacy ids registered at `main.py:118-187`: `mission-plan-dispatch-schedule`, `maintenance-daily-cleanup`, `maintenance-hourly-health-check`, `maintenance-weekly-report`, `maintenance-metrics-aggregation`, `maintenance-cleanup-environments`, `maintenance-workflow-schedules`, `knowledge-daily-extraction`, `knowledge-officer-daily`, `knowledge-embedding-backfill`;
  - `mission-schedule-*` ids (excluding `mission-schedule-probe-*`) with no matching `mission_schedules.temporal_schedule_id` row.

  It never deletes any other id.

**`MissionScheduleTickWorkflow.run` steps:**
1. Read `TemporalScheduledStartTime` with `workflow.info().typed_search_attributes.get(SearchAttributeKey.for_datetime("TemporalScheduledStartTime"))`. If it is absent, raise non-retryable `ApplicationError("NO_SCHEDULED_TIME")`.
2. Run `claim_occurrence`.
3. Run `send_mission_notification` for each returned notification (from 88.4.5, under patch id `p88-lifecycle-signals`; before that, log the count). A notification failure is caught and logged, never propagated.
4. If the outcome is `run`, or `duplicate` with the existing run still `PENDING`, call `start_child_workflow(MissionRunWorkflow.run, result.run_input, id=mission_run_workflow_id(result.mission_run_id), task_queue=inp.config.task_queue, parent_close_policy=ParentClosePolicy.ABANDON, id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE)`. Treat `WorkflowAlreadyStartedError` as success.

**Temporal Schedule definition (built only by `MissionScheduleService.sync_to_temporal`):**
- **Spec:** `ScheduleSpec(cron_expressions=[cron_expression], time_zone_name=time_zone_name, start_at=starts_at, end_at=ends_at)`.
- **Policy:** `SchedulePolicy(overlap=ScheduleOverlapPolicy.ALLOW_ALL, catchup_window=timedelta(seconds=catch_up_window_seconds), pause_on_failure=False)`.
- **State:** `ScheduleState(paused=effective_paused, note=note)`, where `effective_paused` follows 3.2.2 and `note` is the mission's pause reason value or the schedule's status value. `limited_actions` is not used, because max runs counts executed runs, not ticks.
- **Action:** `ScheduleActionStartWorkflow(MissionScheduleTickWorkflow.run, MissionScheduleTickInput(mission_schedule_id=schedule.id, config=tick_config), id=f"mission-tick-{schedule.id}", task_queue=tick_config.task_queue, execution_timeout=timedelta(seconds=tick_execution_timeout_seconds))`.
- **Why ALLOW_ALL and not SKIP.** Decision 8's SKIP semantics are enforced by the Postgres claim, which records every skip. Temporal's own SKIP discards the fire with no hook.

**`claim_occurrence` algorithm.** This runs in one transaction, with the schedule row locked `FOR UPDATE`. `W = catch_up_window_seconds`.
1. **Duplicate.** If a run row exists for `(schedule_id, scheduled_for)`, return `duplicate` with that row.
2. **Backfill missed slots.** Let `lower = coalesce(last_claimed_scheduled_for, created_at)` and `upper = min(scheduled_for, now - W)`. List matching times strictly between `lower` and `upper` with `TemporalScheduleGateway.list_matching_times(schedule.temporal_schedule_id, lower, upper)`. For each `t` with `lower < t < upper` that has no row, allocate a sequence and insert `MISSED/NOT_FIRED`. Slots inside the catch-up window are left to their own ticks, which Temporal still delivers. Bounding by `now - W` as well as `scheduled_for` records outage slots even when buffered ticks arrive earliest first (test `test_out_of_order_ticks_record_every_slot`, 88.1.6).
3. **Decide this tick's outcome.** The first matching rule wins:
   - `missions.recurrence.enabled` is false, or `schedule.status != ACTIVE`, gives `SKIPPED/SCHEDULE_NOT_ACTIVE`.
   - `mission.status != ACTIVE` gives `SKIPPED/MISSION_NOT_ACTIVE`.
   - `now - scheduled_for > W` gives `MISSED/OUTSIDE_CATCHUP_WINDOW`.
   - Any matching time in `(scheduled_for, now]` gives `MISSED/SUPERSEDED`.
   - An active run exists gives `SKIPPED/OVERLAP`.
   - `executed_run_count >= max_runs` gives `SKIPPED/MAX_RUNS_REACHED`.
   - From 88.4.6: a monthly or lifetime cap is breached gives `SKIPPED/BUDGET_CAP_REACHED`, and calls `MissionLifecycleService._apply_pause(mission, reason, None)` with the matching reason inside the claim transaction; the activity calls `sync_mission(mission_id)` after commit and returns a `BUDGET_PAUSED` notification (3.2.2). Phases 1 to 3 have no budget rule.
   - Otherwise the outcome is `run`.
4. **Insert with gap-free sequence.** For a non-`run` outcome, call `increment_run_sequence` and insert the row in the main transaction. For `run`, open `begin_nested()`, call `increment_run_sequence` inside the savepoint and insert a `PENDING` run with the rendered objective. On `IntegrityError` from `uq_mission_runs_one_active`, roll back the savepoint, call `increment_run_sequence` again and insert `SKIPPED/OVERLAP`. On success increment `executed_run_count`; if it now equals `max_runs`, set the schedule to `COMPLETED/MAX_RUNS_REACHED`, and delete the Temporal schedule after commit.
5. **Watermark.** Set `last_claimed_scheduled_for = greatest(existing, scheduled_for)`.
6. **Return.** Return the notifications `RUN_SKIPPED` and/or `RUN_MISSED`, with counts.

**Acceptance criterion for outages.** After an outage, every slot in the outage is either one RUN or `MISSED` with reason in `{SUPERSEDED, NOT_FIRED, OUTSIDE_CATCHUP_WINDOW}`, and exactly one run executes. The result does not depend on the order in which Temporal delivers buffered ticks.

#### 3.3.3 `MissionRunWorkflow` behaviour, signals, queries and updates

**Skeleton (88.1.8).** These names are fixed for every later phase:

```python
def _cause_type(e: ActivityError) -> str:
    if isinstance(e.cause, ApplicationError):
        return e.cause.type or type(e.cause).__name__
    return type(e.cause).__name__


async def _exec(fn: Callable, arg: object, p: ActivityPolicySnapshot) -> Any:
    return await workflow.execute_activity(fn, arg, **activity_kwargs(p))


@workflow.defn
class MissionRunWorkflow:
    @workflow.init
    def __init__(self, inp: MissionRunWorkflowInput) -> None:
        st = inp.state
        self._input = inp
        self._state: MissionRunWorkflowState | None = st
        self._phase = "planning"
        self._refinement_done = False
        self._approved_seq = st.approved_seq if st else 0
        self._pause_requested = st.pause_requested if st else False   # set by handlers from 88.4.5
        self._paused = st.paused if st else False                      # set by handlers from 88.4.5
        self._decision = st.decision if st else None                   # set by the update handler from 88.4.8

    @workflow.signal
    def tasks_approved(self, s: TasksApprovedSignal) -> None:
        self._approved_seq += 1

    async def _end_run(self, status: str, reason: str | None, detail: str | None) -> str:
        self._phase = "finalising"
        await _exec(finalise_mission_run,
                    FinaliseRunInput(self._input.mission_run_id, status, reason, detail),
                    self._input.config.persistence)
        return status
```

- **Handler-owned fields.** Signal and update handlers touch only `_approved_seq`, `_pause_requested`, `_paused`, `_decision` and `_refinement_done`. `@workflow.init` sets every one of them before any handler can run, so a signal delivered before `begin_mission_run` returns is safe (test `test_signal_before_begin_completes`). They are copied into `MissionRunWorkflowState` before continue-as-new.
- **Start rejection.** `begin_mission_run` transitions the run to `FAILED/INVALID_GATE_MODE` or `FAILED/START_FAILED` (owner not a platform user) itself, commits, and raises `RunStartRejectedError` (non-retryable, 88.1.7). From 88.4.5 a run with `cancel_requested_at` set is transitioned to `CANCELLED` and raises the same error. The workflow catches `ActivityError` with `_cause_type(e) == "RunStartRejectedError"` and returns `"failed"` without calling `_end_run`. A run that is no longer PENDING raises `MissionRunStateError`, which is non-retryable and fails the workflow.
- **Layer boundary.** 88.2.6 adds `async def _layer_boundary(self) -> str | None`, called before each layer; it holds the `max_run_duration_seconds` check and returns the stop reason or `None`. Phase 4 hooks the pause check (88.4.5) and the budget check (88.4.6) into it.
- **Approval wake-up.** Before calling `fetch_run_task_graph`, the loop records `seen = self._approved_seq`. When the graph has nothing approved and something proposed, it waits on `workflow.wait_condition(lambda: self._approved_seq > seen)`. A signal delivered while the graph activity runs is therefore never lost (test `test_signal_during_graph_fetch_not_lost`). The counter is carried across continue-as-new.
- **Supervisor-driven approval.** After `advance_refine`, the workflow calls `await _exec(sup.approve_run_proposed_tasks, inp.mission_run_id, c.persistence)` unconditionally. The activity approves only when `run.gate_mode == AUTONOMOUS` and returns `0` otherwise.
- **Phase 1 loop bound.** Phase 1 has no continue-as-new and no workflow iteration cap. The loop is bounded by the supervisor's existing breaker on `mission_plans.max_supervisor_iterations` (`agents/mission_control/gate_post_run.py:131-139`), which `evaluate_post_run` reads from the DB and which escalates. 88.2.6 deletes the breaker (item 8); 88.2.7 adds continue-as-new.

| Name | Kind | Payload | Effect | Step |
|---|---|---|---|---|
| `tasks_approved` | signal | `TasksApprovedSignal` | `approved_seq += 1`. The loop records `seen = approved_seq` before each graph fetch and waits on `approved_seq > seen`. | 88.1.8 |
| `refinement_complete` | signal | none | unchanged (`mission_run_workflow.py:49-52`) | exists |
| `get_run_state` | query | returns `MissionRunWorkflowStatus` | replaces `get_loop_status` (`mission_run_workflow.py:54-61`); its caller `clients/cli/mc_trace.py:47` is updated in 88.1.8 and moved behind the API in 88.5.8 | 88.1.8 |
| `request_pause` | signal | `PauseRequest` | sets `_pause_requested`. The run pauses after the in-flight activities of the current layer complete | 88.4.5 (`p88-lifecycle-signals`) |
| `resume` | signal | `ResumeRequest` | clears `_pause_requested` unconditionally; clears `_paused` when no gate is pending | 88.4.5 (`p88-lifecycle-signals`) |
| `decide_gate` | **Update**, with validator | `GateDecisionUpdate` | The validator rejects unless `gate_request_id == state.pending_gate.gate_request_id` and the action is in `allowed_actions(gate_point)`. The handler stores the decision in `_decision` and returns `GateDecisionAck` | 88.4.8 (`p88-durable-gate`) |
| cancel | Temporal cancellation (`TemporalWorkflowGateway.cancel`) | none | The workflow catches `asyncio.CancelledError`; from 88.4.8 it runs `close_gate_request(cancelled)` for a pending gate; then `_end_run("cancelled", None, None)`, and `finalise` takes the reason from `mission_runs.cancel_reason`. From 88.3.8 `_end_run` writes a deterministic digest on this path | 88.1.8 |

**Gate decision ordering (88.4.8).** `GateDecisionService.decide` works in this order:
1. Lock the gate row with `WHERE id = :gid AND mission_id = :mid`, and validate that it can be decided (3.2.4).
2. Call `TemporalWorkflowGateway.execute_update` on `mission_run_workflow_id(run_id)` with update name `"decide_gate"` and a `GateDecisionUpdate` built from the request. This is one of the three deliberate Temporal calls made inside an open transaction (3.5).
3. On ack, write `DECIDED` and commit.
4. If the update is rejected or the workflow is closed, raise `ConflictError` and leave the DB unchanged.

The workflow then always runs `close_gate_request`, which is idempotent: `UPDATE … WHERE status IN ('PENDING','ESCALATED','TIMED_OUT')`. The DB therefore converges even if the commit in step 3 failed.

**Durable gate (88.4.8, `p88-durable-gate`).** This reimplements the signal, `wait_condition` and timer pattern of `a28ca771:modules/backend/temporal/workflow.py:187-245`, which 88.2.6 deletes. In outline: (1) open the gate with a workflow-generated `gate_request_id = str(workflow.uuid4())`, then send `gate_waiting` through `send_mission_notification`, logging failures; (2) wait for a decision for `escalate_after`; if none, `update_gate_request("escalated")` and, if still none, send `gate_escalated`; (3) wait `pause_after - escalate_after`; if none, `update_gate_request("timed_out")`; if still none, `set_mission_run_status("paused", "gate_timeout")`, `pause_mission_for_run("gate_timeout")`, send `gate_timeout_paused`, then wait with no timeout; (4) `close_gate_request("decided")`, then `resume_mission_for_run` if the gate timed out. `mark_status` updates only rows in `PENDING` or `ESCALATED`.

The insert uses `ON CONFLICT (id) DO NOTHING`, so an activity retry never creates a second row (test `test_open_gate_retry_single_row`). Every notification call goes through `_notify` (88.4.5), which catches `ActivityError`, logs it and returns (test `test_notify_failure_does_not_fail_run`). The reference implementation (88.4.8 item 9):

```python
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

These are `MissionRunWorkflow` methods. Every timeout is followed by a check of `self._decision` before escalating or pausing, so a decision that races the timer never pauses the mission (test `test_decision_racing_timeout_resumes_mission`). `abort` from any gate ends the run with `await self._end_run("cancelled", "gate_rejected", None)`.

**Gate behaviour by mode:**
- **Points.** All gate points are evaluated in the workflow: `pre_dispatch`, `pre_layer`, `post_task`, `verification_failed`, `post_layer`, `post_run`, each honouring `RunConfigSnapshot.gate_points_enabled`. Inside `execute_plan_task`, the dispatch loop runs with `gate=None`.
- **Seam.** 88.2.6 adds `async def _gate(self, point: str, task_id: str | None) -> str` returning `"continue"`. 88.4.8 replaces its body under `p88-durable-gate`.
- **Modes (88.4.8).** `AUTONOMOUS` decides through `evaluate_gate` (channel WORKFLOW). A `continue` writes no row; any other action is recorded as `open_gate_request(human_required=False)` plus `close_gate_request` with `decided_by_user_id=None` and channel `workflow`; `close` writes the mission owner's user id. `AI_ASSISTED` calls `evaluate_gate` for a recommendation (`ai_recommendation_json`) and then waits for a human. `MANUAL` waits for a human.
- **Fail closed.** `INTERACTIVE`, NULL or an unknown mode fails the run at `begin_mission_run` with `FAILED/INVALID_GATE_MODE`. Outside the run path, the in-process `ConfigurableGate` raises `ValidationError` for an invalid mode, and `GateDecisionService.evaluate` raises `MissionRunStateError`. Schedule creation rejects missions whose plan `gate_mode = INTERACTIVE`. 88.4.8 deletes the INTERACTIVE branch and the `modules.clients.cli.gate` import (`CliGateReviewer`, `agents/mission_control/gate.py:169-171`) from the backend gate.

**Continue-as-new (88.2.7 only).** At the top of the loop, with no pending gate and `state.iteration > state.last_can_iteration`, the workflow continues-as-new when `state.iteration - state.last_can_iteration >= config.continue_as_new_after_iterations` or `workflow.info().is_continue_as_new_suggested()`. It first awaits `workflow.all_handlers_finished`, sets `last_can_iteration = iteration`, copies the handler-owned fields into `state`, and calls `workflow.continue_as_new(replace(input, state=state))`. Phase 1 has no continue-as-new; 88.2.7 adds it. The reference implementation, `_maybe_continue_as_new()`:

```python
async def _maybe_continue_as_new(self) -> None:
    s = self._state
    n = self._input.config.continue_as_new_after_iterations
    due = s.iteration - s.last_can_iteration >= n
    suggested = s.iteration > s.last_can_iteration and workflow.info().is_continue_as_new_suggested()
    if not (due or suggested):
        return
    await workflow.wait_condition(workflow.all_handlers_finished)
    s.last_can_iteration = s.iteration
    s.approved_seq = self._approved_seq
    s.pause_requested = self._pause_requested
    s.paused = self._paused
    s.decision = self._decision
    workflow.continue_as_new(dataclasses.replace(self._input, state=s))
```

`last_can_iteration` is set before the call, so a run that continues as new without progress never continues as new again (test `test_can_does_not_repeat_without_progress`). The 25-iteration cap (`mission_run_workflow.py:80-82`) is deleted in 88.1.8.

#### 3.3.4 Dataclasses (`temporal/mission_run_models.py`; `temporal/models.py` is deleted in 88.2.6)

Fields without a step comment exist from the step that creates the class (3.0.1). A comment `# 88.x.y` marks a field added later. String fields that carry an enum hold its lowercase value (3.0.2).

```python
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RetrySnapshot:                          # 88.0.2
    initial_interval_seconds: int
    backoff_coefficient: float
    maximum_interval_seconds: int
    maximum_attempts: int


@dataclass(frozen=True)
class ActivityPolicySnapshot:                 # 88.0.2
    start_to_close_seconds: int
    heartbeat_timeout_seconds: int | None
    retry: RetrySnapshot


@dataclass(frozen=True)
class ReconcilerInput:                        # 88.0.10; schedule action input built by system_schedules.py
    config_hash: str
    orphan_grace_seconds: int
    activity: ActivityPolicySnapshot


@dataclass(frozen=True)
class ReconcileInput:                         # 88.0.10; reconcile_mission_runs activity input
    orphan_grace_seconds: int


@dataclass
class ScheduleSyncStats:                      # 88.0.10
    synced: int
    failed: int
    deleted_orphans: int
    completed: int


@dataclass
class ReconcileStats:                         # 88.0.10
    examined_tasks: int
    examined_execution_records: int
    examined_workflow_runs: int
    failed_tasks: int
    failed_execution_records: int
    failed_workflow_runs: int
    left_running: int
    left_in_process: int                      # 88.0.10
    schedule_sync: ScheduleSyncStats | None   # 88.0.10; None until 88.1.10 runs sync_mission_schedules, and whenever it did not run
    examined_mission_runs: int                # 88.1.10a
    failed_mission_runs: int                  # 88.1.10a
    gates_cancelled: int                      # 88.5.6
    gates_overdue: int                        # 88.5.6


@dataclass(frozen=True)
class WorkflowTimeoutsSnapshot:               # 88.2.2
    activity_timeout_seconds: int             # temporal.min_activity_timeout_seconds
    persistence_timeout_seconds: int
    persistence_retry_max_attempts: int


@dataclass(frozen=True)
class RunConfigSnapshot:                      # 88.1.5
    config_hash: str                          # config_hash(self) over every other field
    task_queue: str
    persistence: ActivityPolicySnapshot
    plan_run: ActivityPolicySnapshot
    execute_task: ActivityPolicySnapshot
    evaluate_gate: ActivityPolicySnapshot
    evaluate_post_run: ActivityPolicySnapshot
    director_turn: ActivityPolicySnapshot
    write_digest: ActivityPolicySnapshot
    notify: ActivityPolicySnapshot
    gate_escalate_after_seconds: int          # temporal.approval_timeout_seconds until 88.4.8, then gate.durable.escalate_after_seconds
    gate_pause_after_seconds: int             # temporal.escalation_timeout_seconds until 88.4.8, then gate.durable.pause_after_seconds
    gate_points_enabled: dict[str, bool]      # keys: pre_dispatch, pre_layer, post_task, verification_failed, post_layer, post_run
    refine_wait_seconds: int
    continue_as_new_after_iterations: int
    max_parallel_tasks: int
    max_run_duration_seconds: int             # 88.2.2
    task_heartbeat_interval_seconds: int      # 88.2.2
    max_failure_digests: int                  # 88.2.6; failures.supervisor.max_failure_digests (3.4.9)


@dataclass(frozen=True)
class TickConfigSnapshot:                     # 88.1.5
    config_hash: str
    task_queue: str
    claim: ActivityPolicySnapshot
    notify: ActivityPolicySnapshot


@dataclass
class PendingGate:                            # 88.1.5; used from 88.4.8
    gate_request_id: str
    gate_point: str                           # a key of RunConfigSnapshot.gate_points_enabled
    task_id: str | None
    opened_at: datetime
    escalated: bool
    timed_out: bool


@dataclass
class GateDecisionUpdate:                     # 88.1.5; used from 88.4.8
    gate_request_id: str
    action: str                               # see 3.3.6
    reason: str | None
    decided_by_user_id: str | None            # None only when channel == "workflow"; close writes the mission owner
    channel: str                              # DecisionChannel value


@dataclass
class MissionRunWorkflowState:                # 88.1.5
    iteration: int
    session_id: str
    execution_record_id: str
    context_version_start: int
    pending_gate: PendingGate | None
    last_supervisor_action: str | None
    approved_seq: int
    pause_requested: bool
    paused: bool
    decision: GateDecisionUpdate | None
    run_started_at: datetime                  # 88.2.6
    excluded_wait_seconds: int                # 88.2.6; gate wait time excluded from max_run_duration_seconds
    last_can_iteration: int                   # 88.2.7


@dataclass
class MissionRunWorkflowInput:                # 88.1.5
    mission_run_id: str
    mission_id: str
    plan_id: str
    config: RunConfigSnapshot
    state: MissionRunWorkflowState | None = None   # set only by continue_as_new


@dataclass
class MissionScheduleTickInput:               # 88.1.5
    mission_schedule_id: str
    config: TickConfigSnapshot


@dataclass
class GateDecisionAck:                        # 88.1.5; used from 88.4.8
    gate_request_id: str
    accepted: bool


@dataclass
class PauseRequest:                           # 88.1.5; used from 88.4.5
    requested_by_user_id: str | None
    reason: str                               # MissionPauseReason value


@dataclass
class ResumeRequest:                          # 88.1.5; used from 88.4.5
    requested_by_user_id: str | None          # None when the workflow resumes after a gate timeout


@dataclass
class PauseForRunInput:                       # 88.4.5
    mission_run_id: str
    reason: str                               # MissionPauseReason value


@dataclass
class TasksApprovedSignal:                    # 88.1.5
    task_ids: list[str]


@dataclass
class NotificationRequest:                    # 88.1.5; sent from 88.4.4 (run-end and tick kinds from 88.4.5)
    kind: str                                 # NotificationKind value
    mission_id: str
    mission_run_id: str | None
    gate_request_id: str | None
    subject_id: str
    payload: dict


@dataclass
class SupervisorFollowupInput:                # 88.1.8; fire_supervisor_followups input
    mission_id: str
    mission_run_id: str
    execution_record_id: str
    action: str
    reason: str
    reviewer: str
    wave_status: str                          # from 88.2.6: "failed" if any task of the layer failed, else "completed"
    wave_cost_usd: float                      # from 88.2.6: sum of the layer's ExecuteTaskResult.cost_usd
    failure_reason: str | None                # from 88.2.6: the first failed task's failure_reason, else None


@dataclass(frozen=True)
class TaskFailureDigest:                      # 88.2.6; built only by digest_failures (below)
    task_id: str                              # first task in the wave with this fingerprint
    origin: str                               # FailureOrigin value
    failure_class: str                        # FailureClass value
    fingerprint: str
    summary: str                              # ExecuteTaskResult.failure_reason
    occurrences: int                          # tasks sharing the fingerprint


# 88.2.6, same module, pure (no I/O; workflow-sandbox safe). The only grouping rule for failure digests:
# def digest_failures(items: Iterable[FailureItem], cap: int) -> tuple[list[TaskFailureDigest], int]
# FailureItem is any object with task_id, failure_origin, failure_class, failure_fingerprint, failure_reason
# (ExecuteTaskResult and the TaskRepository.failed_tasks_for_run rows both qualify). It groups by fingerprint
# in input order, keeps the first item's task_id and summary, counts occurrences, keeps the first `cap` groups
# and returns the number of groups dropped.


@dataclass
class MissionRunWorkflowStatus:               # 88.1.5
    mission_run_id: str
    iteration: int
    phase: str                                # planning | executing | awaiting_gate | paused | supervising | finalising
    pending_gate_id: str | None
    pause_requested: bool
    last_supervisor_action: str | None
```

- **Supervisor inputs (88.2.6).** `_execute_layers` aggregates the layer's final `ExecuteTaskResult`s into `wave_status`, `wave_cost_usd` and `failure_reason`, and `_supervise` builds `SupervisorFollowupInput` from those three values only (test `test_supervisor_input_from_task_results`). In Phase 1 they come from the interim wave result. `_execute_layers` also builds the wave's `TaskFailureDigest` list for `REFINE_PROMPT` (3.8.6). The post-run reviewer reads failures from the database, not from the workflow (`evaluate_post_run`, 3.3.5).
- **Construction in Phase 1.** Until the step marked on a field, the creator fills it with its neutral value: `approved_seq=0`, `pause_requested=False`, `paused=False`, `decision=None`, `pending_gate=None`. Fields marked with a later step are added to the class in that step, never earlier.
- **Activity I/O dataclasses** named in 3.3.5 live in the same module, created by the step that creates their activity.
- **`RetentionInput`, `RetentionPolicyInput` and `RetentionResult`** live in `temporal/retention_models.py` (88.5.4): `RetentionInput{config_hash: str, policies: list[str], batch_size: int, activity: ActivityPolicySnapshot}`, `RetentionPolicyInput{policy: str, batch_size: int}`, `RetentionResult{policy: str, rows_affected: int, rows_aggregated: int, complete: bool, duration_seconds: float}`. `RetentionInput` is built only by `services/retention.build_retention_input`.

**Helper modules:**
- **`temporal/activity_options.py`** (88.0.2) is pure and imports only `temporalio` and `mission_run_models`:

`NON_RETRYABLE` holds class names as strings, so 88.0.2 lists `RunStartRejectedError` before 88.1.7 creates the class.

```python
NON_RETRYABLE = ["BudgetExceededError", "MissionRunStateError", "RunStartRejectedError"]


def retry_policy(s: RetrySnapshot) -> RetryPolicy:
    return RetryPolicy(initial_interval=timedelta(seconds=s.initial_interval_seconds),
                       backoff_coefficient=s.backoff_coefficient,
                       maximum_interval=timedelta(seconds=s.maximum_interval_seconds),
                       maximum_attempts=s.maximum_attempts,
                       non_retryable_error_types=NON_RETRYABLE)


def activity_kwargs(p: ActivityPolicySnapshot) -> dict:
    kw = {"start_to_close_timeout": timedelta(seconds=p.start_to_close_seconds),
          "retry_policy": retry_policy(p.retry)}
    if p.heartbeat_timeout_seconds is not None:
        kw["heartbeat_timeout"] = timedelta(seconds=p.heartbeat_timeout_seconds)
    return kw
```

- **`temporal/config_snapshots.py`** (88.0.2) is not a workflow module, so it may read config. `policy_snapshot(schema: ActivityPolicySchema) -> ActivityPolicySnapshot`; `config_hash(obj) -> str`, the SHA-256 hex of `json.dumps({k: v for k, v in dataclasses.asdict(obj).items() if k != "config_hash"}, sort_keys=True, separators=(",", ":"))`; from 88.1.5 `build_run_config_snapshot() -> RunConfigSnapshot` and `build_tick_config_snapshot() -> TickConfigSnapshot`; and from 88.2.2 `build_workflow_timeouts_snapshot() -> WorkflowTimeoutsSnapshot`.

#### 3.3.5 Activities (all `@activity.defn`; the name is the function name)

| Activity | Module | Input → Output | Policy key | Step |
|---|---|---|---|---|
| `claim_occurrence` | `temporal/mission_schedule_activities.py` | `ClaimOccurrenceInput{mission_schedule_id, scheduled_for: datetime}` → `ClaimOccurrenceResult{outcome: "run" or "skipped" or "missed" or "duplicate", mission_run_id: str or None, run_input: MissionRunWorkflowInput or None, notifications: list[NotificationRequest]}` | `claim` (tick) | 88.1.8 |
| `begin_mission_run` | `temporal/mission_run_activities.py` | `BeginRunInput{mission_run_id}` → `BeginRunResult{session_id, execution_record_id, context_version_start, gate_mode, previous_run_id or None}` | `persistence` | 88.1.8 |
| `plan_mission_run` | same | `PlanRunInput{mission_run_id, session_id}` → `PlanRunResult{task_ids: list[str], status: "planned" or "empty" or "failed", detail}` | `plan_run` | 88.1.8 |
| `fetch_run_task_graph` | same | `mission_run_id: str` → `RunTaskGraph{layers: list[list[str]], proposed: int, approved: int, running: int}` | `persistence` | 88.1.8 |
| `execute_mission` (interim wave executor) | `temporal/activities.py` | `ExecuteWaveInput{mission_run_id, session_id, execution_record_id}` → existing result | `execute_task` | 88.1.8; deleted 88.2.6 |
| `execute_plan_task` | `temporal/task_activities.py` | `ExecuteTaskInput{mission_run_id, task_id, session_id, execution_record_id, budget_headroom_usd: float or None, heartbeat_interval_seconds}` → `ExecuteTaskResult{task_id, status: "completed" or "failed" or "skipped", verification_failed: bool, cost_usd, idempotent_replay: bool, failure_reason: None, "budget_exceeded", "cancelled" or the TaskFailure.summary, failure_origin: str or None, failure_class: str or None, failure_fingerprint: str or None}` (the three failure fields are non-None exactly when `status == "failed"`; 3.8) | `execute_task` (heartbeat) | 88.2.4; `budget_headroom_usd` is `None` until 88.4.6 |
| `resolve_failed_task` | `temporal/task_activities.py` | `ResolveTaskInput{mission_run_id, task_id, action: "retry" or "skip"}` → `None` | `persistence` | 88.2.6 |
| `check_run_budget` | `temporal/mission_run_activities.py` | `mission_run_id: str` → `BudgetCheckResult{run_spent_usd, month_spent_usd, lifetime_spent_usd, headroom_usd, breach: MissionPauseReason value or None}` | `persistence` | 88.4.6 |
| `evaluate_gate` | `temporal/gate_activities.py` | `EvaluateGateInput{mission_run_id, gate_point, task_id or None, recommended_action or None}` → `EvaluateGateResult{action, reason, human_required: bool, recommendation_json: dict or None}` (calls `GateDecisionService.evaluate`). The mode is read from `mission_runs.gate_mode` | `evaluate_gate` | 88.4.8 |
| `open_gate_request` | same | `OpenGateInput{gate_request_id, mission_run_id, gate_point, task_id or None, context_json, recommendation_json or None, escalate_at or None, pause_at or None, human_required: bool}` → `None`. Insert is `ON CONFLICT (id) DO NOTHING`; it sends no notification and issues no tokens | `persistence` | 88.4.8 |
| `update_gate_request` | same | `UpdateGateInput{gate_request_id, status: "escalated" or "timed_out"}` → `None` (calls the guarded `mark_status`) | `persistence` | 88.4.8 |
| `close_gate_request` | same | `CloseGateInput{gate_request_id, status: "decided" or "cancelled", decision: GateDecisionUpdate or None}` → `None` (idempotent) | `persistence` | 88.4.8 |
| `evaluate_post_run` | `temporal/supervisor_activities.py` (changed) | `PostRunEvalInput{mission_id, mission_run_id, execution_record_id, supervisor_iteration_count, session_id}` → `PostRunEvalResult` (unchanged). Gate mode comes from the run, fixing `mission_run_workflow.py:121`. From 88.2.6 the reviewer's `plan_task_summary` carries `failures` and `failures_truncated` (3.8.6), read from `tasks` by `mission_run_id` | `evaluate_post_run` | 88.1.8; failures 88.2.6 |
| `fire_supervisor_followups` | same (changed) | `SupervisorFollowupInput` (3.3.4) → `None`. Emits only `SupervisorDecisionEmittedEvent` and fires followups | `persistence` | 88.1.8; wave fields from per-task results in 88.2.6 |
| `approve_run_proposed_tasks` | same (renamed from `approve_proposed_tasks`) | `mission_run_id: str` → `int`. Approves only when `run.gate_mode == AUTONOMOUS`, else returns `0` | `persistence` | 88.1.8 |
| `start_director_turn` | same (changed) | `DirectorTurnInput{mission_id, mission_run_id, session_id, prompt, signal_workflow_id or None}` → `None` | `director_turn` | 88.1.8 |
| `set_mission_run_status` | `temporal/mission_run_activities.py` | `RunStatusUpdate{mission_run_id, status, reason or None, detail or None}` → `None` | `persistence` | 88.1.8 |
| `pause_mission_for_run` | same | `PauseForRunInput{mission_run_id, reason}` (`reason` is a `MissionPauseReason` value) → `None` (calls `MissionLifecycleService.pause_mission` with `user_id=None`) | `persistence` | 88.4.5 |
| `resume_mission_for_run` | `temporal/mission_run_activities.py` | `mission_run_id: str` → `bool`. When the mission is `PAUSED/GATE_TIMEOUT` with no undecided gate, calls `MissionLifecycleService.resume_mission(mission_id, user_id=None)` and returns `True`; otherwise returns `False` | `persistence` | 88.4.8 |
| `compact_mission_context` | `temporal/run_memory_activities.py` | `CompactContextInput{mission_id, mission_run_id}` → `CompactContextResult{compacted: bool, from_bytes, to_bytes}`. Called in `_end_run` before `write_run_digest`; a failure is logged and does not block the digest | `persistence` | 88.3.8 |
| `write_run_digest` | `temporal/run_memory_activities.py` | `WriteDigestInput{mission_run_id, status, reason or None, force_deterministic: bool}` → `DigestResult{digest_id, generator}`. The activity chooses the narrator; 88.4.6 adds the budget-aware choice here (`narrator=None` when the run is `BUDGET_STOPPED`) | `write_digest` | 88.3.7; 88.4.6 |
| `finalise_mission_run` | `temporal/mission_run_activities.py` | `FinaliseRunInput{mission_run_id, status, reason or None, detail or None}` → `FinaliseRunResult{cost_usd, notification: NotificationRequest}` | `persistence` | 88.1.8 |
| `send_mission_notification` | `temporal/notification_activities.py` | `NotificationRequest` → `list[str]` (delivery ids) | `notify` | 88.4.4 |
| `reconcile_mission_runs` | `temporal/reconciler_activities.py` | `ReconcileInput` → `ReconcileStats` | `reconciler.activity` | 88.0.10 |
| `sync_mission_schedules` | `temporal/mission_schedule_activities.py` in 88.1.8; moved to `temporal/reconciler_activities.py` in 88.1.10 | `mission_id: str or None` → `ScheduleSyncStats` | `reconciler.activity` | 88.1.8; moved and registered in the reconciler by 88.1.10 |
| `run_retention_policy` | `temporal/retention_activities.py` | `RetentionPolicyInput{policy: str, batch_size: int}` → `RetentionResult{policy, rows_affected, rows_aggregated, complete: bool, duration_seconds: float}` | `retention.activity` (heartbeat) | 88.5.4 |

**Deleted (P3):**
- 88.1.8: `fetch_plan_task_counts` and `PlanTaskCounts`; `find_ready_plans`; `execute_run_objective`; the `send_notification` stub (`temporal/activities.py:323-339`) and both workflow calls to it.
- `check_plan_active`: 88.4.2 rewrites `check_plan_active` to read `missions.status`; 88.4.5 stops calling it under `p88-lifecycle-signals`, and the activity stays registered for executions on the old branch. It is deleted in 88.4.5 only when no caller remains. `MissionPlanStatus` goes with `plan88_005` (88.4.2).
- 88.1.3: `run_evaluate_workflow_schedules`.
- 88.2.6: `execute_mission` (`temporal/activities.py:49`) and `persist_mission_outcome` (`:214-215`), with `MissionWorkflowInput`, its interim `gate_mode` field, and `ExecuteWaveInput`.
- 88.5.4: `run_daily_cleanup`.

**Activity rules:**
- **Retry policy construction.** Every `RetryPolicy` for a Plan 88 workflow is built by `activity_options.retry_policy` from an `ActivityPolicySnapshot`.
- **Heartbeats.** `execute_plan_task` heartbeats every `heartbeat_interval_seconds`, with details `{"phase": str}`. It runs with `cancellation_type=ActivityCancellationType.WAIT_CANCELLATION_COMPLETED`.
- **Timeouts.** No activity timeout is derived from budget.
- **Post-run decision cache.** The post-run gate decision cache (`agents/mission_control/gate_post_run.py:104-116`, `services/execution_persistence.py:421-437`) is keyed by `(execution_record_id, supervisor_iteration_count)` from 88.1.8. Keying by `execution_record_id` alone would replay iteration 1's decision forever under one ExecutionRecord per run.
- **Iteration counter.** From 88.2.6, `evaluate_post_run` increments `mission_runs.iteration_count`, not `mission_plans.supervisor_iteration_count` (`supervisor_activities.py:169`).
- **Status fields.** `RunStatusUpdate.status`/`reason` and `FinaliseRunInput.status`/`reason` carry `MissionRunStatus` and `MissionRunStatusReason` values (lowercase strings); `reason` is `str | None`, and `None` with status `cancelled` means `run.cancel_reason`.
- **Ledger writes are fatal.** From 88.4.6, a `record_llm_call` failure (`agents/mission_control/helpers/agent_executor.py:346-362`) propagates whenever `mission_run_id` is set, so the ledger never under-counts.

#### 3.3.6 Gate action vocabulary (durable gates)

| Gate point | Allowed actions | Telegram Approve | Telegram Reject |
|---|---|---|---|
| `pre_dispatch`, `pre_layer`, `post_task`, `post_layer` | `continue`, `abort` | `continue` | `abort` |
| `verification_failed` | `retry`, `skip`, `abort` | `retry` | `abort` |
| `post_run` | `advance_approved`, `advance_refine`, `propose_complete`, `abort` | the supervisor's recommended action stored in `context_json.recommended_action` | `abort` |

- `abort` means the run becomes `CANCELLED/GATE_REJECTED`.
- `allowed_actions(gate_point) -> list[str]` returns this table's row. `_validate_action_for_gate_type` (`missions_gates.py:268`) moves into `GateDecisionService` in 88.4.8. The API exposes the list on `GateRequestDetail.allowed_actions` (88.0.13) and `GateRequestSummary.allowed_actions` (88.4.8), so clients never hold their own copy (`mc_gate.py:43-55` is deleted in 88.4.8).

### 3.4 Config keys

New schema models use `Field(...)` (required, no default), as the no-fallbacks rule requires. Defaults are not added to new fields. Enum-valued keys use lowercase values (3.0.2).

#### 3.4.1 `config/settings/temporal.yaml` (final state)

```yaml
enabled: true
server_url: "127.0.0.1:7233"
namespace: "default"
task_queue: "agent-missions"
# Still read outside MissionRunWorkflow (escalation.py, approval.py, workflow_run_steps/human_input.py),
# and by build_run_config_snapshot for gate timings until 88.4.8:
approval_timeout_seconds: 14400
escalation_timeout_seconds: 86400
# Read by build_workflow_timeouts_snapshot (88.2.2):
min_activity_timeout_seconds: 600
persistence_timeout_seconds: 30
persistence_retry_max_attempts: 3
namespace_retention_days: 30                    # 88.5.1
dev_server:                                     # 88.5.1
  db_path: "var/temporal/dev-server.sqlite"
health:                                         # 88.5.5
  probe_timeout_seconds: 3
  worker_poller_stale_seconds: 120

mission_run:
  continue_as_new_after_iterations: 10
  max_parallel_tasks: 4
  refine_wait_seconds: 600
  tick_execution_timeout_seconds: 300
  task_heartbeat_interval_seconds: 20
  max_run_duration_seconds: 43200               # 88.2.1; 12h of active execution, gate waits excluded
  activities:
    claim:             {start_to_close_seconds: 60,   heartbeat_timeout_seconds: null, retry: {initial_interval_seconds: 2, backoff_coefficient: 2.0, maximum_interval_seconds: 30,  maximum_attempts: 5}}
    persistence:       {start_to_close_seconds: 30,   heartbeat_timeout_seconds: null, retry: {initial_interval_seconds: 1, backoff_coefficient: 2.0, maximum_interval_seconds: 30,  maximum_attempts: 5}}
    plan_run:          {start_to_close_seconds: 1800, heartbeat_timeout_seconds: 60,   retry: {initial_interval_seconds: 10, backoff_coefficient: 2.0, maximum_interval_seconds: 120, maximum_attempts: 2}}
    execute_task:      {start_to_close_seconds: 3600, heartbeat_timeout_seconds: 60,   retry: {initial_interval_seconds: 10, backoff_coefficient: 2.0, maximum_interval_seconds: 300, maximum_attempts: 3}}
    evaluate_gate:     {start_to_close_seconds: 120,  heartbeat_timeout_seconds: null, retry: {initial_interval_seconds: 5, backoff_coefficient: 2.0, maximum_interval_seconds: 60,  maximum_attempts: 3}}
    evaluate_post_run: {start_to_close_seconds: 120,  heartbeat_timeout_seconds: null, retry: {initial_interval_seconds: 5, backoff_coefficient: 2.0, maximum_interval_seconds: 60,  maximum_attempts: 3}}
    director_turn:     {start_to_close_seconds: 60,   heartbeat_timeout_seconds: null, retry: {initial_interval_seconds: 5, backoff_coefficient: 2.0, maximum_interval_seconds: 30,  maximum_attempts: 2}}
    write_digest:      {start_to_close_seconds: 300,  heartbeat_timeout_seconds: 60,   retry: {initial_interval_seconds: 10, backoff_coefficient: 2.0, maximum_interval_seconds: 120, maximum_attempts: 3}}
    notify:            {start_to_close_seconds: 30,   heartbeat_timeout_seconds: null, retry: {initial_interval_seconds: 5, backoff_coefficient: 2.0, maximum_interval_seconds: 300, maximum_attempts: 6}}

reconciler:
  orphan_grace_seconds: 600
  activity: {start_to_close_seconds: 300, heartbeat_timeout_seconds: null, retry: {initial_interval_seconds: 10, backoff_coefficient: 2.0, maximum_interval_seconds: 60, maximum_attempts: 3}}

system_schedules:            # sole source of system crons; registered by the worker, create-or-update
  reconciler:           {cron: "*/5 * * * *"}   # 88.0.2
  retention:            {cron: "30 2 * * *"}    # 88.1.10 (DailyCleanupWorkflow until 88.5.4)
  hourly_health_check:  {cron: "0 * * * *"}     # 88.1.10
  weekly_report:        {cron: "0 6 * * 0"}     # 88.1.10
  metrics_aggregation:  {cron: "*/15 * * * *"}  # 88.1.10
  cleanup_environments: {cron: "0 * * * *"}     # 88.1.10
  knowledge_extraction: {cron: "30 3 * * *"}    # 88.1.10
  knowledge_officer:    {cron: "0 4 * * *"}     # 88.1.10
  embedding_backfill:   {cron: "15 4 * * *"}    # 88.1.10
```

**Deleted keys (13), each in the step that deletes its last reader:**

| Key | Last reader | Deleted in |
|---|---|---|
| `workflow_execution_timeout_days`, `activity_start_to_close_seconds`, `activity_retry_max_attempts` | none (assertions at `test_config.py:18-20` only) | 88.1.1 |
| `refine_poll_interval_seconds` | none | 88.1.1 |
| `dispatch_check_interval_seconds` | `main.py:125` (`ScheduledMissionCheckWorkflow` registration) | 88.1.10 |
| `wait_action_sleep_seconds`, `refine_poll_max_seconds`, `max_supervisor_iterations` | `mission_run_workflow.py:80,188,233` and `run_objective_workflow.py:56` | 88.1.8 |
| `budget_timeout_multiplier_seconds`, `execution_retry_max_attempts`, `execution_retry_initial_interval_seconds`, `execution_retry_max_interval_seconds`, `notification_timeout_seconds` | `AgentMissionWorkflow` (`temporal/workflow.py:72,86-91`) and `api/v1/endpoints/executions.py` | 88.2.6 |

**Also deleted (88.1.1):** `missions.yaml knowledge.embedding.backfill_schedule_cron` and `knowledge.officer.schedule_cron`. Both are unread; `system_schedules` replaces them.

#### 3.4.2 `config/settings/missions.yaml` (append)

```yaml
recurrence:                                 # 88.1.1
  enabled: true                             # false: schedule create rejected; sync pauses every mission schedule
  default_catch_up_window_seconds: 21600    # 6h (decision 8)
  max_catch_up_window_seconds: 604800
  min_interval_seconds: 300                 # cron firing more often than this is rejected (validate_spec over 8 days)
  max_schedules_per_mission: 5
  objective_template_max_chars: 4000
budgets:                                    # 88.4.1
  default_per_run_usd: 5.00
  default_per_month_usd: 100.00
  max_per_run_usd: 100.00
  max_per_month_usd: 2000.00
digest:                                     # 88.3.1
  agent_name: "mission.digest.agent"        # new catalog agent, config/agents/mission/digest/agent.yaml
  summary_max_chars: 2000
  max_outcomes: 50
  headline_max_chars: 200                   # outcome headline and open-item text truncation
  task_excerpt_max_chars: 1500              # per-task output excerpt sent to the digest agent
  agent_output_retries: 2                   # pydantic-ai output_retries for the digest agent
context_packet:                             # 88.3.1
  previous_digest_max_chars: 4000
  context_delta_max_changes: 100
  context_delta_max_tokens: 2000
  context_delta_value_max_chars: 200
  assembly_order: [previous_run_digest, context_delta, code_map, learnings, history]
compaction:                                 # 88.3.1
  decisions_max_age_days: 90
  keep_recent_milestones: 5
  protected_roots: [identity, guardrails, current_state]
observability:                              # 88.5.7
  failing_streak_threshold: 3
  occurrence_window_days: 7
  spend_warn_pct: 80
  temporal_describe_concurrency: 8
  health_list_max_missions: 200
```

Also in 88.3.1: `knowledge.learnings.extraction_window_days: 30`, and the existing `pcd_prune_threshold_pct` becomes required and is read by `MissionContextManager.compact`.

`recurrence.enabled` is required (no default). When it is false, `MissionScheduleService.create_schedule` raises `ValidationError` and `claim_occurrence` records `SKIPPED/SCHEDULE_NOT_ACTIVE`. Until Phase 4 is complete, production sets it to `false` (3.0.1).

#### 3.4.3 `config/settings/gate.yaml`

88.0.2 adds the interim key `manual.poll_interval_seconds: 5`, used by 88.0.13. In 88.4.8 the whole `manual:` block, `GateManualSchema` and `agents/mission_control/gate_manual.py` are deleted and replaced by:

```yaml
durable:
  escalate_after_seconds: 14400
  pause_after_seconds: 86400     # validator: > escalate_after_seconds
```

#### 3.4.4 `config/settings/notifications.yaml` (replace the file, 88.4.4)

```yaml
enabled: true
channels:
  telegram:
    enabled: true
    inbound_approvals_enabled: false     # P8: off by default; the acceptance environment sets true
default_kinds: [run_succeeded, run_failed, gate_waiting, gate_escalated, gate_timeout_paused, budget_paused, run_skipped, run_missed]
action_tokens:
  gate_decision_ttl_seconds: 604800      # 7 days; validator: >= gate.durable.pause_after_seconds
  channel_link_ttl_seconds: 600
message_max_chars: 3500
```

These keys are deleted, along with `RunNotifierService` (`services/run_notifier.py`), which broadcasts to every `authorized_users` entry (`run_notifier.py:235-247`): `budget_warning_threshold_pct`, `notify_on_completion`, `notify_on_failure` and `notify_channels`.

#### 3.4.5 `config/settings/retention.yaml` (new, 88.5.3; loaded with `_load_validated`, required)

```yaml
enabled: true
batch_size: 5000
lock_timeout_ms: 5000
statement_timeout_ms: 60000
activity: {start_to_close_seconds: 3600, heartbeat_timeout_seconds: 120, retry: {initial_interval_seconds: 30, backoff_coefficient: 2.0, maximum_interval_seconds: 300, maximum_attempts: 3}}
policies:
  mission_events_days: 90            # the mission_events table (models/mission_event.py:19)
  task_outputs_days: 90              # task_executions.output_data, execution_records.execution_outcome_json and planning_thinking_trace, tasks.result_summary -> NULL (rows kept)
  llm_calls_raw_days: 90             # rolled into llm_call_daily_aggregates, then deleted
  notification_deliveries_days: 90
  action_tokens_days_after_expiry: 30
  revoked_sessions: expired          # existing purge_expired_revocations
# Never touched: mission_runs, mission_run_digests, gate_requests, context_changes,
# mission_decisions, mission_learnings, llm_call_daily_aggregates, session_messages.
```

`executions.yaml retention_days` and `ExecutionsSchema.retention_days` are deleted in 88.5.3.

#### 3.4.6 `core/config_schema.py` changes

```python
class RetrySchema(_StrictBase):                               # 88.0.2
    initial_interval_seconds: int = Field(..., ge=1)
    backoff_coefficient: float = Field(..., ge=1.0)
    maximum_interval_seconds: int = Field(..., ge=1)
    maximum_attempts: int = Field(..., ge=1)


class ActivityPolicySchema(_StrictBase):                      # 88.0.2
    start_to_close_seconds: int = Field(..., ge=1)
    heartbeat_timeout_seconds: int | None = Field(...)
    retry: RetrySchema


class MissionRunActivitiesSchema(_StrictBase):                # 88.0.2
    claim: ActivityPolicySchema
    persistence: ActivityPolicySchema
    plan_run: ActivityPolicySchema
    execute_task: ActivityPolicySchema
    evaluate_gate: ActivityPolicySchema
    evaluate_post_run: ActivityPolicySchema
    director_turn: ActivityPolicySchema
    write_digest: ActivityPolicySchema
    notify: ActivityPolicySchema


class MissionRunSchema(_StrictBase):                          # 88.0.2
    continue_as_new_after_iterations: int = Field(..., ge=1)
    max_parallel_tasks: int = Field(..., ge=1)
    refine_wait_seconds: int = Field(..., ge=1)
    tick_execution_timeout_seconds: int = Field(..., ge=10)
    task_heartbeat_interval_seconds: int = Field(..., ge=1)
    max_run_duration_seconds: int = Field(..., ge=600)        # 88.2.1
    activities: MissionRunActivitiesSchema
    # validator: activities.execute_task.heartbeat_timeout_seconds is not None and
    #            task_heartbeat_interval_seconds * 2 <= activities.execute_task.heartbeat_timeout_seconds


class ReconcilerSchema(_StrictBase):                          # 88.0.2
    orphan_grace_seconds: int = Field(..., ge=60)
    activity: ActivityPolicySchema


class SystemScheduleSchema(_StrictBase):                      # 88.0.2
    cron: str = Field(..., min_length=9)


ALLOWED_SYSTEM_SCHEDULE_KEYS = frozenset({
    "reconciler", "retention", "hourly_health_check", "weekly_report", "metrics_aggregation",
    "cleanup_environments", "knowledge_extraction", "knowledge_officer", "embedding_backfill",
})


class TemporalDevServerSchema(_StrictBase):                   # 88.5.1
    db_path: str = Field(..., min_length=1)


class TemporalHealthSchema(_StrictBase):                      # 88.5.5
    probe_timeout_seconds: int = Field(..., ge=1)
    worker_poller_stale_seconds: int = Field(..., ge=30)

# TemporalSchema:
#   88.0.2 adds mission_run: MissionRunSchema, reconciler: ReconcilerSchema,
#          system_schedules: dict[str, SystemScheduleSchema], all Field(...), and a validator:
#          keys are a subset of ALLOWED_SYSTEM_SCHEDULE_KEYS and contain "reconciler".
#   88.1.10 tightens the validator to set(system_schedules) == ALLOWED_SYSTEM_SCHEDULE_KEYS.
#   The 13 deleted keys in 3.4.1 are removed in the steps named there.
#   88.5.1 adds namespace_retention_days: int = Field(..., ge=1, le=3650) and dev_server: TemporalDevServerSchema.
#   88.5.5 adds health: TemporalHealthSchema.


class RecurrenceSchema(_StrictBase):                          # 88.1.1
    enabled: bool = Field(...)
    default_catch_up_window_seconds: int = Field(..., ge=60)
    max_catch_up_window_seconds: int = Field(..., ge=60)
    min_interval_seconds: int = Field(..., ge=60)
    max_schedules_per_mission: int = Field(..., ge=1)
    objective_template_max_chars: int = Field(..., ge=100)
    # validator: default_catch_up_window_seconds <= max_catch_up_window_seconds


class BudgetDefaultsSchema(_StrictBase):                      # 88.4.1
    default_per_run_usd: float = Field(..., gt=0)
    default_per_month_usd: float = Field(..., gt=0)
    max_per_run_usd: float = Field(..., gt=0)
    max_per_month_usd: float = Field(..., gt=0)
    # validator: default_per_run_usd <= default_per_month_usd; each default <= its maximum


class DigestSchema(_StrictBase):                              # 88.3.1
    agent_name: str = Field(..., min_length=1)
    summary_max_chars: int = Field(..., ge=200)
    max_outcomes: int = Field(..., ge=1)
    headline_max_chars: int = Field(..., ge=50)
    task_excerpt_max_chars: int = Field(..., ge=1)
    agent_output_retries: int = Field(..., ge=0)


class ContextPacketSchema(_StrictBase):                       # 88.3.1
    previous_digest_max_chars: int = Field(..., ge=200)
    context_delta_max_changes: int = Field(..., ge=1)
    context_delta_max_tokens: int = Field(..., ge=1)
    context_delta_value_max_chars: int = Field(..., ge=50)
    assembly_order: list[Literal["previous_run_digest", "context_delta", "code_map", "learnings", "history"]] = Field(...)
    # validator: assembly_order lists each of the 5 layers exactly once


class CompactionSchema(_StrictBase):                          # 88.3.1
    decisions_max_age_days: int = Field(..., ge=1)
    keep_recent_milestones: int = Field(..., ge=1)
    protected_roots: list[str] = Field(..., min_length=1)
    # validator: reject "version", "last_updated", "last_updated_by" (always protected)


class ObservabilitySchema(_StrictBase):                       # 88.5.7
    failing_streak_threshold: int = Field(..., ge=1)
    occurrence_window_days: int = Field(..., ge=1)
    spend_warn_pct: int = Field(..., ge=1, le=100)
    temporal_describe_concurrency: int = Field(..., ge=1)
    health_list_max_missions: int = Field(..., ge=1)

# MissionsSchema: delete default_budget_ceiling_usd; add recurrence: RecurrenceSchema; budgets: BudgetDefaultsSchema; digest: DigestSchema; context_packet: ContextPacketSchema; compaction: CompactionSchema. pcd_prune_threshold_pct becomes Field(..., ge=1, le=100), read by MissionContextManager.compact. KnowledgeLearningsSchema gains extraction_window_days: int = Field(..., ge=1).
#   Steps: 88.1.1 recurrence; 88.3.1 digest, context_packet, compaction, pcd_prune_threshold_pct and the
#   validator pcd_target_size_bytes < pcd_max_size_bytes; 88.4.1 budgets and the deletion;
#   88.5.7 observability: ObservabilitySchema.
# KnowledgeEmbeddingSchema: 88.1.1 deletes backfill_schedule_cron. KnowledgeOfficerSchema: 88.1.1 deletes schedule_cron.


class GateDurableSchema(_StrictBase):                         # 88.4.8
    escalate_after_seconds: int = Field(..., ge=60)
    pause_after_seconds: int = Field(..., ge=60)
    # validator: pause_after_seconds > escalate_after_seconds

# GateSchema: 88.0.2 adds GateManualSchema.poll_interval_seconds: int = Field(..., ge=1);
#   88.1.0 makes GateSchema.mode required: mode: _GateMode = Field(...);
#   88.4.8 deletes manual: GateManualSchema (and the class) and adds durable: GateDurableSchema.


class TelegramChannelSchema(_StrictBase):                     # 88.4.4
    enabled: bool = Field(...)
    inbound_approvals_enabled: bool = Field(...)


class NotificationChannelsSchema(_StrictBase):                # 88.4.4
    telegram: TelegramChannelSchema


class ActionTokensSchema(_StrictBase):                        # 88.4.4
    gate_decision_ttl_seconds: int = Field(..., ge=60)
    channel_link_ttl_seconds: int = Field(..., ge=60)


class NotificationsSchema(_StrictBase):                       # 88.4.4; replaces the existing class
    enabled: bool = Field(...)
    channels: NotificationChannelsSchema
    default_kinds: list[NotificationKind] = Field(..., min_length=1)
    action_tokens: ActionTokensSchema
    message_max_chars: int = Field(..., ge=500, le=4096)


class RetentionPoliciesSchema(_StrictBase):                   # 88.5.3
    mission_events_days: int = Field(..., ge=1)
    task_outputs_days: int = Field(..., ge=1)
    llm_calls_raw_days: int = Field(..., ge=1)
    notification_deliveries_days: int = Field(..., ge=1)
    action_tokens_days_after_expiry: int = Field(..., ge=1)
    revoked_sessions: Literal["expired"]


class RetentionSchema(_StrictBase):                           # 88.5.3
    enabled: bool = Field(...)
    batch_size: int = Field(..., ge=100)
    lock_timeout_ms: int = Field(..., ge=100)
    statement_timeout_ms: int = Field(..., ge=1000)
    activity: ActivityPolicySchema
    policies: RetentionPoliciesSchema


class CopilotClientSchema(_StrictBase):                       # 88.2.1; ProvidersSchema gains copilot_client: CopilotClientSchema
    health_check_interval_seconds: int = Field(..., ge=30)
    ping_timeout_seconds: int = Field(..., ge=1, le=60)


class CliMcSchema(_StrictBase):                               # 88.1.13
    runs_list_limit: int = Field(..., ge=1, le=200)


class CliSchema(_StrictBase):                                 # 88.1.13
    mc: CliMcSchema

# WorkflowsSchema: 88.1.3 deletes max_scheduled_runs_per_day and schedule_evaluation_interval_seconds.
# ExecutionsSchema: 88.5.3 deletes retention_days.
```

`NotificationsSchema` imports `NotificationKind` from `modules/backend/models/notification.py`. No module under `models/` imports `core.config`, so the import creates no cycle.

**Changes in `AppConfig.__init__`** (`core/config.py`):
- 88.1.13: load `cli.yaml` with `_load_validated(CliSchema, "cli.yaml")`, required, and add the `cli` property.
- 88.5.3: load `retention.yaml` with `_load_validated(RetentionSchema, "retention.yaml")`, required, and add the `retention` property.
- Cross-file checks:
  - 88.4.8: `notifications.action_tokens.gate_decision_ttl_seconds >= gate.durable.pause_after_seconds`;
  - 88.3.1: `missions.digest.agent_name` must not be empty. Catalog existence is checked at worker startup.

#### 3.4.7 `config/settings/providers.yaml` (append, 88.2.1)

```yaml
copilot_client:
  health_check_interval_seconds: 300
  ping_timeout_seconds: 10
```

`ProvidersSchema` gains a required `copilot_client: CopilotClientSchema` field, and `providers.yaml` is loaded with `_load_validated`.

#### 3.4.8 `config/settings/cli.yaml` (new, 88.1.13)

```yaml
mc:
  runs_list_limit: 20      # rows returned by `mc runs list` when --limit is omitted
```

#### 3.4.9 `config/settings/failures.yaml` (new, 88.2.3b; loaded with `_load_validated`, required)

The file starts with the standard commented options header (rule 003.3). It holds bounds and policy only. Classification rules are code (3.8.3).

```yaml
evidence:
  max_message_chars: 2000        # FailureEvidence.message, after redact_secrets
  max_summary_chars: 300         # TaskFailure.summary
  max_traceback_frames: 8        # innermost frames kept in FailureEvidence.traceback_tail
supervisor:
  max_failure_digests: 10        # post-run summary["failures"] and REFINE_PROMPT digests; overflow is counted, never silent
unknown_retryable: true          # retry policy for FailureClass.UNKNOWN (today's behaviour: retry)
```

`FailuresSchema` (`core/config_schema.py`, `extra="forbid"`) requires every key. The bounds are `ge=1`. `AppConfig.__init__` loads it in 88.2.3b with `_load_validated(FailuresSchema, "failures.yaml")`, required, and adds the `failures` property.

#### 3.4.10 `config/settings/executions.yaml` (append, 88.2.3a)

```yaml
run_tests_timeout_seconds: 900   # wall-clock limit for one run_tests call inside the environment handle
```

`ExecutionsSchema` gains `run_tests_timeout_seconds: int = Field(..., ge=1)`, and the options header documents it. 88.2.3a switches `executions.yaml` from `_load_validated_optional` to `_load_validated` (required), because a required key makes an absent file invalid. `run_tests` reads `get_app_config().executions.run_tests_timeout_seconds`; there is no literal default.

### 3.5 Service interfaces, repositories, API and CLI

**Layering:**
- Every service takes `AsyncSession` and subclasses `BaseService`. A method that commits saves its ORM attributes to locals before calling Temporal (`pattern_orm_commit_refresh`).
- A Temporal call never happens inside an open transaction. There are three deliberate exceptions, each bounded by its caller's timeout: `GateDecisionService.decide` (3.3.3), and `MissionScheduleService.claim_occurrence` and `MissionLifecycleService.resume_mission`, which call `TemporalScheduleGateway.list_matching_times` with the schedule row lock held (3.3.2, 3.2.2).
- **Thin clients.** `mc` and the web go through the REST API only. `admin.py` and the Telegram bot run inside the backend trust boundary and may call services in-process, never repositories or models. The Telegram client already does this (`clients/telegram/handlers/common.py:131`).
- **`X-Frontend-ID`.** The `mc` API client (`modules/clients/cli/api_client.py`) sends `X-Frontend-ID: cli`; the frontend api wrapper (`modules/frontend/src/lib/api.ts`) sends `X-Frontend-ID: web` (both in 88.4.8). The middleware already maps the header to `request.state.source` (`core/middleware.py:56`). The header is client-asserted: it labels the audit field `gate_requests.decision_channel` and nothing else, and never feeds an authorisation decision.

#### 3.5.1 Services

```text
# services/mission_schedule.py  (88.1.6; replaces services/workflow_schedule.py)
class MissionScheduleService(BaseService):
    async def create_schedule(self, mission_id: str, data: MissionScheduleCreate, user_id: str) -> MissionSchedule
        # step 0, before any DB access: gateway.validate_spec(spec, window=timedelta(days=8));
        # loads workflow_definition_id scoped to mission_id (closes the create IDOR at missions_workflows.py:648-681)
    async def get_schedule(self, mission_id: str, schedule_id: str) -> MissionSchedule
        # loads by BOTH ids (closes the IDOR at missions_workflows.py:684-735)
    async def list_schedules(self, mission_id: str, *, include_archived: bool) -> list[MissionSchedule]
    async def update_schedule(self, mission_id: str, schedule_id: str, data: MissionScheduleUpdate, user_id: str) -> MissionSchedule
        # a spec change sets last_claimed_scheduled_for = utc_now()
    async def pause_schedule(self, mission_id: str, schedule_id: str, user_id: str) -> MissionSchedule
    async def resume_schedule(self, mission_id: str, schedule_id: str, user_id: str) -> MissionSchedule
        # sets last_claimed_scheduled_for = utc_now(), so a schedule pause is never backfilled
    async def archive_schedule(self, mission_id: str, schedule_id: str, user_id: str) -> MissionSchedule
    async def next_fire_times(self, schedule: MissionSchedule, count: int) -> list[datetime]   # from Temporal describe
    async def sync_to_temporal(self, schedule_id: str) -> TemporalSyncState
    async def sync_mission(self, mission_id: str) -> ScheduleSyncStats
    async def sync_all(self) -> ScheduleSyncStats            # reconciler; completes END_DATE_REACHED from 88.4.7
    async def claim_occurrence(self, schedule_id: str, scheduled_for: datetime) -> OccurrenceClaim   # 3.3.2

# temporal/schedule_gateway.py  (88.1.5; the only module, besides temporal/system_schedules.py, that touches Temporal Schedule APIs)
class TemporalScheduleGateway:
    async def upsert(self, schedule_id: str, schedule: Schedule) -> None
    async def set_paused(self, schedule_id: str, paused: bool, note: str) -> None
    async def delete(self, schedule_id: str) -> None                                           # NOT_FOUND treated as success
    async def describe(self, schedule_id: str) -> ScheduleDescription | None
    async def list_matching_times(self, schedule_id: str, start: datetime, end: datetime) -> list[datetime]
    async def list_ids(self, prefix: str | None) -> list[str]                                  # orphan sweep, legacy cleanup
    async def validate_spec(self, spec: ScheduleSpec, window: timedelta) -> list[datetime]
        # paused probe mission-schedule-probe-{uuid4().hex} whose action is a ScheduleActionStartWorkflow
        # of workflow type "MissionScheduleProbe" (built internally); lists matching times over window;
        # deleted in finally; RPCError INVALID_ARGUMENT -> ValidationError
        # validate_spec exists because ListScheduleMatchingTimes needs a schedule, and the
        # min_interval_seconds check runs before the row exists.

# temporal/workflow_gateway.py  (88.0.3) TemporalWorkflowGateway is the only module outside workflow code
#   that starts or holds handles for MissionRunWorkflow, MissionScheduleTickWorkflow, ReconcilerWorkflow or RetentionWorkflow
#   (TemporalScheduleGateway owns their schedules). No direct start_workflow or get_workflow_handle for them
#   elsewhere; other workflows (chat, tool fork, plan refine, human input, workflow-run) are out of scope.
class TemporalWorkflowGateway:
    async def state(self, workflow_id: str) -> WorkflowState                                   # 88.0.3
    async def cancel(self, workflow_id: str) -> WorkflowState                                  # 88.0.3
    async def terminate(self, workflow_id: str, reason: str) -> WorkflowState                  # 88.0.3
    async def start_mission_run(self, inp: MissionRunWorkflowInput) -> None                    # 88.1.7; REJECT_DUPLICATE
    async def signal(self, workflow_id: str, signal: str, arg: object) -> WorkflowState        # 88.1.9; NOT_FOUND on missing/closed
    async def fetch_history(self, workflow_id: str, *, run_id: str | None) -> tuple[WorkflowHistory, bool]   # 88.2.9; (history, still running)
    async def execute_update(self, workflow_id: str, name: str, payload: object,
                             rpc_timeout: timedelta) -> object                                 # 88.4.8
    async def start_retention(self, inp: RetentionInput, workflow_id: str) -> None            # 88.5.4; REJECT_DUPLICATE
    async def describe_status(self, workflow_id: str) -> WorkflowStatusDescription | None      # 88.5.8; handle.describe(), NOT_FOUND -> None
    async def query_state(self, workflow_id: str) -> MissionRunWorkflowStatus | None           # 88.5.8; get_run_state query, NOT_FOUND -> None
        # WorkflowStatusDescription{workflow_type, status (lowercase execution status), start_time, close_time | None}

# services/mission_run.py  (88.1.7)
class MissionRunService(BaseService):
    async def start_run(self, mission_id: str, *, trigger: MissionRunTrigger, objective: str | None,
                        user_id: str, session_id: str | None) -> MissionRun
        # increment_run_sequence and the insert in one transaction; on uq_mission_runs_one_active the
        # whole transaction rolls back (the increment too) and ConflictError is raised.
        # Commit, then gateway.start_mission_run; a Temporal error transitions the run FAILED/START_FAILED.
    async def on_tasks_approved(self, mission_id: str, task_ids: list[str], user_id: str) -> None   # 88.1.9
        # 88.1.9: active run -> gateway.signal tasks_approved; none, plan.gate_mode == AUTONOMOUS and
        # mission ACTIVE -> start_run(MANUAL, objective=None)
    async def get_run(self, mission_id: str, run_id_or_sequence: str) -> MissionRun
    async def list_runs(self, mission_id: str, *, statuses: list[MissionRunStatus] | None,
                        limit: int, before_sequence: int | None) -> list[MissionRun]
    async def cancel_run(self, mission_id: str, run_id: str, user_id: str, reason: MissionRunStatusReason) -> MissionRun
        # loads WHERE id AND mission_id (3.0.2). From 88.4.5: a terminal run is a no-op, and a PENDING
        # unstarted run is cancelled through the workflow (begin sees cancel_requested_at), not directly.
        # When the workflow is already closed, the run gets write_digest(run_id, status=MissionRunStatus.CANCELLED,
        # reason=run.cancel_reason, narrator=None) before finalise. 88.4.5 updates the 88.1.7 tests by name.
    async def get_live_state(self, mission_id: str, run_id_or_sequence: str) -> MissionRunLiveStateResponse   # 88.5.8
    async def get_history(self, mission_id: str, run_id_or_sequence: str) -> MissionRunHistoryResponse   # 88.5.8; via TemporalWorkflowGateway.fetch_history
    async def transition(self, run_id: str, target: MissionRunStatus, reason: MissionRunStatusReason | None,
                         detail: str | None) -> MissionRun
    async def begin(self, run_id: str) -> BeginRunResult
        # gate mode invalid -> FAILED/INVALID_GATE_MODE; owner not a user -> FAILED/START_FAILED;
        # both commit then raise RunStartRejectedError (88.4.5 adds: cancel_requested_at set -> CANCELLED,
        # same error); a run not PENDING raises MissionRunStateError.
        # Otherwise: snapshot gate_mode, create the session and
        # the run's single ExecutionRecord with temporal_workflow_id = mission_run_workflow_id(run_id) (88.1.10a),
        # adopt APPROVED backlog tasks (mission_run_id IS NULL), read context_version_start,
        # snapshot budget_cap_usd (88.4.1).
    async def plan(self, run_id: str, session_id: str) -> PlanRunResult
        # Director tool-call planning, or definition materialisation via the existing
        # step->Task mapping in workflow_run.py:442-520 (tasks get mission_run_id)
    async def task_graph(self, run_id: str) -> RunTaskGraph
    async def finalise(self, run_id: str, status: MissionRunStatus, reason: MissionRunStatusReason | None,
                       detail: str | None) -> FinaliseRunResult
        # one transaction: cost_usd = sum(llm_calls.cost_usd WHERE mission_run_id = run_id);
        # context_version_end only when NULL; terminal transition; mission_run_id = NULL on the run's
        # PROPOSED and APPROVED tasks. After commit: if APPROVED backlog exists, plan.gate_mode == AUTONOMOUS
        # and mission ACTIVE -> start_run(MANUAL, objective=None) (test test_approval_racing_finalise_starts_next_run)
    async def record_iteration(self, run_id: str, iteration: int) -> None   # 88.2.6

# temporal/config_snapshots.py  (the ONLY place snapshots are built; 88.0.2, 88.1.5, 88.2.2)
def policy_snapshot(schema: ActivityPolicySchema) -> ActivityPolicySnapshot      # 88.0.2
def config_hash(obj: object) -> str                                              # 88.0.2
def build_run_config_snapshot() -> RunConfigSnapshot                            # 88.1.5; 88.2.2 adds its fields
def build_tick_config_snapshot() -> TickConfigSnapshot                          # 88.1.5
def build_workflow_timeouts_snapshot() -> WorkflowTimeoutsSnapshot              # 88.2.2
# MissionRunService builds no snapshot; start_run and MissionScheduleService import these.

# services/mission_lifecycle.py  (88.4.5)
class MissionLifecycleService(BaseService):
    async def pause_mission(self, mission_id: str, *, reason: MissionPauseReason, user_id: str | None) -> Mission
    async def resume_mission(self, mission_id: str, user_id: str | None) -> Mission
        # user_id None only from resume_mission_for_run. Precondition uses GateRequestRepository.has_undecided.
        # Per ACTIVE schedule, locked with MissionScheduleRepository.lock and with the lock held: list_matching_times(schedule_id,
        # missions.paused_at, now) via TemporalScheduleGateway, insert MISSED/NOT_FIRED for each slot
        # (sequence allocated as in claim_occurrence), then set last_claimed_scheduled_for = now (3.2.2;
        # test test_mission_pause_slots_backfilled)
    async def archive_mission(self, mission_id: str, user_id: str) -> Mission
        # undecided gate requests -> CANCELLED through GateRequestRepository.cancel_undecided (3.2.2)
    async def unarchive_mission(self, mission_id: str, user_id: str) -> Mission
    async def pause_all_active(self, user_id: str) -> int
    async def _apply_pause(self, mission: Mission, reason: MissionPauseReason, user_id: str | None) -> None
        # flush only: no commit, no Temporal (used by claim_occurrence)

# services/mission.py  (changed)
class MissionService(BaseService):
    async def is_operator(self, mission: Mission, user: User) -> bool
        # 88.0.9: platform admin, the mission owner, or a member whose role is in
        # {MissionMemberRole.OWNER, MissionMemberRole.MAINTAINER} (models/mission.py:42-46).
        # The single operator rule, used by require_mission_operator and GateDecisionService.

# services/budget.py  (88.4.1; enforcement in 88.4.6)
class BudgetService(BaseService):
    async def get_status(self, mission_id: str) -> BudgetStatus             # caps + run/month/lifetime spend + breach
    async def check_run(self, run_id: str) -> BudgetCheckResult
        # run cap = coalesce(run.budget_cap_usd, plan.budget_per_run_usd)
    async def update_caps(self, mission_id: str, data: BudgetCapsUpdate, user_id: str) -> BudgetStatus
    @staticmethod
    def mission_cap_breach(status: BudgetStatus) -> MissionPauseReason | None
    @staticmethod
    def validate_caps(per_run: float, per_month: float, lifetime: float | None) -> None
    # month and lifetime spend = sum(llm_call_daily_aggregates) + sum(llm_calls) over the window;
    # month = UTC calendar month; run spend = raw llm_calls only

# services/run_memory.py  (88.3.5, 88.3.7; never imports modules.backend.agents)
class RunMemoryService(BaseService):
    async def build_context_packet(self, run_id: str) -> RunContextPacket
        # previous_run_digest (truncated) and context_delta = changes with version in
        # (previous_run.context_version_start, current.context_version_start]. Learnings are selected per task
        # inside ContextAssembler; prior outputs stay in load_prior_outputs.
    def render_planning_brief(self, packet: RunContextPacket) -> str
    async def write_digest(self, run_id: str, *, status: MissionRunStatus, reason: MissionRunStatusReason | None,
                           narrator: DigestNarrator | None) -> MissionRunDigest
        # narrator None -> DETERMINISTIC; the write_run_digest activity passes agents.mission.digest.generate_digest_narrative
    async def get_digest(self, mission_id: str, run_id: str) -> MissionRunDigest | None

# services/context_assembler.py (changed): build(mission_id, task_definition, resolved_inputs, *, domain_tags: list[str] | None, mission_run_id: str | None) -> dict with keys project_context, task, inputs, and the optional layers code_map, history, learnings, previous_run_digest, context_delta in missions.context_packet.assembly_order. token_budget and code_map_max_tokens are deleted. _inject_context (dispatch/task_runner.py since 88.2.3) maps every key into resolved_inputs.
# services/mission_plan_taskio.load_prior_outputs(orchestrator, mission_run_id) filters on mission_run_id.
# agents/mission_control/persistence_bridge.persist_mission_results takes execution_record_id and updates
#   that record through ExecutionPersistenceService.complete_execution; it never calls save_execution when
#   execution_record_id is given (88.1.7, test test_wave_reuses_run_execution_record).
# agents/mission_control/mission_dispatch.handle_mission: its positional `mission_run_id` (mission_dispatch.py:46)
#   is a legacy label, not a MissionRun id; 88.1.7 renames it execution_label. From 88.2.3 handle_mission
#   passes mission_run_id=None to build_dispatch_runtime for in-process callers.

# services/mission_context.py (changed: 88.2.4 adds the mission_run_id keyword to apply_updates with default None;
#   88.3.2 uses it and removes the default, giving the final signature below; 88.3.3)
class MissionContextManager(BaseService):
    def __init__(self, session: AsyncSession, event_bus: EventBusProtocol | None = None) -> None
    async def apply_updates(self, mission_id: str, updates: list, *, agent_id: str | None,
                            task_id: str | None, mission_run_id: str | None, reason: str) -> tuple[int, list[str]]
        # locks the MCD row; over pcd_max_size_bytes -> MissionContextCompactor.plan(target=pcd_target_size_bytes)
        # in the same version bump; rejects only when a single update alone exceeds pcd_target_size_bytes
        # (replaces mission_context.py:324-330). Version conflict raises ConflictError.
    async def compact(self, mission_id: str, *, mission_run_id: str | None, reason: str) -> CompactionResult | None
    async def get_changes_between(self, mission_id: str, after_version: int, up_to_version: int,
                                  limit: int) -> list[ContextChange]
    async def count_changes_between(self, mission_id: str, after_version: int, up_to_version: int) -> int

# services/mission_context_compaction.py  (88.3.3)
class MissionContextCompactor(BaseService):
    async def plan(self, mission_id: str, context_id: str, current_version: int, data: dict,
                   target_bytes: int) -> CompactionResult
        # deterministic only: ContextMilestone snapshot, decisions by age, recent_milestones, then oldest
        # unprotected roots with ChangeType.ARCHIVE. No LLM call. Never writes the mission_contexts row.
# services/mcd_pruning.py: mcd_size_bytes, split_decisions_by_age, split_milestones, archive_decision_rows,
#   archive_milestone_rows (shared by SummarizationService and MissionContextCompactor).

# services/gate_decision.py  (88.4.8)
class GateDecisionService(BaseService):
    async def evaluate(self, data: EvaluateGateInput) -> EvaluateGateResult
    async def open_gate(self, data: OpenGateInput) -> GateRequest
        # ON CONFLICT (id) DO NOTHING; issues no tokens (NotificationService issues them at send time)
    async def get(self, mission_id: str, gate_request_id: str) -> GateRequest
        # loads WHERE id AND mission_id (3.0.2)
    async def decide(self, mission_id: str, gate_request_id: str, *, action: str, reason: str | None,
                     user_id: str, channel: DecisionChannel) -> GateRequest
        # loads WHERE id AND mission_id (3.0.2); ordering in 3.3.3
    async def decide_with_action_token(self, *, raw_token: str, short_action: Literal["a", "r"],
                                       external_id: str, callback_ref: str) -> GateRequest
        # 1 identity = ChannelIdentityService.resolve(TELEGRAM, external_id), verified only, else AuthorizationError
        # 2 ActionTokenService.consume(raw, GATE_DECISION, expected_user_id=identity.user_id, ref=callback_ref)
        # 3 user active; MissionService.is_operator checked NOW
        # 4 map a/r via 3.3.6; 5 decide(..., channel=TELEGRAM); all in one transaction
    async def list_open(self, mission_ids: list[str]) -> list[GateRequest]
        # replaces MissionPlanService.list_pending_gate_requests (also used by services/attention.py:49-50)
    async def mark_status(self, gate_request_id: str, status: GateRequestStatus) -> None    # guarded, 3.2.4
    async def close(self, gate_request_id: str, status: GateRequestStatus, decision: GateDecisionUpdate | None) -> None

# services/action_token.py  (88.4.8)
class ActionTokenService(BaseService):
    async def issue(self, *, purpose: ActionTokenPurpose, user_id: str, channel: ChannelKind,
                    gate_request_id: str | None, ttl_seconds: int) -> str      # returns raw token once
    async def consume(self, raw_token: str, purpose: ActionTokenPurpose, *, expected_user_id: str | None,
                      ref: str) -> ActionToken
        # UPDATE ... SET consumed_at, consumed_ref WHERE token_hash=? AND consumed_at IS NULL AND expires_at > now
        # RETURNING; zero rows -> ConflictError (replay/expired); user mismatch -> AuthorizationError

# services/channel_identity.py  (88.4.9)
class ChannelIdentityService(BaseService):
    async def create_link_code(self, user_id: str, channel: ChannelKind) -> tuple[str, datetime]
    async def redeem_link_code(self, channel: ChannelKind, external_id: str, external_username: str | None,
                               code: str, ref: str) -> UserChannelIdentity
        # creates an UNVERIFIED row (verified_at NULL); external_id must also be in
        # application.telegram.authorized_users (P8)
    async def confirm_identity(self, user_id: str, identity_id: str) -> UserChannelIdentity
        # loads WHERE id AND user_id; sets verified_at
    async def resolve(self, channel: ChannelKind, external_id: str) -> UserChannelIdentity | None   # verified rows only
    async def get_for_user(self, user_id: str, channel: ChannelKind) -> UserChannelIdentity | None  # verified rows only
    async def list_identities(self, user_id: str) -> list[UserChannelIdentity]
    async def unlink(self, user_id: str, identity_id: str) -> None

# services/notification.py  (88.4.4; replaces services/run_notifier.py)
class NotificationService(BaseService):
    async def notify(self, request: NotificationRequest) -> list[NotificationDelivery]
        # dedupe_key idempotent; recipient identity via ChannelIdentityService.get_for_user;
        # no verified identity -> SKIPPED_NO_IDENTITY; errors stored through redact_secrets
    async def send_ad_hoc(self, mission_id: str, title: str, body: str, level: str) -> None
        # replaces the run_notifier calls at human_input_activities.py:92, workflow_run_steps/io.py:38 and
        # workflow_run.py:763-789; manual WorkflowRun budget warnings are dropped
    async def list_recipients(self, mission_id: str) -> list[MissionNotificationRecipient]
    async def add_recipient(self, mission_id: str, data: NotificationRecipientCreate, actor_id: str) -> MissionNotificationRecipient
    async def remove_recipient(self, mission_id: str, recipient_id: str, actor_id: str) -> None
        # loads WHERE id AND mission_id (3.0.2)
# Telegram delivery goes through gateway/adapters/telegram.py: TelegramAdapter.send_notification(
#   chat_id: int, text: str, actions: list[tuple[str, str]] | None) -> str  (returns "{chat_id}:{message_id}")

# services/run_reconciliation.py  (88.0.10; replaces services/mission_plan_crash_recovery.py, deleted with
#   main.py:216-249, the call in mission_plan_dispatch.dispatch_approved and scripts/verify_crash_recovery.py)
class RunReconciliationService(BaseService):
    def __init__(self, session: AsyncSession, gateway: TemporalWorkflowGateway, event_bus: SessionEventBus | None) -> None
    async def reconcile(self, orphan_grace_seconds: int) -> ReconcileStats
    async def sweep_gates(self, orphan_grace_seconds: int) -> GateSweepStats  # 88.5.6; cancels undecided gates of terminal runs; logs overdue timers, read-only
        # GateSweepStats{cancelled: int, overdue: int}; ReconcileStats gains gates_cancelled and gates_overdue

# services/retention.py  (88.5.3, 88.5.4)
class RetentionService(BaseService):
    async def run_policy(self, policy: str, batch_size: int, heartbeat: Callable[[dict], None]) -> RetentionResult
    async def trigger(self, policy: str | None) -> str          # starts RetentionWorkflow; ConflictError when disabled
def build_retention_input(config: AppConfig) -> RetentionInput   # the only place RetentionInput is built
```

**`reconcile()` passes.** Every pass collects, then resolves (all Temporal calls, each workflow id described once), then writes in one transaction that re-selects with `FOR UPDATE SKIP LOCKED` and the same predicates. Temporal unreachable means touch nothing and raise, so the activity retries.
1. **Execution pass (88.0.10).** This is the 88.0.10 algorithm (collect, resolve, decide, write). Candidates, each with `updated_at < cutoff` (`cutoff = now - grace`):
   - `execution_records` in PENDING or RUNNING with `temporal_workflow_id IS NOT NULL OR workflow_run_id IS NOT NULL`;
   - `workflow_runs` in PENDING or RUNNING whose execution record has `temporal_workflow_id IS NOT NULL` (AWAITING_INPUT is never selected, because it waits durably in `HumanInputWorkflow`);
   - `tasks` in RUNNING or QUEUED, plus `list_active_for_mission` (WorkflowRuns in PENDING, RUNNING or AWAITING_INPUT) for each distinct mission among them.

   Liveness, with each `state()` cached per workflow id: a record uses `state(temporal_workflow_id)`; a record with only `workflow_run_id` uses its run's execution-record workflow, and a NULL id there makes it **in-process**; a WorkflowRun uses its execution record's workflow. A task is **live** when `state(mission_run_workflow_id(plan_id))` is RUNNING, or any active WorkflowRun of its mission is AWAITING_INPUT or resolves RUNNING; it is **in-process** when any such run has an execution record with NULL `temporal_workflow_id`. Live rows increment `left_running`, in-process rows `left_in_process`, and CLOSED or NOT_FOUND marks the row FAILED. Rows with neither id (CLI and TUI in-process runs, `clients/cli/execution_cmds.py:152,215`, `clients/tui/services/service_bridge.py:155`) are never selected (test `test_in_process_record_without_ids_untouched`). This pass holds unchanged until 88.1.10a.
2. **Run pass (88.1.10a).** For each active-status `mission_runs` row with `updated_at < now - grace`, describe `mission_run_workflow_id(run.id)`. RUNNING leaves the run and its tasks untouched (test `test_running_workflow_leaves_tasks_untouched`). CLOSED gives `FAILED/ORPHANED_WORKFLOW_CLOSED`; NOT_FOUND gives `FAILED/ORPHANED_WORKFLOW_NOT_FOUND`. The run's QUEUED and RUNNING tasks (through `tasks.mission_run_id`) become FAILED, its ExecutionRecord becomes FAILED, and from 88.4.4 `RUN_FAILED` is notified. A PENDING run whose tick died before starting the child is failed after grace, which releases `uq_mission_runs_one_active`, so the next tick runs (test `test_pending_run_without_workflow_failed_after_grace_and_next_tick_runs`). 88.1.10a deletes the task rule's `mission_run_workflow_id(plan_id)` liveness branch from pass 1: from then on tasks are judged only through their run.

**Deleted (P3):**
- `mission_plan_dispatch.dispatch_autonomous` and `start_temporal_run_workflow` (88.1.7), replaced by `MissionRunService.start_run`.
- The Director tool `run_objective` (88.1.7) now calls `start_run(trigger=DIRECTOR)`.
- `services/mission_plan_dispatch.py` (with `dispatch_approved` and its budget lines `:185-192,285-287,318,329,372`) is deleted in full by 88.2.6; 88.4.1 has no dispatch lines to delete.

**Task-to-run assignment (88.1.7):**
- `begin` adopts APPROVED backlog tasks (`mission_run_id IS NULL`).
- Tasks created while a run is active take its id.
- `refine` and `reconcile_tasks` are scoped to the run plus the backlog.
- `finalise` returns the run's PROPOSED and APPROVED tasks to the backlog.

#### 3.5.2 Repositories (new, under `repositories/`)

| Repository | Required methods beyond `BaseRepository` | Step |
|---|---|---|
| `MissionRunRepository` | `get_active_for_mission(mission_id)`, `get_latest_with_digest(mission_id)`, `get_by_sequence(mission_id, seq)`, `get_for_mission(mission_id, run_id)`, `get_by_slot(schedule_id, scheduled_for)`, `insert_occurrence(...)` (ON CONFLICT on the slot DO NOTHING RETURNING), `list_active_older_than(cutoff)` | 88.1.4 |
| `MissionScheduleRepository` | `get_for_mission(mission_id, schedule_id)`, `lock(schedule_id)`, `list_by_mission(mission_id, include_archived)`, `list_syncable()` | 88.1.4 |
| `MissionRunDigestRepository` | `get_by_run(run_id)` | 88.1.4 |
| `UserChannelIdentityRepository` | `get_by_external(channel, external_id, *, verified_only: bool)`, `get_by_user(user_id, channel, *, verified_only: bool)`, `list_by_user(user_id)` | 88.4.3 |
| `ActionTokenRepository` | `consume(token_hash, ref, now)`, `consume_siblings(gate_request_id, now)` | 88.4.3 |
| `MissionNotificationRecipientRepository` | `list_for_kind(mission_id, kind)`, `get_for_mission(mission_id, recipient_id)` | 88.4.3 |
| `NotificationDeliveryRepository` | `get_or_create(dedupe_key, mission_id, kind, recipient_user_id, channel, mission_run_id)` | 88.4.3 |
| `LlmLedgerRepository` (`repositories/llm_ledger.py`) | `sum_cost(mission_id, *, since, until, mission_run_id=None)` (88.1.7 raw only; 88.4.1 adds aggregates when `mission_run_id is None`, and then non-None bounds must be UTC midnight), `oldest_raw_day() -> date \| None`, `rollup_day(day: date, batch_size: int) -> RollupBatch`, `sum_aggregate_cost_by_mission(mission_ids) -> dict[str, float]` (88.5.3). There is no `sum_run_cost` | 88.1.7, 88.4.1, 88.5.3 |
| `GateRequestRepository` (`repositories/gate_request.py`) | `get_for_mission(mission_id, gate_request_id)`, `lock_for_mission(mission_id, gate_request_id)`, `list_open(mission_ids)`, `has_undecided(mission_id)`, `list_decided_for_run(mission_run_id)`, `insert_if_absent(...)`, `mark_status(gate_request_id, status, now)` (guarded, 3.2.4), `close(gate_request_id, status, decision, now)`; 88.5.7 adds `pending_summary(mission_id, now, grace_seconds) -> PendingGateSummary` | 88.4.3 creates it with `has_undecided(mission_id) -> bool` and `cancel_undecided(mission_id) -> int`; 88.4.8 adds the other methods listed; 88.5.7 adds `pending_summary` |

`MissionRepository` gains `increment_run_sequence(mission_id) -> int` (88.1.4). `TaskRepository` gains `list_by_run(run_id, status=None)` (88.1.4). `WorkflowScheduleRepository` is deleted (88.1.3).

#### 3.5.3 API endpoints

All endpoints return `ApiResponse`. `require_mission_operator(db, mission_id, user)` in `core/dependencies.py` (88.0.9) loads the mission (404 if unknown) and raises `AuthorizationError("Mission operator role required")` unless `MissionService.is_operator` is true. Reads use `require_existing_mission_access`. Enum fields and query parameters use lowercase values (3.0.2).

| Method and path | Auth | Request | Response `data` | Step |
|---|---|---|---|---|
| `POST /missions` (changed) | current user | `MissionCreate` gains required `gate_mode: GateMode`; from 88.4.1 also optional `budget_per_run_usd`, `budget_per_month_usd`, `budget_lifetime_usd` (the first two default from `missions.budgets`) | `MissionResponse` | 88.1.0, 88.4.1 |
| `PATCH /missions/{id}/plan` (changed) | **operator** (was access) | gate mode and task order only; budget fields removed in 88.4.1, ending the layering break at `missions_plan.py:117-119` | plan | 88.0.9, 88.4.1 |
| `POST /missions/{id}/schedules` | operator | `MissionScheduleCreate{name, kind, objective_template?, workflow_definition_id?, workflow_parameters, cron_expression, time_zone_name, starts_at?, ends_at?, max_runs?, catch_up_window_seconds?}` | `MissionScheduleResponse` | 88.1.12 |
| `GET /missions/{id}/schedules?include_archived=` | access | none | `{schedules: [MissionScheduleResponse]}` | 88.1.12 |
| `GET /missions/{id}/schedules/{sid}` | access | none | `MissionScheduleResponse` (includes `next_fire_times[5]`, `temporal_sync_state`) | 88.1.12 |
| `PATCH /missions/{id}/schedules/{sid}` | operator | `MissionScheduleUpdate` (all optional; `kind` not allowed) | `MissionScheduleResponse` | 88.1.12 |
| `POST /missions/{id}/schedules/{sid}/pause` and `/resume` | operator | none | `MissionScheduleResponse` | 88.1.12 |
| `DELETE /missions/{id}/schedules/{sid}` | operator | none | `MissionScheduleResponse` (status `archived`) | 88.1.12 |
| `POST /missions/{id}/runs` | operator | `MissionRunCreate{objective: str}` | `MissionRunResponse` | 88.1.12 |
| `GET /missions/{id}/runs?status=&limit=&before_sequence=` | access | none; `status` repeats and takes `MissionRunStatus` values (`?status=running&status=failed`) | `{runs: [MissionRunResponse], next_before_sequence}` | 88.1.12 |
| `GET /missions/{id}/runs/{run_id_or_seq}` | access | none | `MissionRunDetailResponse{run, digest, tasks: [TaskSummary]}`; `gates: [GateRequestSummary]` added in 88.4.8, because `gate_requests.mission_run_id` arrives in `plan88_006` | 88.1.12, 88.4.8 |
| `GET /missions/{id}/runs/{run_id_or_seq}/live` | access | none | `MissionRunLiveStateResponse{run: MissionRunResponse, workflow_state: WorkflowStatusDescription or None, state: MissionRunWorkflowStatus or None}` | 88.5.8 |
| `GET /missions/{id}/runs/{run_id_or_seq}/history` | access | none | `MissionRunHistoryResponse{run: MissionRunResponse, still_running: bool, events: list[dict]}`; 404 "history expired" when Temporal no longer holds it | 88.5.8 |
| `POST /missions/{id}/runs/{run_id}/cancel` | operator | none | `MissionRunResponse` | 88.1.12 |
| `POST /missions/{id}/pause` | operator | none | `MissionResponse` | 88.4.5 |
| `POST /missions/{id}/resume` | operator | none | `MissionResponse` | 88.4.5 |
| `POST /missions/{id}/archive` and `/unarchive` | `require_mission_owner` | none | `MissionResponse` | 88.4.5 |
| `GET /missions/{id}/budget` | access | none | `BudgetStatusResponse{per_run_usd, per_month_usd, lifetime_usd, month_spent_usd, lifetime_spent_usd, active_run_spent_usd, breach}` | 88.4.1 |
| `PUT /missions/{id}/budget` | operator | `BudgetCapsUpdate{per_run_usd, per_month_usd, lifetime_usd: float or None}` | `BudgetStatusResponse` | 88.4.1 |
| `GET /missions/{id}/notification-recipients` | access | none | `{recipients: [...]}` | 88.4.4 |
| `POST /missions/{id}/notification-recipients` | owner | `NotificationRecipientCreate{user_email, channel, kinds?: list[NotificationKind]}` | `NotificationRecipientResponse{id, user_id, user_email, channel, kinds}` | 88.4.4 |
| `DELETE /missions/{id}/notification-recipients/{rid}` | owner | none | `{id}` | 88.4.4 |
| `GET /missions/{id}/gates/{gid}` | access | none | `GateRequestDetail` with `allowed_actions` | 88.0.13 |
| `POST /missions/{id}/gates/{gid}/decide` (changed) | **operator** (was access) | `GateDecisionSubmission{action, reason?}` | `{id, action, run_status}` | 88.0.13, 88.4.8 |
| `GET /gates/pending` (changed) | current user | none | statuses `pending`, `escalated`, `timed_out`, each `GateRequestSummary` with `mission_run_id`, `gate_point`, `escalate_at`, `pause_at`, `allowed_actions` | 88.4.8 |
| `GET /missions/health` | current user | none | `{missions: [MissionHealthResponse]}` | 88.5.7 |
| `GET /missions/{id}/health` | access | none | `MissionHealthResponse` | 88.5.7 |
| `POST /auth/me/channel-links/telegram` | current user | none | `{code, expires_at, bot_username}` | 88.4.9 |
| `GET /auth/me/channel-identities` | current user | none | `{identities: [{id, channel, external_id, external_username, verified, created_at}]}` | 88.4.9 |
| `POST /auth/me/channel-identities/{iid}/confirm` | current user | none | identity `{id, channel, external_id, external_username, verified, created_at}` | 88.4.9 |
| `DELETE /auth/me/channel-identities/{iid}` | current user | none | `{id}` | 88.4.9 |
| `POST /admin/schedules/sync` | `require_admin` | `{mission_id?}` | `ScheduleSyncStats`. For the web only; `admin.py` calls the service in-process and never this route | 88.1.12 |
| `POST /admin/reconcile/run` | `require_admin` | none | `ReconcileStats`. For the web only; `admin.py` calls the service in-process | 88.1.10a |
| `POST /admin/retention/run` | `require_admin` | `RetentionRunRequest{policy?}` | `{workflow_id}` | 88.5.4 |

**Rules:**
- **Decision channel.** It comes from `request.state.source`: `web` gives WEB, `cli` gives CLI, anything else gives API (see the `X-Frontend-ID` rule in 3.5).
- **Deleted endpoints:**
  - 88.0.9: the four unauthenticated routes at `api/v1/endpoints/workflows.py:90-221` (`POST /workflows/missions`, `GET /workflows/missions`, `GET /workflows/missions/{id}`, `POST /workflows/missions/{id}/cancel`).
  - 88.1.3: the workflow-schedule routes at `missions_workflows.py:622-735`.
  - 88.1.12: `POST /missions/{id}/plan/run-objective` (replaced by `POST /missions/{id}/runs`).
  - 88.2.6: `POST /executions/{id}/execute` and `POST /executions/{id}/approve`.
- **Changed endpoints:**
  - `POST /missions/{id}/plan/dispatch` stays, and from 88.1.9 calls `start_run(MANUAL, objective=None)`.
  - `POST /executions/{id}/cancel`: from 88.4.5, a record with `mission_run_id` delegates to `MissionRunService.cancel_run`; other records keep the 88.0.9 `ExecutionCancellationService` path.
  - The emergency stop at `api/v1/endpoints/admin.py:835` calls `MissionLifecycleService.pause_all_active` from 88.4.5.

**Telegram client** (`modules/clients/telegram`, inside the trust boundary):
- **Fail closed (88.0.14).** An empty `application.telegram.authorized_users` denies every update (`middlewares/auth.py:76-83` today admits everyone as admin). When Telegram is enabled, startup fails if `settings.telegram_webhook_secret` is empty, and the webhook route returns 403 when the `X-Telegram-Bot-Api-Secret-Token` header is missing or wrong (`webhook.py:58` today checks only when a secret is set). Tests `test_empty_allowlist_denies`, `test_webhook_without_secret_config_refuses_start`, `test_webhook_missing_header_403`.
- `callbacks/gate.py` (88.4.9): `GateActionCallback(CallbackData, prefix="g")` with fields `token: str` and `a: str`. The handler calls `GateDecisionService.decide_with_action_token`, then answers the callback and edits the message.
- `handlers/link.py` (88.4.9): `/link CODE` calls `ChannelIdentityService.redeem_link_code` with `from_user.id` and `from_user.username`, then replies that the user must confirm the link in the web or with `mc notify confirm`.
- Webhook debug logging drops `callback_query.data`, which carries raw action tokens (88.4.9).

#### 3.5.4 `mc` and `admin` CLI

| Command | Calls | Step |
|---|---|---|
| `mc mission create … --gate-mode MODE` (required; `manual`, `ai_assisted` or `autonomous`) | `POST /missions` | 88.1.0 |
| `mc mission create … [--budget-per-run X] [--budget-per-month Y] [--budget-lifetime Z]` | `POST /missions` | 88.4.1 |
| `mc schedule create NAME --cron EXPR --tz IANA (--objective TEXT or --workflow NAME [--param k=v]…) [--starts-at] [--ends-at] [--max-runs N] [--catch-up-window DURATION]` | `POST /missions/{id}/schedules`. `--workflow NAME` is resolved through `GET /missions/{id}/workflows` by exact `name` | 88.1.13 |
| `mc schedule list [--all]` / `show NAME` / `edit NAME [same flags]` / `pause NAME` / `resume NAME` / `delete NAME` | schedule endpoints | 88.1.13 |
| `mc runs list [--status S]… [--limit N]` / `show SEQ` / `digest SEQ` / `cancel SEQ` / `start --objective TEXT` | run endpoints. `--limit` is optional; when omitted the client sends `get_app_config().cli.mc.runs_list_limit`. `--status` takes lowercase values. The current WorkflowRun group (`mc runs`) is renamed `mc workflow-runs`, with no alias | 88.1.13; `digest` 88.3.8 |
| `mc runs live SEQ` | `GET /missions/{id}/runs/{seq}/live` | 88.5.8 |
| `mc run --objective TEXT [--dry-run]` | `POST /missions/{id}/runs` (the `--gate`, `--step` and `--budget` options are deleted) | 88.1.13 |
| `mc mission pause` / `resume` / `archive` / `unarchive` | lifecycle endpoints (archive and unarchive switch from PATCH to POST) | 88.4.5 |
| `mc mission health [--all]` | health endpoints (exit 3 unless every verdict is healthy, idle or paused) | 88.5.9 |
| `mc mission budget` / `mc mission set-budget --per-run X --per-month Y [--lifetime Z or --no-lifetime]` | budget endpoints (replaces the current `set-budget`) | 88.4.1 |
| `mc notify recipients list` / `add EMAIL [--kind K]…` / `remove EMAIL` | recipient endpoints | 88.4.4 |
| `mc notify link-telegram` / `confirm ID` / `identities` / `unlink ID` | `/auth/me/...`; `identities` and `confirm` show `external_username` | 88.4.9 |
| `mc gate decide GATE_ID --action A [--reason R]` (unchanged surface) | decide endpoint; actions rendered from `allowed_actions` | 88.4.8 |
| `admin reconcile run` / `admin schedules sync [--mission ID]` / `admin retention run [--policy P]` | the matching services, in-process (3.5 layering rule); no HTTP call to `/admin/schedules/sync` or `/admin/reconcile/run` | 88.1.10a, 88.1.13, 88.5.4 |
| `admin schedule …` (deleted) | replaced by `admin schedules sync` | 88.1.3 |
| `admin admin seed-catalog` | seeds `mission.digest.agent` (`python admin.py admin seed-catalog`) | 88.3.6 |

All new groups expose themselves in `tree` automatically through the existing introspection. Rendering uses `report.py` primitives.

#### 3.5.5 Shared backend modules

- **`core/redaction.py`** (88.1.6): `def redact_secrets(text: str) -> str`. It applies these patterns in this order:
  1. Telegram bot tokens matching `bot\d+:[A-Za-z0-9_-]+` become `"bot<redacted>"`.
  2. Raw action tokens in callback data matching `g:[A-Za-z0-9_-]{22}:` become `"g:<redacted>:"`.
  3. Provider keys matching `sk-ant-[A-Za-z0-9_-]+` or `sk-[A-Za-z0-9_-]{16,}` become `"sk-<redacted>"`.
  4. `Bearer\s+[A-Za-z0-9._~+/=-]+` becomes `"Bearer <redacted>"`.
  5. URL credentials matching `://[^/\s:@]+:[^/\s@]+@` become `"://<redacted>@"`.
  6. `(?i)\b([A-Z0-9_]*(?:api[_-]?key|token|secret|password|passwd|salt|credential))(["']?\s*[=:]\s*)["']?[^\s"',}]+` becomes `\1\2<redacted>`. It covers the platform's own `.env` names (`AZURE_OPENAI_API_KEY=…`) and `key: value` forms.
  7. `gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}` becomes `gh<redacted>`.
  8. `AKIA[0-9A-Z]{16}` becomes `AKIA<redacted>`.
  9. JWTs matching `eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}(\.[A-Za-z0-9_-]+)?` become `eyJ<redacted>`.
  10. Keys matching `(?:sk|pk|ak|rk)[-_](?:live|test|prod)[-_][A-Za-z0-9]{16,}` become `<redacted>`.

  Patterns 3 to 10 exist because 3.8 passes exception text through it (decision 15). It is the platform's only secret redactor: 88.2.3a deletes `agents/security/tool_runner._redact_secrets_in_text`, and `strip_secret_values` calls `redact_secrets`. It is applied to every stored `notification_deliveries.error`, `mission_schedules.temporal_sync_error`, `mission_runs.status_detail` and every event payload field that carries exception text (`NotificationDeliveryFailedEvent.error`, `MissionScheduleSyncFailedEvent.error`). Tests `test_redacts_bot_token`, `test_redacts_action_token`, `test_redacts_provider_key`, `test_redacts_bearer`, `test_redacts_url_credentials`, `test_redacts_key_value_secret`, `test_redacts_env_style_names` (every `NAME=` line of `config/.env.example` with a value, in `NAME=value` and `NAME: value` form), `test_redacts_github_token`, `test_redacts_aws_key`, `test_redacts_jwt` and `test_redacts_stripe_style_key` (88.1.6); `test_delivery_error_redacts_bot_token` (88.4.4). From 88.2.3b it is also applied to every field listed in 3.8.1 item 5.
- **`core/exceptions.py`** gains `MissionRunStateError(ApplicationError)` (88.1.2) and `RunStartRejectedError(ValidationError)` (88.1.7), which covers `INVALID_GATE_MODE` and the owner-not-user `START_FAILED`. Both are in `NON_RETRYABLE`. `BudgetExceededError` exists (`core/exceptions.py:73`). 88.2.3a adds `ExecutionEnvironmentError(ApplicationError)`, which is in `NON_RETRYABLE`. 88.2.3b defines `WorkflowStepFailedError(RuntimeError)`, carrying `failure: TaskFailure`, in `core/failure_classification.py`, beside its only consumer, so `core/exceptions.py` stays a leaf module. `WorkflowHaltedError(RuntimeError)`, carrying `reason`, lives in `tools/halt_workflow.py`, and `UpstreamOutputMissingError(KeyError)`, with `source_task` and `source_field`, lives in `agents/mission_control/dispatch/dag.py` (both 88.2.3b).

### 3.6 Event types and notification kinds

#### 3.6.1 Session events (`events/mission_run_types.py`, registered in `EVENT_TYPE_MAP` in `events/types.py:823`)

New event classes go in `events/mission_run_types.py`, because `events/types.py` is already 918 lines. 88.1.6 creates `events/base.py` (holding `SessionEvent`, moved from `events/types.py:31-41`) and `events/mission_run_types.py` unconditionally; later steps, 88.3.3 included, only add classes to `events/mission_run_types.py`, and `events/types.py` gains only their imports and `EVENT_TYPE_MAP` entries. Every new event carries `mission_id: str` and `mission_run_id: str | None`. Status and reason fields carry lowercase values (3.0.2).

| Class | `event_type` | Extra fields | Step |
|---|---|---|---|
| `MissionRunCreatedEvent` | `mission_run.created` | `sequence`, `trigger`, `schedule_id`, `scheduled_for` | 88.1.7 |
| `MissionRunStatusChangedEvent` | `mission_run.status_changed` | `from_status`, `to_status`, `reason`, `detail` | 88.1.7 |
| `MissionRunOccurrenceRecordedEvent` | `mission_run.occurrence_recorded` | `status` (`skipped` or `missed`), `reason`, `scheduled_for`, `count` | 88.1.6 |
| `MissionRunDigestWrittenEvent` | `mission_run.digest_written` | `digest_id`, `generator` | 88.3.7 |
| `MissionRunBudgetBreachedEvent` | `mission_run.budget_breached` | `cap` (MissionPauseReason value), `spent_usd`, `cap_usd` | 88.4.6 |
| `MissionLifecycleChangedEvent` | `mission.lifecycle_changed` | `from_status`, `to_status`, `paused_reason`, `actor_user_id` | 88.4.5 |
| `MissionScheduleChangedEvent` | `mission_schedule.changed` | `schedule_id`, `from_status`, `to_status`, `completed_reason` | 88.1.6 |
| `MissionScheduleSyncFailedEvent` | `mission_schedule.sync_failed` | `schedule_id`, `error` (redacted) | 88.1.6 |
| `GateRequestOpenedEvent` (changed) | `gate.request.opened` | add `mission_run_id`, `gate_point`, `escalate_at`, `pause_at`; drop `timeout_seconds` | 88.4.8 |
| `GateRequestEscalatedEvent` | `gate.request.escalated` | `request_id`, `gate_point` | 88.4.8 |
| `GateRequestTimedOutEvent` | `gate.request.timed_out` | `request_id`, `gate_point` | 88.4.8 |
| `GateRequestDecidedEvent` (changed) | `gate.request.decided` | add `mission_run_id`, `channel` | 88.4.8 |
| `ContextCompactedEvent` | `context.compacted` | `from_bytes`, `to_bytes`, `archived_paths` | 88.3.3 |
| `NotificationDeliveryFailedEvent` | `notification.delivery_failed` | `delivery_id`, `kind`, `channel`, `error` (redacted) | 88.4.4 |
| `TaskFailedEvent` | `task.failed` | `task_id`, `agent_name`, `origin`, `failure_class`, `fingerprint`, `summary` (redacted), `retryable` | 88.2.4 |

- **Context and digest events.** `ContextCompactedEvent` and `MissionRunDigestWrittenEvent` live in `events/mission_run_types.py` and are registered in `EVENT_TYPE_MAP` in `events/types.py`. `SessionEvent` moves to `events/base.py` (88.1.6), and every module imports it from there. `ContextCompactedEvent` is published only by the `compact_mission_context` activity, after commit.
- **Deleted (P3):** `MissionPlanDispatchedEvent` (`mission_plan.dispatched`, `events/types.py:517`) in 88.1.7 and `MissionPlanRunCompletedEvent` (`mission_plan.run.completed`, `:589`) in 88.1.8.
- **Kept:** `MissionPlanGateModeChangedEvent` (`mission_plan.gate_mode_changed`, `:507`), with `from_mode` and `to_mode` as `GateMode` values from 88.1.0.
- **Session id for run-scoped events:** `session_id` is the run's session.
- **Session id for mission- and schedule-scoped events:** `session_id = mission_id`, following the existing convention at `api/v1/endpoints/missions_gates.py:209`.

#### 3.6.2 Notification kinds (sent from 88.4.4)

| Kind | Fired by | Subject id | Telegram actions |
|---|---|---|---|
| `RUN_SUCCEEDED` | `finalise_mission_run` (SUCCEEDED) | run id | none |
| `RUN_FAILED` | `finalise_mission_run` (FAILED, or CANCELLED with a reason other than CANCELLED_BY_USER); reconciler | run id | none |
| `GATE_WAITING` | the workflow after `open_gate_request` (human required) | gate id | Approve / Reject when `inbound_approvals_enabled`, the recipient has a verified TELEGRAM identity and the recipient is an operator |
| `GATE_ESCALATED` | the workflow after `update_gate_request(escalated)` | gate id | same as `GATE_WAITING`, with fresh tokens |
| `GATE_TIMEOUT_PAUSED` | the workflow after `pause_mission_for_run(gate_timeout)` | gate id | same as `GATE_WAITING` |
| `BUDGET_PAUSED` | the workflow after a budget stop; the tick workflow from the claim result | run id, or `{schedule_id}:{scheduled_for}` when the pause came from a claim | none |
| `RUN_SKIPPED` | `claim_occurrence` | `{schedule_id}:{scheduled_for}` | none |
| `RUN_MISSED` | `claim_occurrence` (including backfill count) | `{schedule_id}:{scheduled_for}` | none |

Before 88.4.5, `FinaliseRunResult.notification` and the tick's notifications are built but only logged; 88.4.5 sends them under patch id `p88-lifecycle-signals`. The SSE channel `notify:mission:{mission_id}` still receives every kind for every mission, as it does today (`run_notifier.py:192-199`). The publish moves into `NotificationService.notify`.

### 3.7 OPEN items (implementer uses the stated default; no questions)

1. **Temporal server support for `ListScheduleMatchingTimes` and Workflow Update.** The dev machine reports `temporal version 1.6.2 (Server 1.30.2, UI 2.45.3)`, and CI pins `TEMPORAL_CLI_VERSION: "1.6.2"` (88.0.1) so the capability test runs against the same server. The SDK has the request type (`temporalio==1.20.0`). **Default:** 88.0.1 runs `temporal operator cluster describe` and `test_workflow_update_supported` (a probe workflow with an update handler and `execute_update`). If either RPC returns UNIMPLEMENTED, upgrade the local Temporal server. Never compute cron times locally, because croniter stays deleted. 88.0.1 also adds the Temporal test-server binary prefetch to CI.
2. **Workflow definitions with steps that have no agent capability** (human input, decision, raw LLM call). How they map to Tasks is undefined. **Default:** `create_schedule` and `plan_mission_run` reject such definitions with `ValidationError` naming the steps. Manual WorkflowRun execution of them is unchanged.
3. **Model for `mission.digest.agent`.** **Default:** the `quick` alias from `models.yaml`, declared in its `agent.yaml` and seeded with `python admin.py admin seed-catalog`. At runtime it changes only through `PATCH /admin/catalog/mission.digest.agent`.
4. **Telegram bot username for link instructions.** **Default:** read through `getMe` at bot startup and shown by `mc notify link-telegram`. It is not configured.

### 3.8 Task failure evidence and the execution boundary (decision 15)

An unattended run must be able to say why a task failed, in a form that code can route. Today it cannot: the reason is dropped, every failure looks the same, and a failed provisioning silently runs agents on the worker host. This section defines one failure contract that every failure path produces and every consumer reads.

**Scope.** Plan 88 builds the robust core only:
- **A fail-closed execution boundary.**
- **A typed failure record.** Its origin and class come from mechanical rules in code: exception types, traceback frame paths and explicit constructors.
- **Persistence and visibility.** The record is stored and shown to the supervisor, the Director and the Planning Agent.

Anything needed only to prove that a failure lies in the mission's target repository is deferred to the repair-loop plan (3.8.7).

#### 3.8.1 Principles

1. **Evidence before routing.** A failure that is not captured as typed data cannot be routed, deduplicated or repaired.
2. **Mechanical classification only.** No LLM classifies, and no config rule assigns an origin. Plan 88 uses the class for two things only: to stop retries that cannot succeed, and to inform the supervisor, the Director and the Planning Agent.
3. **Detect at durable boundaries.** Records are built from the task result and the exception at the activity boundary. The log-to-SSE bridge is a display channel (rule 014) and never a trigger.
4. **Fail closed.** No isolated workspace means no execution, not local execution (3.8.5).
5. **Bounded and redacted.**
   - **Bounds.** Sizes come from `failures.evidence` (3.4.9).
   - **Redaction.** `message` and `summary` pass through `core/redaction.redact_secrets` (88.1.6; patterns in 3.5.5) before they are stored, emitted or put in workflow history.
   - **Replay safety.** No workflow code branches on `failure_reason` or `summary`, because 88.2.9 redacts them in committed replay fixtures. Workflow branches read `failure_class` only.

#### 3.8.2 Types (`schemas/task_failure.py`, 88.2.3b)

```python
class FailureOrigin(str, enum.Enum):
    PLATFORM = "platform"          # the running platform: its code, its installed dependencies, its infrastructure
    PROVIDER = "provider"          # LLM provider error, already typed by classify_provider_error
    ENVIRONMENT = "environment"    # no isolated workspace could be provided (3.8.5)
    AGENT = "agent"                # the agent run itself: output contract, tool misuse, verification, timeout, reported failure
    UPSTREAM = "upstream"          # a dependency of this task failed or produced no output
    CONTROL = "control"            # stopped by the platform: cancellation, budget, run end, gate abort
    UNKNOWN = "unknown"


class FailureClass(str, enum.Enum):
    TRANSIENT_PROVIDER = "transient_provider"
    QUOTA_EXHAUSTED = "quota_exhausted"
    AGENT_CONTRACT = "agent_contract"
    AGENT_TOOL_ERROR = "agent_tool_error"
    AGENT_REPORTED_FAILURE = "agent_reported_failure"
    VERIFICATION_FAILED = "verification_failed"
    TIMEOUT = "timeout"
    UPSTREAM_BLOCKED = "upstream_blocked"
    PLATFORM_DEFECT = "platform_defect"
    PLATFORM_DEPENDENCY_MISSING = "platform_dependency_missing"
    PLATFORM_TRANSIENT = "platform_transient"
    ORPHANED = "orphaned"
    ENV_UNAVAILABLE = "env_unavailable"
    CANCELLED = "cancelled"
    BUDGET_EXCEEDED = "budget_exceeded"
    RUN_ABORTED = "run_aborted"
    UNKNOWN = "unknown"


class FailureEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exception_type: str | None
    message: str                   # redacted, cut to failures.evidence.max_message_chars
    traceback_tail: list[str]      # innermost failures.evidence.max_traceback_frames frames, each written as in 3.8.4
    module_name: str | None        # ModuleNotFoundError.name, when present


class TaskFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origin: FailureOrigin
    failure_class: FailureClass
    fingerprint: str               # 64 hex chars (3.8.4)
    summary: str                   # see below; becomes tasks.failure_reason and ExecuteTaskResult.failure_reason
    retryable: bool                # whether the same agent may retry inside the task (3.8.3)
    evidence: FailureEvidence
```

- **`summary`.** For classifier-built records it is `f"{failure_class.value}: {first line of the redacted message}"`, cut to `failures.evidence.max_summary_chars`. `control` uses its `summary` verbatim; `plan_invalid`, `agent_outcome` and `orphaned` use their `detail` verbatim; `roster_miss`, `upstream_blocked` and `verification_failed` use `f"{failure_class.value}: {agent_name or missing_ref}"`. `control(...)` therefore stores `"budget_exceeded"` and `"cancelled"` exactly.
- **`TaskResult.failure`.** `TaskResult` (`schemas/execution_outcome.py`) gains `failure: TaskFailure | None`. A model validator requires it when `status` is `FAILED` or `TIMEOUT`, and `None` otherwise.
- **Every failed result carries one.** Every construction whose status is or may be `FAILED` or `TIMEOUT` passes a `TaskFailure`. The 88.2.3b item 4 table assigns a constructor to each site. A direct construction keeps its own fields, such as spend and `verification_outcome`.
- **`failed_result`.** `failed_result(task, failure: TaskFailure, *, status: TaskStatus = TaskStatus.FAILED, retry_count=0, retry_history=None, execution_id="", cost_usd=0.0, token_usage=None, duration_seconds=0.0)` replaces `reason: str` (P3). It is the only failed-result builder: `research_loop._failed_result` is deleted, and the research loop passes its spend through these keywords.
- **`RetryHistoryEntry`** gains `failure_class: FailureClass | None`. It is stored in `execution_outcome_json`, and `task_attempts` gains no column.

#### 3.8.3 Classification (`core/failure_classification.py`, 88.2.3b)

`FailureClassifier(config: FailuresSchema, platform_modules_dir: Path)` is built once per process, from `get_app_config().failures` and `find_project_root() / "modules"` resolved with `realpath`. It does no I/O and imports nothing from `modules.backend.agents` or `modules.backend.tools`. All rules below are code, not config. The module also defines `WorkflowStepFailedError(RuntimeError)`, which carries a `TaskFailure`, and the constant `AGENT_TOOL_DIRS = ("backend/tools", "backend/agents/deps")`, which is resolved under `platform_modules_dir`.

**Explicit constructors**, for failures the platform decides without an exception:

| Constructor | Origin / class | Used for |
|---|---|---|
| `control(failure_class, summary)` | `CONTROL` / `CANCELLED`, `BUDGET_EXCEEDED` or `RUN_ABORTED` | Cancellation, gate abort (`"aborted at <gate> gate"`), budget stop, run end |
| `upstream_blocked(missing_ref, upstream_task_id)` | `UPSTREAM` / `UPSTREAM_BLOCKED` | `UpstreamOutputMissingError` from `resolve_upstream_inputs` |
| `roster_miss(agent_name)` | `PLATFORM` / `PLATFORM_DEFECT` | The agent is not on the roster |
| `plan_invalid(agent_name, detail)` | `AGENT` / `AGENT_CONTRACT` | The planner produced an unusable task, such as a missing `loop_config` |
| `agent_outcome(agent_name, detail)` | `AGENT` / `AGENT_REPORTED_FAILURE` | An agent or sub-run finished without raising but reported failure: an unconverged convergence loop, `success: False`, a non-dict result, a failed research decomposition, or a halted workflow step (`"workflow halted: <reason>"`) |
| `verification_failed(agent_name, verification_outcome)` | `AGENT` / `VERIFICATION_FAILED` | The verification retries are exhausted |
| `orphaned(detail)` | `PLATFORM` / `ORPHANED` | `finalise` with reason `ORPHANED_WORKFLOW_CLOSED` or `ORPHANED_WORKFLOW_NOT_FOUND` |

**`from_exception(exc)`.** The first match wins.

0. **`WorkflowStepFailedError`** (defined in this module): return its carried `failure` unchanged.
1. **`BudgetExceededError`**: `control(FailureClass.BUDGET_EXCEEDED, "budget_exceeded")`.
2. **Provider errors.** `from_exception` first applies `classify_provider_error(exc, provider="", model="")` for typing only, so every caller passes the raw exception. The function is idempotent on typed errors and uses `provider` and `model` only as labels. `QuotaExhaustedError` gives `PROVIDER`/`QUOTA_EXHAUSTED`. `RateLimitedError` or `TransientProviderError` give `PROVIDER`/`TRANSIENT_PROVIDER`.
3. **Contract errors.** `ContractViolationError`, pydantic `ValidationError`, `UnexpectedModelBehavior`, `IncompleteToolCall` or `UsageLimitExceeded` give `AGENT`/`AGENT_CONTRACT`. This tuple, `CONTRACT_ERRORS`, lives only in this module. The retry handler's `_CONTRACT_FAILURE_EXCEPTIONS` and `is_token_limit` are deleted (88.2.3b).
4. **`ExecutionEnvironmentError`** (88.2.3a): `ENVIRONMENT`/`ENV_UNAVAILABLE`.
5. **`TimeoutError`**: `AGENT`/`TIMEOUT`.
6. **Platform infrastructure.** `ExternalServiceError`, or a `DatabaseError` whose `__context__` is a `sqlalchemy.exc.OperationalError` or `InterfaceError`, gives `PLATFORM`/`PLATFORM_TRANSIENT`. Any other `DatabaseError`, such as a constraint violation (`services/base.py:117`), continues to step 8.
7. **Agent tool errors.** A `PermissionError`, `ValueError` or `TypeError` whose innermost non-skipped frame is under any of `AGENT_TOOL_DIRS` gives `AGENT`/`AGENT_TOOL_ERROR`. These are bad arguments or out-of-scope paths. Without this step an agent, or content steering it, could raise "platform defect" alarms on demand.
8. **Frame-path test.**
   - **Skipped frames.** A frame is skipped when its resolved file starts with `<frozen`. It is also skipped when the file lies under `sysconfig.get_paths()["stdlib"]` or `["platstdlib"]` but not under `["purelib"]`, `["platlib"]` or any `site.getsitepackages()` entry. Site-packages frames are never skipped: in this environment site-packages sits inside the stdlib directory.
   - **Platform origin.** If the innermost remaining frame resolves under `platform_modules_dir`, the origin is `PLATFORM`.
   - **Class.** A `ModuleNotFoundError` or `ImportError` whose missing top-level module is not `modules` gives `PLATFORM_DEPENDENCY_MISSING`. Anything else gives `PLATFORM_DEFECT`.
   - **Paths, not names.** The test uses resolved file paths, never module-name strings.
   - **Library exceptions.** An exception raised inside site-packages, such as SQLAlchemy, is not `PLATFORM` by this test.
9. **Fallback.** `UNKNOWN`/`UNKNOWN`.

**Retryability** is the only retry decision in the platform. The retry handler reads `TaskFailure.retryable` and nothing else (88.2.3b).
- **Provider errors:** `retryable = exc.retry_policy != "none"`, read from the typed `ProviderError` (`core/exceptions.py`). `retry_policy` is the single source for provider retryability.
- **Retryable classes:**
  - `PLATFORM_TRANSIENT`;
  - `AGENT_TOOL_ERROR`;
  - `TIMEOUT`.
- **Not retryable:** every other class. For `VERIFICATION_FAILED` this means the record is built only once the verification retries are exhausted.
- **Config-driven:** `UNKNOWN` follows `failures.unknown_retryable`, which keeps today's behaviour by default.

#### 3.8.4 Fingerprint

`sha256(f"{origin}|{failure_class}|{key}")`, in hex. The first row that applies wins, top to bottom.

| Case | `key` |
|---|---|
| `PLATFORM_DEPENDENCY_MISSING` | `FailureEvidence.module_name` |
| `UPSTREAM_BLOCKED` | the upstream task id |
| `VERIFICATION_FAILED` | the agent name plus the first failing tier and check name |
| `plan_invalid`, `agent_outcome`, `roster_miss` | the class plus the agent name (or `workflow:<name>`) |
| `control(...)`, `orphaned(...)` | the class only |
| Any other exception | The exception type plus one frame, written as `path.py:function`, with no line numbers. The frame is the innermost one under `platform_modules_dir`, with its path relative to that directory. If there is none, it is the innermost non-skipped frame, with its path relative to its `sys.path` entry (for example `sqlalchemy/orm/session.py`) |

One root cause in one wave gives one fingerprint. That is what lets the reviewer and the Director see "one broken import, six tasks" as one digest (3.8.6).

#### 3.8.5 Fail-closed execution boundary (88.2.3a)

**No fallback to local:**
- In `build_dispatch_runtime`, a non-local `execution_mode` without `mission_repo_root`, or any provisioning error, raises `ExecutionEnvironmentError`.
- A git-aware container handle whose `host_working_dir is None` is a provisioning failure.
- `_validate_mode` raises instead of returning `"local"`.
- `repo_root` never defaults to `find_project_root()`.
- `workflow_run_waves` passes `mission_repo_root` to `handle_mission`, and resolves dispatch parameters inside the step's `try`, so an environment error fails the step.
- `MissionService` rejects `execution_environment="worktree"` on create and update, because no worktree backend is registered.

**No host shell.** One helper runs commands in a handle, and nothing runs them on the host.
- **The helper.** `services/execution_environment.run_in_environment(handle, argv, *, timeout_seconds) -> CommandResult` runs a command through one cached `ExecutionEnvironmentService` with `ContainerBackend` registered (lazy import, because `container_backend` imports this module). A `None` handle raises `ExecutionEnvironmentError`.
- **Deleted, so that it is the only path:**
  - `LocalBackend`, its default registration, and the `mode == "local"` branch and default of `get_or_create_for_mission`. An unregistered mode raises `ExecutionEnvironmentError`.
  - `run_command._run_local` and `run_command._run_in_environment`.
  - `tool_runner`'s local branch, `_get_env_service` and `_run_via_environment_service`.
- **`run_command`** wraps `["sh", "-c", command]` and maps the result to its dict.
- **`run_tests`** declares `TOOL_DEF["deps"] = ["environment_handle"]` and runs the module constant argv `RUN_TESTS_ARGV` with `executions.run_tests_timeout_seconds` (3.4.10).
- **`tool_runner._run_tool_subprocess`** calls the helper.

**CLI engines.** `claude_code`, `codex` and `copilot` run as subprocesses on the worker host. A worktree only sets their working directory; it does not contain them. Until a later plan runs them inside the container (3.8.7):
- **`codex` and `copilot` are deleted.** That covers `execute_codex`, `execute_copilot` and their entries in the engine dicts of `helpers/agent_executor.py` and `chat_cli_handler.py`, because they write regardless of `scope.write`. `AgentConfigSchema._validate_engine` accepts only `pydantic_ai` and `claude_code`, with an error that names this section. The repair-loop plan restores them inside the container.
- **`execute_claude_code`** takes `environment_handle` in place of `working_dir`. It raises `ExecutionEnvironmentError` when `scope.write` is non-empty, or when the handle or its `host_working_dir` is `None`. Otherwise it runs with `cwd=host_working_dir`, `tools=["Read", "Grep", "Glob"]` and `setting_sources=[]`, so it loads no settings or hooks from the target repository.
- **`chat_cli_handler`** passes `environment_handle=None`, so CLI-engine chat raises until 3.8.7.
- **Every `find_project_root()` working-directory fallback** is deleted, in `cli_executor.py` and `chat_cli_handler.py`.

Host reads by a read-only `claude_code` session are not confined to the worktree. That risk is accepted and recorded (Phase 2 Risk 7). No catalog agent sets a non-default `engine` today, so none of these rules removes a capability in use.

**Write guard for `pydantic_ai` agents.** In `execute_agent`, after `effective_handle` is computed (`helpers/agent_executor.py:88-90`), an agent with a non-empty `scope.write` raises `ExecutionEnvironmentError` in either of these cases:
- `effective_handle` is `None`;
- `effective_handle.host_working_dir is None`.

The guard reads `effective_handle`, not `deps`, and uses no path containment, so an isolated worktree under the platform repository's `var/worktrees/` passes. File tools stay confined by `FileScope` under `host_working_dir`. Platform-tier and system-tier agents have no handle, so they can never write files.

**Effect at the baseline:**
- **The two write-capable agents.** `security.webapp.scanner` and `security.webapp.reporter` fail with `ENV_UNAVAILABLE` through the write guard in a local-mode mission, the default. In a container-mode mission they fail with `ENV_UNAVAILABLE` when provisioning fails.
- **Container workflow steps.** Steps such as `security.webapp-assessment` need `mission.repo_root` set.

#### 3.8.6 Who sees the failure record

| Consumer | What it receives | Step |
|---|---|---|
| `tasks` row | **Columns:** `failure_reason = summary` and `failure_origin`, `failure_class`, `failure_fingerprint`, all written as enum members (stored names).<br>**Single writer:** `TaskRepository.set_failure(task, failure: TaskFailure \| None)` is the only code that writes or clears the four columns; `None` clears all four. Its `task_executions` twin also sets `failure_json`.<br>**Callers:**<br>- `record`;<br>- `mark_cancelled` (`CANCELLED`);<br>- `MissionRunService.finalise`: `orphaned` for the two orphan reasons, otherwise `control(RUN_ABORTED, reason)`. The reconciler fails tasks only through `finalise`;<br>- `WorkflowRunService._fail_remaining_plan_tasks` and `workflow_run_waves._sync_plan_task_states`, from the step's `TaskFailure`, otherwise `control(RUN_ABORTED, error)`;<br>- 88.4.6 (`BUDGET_EXCEEDED`, through the classifier).<br>**Cleared by** `retry_task` and `resolve_failed("skip")`, with `set_failure(task, None)` | 88.2.4 |
| `task_executions` row | The same three columns and `failure_json`, one row per recorded attempt. The row survives retries. A cancelled attempt is recorded on `tasks` only | 88.2.4 |
| Mission event stream | `TaskFailedEvent` with `mission_id`, published at most once per failed attempt that reaches `record`, after it commits. The `task_executions` row is the durable record; the event is display only (rule 014) | 88.2.4 |
| Workflow | `ExecuteTaskResult.failure_origin`, `failure_class` and `failure_fingerprint`: strings only (P9), never the evidence | 88.2.4 |
| Post-run reviewer | `evaluate_post_run` adds `summary["failures"]` and `summary["failures_truncated"]`. `TaskRepository.failed_tasks_for_run(mission_run_id)` returns the run's FAILED rows ordered by `last_attempt_at, id`, and `MissionRunService` passes them to `digest_failures` (3.3.4) with cap `failures.supervisor.max_failure_digests`. The grouping rule exists once | 88.2.6 |
| Director's refine turn | `REFINE_PROMPT` lists the wave's `TaskFailureDigest`s, built by the same `digest_failures` over the wave's `ExecuteTaskResult`s with cap `RunConfigSnapshot.max_failure_digests` | 88.2.6 |
| Planning Agent | `materialize_task_states(plan)`: per task `{task_id, status, failure: {origin, failure_class, summary} or None}`. `_call_planning_agent` passes it as the keyword-only argument `task_states` to `prompt_builder._build_planning_prompt`, which renders it beside `current_plan`. It is never seeded into `PlanBuildingSession.tasks`, because `TaskDefinition` forbids extra keys. `materialize_plan_dict` is unchanged | 88.2.4a |
| Retention | `failure_json` is set to NULL with `output_data` after `task_outputs_days`. The three classification columns are kept permanently, as data for a later incident ledger (3.8.7) | 88.5.3 |

#### 3.8.7 Out of scope, and the attach point for later work

Deferred to the repair-loop plan, which needs them and can justify their surface:
- **Target attribution.** This covers `TARGET` origin and its classes, command evidence captured from tool calls, config signature rules, and a platform-run `tests_pass` check as the only trusted source of target evidence. A repair loop must reproduce a `TARGET` failure in a clean checkout before it acts.
- **Container-run CLI engines.** Until then, write-capable CLI agents stay blocked (3.8.5).
- **Repair machinery.** This covers diagnose-and-fix agents, a re-execution oracle, an incident ledger, a cross-mission breaker and runtime package installation.

Two hooks are left in place for that plan:
- **Attach point:** `MissionRunWorkflow._after_task`, for a result with `status == "failed"`, behind its own `workflow.patched` id, with a new action in the 3.3.6 vocabulary.
- **Ledger data:** `task_executions.failure_fingerprint` and its index.

**Plan 89 sandbox.** The sandbox uses this failure contract unchanged. Its builder agents need either the container-run CLI engines above or the `pydantic_ai` engine with file tools under a handle.
