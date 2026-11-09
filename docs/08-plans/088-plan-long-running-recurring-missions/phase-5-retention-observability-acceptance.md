## Phase 5: Retention, observability and endurance acceptance

This phase keeps a mission's data bounded over months, makes a weeks-long mission observable without reading logs, and proves the whole plan with a real 7-day hourly run, a 4-week weekly run and a compressed nightly CI variant. Retention runs as a Temporal system schedule. `llm_calls` older than 90 days roll into the daily aggregates table that 88.4.1 created, and the ledger still returns exact monthly and lifetime spend. Phase 5 closes when the evaluator script passes against both real runs.

Every file:line below was verified at `a28ca771`. Backend and config are identical to `9adaa69d`; the frontend lines cited here were re-checked at `a28ca771`. Code that earlier Plan 88 steps rewrite is cited by step and symbol, never by line.

**Entry criteria:**
- `git status --porcelain` lists no changes under `modules/`, `config/`, `tests/`, `requirements*.txt`, `pyproject.toml`, `mc.py`, `admin.py` or `services.py`. Uncommitted work in progress is committed or stashed first. If such work was committed after `a28ca771`, the implementer re-verifies the line citations in the files it touched (by symbol) before starting the phase.
- Phases 0 to 4 are merged to main. `python admin.py migrate current` reports `plan88_007`.
- These exist and are wired:
  - `MissionRunWorkflow` with the `get_run_state` query (88.1.8), `MissionScheduleTickWorkflow`, `ReconcilerWorkflow` running `reconcile_mission_runs` then `sync_mission_schedules` (88.1.10, 88.1.10a) and `RunReconciliationService`;
  - `temporal/activity_options.py` (`retry_policy`, `activity_kwargs`; 88.0.2), `temporal/config_snapshots.py` (`config_hash`, `policy_snapshot` from 88.0.2; `build_run_config_snapshot` and `build_tick_config_snapshot` from 88.1.5, with `build_run_config_snapshot` extended and `build_workflow_timeouts_snapshot` added by 88.2.2) and `temporal/workflow_gateway.py` (`TemporalWorkflowGateway`; 88.0.3, with `start_mission_run` from 88.1.7, `signal` from 88.1.9, `fetch_history` from 88.2.9 and `execute_update` from 88.4.8);
  - `temporal/system_schedules.py` with `_BUILDERS` and `register_system_schedules(gateway: TemporalScheduleGateway)` (88.1.10), where the `retention` key still maps to `DailyCleanupWorkflow`;
  - `LlmLedgerRepository.sum_cost` (88.1.7, over raw `llm_calls`), extended by 88.4.1 to add `llm_call_daily_aggregates`; `BudgetService` and the `LlmCallDailyAggregate` model (88.4.1, migration `plan88_004`);
  - `NotificationService`, `GateDecisionService`, `ActionTokenRepository.consume_siblings` (88.4.3), `GateRequestRepository` (`repositories/gate_request.py`, created by 88.4.3 with `has_undecided` and `cancel_undecided`; 88.4.8 adds `get_for_mission`, `lock_for_mission`, `list_open` and `list_decided_for_run`) and `modules/backend/core/redaction.py` with `redact_secrets(text)` (88.1.6).
- `grep -rn --exclude-dir=migrations "ScheduledMissionCheckWorkflow\|find_ready_plans\|dispatch_check_interval_seconds" modules config` returns nothing. The 1-second poller is gone (decision 13); dispatch is event-driven through `tasks_approved`.

Commit granularity: one commit per step, with the message prefix `Plan 88 Phase 5:`.

---

### 88.5.1 Durable Temporal dev server and namespace retention

**Files:**
- modify `config/settings/temporal.yaml`
- modify `modules/backend/core/config_schema.py`
- modify `modules/clients/service_manager/process_utils.py`
- modify `modules/clients/service_manager/dev_runner.py`
- modify `services.py`
- create `modules/backend/temporal/namespace_policy.py`
- modify `modules/backend/temporal/worker.py`

**Current state:**
- `services.py:123-135` and `modules/clients/service_manager/dev_runner.py:81-92` start `temporal server start-dev --port … --ui-port …` with no `--db-filename`. The dev server is in-memory. `dev_runner.py` also passes `--log-format pretty`.
- `services.py stop` kills the Temporal port at `services.py:269`. Every redeploy therefore destroys all schedules, run histories and queued ticks. A redeploy during the 7-day test would lose every run, which is exactly what decision 14 forbids.
- Namespace retention is never set. The dev-server default applies. The namespace stays as configured (`temporal.namespace: "default"`).

**Change:**
1. Append to `temporal.yaml`:
   ```yaml
   namespace_retention_days: 30
   dev_server:
     db_path: "var/temporal/dev-server.sqlite"
   ```
   In `config_schema.py`, add `class TemporalDevServerSchema(_StrictBase): db_path: str = Field(..., min_length=1)`. On `TemporalSchema`, add `namespace_retention_days: int = Field(..., ge=1, le=3650)` and `dev_server: TemporalDevServerSchema = Field(...)`.
   **Why 30 days:** Postgres is the source of truth, so Temporal history is only needed to debug recent runs and to capture replay fixtures. Thirty days covers the 4-week acceptance mission. Temporal Schedules are not subject to namespace retention.
2. In `process_utils.py`, add `def temporal_dev_server_argv() -> list[str]`. It imports `get_app_config` and `find_project_root` from `modules.backend.core.config` inside the function body (the same lazy-import pattern as `preflight.py:132`), creates the parent directory of the database file, and returns:
   ```python
   ["temporal", "server", "start-dev", "--port", str(TEMPORAL_PORT), "--ui-port", str(TEMPORAL_UI_PORT),
    "--db-filename", str(find_project_root() / get_app_config().temporal.dev_server.db_path)]
   ```
   Import `TEMPORAL_UI_PORT` from `constants.py`. `services.py:123-135` passes `temporal_dev_server_argv()` to `_spawn_detached`. `dev_runner.py:81-92` passes `temporal_dev_server_argv() + ["--log-format", "pretty"]`. Both inline lists are deleted (P3).
3. Create `namespace_policy.py`:
   ```python
   from google.protobuf.duration_pb2 import Duration
   from temporalio.api.namespace.v1 import NamespaceConfig
   from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest, UpdateNamespaceRequest
   from temporalio.client import Client

   from modules.backend.core.logging import get_logger

   logger = get_logger(__name__)


   async def ensure_namespace_retention(client: Client, namespace: str, retention_days: int) -> None:
       desc = await client.workflow_service.describe_namespace(DescribeNamespaceRequest(namespace=namespace))
       want = retention_days * 86400
       if desc.config.workflow_execution_retention_ttl.seconds == want:
           return
       await client.workflow_service.update_namespace(
           UpdateNamespaceRequest(
               namespace=namespace,
               config=NamespaceConfig(workflow_execution_retention_ttl=Duration(seconds=want)),
           )
       )
       logger.info(
           "temporal.namespace_retention_set",
           extra={"namespace": namespace, "retention_days": retention_days},
       )
   ```
   `UpdateNamespaceRequest` in `temporalio` 1.20.0 has no `update_mask` field; the server updates only the config fields that are set. RPC errors propagate, so the worker refuses to start with the wrong retention (P8).
4. In `worker.py` `start_worker`, call `await ensure_namespace_retention(client, config.namespace, config.namespace_retention_days)` immediately after `client = await get_temporal_client()` and before `Worker(...)`. 88.5.10 replaces the literal message with `LogEvent.TEMPORAL_NAMESPACE_RETENTION_SET.value`.

**Tests:**
- `tests/unit/backend/temporal/test_namespace_policy.py`:
  - `test_updates_when_retention_differs`: describe returns 86400s. Asserts `update_namespace` is called once with `config.workflow_execution_retention_ttl.seconds == 2592000`.
  - `test_noop_when_retention_matches`: asserts `update_namespace` is not called.
  - `test_rpc_error_propagates`: asserts `RPCError` is raised.
- `tests/unit/clients/test_service_manager_temporal_argv.py::test_argv_includes_db_filename_under_project_root`: asserts `--db-filename` is followed by an absolute path ending in `var/temporal/dev-server.sqlite`.

**Done when:**
1. Start a workflow, then run `python services.py stop && python services.py start`.
2. `temporal workflow list --limit 5` still lists that workflow.
3. `temporal operator namespace describe -n default` shows a retention of `720h0m0s`.

---

### 88.5.2 Retention indexes (`plan88_008`)

**Files:**
- create `modules/backend/migrations/versions/plan88_008_retention_indexes.py`

**Current state:**
- `llm_calls` (`models/llm_call.py:15-127`) has `ix_llm_calls_created_at` (`:127`). `llm_call_daily_aggregates` and its model exist since 88.4.1 (`plan88_004`).
- `mission_events` (`models/mission_event.py:16`) has no `created_at` index.
- `task_executions.completed_at` (`models/execution_record.py:321`) and `execution_records.completed_at` (`:147`) are unindexed.
- `mission_runs` (`plan88_002`) has no `ended_at` index. `notification_deliveries` (`plan88_007`) has only `(mission_id, created_at)`, which a global age purge cannot use.

**Change:**
1. **`plan88_008_retention_indexes`** (`revision = "plan88_008"`, `down_revision = "plan88_007"`). Inside `with op.get_context().autocommit_block():`, every index is created with `postgresql_concurrently=True`, because `mission_events` is the largest table:
   - `ix_mission_events_created_at` on `mission_events(created_at)`;
   - `ix_task_executions_completed_at` on `task_executions(completed_at)` with `postgresql_where=sa.text("output_data IS NOT NULL")`;
   - `ix_execution_records_completed_at` on `execution_records(completed_at)` with `postgresql_where=sa.text("execution_outcome_json IS NOT NULL OR planning_thinking_trace IS NOT NULL")`;
   - `ix_mission_runs_ended_at` on `mission_runs(ended_at)` with `postgresql_where=sa.text("ended_at IS NOT NULL")`;
   - `ix_notification_deliveries_created_at` on `notification_deliveries(created_at)`.

   `downgrade` drops all five inside the same autocommit block, concurrently. The migration does not call `get_app_config()`.

**Tests:**
- `tests/integration/backend/migrations/test_plan88_retention_migrations.py`:
  - `test_upgrade_downgrade_roundtrip`: upgrades to head, downgrades to `plan88_007`, then upgrades again, with no error.
  - `test_retention_indexes_exist`: queries `pg_indexes` for the five names.

**Done when:** `python admin.py migrate upgrade head` then `python admin.py migrate current` reports `plan88_008`, and the integration tests pass.

---

### 88.5.3 Retention service, ledger rollup and batching strategy

**Files:**
- create `config/settings/retention.yaml`
- modify `modules/backend/core/config_schema.py`
- modify `modules/backend/core/config.py`
- create `modules/backend/schemas/retention.py`
- create `modules/backend/repositories/retention.py`
- modify `modules/backend/repositories/llm_ledger.py` (`LlmLedgerRepository`, exists since 88.1.7; aggregates since 88.4.1)
- modify `modules/backend/services/budget.py`
- modify `modules/backend/services/token_economics.py`
- create `modules/backend/services/retention.py`
- create `modules/backend/temporal/retention_models.py` (`RetentionInput`, `RetentionResult`)
- modify `config/settings/executions.yaml`: delete the `retention_days` comment line (`:10`) and key (`:21`)
- modify `modules/backend/core/config_schema.py`: delete `ExecutionsSchema.retention_days` (`:307`)

**Current state:**
- Retention does not exist. `tasks/scheduled.py:20-48` `daily_cleanup(older_than_days=30)` ignores its argument and only purges `revoked_sessions`.
- `TokenEconomicsService.get_cost_by_mission` (`services/token_economics.py:119-135`) sums raw `llm_calls` only, so it would under-report after rollup.
- `LlmLedgerRepository.sum_cost` (88.4.1) already adds `llm_call_daily_aggregates` when `mission_run_id is None`. Nothing writes that table yet.
- `retention_days: int = 0` sits at `config_schema.py:307`, and `retention_days: 0` at `executions.yaml:21`.

**Change:**
1. **Config.** Create `retention.yaml` exactly as 3.4.5, plus:
   ```yaml
   lock_timeout_ms: 5000
   statement_timeout_ms: 60000
   activity: {start_to_close_seconds: 3600, heartbeat_timeout_seconds: 120, retry: {initial_interval_seconds: 30, backoff_coefficient: 2.0, maximum_interval_seconds: 300, maximum_attempts: 3}}
   ```
   Add `RetentionPoliciesSchema` and `RetentionSchema` from 3.4.6. `RetentionSchema` also gains `lock_timeout_ms: int = Field(..., ge=100)`, `statement_timeout_ms: int = Field(..., ge=1000)` and `activity: ActivityPolicySchema`.
   `AppConfig.__init__` loads it with `_load_validated(RetentionSchema, "retention.yaml")` (required) and exposes the `retention` property.
2. **Policy names.** In `schemas/retention.py`, define:
   ```python
   RetentionPolicyName = Literal[
       "llm_calls_raw", "task_outputs", "mission_events", "notification_deliveries", "action_tokens", "revoked_sessions"
   ]
   RETENTION_POLICIES: tuple[str, ...] = get_args(RetentionPolicyName)


   class RetentionRunRequest(BaseModel):
       policy: RetentionPolicyName | None = None
   ```
   `RETENTION_POLICIES` is also the execution order. `llm_calls_raw` runs first so that ledger rollup is never starved by a long event purge. `services/retention.py` imports both names from the schema module.
3. **Batch transaction rule (every policy except `revoked_sessions`).** Each batch is one transaction, driven by one helper in `RetentionService`:
   ```python
   LOCK_SQLSTATES = frozenset({"55P03", "57014"})  # lock_not_available, query_canceled


   async def _run_batched(
       self,
       policy: str,
       batch: Callable[[int], Awaitable[int]],
       batch_size: int,
       heartbeat: Callable[[dict], None],
   ) -> tuple[int, bool]:
       cfg = get_app_config().retention
       total = 0
       while True:
           try:
               await self.session.execute(text(f"SET LOCAL lock_timeout = '{cfg.lock_timeout_ms}ms'"))
               await self.session.execute(text(f"SET LOCAL statement_timeout = '{cfg.statement_timeout_ms}ms'"))
               n = await batch(batch_size)
               await self.session.commit()
           except DBAPIError as exc:
               await self.session.rollback()
               if exc.orig.sqlstate not in LOCK_SQLSTATES:
                   raise
               logger.warning("retention.batch_lock_timeout", extra={"policy": policy})
               return total, False
           total += n
           heartbeat({"policy": policy, "rows_affected": n})
           if n < batch_size:
               return total, True
   ```
   **Locking and stop rules:**
   - Every policy statement selects at most `:batch_size` ids with `ORDER BY … LIMIT :batch_size FOR UPDATE SKIP LOCKED`, so retention never waits on rows held by live writers.
   - The loop continues while a batch touched exactly `batch_size` rows.
   - A lock or statement timeout rolls back the batch and stops the policy for this night with `complete=False`. It does not raise. The next night resumes.

   Statements are issued with `sqlalchemy.text()`, so ORM `onupdate` never bumps `updated_at`. `DBAPIError` is `sqlalchemy.exc.DBAPIError`; with the asyncpg dialect its `orig.sqlstate` carries the Postgres error code.
4. **`llm_calls_raw`** (in `LlmLedgerRepository`):
   - `async def oldest_raw_day(self) -> date | None` returns `min(created_at)::date`.
   - `async def rollup_day(self, day: date, batch_size: int) -> RollupBatch` with `@dataclass class RollupBatch: rows_deleted: int; groups_upserted: int`:
   ```sql
   WITH batch AS (
     SELECT c.id FROM llm_calls c
     WHERE c.created_at >= :day_start AND c.created_at < :day_end
       AND NOT EXISTS (SELECT 1 FROM mission_runs r WHERE r.id = c.mission_run_id
                       AND r.status IN ('PENDING','RUNNING','AWAITING_GATE','PAUSED'))
     ORDER BY c.id LIMIT :batch_size FOR UPDATE OF c SKIP LOCKED),
   moved AS (
     DELETE FROM llm_calls c USING batch b WHERE c.id = b.id
     RETURNING c.mission_id, c.agent_name, c.model, c.provider, c.input_tokens, c.output_tokens,
               c.cache_read_tokens, c.cache_write_5m_tokens, c.cache_write_1h_tokens, c.thinking_tokens, c.cost_usd),
   ins AS (
     INSERT INTO llm_call_daily_aggregates (day, mission_id, agent_name, model, provider, call_count,
       input_tokens, output_tokens, cache_read_tokens, cache_write_5m_tokens, cache_write_1h_tokens,
       thinking_tokens, cost_usd, created_at)
     SELECT :day, mission_id, agent_name, model, provider, count(*), sum(input_tokens), sum(output_tokens),
            sum(cache_read_tokens), sum(cache_write_5m_tokens), sum(cache_write_1h_tokens),
            sum(thinking_tokens), sum(cost_usd), now()
     FROM moved GROUP BY mission_id, agent_name, model, provider
     ON CONFLICT ON CONSTRAINT uq_llm_daily DO UPDATE SET
       call_count = llm_call_daily_aggregates.call_count + EXCLUDED.call_count,
       input_tokens = llm_call_daily_aggregates.input_tokens + EXCLUDED.input_tokens,
       output_tokens = llm_call_daily_aggregates.output_tokens + EXCLUDED.output_tokens,
       cache_read_tokens = llm_call_daily_aggregates.cache_read_tokens + EXCLUDED.cache_read_tokens,
       cache_write_5m_tokens = llm_call_daily_aggregates.cache_write_5m_tokens + EXCLUDED.cache_write_5m_tokens,
       cache_write_1h_tokens = llm_call_daily_aggregates.cache_write_1h_tokens + EXCLUDED.cache_write_1h_tokens,
       thinking_tokens = llm_call_daily_aggregates.thinking_tokens + EXCLUDED.thinking_tokens,
       cost_usd = llm_call_daily_aggregates.cost_usd + EXCLUDED.cost_usd
     RETURNING 1)
   SELECT (SELECT count(*) FROM moved), (SELECT count(*) FROM ins);
   ```
   **Why this is exact.** The delete and the upsert share one transaction, so at every commit point `raw + aggregates` equals the original total. The `ON CONFLICT` target relies on `uq_llm_daily` being `NULLS NOT DISTINCT` (3.1.11), so rows with `mission_id IS NULL` merge.

   **Cutoff.** `cutoff_day = (utc_now() - timedelta(days=policies.llm_calls_raw_days)).date()`. The service iterates `day` from `oldest_raw_day()` to `cutoff_day - 1` inclusive, calling `_run_batched` per day. Only whole UTC days roll, so every UTC-calendar-month window stays exact. `rows_affected` is the sum of `rows_deleted`; `rows_aggregated` is the sum of `groups_upserted`.
5. **`LlmLedgerRepository.sum_cost` (modify, exists since 88.1.7, aggregates added by 88.4.1):**
   - When `mission_run_id` is given, it sums raw rows only (unchanged). Rows of active runs are never rolled (3.1.11), and terminal-run spend is `mission_runs.cost_usd`, which `finalise` writes (88.1.7).
   - Otherwise every non-None `since` and `until` must be exactly 00:00:00.000000 UTC, else it raises `ValueError("ledger window must be UTC day-aligned")`. The aggregate term (`day >= since::date AND day < until::date`, each bound omitted when None) is unchanged.
   - `BudgetService` passes `since=None, until=None` for lifetime spend and the aligned `month_start`/`month_end` for the month (88.4.1). Change any other `sum_cost` call without `mission_run_id` in `services/budget.py` to one of these two forms.
   - Add `async def sum_aggregate_cost_by_mission(self, mission_ids: list[str]) -> dict[str, float]`. `TokenEconomicsService.get_cost_by_mission` adds it to the raw sum. Breakdown views (`get_token_breakdown`, `get_cache_performance`, `get_expensive_calls`) stay raw-only, and their docstrings state "last `llm_calls_raw_days` days".
6. **`task_outputs`** (`RetentionRepository.null_task_outputs(cutoff, batch_size) -> int`). One batch runs three statements and returns their summed rowcount. Terminal run names are `('SUCCEEDED','FAILED','CANCELLED','BUDGET_STOPPED','SKIPPED','MISSED')`.
   - `UPDATE task_executions SET output_data = NULL, failure_json = NULL WHERE id IN (SELECT te.id FROM task_executions te LEFT JOIN mission_runs r ON r.id = te.mission_run_id WHERE (te.output_data IS NOT NULL OR te.failure_json IS NOT NULL) AND te.completed_at < :cutoff AND (te.mission_run_id IS NULL OR r.status IN ('SUCCEEDED','FAILED','CANCELLED','BUDGET_STOPPED','SKIPPED','MISSED')) ORDER BY te.completed_at LIMIT :batch_size FOR UPDATE OF te SKIP LOCKED)`
   - `UPDATE execution_records SET execution_outcome_json = NULL, planning_thinking_trace = NULL WHERE id IN (SELECT id FROM execution_records WHERE completed_at < :cutoff AND (execution_outcome_json IS NOT NULL OR planning_thinking_trace IS NOT NULL) ORDER BY completed_at LIMIT :batch_size FOR UPDATE SKIP LOCKED)`
   - `UPDATE tasks SET result_summary = NULL WHERE id IN (SELECT t.id FROM tasks t LEFT JOIN mission_runs r ON r.id = t.mission_run_id WHERE t.result_summary IS NOT NULL AND ((r.ended_at IS NOT NULL AND r.ended_at < :cutoff) OR (t.mission_run_id IS NULL AND t.status IN ('COMPLETED','FAILED','SKIPPED','CANCELLED') AND t.updated_at < :cutoff)) LIMIT :batch_size FOR UPDATE OF t SKIP LOCKED)`

   `cutoff = utc_now() - timedelta(days=policies.task_outputs_days)`. `failure_json` (decision 15) holds the redacted exception message and traceback frames, so it follows `output_data`. `failure_origin`, `failure_class` and `failure_fingerprint` are never nulled, because they are the data for a later incident ledger (contracts 3.8.7). The task-outputs retention test also asserts that an old FAILED row has `failure_json IS NULL` and a non-NULL `failure_fingerprint`.
7. **`mission_events`** ("raw persisted session events" in 3.4.5 is the `mission_events` table, `models/mission_event.py:16`; `session_messages` is kept): `DELETE FROM mission_events WHERE id IN (SELECT id FROM mission_events WHERE created_at < :cutoff ORDER BY created_at LIMIT :batch_size FOR UPDATE SKIP LOCKED)`, with `cutoff = utc_now() - timedelta(days=policies.mission_events_days)`.
8. **`notification_deliveries`:** the same shape as `mission_events`, on `created_at`, with `policies.notification_deliveries_days`.
9. **`action_tokens`:** the same shape, on `expires_at < now() - make_interval(days => :d)` with `:d = policies.action_tokens_days_after_expiry`, whether consumed or not.
10. **`revoked_sessions`:** one call to `AuthService(session).purge_expired_revocations()` (`services/auth.py:176`). `rows_affected` is its return value and `complete=True`.
11. **Service:**
    ```python
    @dataclass
    class RetentionResult:
        policy: str
        rows_affected: int
        rows_aggregated: int
        complete: bool
        duration_seconds: float


    class RetentionService(BaseService):
        async def run_policy(
            self, policy: str, batch_size: int, heartbeat: Callable[[dict], None]
        ) -> RetentionResult:
            """ValidationError when policy is not in RETENTION_POLICIES; ConflictError when retention.enabled is false."""

        async def trigger(self, policy: str | None) -> str:
            """Starts RetentionWorkflow and returns its workflow id; ConflictError when retention.enabled is false."""


    def build_retention_input(config: AppConfig) -> RetentionInput:
        """The only place RetentionInput is built."""
    ```
    `run_policy` logs `retention.policy_completed` with every `RetentionResult` field. `RetentionResult` and `RetentionInput` live in `temporal/retention_models.py` (88.5.4); this step creates that module with both dataclasses and 88.5.4 adds `RetentionPolicyInput` to it.

**Tests:**
- `tests/integration/backend/services/test_retention_ledger.py`:
  - `test_rollup_preserves_month_total`: seeds 3 days of `llm_calls` 100 days old across two missions. Records `BudgetService.get_status().month_spent_usd` and `lifetime_spent_usd` for windows covering them, runs `run_policy("llm_calls_raw", 2, heartbeat=lambda d: None)`, and asserts both figures are equal to 6 decimal places.
  - `test_rollup_skips_active_run_rows`: rows linked to a `RUNNING` run that are 100 days old remain raw.
  - `test_rollup_idempotent_upsert`: two partial batches for the same day produce one aggregate row whose `call_count` equals the total.
  - `test_rollup_merges_null_mission_rows`: two batches of rows with `mission_id=NULL` and an identical key produce one aggregate row.
  - `test_rollup_only_whole_days_before_cutoff`: rows from `cutoff_day` are not rolled.
  - `test_sum_cost_rejects_unaligned_window`: raises `ValueError`.
  - `test_cost_by_mission_includes_aggregates`.
- `tests/integration/backend/services/test_retention_policies.py`:
  - `test_mission_events_deleted_before_cutoff_only`.
  - `test_task_outputs_nulled_for_terminal_runs_only`: the outputs of a task in a `PAUSED` run that is 100 days old remain.
  - `test_task_outputs_keep_rows`: row counts are unchanged.
  - `test_retention_does_not_touch_kept_tables`: counts of `mission_runs`, `mission_run_digests`, `gate_requests`, `context_changes`, `mission_decisions`, `mission_learnings`, `llm_call_daily_aggregates` (outside the rollup) and `session_messages` are unchanged.
  - `test_action_tokens_deleted_after_expiry_grace`.
  - `test_lock_timeout_returns_incomplete`: a second connection holds `ACCESS EXCLUSIVE` on `mission_events`, and the result is asserted `complete=False` with no exception.
  - `test_unknown_policy_raises`.
  - `test_disabled_raises_conflict`.
- `tests/unit/backend/core/test_config_retention.py`:
  - `test_retention_yaml_required`: a missing file raises.
  - `test_executions_retention_days_removed`: `"retention_days" not in ExecutionsSchema.model_fields`.
  - `test_policy_literal_matches_policies_table`: `set(RETENTION_POLICIES)` equals the six names, in the order given in item 2.

**Done when:**
- All of the tests above pass.
- `grep -n "retention_days" config/settings/executions.yaml` and `grep -n "retention_days: int = 0" modules/backend/core/config_schema.py` both return nothing.

---

### 88.5.4 RetentionWorkflow, system schedule and admin trigger

**Files:**
- modify `modules/backend/temporal/retention_models.py` (created in 88.5.3)
- create `modules/backend/temporal/retention_workflow.py`
- create `modules/backend/temporal/retention_activities.py`
- modify `modules/backend/temporal/worker.py`
- modify `modules/backend/temporal/system_schedules.py` (exists since 88.0.10, rewritten in 88.1.10)
- modify `modules/backend/temporal/maintenance_workflow.py`
- modify `modules/backend/temporal/maintenance_activities.py`
- modify `modules/backend/tasks/scheduled.py`
- modify `tests/unit/backend/tasks/test_scheduled_tasks.py`
- modify `modules/backend/temporal/workflow_gateway.py` (`TemporalWorkflowGateway`, exists since 88.0.3)
- modify `modules/backend/api/v1/endpoints/admin.py`
- create `modules/clients/cli/admin_groups/retention.py`
- modify `admin.py` (registers the `retention` group)

**Current state:**
- `DailyCleanupWorkflow` is at `maintenance_workflow.py:21-31` and `run_daily_cleanup` at `maintenance_activities.py:27-41`.
- `daily_cleanup` is at `tasks/scheduled.py:20-48`.
- The worker imports and registers both (`worker.py` imports at `:40,48` and registration lists).
- `_BUILDERS["retention"]` returns `(DailyCleanupWorkflow.run, None)` (88.1.10).
- `test_scheduled_tasks.py` tests `daily_cleanup`: the import at `:15`, the `purge` fixture at `:22-36` and `class TestDailyCleanup` at `:39-74`.

**Change:**
1. **Input models.** `retention_models.py`:
   ```python
   @dataclass(frozen=True)
   class RetentionInput:
       config_hash: str
       policies: list[str]
       batch_size: int
       activity: ActivityPolicySnapshot


   @dataclass(frozen=True)
   class RetentionPolicyInput:
       policy: str
       batch_size: int
   ```
   `build_retention_input` sets `policies=list(RETENTION_POLICIES)`, `batch_size=config.retention.batch_size`, `activity=policy_snapshot(config.retention.activity)` and `config_hash=config_hash(...)` over the other fields, using the helpers in `temporal/config_snapshots.py`.
2. **Workflow.** `retention_workflow.py`:
   ```python
   from temporalio import workflow
   from temporalio.exceptions import ActivityError, ApplicationError

   with workflow.unsafe.imports_passed_through():
       from modules.backend.core.log_events import LogEvent
       from modules.backend.temporal.activity_options import activity_kwargs
       from modules.backend.temporal.retention_activities import run_retention_policy
       from modules.backend.temporal.retention_models import RetentionInput, RetentionPolicyInput, RetentionResult


   @workflow.defn
   class RetentionWorkflow:
       @workflow.run
       async def run(self, inp: RetentionInput) -> list[RetentionResult]:
           results: list[RetentionResult] = []
           failed: list[str] = []
           for policy in inp.policies:
               try:
                   results.append(
                       await workflow.execute_activity(
                           run_retention_policy,
                           RetentionPolicyInput(policy, inp.batch_size),
                           **activity_kwargs(inp.activity),
                       )
                   )
               except ActivityError:
                   failed.append(policy)
                   workflow.logger.error(LogEvent.RETENTION_POLICY_FAILED.value, extra={"policy": policy})
           if failed:
               raise ApplicationError(f"RETENTION_POLICY_FAILED:{','.join(failed)}", non_retryable=True)
           return results
   ```
   One failing policy does not block the others. The workflow still closes FAILED, so health and the Temporal UI show it. `LogEvent` arrives in 88.5.10; until that commit, this line uses the literal `"retention.policy_failed"` and the import is absent.
3. **Activity.** `retention_activities.py`: `@activity.defn async def run_retention_policy(inp: RetentionPolicyInput) -> RetentionResult`. It opens `get_async_session()`, calls `RetentionService(session).run_policy(inp.policy, inp.batch_size, heartbeat=activity.heartbeat)`, and raises on any exception.
4. **System schedule.** In `system_schedules.py`:
   - `_BUILDERS["retention"]` becomes `_retention_action`, with `def _retention_action(temporal: "TemporalSchema") -> tuple[Callable[..., Any], RetentionInput]: return RetentionWorkflow.run, build_retention_input(get_app_config())`.
   - `register_system_schedules` passes `state=ScheduleState(paused=True, note="retention.enabled=false")` in the `Schedule` for key `retention` when `get_app_config().retention.enabled` is false, and `state=ScheduleState(paused=False)` for every other case.

   Registration is create-or-update, so a config change takes effect on worker restart.
5. **Delete (P3):**
   - `DailyCleanupWorkflow`, `run_daily_cleanup` and `tasks/scheduled.daily_cleanup`;
   - their imports and registrations in `worker.py`;
   - in `test_scheduled_tasks.py`: the `daily_cleanup` import (`:15`), the `purge` fixture (`:22-36`) and `class TestDailyCleanup` (`:39-74`).

   Register `RetentionWorkflow` and `run_retention_policy` in `worker.py`.
6. **Admin trigger.** Add `POST /admin/retention/run` (`require_admin`) in `admin.py`. The body is `RetentionRunRequest` (88.5.3), so an unknown policy is rejected with 422 by validation. The handler calls `RetentionService(db).trigger(body.policy)`, which:
   - raises `ConflictError("retention disabled")` when `retention.enabled` is false;
   - starts `RetentionWorkflow` through `TemporalWorkflowGateway.start_retention(inp: RetentionInput, workflow_id: str) -> None`, a method this step adds (`client.start_workflow` with `id_reuse_policy=REJECT_DUPLICATE` on `temporal.task_queue`; `RPCError` becomes `ExternalServiceError`), with id `f"system-retention-manual-{utc_now():%Y%m%dT%H%M%S}-{uuid4().hex[:8]}"` and `build_retention_input(get_app_config())`, with `policies=[policy]` (through `dataclasses.replace`, then recomputing `config_hash`) when `policy` is given;
   - returns the workflow id.

   The route returns `ApiResponse(data={"workflow_id": workflow_id})`.

   CLI: `modules/clients/cli/admin_groups/retention.py` defines `@click.group("retention")` with the command `run [--policy P]`, registered in `admin.py` with `admin_cli.add_command(retention)` (`python admin.py retention run`), a root group alongside `reconcile` and `schedules`. It calls `RetentionService(session).trigger(policy)` in-process, as `python admin.py reconcile run` and `python admin.py schedules sync` do (contracts 3.0.2), and prints the id through `report.py`. The HTTP route serves the web.

**Tests:**
- `tests/unit/backend/temporal/test_retention_workflow.py`, using `WorkflowEnvironment.start_time_skipping()` and mocked activities:
  - `test_runs_policies_in_order`;
  - `test_continues_after_policy_failure_then_fails`, which asserts the remaining policies ran and the workflow raised `RETENTION_POLICY_FAILED:mission_events`;
  - `test_activity_options_from_snapshot`: the stub activity reads `activity.info().heartbeat_timeout == timedelta(seconds=120)` and `start_to_close_timeout == timedelta(seconds=3600)`.
- `tests/unit/backend/services/test_build_retention_input.py`:
  - `test_policies_match_tuple_order`;
  - `test_config_hash_stable`.
- `tests/unit/backend/temporal/test_system_schedules.py` (extend): `test_retention_maps_to_retention_workflow` and `test_retention_paused_when_disabled`.
- `tests/integration/backend/api/test_admin_retention.py`:
  - `test_non_admin_forbidden`;
  - `test_unknown_policy_422`;
  - `test_disabled_409`;
  - `test_returns_workflow_id_envelope`, with `TemporalWorkflowGateway` mocked.
- `tests/unit/backend/temporal/test_workflow_gateway.py` (extend): `test_start_retention_rejects_duplicate_id`.

**Done when:**
- `temporal schedule describe --schedule-id system-retention` shows action `RetentionWorkflow` and cron `30 2 * * *`.
- `python admin.py retention run --policy revoked_sessions` produces a COMPLETED workflow.
- `grep -rn --exclude-dir=migrations "DailyCleanupWorkflow\|run_daily_cleanup\|def daily_cleanup" modules tests` returns nothing.
- `rg -n "start_workflow|get_workflow_handle" modules --glob '!modules/backend/migrations/**' --glob '!modules/backend/temporal/workflow_gateway.py' --glob '!modules/backend/temporal/schedule_gateway.py' | rg -i "MissionRun|MissionTick|MissionScheduleTick|Reconciler|Retention|mission_run_workflow_id"` returns nothing.

---

### 88.5.5 Health checks for Temporal and the worker

**Files:**
- modify `config/settings/temporal.yaml`
- modify `modules/backend/core/config_schema.py`
- modify `modules/backend/api/health.py`
- modify `modules/backend/services/health.py`
- modify `modules/backend/tasks/scheduled.py`
- modify `modules/clients/cli/admin_groups/admin_ops.py` (the `admin health` help text)

**Current state:**
- `api/health.py` checks only the database (`check_database`, `:24`) and Redis (`check_redis`, `:64`).
- Readiness is at `:112-167` and detailed health at `:170-230`.
- `HealthCheckService.check_readiness` (`services/health.py:43-72`) checks the database and Redis only. It backs `POST /admin/system/health` (`endpoints/admin.py:670-691`), which the web admin health page uses (`modules/frontend/src/hooks/use-admin.ts:164`).
- `hourly_health_check` (`tasks/scheduled.py:51-86`) duplicates the gather.
- `python admin.py admin health` describes itself as "Run system health check (database, Redis)".
- `services/health.py` imports `check_database` and `check_redis` from `api/health.py`, a layering inversion that predates Plan 88. This step follows the existing pattern; see Risk 6.

**Change:**
1. **Config.** `temporal.yaml` adds `health: {probe_timeout_seconds: 3, worker_poller_stale_seconds: 120}`. The schema adds `class TemporalHealthSchema(_StrictBase)` with `probe_timeout_seconds: int = Field(..., ge=1)` and `worker_poller_stale_seconds: int = Field(..., ge=30)`, and `TemporalSchema` gains `health: TemporalHealthSchema = Field(...)`.
2. **`check_temporal()` in `api/health.py`.** It returns `{"status": "not_configured"}` when `temporal.enabled` is false. Otherwise it runs `asyncio.wait_for(client.workflow_service.describe_namespace(DescribeNamespaceRequest(namespace=cfg.namespace)), timeout=cfg.health.probe_timeout_seconds)`. On success it returns `{"status": "healthy", "latency_ms": latency_ms, "namespace": cfg.namespace, "retention_days": ttl_seconds // 86400}`. Any exception gives `{"status": "unhealthy", "error": str(exc)}`.
3. **`check_worker()` in `api/health.py`.** It calls `describe_task_queue` with `TaskQueue(name=cfg.task_queue)` for `TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW` and for `TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY`, each under the same `probe_timeout_seconds`.
   - **Healthy** only when each type has at least one poller with `last_access_time >= utc_now() - timedelta(seconds=cfg.health.worker_poller_stale_seconds)`. It then returns `{"status": "healthy", "workflow_pollers": n, "activity_pollers": m, "identities": sorted_identities}`.
   - **Unhealthy** otherwise, with `"error": "no live workflow pollers"` or `"error": "no live activity pollers"`. A probe exception gives `{"status": "unhealthy", "error": str(exc)}`.
4. **Wiring:**
   - `readiness_check` adds `check_temporal` only, because the API cannot start runs without Temporal. The worker is left out so that worker restarts do not flap API readiness.
   - `detailed_health_check` and `HealthCheckService.check_readiness` add both, so the web admin page, `python admin.py admin health` and `mc` show `temporal` and `worker`. Update the `admin health` help text to "Run system health check (database, Redis, Temporal, worker)".
   - `hourly_health_check` is replaced by a call to `HealthCheckService().check_readiness()`. It logs `health.component_unhealthy` at ERROR per unhealthy component with `{component, error}`.

**Tests:**
- `tests/unit/backend/api/test_health_temporal.py`:
  - `test_check_temporal_healthy`;
  - `test_check_temporal_timeout_unhealthy`;
  - `test_check_temporal_not_configured_when_disabled`;
  - `test_check_worker_live_pollers_healthy`;
  - `test_check_worker_no_activity_pollers_unhealthy`;
  - `test_check_worker_stale_poller_unhealthy`;
  - `test_readiness_includes_temporal_excludes_worker`.
- `tests/unit/backend/services/test_health_service.py::test_check_readiness_reports_temporal_and_worker`.
- `tests/unit/backend/tasks/test_scheduled_tasks.py::test_hourly_health_check_logs_unhealthy_component`, which replaces `class TestHourlyHealthCheck` (`:77-97`).

**Done when:**
- With all services up, `curl -s http://127.0.0.1:$(python -c 'from modules.clients.service_manager.constants import BACKEND_PORT as p; print(p)')/health/detailed | jq -r '.checks.temporal.status, .checks.worker.status'` prints `healthy` twice.
- After `pkill -f modules.backend.temporal.worker` and 130 seconds, the worker check prints `unhealthy`.

---

### 88.5.6 Stale-gate sweep in the reconciler

**Files:**
- modify `modules/backend/services/run_reconciliation.py`
- modify `modules/backend/temporal/reconciler_activities.py`
- modify `modules/backend/temporal/mission_run_models.py` (`ReconcileStats`, exists since 88.0.10: `left_in_process` and `schedule_sync: ScheduleSyncStats | None` since 88.0.10, with `schedule_sync` filled from 88.1.10; `examined_mission_runs` and `failed_mission_runs` since 88.1.10a)

**Current state:**
- `RunReconciliationService.reconcile` fails orphaned `mission_runs` (88.1.10a).
- Nothing reconciles `gate_requests` left undecided after their run is terminal. Nothing detects a durable-gate timer that did not fire.
- `ActionTokenRepository.consume_siblings(gate_request_id, now)` exists since 88.4.3.

**Change:**
1. Add `async def sweep_gates(self, orphan_grace_seconds: int) -> GateSweepStats`, with `@dataclass class GateSweepStats: cancelled: int; overdue: int`. It runs two passes.
2. **(a) Cancel.** `UPDATE gate_requests g SET status='CANCELLED' FROM mission_runs r WHERE r.id = g.mission_run_id AND g.status IN ('PENDING','ESCALATED','TIMED_OUT') AND r.status IN ('SUCCEEDED','FAILED','CANCELLED','BUDGET_STOPPED','SKIPPED','MISSED') RETURNING g.id, g.mission_run_id`. For each id, `ActionTokenRepository.consume_siblings(gate_id, now)` invalidates outstanding Telegram buttons, and the sweep logs `gate.swept_cancelled` with `{gate_request_id, mission_run_id}`. It commits once.
3. **(b) Detect overdue, read-only.** It selects gates where `((g.status='PENDING' AND g.escalate_at < :now - :grace) OR (g.status IN ('PENDING','ESCALATED') AND g.pause_at < :now - :grace))` and the run status is `AWAITING_GATE`. For each, it logs `gate.timer_overdue` at ERROR with `{gate_request_id, mission_run_id, gate_point, escalate_at, pause_at}`.

   It does not mutate these rows. The workflow owns gate transitions, so writing from outside would race the timer. Visibility comes from health (88.5.7).
4. `reconcile_mission_runs` calls `reconcile(...)` and then `sweep_gates(...)` with the same `orphan_grace_seconds`. `ReconcileStats` gains `gates_cancelled: int` and `gates_overdue: int`. The activity logs `reconciler.completed` with `gates_cancelled`, `gates_overdue` and `stats` (`dataclasses.asdict(stats)`).

**Tests:**
- `tests/integration/backend/services/test_run_reconciliation_gates.py`:
  - `test_sweep_cancels_undecided_gate_of_terminal_run`;
  - `test_sweep_consumes_sibling_action_tokens`;
  - `test_sweep_flags_overdue_without_mutation`, which asserts the status is unchanged and the log was emitted;
  - `test_sweep_leaves_timed_out_gate_of_paused_run`;
  - `test_sweep_is_idempotent`, where a second call returns `cancelled=0`.

**Done when:** these tests pass, and a `reconciler.completed` log line in `logs/system.jsonl` contains `gates_cancelled` and `gates_overdue`.

---

### 88.5.7 Per-mission health service and API

**Files:**
- modify `config/settings/missions.yaml`
- modify `modules/backend/core/config_schema.py`
- create `modules/backend/schemas/mission_health.py`
- create `modules/backend/services/mission_health.py`
- modify `modules/backend/repositories/mission_run.py`
- modify `modules/backend/repositories/gate_request.py` (`GateRequestRepository`, exists since 88.4.3)
- modify `modules/backend/api/v1/endpoints/missions.py`

**Current state:** there is no per-mission health. `endpoints/missions.py:88` serves `GET ""` and `:120` serves `GET "/{mission_id}"`. `GateRequestRepository` exists since 88.4.3 and was extended by 88.4.8; this step adds `pending_summary`.

**Change:**
1. **Config.** Append to `missions.yaml`:
   ```yaml
   observability:
     failing_streak_threshold: 3
     occurrence_window_days: 7
     spend_warn_pct: 80
     temporal_describe_concurrency: 8
     health_list_max_missions: 200
   ```
   `ObservabilitySchema(_StrictBase)` gets every field as `int = Field(..., ge=1)`, and `spend_warn_pct` also gets `le=100`. `MissionsSchema` gains `observability: ObservabilitySchema = Field(...)`.
2. **Repository queries:**
   - **`MissionRunRepository.failure_streak(mission_id) -> int`:**
     ```sql
     SELECT count(*) FROM mission_runs
     WHERE mission_id=:m AND status IN ('FAILED','BUDGET_STOPPED','CANCELLED')
       AND NOT (status='CANCELLED' AND status_reason='CANCELLED_BY_USER')
       AND sequence > COALESCE((SELECT max(sequence) FROM mission_runs WHERE mission_id=:m AND status='SUCCEEDED'), 0)
     ```
   - **`last_success(mission_id)` and `latest_terminal(mission_id)`:** both return a `MissionRun` or `None`.
   - **`occurrence_counts(mission_id, since) -> tuple[int, int]`:** returns `(missed, skipped)` and counts rows with `created_at >= since`.
   - **`GateRequestRepository.pending_summary(mission_id, now, grace_seconds) -> PendingGateSummary`:** returns `count`, `oldest_opened_at`, `escalated`, `timed_out` and `overdue`, using the 88.5.6 predicate for `overdue`.
3. **Response schema** (`schemas/mission_health.py`). Every enum on the wire uses lowercase values:
   ```python
   class MissionHealthVerdict(str, enum.Enum):
       HEALTHY = "healthy"
       DEGRADED = "degraded"
       FAILING = "failing"
       PAUSED = "paused"
       IDLE = "idle"


   class MissionHealthReason(str, enum.Enum):
       ARCHIVED = "archived"
       FAILURE_STREAK = "failure_streak"
       SCHEDULE_SYNC_FAILED = "schedule_sync_failed"
       GATE_TIMER_OVERDUE = "gate_timer_overdue"
       RECENT_FAILURE = "recent_failure"
       GATE_ESCALATED = "gate_escalated"
       SPEND_NEAR_CAP = "spend_near_cap"
       OCCURRENCES_MISSED = "occurrences_missed"
       TEMPORAL_UNREACHABLE = "temporal_unreachable"
       NO_ACTIVE_SCHEDULE = "no_active_schedule"
   ```
   `MissionHealthResponse` fields:
   - Mission: `mission_id`, `mission_name`, `mission_status: MissionStatus`, `paused_reason: MissionPauseReason | None`.
   - Verdict: `verdict: MissionHealthVerdict`, `verdict_reasons: list[str]` (`MissionHealthReason` values, or the `MissionPauseReason` value when the verdict is `paused`).
   - Runs: `last_run: RunBrief | None`, with `RunBrief{id, sequence, status: MissionRunStatus, status_reason: MissionRunStatusReason | None, ended_at}`; `last_success_at`, `last_success_sequence`, `failure_streak`, `active_run: RunBrief | None`.
   - Schedules: `next_fire_at`, `next_fire_schedule_id`, `schedules{active, paused, completed, sync_failed}` and `temporal_reachable: bool`.
   - Budget: `budget{month_spent_usd, per_month_usd, month_pct, lifetime_spent_usd, lifetime_usd}`, from `BudgetService.get_status`, with `month_pct = round(100 * month_spent_usd / per_month_usd, 1)`.
   - Gates and occurrences: `pending_gates{count, oldest_opened_at, escalated, timed_out, overdue}` and `occurrences{window_days, missed, skipped}`.
4. **Service:**
   ```python
   class MissionHealthService(BaseService):
       async def get_health(self, mission_id: str) -> MissionHealthResponse: ...

       async def list_health(self, user_id: str, *, is_admin: bool) -> list[MissionHealthResponse]: ...

       @staticmethod
       def compute_verdict(
           h: MissionHealthResponse, cfg: ObservabilitySchema
       ) -> tuple[MissionHealthVerdict, list[str]]: ...
   ```
   **Order of work:** all DB reads for a mission run sequentially on the one `AsyncSession`, because it is not concurrency-safe. After that, `MissionScheduleService.next_fire_times(schedule, 1)` runs for every `ACTIVE` schedule concurrently under `asyncio.Semaphore(temporal_describe_concurrency)`.

   **When Temporal fails.** A Temporal `RPCError` or a timeout sets `temporal_reachable=False` and `next_fire_at=None`, and logs `mission_health.temporal_unreachable` at WARNING with `{mission_id, error}`. The field reports the failure explicitly; it is not a silent fallback.

   **List scope.** `list_health` covers non-archived missions visible to the user (the same filter as `GET /missions`), limited to `health_list_max_missions` and ordered by `updated_at DESC`.

   **`compute_verdict` (first match wins for the verdict; FAILING and DEGRADED collect every matching reason):**
   1. Mission `archived` gives `idle`, `["archived"]`.
   2. Mission `paused` gives `paused`, `[paused_reason.value]`.
   3. `failing` if any of these hold:
      - `failure_streak >= failing_streak_threshold` (`failure_streak`);
      - `schedules.sync_failed > 0` (`schedule_sync_failed`);
      - `pending_gates.overdue > 0` (`gate_timer_overdue`).
   4. `degraded` if any of these hold:
      - `failure_streak >= 1` (`recent_failure`);
      - `escalated + timed_out > 0` (`gate_escalated`);
      - `month_pct >= spend_warn_pct` (`spend_near_cap`);
      - `missed > 0` (`occurrences_missed`);
      - `not temporal_reachable` (`temporal_unreachable`).
   5. No `ACTIVE` schedule and no active run gives `idle`, `["no_active_schedule"]`.
   6. Otherwise `healthy`, `[]`.
5. **API, in `missions.py`:**
   - `GET /missions/health` is registered **above** `GET /{mission_id}` (`:120`). It uses the current user and returns `ApiResponse(data={"missions": [...]})`.
   - `GET /missions/{mission_id}/health` uses `require_existing_mission_access` and returns `ApiResponse(data=MissionHealthResponse)`.

**Tests:**
- `tests/unit/backend/services/test_mission_health_verdict.py` (table-driven over `compute_verdict`):
  - `test_archived_is_idle`;
  - `test_paused_wins_over_failing`;
  - `test_failing_on_streak_threshold`;
  - `test_failing_on_sync_failed`;
  - `test_failing_on_overdue_gate`;
  - `test_degraded_accumulates_reasons`;
  - `test_idle_without_active_schedule`;
  - `test_healthy`.
- `tests/integration/backend/services/test_mission_health_queries.py`:
  - `test_failure_streak_counts_since_last_success`;
  - `test_failure_streak_ignores_user_cancel_skipped_missed`;
  - `test_occurrence_counts_window`;
  - `test_temporal_unreachable_sets_flag_and_returns`.
- `tests/integration/backend/api/test_mission_health_api.py`:
  - `test_list_route_not_shadowed_by_detail`;
  - `test_detail_forbidden_for_non_member`;
  - `test_envelope_shape`: `data.verdict` is a lowercase value.

**Done when:** these tests pass, and `GET /missions/{id}/health` for the endurance mission returns verdict `healthy` while its schedule is active.

---

### 88.5.8 Live run state through the API (`get_run_state`)

**Files:**
- modify `modules/backend/temporal/workflow_gateway.py` (`TemporalWorkflowGateway`, exists since 88.0.3)
- modify `modules/backend/services/mission_run.py`
- modify `modules/backend/api/v1/endpoints/missions_runs.py` (exists since 88.1.12)
- modify `modules/backend/schemas/mission_run.py`
- modify `modules/clients/cli/mc_trace.py`
- create `tests/unit/clients/cli/test_mc_trace.py`
- modify `modules/clients/cli/mc_groups/runs.py` and `modules/clients/cli/mc_mission_runs.py` (exist since 88.1.13)

**Current state:**
- `MissionRunWorkflow` exposes the `get_run_state` query returning `MissionRunWorkflowStatus` (88.1.8, 3.3.3).
- The only caller is the client `mc_trace.py`, which runs `handle.query(...)` from client code inside a `try`/`except` block (the block that queried `get_loop_status` at `a28ca771:modules/clients/cli/mc_trace.py:45-54`, renamed by 88.1.8). That breaks the thin-client rule.
- `TemporalWorkflowGateway` already owns `WorkflowHandle` access: `state()`, `cancel()` and `terminate()` (88.0.3), `start_mission_run` (88.1.7), `signal` (88.1.9), `fetch_history` (88.2.9), `execute_update` (88.4.8) and `start_retention` (88.5.4).

**Change:**
1. **Gateway.** Add to `TemporalWorkflowGateway`:
   ```python
   @dataclass(frozen=True)
   class WorkflowStatusDescription:
       workflow_type: str
       status: str  # lowercase WorkflowExecutionStatus name, for example "running" or "terminated"
       start_time: datetime
       close_time: datetime | None


   async def describe_status(self, workflow_id: str) -> WorkflowStatusDescription | None:
       """handle.describe(); RPCError NOT_FOUND -> None; any other RPCError -> ExternalServiceError."""

   async def query_state(self, workflow_id: str) -> MissionRunWorkflowStatus | None:
       """handle.query("get_run_state", result_type=MissionRunWorkflowStatus); RPCError NOT_FOUND -> None;
       any other RPCError -> ExternalServiceError."""
   ```
   No new gateway module is created and there is no `temporal/run_gateway.py`; `workflow_gateway.py` stays the single owner of `MissionRunWorkflow`, `MissionScheduleTickWorkflow`, `ReconcilerWorkflow` and `RetentionWorkflow` handles; `schedule_gateway.py` owns schedule handles.
2. **Service.** `MissionRunService.get_live_state(mission_id: str, run_id_or_sequence: str) -> MissionRunLiveStateResponse`, with `MissionRunLiveStateResponse{run: MissionRunResponse, workflow_state: WorkflowStatusDescription | None, state: MissionRunWorkflowStatus | None}` in `schemas/mission_run.py`.
   - The run is loaded through `get_run(mission_id, run_id_or_sequence)`, which filters on `mission_id`; a run of another mission raises `NotFoundError`.
   - Temporal is called only when the run status is active (`PENDING`, `RUNNING`, `AWAITING_GATE`, `PAUSED`): `describe_status(mission_run_workflow_id(run.id))` and `query_state(...)` for the same id.
   - Terminal runs return `workflow_state=None, state=None` and make no Temporal call.
3. **Endpoint.** `GET /missions/{id}/runs/{run_id_or_seq}/live` in `missions_runs.py` uses `require_existing_mission_access` and returns `ApiResponse(data=MissionRunLiveStateResponse)`.
4. **Client.**
   - `mc_trace.py` reads live state through `GET /missions/{id}/runs/{run_id_or_seq}/live` instead of a workflow handle. When the target is a mission run (a `SEQ`, or a workflow id produced by `mission_run_workflow_id`, whose run id suffix is passed as `run_id_or_seq`), the header (type, status, start, close) comes from `workflow_state` and the iteration line from `state`. Delete the `try`/`except` block that calls `handle.query(...)`, and stop calling `handle.describe()` for mission runs. For mission-run targets the history timeline is rendered from `GET /missions/{id}/runs/{run_id_or_seq}/history` (item 5). The client-side `get_workflow_handle(...)` call remains only for workflows that are not mission runs (Risk 7).
   - Add `mc runs live SEQ` to `mc_groups/runs.py`, with its renderer in `mc_mission_runs.py`. It calls the endpoint and renders iteration, phase, pending gate, pause flag and last supervisor action through `report.py`.
5. **Run history endpoint.** `MissionRunService.get_history(mission_id: str, run_id_or_sequence: str) -> MissionRunHistoryResponse` loads the run through `get_run` (filters on `mission_id`; another mission's run raises `NotFoundError`) and calls `TemporalWorkflowGateway.fetch_history(mission_run_workflow_id(run.id), run_id=None)` (exists since 88.2.9). `MissionRunHistoryResponse{run: MissionRunResponse, still_running: bool, events: list[dict]}` in `schemas/mission_run.py`; `events` is `history.to_json_dict()["events"]`. A workflow that Temporal no longer holds (namespace retention, 88.5.1) raises `NotFoundError` with detail "history expired". `GET /missions/{id}/runs/{run_id_or_seq}/history` in `missions_runs.py` uses `require_existing_mission_access` and returns `ApiResponse(data=MissionRunHistoryResponse)`. Tests in `test_mission_run_live_state.py`: `test_history_returns_events`, `test_history_other_missions_run_404`, `test_history_expired_404`.

**Tests:**
- `tests/unit/backend/services/test_mission_run_live_state.py`:
  - `test_active_run_queries_temporal`;
  - `test_terminal_run_skips_temporal`;
  - `test_not_found_returns_none_state`;
  - `test_live_other_missions_run_404`.
- `tests/unit/backend/temporal/test_workflow_gateway.py` (extend): `test_query_state_not_found_returns_none` and `test_describe_status_not_found_returns_none`.
- `tests/integration/backend/api/test_mission_run_live_api.py::test_live_endpoint_envelope_and_auth`.
- `tests/unit/clients/cli/test_mc_runs_live.py::test_renders_state_from_api`.
- `tests/unit/clients/cli/test_mc_trace.py::test_mission_run_header_from_live_endpoint`: for a `SEQ` target, the header and iteration line come from the mocked `/live` response, and `handle.describe()` is not called.

**Done when:**
- `grep -rn 'handle.query(' modules/clients` returns nothing.
- `rg -n "start_workflow|get_workflow_handle" modules --glob '!modules/backend/migrations/**' --glob '!modules/backend/temporal/workflow_gateway.py' --glob '!modules/backend/temporal/schedule_gateway.py' | rg -i "MissionRun|MissionTick|MissionScheduleTick|Reconciler|Retention|mission_run_workflow_id"` returns nothing.
- `mc runs live SEQ` prints the phase of a running run, and `mc trace SEQ` prints its status without calling `handle.describe()`.

---

### 88.5.9 Health views in `mc` and the web

**Files:**
- modify `modules/clients/cli/mc_groups/mission.py` (175 lines)
- modify `modules/clients/cli/mc_mission.py`
- create `modules/frontend/src/types/mission-health.ts`
- create `modules/frontend/src/hooks/use-mission-health.ts`
- create `modules/frontend/src/components/mission/mission-health-card.tsx`
- create `modules/frontend/src/components/mission/run-live-state-panel.tsx`
- modify `modules/frontend/src/pages/mission/overview.tsx` (280 lines)
- modify `modules/frontend/src/pages/dashboard.tsx` (122 lines)
- modify `modules/frontend/src/components/dashboard/mission-card.tsx`
- modify `modules/frontend/src/components/workspace/run-detail-panel.tsx`
- modify `modules/frontend/src/lib/constants.ts`

**Current state:**
- At `a28ca771`, `mc mission` has `create`, `list`, `use`, `info`, `set-gate`, `set-budget`, `archive`, `delete` and `unarchive` (`mc_groups/mission.py:26-175`). Phase 4 adds `pause`, `resume` and `budget`, and rewrites `set-budget`.
- The web shows no mission health. The admin health page (`pages/admin/health.tsx:47`) renders `checks` generically through `HealthChecksPanel`, so `temporal` and `worker` appear there without change after 88.5.5.
- `dashboard.tsx:113-115` renders one `MissionCard` (`components/dashboard/mission-card.tsx:20`) per mission.
- `run-detail-panel.tsx` loads `useMissionRun` (88.1.14).

**Change:**
1. **`mc mission health [--all]`.** Without `--all`, it uses `require_mission` and calls `GET /missions/{id}/health`. With `--all`, it calls `GET /missions/health`.
   - **Table columns:** Mission, Verdict, Reasons, Last success, Streak, Next fire, Month spend/cap, Gates (count/overdue). Built through `report.py` primitives (`get_console()`, `build_table`), with no direct `Console` or `Table`.
   - **Exit code:** 0 when every listed verdict is in `{healthy, idle, paused}`, else 3, so cron and monitoring scripts can use it.
2. **Web constants.** `lib/constants.ts`: `export const MISSION_HEALTH_REFETCH_MS = 60_000` and `export const MISSION_RUN_LIVE_REFETCH_MS = 5_000`.
3. **Types.** `types/mission-health.ts` mirrors `MissionHealthResponse` and `MissionRunLiveStateResponse`, with verdict and status unions in the lowercase values the API returns.
4. **Hooks.** `use-mission-health.ts` exports `useMissionHealth(missionId)` and `useMissionsHealth()`, using `api.get` (which unwraps the `ApiResponse` envelope), with `refetchInterval: MISSION_HEALTH_REFETCH_MS`. It also exports `useMissionRunLive(missionId, runRef, active)`, with `refetchInterval: active ? MISSION_RUN_LIVE_REFETCH_MS : false`, where `active` is true while the run status is `pending`, `running`, `awaiting_gate` or `paused`.
5. **Mission health card.** `mission-health-card.tsx` shows the verdict with the existing `StatusPill` (`components/ui/status-pill.tsx`), the reasons, last success, failure streak, next fire (in the schedule's zone as returned), month spend against cap as a meter, and pending gates with a link to the gate. It is mounted at the top of `overview.tsx`.
6. **Dashboard.** `dashboard.tsx` calls `useMissionsHealth()` once, builds a map by `mission_id`, and passes `verdict` to `MissionCard`. `mission-card.tsx` gains an optional `verdict` prop and renders it as a `StatusPill`.
7. **Run live panel.** `run-live-state-panel.tsx` renders `useMissionRunLive`. It is mounted in `run-detail-panel.tsx`, below the run summary.

**Tests:**
- `tests/unit/clients/cli/test_mc_mission_health.py`:
  - `test_health_table_columns`;
  - `test_exit_code_3_on_failing`;
  - `test_all_flag_calls_list_endpoint`.
- Frontend: `npm --prefix modules/frontend run build` and `npm --prefix modules/frontend run lint` pass.

**Done when:**
- `mc mission health --all` lists the endurance mission.
- The overview page shows the card.
- `python mc.py tree | grep "health"` shows `mission health`.

---

### 88.5.10 Structured log event catalogue

**Files:**
- create `modules/backend/core/log_events.py`
- modify the emitting call sites listed in the table below
- create `tests/unit/backend/core/test_log_events.py`

**Current state:** run, schedule, gate, reconciler and retention logs use free-text messages chosen per call site. `scripts/trace_execution.py` and any log query must guess them.

**Change:**
1. **The catalogue.** `log_events.py` imports only the standard library, so workflow modules may import it. It holds two things.
   - `class LogEvent(str, enum.Enum)`. Every value is a dotted name, and each member name is the value upper-cased with `.` replaced by `_` (for example `MISSION_RUN_CLAIMED = "mission_run.claimed"`).
   - `REQUIRED_FIELDS: dict[LogEvent, frozenset[str]]`, as below.

   | LogEvent value | Emitted in | Required `extra` keys |
   |---|---|---|
   | `mission_run.claimed` | `MissionScheduleService.claim_occurrence` | `schedule_id`, `scheduled_for`, `outcome`, `reason`, `mission_run_id` |
   | `mission_run.started` | `MissionRunService.begin` | `mission_id`, `mission_run_id`, `sequence`, `gate_mode`, `config_hash` |
   | `mission_run.finalised` | `MissionRunService.finalise` | `mission_id`, `mission_run_id`, `sequence`, `status`, `reason`, `cost_usd`, `duration_seconds` |
   | `mission_run.budget_breached` | `BudgetService.check_run` | `mission_id`, `mission_run_id`, `cap`, `spent_usd`, `cap_usd` |
   | `mission_run.task_replayed` | `execute_plan_task` idempotent path (88.2.4) | `mission_run_id`, `task_id`, `idempotency_key` |
   | `mission_run.digest_written` | `RunMemoryService.write_digest` | `mission_run_id`, `generator`, `generation_cost_usd` |
   | `mission_schedule.sync_failed` | `MissionScheduleService.sync_to_temporal` | `schedule_id`, `error` |
   | `mission.lifecycle_changed` | `MissionLifecycleService` | `mission_id`, `from_status`, `to_status`, `paused_reason`, `actor_user_id` |
   | `gate.opened` / `gate.escalated` / `gate.timed_out` | `GateDecisionService.open_gate` / `mark_status` | `gate_request_id`, `mission_run_id`, `gate_point` |
   | `gate.decided` | `GateDecisionService.decide` and `close` | `gate_request_id`, `mission_run_id`, `action`, `channel` |
   | `gate.timer_overdue` / `gate.swept_cancelled` | `RunReconciliationService.sweep_gates` (88.5.6) | `gate_request_id`, `mission_run_id` |
   | `reconciler.completed` | `reconcile_mission_runs` activity (88.5.6) | `gates_cancelled`, `gates_overdue`, `stats` |
   | `reconciler.run_orphaned` | `RunReconciliationService.reconcile` (88.1.10a) | `mission_run_id`, `reason` |
   | `retention.policy_completed` | `RetentionService.run_policy` | `policy`, `rows_affected`, `rows_aggregated`, `complete`, `duration_seconds` |
   | `retention.batch_lock_timeout` | `RetentionService._run_batched` | `policy` |
   | `retention.policy_failed` | `RetentionWorkflow` (`workflow.logger`) | `policy` |
   | `health.component_unhealthy` | `hourly_health_check` | `component`, `error` |
   | `mission_health.temporal_unreachable` | `MissionHealthService` | `mission_id`, `error` |
   | `notification.delivery_failed` | `NotificationService` | `delivery_id`, `kind`, `channel`, `error` |
   | `temporal.namespace_retention_set` | `namespace_policy.ensure_namespace_retention` | `namespace`, `retention_days` |

2. **Call-site form.** Each call site uses `logger.<level>(LogEvent.X.value, extra={...})` (or `workflow.logger.<level>` in workflow code) with a dict literal containing at least the required keys. The literal messages introduced in 88.5.1, 88.5.3, 88.5.4 and 88.5.6 are replaced. Every `error` value passes through `redact_secrets` from `modules/backend/core/redaction.py`.

**Tests:** `test_log_events.py` parses every `modules/backend/**/*.py` with `ast`. A logger call is a `Call` whose `func` is an `Attribute` with `attr` in `{"debug", "info", "warning", "error", "exception", "critical"}` and whose receiver is the name `logger` or an attribute named `logger`.
- `test_every_event_emitted`: each `LogEvent` member appears as the first argument (`LogEvent.X.value`) of at least one logger call.
- `test_required_fields_present`: for each such call, the `extra=` dict literal keys are a superset of `REQUIRED_FIELDS[member]`.
- `test_no_raw_string_for_catalogued_names`: no logger call has a string-literal first argument equal to any `LogEvent` value.

**Done when:** `pytest tests/unit/backend/core/test_log_events.py` passes.

---

### 88.5.11 Endurance evaluator: service and script

**Files:**
- create `modules/backend/services/endurance_check.py`
- create `scripts/verify_mission_endurance.py`

**Current state:**
- No tool evaluates a long run. Plan 61 (`docs/08-plans/061-plan-v1-hardening-and-endurance.md:236,247-250`) records that the worker-kill harness was never built.
- `scripts/verify_crash_recovery.py` was deleted in 88.0.10 with the startup crash recovery it exercised.

**Change:**
1. **Service:**
   ```python
   @dataclass
   class EnduranceCheck:
       name: str
       passed: bool
       detail: str
       offending_ids: list[str]


   @dataclass
   class EnduranceReport:
       mission_id: str
       schedule_id: str
       expected_slots: int
       checks: list[EnduranceCheck]

       @property
       def passed(self) -> bool:
           return all(c.passed for c in self.checks)


   class EnduranceCheckService(BaseService):
       async def snapshot_expected_slots(self, schedule_id: str) -> list[datetime]:
           """TemporalScheduleGateway.list_matching_times(temporal_schedule_id, starts_at, ends_at).
           ValidationError if either bound is NULL."""

       async def evaluate(
           self,
           mission_id: str,
           schedule_id: str,
           expected_slots: list[datetime],
           *,
           expect_delivery_status: NotificationDeliveryStatus,
       ) -> EnduranceReport:
           """ValidationError when the mission's first run started more than
           retention.policies.llm_calls_raw_days days ago (rolled-up rows carry no mission_run_id)."""
   ```
   Expected slots come from Temporal and are snapshotted at the start, because the schedule is deleted once COMPLETED. No cron arithmetic is done locally (3.7 item 1).
2. **Checks, all of which must pass.** Names are fixed.

   **Slot accounting:**
   - `slots_complete`: the set of `scheduled_for` for the schedule's runs equals `expected_slots`. `offending_ids` lists lost and unexpected slots as ISO strings.
   - `occurrences_recorded`: every expected slot without a RUN-outcome row has status `SKIPPED` or `MISSED` with a non-null `status_reason`.
   - `sequence_contiguous`: the mission's `sequence` values are exactly `1..max(sequence)`.
   - `watermark_consistent`: `mission_schedules.last_claimed_scheduled_for` equals `max(scheduled_for)` over the schedule's runs.

   **Duplicates and run state:**
   - `no_duplicate_runs`: four conditions must hold.
     - (a) No two runs share `(schedule_id, scheduled_for)`.
     - (b) No run has more than one `execution_records` row.
     - (c) No `(mission_run_id, task_id)` has more than one `task_executions` row with status `COMPLETED`.
     - (d) For each run with `temporal_workflow_id` that ended within `temporal.namespace_retention_days`, a Temporal visibility query on that `WorkflowId` returns exactly one execution whose status is not `ContinuedAsNew`.
   - `all_terminal`: every run is terminal, and none has a `status_reason` of `ORPHANED_WORKFLOW_CLOSED` or `ORPHANED_WORKFLOW_NOT_FOUND`.

   **Spend:**
   - `spend_matches_ledger`: for every run, `abs(mission_runs.cost_usd - sum(llm_calls.cost_usd WHERE mission_run_id = run.id)) <= 0.000001`.

     It also requires `BudgetService.get_status(mission_id).lifetime_spent_usd == sum(mission_runs.cost_usd) + sum(llm_calls.cost_usd WHERE mission_id = :m AND mission_run_id IS NULL)`, to within 0.000001. `detail` reports the unattributed spend.
   - `budget_respected`: for every run, `cost_usd <= coalesce(budget_cap_usd, plan.budget_per_run_usd) + max(llm_calls.cost_usd in that run)`. Overshoot is bounded by one call, because caps are checked between calls. `BUDGET_STOPPED` runs count as a pass here.

   **Digests:**
   - `digests_complete`: every run with `started_at IS NOT NULL` has exactly one `mission_run_digests` row.
   - `digest_chain_intact`: take runs with digests ordered by `sequence`. For each after the first, `previous_run_id` is the immediately preceding one, `context_version_start >= previous.context_version_end`, and every `digest.context_changes[].version` lies in `(context_version_start, context_version_end]`.

   **Notifications and gates:**
   - `notifications_delivered`: every `SUCCEEDED` or `FAILED` run has a `notification_deliveries` row of kind `RUN_SUCCEEDED` or `RUN_FAILED` per recipient whose kinds include it, with status `expect_delivery_status`.
   - `no_stuck_gates`: no gate of the mission is `PENDING`, `ESCALATED` or `TIMED_OUT`.
3. **Script** `scripts/verify_mission_endurance.py`, using argparse with two subcommands:
   - `snapshot --mission-id ID --schedule-id ID --out PATH` writes `{"schedule_id": ..., "slots": [iso, ...]}` and prints the count.
   - `evaluate --mission-id ID --schedule-id ID --slots PATH --expect-delivery-status {sent,skipped_disabled} [--json]` prints a `report.py` table or JSON. The flag value is converted with `NotificationDeliveryStatus(value)`.
   - `tree` prints the subcommands by introspecting the argparse subparsers (rule 010.1).

   **Exit codes:** 0 pass, 1 any check failed, 2 an error such as an unreachable DB or Temporal.

   The script is thin. It opens `get_async_session()` and calls the service.

**Tests:** `tests/integration/backend/services/test_endurance_check.py` seeds runs directly and stubs `TemporalScheduleGateway` and the visibility query.
- `test_clean_history_passes`;
- `test_detects_lost_slot`;
- `test_detects_unexpected_slot`;
- `test_detects_sequence_gap`;
- `test_detects_watermark_regression`;
- `test_detects_duplicate_completed_task_execution`;
- `test_detects_spend_mismatch`;
- `test_unattributed_spend_reported_not_failed_when_balanced`;
- `test_detects_missing_digest`;
- `test_detects_broken_previous_run_link`;
- `test_detects_non_terminal_run`;
- `test_detects_orphaned_reason`;
- `test_detects_stuck_gate`;
- `test_rejects_history_older_than_raw_retention`.

**Done when:** these tests pass, `python scripts/verify_mission_endurance.py --help` lists both subcommands, and `python scripts/verify_mission_endurance.py tree` prints them.

---

### 88.5.12 Compressed endurance variant in CI

**Files:**
- create `tests/endurance/__init__.py`
- create `tests/endurance/conftest.py`
- create `tests/endurance/scripted_model.py`
- create `tests/endurance/worker_entry.py`
- create `tests/endurance/fixtures/outputs/` with one JSON per output schema
- create `tests/endurance/fixtures/scripts.yaml`
- create `tests/endurance/test_compressed_endurance.py`
- create `.github/workflows/endurance.yml`

**Current state:**
- CI (`.github/workflows/ci.yml:58-106`, job `tests`) runs `tests/unit` and `tests/integration` only, and no fault-injection test exists.
- Providers are `anthropic`, `openai`, `copilot` and `foundry` (`core/model_builder.py:152-200`). CI has no credentials for any of them.

**Change:**
1. **Model substitution.** `worker_entry.py` patches `modules.backend.core.model_builder._build_model` before importing `modules.backend.temporal.worker`, then runs `main()`. The patch returns `FunctionModel(scripted_model.respond)`, and production code gets no test hook.

   **`scripted_model.respond(messages, info)` decides as follows:**
   - If `add_task` is in `info.function_tools` and has not been called in `messages`, it calls `add_task` with the args in `scripts.yaml` `add_task`. That is a single task with `agent: research.analyst.agent` (`config/agents/research/analyst/agent.yaml:1`, `tools: []` at `:19`).
   - Else, if `finalise_plan` is available and not yet called, it calls `finalise_plan`.
   - Else, if `info.output_tools` is non-empty, it calls the first output tool with `fixtures/outputs/{title}.json`, where `title` is the output tool JSON schema `title`.
   - The supervisor fixture sets `action: "propose_complete"`.
   - A missing fixture raises `AssertionError(f"no endurance fixture for {title}")`. There is no generated fallback. The implementer creates each fixture when the first run names it.
2. **Fixture (`conftest.py`):**
   - Starts `WorkflowEnvironment.start_local(port=7233, dev_server_extra_args=["--db-filename", str(tmp_path / "temporal.sqlite")])`. The port matches `temporal.server_url`.
   - Runs `python admin.py migrate upgrade head` and `python admin.py admin seed-catalog`.
   - Creates an owner user and a mission through the services in-process. The test process plays the API. The mission is created with `gate_mode=GateMode.AUTONOMOUS`, `budget_per_run_usd=0.50`, `budget_per_month_usd=50` and `owner_id` set to the created user's id.
   - Starts `worker_entry` as a subprocess (`subprocess.Popen([sys.executable, "-m", "tests.endurance.worker_entry"])`).
3. **Test** `test_compressed_endurance_30_runs`:
   1. Create the schedule through `MissionScheduleService.create_schedule` with `MissionScheduleCreate(kind="objective", cron_expression="* * * * *", time_zone_name="UTC", starts_at=..., ends_at=..., objective_template="CI endurance probe {sequence} at {scheduled_for}", name="ci-endurance")`. `starts_at` is the next whole minute plus 1 minute, and `ends_at = starts_at + 29m30s`, giving 30 slots. The catch-up window is the config default.
   2. Snapshot the slots with `EnduranceCheckService.snapshot_expected_slots` and assert there are 30.
   3. **Fault F1 (worker kill mid-task).** Poll the DB once a second. When the run claimed for slot 8 has a task in `RUNNING`, send `SIGKILL` to the worker, wait 70 seconds and restart it. The 70-second hold puts slot 9's tick after the kill, so slot 9 is claimed while run 8 is still active.
   4. **Fault F2 (worker outage across ticks).** Five seconds before slot 16's fire time, send `SIGTERM` to the worker, hold for 150 seconds and restart it. The ticks for slots 16, 17 and 18 queue in Temporal and claim after the restart.
   5. **Fault F3 (Temporal restart).** Five seconds before slot 23's fire time, shut down the `WorkflowEnvironment`, wait 90 seconds and start it again with the same `--db-filename`.
   6. Wait until `ends_at` plus up to 10 minutes, until every run is terminal.
   7. Assert `EnduranceCheckService.evaluate(..., expect_delivery_status=NotificationDeliveryStatus.SKIPPED_DISABLED).passed`.
   8. Assert slot 9 is `SKIPPED/OVERLAP`.
   9. For each of F2 and F3, assert that every slot whose fire time fell inside the outage is either the one `RUN` or `MISSED` with `status_reason` in `{SUPERSEDED, NOT_FIRED}`, and that exactly one of them is `RUN`. Assert at least one `MISSED/SUPERSEDED` row exists.
   10. Assert the slot-8 run is `SUCCEEDED`, with exactly one `COMPLETED` `task_executions` row for its task.
   11. Assert every `llm_calls.model` row for the mission starts with `function`, which proves the patch took effect.
4. **Workflow** `.github/workflows/endurance.yml`:
   - Triggers: `on: schedule: [{cron: "0 3 * * *"}]` and `workflow_dispatch`, with `timeout-minutes: 60`.
   - Services: Postgres 16 with `POSTGRES_USER: mission_control`, `POSTGRES_PASSWORD: postgres` and `POSTGRES_DB: mission_control`, to match `config/settings/database.yaml` and the bootstrapped `DB_PASSWORD`; and Redis 7.
   - Steps copied from the `ci.yml` `tests` job: checkout, `setup-python` 3.14, dependency install, the `.env` bootstrap (`ci.yml:96-102`), and the Temporal dev-server binary prefetch step that 88.0.1 adds.
   - Config steps:
     - `sed -i 's/^\(\s*min_interval_seconds:\).*/\1 60/' config/settings/missions.yaml`;
     - `sed -i '/^channels:/,/^[a-z]/ s/^\(\s*enabled:\).*/\1 false/' config/settings/notifications.yaml` (sets `channels.telegram.enabled: false`, so deliveries record `SKIPPED_DISABLED`).
   - Run: `pytest tests/endurance -q -p no:cacheprovider -s`.
   - On failure: upload `logs/system.jsonl` and `var/logs/*.log` as artefacts.

**Tests:** this step is the test.

**Done when:** a `workflow_dispatch` run of `endurance` is green on main, and it has stayed green for 3 consecutive nightly runs before 88.5.13 starts.

---

### 88.5.13 Acceptance run 1: 7-day hourly mission (168 runs)

**Files:**
- modify `docs/08-plans/088-plan-long-running-recurring-missions.md` (results table only)
- the run outputs `var/endurance/hourly-88-slots.json` and `var/endurance/hourly-88-report.json`, which are not committed

**Current state:** Plan 46 Phase 6 (`docs/08-plans/046-plan-autonomous-mission-roadmap.md:530-569`) is open. No multi-day run has passed.

**Change (runbook, executed exactly):**
1. **Preflight.**
   - Main is at the 88.5.12 commit, with `python services.py start` running.
   - `temporal operator namespace describe -n default` shows `720h0m0s`.
   - `curl -s http://127.0.0.1:$P/health/detailed` shows `temporal` and `worker` healthy, with `P` as in Verification.
   - `notifications.yaml channels.telegram.inbound_approvals_enabled: true` is set in this environment, and `config/.env` sets the Telegram webhook secret (88.0.14 refuses to start the bot without it).
   - The owner has run `mc notify link-telegram` and sent `/link CODE` to the bot, then confirmed the identity showing the expected `@username` (`POST /auth/me/channel-identities/{iid}/confirm`, through the `mc notify` confirm subcommand that `python mc.py tree` lists under `notify`).
   - `mc notify identities` lists one TELEGRAM identity with `verified_at` set.
   - `missions.yaml recurrence.enabled: true` is set in this environment. Production keeps it `false` until Phase 4 is complete (Phase 2 operational rule).
2. **Create the mission.**
   ```bash
   mc mission create --name endurance-hourly-88 --description "Plan 88 7-day hourly acceptance" --gate-mode autonomous
   mc mission use --name endurance-hourly-88
   mc mission set-budget --per-run 0.50 --per-month 120 --lifetime 150
   ```
3. **Choose T0.** T0 is the next whole UTC hour that is at least 15 minutes away.
   ```bash
   mc schedule create hourly --cron "0 * * * *" --tz UTC \
     --objective "Endurance probe {sequence} for {mission_name} at {scheduled_for}: in one task using research.analyst.agent, state in three lines what changed since the previous run's digest and what remains open." \
     --starts-at "$T0" --ends-at "$T0_PLUS_167H30M"
   mc schedule show hourly
   ```
   `T0` and `T0_PLUS_167H30M` are ISO 8601 UTC timestamps written by the operator. `mc schedule show` must report `temporal_sync_state` `synced`.
4. **Snapshot.** `python scripts/verify_mission_endurance.py snapshot --mission-id "$M" --schedule-id "$S" --out var/endurance/hourly-88-slots.json`, where `M` and `S` are the ids `mc mission info` and `mc schedule show hourly` print. It must print `168`.
5. **Daily check at 09:00 UTC.** Run `mc mission health` and `mc runs list --limit 30`. Record the verdict in the results table. A `failing` verdict stops the run: fix in this phase, then restart the runbook from step 2 under a new mission name with suffix `-r2`.
6. **Fault W (worker kill), between hour 24 and hour 36.**
   - Wait until `mc runs live SEQ` shows phase `executing`.
   - Run `pkill -9 -f modules.backend.temporal.worker`.
   - Wait 120 seconds, then `nohup python -m modules.backend.temporal.worker >> var/logs/services-temporal-worker.log 2>&1 &`.
   - Record the run sequence.
7. **Faults R1 and R2 (full redeploy), between hour 72 and hour 96.** Record the git SHA before and after each.
   - **R1, redeploy mid-run.** Before minute 30 of an hour, wait until `mc runs live SEQ` shows phase `executing`, then run `python services.py stop`. Keep everything down for 10 minutes. Run `git pull --ff-only`, `python admin.py migrate upgrade head` and `python services.py start`. Record the run sequence.
   - **R2, redeploy across a tick.** Between minute 45 and minute 50 of an hour, with `mc runs list --status running` empty, run `python services.py stop`. Keep everything down for 30 minutes, so the outage spans exactly one top of the hour. Run `git pull --ff-only`, `python admin.py migrate upgrade head` and `python services.py start`. Record the slot that fell inside the outage.
   - Any `MissionRunWorkflow` code change in a pulled range must already pass the replay test in CI.
8. **User pause, between hour 120 and hour 130.**
   - Run `mc mission pause`, hold for 2 hours 10 minutes, then `mc mission resume`.
   - On resume, `MissionLifecycleService.resume_mission` (88.4.5) locks each `ACTIVE` schedule row (`MissionScheduleRepository.lock`) and, with the lock held, lists the matching times between `missions.paused_at` and now through `TemporalScheduleGateway.list_matching_times`, inserts a `MISSED/NOT_FIRED` row for each, and advances `last_claimed_scheduled_for` to now. `mc runs list` shows those rows immediately.
9. **Retention.** `temporal workflow list --query "WorkflowType='RetentionWorkflow'"` shows at least 7 COMPLETED executions by the end.
10. **Settle and evaluate.** Wait until `mc runs list --status running` is empty after T0 + 168h, for at most 2 hours, then run:
    ```bash
    python scripts/verify_mission_endurance.py evaluate --mission-id "$M" --schedule-id "$S" \
      --slots var/endurance/hourly-88-slots.json --expect-delivery-status sent --json > var/endurance/hourly-88-report.json
    ```

**Pass criteria (all required):**
- Exit code 0, so every 88.5.11 check passed.
- Exactly 168 slots are recorded. The run killed by fault W and the run in flight at fault R1 are `SUCCEEDED` with no `ORPHANED_*`.
- Fault R2: every slot whose fire time fell inside the outage is either the one `RUN` or `MISSED` with reason in `{SUPERSEDED, NOT_FIRED}`, and exactly one run executes for those slots.
- Every slot during the mission pause is `MISSED/NOT_FIRED`.
- Total spend is at most the monthly cap. `GET /missions/{id}/budget` `lifetime_spent_usd` equals the report's ledger figure.
- At least one Telegram `RUN_SUCCEEDED` was received on the owner's phone.

**Done when:** the results table in this plan records the mission id, T0, the fault timestamps, all four SHAs, the run counts by status and reason, the total spend and the evaluator exit code 0.

---

### 88.5.14 Acceptance run 2: 4-week weekly mission with human gates

**Files:** modify `docs/08-plans/088-plan-long-running-recurring-missions.md` (results table only).

**Current state:** durable gates, Telegram approvals and the GATE_TIMEOUT pause have been tested only in unit and integration tests.

**Change (runbook):**
1. **Create the mission.** The owner's Telegram identity is the confirmed one from 88.5.13 step 1. `STARTS_AT` is the first Monday 09:00 Europe/London as a UTC ISO timestamp, and `ENDS_AT` is `STARTS_AT` plus 27 days.
   ```bash
   mc mission create --name endurance-weekly-88 --description "Plan 88 4-week weekly acceptance" --gate-mode manual
   mc mission use --name endurance-weekly-88
   mc mission set-budget --per-run 2.00 --per-month 20
   mc schedule create weekly --cron "0 9 * * 1" --tz Europe/London \
     --objective "Weekly review {sequence} at {scheduled_for}: summarise what changed since the previous digest and list open items." \
     --starts-at "$STARTS_AT" --ends-at "$ENDS_AT"
   python scripts/verify_mission_endurance.py snapshot --mission-id "$M" --schedule-id "$S" --out var/endurance/weekly-88-slots.json
   ```
   The snapshot must print `4`.
2. **Run 1.** Decide every gate in the web UI (channel `WEB`).
3. **Run 2.** Decide every gate with Telegram Approve (channel `TELEGRAM`). Tap the same button a second time. The bot must answer that the action was already used, and `action_tokens.consumed_ref` is set once.
4. **Run 3.** Leave the first gate undecided for more than `gate.durable.pause_after_seconds` (24 hours).
   - Verify that the `GATE_ESCALATED` notification arrived at 4 hours.
   - Verify that `GATE_TIMEOUT_PAUSED` arrived at 24 hours.
   - Verify that `mc mission health` shows verdict `paused` with reason `gate_timeout`.
   - Then approve with Telegram. The workflow closes the gate and resumes the mission (88.4.8), so the mission returns to `active` and the run completes.
5. **Run 4.** Decide gates with `mc gate decide GATE_ID --action continue` (channel `CLI`).
6. **Evaluate.** After the fourth run is terminal, run `python scripts/verify_mission_endurance.py evaluate --mission-id "$M" --schedule-id "$S" --slots var/endurance/weekly-88-slots.json --expect-delivery-status sent`.

**Pass criteria:**
- Evaluator exit code 0.
- `gate_requests.decision_channel` for the mission contains `WEB`, `TELEGRAM` and `CLI`.
- Exactly one gate of the mission has `timed_out_at IS NOT NULL`, and its status is `DECIDED`.
- `missions.paused_reason` is NULL at the end.
- `digest_chain_intact` holds across a 7-day gap between runs.

**Done when:** the results table records the outcome and the evaluator exit code 0.

---

### 88.5.15 Documentation and cross-references

**Files:**
- modify `AGENTS.md`
- modify `docs/08-plans/046-plan-autonomous-mission-roadmap.md`
- modify `docs/08-plans/061-plan-v1-hardening-and-endurance.md`
- modify `docs/10-reference-architecture/10-core-observability.md`
- modify `docs/08-plans/088-plan-long-running-recurring-missions.md`

**Current state:**
- `AGENTS.md` "Codebase Intelligence Tools" (`:123`) lists `code_map.py`, `code_quality.py` and `trace_execution.py`.
- Plan 46 Phase 6 (`:530-569`) still describes pausing through `mission_plans.status` (work unit 3, `:543-544`), which Plan 88 dropped. `:195` and `:224` cite `scripts/verify_crash_recovery.py`, which 88.0.10 deleted.
- Plan 61 (`:247-250`) lists the worker-kill harness as an unmet condition.

**Change:**
1. **`AGENTS.md`.**
   - Under "Codebase Intelligence Tools", add an "Endurance verification" block with the two `verify_mission_endurance.py` commands from 88.5.13 steps 4 and 10, and `mc mission health --all` (exit code 3 means a `failing` or `degraded` verdict).
   - Under "Critical Rules", add one line: "Retention is config-driven (`config/settings/retention.yaml`), runs nightly as Temporal schedule `system-retention`, and never touches `mission_runs`, `mission_run_digests`, `gate_requests` or `llm_call_daily_aggregates`."
   - Under "What NOT to Do", add: "Do not sum `llm_calls` directly for mission spend; use `LlmLedgerRepository.sum_cost`, which includes daily aggregates."
2. **Plan 046.**
   - At the start of Phase 6, add: "**Superseded by Plan 88 Phase 5** (`088-plan-long-running-recurring-missions.md`, steps 88.5.13 and 88.5.14). Pause and resume use `missions.status`; `mission_plans.status` was removed by Plan 88."
   - Strike through work unit 3.
   - After the sentences at `:195` and `:224`, add "(script deleted by Plan 88 step 88.0.10; superseded by `scripts/verify_mission_endurance.py`)".
   - When 88.5.13 passes, set the Phase 6 exit criteria checkboxes (`:554` onwards) and add a dated close-out note citing the mission id.
3. **Plan 061.** After `:250`, add: "Condition 2 is delivered by Plan 88 step 88.5.12 (nightly compressed run with worker SIGKILL, worker outage and Temporal restart) and verified by 88.5.13."
4. **`10-core-observability.md`.** Add a section, "Mission health and log events", covering:
   - the verdict rules from 88.5.7;
   - the `/health/detailed` `temporal` and `worker` components;
   - the rule that every operational log uses `LogEvent` from `modules/backend/core/log_events.py`.
5. **Plan 088.** Add the two results tables. Set the status to Done only after 88.5.14 passes.

**Tests:** `python scripts/check_docs.py` passes.

**Done when:** `python scripts/check_docs.py` and `python scripts/code_rules_fast.py --all` pass.

---

### Verification

```bash
# static and unit/integration
python scripts/code_rules_fast.py --all
python scripts/check_docs.py
black --check --line-length=100 modules/backend modules/clients tests scripts mc.py admin.py services.py tui.py
pytest tests/unit -q -p no:cacheprovider
pytest tests/integration -q -p no:cacheprovider
npm --prefix modules/frontend run build && npm --prefix modules/frontend run lint

# migrations round-trip
python admin.py migrate upgrade head
python admin.py migrate downgrade plan88_007
python admin.py migrate upgrade head
python admin.py migrate current            # plan88_008

# deleted code stays deleted (each prints nothing)
grep -rn --exclude-dir=migrations "DailyCleanupWorkflow\|run_daily_cleanup\|def daily_cleanup\|get_loop_status\|ScheduledMissionCheckWorkflow" modules tests config
grep -n "retention_days" config/settings/executions.yaml
grep -rn 'handle.query(' modules/clients
rg -n "start_workflow|get_workflow_handle" modules --glob '!modules/backend/migrations/**' --glob '!modules/backend/temporal/workflow_gateway.py' --glob '!modules/backend/temporal/schedule_gateway.py' | rg -i "MissionRun|MissionTick|MissionScheduleTick|Reconciler|Retention|mission_run_workflow_id"
test ! -e scripts/verify_crash_recovery.py && echo deleted

# Temporal state
temporal operator namespace describe -n default | grep -i retention                 # 720h0m0s
temporal schedule describe --schedule-id system-retention
python admin.py retention run --policy revoked_sessions
temporal workflow list --query "WorkflowType='RetentionWorkflow'" --limit 3

# health
P=$(python -c 'from modules.clients.service_manager.constants import BACKEND_PORT as p; print(p)')
curl -s http://127.0.0.1:$P/health/detailed | jq -r '.checks.temporal.status, .checks.worker.status'
mc mission health --all; echo "exit=$?"

# endurance
pytest tests/endurance -q -p no:cacheprovider -s     # compressed variant, about 40 minutes
python scripts/verify_mission_endurance.py evaluate --mission-id "$M" --schedule-id "$S" --slots var/endurance/hourly-88-slots.json --expect-delivery-status sent
```

### Risks

1. **The Copilot client degrades over days.** `CopilotModel._client` is process-global (`core/copilot_model.py:419-434`). 88.2.5 adds `CopilotModel.ensure_healthy`, which `execute_plan_task` calls before each task. The residual risk is a failure mode `ensure_healthy` does not detect, such as an SDK session that reports healthy but returns errors on every call.
   **Mitigation:** the daily check in 88.5.13 step 5 catches it as a `failing` streak. The fix lands in this phase (Plan 46 rule: breakage found during endurance is fixed in-phase), and the runbook restarts with `-r2`.
2. **The first retention run hits a large backlog.** `mission_events` has never been purged, so the first night may need hours.
   **Mitigation:** batches of 5000 with `SKIP LOCKED`, `lock_timeout` 5s and `statement_timeout` 60s. Heartbeats run every batch, and `complete=False` resumes the next night. Indexes are built `CONCURRENTLY` in `plan88_008`. Run `python admin.py retention run --policy mission_events` manually once off-peak before enabling the schedule in production.
3. **The rollup could double-count or drop spend.** That would break the monthly cap after 90 days.
   **Mitigation:** delete and upsert happen in one statement and transaction, and only whole UTC days before the cutoff roll. Rows of active runs never roll, and `sum_cost` rejects unaligned windows. `test_rollup_preserves_month_total` is the regression guard.
4. **The scripted model drifts from the real agent schemas.** The CI variant would then pass while the real run fails.
   **Mitigation:** a missing fixture fails the test, with no generated fallback. Fixtures are keyed by output schema title, so a schema rename breaks CI immediately. The real 7-day and 4-week runs remain the acceptance gate, and CI is a regression net only.
5. **The dev-server SQLite file is a single point of loss.** Deleting `var/temporal/dev-server.sqlite` loses all schedules.
   **Mitigation:** Postgres is the source of truth. `python admin.py schedules sync` recreates every Temporal schedule from `mission_schedules`, and the claim backfill records the gap as `MISSED/NOT_FIRED` for every slot after the watermark with `t < min(scheduled_for, now - catch_up_window_seconds)` (88.1.6). The runbook forbids deleting `var/temporal/` during acceptance.
6. **`services/health.py` imports probes from `api/health.py`.** This layering inversion predates Plan 88, and 88.5.5 adds `check_temporal` and `check_worker` in the same pattern rather than widening the step.
   **Mitigation:** out of scope for Plan 88. Moving the probes into the service layer is a separate clean-up with no behaviour change.
7. **`mc trace` still opens a workflow handle from client code for workflows that are not mission runs.** After 88.5.8 every mission-run read in `mc_trace.py` goes through the API, so the single-gateway rule holds. Tracing chat, tool-fork or workflow-run executions still uses `client.get_workflow_handle(...)` in client code, a pre-existing thin-client breach outside this plan's scope. Mitigation: record it as a follow-up; do not extend that path.
   **Mitigation:** none in this phase. The owner decides whether to move the history timeline behind `TemporalWorkflowGateway` and an endpoint, or to retire `mc trace` in favour of `scripts/trace_execution.py`.
