## Phase 2: Durable execution: per-task activities, idempotency, versioning

This phase delivers decisions 11 and 12. Each approved task in a wave runs as its own heartbeating Temporal activity. That activity has config-driven timeouts and an idempotency key, so a retry never re-runs or re-charges a completed task. `MissionRunWorkflow` becomes replay-safe for runs lasting weeks: config is pinned as workflow input, history is bounded by continue-as-new, idle waits are durable, code changes after this phase go through `workflow.patched`, and recorded histories are replayed in CI.

**Scope boundaries (3.0 Phase ownership):**
- **No budget enforcement.** Phase 2 contains no budget branch. `check_run_budget`, `BudgetService` and the run, monthly and lifetime caps arrive in 88.4.1 and 88.4.6, which add enforcement under patch id `p88-budget-caps`. This phase deletes `dispatch_approved` (88.2.6), so the plan-ceiling check it held leaves the Temporal path here (Risk 6).
- **Gates are a seam only.** 88.2.6 adds `MissionRunWorkflow._gate()`, which returns `"continue"`. 88.4.8 replaces its body under patch id `p88-durable-gate` (Risk 6).
- **No migration.** Phase 2 adds no Alembic revision. The head stays `plan88_003`.
- **Owned here:** the deletion of `AgentMissionWorkflow` (`temporal/workflow.py`), `POST /executions/{id}/execute`, `POST /executions/{id}/approve`, the web code that calls them, and the config keys only they read (88.2.6); continue-as-new (88.2.7, Phase 1 has none).

**Entry criteria:**
- `git status --porcelain` lists no changes under `modules/`, `config/`, `tests/`, `requirements*.txt`, `pyproject.toml`, `mc.py`, `admin.py` or `services.py`. Uncommitted work in progress (for example the model-provider changes in progress at the time of writing) is committed or stashed first. If such work is committed, re-verify by symbol the line citations below in the files it touched before starting.
- Phases 0 and 1 are merged to `main`. `alembic heads` returns only `plan88_003`. `plan88_002` already created `llm_calls.mission_run_id`, `llm_calls.task_id` and their indexes (3.1.12).
- These exist on `main`:
  - `models/mission_run.py` (`MissionRun`, `MissionRunStatus`, `MissionRunStatusReason`, `VALID_RUN_TRANSITIONS`) and `TaskRepository.list_by_run`;
  - `MissionRunService.start_run`, `begin`, `plan`, `task_graph`, and `finalise`, with `finalise` writing `cost_usd` from `llm_calls` and returning PROPOSED and APPROVED tasks to the backlog (88.1.7);
  - `MissionRunService.on_tasks_approved` and `TemporalWorkflowGateway.signal` (88.1.9);
  - `persist_mission_results(..., execution_record_id=...)` updating that record through `complete_execution` (88.1.7);
  - the activities `begin_mission_run`, `plan_mission_run`, `fetch_run_task_graph`, `set_mission_run_status`, `finalise_mission_run`, `approve_run_proposed_tasks`, `evaluate_post_run`, `fire_supervisor_followups`, `check_plan_active`, `start_director_turn` and `execute_mission` (taking `ExecuteWaveInput`);
  - `MissionRunWorkflow` started as `mission_run_workflow_id(mission_run_id)` (`temporal/workflow_ids.py`), with `@workflow.init` initialising the handler-owned fields `approved_seq`, `pause_requested`, `paused` and `decision` (contracts 3.3.3 names), and the 88.1.8 helpers `_end_run(status, reason, detail)`, `_exec(fn, arg, p)` and `_cause_type(e)`. Its loop is bounded and has no continue-as-new;
  - `temporal/activity_options.py` with `retry_policy(p: RetrySnapshot)` and `activity_kwargs(p)` (88.0.2);
  - `temporal/config_snapshots.py` with `policy_snapshot` and `config_hash` (88.0.2), and `build_run_config_snapshot` and `build_tick_config_snapshot` (88.1.5);
  - `temporal/workflow_gateway.py` with `TemporalWorkflowGateway` (88.0.3), the only owner of workflow handles, with `start_mission_run` (88.1.7) and `signal` (88.1.9);
  - `MissionContextManager.apply_updates` (`services/mission_context.py`) and the mapped column `ContextChange.mission_run_id` (88.1.2);
  - `tests/unit/backend/temporal/test_no_config_in_workflows.py` (88.1.8);
  - `activity_helpers.heartbeat_every` (88.1.8);
  - the `temporal.yaml` blocks `mission_run`, `reconciler` and `system_schedules` and their schema classes (88.0.2);
  - `reconcile_mission_runs` running over `mission_runs` (88.1.10a).
- `temporal/run_objective_workflow.py` and `temporal/scheduled_workflow.py` are deleted (88.1.8). `temporal/workflow.py` still exists; 88.2.6 deletes it.
- **Operational rule (until Phase 4 is complete).** Production keeps mission schedules disabled (`missions.recurrence.enabled: false`, added by 88.1.1; `MissionScheduleService.create_schedule` and the tick workflow refuse while it is false) and does not dispatch MANUAL or AI_ASSISTED missions, because budget enforcement and durable gates arrive in Phase 4 (Risk 6).
- If any item above is missing, stop. Do not start this phase.

**Baseline:** file:line references were verified at `a28ca771` (backend and config identical to `9adaa69d` and `777cd5c5`; frontend lines re-verified at `a28ca771`). Phases 0 and 1 edit several of these files first, so line numbers in those files are positions at `a28ca771`: locate the code by the symbol named next to each reference. Paths are relative to `modules/backend/` unless they start with `config/`, `tests/`, `scripts/`, `docs/`, `.github/` or `modules/frontend/`.

**Commits:** one commit per step, message `Plan 88 Phase 2: 88.2.N <step title>` (for example `Plan 88 Phase 2: 88.2.4 idempotent execute_plan_task activity`). The phase is pushed to `main` once, after Verification passes. 88.2.2 leaves `temporal/workflow.py` outside the config AST test until 88.2.6 deletes it; that is acceptable only because nothing is pushed before the phase completes.

### 88.2.1 Config: run hard stop and Copilot health keys

**Files:**
- modify `config/settings/temporal.yaml`, `config/settings/providers.yaml`, `core/config_schema.py`, `core/config.py`;
- create `tests/unit/backend/core/test_config_schema_plan88_phase2.py`.

**Current state:**
- The `mission_run:` block and `MissionRunSchema`, including the heartbeat validator, exist since 88.0.2. Neither carries a run duration limit.
- `ProvidersSchema` (`core/config_schema.py:553`) has no Copilot client settings, and `providers.yaml` is loaded with `_load_validated_optional` (`core/config.py:159`). The Copilot client is never health-checked (`core/copilot_model.py:419-434`).

**Change:**
1. **Delta to the existing `mission_run:` block** in `temporal.yaml`. Add one key, directly under `task_heartbeat_interval_seconds`:
   ```yaml
     max_run_duration_seconds: 43200   # 12h of active execution; human waits excluded (88.2.6)
   ```
2. **`MissionRunSchema`.** Add `max_run_duration_seconds: int = Field(..., ge=600)`. Do not touch the other fields or the heartbeat validator.
3. **Copilot client config.** Append to `providers.yaml`:
   ```yaml
   copilot_client:
     health_check_interval_seconds: 300
     ping_timeout_seconds: 10
   ```
   Add the schema and a required field on `ProvidersSchema`:
   ```python
   class CopilotClientSchema(_StrictBase):
       health_check_interval_seconds: int = Field(..., ge=30)
       ping_timeout_seconds: int = Field(..., ge=1, le=60)


   class ProvidersSchema(_StrictBase):
       copilot_client: CopilotClientSchema   # existing fields unchanged
   ```
4. **Loader.** `core/config.py:159` becomes `self._providers = _load_validated(ProvidersSchema, "providers.yaml")`. A missing file is now a startup failure, as P8 requires for a required section.

No key is deleted in this step. The keys read only by `AgentMissionWorkflow` are deleted with it in 88.2.6.

**Tests** (`test_config_schema_plan88_phase2.py`):
- `test_max_run_duration_loads_from_yaml`: `get_app_config().temporal.mission_run.max_run_duration_seconds == 43200`.
- `test_max_run_duration_required`: building `MissionRunSchema` from the repo YAML dict with `max_run_duration_seconds` removed raises `ValidationError`.
- `test_max_run_duration_floor`: `max_run_duration_seconds=599` raises `ValidationError`.
- `test_copilot_client_required`: `ProvidersSchema()` raises `ValidationError`.
- `test_copilot_client_loads_from_yaml`: `get_app_config().providers.copilot_client.ping_timeout_seconds == 10`.

**Done when:**
- `pytest tests/unit/backend/core/test_config_schema_plan88_phase2.py -q` passes.
- `python -c "from modules.backend.core.config import get_app_config; get_app_config()"` exits 0.

### 88.2.2 Config snapshot as workflow input; no config reads in workflow code

**Files:**
- modify `temporal/mission_run_models.py`, `temporal/config_snapshots.py`;
- modify `temporal/chat_workflow.py`, `temporal/chat_models.py`, `temporal/plan_refine_workflow.py`, `temporal/plan_refine_models.py`, `temporal/tool_fork_workflow.py`, `temporal/tool_fork_models.py`;
- modify every starter: `temporal/supervisor_activities.py:392` (`start_director_turn`), `temporal/tool_fork_activities.py:260`, `agents/mission/director/tools/design_workflow.py:58`, `agents/mission/director/tools/run_workflow.py:71`, `agents/mission/director/tools/refine_plan.py:67`, `api/v1/endpoints/missions_plan.py:179`, `api/v1/endpoints/missions_workflows.py:348`;
- modify `tests/unit/backend/temporal/test_no_config_in_workflows.py` (exists since 88.1.8);
- modify `tests/unit/backend/temporal/test_config_snapshots.py` (exists since 88.0.2);
- create `tests/unit/backend/temporal/test_workflow_timeouts_input.py`.

**Current state:**
- `policy_snapshot` and `config_hash` exist in `temporal/config_snapshots.py` since 88.0.2; `build_run_config_snapshot` and `build_tick_config_snapshot` exist there since 88.1.5. The `RunConfigSnapshot` dataclass (3.3.4) exists in `temporal/mission_run_models.py` since 88.1.5. It has no run duration and no heartbeat interval, so the workflow cannot enforce a hard stop or pass a heartbeat interval to a per-task activity.
- These workflow modules still read config:

  | File:line | Call | Disposition |
  |---|---|---|
  | `temporal/chat_workflow.py:31,57` | `get_app_config().temporal` | `input.timeouts` |
  | `temporal/plan_refine_workflow.py:20,44` | `get_app_config().temporal` | `input.timeouts` |
  | `temporal/tool_fork_workflow.py:29,78` | `get_app_config().temporal` (`DesignWorkflowWorkflow`) | `input.timeouts` |
  | `temporal/tool_fork_workflow.py:125` | `get_app_config().temporal` (`RunWorkflowWorkflow`) | `input.timeouts` |
  | `temporal/workflow.py:27,69` | `get_app_config().temporal` | file deleted in 88.2.6 |

- The same workflows hardcode activity-timeout floors: `chat_workflow.py:78-83` (`600`), `plan_refine_workflow.py:50` (`120`), `tool_fork_workflow.py:91` (`300`) and `:138` (`600`). With `min_activity_timeout_seconds: 600`, every floor already resolves to 600.
- `human_input_workflow.py`, `knowledge_workflow.py` and `maintenance_workflow.py` read no config.

**Change:**
1. **`temporal/mission_run_models.py`** (exists since 88.0.2). Add:
   ```python
   @dataclass(frozen=True)
   class WorkflowTimeoutsSnapshot:
       activity_timeout_seconds: int        # temporal.min_activity_timeout_seconds
       persistence_timeout_seconds: int     # temporal.persistence_timeout_seconds
       persistence_retry_max_attempts: int  # temporal.persistence_retry_max_attempts
   ```
   `RunConfigSnapshot` gains `max_run_duration_seconds: int` and `task_heartbeat_interval_seconds: int`, appended after `max_parallel_tasks`. The gate fields stay as 88.1.5 fills them (from `temporal.approval_timeout_seconds` and `temporal.escalation_timeout_seconds`) until 88.4.8 switches them to `gate.durable`.
2. **`temporal/config_snapshots.py`** (exists since 88.0.2, holds `policy_snapshot` and `config_hash`). It is the only module that builds snapshots. It may read config because it is not a workflow module. End state:
   ```python
   def policy_snapshot(schema: ActivityPolicySchema) -> ActivityPolicySnapshot: ...   # unchanged from 88.0.2
   def config_hash(obj: object) -> str: ...                                          # unchanged from 88.0.2
   def build_run_config_snapshot() -> RunConfigSnapshot: ...                         # 88.1.5; extended here
   def build_tick_config_snapshot() -> TickConfigSnapshot: ...                       # unchanged from 88.1.5
   def build_workflow_timeouts_snapshot() -> WorkflowTimeoutsSnapshot: ...           # new in 88.2.2
   ```
   - `build_run_config_snapshot()` is the ONLY builder of `RunConfigSnapshot`; the dataclass stays in `temporal/mission_run_models.py`. It maps `temporal.mission_run` 1:1 with `policy_snapshot`, including the two new fields, keeps the gate-field sources from 88.1.5, and sets `config_hash` last.
   - `build_run_config_snapshot` and `build_tick_config_snapshot` exist since 88.1.5; extend `build_run_config_snapshot` with `max_run_duration_seconds` and `task_heartbeat_interval_seconds`, and add `build_workflow_timeouts_snapshot`. `MissionRunService.start_run` and `MissionScheduleService` already call the 88.1.5 builders and do not change. `start_run` still stores `dataclasses.asdict(snapshot)` in `mission_runs.config_snapshot`.
3. **Workflow inputs.** Add `timeouts: WorkflowTimeoutsSnapshot = field(kw_only=True)` (required, no default) to `ChatTurnInput`, `PlanRefineInput`, `DesignWorkflowInput` and `RunWorkflowInput`. `kw_only` is needed because `ChatTurnInput` and `RunWorkflowInput` have defaulted fields; it is used on all four for one convention. Every starter listed under **Files** passes `timeouts=build_workflow_timeouts_snapshot()`.
4. **Workflow modules.** In `chat_workflow.py`, `plan_refine_workflow.py` and `tool_fork_workflow.py`, delete the `get_app_config` import and every call. Replace each `max(<config>.min_activity_timeout_seconds, N)` with `input.timeouts.activity_timeout_seconds`, which deletes the hardcoded floors. The persistence timeout and retry in `chat_workflow.py:61-70` read `input.timeouts.persistence_timeout_seconds` and `input.timeouts.persistence_retry_max_attempts`.
5. **Extend the AST test** (`test_no_config_in_workflows.py`):
   ```python
   TEMPORAL_DIR = Path("modules/backend/temporal")
   DELETED_IN_88_2_6 = frozenset({"workflow.py"})   # AgentMissionWorkflow; 88.2.6 deletes the file and this constant
   WORKFLOW_FILES = sorted(p for p in TEMPORAL_DIR.glob("*workflow*.py") if p.name not in DELETED_IN_88_2_6)
   FORBIDDEN = frozenset({"get_app_config", "get_default_budget_usd", "get_settings"})
   ```
   It parses each file with `ast` and collects every `ImportFrom` alias name, every `Name.id` and every `Attribute.attr` that is in `FORBIDDEN`. The 88.1.8 test function is replaced by the two tests below.

**Tests:**
- `test_no_config_in_workflows.py`:
  - `test_workflow_files_discovered`: `len(WORKFLOW_FILES) >= 6`.
  - `test_no_forbidden_config_access`, parametrised over `WORKFLOW_FILES` with `ids=lambda p: p.name`: the collected set is empty.
- `test_config_snapshots.py` (add to the 88.0.2 and Phase 1 tests; do not duplicate the `policy_snapshot` and `config_hash` tests):
  - `test_run_snapshot_hash_stable`: two calls to `build_run_config_snapshot()` give the same `config_hash`.
  - `test_run_snapshot_hash_changes_with_config`: changing `execute_task.start_to_close_seconds` through a monkeypatched `get_app_config` changes the hash.
  - `test_run_snapshot_carries_duration_and_heartbeat`: `max_run_duration_seconds == 43200` and `task_heartbeat_interval_seconds == 20` with the repo YAML.
  - `test_snapshot_round_trips_temporal_converter`: `DataConverter.default.encode([snapshot])`, then `decode(..., [RunConfigSnapshot])`, gives an equal object.
  - `test_single_snapshot_builder`: `grep -rn "def build_.*config_snapshot\|def policy_snapshot\|def snapshot_from_schema" modules/backend`, run through `subprocess`, matches only `temporal/config_snapshots.py`.
- `test_workflow_timeouts_input.py`:
  - `test_inputs_require_timeouts`: constructing each of `ChatTurnInput`, `PlanRefineInput`, `DesignWorkflowInput` and `RunWorkflowInput` without `timeouts` raises `TypeError`.

**Done when:**
- The three test files pass.
- `grep -rn "get_app_config\|get_default_budget_usd" modules/backend/temporal/chat_workflow.py modules/backend/temporal/plan_refine_workflow.py modules/backend/temporal/tool_fork_workflow.py modules/backend/temporal/mission_run_workflow.py` returns nothing.
- `grep -rn --exclude-dir=migrations "build_config_snapshot\b" modules` returns nothing.

### 88.2.3 Extract per-task execution from the dispatch loop

**Files:**
- create `agents/mission_control/dispatch/task_runner.py` and `agents/mission_control/runtime.py`;
- modify `agents/mission_control/dispatch/loop.py`, `agents/mission_control/mission_dispatch.py`, `agents/mission_control/persistence_bridge.py`, `agents/mission_control/helpers/agent_executor.py`, `agents/mission_control/helpers/cost_recorder.py`, `services/execution_persistence.py`, `services/mission_plan_taskio.py`;
- create `tests/unit/backend/mission_control/test_task_runner.py`.

**Current state:**
- `_execute_layer` (`dispatch/loop.py:227-489`) does all of the following inside one process:
  - per-task routing into four forks: convergence loop `:260-286`, research loop `:288-325`, `workflow:` tasks `:327-344` and standard agents `:346-391`;
  - upstream resolution through `resolve_upstream_inputs`;
  - context injection through `_inject_context` (`:762-794`);
  - the in-process approval wait `wait_until_approved` (`:406-416`);
  - parallel execution with `asyncio.gather` (`:418`);
  - MCD write-back through `context_curator.apply_task_updates` (`:437-451`);
  - the `post_layer` gate (`:458-482`).
- `handle_mission` (`mission_dispatch.py:45-457`) builds the runtime before it calls `dispatch` (`:415-434`): roster `derive_roster_from_team` (`:116`), `MissionContextManager`, `ContextCurator` and `ContextAssembler` (`:125-138`), the environment handle (`:364-412`) and the executor `_make_agent_executor` (`:418-424`, defined at `helpers/agent_executor.py:52`).
- `persist_mission_results` (`persistence_bridge.py:26-188`) writes `task_executions`, artifacts and attempts in a loop over the whole outcome (`:95-165`).
- `materialize_plan_dict` (`mission_plan_taskio.py:25-58`) builds every task dict at once (`:34-47`).
- `record_llm_call` (`helpers/cost_recorder.py:46`) has no run or task attribution. Its callers are `helpers/agent_executor.py:335` and `:624`.

**Change.** The in-process `dispatch()` stays for the direct callers of `handle_mission` (`clients/cli/execution_cmds.py:152,215`, `clients/tui/services/service_bridge.py:155`, `services/workflow_run_waves.py:655`, `agents/mission_control/mission_control.py:165`). Both the in-process path and the Temporal path share one per-task unit.

1. **`agents/mission_control/runtime.py`:**
   ```python
   @dataclass
   class DispatchRuntime:
       roster: Roster
       execute_agent_fn: ExecuteAgentFn
       context_curator: ContextCurator | None
       context_assembler: ContextAssembler | None
       environment_handle: object | None


   async def build_dispatch_runtime(
       *,
       db_session: AsyncSession,
       event_bus: EventBusProtocol,
       mission_id: str,
       session_id: str,
       execution_mode: str,
       mission_repo_root: str | None,
       container_image: str | None,
       extra_volumes: list[dict[str, str]] | None,
       mission_run_id: str | None,
       task_id: str | None,
   ) -> DispatchRuntime: ...
   ```
   - The body moves out of `mission_dispatch.py` without changing behaviour: roster (`:116`), context services (`:125-138`), environment (`:364-412`) and executor (`:418-424`). `handle_mission` calls it and passes `mission_run_id=None, task_id=None` for its in-process callers. Its legacy positional `execution_label` (renamed in 88.1.7) is a label, never a run id, and is not passed as `mission_run_id`.
   - `_make_agent_executor` gains the keyword-only arguments `mission_run_id: str | None` and `task_id: str | None`, and passes both to every `record_llm_call` (`helpers/agent_executor.py:335`, `:624`).
   - `record_llm_call` gains the keyword-only arguments `mission_run_id: str | None` and `task_id: str | None` and writes them to `llm_calls` (columns since `plan88_002`). This delivers the `task_id` attribution in 3.1.9 rule 2. If `models/llm_call.py` lacks the two mapped columns, add them here as `mapped_column(PgUUID(as_uuid=False), nullable=True)`.
2. **`dispatch/task_runner.py`:**
   ```python
   async def run_single_task(
       *,
       task: TaskDefinition,
       runtime: DispatchRuntime,
       upstream_outputs: dict[str, dict],
       mission_id: str,
       budget_usd: float,
       event_bus: EventBusProtocol,
       session_id: str,
       gate: GateReviewer | None,
   ) -> TaskResult: ...
   ```
   - The body is the per-task routing from `_execute_layer:250-391`: the four forks, `resolve_upstream_inputs` and `_inject_context`. `_inject_context` moves into `task_runner.py` unchanged; the learnings fix is 88.3.5, which edits it in this file.
   - It runs one coroutine and returns its `TaskResult`. On `KeyError` from upstream resolution or a roster miss it returns `failed_result(...)`, exactly as the loop does today.
   - `gate=None` means `NoOpGate()`. `budget_usd` feeds only `GateContext`, as it does today.
   - It does not apply MCD updates. The caller does.
3. **`loop.py`.** `_execute_layer` builds one `run_single_task(...)` coroutine per task id, passing its own `gate` and `mission_budget_usd`. It keeps the `wait_until_approved` waiters, `gather`, MCD write-back and the `post_layer` gate exactly as they are. Target: `loop.py` under 600 lines, down from 852.
4. **`persistence_bridge.py`.** Extract the loop body at `:95-165` into:
   ```python
   async def persist_task_result(
       service: ExecutionPersistenceService,
       *,
       execution_record_id: str,
       task_result: TaskResult,
       mission_id: str | None,
       domain_tags: list[str] | None,
       mission_run_id: str | None,
       idempotency_key: str | None,
   ) -> TaskExecution: ...
   ```
   It writes the `task_executions` row, the artifact (`_maybe_create_artifact`) and the retry attempts. `persist_mission_results` calls it once per task result with `mission_run_id=None, idempotency_key=None`.
   `ExecutionPersistenceService.save_task_execution` (`services/execution_persistence.py:207`) gains the keyword arguments `mission_run_id: str | None` and `idempotency_key: str | None`, written to the 3.1.8 columns.
5. **`mission_plan_taskio.py`:**
   - Extract the per-task dict builder (`:34-47`) into `task_definition_from_row(task: Task) -> TaskDefinition`, which returns `TaskDefinition.model_validate(<dict>)`. `materialize_plan_dict` calls it.
   - Add `async def load_dependency_outputs(session: AsyncSession, task_id: str) -> dict[str, dict]`. It reads `result_summary` of the task's direct dependencies (`task_dependencies.depends_on_id`), keyed by task id, with the JSON decode used by `load_prior_outputs` (`:142-148`), whatever run they completed in. Explicit dependency edges are not bounded by run. Prior-output context injection is bounded by run, which is 88.3.5's change to `load_prior_outputs`.

**Tests:**
- `test_task_runner.py`, using a fake `DispatchRuntime` and `NoOpEventBus`:
  - `test_standard_task_calls_executor_once`: the result is SUCCESS and the executor was called once.
  - `test_roster_miss_returns_failed_result`: `status == FAILED` and the reason is "Agent not found in roster".
  - `test_missing_upstream_returns_failed_result`: `from_upstream` refers to an absent key and the result is FAILED.
  - `test_research_loop_routed`: `inputs.static.type="research_loop"` invokes the patched `_dispatch_research_loop`.
  - `test_workflow_agent_routed`: `agent="workflow:x"` invokes `_dispatch_workflow_task`.
  - `test_no_mcd_write`: the curator's `apply_task_updates` is not called.
- `tests/unit/backend/mission_control/test_dispatch.py` passes unchanged. It is the regression guard for the in-process path.
- `tests/unit/backend/agents/mission_control/test_gate.py` passes unchanged.

**Done when:**
- `pytest tests/unit/backend/mission_control tests/unit/backend/agents/mission_control -q` passes.
- `lint-imports` passes with no new `ignore_imports` entry.
- `grep -n "async def _inject_context" modules/backend/agents/mission_control/dispatch/task_runner.py` matches, and the same grep on `loop.py` matches nothing.

### 88.2.4 Idempotent `execute_plan_task` activity with heartbeats

**Files:**
- create `services/run_task_execution.py` and `temporal/task_activities.py`;
- modify `models/task.py`, `services/mission_context.py`, `temporal/mission_run_models.py`, `temporal/activity_helpers.py`, `temporal/mission_run_activities.py`, `temporal/worker.py`;
- create `tests/integration/backend/services/test_run_task_execution.py` and `tests/unit/backend/temporal/test_task_activities.py`.

**Current state:**
- The whole wave is one activity, `execute_mission`, taking `ExecuteWaveInput` (88.1.8). A retry re-dispatches the whole wave.
- `retry_task` (`services/mission_plan.py:523-555`) increments `retry_count` (`:539`), and `write_back_task_results` increments it again (`mission_plan_taskio.py:208`, `:231`). 88.2.6 deletes `write_back_task_results`, which leaves `retry_task` as the only increment.
- `VALID_TASK_TRANSITIONS` (`models/task.py:58-67`) has no exit from FAILED except APPROVED (`:63`).
- `heartbeat_every(interval_seconds, phase)` (88.1.8) takes the interval from its caller and a fixed phase string; it yields nothing, so a caller cannot change the phase. Its callers are `plan_mission_run` (`"planning"`) and `execute_mission` (`"executing"`, deleted in 88.2.6).
- `MissionContextManager.apply_updates` (`services/mission_context.py:238-246`) takes `agent_id`, `mission_id_ref` and `task_id` and cannot attribute a change to a run, although `context_changes.mission_run_id` exists since `plan88_002`.

**Change:**
1. **`models/task.py:63`.** `TaskStatus.FAILED` maps to `frozenset({TaskStatus.APPROVED, TaskStatus.SKIPPED})`, so a gate `skip` can close a failed task.
2. **DTOs** in `temporal/mission_run_models.py` (3.3.5 shapes):
   ```python
   @dataclass(frozen=True)
   class ExecuteTaskInput:
       mission_run_id: str
       task_id: str
       session_id: str
       execution_record_id: str
       budget_headroom_usd: float | None    # None in Phases 2-3; 88.4.6 sets it under p88-budget-caps
       heartbeat_interval_seconds: int


   @dataclass(frozen=True)
   class ExecuteTaskResult:
       task_id: str
       status: str                          # "completed" | "failed" | "skipped" (lowercase TaskStatus values, 3.0.2)
       verification_failed: bool
       cost_usd: float
       idempotent_replay: bool
       failure_reason: str | None


   @dataclass(frozen=True)
   class ResolveTaskInput:
       mission_run_id: str
       task_id: str
       action: str                          # "retry" | "skip"
   ```
3. **`services/run_task_execution.py`.** It must not import `modules.backend.agents`.
   ```python
   @dataclass
   class TaskClaim:
       outcome: Literal["execute", "replay"]
       idempotency_key: str
       task_definition: TaskDefinition | None   # "execute" only
       stored: ExecuteTaskResult | None         # "replay" only
       mission_id: str
       execution_mode: str
       mission_repo_root: str | None


   class RunTaskExecutionService(BaseService):
       async def claim(self, mission_run_id: str, task_id: str) -> TaskClaim: ...

       async def record(
           self,
           *,
           mission_run_id: str,
           task_id: str,
           idempotency_key: str,
           execution_record_id: str,
           task_result_json: dict,
       ) -> ExecuteTaskResult: ...

       async def mark_cancelled(self, mission_run_id: str, task_id: str) -> None: ...

       async def resolve_failed(
           self, mission_run_id: str, task_id: str, action: Literal["retry", "skip"]
       ) -> None: ...
   ```
   - **`claim`, transaction A (short):**
     1. `SELECT … FROM tasks WHERE id = :task_id AND mission_run_id = :run_id FOR UPDATE`. A missing row raises `MissionRunStateError`.
     2. `key = f"{mission_run_id}:{task_id}:{task.retry_count}"`.
     3. If a `task_executions` row with `idempotency_key = key` exists, return outcome `"replay"` with `stored` rebuilt from that row and `idempotent_replay=True`.
     4. If `task.status` is COMPLETED or SKIPPED with no such row, return outcome `"replay"` with `stored = ExecuteTaskResult(task_id, task.status.value, False, float(task.cost_usd), True, task.failure_reason)`.
     5. Status APPROVED transitions APPROVED→QUEUED→RUNNING; QUEUED transitions QUEUED→RUNNING; RUNNING stays RUNNING (3.1.9 rule 2, interrupted attempt). Any other status raises `MissionRunStateError`.
     6. Set `last_attempt_at = utc_now()`. Read `mission.execution_environment` (`"local"` when NULL, as `dispatch_approved` does today) and `mission.repo_root`. Build `task_definition = task_definition_from_row(task)`. Commit.

     The row lock is released before the agent call, which can last up to `execute_task.start_to_close_seconds`. The UNIQUE `idempotency_key` arbitrates between concurrent attempts.
   - **`record`, transaction B (short):**
     1. Lock the task row again. If a row with `idempotency_key = key` exists, roll back and return it with `idempotent_replay=True`: a duplicate attempt finished first.
     2. Otherwise, in one transaction:
        - `persist_task_result(..., execution_record_id=execution_record_id, mission_run_id=mission_run_id, idempotency_key=key)`;
        - when the result status is SUCCESS and `context_updates` is not empty, `MissionContextManager(self._session).apply_updates(mission_id, task_result.context_updates, agent_id=task_result.agent_name, mission_id_ref=mission_id, task_id=task_id, mission_run_id=mission_run_id)`. 88.3.2 replaces `mission_id_ref` with `reason` and keeps `mission_run_id`;
        - the task transition, mapping `TaskResult.status` SUCCESS to COMPLETED, FAILED and TIMEOUT to FAILED, SKIPPED to SKIPPED;
        - `tasks.cost_usd`, `tasks.duration_seconds`, and `tasks.result_summary = json.dumps(task_result.output_reference)` on COMPLETED or `tasks.failure_reason` on FAILED.
     3. Commit.
     4. An `IntegrityError` on the `idempotency_key` unique index is caught: roll back, re-read the row and return it with `idempotent_replay=True`.
     - `verification_failed` is `status == FAILED and any(t.status == "fail" for t in (vo.tier_1, vo.tier_2, vo.tier_3))`, where `vo` is the result's `verification_outcome`. The same rule rebuilds `verification_failed` from a stored row.
     - `retry_count` is not touched.
   - **`mark_cancelled`** transitions RUNNING→FAILED with `failure_reason="cancelled"` and commits, in its own session.
   - **`resolve_failed`** loads the task with `WHERE id = :task_id AND mission_run_id = :run_id`, else `NotFoundError`.
     - `retry` calls `MissionPlanService.retry_task(plan_id, task_id, user_id=mission.owner_id)`. That is the only `retry_count` increment.
     - `skip` transitions FAILED→SKIPPED.
4. **`activity_helpers.heartbeat_every`** (exists since 88.1.8). Its end-state signature is:
   ```python
   @dataclass
   class HeartbeatState:
       phase: str


   @asynccontextmanager
   async def heartbeat_every(interval_seconds: float, *, phase: str) -> AsyncIterator[HeartbeatState]: ...
   ```
   It heartbeats `{"phase": state.phase}` on entry and then every `interval_seconds`, and cancels its asyncio task on exit. The caller may set `state.phase`. `plan_mission_run` passes `get_app_config().temporal.mission_run.task_heartbeat_interval_seconds` explicitly and `phase="planning"` as a keyword. The `execute_mission` call site is left as it is; 88.2.6 deletes it.
5. **`MissionContextManager.apply_updates`** (`services/mission_context.py:238`). Add the keyword-only argument `mission_run_id: str | None = None`, matching the existing optional keywords, and write it to every `ContextChange` row the call inserts (`ContextChange.mission_run_id`, mapped since 88.1.2). No other caller changes in this step. 88.3.2 makes the argument required and passes it from every caller.
6. **`temporal/task_activities.py`:**
   ```python
   @activity.defn
   async def execute_plan_task(input: ExecuteTaskInput) -> ExecuteTaskResult:
       async with heartbeat_every(input.heartbeat_interval_seconds, phase="claim") as hb:
           async with get_async_session() as db:
               claim = await RunTaskExecutionService(db).claim(input.mission_run_id, input.task_id)
           if claim.outcome == "replay":
               return claim.stored
           await CopilotModel.ensure_healthy()                                  # 88.2.5
           hb.phase = "agent"
           redis = AsyncRedis.from_url(get_redis_url())
           try:
               bus = SessionEventBus(redis, mission_id=claim.mission_id)
               async with get_async_session() as db:                            # read-only use; no commit
                   runtime = await build_dispatch_runtime(
                       db_session=db, event_bus=bus, mission_id=claim.mission_id,
                       session_id=input.session_id, execution_mode=claim.execution_mode,
                       mission_repo_root=claim.mission_repo_root, container_image=None,
                       extra_volumes=None, mission_run_id=input.mission_run_id, task_id=input.task_id,
                   )
                   upstream = await load_dependency_outputs(db, input.task_id)
                   result = await run_single_task(
                       task=claim.task_definition, runtime=runtime, upstream_outputs=upstream,
                       mission_id=claim.mission_id, budget_usd=0.0, event_bus=bus,
                       session_id=input.session_id, gate=None,
                   )                                                            # budget_usd feeds GateContext only; gate=None ignores it
           except asyncio.CancelledError:
               async with get_async_session() as db:
                   await RunTaskExecutionService(db).mark_cancelled(input.mission_run_id, input.task_id)
               raise
           finally:
               await redis.aclose()
           hb.phase = "record"
           async with get_async_session() as db:
               return await RunTaskExecutionService(db).record(
                   mission_run_id=input.mission_run_id,
                   task_id=input.task_id,
                   idempotency_key=claim.idempotency_key,
                   execution_record_id=input.execution_record_id,
                   task_result_json=result.model_dump(mode="json"),
               )


   @activity.defn
   async def resolve_failed_task(input: ResolveTaskInput) -> None:
       async with get_async_session() as db:
           await RunTaskExecutionService(db).resolve_failed(input.mission_run_id, input.task_id, input.action)
   ```
   - The activity raises only for infrastructure errors. A failed agent task returns `status="failed"`, so Temporal never retries an agent failure.
   - `resolve_failed_task` uses the `persistence` policy.
7. **`temporal/worker.py`.** Register `execute_plan_task` and `resolve_failed_task`.

**Tests:**
- `test_run_task_execution.py` (integration, real DB):
  - `test_claim_completed_task_replays`: a COMPLETED task gives outcome `"replay"`, `idempotent_replay=True`, and the `llm_calls` count is unchanged.
  - `test_claim_existing_key_replays`: a `task_executions` row with the key exists while the task is RUNNING; the outcome is `"replay"`.
  - `test_claim_running_reexecutes_same_key`: a RUNNING task gives outcome `"execute"` with `idempotency_key.endswith(":0")`.
  - `test_claim_approved_moves_to_running`: the status is RUNNING after commit.
  - `test_claim_other_runs_task_raises`: a task whose `mission_run_id` is another run raises `MissionRunStateError`.
  - `test_record_atomic`: an exception injected into `apply_task_updates` leaves no `task_executions` row, the status RUNNING and `cost_usd == 0`.
  - `test_record_duplicate_returns_first`: two `record` calls with the same key leave one row and return the second with `idempotent_replay=True`.
  - `test_record_writes_result_summary_json`: a COMPLETED task's `result_summary` decodes to the result's `output_reference`.
  - `test_record_context_changes_carry_run_id`: a SUCCESS result with one context update writes a `context_changes` row whose `mission_run_id` is the run's id.
  - `test_replay_status_is_lowercase_value`: a COMPLETED task replays with `stored.status == "completed"`.
  - `test_retry_increments_once`: FAILED then `resolve_failed("retry")` gives `retry_count == 1` and a next claim key ending `:1`.
  - `test_skip_failed_task`: FAILED then `resolve_failed("skip")` gives SKIPPED.
  - `test_resolve_other_runs_task_404`: `resolve_failed` with another run's id raises `NotFoundError`.
- `test_task_activities.py` (unit, `ActivityEnvironment` from `temporalio.testing`, with the services and `run_single_task` patched):
  - `test_replay_skips_agent`: when `claim` returns outcome `"replay"`, `run_single_task` is not awaited.
  - `test_heartbeats_emitted`: interval 0.01s and an agent that sleeps 0.05s give at least 3 heartbeats, each with a `phase` key.
  - `test_cancel_marks_failed_and_reraises`: cancelling the environment calls `mark_cancelled` and raises `CancelledError`.
  - `test_agent_failure_returns_failed_not_raises`: a FAILED `TaskResult` gives `status == "failed"`.

**Done when:** both test files pass, and `python -m modules.backend.temporal.worker` starts with no import errors.

### 88.2.5 Copilot client health check and restart

**Files:**
- modify `core/copilot_model.py`;
- create `tests/unit/backend/core/test_copilot_health.py`.

**Current state:**
- `CopilotModel._client`, `_started` and `_lock` are process globals (`copilot_model.py:373-375`). The client is started once in `_ensure_client` (`:419-434`) and never checked or restarted. The lock is created lazily at `:420-421`.
- `_classify_session_error` (`:444`) is synchronous, so it cannot stop the client. Its callers are at `:638`, `:653` and `:779`. `classify_provider_error` returns `TransientProviderError` (`core/exceptions.py:194`) for transient connection errors.
- The installed SDK exposes `ping()` and `get_auth_status()` (async, `.isAuthenticated`), `get_state()` (sync: `"disconnected" | "connecting" | "connected" | "error"`), `stop()` and `force_stop()` (async).

**Change:**
```python
_last_health_check: float = 0.0          # class attribute, time.monotonic()

@classmethod
def _get_lock(cls) -> asyncio.Lock:
    if cls._lock is None:
        cls._lock = asyncio.Lock()
    return cls._lock

@classmethod
async def _reset_client(cls) -> None:
    """Stop and drop the shared client so the next request starts a new one. Caller holds the lock."""
    if cls._client is not None:
        await cls._client.force_stop()
    cls._client, cls._started = None, False

@classmethod
async def ensure_healthy(cls) -> None:
    """Called at the start of every execute_plan_task. No-op when no client exists yet."""
    cfg = get_app_config().providers.copilot_client
    if cls._client is None or time.monotonic() - cls._last_health_check < cfg.health_check_interval_seconds:
        return
    async with cls._get_lock():
        healthy = cls._client.get_state() == "connected"
        if healthy:
            try:
                await asyncio.wait_for(cls._client.ping(), timeout=cfg.ping_timeout_seconds)
                healthy = (await cls._client.get_auth_status()).isAuthenticated
            except (asyncio.TimeoutError, OSError, RuntimeError, ConnectionError):
                healthy = False
        if not healthy:
            logger.warning("Copilot client unhealthy, restarting", extra={"state": cls._client.get_state()})
            await cls._reset_client()
        cls._last_health_check = time.monotonic()
```
- `_ensure_client` uses `CopilotModel._get_lock()` in place of the lazy creation at `:420-421`.
- At each `_classify_session_error` call site (`:638`, `:653`, `:779`), when the classified error is a `TransientProviderError`, run `async with CopilotModel._get_lock(): await CopilotModel._reset_client()` before re-raising, so the next call starts a new client.
- `temporal/task_activities.py` imports `CopilotModel` from `core/copilot_model.py` directly.

**Tests** (`test_copilot_health.py`, with a fake client):
- `test_skips_within_interval`: `ping` is not called.
- `test_restart_on_disconnected_state`: `force_stop` is called and `_client is None`.
- `test_restart_on_ping_timeout`.
- `test_restart_on_unauthenticated`.
- `test_healthy_client_kept`: the same object is kept and `force_stop` is not called.
- `test_transient_error_resets_client`: a send raising a message that `classify_provider_error` maps to `TransientProviderError` leaves `_client is None` and re-raises.

**Done when:** `pytest tests/unit/backend/core/test_copilot_health.py -q` passes.

### 88.2.6 MissionRunWorkflow: per-task layers, durable WAIT, hard stop, legacy paths deleted

**Files:**
- modify `temporal/mission_run_workflow.py`, `temporal/mission_run_models.py`, `temporal/supervisor_activities.py`, `temporal/worker.py`, `agents/mission_control/gate_post_run.py`, `agents/adapters/plan_introspection.py`, `services/execution_persistence.py`, `services/mission_run.py`, `services/mission_plan.py`, `services/mission_plan_orchestrator.py`, `repositories/task.py`, `api/v1/endpoints/missions_plan.py`, `api/v1/endpoints/executions.py`, `core/config_schema.py`, `config/settings/temporal.yaml`;
- modify `temporal/chat_workflow.py:16` and `temporal/human_input_workflow.py:4` (docstrings naming `AgentMissionWorkflow`);
- modify `modules/frontend/src/hooks/use-executions.ts`, `modules/frontend/src/pages/mission/run-live.tsx`;
- modify `scripts/trace_execution.py:396`, `scripts/verify_autonomy_loop.py:109,456`;
- modify `tests/unit/backend/temporal/test_no_config_in_workflows.py`, `tests/unit/backend/temporal/test_config.py`;
- delete `temporal/workflow.py`, `temporal/activities.py` (`execute_mission`, `persist_mission_outcome` and `send_notification` are its only contents), `temporal/models.py`, `services/mission_plan_dispatch.py`;
- delete `tests/unit/backend/temporal/test_activities.py`, `tests/unit/backend/temporal/test_models.py`, and the classes `TestWriteBackTaskResults` and `TestDeriveSubsetTaskPlan` in `tests/unit/backend/services/test_mission_plan_orchestrator.py` (`:181-322`);
- create `tests/integration/backend/temporal/test_mission_run_workflow.py` and `tests/integration/backend/temporal/mission_run_stubs.py`.

**Current state** (after Phase 1):
- Each wave is one `execute_mission` activity that calls `orchestrator.dispatch_approved(...)` (`services/mission_plan_dispatch.py:127-379`), which calls `handle_mission`, persists, and writes back with `write_back_task_results` (`mission_plan_taskio.py:151-236`). `persist_mission_outcome` (`temporal/activities.py:214-320`) follows it.
- The supervisor `wait` arm loops straight back to the top of the loop. 88.1.8 has no workflow iteration cap; the loop is bounded by breaker #2.
- Breaker #2, `max_supervisor_iterations`, is at `gate_post_run.py:130-139`. `_do_evaluate_post_run` increments `plan.supervisor_iteration_count` (`supervisor_activities.py:169`) and feeds the reviewer `plan.total_spent_usd`, which only `dispatch_approved` updates (`mission_plan_dispatch.py:318`).
- `AgentMissionWorkflow` (`temporal/workflow.py`) is started only by `POST /executions/{id}/execute` (`executions.py:193-345`, Temporal branch `:231-271`), signalled by `POST /executions/{id}/approve` (`executions.py:389-451`), and queried by the Temporal branch of `GET /executions/{id}/status` (`executions.py:474-499`). The web calls `/execute` through `useStartExecution` (`use-executions.ts:130-139`) from the auto-start effect in `run-live.tsx:49-59`. 88.0.13 already deleted `useSubmitApproval`.
- Config keys read only by `AgentMissionWorkflow` and `executions.py:253-255`: `budget_timeout_multiplier_seconds` (`workflow.py:72`), `execution_retry_max_attempts`, `execution_retry_initial_interval_seconds`, `execution_retry_max_interval_seconds` (`workflow.py:86-91`) and `notification_timeout_seconds` (`workflow.py:77`, `executions.py:255`). `approval_timeout_seconds` and `escalation_timeout_seconds` are also read by `agents/mission_control/approval.py:29`, `escalation.py:54,60`, `services/workflow_run_steps/human_input.py:55` and the 88.1.5 snapshot gate fields, so they stay.
- After `execute_mission` goes, nothing calls `dispatch_approved`. `temporal/models.py` holds only `AgentMissionWorkflow` DTOs.

**Change.**

1. **Workflow state.** `MissionRunWorkflowState` gains `run_started_at: datetime` and `excluded_wait_seconds: int`. The state built after `begin_mission_run` sets `run_started_at=workflow.now()` and `excluded_wait_seconds=0`. Delete `ExecuteWaveInput`.
2. **Main loop.** Keep the 88.1.8 begin/plan prologue and the `asyncio.CancelledError` handler unchanged. Replace the loop with:
   ```python
   while True:
       seen = self._approved_seq                     # recorded before the fetch (contracts 3.3.3)
       graph = await _exec(fetch_run_task_graph, inp.mission_run_id, inp.config.persistence)
       if graph.approved == 0:
           if graph.proposed == 0:
               return await self._end_run("succeeded", "no_further_work", None)
           await self._wait_for_approval(seen)
           continue
       self._state.iteration += 1                    # one iteration == one executed wave
       end = await self._execute_layers(graph)
       if end is not None:
           return end
       end = await self._supervise(seen)
       if end is not None:
           return end
   ```
   `_supervise(seen)` holds the 88.1.8 supervisor block unchanged (`evaluate_post_run`, `fire_supervisor_followups`, `check_plan_active`, then the branches on `ev.action`), except two points: the `wait` arm (item 5), and the wave fields of `SupervisorFollowupInput`, which now come from the per-task results (item 3): `wave_status=self._wave_status`, `wave_cost_usd=self._wave_cost_usd`, `failure_reason=self._wave_failure_reason`. `check_plan_active` stays in Phase 2: 88.4.2 rewrites its body to read `missions.status`, 88.4.5 stops calling it under patch id `p88-lifecycle-signals`, and it is deleted in 88.4.5 only when no caller remains.
3. **Layers.** Every activity call goes through `_exec` or `activity_kwargs`; none reads config.
   ```python
   async def _execute_layers(self, graph: RunTaskGraph) -> str | None:
       cfg = self._input.config
       self._phase = "executing"
       self._wave_results: dict[str, ExecuteTaskResult] = {}   # final result per task id, in execution order
       if await self._gate("pre_dispatch", None) == "abort":
           return await self._end_run("cancelled", "gate_rejected", "aborted at pre_dispatch")
       for layer in graph.layers:
           if await self._gate("pre_layer", None) == "abort":
               return await self._end_run("cancelled", "gate_rejected", "aborted at pre_layer")
           for start in range(0, len(layer), cfg.max_parallel_tasks):
               end = await self._layer_boundary()
               if end is not None:
                   return end
               chunk = layer[start:start + cfg.max_parallel_tasks]
               outcomes = await asyncio.gather(*(self._run_task(t) for t in chunk), return_exceptions=True)
               for outcome in outcomes:
                   if isinstance(outcome, BaseException) and not isinstance(outcome, ActivityError):
                       raise outcome
               failed = [o for o in outcomes if isinstance(o, ActivityError)]
               if failed:
                   return await self._end_run("failed", "task_failures", str(failed[0])[:500])
               for task_id, result in zip(chunk, outcomes):
                   end = await self._after_task(task_id, result)
                   if end is not None:
                       return end
           if await self._gate("post_layer", None) == "abort":
               return await self._end_run("cancelled", "gate_rejected", "aborted at post_layer")
       results = list(self._wave_results.values())
       failed_results = [r for r in results if r.status == "failed"]
       self._wave_status = "failed" if failed_results else "completed"
       self._wave_cost_usd = sum(r.cost_usd for r in results)
       self._wave_failure_reason = failed_results[0].failure_reason if failed_results else None
       return None

   async def _layer_boundary(self) -> str | None:
       if self._duration_exhausted():
           return await self._end_run("failed", "max_duration_exceeded",
                                      "max_run_duration_seconds reached at a layer boundary")
       return None

   async def _run_task(self, task_id: str) -> ExecuteTaskResult:
       cfg = self._input.config
       return await workflow.execute_activity(
           execute_plan_task,
           ExecuteTaskInput(
               mission_run_id=self._input.mission_run_id,
               task_id=task_id,
               session_id=self._state.session_id,
               execution_record_id=self._state.execution_record_id,
               budget_headroom_usd=None,
               heartbeat_interval_seconds=cfg.task_heartbeat_interval_seconds,
           ),
           cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
           **activity_kwargs(cfg.execute_task),
       )

   async def _after_task(self, task_id: str, result: ExecuteTaskResult) -> str | None:
       self._wave_results[task_id] = result
       while result.verification_failed:
           action = await self._gate("verification_failed", task_id)
           if action == "abort":
               return await self._end_run("cancelled", "gate_rejected", f"aborted at verification_failed for {task_id}")
           if action not in ("retry", "skip"):
               return None                           # "continue" from the Phase 2 seam: the task stays FAILED
           await _exec(resolve_failed_task, ResolveTaskInput(self._input.mission_run_id, task_id, action),
                       self._input.config.persistence)
           if action == "skip":
               self._wave_results[task_id] = dataclasses.replace(result, status="skipped")
               return None
           if self._duration_exhausted():
               return await self._end_run("failed", "max_duration_exceeded", "max_run_duration_seconds reached before a retry")
           try:
               result = await self._run_task(task_id)
           except ActivityError as err:
               return await self._end_run("failed", "task_failures", str(err)[:500])
           self._wave_results[task_id] = result
       if result.status == "completed" and await self._gate("post_task", task_id) == "abort":
           return await self._end_run("cancelled", "gate_rejected", f"aborted at post_task for {task_id}")
       return None
   ```
   A FAILED task without a verification failure stays FAILED and no gate runs; the supervisor sees it in `evaluate_post_run`. `_layer_boundary()` runs before each chunk. 88.4.5 and 88.4.6 extend `_layer_boundary` with `_pause_point()` and `_budget_point()`.
   - **Supervisor inputs.** When every layer has run, `_execute_layers` aggregates the final `ExecuteTaskResult` of each task (the retried result after a `retry`, `status="skipped"` after a `skip`) into `self._wave_status` (`"failed"` if any task failed, else `"completed"`), `self._wave_cost_usd` (sum of `cost_usd`) and `self._wave_failure_reason` (the first failed task's `failure_reason`, else `None`). `_supervise` builds `SupervisorFollowupInput` from these three fields (3.3.4, 3.3.5); nothing else feeds them.
4. **Gate seam.**
   ```python
   async def _gate(self, gate_point: str, task_id: str | None) -> str:
       """Returns an action from 3.3.6, or "continue". 88.4.8 replaces the body under patch id p88-durable-gate."""
       return "continue"
   ```
   It issues no command, so the call sites add nothing to history. 88.4.8 adds the time its human waits take to `self._state.excluded_wait_seconds`.
5. **Durable WAIT.** The `wait` arm of `_supervise` becomes `return await self._supervisor_wait(seen)`:
   ```python
   async def _supervisor_wait(self, seen: int) -> str | None:
       self._phase = "supervising"
       try:
           await workflow.wait_condition(lambda: self._approved_seq > seen, timeout=self._remaining_duration())
       except TimeoutError:
           return await self._end_run("failed", "max_duration_exceeded", "idle wait exceeded max_run_duration_seconds")
       return None
   ```
   - No `workflow.sleep` and no iteration increment. An approval signalled while the wave executed already satisfies the wait, because `seen` was recorded before the graph fetch.
   - The supervisor WAIT counts against the duration; it holds the mission's active-run slot.
6. **Human approval wait.** The loop-top wait (PROPOSED tasks only, MANUAL and AI_ASSISTED) keeps no timeout until 88.4.8, and its time is excluded from the duration:
   ```python
   async def _wait_for_approval(self, seen: int) -> None:
       self._phase = "awaiting_gate"
       opened = workflow.now()
       await workflow.wait_condition(lambda: self._approved_seq > seen)
       self._state.excluded_wait_seconds += int((workflow.now() - opened).total_seconds())
   ```
7. **Hard stop.**
   ```python
   def _duration_used_seconds(self) -> float:
       return (workflow.now() - self._state.run_started_at).total_seconds() - self._state.excluded_wait_seconds

   def _duration_exhausted(self) -> bool:
       return self._duration_used_seconds() >= self._input.config.max_run_duration_seconds

   def _remaining_duration(self) -> timedelta:
       return timedelta(seconds=max(self._input.config.max_run_duration_seconds - self._duration_used_seconds(), 1))
   ```
   `MAX_DURATION_EXCEEDED` is a `MissionRunStatusReason` member since 88.1.2 (3.1.2) and is in the `RUNNING → FAILED` reason list (3.2.1); this step is its first use. The workflow passes its lowercase value `"max_duration_exceeded"` (3.0.2). The enum stores names in a `VARCHAR(40)`, so no migration is needed.
8. **Post-run** (`supervisor_activities._do_evaluate_post_run`, `PostRunEvalInput` unchanged from 88.1.8):
   - `GateContext.total_cost_usd` is `MissionPlanService.total_task_cost_usd(plan.id)`, a new method backed by `TaskRepository.sum_cost_by_plan(plan_id) -> float` (`SELECT coalesce(sum(cost_usd), 0) FROM tasks WHERE plan_id = :plan_id`). `budget_usd` stays `plan.budget_usd_ceiling`. This keeps breaker #1 working after `plan.total_spent_usd` stops moving. 88.4.6 replaces both with `BudgetService.check_run`.
   - Drop `max_supervisor_iterations` from the summary dict.
   - Replace the plan increment at `:169` with `MissionRunService.record_iteration(mission_run_id, input.supervisor_iteration_count)`, which sets `mission_runs.iteration_count`.
   - Delete breaker #2 (`gate_post_run.py:130-139`), the `max_supervisor_iterations` keys at `plan_introspection.py:51` and `verify_autonomy_loop.py:109,456`. `trace_execution.py:396` prints `mission_runs.iteration_count` for the run in place of the plan fields.
9. **Retry endpoint.** `POST /missions/{id}/plan/tasks/{task_id}/retry` calls `on_tasks_approved` since 88.1.9 (trigger row 2). No change here.
10. **Delete `AgentMissionWorkflow` and its surfaces** (one commit with item 11):
    - `temporal/workflow.py`, and its registration and docstring mention in `worker.py`.
    - `POST /executions/{id}/execute` (`execute_execution`, both branches) and `POST /executions/{id}/approve` (`submit_approval`). In `GET /executions/{id}/status`, delete the Temporal branch; the database branch stays. Update the module docstring (`executions.py:8-9`).
    - `temporal/models.py` and `tests/unit/backend/temporal/test_models.py`.
    - Web: delete `useStartExecution` (`use-executions.ts:130-139`) and the auto-start effect in `run-live.tsx:49-59`, with any import or constant that becomes unused. Runs start only through `MissionRunService`.
    - Config: delete `budget_timeout_multiplier_seconds`, `execution_retry_max_attempts`, `execution_retry_initial_interval_seconds`, `execution_retry_max_interval_seconds` and `notification_timeout_seconds` from `temporal.yaml` and `TemporalSchema`, and any assertion on them in `tests/unit/backend/temporal/test_config.py`.
    - Docstrings naming `AgentMissionWorkflow`: `chat_workflow.py:16`, `human_input_workflow.py:4`.
    - `test_no_config_in_workflows.py`: delete `DELETED_IN_88_2_6` and its filter, so `WORKFLOW_FILES = sorted(TEMPORAL_DIR.glob("*workflow*.py"))`.

    88.4.8 re-implements the signal, `wait_condition` and timer pattern inside `MissionRunWorkflow`, citing it as `a28ca771:modules/backend/temporal/workflow.py`.
11. **Delete the wave path** (P3):
    - `temporal/activities.py` in full (`execute_mission`, `persist_mission_outcome`, `send_notification`) with `tests/unit/backend/temporal/test_activities.py`, and their `worker.py` registrations.
    - `services/mission_plan_dispatch.py` in full (`dispatch_approved` is its last function) and the `MissionPlanOrchestrator.dispatch_approved` wrapper (`mission_plan_orchestrator.py:497-517`) with the docstring lines naming it (`:5`, `:17`). 88.4.1 therefore has no budget lines to delete in `mission_plan_dispatch.py`.
    - `mission_plan_taskio.write_back_task_results`, `derive_subset_task_plan` and `materialize_task_plan`, whose only caller was `dispatch_approved`, with their test classes (`test_mission_plan_orchestrator.py:181-322`). This also deletes the `retry_count` increments at `:208` and `:231`. `load_prior_outputs` and `materialize_plan_dict` stay.

**Tests:** `tests/integration/backend/temporal/test_mission_run_workflow.py` uses `WorkflowEnvironment.start_time_skipping()` and a worker that registers the real `MissionRunWorkflow` with `workflow_runner=UnsandboxedWorkflowRunner()`, so `monkeypatch.setattr(MissionRunWorkflow, "_gate", ...)` takes effect. Stub activities with the same `@activity.defn(name=…)` live in `mission_run_stubs.py` and record calls in a module-level list. Inputs are built with `build_run_config_snapshot()` and `dataclasses.replace` for per-test values.
- `test_one_activity_per_task`: a graph of two layers with three tasks gives exactly three `execute_plan_task` calls with distinct `task_id`s.
- `test_parallelism_bounded`: `max_parallel_tasks=2` and five tasks in one layer give at most two concurrent stub executions, measured by an in-stub counter.
- `test_wait_is_durable_and_free`: evaluate returns `wait`; `tasks_approved` is signalled after `env.sleep(timedelta(hours=3))`. The next `fetch_run_task_graph` happens after the signal, and `iteration` rises by 1.
- `test_signal_during_execution_satisfies_wait`: `tasks_approved` is signalled while `execute_plan_task` runs and evaluate then returns `wait`; the workflow does not block and fetches the graph again.
- `test_wait_times_out_to_max_duration`: no signal ends the run with one `finalise_mission_run` call whose `FinaliseRunInput` has `status == "failed"` and `reason == "max_duration_exceeded"`.
- `test_approval_wait_excluded_from_duration`: the graph has `proposed=1, approved=0`; `tasks_approved` arrives after 13 hours of skipped time; the wave then executes and the run ends `SUCCEEDED`.
- `test_duration_exhausted_stops_before_next_chunk`: the input carries a `state` with `run_started_at = utc_now() - timedelta(hours=13)`; no `execute_plan_task` is scheduled and the run ends `FAILED/MAX_DURATION_EXCEEDED`.
- `test_no_iteration_cap`: with `continue_as_new_after_iterations=1000`, evaluate returns `advance_approved` 40 times and then `propose_complete`; the run ends `SUCCEEDED/OBJECTIVE_MET` and the last `evaluate_post_run` call has `supervisor_iteration_count == 40`.
- `test_verification_failed_seam_continue_leaves_failed`: the stub returns `verification_failed=True`; `resolve_failed_task` is never called and `evaluate_post_run` runs.
- `test_verification_failed_retry_reruns_once`: `_gate` patched to return `retry` for `verification_failed` and `continue` otherwise; the stub returns `verification_failed=True` and then COMPLETED. The calls are `resolve_failed_task(retry)` and a second `execute_plan_task` for the same task.
- `test_verification_failed_skip`: patched `_gate` returns `skip`; one `resolve_failed_task(skip)` call and no second execution.
- `test_gate_abort_cancels_run`: patched `_gate` returns `abort` at `post_layer`; the run ends `CANCELLED/GATE_REJECTED`.
- `test_activity_failure_ends_task_failures`: the stub raises a non-retryable `ApplicationError`; the run ends `FAILED/TASK_FAILURES` after every activity in the chunk has completed.
- `test_activity_options_from_snapshot`: the stub reads `activity.info().heartbeat_timeout == timedelta(seconds=60)` and `start_to_close_timeout == timedelta(seconds=3600)`.
- `test_supervisor_input_from_task_results`: one layer with two tasks; the stub returns COMPLETED with `cost_usd=0.5` for the first and FAILED with `cost_usd=0.25`, `failure_reason="boom"` and `verification_failed=False` for the second. The `fire_supervisor_followups` stub receives `wave_status == "failed"`, `wave_cost_usd == 0.75` and `failure_reason == "boom"`.
- `test_get_run_state_query`: the query during the supervisor WAIT returns `phase == "supervising"` and `pending_gate_id is None`.
- `tests/unit/backend/mission_control/test_gate_post_run.py::test_no_iteration_breaker`: `supervisor_iteration_count=500` does not escalate.

**Done when:**
- The integration file and `tests/unit/backend/mission_control/test_gate_post_run.py` pass, and `pytest tests/unit/backend/temporal -q` passes.
- `grep -rnwE "execute_mission|persist_mission_outcome|send_notification|MissionWorkflowInput|ExecuteWaveInput|AgentMissionWorkflow|dispatch_approved|write_back_task_results|DELETED_IN_88_2_6" modules/backend/temporal modules/backend/services scripts tests/unit/backend/temporal` returns nothing.
- `grep -rnE --exclude-dir=migrations "budget_timeout_multiplier_seconds|execution_retry_|notification_timeout_seconds" config modules/backend` returns nothing.
- `grep -rn "useStartExecution\|}/execute" modules/frontend/src` returns nothing, and `npm run build` and `npm run lint` pass in `modules/frontend`.
- `grep -n "retry_count += 1" modules/backend/services/*.py` matches only `services/mission_plan.py` (`retry_task`).
- `wc -l modules/backend/temporal/mission_run_workflow.py` is at most 500.

### 88.2.7 Continue-as-new with carried state

**Files:**
- modify `temporal/mission_run_workflow.py`, `temporal/mission_run_models.py`;
- add tests to `tests/integration/backend/temporal/test_mission_run_workflow.py`.

**Current state:** there is no `continue_as_new` call in `modules/backend/temporal/`; Phase 1 has none and 88.2.6 removed the loop bound. The handler-owned fields live on the workflow instance (88.1.8 `@workflow.init`).

**Change:**
1. `MissionRunWorkflowState` gains `last_can_iteration: int`, set to 0 where 88.2.6 builds the state after `begin_mission_run`.
2. Add the first line of the main loop, before `seen = self._approved_seq`: `await self._maybe_continue_as_new()`.
   ```python
   async def _maybe_continue_as_new(self) -> None:
       s = self._state
       if s.pending_gate is not None or s.iteration <= s.last_can_iteration:
           return
       due = s.iteration - s.last_can_iteration >= self._input.config.continue_as_new_after_iterations
       if not (due or workflow.info().is_continue_as_new_suggested()):
           return
       await workflow.wait_condition(workflow.all_handlers_finished)
       s.last_can_iteration = s.iteration
       carried = dataclasses.replace(
           s, approved_seq=self._approved_seq, pause_requested=self._pause_requested, paused=self._paused
       )
       workflow.continue_as_new(dataclasses.replace(self._input, state=carried))
   ```
   - The loop top is a layer boundary with no activity in flight.
   - `is_continue_as_new_suggested()` counts only when `iteration > last_can_iteration`, so a new run that has made no progress never continues-as-new again.
   - `approved_seq`, `excluded_wait_seconds` and `run_started_at` are carried, so a pending approval and the elapsed-time budget survive the hand-over. `@workflow.init` reads the handler-owned fields back from `inp.state` (88.1.8).
   - The workflow id stays `mission_run_workflow_id(mission_run_id)`, and the `config` snapshot is carried unchanged. A run never picks up new config mid-run.

**Tests:**
- `test_continue_as_new_every_n`: `continue_as_new_after_iterations=3`; evaluate returns `advance_approved` for iterations 1 to 6 and `propose_complete` at 7. `describe().run_id` changes twice, the run ends `SUCCEEDED`, and the last `evaluate_post_run` call has `supervisor_iteration_count == 7`.
- `test_state_carried_across_can`: N=1; evaluate returns `wait` at iteration 1; `tasks_approved` is signalled once. The second run executes a wave with no second signal.
- `test_can_does_not_repeat_without_progress`: N=2; evaluate returns `advance_approved` at iteration 1 and `wait` at iteration 2; after the signal the graph returns `approved=0, proposed=0`. Exactly one continue-as-new happens and the run ends `SUCCEEDED/NO_FURTHER_WORK`.
- `test_no_can_with_pending_gate`: `_gate` patched to set `self._state.pending_gate` to a `PendingGate` at `post_layer` and return `continue`; with N=1 and three iterations, `describe().run_id` never changes.

**Done when:** the four tests pass, and every run in `test_continue_as_new_every_n` has fewer than 2,000 history events.

### 88.2.8 Versioning policy for `workflow.patched`

**Files:**
- create `temporal/versioning.py`;
- create `docs/10-reference-architecture/29-opt-temporal-workflow-versioning.md`;
- modify `AGENTS.md` (reference table row `| 29 | Temporal Workflow Versioning (patching, replay, drain) |` under "Optional Platform", whose range label becomes `20-29`);
- create `tests/unit/backend/temporal/test_patch_ids.py`.

**Current state:** there are no `workflow.patched` calls in `temporal/`. Reference-architecture numbers 48 and 49 are taken (`48-agentic-project-context.md`, `49-agentic-codebase-intelligence.md`); 29 is free.

**Change:**
1. `temporal/versioning.py` holds the only registry of patch ids:
   ```python
   PATCH_ID_PATTERN = re.compile(r"^p\d{2,3}-[a-z0-9]+(-[a-z0-9]+)*$")
   PATCH_IDS: frozenset[str] = frozenset()
   ```
2. Policy, written in doc 29 and enforced by the tests:
   1. Any change to a module matching `temporal/*workflow*.py` that alters the order, type or arguments of commands is wrapped in `if workflow.patched("<id>"): <new> else: <old>`. Commands are activities, timers, child workflows, signals sent and continue-as-new. The id is a string literal that is also in `PATCH_IDS`.
   2. Ids are `p{plan}-{kebab-slug}`. They are never reused or renamed.
   3. `workflow.deprecate_patch` is not called inside Plan 88. An old branch is removed only by a later plan, and only after `temporal workflow count --query "WorkflowType='MissionRunWorkflow' AND ExecutionStatus='Running'"` returns 0 for runs started before the patch.
   4. Phase 2 ships without patches and uses the drain in 88.2.10, because it replaces the activity graph wholesale. Every change after Phase 2 uses patches.
   5. Each step that introduces `workflow.patched("<id>")` does three things in the same commit: adds `<id>` to `PATCH_IDS`; records one history that takes the new branch at `tests/fixtures/temporal_histories/mission_run/<id>.json` (88.2.9); adds `<id>` to `REQUIRED` in `test_replay_histories.py`. Histories for the old branch are kept. Plan 88 ids: `p88-run-memory` (Phase 3, whose pre-patch fixture is recorded from Phase 2 code), `p88-lifecycle-signals`, `p88-budget-caps`, `p88-durable-gate` (Phase 4).

**Tests** (`test_patch_ids.py`):
- `test_patch_calls_use_registered_literal_ids`: walks the AST of each `*workflow*.py`. Every `workflow.patched(...)` argument is an `ast.Constant` string in `PATCH_IDS`.
- `test_registered_ids_match_pattern`.
- `test_registered_ids_have_histories`: every id in `PATCH_IDS` has `tests/fixtures/temporal_histories/mission_run/<id>.json`.
- `test_no_deprecate_patch`: no call to `deprecate_patch`.

**Done when:**
- `pytest tests/unit/backend/temporal/test_patch_ids.py -q` passes.
- `python scripts/check_docs.py` passes with doc 29 listed in the AGENTS.md reference table.

### 88.2.9 Replay test harness in CI

**Files:**
- create `temporal/history_redaction.py`;
- create `scripts/record_workflow_history.py`;
- modify `temporal/workflow_gateway.py` (exists since 88.0.3; adds `fetch_history`) and `tests/unit/backend/temporal/test_workflow_gateway.py` (exists since 88.0.3);
- create `tests/fixtures/temporal_histories/mission_run/README.md` and the seven fixture files below;
- create `tests/integration/backend/temporal/test_record_mission_run_histories.py`;
- create `tests/unit/backend/temporal/test_replay_histories.py` and `tests/unit/backend/temporal/test_history_redaction.py`;
- modify `tests/conftest.py`, `.github/workflows/ci.yml`.

**Current state:** there is no `Replayer` usage in `tests/`. CI runs the steps "Unit tests" (`pytest tests/unit -q -p no:cacheprovider`) and "Integration tests" (`.github/workflows/ci.yml:103-106`). 88.0.1 added the Temporal test-server prefetch to CI. Phase 2 supervisor decisions come from an LLM, so a live dev-stack run cannot reproduce a chosen history shape on demand.

**Change:**
1. **`temporal/history_redaction.py`** (pure, no I/O):
   ```python
   REDACT_KEYS = frozenset({"objective", "prompt", "output_data", "mission_brief", "message", "instructions"})

   def redact_history(history: dict) -> dict: ...
   ```
   It walks every `payloads[*]` in the history JSON. For each payload with `metadata.encoding` `json/plain`, it base64-decodes `data`, parses the JSON, and replaces the value of every key in `REDACT_KEYS`, at any depth, in place: a string becomes `"<redacted>"`, a dict `{}`, a list `[]`; numbers, booleans and `null` are kept. It re-encodes `data`. The JSON shape and value types are kept, so the dataclasses still decode.
2. **Fixture recording from the stubbed workflow** (the source of the required fixtures):
   - `tests/conftest.py` adds `pytest_addoption(parser)` with `parser.addoption("--record-histories", action="store_true", default=False)`.
   - `test_record_mission_run_histories.py` has a module-level autouse fixture that calls `pytest.skip("pass --record-histories to regenerate fixtures")` unless the option is set. It reuses `mission_run_stubs.py`, runs one scenario per fixture, fetches each run's history with `client.get_workflow_handle(workflow_id, run_id=run_id).fetch_history()`, and writes `json.dumps(redact_history(json.loads(history.to_json())), indent=2)` to `tests/fixtures/temporal_histories/mission_run/<name>.json`.
   - Run: `pytest tests/integration/backend/temporal/test_record_mission_run_histories.py --record-histories -q`.
3. **Required fixtures** (`REQUIRED` in item 5):
   - `two_layer_success`: two layers, three tasks, `propose_complete`.
   - `wait_then_signal`: evaluate returns `wait`, then `tasks_approved`, then `propose_complete`.
   - `can_first_run`: first run of a `continue_as_new_after_iterations=2` scenario, ending in continue-as-new.
   - `can_carried_state_run`: the second run of that scenario, started with `state` set.
   - `verification_failed_continue`: a task returns `verification_failed=True` and the seam returns `continue`.
   - `cancelled_mid_layer`: `handle.cancel()` while `execute_plan_task` runs.
   - `max_duration_stop`: the supervisor WAIT times out to `MAX_DURATION_EXCEEDED`.
4. **`scripts/record_workflow_history.py`**, for histories from a real server (later patch fixtures, incident captures). Argparse subparsers `record` and `tree` (rule 010.1; `tree` introspects the parser):
   ```
   python scripts/record_workflow_history.py record --workflow-id WORKFLOW_ID [--run-id RUN_ID] --name SLUG
   ```
   It connects through `TemporalWorkflowGateway.connect()` and calls `gateway.fetch_history(workflow_id, run_id=run_id)`, a method this step adds to `temporal/workflow_gateway.py` (the gateway stays the only owner of workflow handles, 88.0.3; the script never calls `client.get_workflow_handle`). It refuses a history whose workflow is still running, applies `redact_history`, and writes `tests/fixtures/temporal_histories/mission_run/<SLUG>.json`. The method signature is `async def fetch_history(self, workflow_id: str, *, run_id: str | None) -> tuple[WorkflowHistory, bool]`, returning the history and whether the execution is still running.
5. **`test_replay_histories.py`:**
   ```python
   HISTORY_DIR = Path("tests/fixtures/temporal_histories/mission_run")
   FILES = sorted(HISTORY_DIR.glob("*.json"))
   REQUIRED = frozenset({
       "two_layer_success", "wait_then_signal", "can_first_run", "can_carried_state_run",
       "verification_failed_continue", "cancelled_mid_layer", "max_duration_stop",
   })


   def test_histories_present() -> None:
       assert {f.stem for f in FILES} >= REQUIRED


   @pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
   async def test_replay(path: Path) -> None:
       history = WorkflowHistory.from_json(path.stem, path.read_text())
       await Replayer(workflows=[MissionRunWorkflow]).replay_workflow(history)
   ```
   No Temporal server is needed. Later patch steps add their ids to `REQUIRED` (88.2.8 rule 5).
6. **`ci.yml`.** Add a step before "Unit tests":
   ```yaml
   - name: Temporal replay
     run: pytest tests/unit/backend/temporal/test_replay_histories.py -q -p no:cacheprovider
   ```
   It is a separate step so that a nondeterminism failure is named in the CI summary.
7. **README.** `tests/fixtures/temporal_histories/mission_run/README.md` states the two recording commands, the redaction rule, and 88.2.8 rule 5.

**Tests:**
- `test_replay_histories.py` as in item 5.
- `test_history_redaction.py`:
  - `test_redacted_history_decodes`: redacting `two_layer_success.json` again and replaying the result with `Replayer` succeeds.
  - `test_redaction_keeps_types`: a payload `{"objective": "x", "output_data": {"a": 1}, "cost_usd": 1.5}` becomes `{"objective": "<redacted>", "output_data": {}, "cost_usd": 1.5}`.
- `tests/unit/backend/temporal/test_workflow_gateway.py::test_fetch_history_reports_running`: with a fake client whose handle's `describe()` returns status RUNNING, `fetch_history` returns `True` as its second element.
- Negative check, run once locally: insert `await workflow.sleep(timedelta(seconds=1))` as the first line of the main loop; `test_replay[two_layer_success]` must fail with `NondeterminismError`. Revert it.

**Done when:**
- The seven fixture files are committed, and `pytest tests/unit/backend/temporal/test_replay_histories.py tests/unit/backend/temporal/test_history_redaction.py -q` passes.
- `python scripts/record_workflow_history.py tree` lists `record` and `tree`.
- The CI run on `main` shows the "Temporal replay" step green.

### 88.2.10 Deploy: drain in-flight workflows

**Files:**
- modify `docs/10-reference-architecture/29-opt-temporal-workflow-versioning.md` (add a "Drain procedure" section holding this runbook).
- No code change.

**Current state:** Phase 1 `MissionRunWorkflow` executions carry the wave-activity graph and no Phase 2 state fields, so replaying them on Phase 2 code raises `NondeterminismError`. `ChatTurnWorkflow`, `PlanRefineWorkflow`, `DesignWorkflowWorkflow` and `RunWorkflowWorkflow` inputs gained a required `timeouts` field, so an execution started before the deploy cannot decode its input on Phase 2 code. `AgentMissionWorkflow` no longer exists on the worker.

**Change.** The deploy runbook, run once for the Phase 2 release in this order:
1. Set `missions.recurrence.enabled: false` (`config/settings/missions.yaml`) on the running deployment, then run `python admin.py schedules sync` (in-process service call, contracts 3.0.2). Every `mission-schedule-*` Temporal schedule is now deleted; the `mission_schedules` rows are unchanged. Step 5 recreates the schedules on the dev stack; production recreates them when the Phase 4 release sets `missions.recurrence.enabled: true`.
2. Count open executions of the affected types:
   ```
   temporal workflow count --query "ExecutionStatus='Running' AND WorkflowType IN ('MissionRunWorkflow','ChatTurnWorkflow','PlanRefineWorkflow','DesignWorkflowWorkflow','RunWorkflowWorkflow','AgentMissionWorkflow')"
   ```
   Repeat every 5 minutes for up to 2 hours.
3. Cancel whatever is still running:
   ```
   temporal workflow list --query "ExecutionStatus='Running' AND WorkflowType IN ('MissionRunWorkflow','ChatTurnWorkflow','PlanRefineWorkflow','DesignWorkflowWorkflow','RunWorkflowWorkflow','AgentMissionWorkflow')" -o json | jq -r '.[].execution.workflowId' | xargs -I{} temporal workflow cancel --workflow-id {}
   ```
   Wait until the count from step 2 is 0. Each cancelled `MissionRunWorkflow` finalises itself as `CANCELLED` through its cancellation handler; a run that does not is failed by the reconciler (88.1.10a) after `orphan_grace_seconds`.
4. Stop the worker, deploy, and start the worker. Phase 2 has no migration; `python admin.py migrate current` still shows `plan88_003`.
5. On the dev stack, set `missions.recurrence.enabled: true` and run `python admin.py schedules sync`. Production keeps `missions.recurrence.enabled: false` until Phase 4 is complete (Risk 6).
6. Check that `temporal schedule list` shows every expected `mission-schedule-*` unpaused on the dev stack.

**Tests:** run the runbook once on the dev stack with one active hourly mission. Record in the commit message the workflow count before and after, and the run statuses.

**Done when:**
- After step 6, the next scheduled tick on the dev stack produces a `MissionRun` that reaches `SUCCEEDED`.
- `temporal workflow count --query "WorkflowType='MissionRunWorkflow' AND ExecutionStatus='Running' AND StartTime < '$DEPLOY_TIME'"`, with `DEPLOY_TIME` set to the RFC 3339 time of step 4, returns 0.

### Verification

```bash
cd /Users/herman.young/development/mission-control
pytest tests/unit/backend/temporal tests/unit/backend/core/test_config_schema_plan88_phase2.py tests/unit/backend/core/test_copilot_health.py tests/unit/backend/mission_control tests/unit/backend/agents/mission_control -q
pytest tests/integration/backend/services/test_run_task_execution.py tests/integration/backend/temporal/test_mission_run_workflow.py -q
pytest tests/unit/backend/temporal/test_replay_histories.py tests/unit/backend/temporal/test_history_redaction.py -q
lint-imports
python scripts/code_rules_fast.py --all
python scripts/check_docs.py
(cd modules/frontend && npm run build && npm run lint)
grep -rn "get_app_config\|get_default_budget_usd\|get_settings" modules/backend/temporal/*workflow*.py         # expect no output
grep -rnwE "execute_mission|persist_mission_outcome|AgentMissionWorkflow|dispatch_approved|MissionWorkflowInput" modules/backend/temporal modules/backend/services scripts   # expect no output
grep -rnE --exclude-dir=migrations "budget_timeout_multiplier_seconds|execution_retry_|notification_timeout_seconds|wait_action_sleep_seconds" config modules/backend   # expect no output
grep -rn "max_supervisor_iterations" modules/backend/temporal modules/backend/agents scripts/trace_execution.py scripts/verify_autonomy_loop.py   # expect no output
python scripts/record_workflow_history.py tree
MISSION_SLUG=replay-fixture python scripts/trace_execution.py --mission "$MISSION_SLUG" --last --filter errors,transitions
```

Then run a crash drill on the dev stack:
1. Start a run with three tasks in one dependency chain.
2. During task 2's agent call, run `kill -9` on the worker process and restart the worker.
3. `python scripts/trace_execution.py --mission "$MISSION_SLUG" --last` must show:
   - task 1 executed exactly once: one `task_executions` row, and the `llm_calls` count `WHERE task_id = <task 1 id>` unchanged after the restart;
   - task 2 re-executed under the same idempotency key, ending `:0`;
   - the run reaching `SUCCEEDED`.

### Risks

1. **A zombie attempt spends money twice.** A worker can be alive but have a blocked event loop. It misses heartbeats, so Temporal starts a second attempt while the first is still calling the LLM. The UNIQUE `idempotency_key` keeps the stored result single, but the zombie's LLM spend is real. **Mitigation:**
   - `heartbeat_timeout_seconds: 60` with a 20s interval;
   - `record` returns the stored result with `idempotent_replay=True` for the loser;
   - spend stays attributed by `task_id`, so this query lists every task whose ledger spend exceeds its recorded cost, for inspection in the acceptance runs:
     ```sql
     SELECT t.id, t.cost_usd, sum(l.cost_usd) AS ledger_usd
     FROM tasks t JOIN llm_calls l ON l.task_id = t.id
     WHERE l.mission_run_id = :mission_run_id
     GROUP BY t.id, t.cost_usd
     HAVING sum(l.cost_usd) > t.cost_usd;
     ```
     Legitimate verification retries inside one attempt also appear; a zombie shows as roughly double the expected spend.
2. **A history shape not covered by fixtures.** Replay protects only the seven recorded shapes. **Mitigation:** 88.2.8 rule 5 adds a history for each patch; the AST tests block config reads and unregistered patch ids; continue-as-new keeps histories short, so a nondeterminism failure affects at most N iterations of one run, and the reconciler fails it cleanly.
3. **Losing the shared in-memory `completed_outputs`.** Per-task activities can lose upstream outputs. **Mitigation:** `load_dependency_outputs` reads `tasks.result_summary` from Postgres, and `test_missing_upstream_returns_failed_result` makes a gap fail loudly.
4. **Parallel tasks under-funded by the run cap.** This applies from 88.4.6, which splits headroom equally across a chunk. A large task in a chunk can hit its share and fail. **Mitigation:** accepted; it fails safe. Raise `max_parallel_tasks` or the per-run cap for that mission.
5. **Stall detection reads the wrong unit.** Stall detection (`gate_post_run.py:141-153`) reads `recent_run_outcomes` per ExecutionRecord. With one record per run, it measures runs, not waves. **Mitigation:** the stall breaker fires later, not wrongly. Phase 3 feeds per-wave counts. Until then the duration hard stop bounds a stalled run.
6. **Phases 2 and 3 run without budget enforcement or in-run gates.** contracts 3.0.1 places budget enforcement in 88.4.6 and durable gates in 88.4.8. From 88.2.6, the Temporal path has no plan-ceiling check (it lived in `dispatch_approved`), and the `post_task`, `verification_failed` and `post_layer` gates return `continue` for every gate mode. MANUAL and AI_ASSISTED missions keep human control only through task approval (PROPOSED→APPROVED). **Mitigation:**
   - post-run breaker #1 still escalates a run when the plan's summed task cost reaches `budget_usd_ceiling` (88.2.6 item 8);
   - **Operational rule** (also a Phase 2 entry criterion): until Phase 4 is complete, production keeps mission schedules disabled (`missions.recurrence.enabled: false`, set in 88.2.10 step 1; `MissionScheduleService.create_schedule` and the tick workflow refuse while it is false, 88.1.1) and does not dispatch MANUAL or AI_ASSISTED missions.
