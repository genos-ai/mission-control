## Phase 0: Prerequisite correctness fixes

**Goal:** Phase 0 removes the defects that corrupt or lose state today, before any recurrence work starts. These are reconcilers that fail live work on API restart, the gate-mode and workflow-id confusion, cancellations that never reach Temporal, IDOR on schedules, swallowed exceptions, wrong budgets, fail-open gates and a fail-open Telegram channel. Each step deletes the defective code (P3) and lands with tests that would have caught it.

**Entry criteria:**
- `main` is green on `pytest tests/unit` and `pytest tests/integration`.
- Alembic head is `plan87_002`.
- `git status --porcelain` lists no changes under `modules/`, `config/`, `tests/`, `requirements*.txt`, `pyproject.toml`, `mc.py`, `admin.py` or `services.py`. Uncommitted work in progress (for example the model-provider changes in progress at the time of writing) is committed or stashed first. If it is committed, the implementer re-verifies, by symbol, every line citation in the files it touched before starting the phase. The same criterion applies at the start of every later phase.
- No `MissionRunWorkflow` or `ScheduledMissionCheckWorkflow` executions are open in Temporal: `temporal workflow list --query 'ExecutionStatus="Running" AND (WorkflowType="MissionRunWorkflow" OR WorkflowType="ScheduledMissionCheckWorkflow")'` returns nothing. Otherwise cancel them first (Risk 1).

**Baseline:** every file:line below was verified at `a28ca771`. Backend and config are identical to `9adaa69d` and `777cd5c5`; the later commits touch only the frontend, and every frontend line cited here was re-verified at `a28ca771`. `core/config_schema.py` is cited by class name (line ranges at `a28ca771` in parentheses), because uncommitted work shifts its lines.

**Commit granularity:** one commit per step, message prefix `Plan 88 Phase 0:` (for example `Plan 88 Phase 0: 88.0.4 separate gate_mode from execution_mode`). Phase 0 adds no Alembic migration; `plan88_001` is created by 88.1.0.

**Phase ownership.** Contract 3.0 maps each shared item to its owning step. Phase 0 creates these, and later steps modify them:

| Item | Created in | Later changes |
|---|---|---|
| `temporal/activity_options.py` (`retry_policy`, `activity_kwargs`) | 88.0.2 | imported by every later step; no other retry helper exists |
| `temporal/config_snapshots.py` (`policy_snapshot`, `config_hash`) | 88.0.2 | 88.1.5 imports both and creates `build_run_config_snapshot()`, the only builder of `RunConfigSnapshot` (the dataclass lives in `temporal/mission_run_models.py`), and `build_tick_config_snapshot()`; 88.2.2 extends `build_run_config_snapshot()` with its new fields and adds `build_workflow_timeouts_snapshot()` |
| `temporal.yaml` blocks `mission_run`, `reconciler`, `system_schedules` and their schema classes | 88.0.2 | 88.1.1 and 88.2.1 add only their own keys; 88.1.10 adds the eight remaining `system_schedules` keys together with their `_BUILDERS` entries, never earlier |
| `mission_run_workflow_id` (plan-keyed) | 88.0.3 | 88.1.7 changes the parameter to `mission_run_id` |
| `TemporalWorkflowGateway` (`temporal/workflow_gateway.py`), the only owner of `MissionRunWorkflow`, `MissionScheduleTickWorkflow`, `ReconcilerWorkflow` and `RetentionWorkflow` handles | 88.0.3 | 88.1.7 adds `start_mission_run`, 88.1.9 `signal`, 88.2.9 `fetch_history`, 88.4.8 `execute_update`, 88.5.4 `start_retention`, 88.5.8 `describe_status` and `query_state` |
| `MissionService.is_operator`, `require_mission_operator` | 88.0.9 | 88.1.9, 88.1.12 and 88.4.5 apply it to their routes |
| Mission delete reaching Temporal | 88.0.9 | 88.1.11 terminates (not cancels) the active `mission_runs` workflow and deletes mission schedules; archive (88.4.5) is the cancelling path |
| `RunReconciliationService`, `ReconcilerWorkflow`, `reconciler_activities.py`, `system_schedules.py`, `ReconcilerInput`, `ScheduleSyncStats`, `ReconcileStats` (including `schedule_sync: ScheduleSyncStats \| None`, always `None` in Phase 0) | 88.0.10 | 88.1.10 changes `register_system_schedules(client: Client)` to `register_system_schedules(gateway: TemporalScheduleGateway)` and fills `ReconcileStats.schedule_sync` from `sync_mission_schedules`; 88.1.10a reconciles `mission_runs` and adds `ReconcileStats.examined_mission_runs` and `failed_mission_runs` |
| `use-gates.ts` and the web gate route | 88.0.13 | 88.4.8 |
| Telegram fail-closed allowlist and mandatory webhook secret | 88.0.14 | 88.4.9 cites it |

---

### 88.0.1 Temporal server capability checks and CI Temporal binaries (contract 3.7 item 1)

**Files**
- modify `.github/workflows/ci.yml`
- create `tests/integration/backend/temporal/__init__.py`
- create `tests/integration/backend/temporal/test_server_capabilities.py`

**Current state**
- No test proves that the Temporal server implements `ListScheduleMatchingTimes`, which Phase 1's `claim_occurrence` depends on, or Workflow Update, which Phase 4's gate decisions depend on (`execute_update` needs `frontend.enableUpdateWorkflowExecution` on older self-hosted servers).
- The SDK pin is `temporalio>=1.20.0` (`requirements.txt:61`, `pyproject.toml:50`).
- The dev machine runs `temporal version 1.6.2 (Server 1.30.2, UI 2.45.3)`. CI pins the same CLI release, so the capability tests run against the same server version.
- The CI `tests` job (`.github/workflows/ci.yml`) starts Postgres and Redis only. It has no Temporal server, and nothing prefetches the time-skipping test-server binary that `WorkflowEnvironment.start_time_skipping()` downloads. 88.0.3, 88.0.4 and 88.0.8 depend on that binary. Nothing under `tests/` uses `WorkflowEnvironment` today.

**Change**
1. In `.github/workflows/ci.yml`, job `tests`, insert two steps after `Bootstrap config` and before `Unit tests`. `TEMPORAL_CLI_VERSION` is `1.6.2`, the release the dev machine runs. The download is pinned and its checksum is verified.
   ```yaml
         - name: Start Temporal dev server
           env:
             TEMPORAL_CLI_VERSION: "1.6.2"
           run: |
             base="https://github.com/temporalio/cli/releases/download/v${TEMPORAL_CLI_VERSION}"
             archive="temporal_cli_${TEMPORAL_CLI_VERSION}_linux_amd64.tar.gz"
             curl -sSfL -o "$archive" "$base/$archive"
             curl -sSfL -o checksums.txt "$base/checksums.txt"
             grep " $archive\$" checksums.txt | sha256sum --check
             tar -xzf "$archive" temporal
             nohup ./temporal server start-dev --headless --ip 127.0.0.1 --port 7233 --namespace default > temporal-dev.log 2>&1 &
             for i in $(seq 1 30); do ./temporal operator cluster health --address 127.0.0.1:7233 && break; sleep 1; done
             ./temporal operator cluster health --address 127.0.0.1:7233
         - name: Prefetch Temporal time-skipping test server
           run: |
             python - <<'EOF'
             import asyncio

             from temporalio.testing import WorkflowEnvironment


             async def main() -> None:
                 env = await WorkflowEnvironment.start_time_skipping()
                 await env.shutdown()


             asyncio.run(main())
             EOF
   ```
   The dev server listens on `127.0.0.1:7233`, which is `temporal.yaml server_url`, so `get_temporal_client()` reaches it in CI with no test-only config.
2. Create `tests/integration/backend/temporal/test_server_capabilities.py`. Every test connects with `await get_temporal_client()` (the configured server: the CI dev server above, or the local dev server). Helpers:
   ```python
   from datetime import datetime, timezone

   from google.protobuf.timestamp_pb2 import Timestamp
   from temporalio.api.workflowservice.v1 import ListScheduleMatchingTimesRequest
   from temporalio.client import (
       Client,
       Schedule,
       ScheduleActionStartWorkflow,
       ScheduleSpec,
       ScheduleState,
   )


   def _ts(value: datetime) -> Timestamp:
       ts = Timestamp()
       ts.FromDatetime(value)
       return ts


   async def _matching_times(
       client: Client, schedule_id: str, start: datetime, end: datetime
   ) -> list[datetime]:
       response = await client.workflow_service.list_schedule_matching_times(
           ListScheduleMatchingTimesRequest(
               namespace=client.namespace,
               schedule_id=schedule_id,
               start_time=_ts(start),
               end_time=_ts(end),
           )
       )
       return [t.ToDatetime(tzinfo=timezone.utc) for t in response.start_time]


   async def _create_probe(client: Client, schedule_id: str, cron: str) -> None:
       await client.create_schedule(
           schedule_id,
           Schedule(
               action=ScheduleActionStartWorkflow(
                   "P88CapabilityProbe", id=f"{schedule_id}-wf", task_queue=f"{schedule_id}-q"
               ),
               spec=ScheduleSpec(cron_expressions=[cron], time_zone_name="Europe/London"),
               state=ScheduleState(paused=True),
           ),
       )
   ```
   Each schedule test uses the id `p88-capability-probe-{uuid4().hex[:8]}` and deletes the schedule in `finally` with `await client.get_schedule_handle(schedule_id).delete()`. The windows are fixed dates away from any DST transition, so the expected counts are exact.

   The update probe is a workflow defined in the test module and run on a worker with a unique task queue `p88-update-probe-{uuid4().hex[:8]}`:
   ```python
   from temporalio import workflow


   @workflow.defn(name="P88UpdateProbe")
   class UpdateProbeWorkflow:
       def __init__(self) -> None:
           self._done = False

       @workflow.run
       async def run(self) -> str:
           await workflow.wait_condition(lambda: self._done)
           return "done"

       @workflow.update
       async def finish(self, value: str) -> str:
           self._done = True
           return value
   ```
3. If `list_schedule_matching_times` raises `RPCError` with `RPCStatusCode.UNIMPLEMENTED`, or `execute_update` fails because the server rejects updates, upgrade the dev Temporal server (`temporal server start-dev` binary) to a release that implements both, raise `TEMPORAL_CLI_VERSION` in CI to the same release, and re-run. Do not compute cron times locally.

**Tests** (`test_server_capabilities.py`)
- `test_list_schedule_matching_times_supported`: cron `0 * * * *`, window `2027-01-15T00:30:00Z` to `2027-01-16T00:30:00Z`. Asserts exactly 24 timestamps, each with `minute == 0` after conversion to `Europe/London`.
- `test_schedule_time_zone_name_respected`: cron `0 6 * * *`. Window `2027-01-15T00:00:00Z` to `2027-01-16T00:00:00Z` returns exactly `[2027-01-15T06:00:00Z]` (GMT); window `2027-07-15T00:00:00Z` to `2027-07-16T00:00:00Z` returns exactly `[2027-07-15T05:00:00Z]` (BST).
- `test_workflow_update_supported`: inside `async with Worker(client, task_queue=q, workflows=[UpdateProbeWorkflow])`, start `UpdateProbeWorkflow.run` with id `f"{q}-wf"`, assert `await handle.execute_update(UpdateProbeWorkflow.finish, "ok") == "ok"` and `await handle.result() == "done"`.

**Done when:** `pytest tests/integration/backend/temporal/test_server_capabilities.py -v` passes locally against the dev server and in CI; the CI log shows both new steps succeeding; and the output of `temporal operator cluster describe` (server version) is pasted into the commit body.

---

### 88.0.2 Config, snapshot and activity-policy primitives

**Files**
- modify `config/settings/temporal.yaml`
- modify `config/settings/gate.yaml`
- modify `modules/backend/core/config_schema.py`
- create `modules/backend/temporal/mission_run_models.py`
- create `modules/backend/temporal/activity_options.py`
- create `modules/backend/temporal/config_snapshots.py`
- create `tests/unit/backend/core/test_config_schema_plan88_phase0.py`
- create `tests/unit/backend/temporal/test_activity_options.py`
- create `tests/unit/backend/temporal/test_config_snapshots.py`

**Current state:** `class TemporalSchema` (`core/config_schema.py`, `:320-354` at `a28ca771`) has defaults on every field, which breaks the no-fallback rule, and has no reconciler, heartbeat or system-schedule keys. `class GateManualSchema` (`:611-620` at `a28ca771`) has only `timeout_seconds`. No module converts config into Temporal activity options: each workflow builds `RetryPolicy` inline (`mission_run_workflow.py:68-70,90-93`).

**Change**
1. **`temporal.yaml`.** Append the `mission_run:` block and the `reconciler:` block exactly as contract 3.4.1. Append `system_schedules:` containing **only** `reconciler: {cron: "*/5 * * * *"}`. 88.1.10 adds the other eight keys together with their `_BUILDERS` entries and the equality validator, in one step, so the worker never sees a key it cannot build; 88.2.1 adds `mission_run.max_run_duration_seconds`. Do not delete existing keys in this step: Phase 1 deletes the unread and poller keys in the steps that delete their readers (contract 3.4.1), and 88.2.6 deletes the keys read only by `AgentMissionWorkflow`.
2. **`config_schema.py`.** Add `RetrySchema`, `ActivityPolicySchema`, `MissionRunActivitiesSchema`, `MissionRunSchema`, `ReconcilerSchema` and `SystemScheduleSchema` verbatim from contract 3.4.6. The `MissionRunSchema` validator is:
   ```python
       @model_validator(mode="after")
       def _heartbeat_fits_timeout(self) -> "MissionRunSchema":
           timeout = self.activities.execute_task.heartbeat_timeout_seconds
           if timeout is None:
               raise ValueError(
                   "temporal.mission_run.activities.execute_task.heartbeat_timeout_seconds is required"
               )
           if self.task_heartbeat_interval_seconds * 2 > timeout:
               raise ValueError(
                   "temporal.mission_run.task_heartbeat_interval_seconds must be at most half of "
                   "activities.execute_task.heartbeat_timeout_seconds"
               )
           return self
   ```
   On `TemporalSchema`, add `mission_run: MissionRunSchema = Field(...)`, `reconciler: ReconcilerSchema = Field(...)` and `system_schedules: dict[str, SystemScheduleSchema] = Field(...)`, plus this module constant and validator:
   ```python
   ALLOWED_SYSTEM_SCHEDULE_KEYS: frozenset[str] = frozenset(
       {
           "reconciler",
           "retention",
           "hourly_health_check",
           "weekly_report",
           "metrics_aggregation",
           "cleanup_environments",
           "knowledge_extraction",
           "knowledge_officer",
           "embedding_backfill",
       }
   )


   class TemporalSchema(_StrictBase):
       # existing fields unchanged, plus mission_run, reconciler, system_schedules

       @model_validator(mode="after")
       def _system_schedule_keys(self) -> "TemporalSchema":
           keys = set(self.system_schedules)
           unknown = keys - ALLOWED_SYSTEM_SCHEDULE_KEYS
           if unknown:
               raise ValueError(f"unknown temporal.system_schedules keys: {sorted(unknown)}")
           if "reconciler" not in keys:
               raise ValueError("temporal.system_schedules.reconciler is required")
           return self
   ```
   The existing `_require_server_url_when_enabled` validator stays.
3. **`GateManualSchema`.** Add `poll_interval_seconds: int = Field(..., ge=1)`, and add `poll_interval_seconds: 5` under `gate.yaml manual:` (after `timeout_seconds`, `:33`). 88.0.13 reads it. 88.4.8 deletes it with the `gate.manual` block and `GateManualSchema` (contract 3.4.6).
4. **`temporal/mission_run_models.py`.** Create it with `RetrySnapshot` and `ActivityPolicySnapshot` verbatim from contract 3.3.4, nothing else. 88.0.10 adds the reconciler dataclasses; 88.1.5 adds the remaining 3.3.4 dataclasses.
5. **`temporal/activity_options.py`.** Pure and deterministic; imports only the standard library, `temporalio` and `mission_run_models`. It is the only place a `RetryPolicy` is built for Plan 88 code. `NON_RETRYABLE` holds exception type names, so it may name `RunStartRejectedError` before 88.1.7 creates that class (it covers `INVALID_GATE_MODE` and the owner-not-user `START_FAILED`).
   ```python
   from datetime import timedelta
   from typing import Any

   from temporalio.common import RetryPolicy

   from modules.backend.temporal.mission_run_models import ActivityPolicySnapshot, RetrySnapshot

   NON_RETRYABLE: list[str] = ["BudgetExceededError", "MissionRunStateError", "RunStartRejectedError"]


   def retry_policy(p: RetrySnapshot) -> RetryPolicy:
       return RetryPolicy(
           initial_interval=timedelta(seconds=p.initial_interval_seconds),
           backoff_coefficient=p.backoff_coefficient,
           maximum_interval=timedelta(seconds=p.maximum_interval_seconds),
           maximum_attempts=p.maximum_attempts,
           non_retryable_error_types=NON_RETRYABLE,
       )


   def activity_kwargs(p: ActivityPolicySnapshot) -> dict[str, Any]:
       kwargs: dict[str, Any] = {
           "start_to_close_timeout": timedelta(seconds=p.start_to_close_seconds),
           "retry_policy": retry_policy(p.retry),
       }
       if p.heartbeat_timeout_seconds is not None:
           kwargs["heartbeat_timeout"] = timedelta(seconds=p.heartbeat_timeout_seconds)
       return kwargs
   ```
6. **`temporal/config_snapshots.py`.** Not a workflow module; it converts config into snapshots. The schema import is under `TYPE_CHECKING` so workflow modules can import it through `imports_passed_through` without loading config.
   ```python
   import dataclasses
   import hashlib
   import json
   from typing import TYPE_CHECKING, Any

   from modules.backend.temporal.mission_run_models import ActivityPolicySnapshot, RetrySnapshot

   if TYPE_CHECKING:
       from modules.backend.core.config_schema import ActivityPolicySchema


   def policy_snapshot(schema: "ActivityPolicySchema") -> ActivityPolicySnapshot:
       return ActivityPolicySnapshot(
           start_to_close_seconds=schema.start_to_close_seconds,
           heartbeat_timeout_seconds=schema.heartbeat_timeout_seconds,
           retry=RetrySnapshot(
               initial_interval_seconds=schema.retry.initial_interval_seconds,
               backoff_coefficient=schema.retry.backoff_coefficient,
               maximum_interval_seconds=schema.retry.maximum_interval_seconds,
               maximum_attempts=schema.retry.maximum_attempts,
           ),
       )


   def config_hash(obj: Any) -> str:
       """SHA-256 of the canonical JSON of a snapshot dataclass, excluding its config_hash field."""
       data = {k: v for k, v in dataclasses.asdict(obj).items() if k != "config_hash"}
       canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
       return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
   ```
   A frozen snapshot with a `config_hash` field is built with `config_hash=""` and then finalised with `dataclasses.replace(snapshot, config_hash=config_hash(snapshot))`. This is the only definition of `config_hash`; 88.1.5 and 88.2.2 import it.

**Tests**
- `tests/unit/backend/core/test_config_schema_plan88_phase0.py`:
  - `test_repo_temporal_yaml_validates`: `get_app_config().temporal.reconciler.orphan_grace_seconds == 600` and `system_schedules["reconciler"].cron == "*/5 * * * *"`.
  - `test_heartbeat_validator_rejects_interval_over_half_timeout`: interval 31 with timeout 60 raises `ValidationError`.
  - `test_heartbeat_validator_rejects_null_execute_task_heartbeat`.
  - `test_system_schedules_rejects_unknown_key` and `test_system_schedules_requires_reconciler`.
  - `test_mission_run_schema_has_no_defaults`: every field in `MissionRunSchema.model_fields` has `is_required() is True`.
- `tests/unit/backend/temporal/test_activity_options.py`:
  - `test_retry_policy_maps_snapshot`: all four retry fields map, and `non_retryable_error_types == NON_RETRYABLE`.
  - `test_activity_kwargs_heartbeat_only_when_set`: the `persistence` policy from the repo YAML has no `heartbeat_timeout` key; `execute_task` has `heartbeat_timeout == timedelta(seconds=60)` and `start_to_close_timeout == timedelta(seconds=3600)`.
- `tests/unit/backend/temporal/test_config_snapshots.py`:
  - `test_policy_snapshot_maps_every_field`: built from `temporal.reconciler.activity`.
  - `test_config_hash_ignores_own_field`: two equal objects differing only in `config_hash` give the same hash.
  - `test_config_hash_changes_with_field`: changing `orphan_grace_seconds` changes the hash (uses a local frozen dataclass with fields `config_hash`, `orphan_grace_seconds`).

**Done when:** the tests pass; `python -c "from modules.backend.core.config import get_app_config; get_app_config()"` exits 0; and `grep -rn --exclude-dir=migrations "def retry_policy\|def config_hash\|def activity_kwargs" modules` matches only `temporal/activity_options.py` and `temporal/config_snapshots.py`.

---

### 88.0.3 One deterministic MissionRunWorkflow id, plus a Temporal workflow gateway

**Files**
- create `modules/backend/temporal/workflow_ids.py`
- create `modules/backend/temporal/workflow_gateway.py`
- modify `modules/backend/services/mission_plan_dispatch.py`
- modify `modules/backend/temporal/scheduled_workflow.py`
- create `tests/unit/backend/temporal/test_workflow_ids.py`
- create `tests/unit/backend/temporal/test_workflow_gateway.py`
- create `tests/unit/backend/services/test_mission_plan_dispatch_ids.py`
- create `tests/integration/backend/temporal/test_scheduled_mission_check.py`

**Current state**
- The Director/API path uses `f"mission-run-{plan.id[:12]}-{uuid.uuid4().hex[:8]}"` (`mission_plan_dispatch.py:117`), which is random per start.
- The poller uses `f"mission-run-{plan_info['plan_id']}"` (`scheduled_workflow.py:73`).
- The two schemes never collide, so one plan can have two concurrent MissionRunWorkflows dispatching the same approved tasks.
- `scheduled_workflow.py:86-96` swallows every exception from `start_child_workflow`.
- `services/mission.py:202` uses the poller scheme but iterates a relationship that does not exist (88.0.9).

**Change**
1. `workflow_ids.py`:
   ```python
   def mission_run_workflow_id(plan_id: str) -> str:
       """Phase 0: one MissionRunWorkflow per plan. 88.1.7 changes the parameter to mission_run_id."""
       return f"mission-run-{plan_id}"
   ```
2. `workflow_gateway.py` is the only owner of `MissionRunWorkflow`, `MissionScheduleTickWorkflow`, `ReconcilerWorkflow` and `RetentionWorkflow` handles. Later steps add methods to it and never create another gateway: `start_mission_run` (88.1.7), `signal` (88.1.9), `fetch_history` (88.2.9), `execute_update` (88.4.8), `start_retention` (88.5.4), `describe_status` and `query_state` (88.5.8). Outside this gateway and `TemporalScheduleGateway` (88.1.5), no code calls `start_workflow` or `get_workflow_handle` for `MissionRunWorkflow`, `MissionScheduleTickWorkflow`, `ReconcilerWorkflow` or `RetentionWorkflow`. Other existing workflows (chat, tool fork, plan refine, human input, workflow-run) are out of scope and keep their current calls. The existing `client.start_workflow` in `start_temporal_run_workflow` (item 3) stays only until 88.1.7 deletes that function and starts runs through `start_mission_run`; the child start in `scheduled_workflow.py` (item 4) stays until 88.1.8 deletes that module.
   ```python
   import enum

   from temporalio.client import Client


   class WorkflowState(str, enum.Enum):
       RUNNING = "running"
       CLOSED = "closed"
       NOT_FOUND = "not_found"


   class TemporalWorkflowGateway:
       def __init__(self, client: Client) -> None: ...

       @classmethod
       async def connect(cls) -> "TemporalWorkflowGateway": ...

       async def state(self, workflow_id: str) -> WorkflowState: ...

       async def cancel(self, workflow_id: str) -> WorkflowState: ...

       async def terminate(self, workflow_id: str, reason: str) -> WorkflowState: ...
   ```
   - `connect` calls `get_temporal_client()`; a `RuntimeError` from it becomes `ExternalServiceError`.
   - `state` calls `handle.describe()`. Status RUNNING gives `RUNNING`; any other status gives `CLOSED`; `RPCError` with `RPCStatusCode.NOT_FOUND` gives `NOT_FOUND`; any other `RPCError` raises `ExternalServiceError`.
   - `cancel` calls `state()`; if RUNNING it calls `handle.cancel()`. It returns the pre-cancel state.
   - `terminate` has the same shape and calls `handle.terminate(reason=reason)`.
3. `start_temporal_run_workflow` (`mission_plan_dispatch.py:71-124`): set `workflow_id = mission_run_workflow_id(plan.id)` and start with
   ```python
   try:
       await client.start_workflow(
           MissionRunWorkflow.run,
           workflow_input,
           id=workflow_id,
           task_queue=config.temporal.task_queue,
           id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
           id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
       )
   except WorkflowAlreadyStartedError as exc:
       raise ConflictError(f"A mission run is already in progress for plan {plan.id}") from exc
   ```
   `WorkflowIDReusePolicy` and `WorkflowIDConflictPolicy` come from `temporalio.common`; `WorkflowAlreadyStartedError` from `temporalio.exceptions`. `import uuid` (`:19`) stays, because `:335` still uses it.
4. `scheduled_workflow.py:71-96`: start the child with `id=mission_run_workflow_id(plan_info["plan_id"])` and `id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE`. Replace `except Exception` with `except WorkflowAlreadyStartedError`, logged at info. Any other exception propagates and fails the check workflow, so it is visible in Temporal.

**Tests**
- `test_workflow_ids.py::test_mission_run_workflow_id_uses_full_plan_uuid`: id equals `"mission-run-" + plan_id` for a 36-character UUID.
- `test_workflow_gateway.py`:
  - `test_state_running`, `test_state_closed_for_completed_failed_cancelled_terminated_timed_out`, `test_state_not_found_on_rpc_not_found`.
  - `test_state_raises_external_service_error_on_unavailable`.
  - `test_cancel_noop_when_closed` (asserts `handle.cancel` not awaited).
  - `test_terminate_passes_reason`.
- `test_mission_plan_dispatch_ids.py`:
  - `test_start_uses_deterministic_id_and_fail_conflict_policy`: mock client; asserts the `id`, `id_reuse_policy` and `id_conflict_policy` kwargs.
  - `test_start_conflict_raises_conflict_error`: the client raises `WorkflowAlreadyStartedError`; asserts `ConflictError`.
- `test_scheduled_mission_check.py` (time-skipping `WorkflowEnvironment`; stub activity `find_ready_plans` returning one plan; stub workflow `@workflow.defn(name="MissionRunWorkflow")` that waits on a signal):
  - `test_child_started_with_shared_id`: the child id is `mission-run-{plan_id}`.
  - `test_second_check_does_not_start_duplicate`: a second run returns `dispatched == 0` and exactly one child exists.

**Done when:** `grep -rn --exclude-dir=migrations 'mission-run-{' modules/backend --include=*.py` shows only `temporal/workflow_ids.py` and `services/mission.py` (the latter is removed by 88.0.9), and the tests pass.

---

### 88.0.4 Separate `gate_mode` from `execution_mode`

**Files**
- modify `modules/backend/temporal/models.py`
- modify `modules/backend/services/mission_plan_dispatch.py`
- modify `modules/backend/temporal/scheduled_activities.py`
- modify `modules/backend/temporal/scheduled_workflow.py`
- modify `modules/backend/temporal/mission_run_workflow.py`
- modify `modules/backend/temporal/supervisor_activities.py`
- modify `modules/backend/models/mission_plan.py`
- create `tests/unit/backend/models/test_gate_mode_resolution.py`
- modify `tests/unit/backend/temporal/test_models.py`
- create `tests/integration/backend/temporal/test_mission_run_workflow_phase0.py`

**Current state**
- `MissionWorkflowInput.execution_mode` (`temporal/models.py:22`) carries two meanings:
  - the Director path sets it to `mission.execution_environment` (`mission_plan_dispatch.py:114`, for example `local` or `container`);
  - the poller sets it to the plan gate mode (`scheduled_workflow.py:67`).
- `MissionRunWorkflow` passes it as `gate_mode` to the supervisor (`mission_run_workflow.py:121`), so Director-dispatched runs evaluate with `gate_mode="local"`. `AutonomousPostRunReviewer` treats that as neither `manual` nor `autonomous` (`gate_post_run.py:92,188,197`).
- No other consumer reads `MissionWorkflowInput.execution_mode`. `dispatch_approved` reads `mission.execution_environment` directly (`mission_plan_dispatch.py:302`).

**Change**
1. `temporal/models.py`: delete `execution_mode`, and add `gate_mode: str | None = None` directly after `mission_id`, with the comment `# plan gate mode; None only on AgentMissionWorkflow starts, which do not read it (deleted in 88.2.6)`.
2. `mission_plan_dispatch.py:107-115`: pass `gate_mode=resolve_gate_mode(plan.gate_mode)` (helper from 88.0.5) and remove `execution_mode=`.
3. `scheduled_activities.py:84`: return `"gate_mode": resolve_gate_mode(plan.gate_mode)`. In `scheduled_workflow.py:67`, use `gate_mode=plan_info["gate_mode"]` (no `.get` default).
4. `mission_run_workflow.py:121`: `gate_mode=resolve_gate_mode(input.gate_mode)`. `resolve_gate_mode` is a pure function, imported inside the existing `workflow.unsafe.imports_passed_through()` block (`:25-28`).
5. `supervisor_activities.py:39`: `gate_mode: str` with no default; reorder so it sits among the non-default fields.

Steps 2 to 4 use `resolve_gate_mode`. This commit adds it, exactly as 88.0.5 item 1 specifies, together with `test_gate_mode_resolution.py`; 88.0.5 then applies it to the remaining sites.

**Tests**
- `test_models.py`:
  - `test_mission_workflow_input_has_no_execution_mode`: `"execution_mode" not in {f.name for f in fields(MissionWorkflowInput)}`.
  - `test_post_run_eval_input_gate_mode_required`: constructing it without `gate_mode` raises `TypeError`.
- `test_mission_plan_dispatch_ids.py::test_start_passes_plan_gate_mode_not_environment`: mission `execution_environment="container"` with plan `gate_mode="manual"`; the captured input has `gate_mode == "manual"`.
- `test_mission_run_workflow_phase0.py` (time-skipping `WorkflowEnvironment`; stub activities registered under the real names `execute_mission`, `persist_mission_outcome`, `evaluate_post_run` (returns `escalate`), `fire_supervisor_followups`, `check_plan_active`, `start_director_turn` and `send_notification`):
  - `test_supervisor_receives_input_gate_mode`: input `gate_mode="manual"`; the captured `PostRunEvalInput.gate_mode == "manual"`.
  - `test_supervisor_receives_manual_when_gate_mode_missing`: input `gate_mode=None`; the captured value is `"manual"`.

**Done when:** `grep -rn --exclude-dir=migrations "execution_mode" modules/backend/temporal` returns nothing, and the tests pass.

---

### 88.0.5 Fail-closed gate defaults

**Files**
- modify `modules/backend/agents/mission_control/gate.py`
- modify `modules/backend/agents/mission_control/gate_post_run.py`
- modify `modules/backend/agents/mission_control/gate_prompt.py`
- modify `modules/backend/temporal/scheduled_activities.py`
- modify `modules/backend/temporal/plan_refine_activities.py`
- modify `modules/backend/agents/mission/director/agent.py`
- modify `modules/backend/services/mission_plan_dispatch.py`
- modify `modules/backend/services/mission_plan_orchestrator.py`
- modify `tests/unit/backend/agents/mission_control/test_gate.py`
- modify `tests/unit/backend/mission_control/test_gate_post_run.py`
- create `tests/unit/backend/temporal/test_scheduled_activities.py`
- create `tests/unit/backend/temporal/test_plan_refine_activities.py`
- create `tests/unit/backend/services/test_mission_plan_orchestrator_gate.py`

**Current state:** each of these sites fails open:
- `scheduled_activities.py:57-60`: the poller dispatches plans whose `gate_mode IS NULL` as autonomous.
- `scheduled_activities.py:84`: `plan.gate_mode or "autonomous"`.
- `gate.py:282-286`: an unknown effective mode logs a warning and returns `CONTINUE`.
- `gate_prompt.py:138-146`: `_parse_action` maps an unknown gate action from the AI reviewer to `CONTINUE` (`:145-146`, "Unknown gate action '%s', defaulting to CONTINUE").
- `gate_post_run.py:78`: `gate_mode or "autonomous"`.
- `plan_refine_activities.py:63-73`: `gate = refined.gate_mode or "autonomous"`, then `if gate != "interactive": approve_all_proposed(...)`. Every MANUAL and NULL plan is auto-approved after a Director refine.
- `director/agent.py:152`: `gate = plan.gate_mode or "autonomous"`, so the Director's orientation reports NULL plans as autonomous.
- `mission_plan_dispatch.py:270-277`: `if plan.gate_mode:` builds no gate at all when NULL, so every gate point is skipped.
- `mission_plan_orchestrator.py:402`: an invalid `gate_mode` override is silently ignored.
- `mission_plan_orchestrator.py:423-440`: `plan.gate_mode or "autonomous"`, and every mode except `interactive` falls through to `approve_all_proposed` (`:440`), so MANUAL plans are auto-approved.

`create_mission` never sets `gate_mode` from the API (`schemas/mission.py` `MissionCreate` has no such field), so NULL is the common case.

**Change**
1. `models/mission_plan.py`, after `AUTO_APPROVE_GATE_MODES` (`:59`), added in the 88.0.4 commit:
   ```python
   FAIL_CLOSED_GATE_MODE: str = "manual"


   def resolve_gate_mode(value: str | None) -> str:
       """NULL, 'workflow_managed' and any value outside VALID_GATE_MODES resolve to MANUAL (decision 7, fail closed)."""
       return value if value in VALID_GATE_MODES else FAIL_CLOSED_GATE_MODE
   ```
   No logging here: it is called inside workflow code. Service callers log the resolution when the input differs from the result.
2. `gate.py:282-286`: replace with `logger.error("Unknown gate mode %r: aborting (fail closed)", effective_mode)` and `return GateDecision(action=GateAction.ABORT, reason=f"unknown gate mode {effective_mode!r}", reviewer=f"config:invalid_mode:{effective_mode}")`.
3. `gate_post_run.py:78`: `self._gate_mode = resolve_gate_mode(gate_mode)`.
4. `scheduled_activities.py:57-60`: replace the `or_(...)` with `MissionPlan.gate_mode == "autonomous"`. Line 84 is handled in 88.0.4.
5. `plan_refine_activities.py:63-65`: replace the two lines with `approved_count = 0` and `if resolve_gate_mode(refined.gate_mode) == "autonomous":`. The body (`:66-72`) is unchanged.
6. `director/agent.py:152`: `gate = resolve_gate_mode(plan.gate_mode)`.
7. `mission_plan_dispatch.py:270-277`: always build the gate with `create_gate(mode_override=resolve_gate_mode(plan.gate_mode), event_bus=event_bus)` (the arguments the current call already passes), and delete the `if plan.gate_mode:` guard and the `gate_reviewer = None` line.
8. `mission_plan_orchestrator.py:402`: replace `if gate_mode is not None and gate_mode in VALID_GATE_MODES:` with
   ```python
   if gate_mode is not None:
       if gate_mode not in VALID_GATE_MODES:
           raise ValidationError(
               f"Invalid gate_mode {gate_mode!r}. Must be one of: {sorted(VALID_GATE_MODES)}"
           )
       plan.gate_mode = gate_mode
   ```
   At `:423-424`, use `effective_gate = resolve_gate_mode(plan.gate_mode)` and `if effective_gate != "autonomous":`, so every non-autonomous mode stops after refine with `outcome_status="awaiting_approval"` (the existing return at `:431-438`). The log message at `:426` becomes `"run_objective: non-autonomous gate, stopping after refine"`.
9. `gate_prompt.py:138-146` (`_parse_action`): an unknown action fails closed. Replace the comment and the two lines at `:143-146` with `logger.warning("Unknown gate action %r: aborting (fail closed)", action_str)` and `return GateAction.ABORT`, and change the docstring to `"""Parse action string to GateAction; an unknown action is ABORT (fail closed)."""`. The caller (`gate.py:108`) is unchanged.

Auto-approval after refine is AUTONOMOUS-only at `plan_refine_activities.py` and `mission_plan_orchestrator.py`, matching the target `AUTO_APPROVE_GATE_MODES = {GateMode.AUTONOMOUS}` that 88.1.0 introduces. Making `gate_mode` required at mission creation is **not** in Phase 0; it lands with `plan88_001` in 88.1.0. Until then new missions resolve to MANUAL (Risk 2).

**Tests**
- `test_gate_mode_resolution.py` (created in 88.0.4): `test_none_resolves_manual`, `test_unknown_resolves_manual`, `test_workflow_managed_resolves_manual`, and `test_valid_modes_pass_through` (parametrised over `VALID_GATE_MODES`).
- `test_gate.py::test_unknown_effective_mode_aborts`: config `mode="bogus"` built with `model_construct` to bypass `_GateMode`; asserts `action == GateAction.ABORT` and `reviewer == "config:invalid_mode:bogus"`. Delete any existing test asserting unknown gives CONTINUE.
- `test_gate.py::test_unknown_gate_action_aborts`: `_parse_action("explode") == GateAction.ABORT`. It replaces `test_unknown_action_falls_back` (`:255-256`), which is deleted.
- `test_gate_post_run.py::test_none_gate_mode_uses_manual_reviewer`: patches `ManualGateReviewer.review` and asserts it is awaited when `gate_mode=None`.
- `test_scheduled_activities.py` (DB):
  - `test_find_ready_plans_excludes_null_gate_mode`: a plan with NULL gate mode and one approved task gives an empty result.
  - `test_find_ready_plans_includes_autonomous`.
- `test_plan_refine_activities.py` (refine and `approve_all_proposed` patched):
  - `test_refine_null_gate_mode_does_not_approve`: `approve_all_proposed` is not awaited.
  - `test_refine_manual_gate_mode_does_not_approve`.
  - `test_refine_autonomous_approves`.
- `test_mission_plan_orchestrator_gate.py`:
  - `test_run_objective_rejects_invalid_gate_mode_override`: raises `ValidationError`.
  - `test_run_objective_null_gate_mode_leaves_tasks_proposed`: `refine` is patched to return two PROPOSED tasks; afterwards both are still PROPOSED and `outcome_status == "awaiting_approval"`.
- `test_mission_plan_dispatch_ids.py::test_dispatch_approved_null_gate_mode_builds_manual_gate`: patches `create_gate` and asserts `mode_override="manual"`.

**Done when:** `grep -rnE --exclude-dir=migrations 'or "autonomous"|gate_mode or |defaulting to CONTINUE' modules/backend` returns nothing (in particular, `defaulting to CONTINUE` matches neither `gate.py` nor `gate_prompt.py`), and the tests pass.

---

### 88.0.6 Stop `_persist_workflow_as_plan` overwriting `plan.gate_mode`

**Files**
- modify `modules/backend/services/workflow_run.py`
- modify `modules/backend/temporal/scheduled_activities.py`
- create `tests/unit/backend/services/test_workflow_run_persist_plan.py`
- modify `tests/unit/backend/temporal/test_scheduled_activities.py`

**Current state**
- `workflow_run.py:504-513` permanently rewrites the mission's plan `gate_mode` to `"workflow_managed"` whenever it is not manual, interactive or ai_assisted. This includes autonomous and NULL, and the value is never restored. Running one workflow therefore removes a mission from autonomous dispatch for good, and turns every later `create_gate(mode_override="workflow_managed")` into the unknown-mode branch.
- `:529` auto-approves on `("workflow_managed", "autonomous")`.
- The overwrite exists only to hide the materialised tasks from `find_ready_plans`.

**Change**
1. Delete `workflow_run.py:504-513` (comment and assignment). Change `:529` to `if resolve_gate_mode(plan.gate_mode) == "autonomous":`.
2. Keep the poller off missions whose tasks a workflow run owns. In `find_ready_plans` (`scheduled_activities.py:50-63`), add `~exists(select(WorkflowRun.id).where(WorkflowRun.mission_id == Mission.id, WorkflowRun.status.in_([WorkflowRunState.PENDING, WorkflowRunState.RUNNING, WorkflowRunState.AWAITING_INPUT])))`.
3. Existing rows that already hold `workflow_managed` are not migrated here. They resolve to MANUAL through `resolve_gate_mode` (88.0.5) and are normalised by `plan88_001` in 88.1.0.

**Tests**
- `test_workflow_run_persist_plan.py` (DB; workflow schema with two agent steps):
  - `test_autonomous_gate_mode_preserved`: after the call `plan.gate_mode == "autonomous"`.
  - `test_null_gate_mode_preserved`: stays NULL.
  - `test_autonomous_auto_approves_tasks`: both tasks are APPROVED.
  - `test_manual_leaves_tasks_proposed`.
  - `test_null_leaves_tasks_proposed`.
- `test_scheduled_activities.py::test_find_ready_plans_excludes_mission_with_active_workflow_run`: an autonomous plan with an approved task and a RUNNING `WorkflowRun` on the same mission gives an empty result.

**Done when:** `grep -rn --exclude-dir=migrations "workflow_managed" modules/backend --include=*.py` matches only `models/mission_plan.py` (the docstring of `resolve_gate_mode`), and the tests pass.

---

### 88.0.7 The scheduled poller passes the remaining budget, not the lifetime ceiling

**Files**
- modify `modules/backend/services/mission_plan.py`
- modify `modules/backend/temporal/scheduled_activities.py`
- modify `modules/backend/temporal/scheduled_workflow.py`
- modify `modules/backend/services/mission_plan_dispatch.py`
- modify `modules/backend/temporal/plan_refine_models.py`
- modify `modules/backend/agents/mission/director/tools/refine_plan.py`
- modify `modules/backend/api/v1/endpoints/missions_plan.py`
- create `tests/unit/backend/services/test_mission_plan_budget.py`
- modify `tests/unit/backend/temporal/test_scheduled_activities.py`

**Current state:** three call sites compute the run budget three different ways:
- The poller returns `"budget": plan.budget_usd_ceiling or get_default_budget_usd()` (`scheduled_activities.py:83`), and the workflow passes it as `mission_budget_usd` (`scheduled_workflow.py:65`). Every poller-started run therefore gets the whole lifetime ceiling as its in-run budget.
- The Director path uses `(ceiling or default) - total_spent` (`mission_plan_dispatch.py:90`).
- `dispatch_approved` uses `ceiling - spent` only when a ceiling is set, and otherwise the full default (`:285-287`). Its exhaustion check ignores NULL ceilings (`:185-192`).
- `scheduled_workflow.py:20,65` calls `get_default_budget_usd()` inside workflow code.
- `PlanRefineInput.mission_budget_usd: float = 10.0` (`temporal/plan_refine_models.py:19`) is a hardcoded fallback. Both starters pass `plan.budget_usd_ceiling or get_default_budget_usd()`, the lifetime ceiling (`director/tools/refine_plan.py:72`, `missions_plan.py:184`).

**Change**
1. Add to `services/mission_plan.py`, module level:
   ```python
   def remaining_plan_budget_usd(plan: MissionPlan) -> float:
       """Lifetime cap minus spend. A NULL ceiling means the configured default cap (missions.default_budget_ceiling_usd)."""
       ceiling = (
           plan.budget_usd_ceiling if plan.budget_usd_ceiling is not None else get_default_budget_usd()
       )
       return ceiling - plan.total_spent_usd
   ```
2. In `find_ready_plans`, delete the SQL budget filter (`:65-71`). After the query, skip rows where `remaining_plan_budget_usd(plan) <= 0`, and return `"budget_remaining_usd": remaining_plan_budget_usd(plan)` instead of `"budget"`.
3. In `scheduled_workflow.py:65`, set `mission_budget_usd=plan_info["budget_remaining_usd"]`, and remove `get_default_budget_usd` from the import at `:20`.
4. In `mission_plan_dispatch.py`, use `remaining = remaining_plan_budget_usd(plan)` at `:90` (`max(remaining, 0.01)` is unchanged), at `:185-192` (the check now applies when the ceiling is NULL as well) and at `:285-287` (`budget = remaining`). Phase 4 (88.4.1) later deletes the `dispatch_approved` budget lines.
5. `plan_refine_models.py:19`: change the field to `mission_budget_usd: float` (required, no default, comment deleted). Both starters pass `mission_budget_usd=remaining_plan_budget_usd(plan)`, imported from `modules.backend.services.mission_plan` beside the existing `MissionPlanService` import: `director/tools/refine_plan.py:72` and `missions_plan.py:184`. Remove `get_default_budget_usd` from each file's imports when ruff F401 reports it unused.

**Tests**
- `test_mission_plan_budget.py`:
  - `test_remaining_uses_ceiling_minus_spent`: ceiling 10, spent 7 gives 3.0.
  - `test_remaining_null_ceiling_uses_default_minus_spent`: `get_default_budget_usd` patched to 5, spent 2 gives 3.0.
  - `test_dispatch_approved_rejects_exhausted_null_ceiling`: NULL ceiling and spend at or above the default raises `ValidationError` containing `"budget exhausted"`.
- `test_scheduled_activities.py`:
  - `test_find_ready_plans_returns_remaining_not_ceiling`: ceiling 10, spent 7 gives `budget_remaining_usd == 3.0` and no `"budget"` key.
  - `test_find_ready_plans_skips_exhausted_plan`.
- `test_mission_plan_budget.py::test_plan_refine_input_budget_required`: constructing `PlanRefineInput` without `mission_budget_usd` raises `TypeError`.

**Done when:** `grep -n "get_default_budget_usd\|\"budget\"" modules/backend/temporal/scheduled_*.py` returns nothing (the activity reaches the default only through `remaining_plan_budget_usd`), `grep -n "= 10.0" modules/backend/temporal/plan_refine_models.py` returns nothing, and the tests pass.

---

### 88.0.8 Stop swallowing exceptions; make execute_mission cancellable and decouple its timeout from budget

**Files**
- modify `modules/backend/temporal/activities.py`
- modify `modules/backend/temporal/mission_run_workflow.py`
- modify `modules/backend/agents/mission_control/persistence_bridge.py`
- modify `modules/backend/agents/mission_control/mission_dispatch.py`
- modify `tests/unit/backend/temporal/test_activities.py`
- create `tests/unit/backend/mission_control/test_persistence_bridge.py`
- modify `tests/integration/backend/temporal/test_mission_run_workflow_phase0.py`

**Current state**
- `execute_mission` catches `asyncio.CancelledError` and returns `status="failed"` (`activities.py:136-169`), so Temporal cancellation and timeouts never surface. It also catches every `Exception` and returns a failed stub (`:171-209`), so the workflow proceeds to supervisor evaluation as if a wave ran, and the retry policy never applies.
- `persist_mission_outcome` swallows `Exception` and returns `False` (`:280-320`).
- `persist_mission_results` swallows `OSError/ValueError/RuntimeError` and returns `None` (`persistence_bridge.py:178-186`). `outcome.execution_record_id` then becomes `None` (`mission_dispatch.py:446-455`), and `persist_mission_outcome` re-persists the same outcome through the "crash recovery path" (`activities.py:245-275`), which duplicates execution records.
- The execute timeout is `max(budget*120, 600)` (`mission_run_workflow.py:73-78`).
- No heartbeat exists, so Temporal cannot deliver cancellation into the activity.

**Change**
1. `execute_mission`:
   - Start a heartbeat task at entry:
     ```python
     interval = get_app_config().temporal.mission_run.task_heartbeat_interval_seconds


     async def _beat() -> None:
         while True:
             activity.heartbeat({"phase": "dispatch"})
             await asyncio.sleep(interval)


     beat = asyncio.create_task(_beat())
     ```
     Cancel `beat` in `finally`, before `redis.aclose()` (`:211`).
   - In the `CancelledError` branch, keep the best-effort SystemEvent, then `raise` (delete the `return` at `:165-169`).
   - In the `Exception` branch, keep the log and SystemEvent, then `raise` (delete the `return` at `:205-209`).
2. `persist_mission_outcome`: delete the error-stub branch (`:227-238`), which is unreachable once (1) lands. In the `Exception` branch (`:280`), keep the log and event, then `raise` (delete `return False` at `:320`).
3. `persistence_bridge.persist_mission_results`:
   - Change the return type to `str`.
   - Change `except (OSError, ValueError, RuntimeError) as e:` (`:178`) to log, `await db_session.rollback()`, then `raise`.
   - Change the docstring to "Raises on failure; the caller's activity retry policy decides".
   - Leave the per-artifact best-effort `try` (`:127-147`) unchanged.
   - In `mission_dispatch.py:444`, change the comment `# Best-effort persistence` to `# Persistence (raises on failure)`.
4. Retry behaviour after (1) and (2): `dispatch_approved` flips every approved task to RUNNING and commits (`mission_plan_dispatch.py:226-230`) before any work runs. A retry of a partially executed wave therefore finds no APPROVED tasks and raises `ValidationError` (`:200-203`). `ValidationError` is not in `NON_RETRYABLE`, so the remaining attempts of the `execute_task` policy (3 in total) each raise the same error without re-running or re-charging completed work; then the workflow fails, and 88.0.10 fails the orphaned RUNNING tasks.
5. `mission_run_workflow.py`:
   - Add to the `imports_passed_through` block (`:25-28`): `from modules.backend.temporal.activity_options import activity_kwargs` and `from modules.backend.temporal.config_snapshots import policy_snapshot`.
   - Delete `activity_timeout` (`:73-78`) and replace the `execute_mission` call (`:86-94`) with:
     ```python
     result = await workflow.execute_activity(
         activities.execute_mission,
         input,
         cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
         **activity_kwargs(policy_snapshot(config.mission_run.activities.execute_task)),
     )
     ```
   - Replace the three `start_director_turn` timeouts at `:285`, `:304` and `:346` with `start_to_close_timeout=timedelta(seconds=config.mission_run.activities.director_turn.start_to_close_seconds)`. Their `retry_policy` arguments are unchanged.
   - `get_app_config()` stays in this workflow until 88.2.2 replaces it with the run config snapshot.
   - Do not delete `budget_timeout_multiplier_seconds` or the `execution_retry_*` keys: `temporal/workflow.py:72,86-91` and `run_objective_workflow.py:56` still read them. 88.2.6 deletes them with `AgentMissionWorkflow`.

**Tests**
- `test_activities.py`:
  - Delete the existing test asserting a failed result on cancellation.
  - `test_execute_mission_reraises_cancelled_error`: `dispatch_approved` raises `asyncio.CancelledError`; `pytest.raises(asyncio.CancelledError)`.
  - `test_execute_mission_reraises_dispatch_exception`: raises `RuntimeError("boom")`; asserts the same type is raised and `publish_to_mission` is awaited once with a `SystemEvent` at level `error`.
  - `test_execute_mission_heartbeats_while_dispatching`: interval patched to `0.01`, dispatch sleeps `0.05`; `activity.heartbeat` is patched and called at least 3 times with `{"phase": "dispatch"}`.
  - `test_persist_mission_outcome_reraises_on_failure`.
- `test_persistence_bridge.py`:
  - `test_raises_and_rolls_back_on_value_error`: `ExecutionPersistenceService.save_execution` patched to raise `ValueError`; asserts it raises and `rollback` is awaited.
  - `test_artifact_failure_does_not_raise`.
- `test_mission_run_workflow_phase0.py`:
  - `test_cancel_reaches_execute_mission`: the stub `execute_mission` heartbeats in a loop and records `CancelledError`. After `handle.cancel()`, the stub recorded the cancel and `describe().status == WorkflowExecutionStatus.CANCELED`.
  - `test_execute_timeout_independent_of_budget`: inputs `mission_budget_usd=0.01` and `1000` both schedule `execute_mission` with `start_to_close_timeout == 3600s` and `heartbeat_timeout == 60s`, read from the history's `ActivityTaskScheduledEventAttributes`.

**Done when:** `grep -n "return MissionExecutionResult" modules/backend/temporal/activities.py` shows only the success return (`:121`), and `grep -n "budget_timeout_multiplier\|activity_timeout" modules/backend/temporal/mission_run_workflow.py` is empty.

---

### 88.0.9 Operator rule; cancellation reaches Temporal; mission delete stops its workflows; remove unauthenticated legacy endpoints

**Files**
- modify `modules/backend/services/mission.py`
- modify `modules/backend/core/dependencies.py`
- create `modules/backend/services/execution_cancellation.py`
- modify `modules/backend/api/v1/endpoints/executions.py`
- modify `modules/backend/api/v1/endpoints/missions_workflows.py`
- modify `modules/backend/api/v1/endpoints/missions_plan.py`
- modify `modules/backend/api/v1/endpoints/workflows.py`
- modify `modules/frontend/src/hooks/use-executions.ts`
- create `tests/unit/backend/services/test_execution_cancellation.py`
- modify `tests/unit/backend/api/test_executions_api.py`
- create `tests/unit/backend/api/test_missions_plan_api.py`
- modify `tests/integration/backend/services/test_mission.py`

**Current state**
- No write-level mission check exists. `core/dependencies.py` has `require_mission_access` and `require_existing_mission_access` (owner or any member, `:277-304`) and `require_mission_owner` (`:307-321`). `MissionMemberRole` is `OWNER`, `MAINTAINER`, `VIEWER` (`models/mission.py:42-46`).
- `PATCH /missions/{id}/plan` (`missions_plan.py:86-105`) changes `gate_mode` and budget behind `require_existing_mission_access` (`:104`), so a VIEWER can switch a mission to autonomous.
- `POST /executions/{id}/cancel` (`executions.py:349-386`) only writes `cancelled` to the DB, and the Temporal workflow keeps running and spending.
- `POST /missions/{id}/workflow-runs/{run_id}/cancel` (`missions_workflows.py:571-617`) is the same and uses read-level `require_mission_access` (`:592`) for a write.
- `services/mission.py:194-212` loops over `mission.plans`, which does not exist (`models/mission.py:122` defines only `members`), so the loop never runs. It also swallows every error.
- `api/v1/endpoints/workflows.py:86-221` exposes `POST /workflows/missions` (`:90-109`, a deprecated stub), `GET /workflows/missions` (`:112-139`), `GET /workflows/missions/{id}` (`:142-178`) and `POST /workflows/missions/{id}/cancel` (`:181-221`) with **no `CurrentUser` dependency**: any caller can list, read and cancel any execution record. The only consumer is the unused `useCreateExecution` (`use-executions.ts:98-108`).

**Change**
1. `MissionService.is_operator` (`services/mission.py`, next to `is_member` at `:357`):
   ```python
   async def is_operator(self, mission_id: str, user: User) -> bool:
       """Platform admin, the mission owner, or a member whose role is OWNER or MAINTAINER.

       Raises NotFoundError for an unknown mission, for every caller.
       """
       mission = await self.get_mission(mission_id)
       if user.has_role("admin") or mission.owner_id == user.id:
           return True
       membership = await self._member_repo.get_membership(mission_id, user.id)
       return membership is not None and membership.role in {
           MissionMemberRole.OWNER,
           MissionMemberRole.MAINTAINER,
       }
   ```
2. `core/dependencies.py`, after `require_mission_owner`:
   ```python
   async def require_mission_operator(db, mission_id: str, user) -> None:
       """Allow a platform admin, the mission owner, or an OWNER/MAINTAINER member.

       Raises AuthorizationError otherwise; NotFoundError for an unknown mission.
       """
       from modules.backend.services.mission import MissionService

       if not await MissionService(db).is_operator(mission_id, user):
           raise AuthorizationError("Requires mission owner or maintainer")
   ```
   This is the only definition. 88.1.9, 88.1.12 and 88.4.5 apply it to their routes.
3. `PATCH /missions/{id}/plan`: replace `require_existing_mission_access` at `missions_plan.py:104` with `require_mission_operator`.
4. `services/execution_cancellation.py`:
   ```python
   class ExecutionCancellationService(BaseService):
       async def cancel_execution(
           self, execution_id: str, *, user_id: str, reason: str
       ) -> tuple[ExecutionRecord, bool, bool]: ...

       async def cancel_workflow_run(
           self, mission_id: str, run_id: str, *, user_id: str
       ) -> tuple[WorkflowRun, bool, bool]: ...
   ```
   Both return `(row, changed, temporal_cancelled)`. The order in both methods is:
   1. Load the row. `cancel_workflow_run` loads with `WHERE id = :run_id AND mission_id = :mission_id` and raises `NotFoundError` otherwise. If the row is terminal, return `(row, False, False)` with no Temporal call.
   2. Save `temporal_workflow_id` to a local. For a WorkflowRun, use the `temporal_workflow_id` of `ExecutionRecord(id=run.execution_record_id)`.
   3. `await self._session.commit()` to end the read transaction.
   4. If the id is not None, call `TemporalWorkflowGateway.connect()` then `.cancel(id)`. `ExternalServiceError` propagates (HTTP 503) and the DB is untouched.
   5. Mark the row cancelled through the existing `ExecutionPersistenceService.complete_execution(..., status="cancelled")` or `WorkflowRunService.cancel_run`, and return. The caller commits.

   Log `reason` with the cancel. A record whose id is `mission-run-{plan_id}` cancels the whole mission run, which is intended; 88.0.10 fails its RUNNING tasks once the workflow closes.
5. Endpoints:
   - `cancel_execution` uses `require_mission_operator` (in place of `_require_execution_access` at `executions.py:367`) and the service, and returns `{"id", "status", "temporal_cancelled"}`.
   - `cancel_workflow_run` does the same with `require_mission_operator` (in place of `:592`).
   - Delete `workflows.py:86-221` (the section comment and the four routes) and the imports that become unused (ruff F401 decides).
   - Delete `useCreateExecution` (`use-executions.ts:98-108`) and the `ExecutionCreateRequest` and `ExecutionCreateResponse` types when no other file imports them.
6. `MissionService.delete_mission`: replace `services/mission.py:194-212` with:
   - `plan = await MissionPlanRepository(self._session).get_by_mission_id(mission_id)`;
   - collect the `temporal_workflow_id` values of the mission's execution records with status PENDING or RUNNING;
   - build the id set: `{mission_run_workflow_id(plan.id)}` when a plan exists, plus those ids; then `await self._session.commit()`;
   - `gateway = await TemporalWorkflowGateway.connect()`; for each id, `await gateway.terminate(id, reason=f"Mission {mission_name} deleted")`.

   Termination is used rather than cancellation because the rows are about to be deleted, so no cleanup activity may run. `ExternalServiceError` aborts the delete before any DB delete (fail closed). 88.1.11 modifies this block to terminate (not cancel) the active `mission_runs` workflow, for the same reason, and to delete the mission's schedules through the schedule gateway. Archive (88.4.5) is the cancelling path.

**Tests**
- `tests/integration/backend/services/test_mission.py`:
  - `test_is_operator_matrix`, parametrised: platform admin `True`; mission owner `True`; member OWNER `True`; member MAINTAINER `True`; member VIEWER `False`; non-member `False`.
  - `test_is_operator_unknown_mission_raises_not_found`.
  - `test_delete_mission_terminates_mission_run_workflow`: the patched gateway's `terminate` is awaited with `mission-run-{plan.id}`.
  - `test_delete_mission_aborts_when_temporal_unavailable`: the mission row still exists after `ExternalServiceError`.
- `test_missions_plan_api.py::test_patch_plan_gate_mode_viewer_forbidden`: a VIEWER member sends `PATCH /api/v1/missions/{id}/plan {"gate_mode": "autonomous"}` and gets 403; the plan's `gate_mode` is unchanged.
- `test_execution_cancellation.py` (DB plus a fake gateway):
  - `test_cancel_execution_cancels_workflow_then_marks_cancelled`: the gateway's `cancel` is awaited with the stored id, and the record ends `cancelled`.
  - `test_cancel_execution_not_found_workflow_still_marks_cancelled`.
  - `test_cancel_execution_temporal_unavailable_leaves_record_running`: `ExternalServiceError` is raised and the status is still `running`.
  - `test_cancel_terminal_execution_noop_without_gateway_call`.
  - `test_cancel_workflow_run_cancels_linked_workflow`.
  - `test_cancel_workflow_run_other_mission_raises_not_found`.
  - `test_cancel_execution_without_workflow_id_is_db_only`: `temporal_cancelled is False`.
- `test_executions_api.py`:
  - `test_cancel_execution_viewer_forbidden`: a VIEWER member gets 403.
  - `test_legacy_workflows_missions_routes_removed`: `POST /api/v1/workflows/missions`, `GET /api/v1/workflows/missions`, `GET /api/v1/workflows/missions/x` and `POST /api/v1/workflows/missions/x/cancel` each return 404 or 405.

**Done when:** `grep -n 'hasattr(mission, "plans")' modules/backend/services/mission.py` is empty, `grep -rn --exclude-dir=migrations "workflows/missions" modules` is empty, `grep -rn --exclude-dir=migrations "def require_mission_operator\|def is_operator" modules` shows one match each, and the tests pass.

---

### 88.0.10 Delete the API-startup reconcilers; add a periodic Temporal-aware reconciler in the worker

**Files**
- delete `modules/backend/services/mission_plan_crash_recovery.py`
- delete `tests/unit/backend/services/test_mission_plan_crash_recovery.py`
- delete `scripts/verify_crash_recovery.py`
- modify `modules/backend/main.py`
- modify `modules/backend/services/mission_plan_dispatch.py`
- modify `modules/backend/services/mission_plan_orchestrator.py`
- modify `modules/backend/temporal/activities.py`
- modify `modules/backend/models/task.py`
- modify `modules/backend/repositories/task.py`
- modify `modules/backend/repositories/execution_record.py`
- modify `modules/backend/repositories/workflow_run.py`
- modify `modules/backend/api/v1/endpoints/executions.py`
- modify `modules/backend/services/workflow_run.py`
- modify `modules/backend/temporal/tool_fork_activities.py`
- modify `modules/backend/temporal/mission_run_models.py`
- create `modules/backend/services/run_reconciliation.py`
- create `modules/backend/temporal/reconciler_activities.py`
- create `modules/backend/temporal/reconciler_workflow.py`
- create `modules/backend/temporal/system_schedules.py`
- modify `modules/backend/temporal/worker.py`
- create `tests/unit/backend/services/test_run_reconciliation.py`
- create `tests/unit/backend/temporal/test_system_schedules.py`
- create `tests/unit/backend/test_no_startup_reconcilers.py`
- create `tests/integration/backend/temporal/test_reconciler_workflow.py`

**Current state**
- On every API process start, `main.py:216-249` runs three blind reconcilers:
  - every RUNNING task becomes FAILED and every QUEUED task becomes APPROVED (`mission_plan_crash_recovery.py:39-150`);
  - every RUNNING or PENDING `WorkflowRun` becomes FAILED (`:153-223`);
  - every RUNNING or PENDING `ExecutionRecord` becomes FAILED (`:226-259`).
- None of them consults Temporal, so an API redeploy fails work the worker is still executing. QUEUED to APPROVED re-feeds the autonomous poller, which re-spends.
- `dispatch_approved` calls the same reconciler per plan before every wave (`mission_plan_dispatch.py:168-180`), failing tasks that a concurrent run owns.
- Workflow ids are not recorded for:
  - early wave records (`mission_plan_dispatch.py:381-415`, called at `:240`);
  - `/executions/{id}/execute` (`executions.py:244-258`);
  - the inner WorkflowRun record created by `run_workflow_from_definition` (`workflow_run.py:236-262`) when it runs under `RunWorkflowWorkflow` (`tool_fork_activities.py:141-162`).
- Several paths run work in-process with no Temporal workflow at all: `handle_mission` from `clients/cli/execution_cmds.py:152,215` and `clients/tui/services/service_bridge.py:155`; `WorkflowRunService.run_workflow` from `clients/cli/workflow_cmds.py:230`, `api/v1/endpoints/missions_workflows.py:386` and `agents/mission_control/dispatch/loop.py:692`. These can run longer than any grace period, and the reconciler cannot observe them.

**Change**
1. Delete `main.py:216-249`, `mission_plan_dispatch.py:168-180`, `mission_plan_crash_recovery.py` and its test. Delete `scripts/verify_crash_recovery.py`, which verifies only the deleted `reconcile_orphaned_task_states()` and already fails at baseline (it imports `PlanTaskState` and `PlanTaskStatus`, which no longer exist). Delete `TaskRepository.list_in_flight` (`repositories/task.py:132-146`).
2. Stamp workflow ids on every Temporal-driven row:
   - `dispatch_approved` (`mission_plan_dispatch.py:127`) and the orchestrator wrapper (`mission_plan_orchestrator.py:497-511`) gain the required keyword `temporal_workflow_id: str`. `execute_mission` passes `activity.info().workflow_id` (its only caller, `activities.py:113`). `create_early_execution_record` gains the same keyword and sets `temporal_workflow_id` on the record.
   - `execute_execution` sets `record.temporal_workflow_id = f"execution-{execution_id}"` before commit.
   - `WorkflowRunService.run_workflow` and `run_workflow_from_definition` gain the keyword `temporal_workflow_id: str | None` and write it on the inner `exec_record`. In-process callers pass `None`.
   - `execute_run_workflow` passes `activity.info().workflow_id`.
3. `models/task.py:61`: `TaskStatus.QUEUED: frozenset({TaskStatus.RUNNING, TaskStatus.FAILED})`.
4. Repositories (selects only). The id predicates implement the reconciler scope: rows with no Temporal id (in-process work) are never selected.
   - `TaskRepository.list_in_flight_older_than(cutoff) -> list[Task]`: status in (RUNNING, QUEUED) and `updated_at < cutoff`.
   - `ExecutionRecordRepository.list_in_flight_older_than(cutoff) -> list[ExecutionRecord]`: status in (PENDING, RUNNING), `updated_at < cutoff`, and `temporal_workflow_id IS NOT NULL OR workflow_run_id IS NOT NULL`.
   - `WorkflowRunRepository.list_in_flight_older_than(cutoff) -> list[WorkflowRun]`: status in (PENDING, RUNNING), `updated_at < cutoff`, joined to `ExecutionRecord` on `WorkflowRun.execution_record_id` with `ExecutionRecord.temporal_workflow_id IS NOT NULL`. AWAITING_INPUT is excluded because it waits durably in `HumanInputWorkflow`.
   - `WorkflowRunRepository.list_active_for_mission(mission_id) -> list[WorkflowRun]`: status in (PENDING, RUNNING, AWAITING_INPUT).
5. `temporal/mission_run_models.py`: add
   ```python
   @dataclass(frozen=True)
   class ReconcilerInput:
       """Schedule action input, built by the worker; config_hash covers the other fields."""

       config_hash: str
       orphan_grace_seconds: int
       activity: ActivityPolicySnapshot


   @dataclass(frozen=True)
   class ReconcileInput:
       orphan_grace_seconds: int


   @dataclass
   class ScheduleSyncStats:
       synced: int
       failed: int
       deleted_orphans: int
       completed: int


   @dataclass
   class ReconcileStats:
       examined_tasks: int
       examined_execution_records: int
       examined_workflow_runs: int
       failed_tasks: int
       failed_execution_records: int
       failed_workflow_runs: int
       left_running: int
       left_in_process: int
       schedule_sync: ScheduleSyncStats | None
   ```
   Phase 0 has no schedule sync, so `schedule_sync` is always `None` here. 88.1.10 fills it from `sync_mission_schedules` (it stays `None` whenever that activity did not run), and 88.1.10a adds `examined_mission_runs` and `failed_mission_runs`.
6. `services/run_reconciliation.py`:
   ```python
   class RunReconciliationService(BaseService):
       def __init__(
           self,
           session: AsyncSession,
           gateway: TemporalWorkflowGateway,
           event_bus: SessionEventBus | None,
       ) -> None: ...

       async def reconcile(self, orphan_grace_seconds: int) -> ReconcileStats: ...
   ```
   The algorithm runs in strict order.

   **Collect.** Set `cutoff = utc_now() - timedelta(seconds=orphan_grace_seconds)`. Load the three candidate lists (step 4) and `list_active_for_mission` for each distinct `mission_id` among the tasks. Save ids, statuses, `plan_id`, `mission_id`, `execution_record_id`, `workflow_run_id` and the resolved `temporal_workflow_id` values into plain dataclasses, then `commit()`.

   **Resolve.** Every Temporal call happens here, with each `state()` result cached per workflow id. Any `ExternalServiceError` propagates before any write.
   - **ExecutionRecord:** if `temporal_workflow_id` is set, use `state(id)`. Otherwise (`workflow_run_id` is set) look up `ExecutionRecord(id=WorkflowRun.execution_record_id).temporal_workflow_id` for that run: NULL means the run is in-process, so the record is **in-process**; otherwise use `state(id)`.
   - **WorkflowRun:** use `state()` of its execution record's `temporal_workflow_id` (never NULL, by the step 4 join).
   - **Task (by plan):** the task is live if `state(mission_run_workflow_id(plan_id)) == RUNNING`, or if any `list_active_for_mission` run of its mission is AWAITING_INPUT, or resolves RUNNING. It is **in-process** if any active run of its mission has an execution record whose `temporal_workflow_id` is NULL.

   **Decide.** RUNNING or live leaves the row alone and increments `left_running`. In-process leaves the row alone and increments `left_in_process`. CLOSED or NOT_FOUND marks it orphaned.

   **Write.** One transaction. Re-select the orphaned ids with `with_for_update(skip_locked=True)` and the same status, `updated_at < cutoff` and id predicates, so a row that progressed meanwhile is skipped.
   - **Tasks:** `transition_status(FAILED)`, `failure_reason = f"orphaned: workflow {wid} {state.value}"[:500]`, `last_attempt_at = utc_now()`.
   - **Execution records:** `status = FAILED`, `completed_at = utc_now()`.
   - **Workflow runs:** `FAILED`, `completed_at`, and `error_data = {"type": "OrphanedWorkflow", "message": f"workflow {wid} {state.value}"}`.

   **Return.** `ReconcileStats` with the eight counters and `schedule_sync=None`.

   **Emit.** After commit, best-effort: `MissionPlanTaskStatusChangedEvent` with `actor="system:reconciler"` and `WorkflowRunFailedEvent`, as the deleted module did.

   88.1.10a replaces the task liveness branch with reconciliation keyed on `mission_runs` (contract 3.5.1) and deletes the `mission_run_workflow_id(plan_id)` lookup.
7. `temporal/reconciler_activities.py`: `@activity.defn async def reconcile_mission_runs(input: ReconcileInput) -> ReconcileStats`. It opens a session, a Redis event bus and `TemporalWorkflowGateway.connect()`, then calls the service and commits.
8. `temporal/reconciler_workflow.py`:
   ```python
   @workflow.defn
   class ReconcilerWorkflow:
       @workflow.run
       async def run(self, inp: ReconcilerInput) -> ReconcileStats:
           return await workflow.execute_activity(
               reconcile_mission_runs,
               ReconcileInput(orphan_grace_seconds=inp.orphan_grace_seconds),
               **activity_kwargs(inp.activity),
           )
   ```
   It does not read config. 88.1.10 adds `sync_mission_schedules` after `reconcile_mission_runs`.
9. `temporal/system_schedules.py`:
   ```python
   async def register_system_schedules(client: Client) -> None: ...
   ```
   - For each key in `get_app_config().temporal.system_schedules`, look up `_BUILDERS: dict[str, Callable[[TemporalSchema], tuple[Callable[..., Any], Any]]]`. Phase 0 holds only `"reconciler"`. A key missing from `_BUILDERS` raises `RuntimeError`.
   - The reconciler builder:
     ```python
     def _reconciler_action(temporal: "TemporalSchema") -> tuple[Callable[..., Any], ReconcilerInput]:
         inp = ReconcilerInput(
             config_hash="",
             orphan_grace_seconds=temporal.reconciler.orphan_grace_seconds,
             activity=policy_snapshot(temporal.reconciler.activity),
         )
         return ReconcilerWorkflow.run, dataclasses.replace(inp, config_hash=config_hash(inp))
     ```
   - Create or update each schedule:
     ```python
     schedule_id = f"system-{key}"
     fn, arg = _BUILDERS[key](temporal)
     schedule = Schedule(
         action=ScheduleActionStartWorkflow(fn, arg, id=schedule_id, task_queue=temporal.task_queue),
         spec=ScheduleSpec(cron_expressions=[entry.cron]),
         policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
     )
     try:
         await client.create_schedule(schedule_id, schedule)
     except ScheduleAlreadyRunningError:
         await client.get_schedule_handle(schedule_id).update(
             lambda _: ScheduleUpdate(schedule=schedule)
         )
     ```
     Other errors propagate. 88.1.10 changes the signature to `register_system_schedules(gateway: TemporalScheduleGateway)` and routes these calls through the gateway.
10. `worker.py`: register `ReconcilerWorkflow` and `reconcile_mission_runs`. In `start_worker` (`:81`), call `await register_system_schedules(client)` before `await worker.run()`. A failure stops the worker from starting (fail closed).

**Tests**
- `test_run_reconciliation.py` (DB plus a fake gateway that records `state` calls):
  - `test_running_workflow_leaves_tasks_untouched`: a RUNNING task with `updated_at = now - 700s`; the gateway returns `RUNNING` for `mission-run-{plan_id}`; after `reconcile(600)` the task is RUNNING and `left_running == 1`.
  - `test_closed_workflow_fails_running_and_queued_tasks`: both FAILED, and `failure_reason` starts with `"orphaned: workflow mission-run-"`.
  - `test_not_found_workflow_fails_tasks`: the gateway `state` returns `NOT_FOUND` for a RUNNING task with `updated_at = now - 700s`; after `reconcile(600)` the task is FAILED, `failure_reason` ends with `not_found`, and `failed_tasks == 1`.
  - `test_rows_inside_grace_untouched`: `updated_at = now - 60s` with grace 600.
  - `test_task_owned_by_live_workflow_run_untouched`: the plan workflow resolves `CLOSED`; the task's mission has a RUNNING `WorkflowRun` whose execution record has `temporal_workflow_id = "run-workflow-x"`, which resolves `RUNNING`; after `reconcile(600)` the task is RUNNING and `left_running == 1`.
  - `test_task_owned_by_awaiting_input_workflow_run_untouched`: the plan workflow resolves `CLOSED`; the task's mission has an AWAITING_INPUT `WorkflowRun`; after `reconcile(600)` the task is RUNNING and the gateway records no `state` call for that run's workflow id.
  - `test_task_owned_by_in_process_workflow_run_untouched`: the active run's execution record has `temporal_workflow_id = NULL`; the task stays RUNNING and `left_in_process == 1`.
  - `test_in_process_record_without_ids_untouched`: a RUNNING record with both `temporal_workflow_id` and `workflow_run_id` NULL and `updated_at = now - 3600s` stays RUNNING, and the gateway records no `state` call for it.
  - `test_execution_record_with_running_workflow_untouched`: a RUNNING record with `temporal_workflow_id = "execution-a"` and `updated_at = now - 700s`; the gateway returns `RUNNING`; after `reconcile(600)` the record is RUNNING and `failed_execution_records == 0`.
  - `test_execution_record_with_closed_workflow_failed`: the same record with the gateway returning `CLOSED`; after `reconcile(600)` the record is FAILED, `completed_at` is set, and `failed_execution_records == 1`.
  - `test_step_record_follows_its_workflow_run`: a RUNNING step record with `temporal_workflow_id = NULL` and `workflow_run_id` set, whose run's execution record has `temporal_workflow_id = "run-workflow-x"`; the gateway returns `CLOSED` for `run-workflow-x`; after `reconcile(600)` the step record is FAILED and the gateway recorded `state("run-workflow-x")` exactly once.
  - `test_workflow_run_with_in_process_record_never_selected`: a RUNNING `WorkflowRun` with `updated_at = now - 3600s` whose execution record has `temporal_workflow_id = NULL`; `WorkflowRunRepository.list_in_flight_older_than` does not return it, after `reconcile(600)` it is RUNNING, and `examined_workflow_runs == 0`.
  - `test_workflow_run_awaiting_input_never_selected`: an AWAITING_INPUT `WorkflowRun` with `updated_at = now - 3600s` and a Temporal id on its execution record; after `reconcile(600)` it is AWAITING_INPUT and `examined_workflow_runs == 0`.
  - `test_temporal_unavailable_raises_and_writes_nothing`: all rows keep their status after `ExternalServiceError`.
  - `test_state_cached_per_workflow_id`: three tasks in one plan give exactly one `state` call.
  - `test_reconcile_returns_no_schedule_sync`: the returned stats have `schedule_sync is None`.
  - `test_row_progressed_between_resolve_and_write_skipped`: the task is moved to COMPLETED inside a gateway side effect, and the final status is COMPLETED.
- `test_system_schedules.py` (mock client):
  - `test_creates_reconciler_schedule_when_absent`: id `system-reconciler`, cron `*/5 * * * *`, overlap SKIP, and the action arg is a `ReconcilerInput` with `orphan_grace_seconds == 600` and `config_hash == config_hash(arg)`.
  - `test_updates_existing_schedule`: `create_schedule` raises `ScheduleAlreadyRunningError`, and `handle.update` is awaited once.
  - `test_unknown_key_raises`: `get_app_config().temporal.system_schedules` is patched to contain `"bogus"` alongside `"reconciler"`; `register_system_schedules(client)` raises `RuntimeError` naming `bogus`.
- `test_no_startup_reconcilers.py`:
  - `test_main_does_not_reference_reconcilers`: the AST of `modules/backend/main.py` has no name or attribute containing `reconcile`.
  - `test_dispatch_does_not_reconcile`: the same check for `mission_plan_dispatch.py`.
- `test_reconciler_workflow.py` (time-skipping `WorkflowEnvironment`):
  - `test_workflow_runs_activity_with_grace`: the stub activity receives `ReconcileInput(orphan_grace_seconds=600)` and the workflow returns its stats.

**Done when:** `grep -rn --exclude-dir=migrations "mission_plan_crash_recovery\|reconcile_orphaned\|list_in_flight(" modules tests scripts` is empty, `scripts/verify_crash_recovery.py` does not exist, `temporal schedule describe --schedule-id system-reconciler` shows cron `*/5 * * * *`, and restarting the API during a live mission run leaves its tasks RUNNING (Verification step 6).

---

### 88.0.11 Schedule IDOR, write authorisation, and PATCH re-enable recompute

**Files**
- modify `modules/backend/repositories/workflow_schedule.py`
- modify `modules/backend/services/workflow_schedule.py`
- modify `modules/backend/api/v1/endpoints/missions_workflows.py`
- modify `modules/clients/cli/admin_groups/schedule.py`
- modify `modules/clients/cli/schedule_cmds.py`
- modify `tests/unit/backend/services/test_workflow_schedule.py`
- modify `tests/unit/backend/api/test_mission_schedules_api.py`

**Current state**
- PATCH (`missions_workflows.py:684-709`) and DELETE (`:712-735`) authorise against `mission_id` from the path, then act on `schedule_id` alone through `update_schedule(schedule_id, …)` and `delete_schedule(schedule_id)` (`services/workflow_schedule.py:182-219`). Any member of mission A can therefore edit or delete mission B's schedule.
- Create (`:648-681`) accepts a `workflow_definition_id` from any mission.
- All writes use read-level `require_mission_access` (`:661`, `:698`, `:725`).
- `update_schedule` recomputes `next_fire_at` only when `cron_expression` changes (`:182-196`). `mc schedule enable` sends `PATCH {"enabled": true}` (`clients/cli/mc_schedule.py:144-157`), so a re-enabled schedule fires immediately on its stale `next_fire_at`. Only `admin schedule enable` uses `toggle_enabled` (`:198-214`), which recomputes.

**Change**
1. Add `WorkflowScheduleRepository.get_for_mission(mission_id, schedule_id) -> WorkflowSchedule | None` (`WHERE id = :sid AND mission_id = :mid`).
2. Service signatures (all scoped):
   ```python
   async def get_schedule(self, mission_id: str, schedule_id: str) -> WorkflowSchedule: ...

   async def update_schedule(
       self, mission_id: str, schedule_id: str, **updates: Any
   ) -> WorkflowSchedule: ...

   async def toggle_enabled(
       self, mission_id: str, schedule_id: str, enabled: bool
   ) -> WorkflowSchedule: ...

   async def delete_schedule(self, mission_id: str, schedule_id: str) -> None: ...
   ```
   - `get_schedule` raises `NotFoundError` when the schedule is not in the mission. Every other method loads through it first.
   - `update_schedule` recomputes `next_fire_at = _compute_next_fire(updates.get("cron_expression") or schedule.cron_expression, utc_now())` when `cron_expression` is in `updates` or `updates.get("enabled") is True`.
   - `create_schedule` rejects a definition whose `mission_id` is neither NULL (system template) nor the target mission, with `NotFoundError(f"Workflow definition '{workflow_definition_id}' not found")`.
3. The create, PATCH and DELETE endpoints use `require_mission_operator` (88.0.9) and pass `mission_id` through to the service. GET stays `require_mission_access`.
4. Admin CLI: `schedule enable`, `disable` and `delete` gain a required `--mission MISSION_ID` option, passed through `run_schedule` to `toggle_enabled` and `delete_schedule`.

**Tests**
- `test_workflow_schedule.py`:
  - `test_get_schedule_other_mission_raises_not_found`
  - `test_update_schedule_enable_recomputes_next_fire_at`: `_compute_next_fire` patched to return `T`; enabling a disabled schedule with a stale `next_fire_at` gives `T`, called with the stored cron.
  - `test_update_schedule_disable_does_not_recompute`
  - `test_create_rejects_other_missions_definition`
- `test_mission_schedules_api.py`:
  - `test_patch_other_missions_schedule_returns_404`
  - `test_delete_other_missions_schedule_returns_404_and_row_survives`
  - `test_viewer_cannot_create_patch_or_delete`: 403 for each.
  - `test_maintainer_can_patch`

**Done when:** `grep -n "get_by_id_or_none(schedule_id)" modules/backend/services/workflow_schedule.py` is empty, and the tests pass.

---

### 88.0.12 Cron evaluation without croniter raises instead of firing hourly

**Files**
- modify `modules/backend/services/workflow_schedule.py`
- modify `tests/unit/backend/services/test_workflow_schedule.py`
- modify `tests/unit/backend/tasks/test_workflow_scheduler.py`

**Current state:** `_compute_next_fire` (`services/workflow_schedule.py:72-87`) returns `after + 1h` on `ImportError` (`:86-87`). `croniter` is in neither `requirements.txt` nor `pyproject.toml`, and `import croniter` fails in this environment. Every schedule therefore fires hourly whatever its cron says, including weekly schedules, and creation succeeds with a wrong `next_fire_at`.

**Change:** replace the `except ImportError` branch with `raise ValidationError("Cron evaluation unavailable: croniter is not installed. Workflow schedules cannot be created, enabled or fired until Plan 88 Phase 1 moves recurrence to Temporal Schedules.") from exc`, and change the return type to `datetime`.

Do **not** add croniter as a dependency, because Phase 1 (88.1.3) deletes this path. This has three consequences:
- create, enable and cron-change requests return 422;
- `evaluate_due_schedules` raises on the first due schedule, and its session rolls back before `record_fire`, so nothing fires;
- `evaluate_workflow_schedules` returns `status="error"`, as it already does on any exception (`tasks/workflow_scheduler.py:47-56`).

**Tests**
- `test_workflow_schedule.py`:
  - `test_compute_next_fire_raises_without_croniter`: `monkeypatch.setitem(sys.modules, "croniter", None)`, and `pytest.raises(ValidationError, match="croniter")`.
  - `test_create_schedule_rejected_without_croniter`
  - `test_evaluate_due_schedules_records_no_fire_without_croniter`: the due schedule's `last_fired_at` and `iteration_count` are unchanged.
- `test_workflow_scheduler.py::test_evaluate_returns_error_status_without_croniter`

**Done when:** `grep -n "hours=1" modules/backend/services/workflow_schedule.py` is empty, and the tests pass.

---

### 88.0.13 Web gate approval uses the real gate route; manual gates wake across processes

**Files**
- create `modules/frontend/src/hooks/use-gates.ts`
- modify `modules/frontend/src/hooks/use-executions.ts`
- modify `modules/frontend/src/components/mission/gate-approval.tsx`
- modify `modules/frontend/src/components/mission/active-run-card.tsx`
- modify `modules/frontend/src/components/live/live-results-panel.tsx`
- modify `modules/frontend/src/stores/live-run.ts`
- modify `modules/backend/api/v1/endpoints/missions_gates.py`
- modify `modules/backend/services/mission_plan.py`
- modify `modules/backend/agents/mission_control/gate_manual.py`
- modify `modules/backend/agents/mission_control/gate.py`
- modify `modules/backend/agents/mission_control/gate_post_run.py`
- create `tests/unit/backend/api/test_frontend_route_contract.py`
- modify `tests/unit/backend/agents/mission_control/test_gate_manual.py`

**Current state**
- `useSubmitApproval` posts to `/executions/{id}/submit-approval` (`use-executions.ts:152-171`), but the backend route is `/executions/{id}/approve` (`executions.py:389-393`), so every click is a 404.
- The component only renders on `agent.approval.requested` (`active-run-card.tsx:27-30`, `live-run.ts:260-278`), which no backend code emits (`ApprovalRequestedEvent` is never constructed).
- Real gates emit `gate.request.opened` (`gate_manual.py:209-226`) and are decided at `POST /missions/{id}/gates/{gid}/decide` (`missions_gates.py:176-251`), which the web never calls.
- That endpoint wakes the waiter through a process-local `asyncio.Event` (`gate_manual.py:41-60`; the call is `missions_gates.py:221`). The waiter runs in the Temporal worker process (inside `execute_mission`), so an API decision never wakes it, and every manual gate on the Temporal path times out to ABORT.
- The action vocabulary lives in the endpoint module (`missions_gates.py:260-280`), and `GateRequestDetail` (`:96`) does not expose it.
- `ManualGateReviewer.__init__` defaults `timeout_seconds` to `1800` (`gate_manual.py:78`), a hardcoded fallback.

**Change**
1. Backend:
   - Move `_STANDARD_ACTIONS`, `_POST_RUN_ACTIONS` and the vocabulary check (`missions_gates.py:260-280`) into `MissionPlanService` as `@staticmethod def allowed_gate_actions(gate_type: str) -> list[str]` (sorted). `_validate_action_for_gate_type` calls it.
   - Add `allowed_actions: list[str]` to `GateRequestDetail` (`missions_gates.py:96`), populated in `get_gate_request` (`:147-173`).
   - `decide_gate` (`:181`) uses `require_mission_operator` (in place of `require_mission_access` at `:196`) and deletes the `fire_decision` call (`:221`) and its import (`:22`).
2. `gate_manual.py`: delete `_LOCK`, `_PENDING` and `fire_decision` (`:41-60`), the `asyncio.Event` and its registration in `review` (`:90-94`), and the `finally` that pops it (`:180-182`). Replace `await asyncio.wait_for(event.wait(), timeout=self._timeout_seconds)` (`:110`) with `await self._wait_for_decision(request_id, context.mission_id)`, so the existing `except asyncio.TimeoutError` and `except asyncio.CancelledError` branches are unchanged:
   ```python
   async def _wait_for_decision(self, request_id: str, mission_id: str) -> None:
       """Poll the gate row until DECIDED; raise asyncio.TimeoutError at the deadline."""
       loop = asyncio.get_running_loop()
       deadline = loop.time() + self._timeout_seconds
       while loop.time() < deadline:
           await asyncio.sleep(self._poll_interval_seconds)
           async with self._session_factory() as session:
               row = await MissionPlanService(session).get_gate_request(mission_id, request_id)
           if row.status == GateRequestStatus.DECIDED:
               return
       raise asyncio.TimeoutError
   ```
   The constructor takes `timeout_seconds: int` and `poll_interval_seconds: int`, both required keywords with no default. Both construction sites (`gate.py:187`, `gate_post_run.py:97-100`) pass `get_app_config().gate.manual.timeout_seconds` and `get_app_config().gate.manual.poll_interval_seconds`.
3. Frontend:
   - `use-gates.ts` exports `useGateRequest(missionId, requestId)` (GET `` `/missions/${missionId}/gates/${requestId}` ``) and `useDecideGate(missionId)`, which posts `{action, reason}` to `` `/missions/${missionId}/gates/${requestId}/decide` ``.
   - `GateApproval` props become `{missionId, requestId, gateMessage?, onResolved}`, and it renders one button per `allowed_actions` entry from `useGateRequest`.
   - `live-run.ts` replaces the `agent.approval.requested` and `agent.approval.response` cases (`:260-278`) with `gate.request.opened`, which sets `pendingGate {missionId, requestId, gateType}`, and `gate.request.decided`, which clears it when `request_id` matches.
   - `active-run-card.tsx` finds the latest `gate.request.opened` with no later `gate.request.decided` for the same `request_id`. `live-results-panel.tsx` passes the new props.
   - Delete `useSubmitApproval` (`use-executions.ts:152-171`).

88.4.8 modifies `use-gates.ts` and `GateApproval` for durable gates.

**Tests**
- `test_frontend_route_contract.py`:
  - `test_no_frontend_reference_to_submit_approval`: no file under `modules/frontend/src` contains `submit-approval` or `agent.approval.requested`.
  - `test_gate_hook_targets_existing_route`: extracts the decide path template from `use-gates.ts` with a regex, normalises `${…}` to `{}`, and asserts that a route in `create_app().routes` normalises to the same `POST /api/v1/missions/{}/gates/{}/decide`.
  - `test_get_gate_returns_allowed_actions`: a `post_run` gate returns the five post-run actions.
  - `test_decide_requires_operator`: a VIEWER gets 403.
- `test_gate_manual.py` (DB, `poll_interval_seconds=1`, `timeout_seconds=5`). Delete the existing tests that call `fire_decision` or read `_PENDING`.
  - `test_review_returns_decision_written_by_another_session`: a concurrent task records the decision through a separate session after 1s; `review` returns that action.
  - `test_review_times_out_to_abort`.

**Done when:** `npm run build` and `npm run lint` in `modules/frontend` pass, `grep -rn --exclude-dir=migrations "fire_decision\|_PENDING" modules/backend` is empty, and the tests pass.

---

### 88.0.14 Telegram: fail-closed allowlist and mandatory webhook secret

**Files**
- modify `modules/clients/telegram/middlewares/auth.py`
- modify `modules/clients/telegram/webhook.py`
- modify `tests/unit/telegram/test_middlewares.py`
- create `tests/unit/telegram/test_webhook.py`

**Current state**
- `middlewares/auth.py:76-83`: an empty `telegram.authorized_users` logs "No authorized users configured, allowing all" and sets `user_role="admin"`. The repo config has `authorized_users: []` (`config/settings/application.yaml:73`), while its own comment says "empty = deny all" (`:26`). Any Telegram account is therefore an admin of the bot today.
- `webhook.py:58`: the `X-Telegram-Bot-Api-Secret-Token` header is checked only `if webhook_secret:`. With the secret unset, anyone who can reach the route can POST forged updates with any `from_user.id`.
- `gateway/security/startup_checks.py:88` rejects an empty secret when `channel_telegram_enabled` is true, but only when `features.security_startup_checks_enabled` is true (`main.py:35-38`). The route itself does not enforce it.
- `main.py:298-324` mounts the webhook router only when `channel_telegram_enabled`, and re-raises any `RuntimeError` from mounting, which aborts startup.

**Change**
1. `auth.py:76-83`: replace the branch with
   ```python
   if not authorized_users:
       logger.warning(
           "Telegram access denied: no authorized users configured (fail closed)",
           extra={"user_id": user_id},
       )
       return None
   ```
2. `webhook.py`, in `get_webhook_router` after `webhook_secret = settings.telegram_webhook_secret` (`:48`):
   ```python
   if not webhook_secret:
       raise RuntimeError(
           "TELEGRAM_WEBHOOK_SECRET is required when channel_telegram_enabled is true"
       )
   ```
   The `RuntimeError` propagates through `_mount_channel_adapters` (`main.py:316-324` re-raises), so the API refuses to start whatever `security_startup_checks_enabled` says.
3. `webhook.py:57-65`: delete the `if webhook_secret:` guard and dedent its body, so every request without a header, or with a header that fails `hmac.compare_digest`, gets 403 before the body is parsed.

88.4.9 relies on this step and does not repeat it.

**Tests**
- `test_middlewares.py`:
  - Delete `test_allows_all_when_no_authorized_users` (`:79`).
  - `test_empty_allowlist_denies`: `authorized_users = []`; the handler is not awaited and the middleware returns `None`.
- `test_webhook.py`:
  - `test_webhook_without_secret_config_refuses_start`: `telegram_webhook_secret = ""`; `get_webhook_router(bot, dp)` raises `RuntimeError`.
  - `test_webhook_missing_header_403`: with a configured secret, a POST without the header returns 403 and `dp.feed_update` is not awaited.
  - `test_webhook_wrong_header_403`.
  - `test_webhook_valid_header_accepted`: the update is fed to the dispatcher.

**Done when:** the tests pass, `grep -n "allowing all" modules/clients/telegram/middlewares/auth.py` is empty, and `grep -n "if webhook_secret:" modules/clients/telegram/webhook.py` is empty.

---

### Verification

```bash
cd /Users/herman.young/development/mission-control

# 1. Unit and integration suites
pytest tests/unit -v
pytest tests/integration/backend/temporal -v
pytest tests/integration/backend/services/test_mission.py -v

# 2. Static checks
ruff check modules tests
lint-imports
(cd modules/frontend && npm run build && npm run lint)

# 3. Deleted or forbidden code is gone (each command must print nothing)
grep -rn --exclude-dir=migrations "mission_plan_crash_recovery\|reconcile_orphaned\|list_in_flight(" modules tests scripts
grep -rn --exclude-dir=migrations "execution_mode" modules/backend/temporal
grep -rnE --exclude-dir=migrations 'or "autonomous"|gate_mode or |defaulting to CONTINUE' modules/backend
grep -rn "submit-approval\|agent.approval.requested" modules/frontend/src
grep -rn --exclude-dir=migrations "workflows/missions" modules
grep -n "hours=1" modules/backend/services/workflow_schedule.py
grep -rn --exclude-dir=migrations "fire_decision\|_PENDING" modules/backend
grep -n "allowing all" modules/clients/telegram/middlewares/auth.py

# 4. CLI surfaces still introspect
python mc.py tree && python admin.py tree

# 5. Reconciler schedule registered by the worker (start the worker first)
python -m modules.backend.temporal.worker &
temporal schedule describe --schedule-id system-reconciler
temporal schedule trigger --schedule-id system-reconciler
temporal workflow list --query 'WorkflowType="ReconcilerWorkflow"' --limit 1

# 6. API restart no longer fails live work
#    a) dispatch a mission with an autonomous plan; wait until a task is RUNNING
#    b) restart only the API process (uvicorn); then:
psql "$DATABASE_URL" -c "SELECT id, status FROM tasks WHERE status = 'RUNNING';"   # still RUNNING
#    c) temporal workflow cancel --workflow-id mission-run-<plan_id>; wait longer than orphan_grace_seconds + 300s
psql "$DATABASE_URL" -c "SELECT status, failure_reason FROM tasks WHERE plan_id = '<plan_id>' AND failure_reason LIKE 'orphaned:%';"

# 7. Missions now resolving to MANUAL (an owner or maintainer must set an explicit gate mode)
psql "$DATABASE_URL" -c "SELECT m.id, m.name, p.gate_mode FROM missions m JOIN mission_plans p ON p.mission_id = m.id WHERE p.gate_mode IS NULL OR p.gate_mode NOT IN ('interactive','manual','ai_assisted','autonomous');"

# 8. Telegram fails closed: with TELEGRAM_WEBHOOK_SECRET empty and channel_telegram_enabled true,
#    the API refuses to start; with the secret set, a POST without the header returns 403
curl -s -o /dev/null -w '%{http_code}\n' -X POST "http://127.0.0.1:8000/webhook/telegram" -d '{}'   # 403
```

Step 6 and step 7 use `gate_mode` values as stored today (lowercase strings, before `plan88_001`) and task status names (uppercase, `native_enum=False`). Step 8 uses the port the API is started on; the path is `application.yaml telegram.webhook_path`.

### Risks

1. **Open workflows at deploy.** Removing `MissionWorkflowInput.execution_mode` and changing activity options can break replay or decoding of in-flight `MissionRunWorkflow` and `ScheduledMissionCheckWorkflow` histories. **Mitigation:**
   - Run the entry-criteria query before deploy and cancel what it lists (`temporal workflow cancel --query '…'` with the same query).
   - Pause `mission-plan-dispatch-schedule` (`temporal schedule toggle --schedule-id mission-plan-dispatch-schedule --pause --reason "Plan 88 Phase 0 deploy"`) and unpause it after the worker restarts.
2. **Fail-closed gate modes stop unattended missions.** NULL, `workflow_managed` and unknown modes now resolve to MANUAL, so those missions stop auto-dispatching and wait for a human at each gate; Director refines no longer auto-approve them. **Mitigation:** Verification step 7 lists the affected missions. An owner or maintainer sets the intended mode with `PATCH /missions/{id}/plan {"gate_mode": …}`, which 88.0.9 restricts to operators. 88.0.13 makes manual decisions reach the worker, so MANUAL is usable, not a dead end.
3. **Workflow schedules stop firing until Phase 1** (88.0.12). Today they fire hourly regardless of cron. **Mitigation:** this is intended; Phase 1 is the next delivery. `evaluate_workflow_schedules` returns `status="error"` while any schedule is due, which is the visible signal.
4. **In-process runs are invisible to the reconciler.** `handle_mission` from the CLI and TUI, and `WorkflowRunService.run_workflow` from the CLI, the API (`missions_workflows.py:386`) and the dispatch loop (`loop.py:692`), run with no Temporal workflow. **Mitigation:** the reconciler selects only rows carrying a Temporal id (`temporal_workflow_id IS NOT NULL OR workflow_run_id IS NOT NULL` for execution records; a record with a Temporal id for workflow runs) and treats tasks owned by an in-process workflow run as live, so live in-process work is never failed (`test_in_process_record_without_ids_untouched`). **Residual:** a crashed in-process run leaves its rows RUNNING indefinitely. An operator clears them with `POST /executions/{id}/cancel` or `POST /missions/{id}/workflow-runs/{run_id}/cancel`, which are DB-only when no workflow id is stored; the next reconcile then fails the run's orphaned tasks.
5. **Infrastructure errors now fail the MissionRunWorkflow instead of becoming a silent "failed wave".** **Mitigation:** this is the intended visibility. The retry cannot re-run completed tasks (88.0.8 item 4), and the reconciler fails the orphaned tasks within `orphan_grace_seconds` plus one 5-minute schedule interval. Notifications arrive in Phase 4.
6. **Telegram stops answering on deployments with an empty allowlist** (88.0.14). This is the intended P8 behaviour. **Mitigation:** before deploy, set `telegram.authorized_users` in `application.yaml` to the operators' Telegram ids and set `TELEGRAM_WEBHOOK_SECRET` (at least the length `startup_checks.py:76` requires) in `config/.env`, then re-register the webhook with the secret.
