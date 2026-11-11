## Phase 2: Durable execution: per-task activities, idempotency, versioning

This phase delivers decisions 11, 12 and 15. Before the per-task activity exists, 88.2.3a closes the fail-open execution boundary and 88.2.3b gives every failed task a typed, classified failure record (contracts 3.8), so the activity, the supervisor and the Director are built on evidence rather than "Task failed during dispatch". Each approved task in a wave runs as its own heartbeating Temporal activity. That activity has config-driven timeouts and an idempotency key, so a retry never re-runs or re-charges a completed task. `MissionRunWorkflow` becomes replay-safe for runs lasting weeks: config is pinned as workflow input, history is bounded by continue-as-new, idle waits are durable, code changes after this phase go through `workflow.patched`, and recorded histories are replayed in CI.

**Scope boundaries (3.0 Phase ownership):**
- **No budget enforcement.** Phase 2 contains no budget branch. `check_run_budget`, `BudgetService` and the run, monthly and lifetime caps arrive in 88.4.1 and 88.4.6, which add enforcement under patch id `p88-budget-caps`. This phase deletes `dispatch_approved` (88.2.6), so the plan-ceiling check it held leaves the Temporal path here (Risk 6).
- **Gates are a seam only.** 88.2.6 adds `MissionRunWorkflow._gate()`, which returns `"continue"`. 88.4.8 replaces its body under patch id `p88-durable-gate` (Risk 6).
- **No migration.** Phase 2 adds no Alembic revision. The head stays `plan88_003`.
- **Owned here:** the deletion of `AgentMissionWorkflow` (`temporal/workflow.py`), `POST /executions/{id}/execute`, `POST /executions/{id}/approve`, the web code that calls them, and the config keys only they read (88.2.6); continue-as-new (88.2.7, Phase 1 has none); the fail-closed execution boundary (88.2.3a), the task failure contract (88.2.3b, 88.2.4, 88.2.4a, 88.2.6; contracts 3.8) and the `verification_failed` gate actions (88.2.3c).
- **No repair loop.** Phase 2 records, classifies and surfaces failures. It does not diagnose or fix them (contracts 3.8.7).

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
  - the approval wait `wait_until_approved`, which polls the task row (88.0.13a);
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
   - The body moves out of `mission_dispatch.py` without changing behaviour: roster (`:116`), context services (`:125-138`), environment (`:364-412`) and executor (`:418-424`). `handle_mission` calls it and passes its keyword `mission_run_id` (set only by `dispatch_approved`, None for other in-process callers) and `task_id=None`. Its legacy positional `execution_label` (renamed in 88.1.7) is a label, never a run id, and is not passed as `mission_run_id`.
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

### 88.2.3a Fail-closed execution boundary

Delivers decision 15, boundary half (contracts 3.8.5). 88.2.3 moved the provisioning code into `build_dispatch_runtime` without changing behaviour. This step changes the behaviour, so that every later step builds on a boundary that cannot fail open.

**Files:**
- modify:
  - core and config: `core/exceptions.py`, `core/config.py`, `core/config_schema.py`, `config/settings/executions.yaml`, `temporal/activity_options.py`;
  - dispatch: `agents/mission_control/runtime.py`, `agents/mission_control/dispatch/environment.py`, `agents/mission_control/helpers/agent_executor.py`, `agents/mission_control/helpers/cli_executor.py`, `agents/mission_control/chat_cli_handler.py`, `agents/security/tool_runner.py`;
  - environment and schema: `services/execution_environment.py`, `schemas/agent_config.py`;
  - tools: `tools/run_command.py`, `tools/run_tests.py`;
  - services and schemas: `services/workflow_run_waves.py`, `services/workflow_run_steps/helpers.py`, `services/mission.py`, `schemas/mission.py`;
- modify these existing tests:
  - `tests/unit/backend/agents/test_cli_executor.py`: fixtures supply a fake handle with `host_working_dir` set and an empty `scope.write`;
  - `tests/unit/backend/config/test_config_executions.py` and `tests/unit/backend/services/test_execution_persistence.py`: both supply `run_tests_timeout_seconds`;
  - `tests/agents/security/test_secret_detection_redaction.py`: asserts `<redacted>`;
- create `tests/unit/backend/mission_control/test_execution_boundary.py`.

**Current state** (cited at `86ecd6eb`; locate by symbol):
- **`build_dispatch_runtime`** (from `mission_dispatch.py` before 88.2.3):
  - defaults `repo_root` to `find_project_root()` (`mission_dispatch.py:375`);
  - on any provisioning exception, emits a warning `SystemEvent` and continues with `env_handle = None`, which is local execution (`:396-412`).
- **`_validate_mode`** (`dispatch/environment.py:108-120`) returns `"local"` when worktree or container mode has no `repo_root`.
- **Workflow steps.** `workflow_run_waves` calls `handle_mission` without `mission_repo_root`. It calls `resolve_dispatch_params` (`workflow_run_steps/helpers.py:143`) outside the step's `try`. No worktree backend is registered.
- **Host execution without a handle:**
  - `run_command` calls `_run_local` (`tools/run_command.py:88-118`), a host shell;
  - `run_tests` runs `sys.executable -m pytest tests/unit` on the host with no timeout (`tools/run_tests.py:21-42`);
  - `security/tool_runner._run_tool_subprocess` (`:52`) runs on the host.
- **`LocalBackend`** (`services/execution_environment.py:106-162`) is registered by default and runs `create_subprocess_exec` on the host with `cwd=find_project_root()`. `get_or_create_for_mission` defaults to `mode="local"`.
- **Two "run in handle" helpers exist.** `run_command._run_in_environment` builds a service per call, and `tool_runner._get_env_service` with `_run_via_environment_service` is a cached twin. `tool_runner._redact_secrets_in_text` (`:200-211`) is a second secret redactor beside `core/redaction`.
- **`chat_cli_handler`** (`:41-45`, `:133-147`) calls the CLI engines with `working_dir=str(find_project_root())`.
- **The CLI engines** run as host subprocesses with `cwd` defaulting to `find_project_root()` (`helpers/cli_executor.py:205`, `:272`, `:306`). `claude_code` gets Write, Edit and Bash when `scope.write` is non-empty. `codex` runs `--full-auto`. `copilot` writes `AGENTS.md` into its working directory.

**Change:**
1. **Exception.** Add `class ExecutionEnvironmentError(ApplicationError)` to `core/exceptions.py`. Add its name to `temporal/activity_options.NON_RETRYABLE`.
2. **`build_dispatch_runtime`.**
   - A non-local `execution_mode` with no `mission_repo_root` raises `ExecutionEnvironmentError("execution mode '<mode>' requires repo_root")`.
   - Any provisioning exception is re-raised as `ExecutionEnvironmentError`, with the original as `__cause__`.
   - A git-aware container handle whose `host_working_dir is None` raises.
   - Delete the `find_project_root()` default, the warning `SystemEvent` and the `env_handle = None` fallback.
   - The `CodeMapLoader` call keeps `find_project_root()`, because it reads the platform's own code map.
3. **Workflow steps and modes.**
   - `_validate_mode` raises `ExecutionEnvironmentError` instead of returning `"local"`.
   - `workflow_run_waves` passes `mission_repo_root=mission.repo_root` to `handle_mission`.
   - `workflow_run_waves` moves the `resolve_dispatch_params` call inside the step's `try`, so an `ExecutionEnvironmentError` marks the step failed through the existing handler.
4. **Worktree.** `MissionService` create and update reject `execution_environment="worktree"` with `ValidationError("no worktree backend is registered")`.
5. **No host shell** (contracts 3.8.5).
   - **`run_in_environment`.** Add `run_in_environment(handle, argv, *, timeout_seconds) -> CommandResult` to `services/execution_environment.py`. It uses one cached service with `ContainerBackend` registered by lazy import. A `None` handle raises.
   - **Delete:**
     - `LocalBackend`, its default registration, and the local branch and default of `get_or_create_for_mission`. An unregistered mode raises `ExecutionEnvironmentError`.
     - `run_command._run_local` and `run_command._run_in_environment`.
     - `tool_runner._get_env_service`, `_run_via_environment_service` and the local branch of `_run_tool_subprocess`.
   - **Call sites:**
     - `run_command` wraps `["sh", "-c", command]` and maps the result to its dict.
     - `tool_runner._run_tool_subprocess` calls the helper.
     - `run_tests` declares `TOOL_DEF["deps"] = ["environment_handle"]` (its `register` wrapper passes `ctx.deps.environment_handle`) and runs the module constant `RUN_TESTS_ARGV = ["python", "-m", "pytest", "tests/unit", "-v", "--tb=short"]` with `timeout_seconds=get_app_config().executions.run_tests_timeout_seconds` (3.4.10, key added here). Its return shape is unchanged.
   - **Config.** `executions.yaml` switches to `_load_validated` (required).
   - **One redactor.** `tool_runner._redact_secrets_in_text` is deleted, and `strip_secret_values` calls `core/redaction.redact_secrets` (patterns in 3.5.5).
6. **CLI engines** (contracts 3.8.5). Until they run inside the container (3.8.7):
   - **`codex` and `copilot`.** Delete `execute_codex`, `execute_copilot` and their entries in the engine dicts of `helpers/agent_executor.py` and `chat_cli_handler.py`. `AgentConfigSchema._validate_engine` accepts only `pydantic_ai` and `claude_code`, with an error that names contracts 3.8.7.
   - **`execute_claude_code`** takes `environment_handle` in place of `working_dir`. It raises `ExecutionEnvironmentError` when `scope.write` is non-empty, or when the handle or its `host_working_dir` is `None`. Otherwise it runs with `cwd=host_working_dir`, `tools=["Read", "Grep", "Glob"]` and `setting_sources=[]`.
   - **`chat_cli_handler`** passes `environment_handle=None` and drops `find_project_root`, so CLI-engine chat raises.
7. **Write guard** (`helpers/agent_executor.py`, in `execute_agent`).
   - **Where it runs:** immediately after `effective_handle` is computed (`:88-90`), and before the engine branch.
   - **When it raises:** a `pydantic_ai` agent with a non-empty `scope.write` raises `ExecutionEnvironmentError("agent '<name>' needs an isolated workspace")` when `effective_handle` is `None` or its `host_working_dir is None`.
   - **What it reads:** `effective_handle`, not `deps`. It uses no path containment.

**Tests** (`test_execution_boundary.py`, unit):
- `test_container_mode_without_repo_root_raises`.
- `test_provisioning_error_raises_not_local`: no `SystemEvent` is emitted.
- `test_container_without_worktree_raises`.
- `test_validate_mode_raises`.
- `test_workflow_wave_passes_repo_root`.
- `test_workflow_step_env_error_fails_step`: the step's record ends failed, not running.
- `test_mission_worktree_rejected`.
- `test_run_command_without_handle_raises`.
- `test_run_tests_without_handle_raises`.
- `test_run_tests_uses_argv_constant_and_config_timeout`.
- `test_security_tool_runner_without_handle_raises`.
- `test_local_mode_handle_cannot_execute`: an unregistered `local` mode raises `ExecutionEnvironmentError`.
- `test_run_in_environment_none_handle_raises`.
- `test_codex_and_copilot_engines_rejected_by_schema`.
- `test_chat_cli_engine_without_handle_raises`.
- `test_claude_code_with_write_scope_raises_even_with_handle`.
- `test_claude_code_without_handle_raises`.
- `test_claude_code_passes_read_tools_and_empty_setting_sources`.
- `test_write_guard_blocks_without_handle`.
- `test_write_guard_allows_worktree_under_platform_repo`: `host_working_dir` is `<platform>/var/worktrees/x/workspace`.

**Done when:**
- `pytest tests/unit/backend/mission_control tests/unit/backend/agents tests/unit/backend/config tests/unit/backend/services/test_execution_persistence.py tests/agents/security/test_secret_detection_redaction.py -q` passes.
- `grep -rn "_run_local\|falling back to local" modules/backend` returns nothing.
- `grep -n "find_project_root" modules/backend/agents/mission_control/helpers/cli_executor.py modules/backend/agents/mission_control/chat_cli_handler.py` returns nothing.
- `grep -rn "class LocalBackend\|_run_via_environment_service\|_redact_secrets_in_text\|def execute_codex\|def execute_copilot" modules/backend` returns nothing.
- `grep -n "repo_root.*find_project_root" modules/backend/agents/mission_control/runtime.py` returns nothing.

### 88.2.3b Typed task failure record and deterministic classifier

Delivers decision 15, evidence half (contracts 3.8.2 to 3.8.4). After this step every failed `TaskResult` carries a classified `TaskFailure`, and the retry handler has one retry rule. 88.2.4 persists the record, 88.2.4a shows it to the Planning Agent, and 88.2.6 hands it to the post-run reviewer and the Director.

**Files:**
- create `schemas/task_failure.py`, `core/failure_classification.py`, `config/settings/failures.yaml`;
- modify:
  - core: `core/config_schema.py`, `core/config.py`;
  - schemas and models: `schemas/execution_outcome.py`, `models/task.py`, `models/execution_record.py`;
  - tools: `tools/halt_workflow.py`;
  - dispatch: `agents/mission_control/dispatch/result_builders.py`, `retry_handler.py`, `task_runner.py`, `research_loop.py`, `convergence.py`, `loop.py`, `dag.py`;
  - services: `services/workflow_run.py`, `services/workflow_run_waves.py`, `services/workflow_run_steps/helpers.py`, `services/synthesis.py`;
  - clients: `clients/tui/app.py`, `clients/tui/widgets/mission_panel.py`;
- modify these existing tests:
  - `tests/unit/backend/mission_control/test_dispatch.py`: the `retry_history` lengths in `test_timeout_retry_then_exhaustion` and `test_execution_error_retries_then_fails` become 3;
  - `tests/unit/backend/mission_control/test_retry_handler_classification.py`: the raised error is defined in the test module, so the `UNKNOWN` retry path is still exercised;
  - `tests/unit/clients/tui/test_mission_panel.py`;
- create `tests/unit/backend/core/test_failure_classification.py`, `tests/unit/backend/core/test_failures_config.py`, `tests/unit/backend/mission_control/test_failure_capture.py`.

**Current state** (cited at `86ecd6eb`; locate by symbol):
- **Lost reasons.** `failed_result()` accepts `reason` and never stores it (`dispatch/result_builders.py:66-85`). `TaskResult` has no failure field (`schemas/execution_outcome.py:106-131`, `extra="forbid"`).
- **Direct `TaskResult(status=FAILED|TIMEOUT)` constructions:**
  - `retry_handler.py:178`, `:297`, `:504`;
  - `convergence.py:285`, `:431`, `:442`;
  - the `loop.py` forks that 88.2.3 moves into `task_runner.py`: a missing `loop_config`, and a `workflow:` run that did not complete.
- **A second failed-result builder.** `research_loop._failed_result` (`:774-785`) keeps the spend already incurred. It is called at `:272` and from the catch-all at `:686`.
- **The retry handler decides retries in several places:**
  - typed except clauses for quota (`:92`), for transient, rate-limit and timeout errors (`:122`), and for `_CONTRACT_FAILURE_EXCEPTIONS` (`:53-57`, `:190`);
  - `isinstance` branches after `classify_provider_error` (`:244`, `:270`);
  - an `is_token_limit` special case (`:311`).

  `ProviderError.retry_policy` (`core/exceptions.py`) encodes the same policy and has no reader. The handler also drops the final failing attempt from `retry_history` (`:165-189`, `:284-308`, `:325-346`), and feeds other exceptions back as `"... Avoid this error."` (`:330-337`).
- **Upstream errors.** `resolve_upstream_inputs` raises a bare `KeyError`.
- **Workflow step errors.**
  - The workflow engine re-raises step failures as `RuntimeError`, and `halt_workflow` raises a bare `RuntimeError` (`tools/halt_workflow.py:47`).
  - `extract_first_task_failure` (`workflow_run_steps/helpers.py:191-226`) guesses a failure text from output keys, `retry_history` and verification tiers. It is called at `workflow_run_waves.py:444` and `:775`.
  - `synthesis.py:65-66` reads `retry_history[-1].failure_reason`.
- **Workflow task-fail paths.** `WorkflowRunService._fail_remaining_plan_tasks` (`services/workflow_run.py:577-604`) and `workflow_run_waves._sync_plan_task_states` (`:105`) write `failure_reason` text only.
- **The TUI** builds `TaskResult` objects from SSE events (`clients/tui/app.py`, `widgets/mission_panel.py`).

**Change:**
1. **Types and config.** Create `schemas/task_failure.py` exactly as contracts 3.8.2. Add `TaskResult.failure` with its validator, and `RetryHistoryEntry.failure_class`. Create `failures.yaml` as contracts 3.4.9, with `FailuresSchema`, loaded with `_load_validated` (required).
2. **Classifier.** Create `core/failure_classification.py`, containing:
   - `FailureClassifier` (3.8.3), `CONTRACT_ERRORS`, `AGENT_TOOL_DIRS`, `WorkflowStepFailedError` and the fingerprint (3.8.4);
   - `get_failure_classifier()`, an `lru_cache` singleton over `get_app_config().failures` and `Path(os.path.realpath(find_project_root() / "modules"))`.

   `message` and `summary` pass through `redact_secrets`.
3. **Exceptions** (contracts 3.5.5). `UpstreamOutputMissingError(KeyError)` in `dag.py`, with `source_task` and `source_field`. `WorkflowHaltedError(RuntimeError)` in `tools/halt_workflow.py`, with `reason`; the `tool_call` dispatcher's re-raise of `RuntimeError` is unchanged.
4. **One failed-result builder.** `failed_result(task, failure, *, status=TaskStatus.FAILED, ..., cost_usd=0.0, token_usage=None, duration_seconds=0.0)` replaces `reason: str` (P3). `research_loop._failed_result` is deleted. `execute_research_loop` takes `task: TaskDefinition` in place of `task_id` (its caller `loop.py:638` has it) and passes its spend through `failed_result`. Each site gets its `TaskFailure` as follows:

   | Site | `TaskFailure` |
   |---|---|
   | Roster miss | `roster_miss(agent)` |
   | `UpstreamOutputMissingError` in `run_single_task` | `upstream_blocked(ref, exc.source_task)` |
   | Missing or invalid `loop_config` | `plan_invalid(agent, detail)` |
   | Exception around `execute_task` | `from_exception(exc)` (item 5) |
   | Exhausted verification (direct `TaskResult`, keeps `output_reference` and `verification_outcome`) | `verification_failed(agent, verification_outcome)` |
   | Gate `ABORT` at `verification_failed` or `post_task` | `control(CANCELLED, "aborted at <gate> gate")` |
   | Convergence not converged, `success: False`, or a non-dict result (`convergence.py:285`, `:431`, `:442`) | `agent_outcome(agent, detail)` |
   | Research decomposition failure (`research_loop.py:272`) | `agent_outcome(task.agent, detail)` |
   | Research catch-all (`research_loop.py:686`) | `from_exception(exc)` |
   | `workflow:` fork | `TaskFailure.model_validate(run.error_data["failure"])` when the run is FAILED; if `run.error_data` has no `failure` key, `control(FailureClass.RUN_ABORTED, run.error)`. In the fork's catch-all, `from_exception(exc)` |
   | Workflow step (in `workflow_run_waves`) | The step builds its `TaskFailure`: `from_exception(exc)` on the except path; the first failed task's `result.failure`; or `agent_outcome("workflow:<step>", f"workflow halted: {reason}")` for `WorkflowHaltedError`. It raises `WorkflowStepFailedError` carrying it. `run_workflow` stores `failure.model_dump(mode="json")` in `run.error_data["failure"]`. `extract_first_task_failure` and both its calls are deleted (P3). The step message and `_failure_reasons` use the first failed task's `failure.summary`, and `synthesis.py` reads `t.failure.summary` |

5. **One retry rule** (contracts 3.8.3).
   - **One handler.** Exception handling around `execute_task` collapses to one `except Exception as raw`:
     - `failure = get_failure_classifier().from_exception(raw)`;
     - append the attempt with `failure.failure_class`, the final attempt included;
     - when `failure.origin is FailureOrigin.PROVIDER`, log through `log_provider_error` with the labelled `classify_provider_error(raw, provider=..., model=...)`; otherwise log `failure.failure_class`;
     - when `failure.retryable` is true and budget remains, retry with the feedback `f"Previous attempt failed ({failure.failure_class.value}): {failure.summary}"`;
     - otherwise return `failed_result(task, failure, status=TaskStatus.TIMEOUT if failure.failure_class is FailureClass.TIMEOUT else TaskStatus.FAILED, ...)`.
   - **Deleted (P3):**
     - the `QuotaExhaustedError` clause and the `(TransientProviderError, RateLimitedError, asyncio.TimeoutError)` clause;
     - `_CONTRACT_FAILURE_EXCEPTIONS` and its clause;
     - the post-classification `isinstance` branches;
     - `is_token_limit`;
     - the "Avoid this error" feedback.
   - **Unchanged behaviour.** Provider and contract retry behaviour is preserved, because the 3.8.3 class table and `retry_policy` reproduce it.
6. **Model mapping.** Map the `plan88_002` failure columns (3.1.8):
   - `failure_origin` as `Enum(FailureOrigin, native_enum=False, length=32)`;
   - `failure_class` as `Enum(FailureClass, native_enum=False, length=40)`;
   - `failure_fingerprint` as `String(64)`;
   - `TaskExecution.failure_json` as `JSONB`.
7. **TUI.** `clients/tui/app.py` and `widgets/mission_panel.py` store a client-side view (`task_id`, `agent_name`, `status`) instead of building a backend `TaskResult` from SSE events. The validator is not relaxed.

**Tests:**
- **`test_failure_classification.py`** (unit, no I/O):
  - **Provider and contract:** `test_quota_is_provider_not_retryable`; `test_rate_limited_is_transient_retryable`; `test_raw_sdk_rate_limit_is_transient_provider`, using a raw `ModelHTTPError(status_code=429)`; `test_provider_retryable_follows_retry_policy`; `test_contract_violation_is_agent_contract`; `test_pydantic_validation_error_is_agent_contract`; `test_unexpected_model_behavior_is_agent_contract`; `test_usage_limit_exceeded_is_agent_contract`.
  - **Control, environment and platform:** `test_budget_exceeded_is_control`; `test_env_error_is_environment`; `test_timeout_is_agent_timeout`; `test_db_connection_error_is_platform_transient`; `test_db_constraint_violation_is_platform_defect`; `test_external_service_error_is_platform_transient`.
  - **Tool errors:** `test_scope_violation_is_agent_tool_error`; `test_agent_tool_dirs_exist`, which checks that each resolved directory exists and holds `__init__.py`.
  - **Frame-path test:** `test_platform_frame_is_platform_defect`; `test_missing_third_party_import_is_dependency_missing`; `test_missing_internal_module_is_platform_defect`; `test_import_module_failure_is_platform`; `test_json_error_from_platform_caller_is_platform`; `test_site_packages_error_not_platform`; `test_site_packages_nested_in_stdlib_not_skipped`; `test_target_package_named_modules_not_platform`.
  - **Workflow and constructors:** `test_workflow_step_failure_passes_through`, plus every explicit constructor's origin, class, retryability and summary.
  - **Fingerprint:** `test_upstream_cascade_one_fingerprint`; `test_distinct_upstream_ids_distinct_fingerprints` (`v1-task-001` against `v1-task-002`); `test_distinct_platform_sites_have_distinct_fingerprints`; `test_fingerprint_has_no_line_numbers`.
  - **Policy and bounds:** `test_unknown_uses_config_retryable`; `test_summary_format_and_bound`; `test_evidence_redacted_and_bounded`.
- **`test_failures_config.py`:** `test_file_required`; `test_missing_key_rejected`.
- **`test_failure_capture.py`:**
  - **Construction:** `test_failed_result_requires_failure`; `test_every_failed_fork_carries_failure`, which drives the standard, convergence, research and `workflow:` forks to FAILED or TIMEOUT.
  - **Retry handler:** `test_retry_decision_follows_failure_retryable`, parametrised over one exception per class; `test_timeout_class_sets_timeout_status`; `test_final_attempt_in_retry_history`; `test_platform_defect_not_retried`; `test_budget_exceeded_not_retried`.
  - **Workflow errors:** `test_workflow_step_env_error_is_env_unavailable`; `test_workflow_halt_is_agent_reported_failure`.
  - **Spend:** `test_research_failure_keeps_spend`.
  - **Call sites:** `test_failed_result_callers_pass_task_failure`, an AST check that every `failed_result` call passes a second positional argument or `failure=`, and that no `_failed_result` definition remains under `modules/backend`.

**Done when:**
- The tests above and the modified existing tests pass.
- `grep -rn "Avoid this error\|_CONTRACT_FAILURE_EXCEPTIONS\|is_token_limit\|extract_first_task_failure" modules/backend` returns nothing.

### 88.2.3c `verification_failed` gate actions

A behaviour fix kept as its own commit so that it can be reverted alone. It needs only `control(...)` from 88.2.3b.

**Files:**
- modify `agents/mission_control/dispatch/retry_handler.py`, `agents/mission_control/gate_prompt.py`, `clients/cli/gate.py`, `clients/tui/widgets/gate_modal.py`;
- modify `tests/unit/backend/mission_control/test_dispatch.py`, where `TestRetryModifyAction` becomes an abort assertion, and `tests/unit/clients/tui/test_gate_modal.py`.

**Current state:**
- `retry_handler.py:471-484` returns a verification-failed output as `SUCCESS` on `MODIFY`.
- `gate_prompt.py` and both gate clients offer `MODIFY` at `verification_failed`.
- `CONTINUE`, which `NoOpGate` returns, falls through to a retry.

**Change.** At `verification_failed`:
- `CONTINUE` and `RETRY` both retry, as today;
- `SKIP` skips;
- `ABORT` aborts with `control(CANCELLED, "aborted at verification_failed gate")`;
- `MODIFY` and any other action are treated as `ABORT`.

The `MODIFY` branch is deleted (P3). `MODIFY` is removed from the `verification_failed` vocabulary in `gate_prompt.py`, `clients/cli/gate.py` and `clients/tui/widgets/gate_modal.py` (contracts 3.3.6).

**Tests:** `test_noop_gate_verification_failure_retries`; `test_modify_at_verification_failed_aborts`.

**Done when:**
- The tests pass, along with `pytest tests/unit/clients/tui/test_gate_modal.py -q`.
- `grep -rn "GateAction.MODIFY" modules/backend/agents modules/clients` lists no `verification_failed` use.

### 88.2.4 Idempotent `execute_plan_task` activity with heartbeats

**Files:**
- create `services/run_task_execution.py` and `temporal/task_activities.py`;
- modify `models/task.py`, `services/mission_context.py`, `services/mission_plan.py` (`retry_task`), `services/mission_run.py` (`finalise`), `services/workflow_run.py`, `services/workflow_run_waves.py`, `agents/mission_control/persistence_bridge.py` (`persist_task_result`), `services/execution_persistence.py`, `events/mission_run_types.py`, `events/types.py`, `temporal/mission_run_models.py`, `temporal/activity_helpers.py`, `temporal/mission_run_activities.py`, `temporal/worker.py`;
- create `tests/integration/backend/services/test_run_task_execution.py` and `tests/unit/backend/temporal/test_task_activities.py`.

**Current state:**
- The whole wave is one activity, `execute_mission`, taking `ExecuteWaveInput` (88.1.8). A retry re-dispatches the whole wave.
- `retry_task` (`services/mission_plan.py:523-555`) increments `retry_count` (`:539`), and `write_back_task_results` increments it again (`mission_plan_taskio.py:208`, `:231`). 88.2.4 deletes those two increments (contracts 3.1.9), which leaves `retry_task` as the only increment; 88.2.6 deletes `write_back_task_results` itself.
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
       failure_reason: str | None           # TaskFailure.summary (contracts 3.8)
       failure_origin: str | None           # FailureOrigin value; set exactly when status == "failed"
       failure_class: str | None            # FailureClass value
       failure_fingerprint: str | None


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
     4. If `task.status` is COMPLETED or SKIPPED with no such row, return outcome `"replay"` with `stored = ExecuteTaskResult(task_id, task.status.value, False, float(task.cost_usd), True, task.failure_reason, None, None, None)`. A replay rebuilt from a `task_executions` row (step 3) reads `failure_origin`, `failure_class` and `failure_fingerprint` from that row.
     5. Status APPROVED transitions APPROVED→QUEUED→RUNNING; QUEUED transitions QUEUED→RUNNING; RUNNING stays RUNNING (3.1.9 rule 2, interrupted attempt). Any other status raises `MissionRunStateError`.
     6. Set `last_attempt_at = utc_now()`. Read `mission.execution_environment` (`"local"` when NULL, as `dispatch_approved` does today) and `mission.repo_root`. Build `task_definition = task_definition_from_row(task)`. Commit.

     The row lock is released before the agent call, which can last up to `execute_task.start_to_close_seconds`. The UNIQUE `idempotency_key` arbitrates between concurrent attempts.
   - **`record`, transaction B (short):**
     1. Lock the task row again. If a row with `idempotency_key = key` exists, roll back and return it with `idempotent_replay=True`: a duplicate attempt finished first.
     2. Otherwise, in one transaction:
        - `persist_task_result(..., execution_record_id=execution_record_id, mission_run_id=mission_run_id, idempotency_key=key)`;
        - when the result status is SUCCESS and `context_updates` is not empty, `MissionContextManager(self._session).apply_updates(mission_id, task_result.context_updates, agent_id=task_result.agent_name, mission_id_ref=mission_id, task_id=task_id, mission_run_id=mission_run_id)`. 88.3.2 replaces `mission_id_ref` with `reason` and keeps `mission_run_id`;
        - the task transition, mapping `TaskResult.status` SUCCESS to COMPLETED, FAILED and TIMEOUT to FAILED, SKIPPED to SKIPPED;
        - `tasks.cost_usd`, `tasks.duration_seconds`, and `tasks.result_summary = json.dumps(task_result.output_reference)` on COMPLETED. On FAILED, `TaskRepository.set_failure(task, task_result.failure)` writes the four failure columns (contracts 3.8.6). `persist_task_result` (88.2.3) calls the `task_executions` twin, which also writes `failure_json`, for the in-process path as well.
     3. Commit.
     4. An `IntegrityError` on the `idempotency_key` unique index is caught: roll back, re-read the row and return it with `idempotent_replay=True`.
     - `verification_failed` is `status == FAILED and any(t.status == "fail" for t in (vo.tier_1, vo.tier_2, vo.tier_3))`, where `vo` is the result's `verification_outcome`. The same rule rebuilds `verification_failed` from a stored row.
     - `retry_count` is not touched.
   - **Single writer.** Add `TaskRepository.set_failure(task, failure: TaskFailure | None)` and its `task_executions` twin in `repositories/execution_record.py`. They are the only code that writes or clears `failure_reason`, `failure_origin`, `failure_class`, `failure_fingerprint` and, for the twin, `failure_json`.
     - They write enum members, so the stored values are names (`CONTROL`, `CANCELLED`); lowercase values appear only in `ExecuteTaskResult` and events (3.0.2).
     - `None` clears all of them.
   - **`mark_cancelled`** transitions RUNNING→FAILED with `set_failure(task, get_failure_classifier().control(FailureClass.CANCELLED, "cancelled"))`, and commits in its own session.
   - **Other writers of FAILED tasks** (contracts 3.8.6) call `set_failure`:
     - `MissionRunService.finalise` step 2 fails every QUEUED or RUNNING task with `orphaned(detail)` when `reason` is `ORPHANED_WORKFLOW_CLOSED` or `ORPHANED_WORKFLOW_NOT_FOUND`, and with `control(FailureClass.RUN_ABORTED, reason)` otherwise. The reconciler fails tasks only through `finalise` (88.1.10a).
     - `WorkflowRunService._fail_remaining_plan_tasks` and `workflow_run_waves._sync_plan_task_states` write the step's `TaskFailure` (88.2.3b item 4), or `control(FailureClass.RUN_ABORTED, error)` when the run failed without a step failure.
   - **`retry_task`** (`services/mission_plan.py`) calls `set_failure(task, None)`. The attempt's record stays on its `task_executions` row.
   - **`resolve_failed`** loads the task with `WHERE id = :task_id AND mission_run_id = :run_id`, else `NotFoundError`.
     - `retry` calls `MissionPlanService.retry_task(plan_id, task_id, user_id=mission.owner_id)`. That is the only `retry_count` increment.
     - `skip` transitions FAILED→SKIPPED and calls `set_failure(task, None)`; the attempt's record stays on `task_executions`.
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
                   try:
                       runtime = await build_dispatch_runtime(
                           db_session=db, event_bus=bus, mission_id=claim.mission_id,
                           session_id=input.session_id, execution_mode=claim.execution_mode,
                           mission_repo_root=claim.mission_repo_root, container_image=None,
                           extra_volumes=None, mission_run_id=input.mission_run_id, task_id=input.task_id,
                       )
                   except ExecutionEnvironmentError as exc:                    # 88.2.3a: fail the task, not the run
                       result = failed_result(
                           claim.task_definition,
                           get_failure_classifier().from_exception(exc),
                       )
                   else:
                       upstream = await load_dependency_outputs(db, input.task_id)
                       result = await run_single_task(
                           task=claim.task_definition, runtime=runtime, upstream_outputs=upstream,
                           mission_id=claim.mission_id, budget_usd=0.0, event_bus=bus,
                           session_id=input.session_id, gate=None,
                       )                                                        # budget_usd feeds GateContext only; gate=None ignores it
           except asyncio.CancelledError:
               async with get_async_session() as db:
                   await RunTaskExecutionService(db).mark_cancelled(input.mission_run_id, input.task_id)
               raise
           finally:
               await redis.aclose()
           hb.phase = "record"
           async with get_async_session() as db:
               recorded = await RunTaskExecutionService(db).record(
                   mission_run_id=input.mission_run_id,
                   task_id=input.task_id,
                   idempotency_key=claim.idempotency_key,
                   execution_record_id=input.execution_record_id,
                   task_result_json=result.model_dump(mode="json"),
               )
           if recorded.status == "failed" and not recorded.idempotent_replay:     # contracts 3.6.1, after commit
               redis = AsyncRedis.from_url(get_redis_url())
               try:
                   await SessionEventBus(redis, mission_id=claim.mission_id).publish(
                       task_failed_event(result, mission_id=claim.mission_id,
                                         mission_run_id=input.mission_run_id, session_id=input.session_id)
                   )
               finally:
                   await redis.aclose()
           return recorded


   @activity.defn
   async def resolve_failed_task(input: ResolveTaskInput) -> None:
       async with get_async_session() as db:
           await RunTaskExecutionService(db).resolve_failed(input.mission_run_id, input.task_id, input.action)
   ```
   - The activity raises only for infrastructure errors. A failed agent task returns `status="failed"`, so Temporal never retries an agent failure. An `ExecutionEnvironmentError` from `build_dispatch_runtime` (88.2.3a) is a failed task with `ENV_UNAVAILABLE`, not an activity error, so one unavailable environment does not end the run as `task_failures`.
   - **`TaskFailedEvent`.** The event and its builder `task_failed_event(result: TaskResult, *, mission_id: str, mission_run_id: str, session_id: str) -> TaskFailedEvent` live in `events/mission_run_types.py`, and the event is registered in `EVENT_TYPE_MAP` (contracts 3.6.1).
     - It is published only after `record` commits, and never for a replay. One failed attempt therefore gives at most one event: a crash between commit and publish loses it.
     - The `task_executions` row is the durable record; the event is for display (rule 014).
     - A cancelled attempt is recorded on `tasks` only and emits no event.
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
  - `test_record_failed_writes_failure_columns`: a FAILED result with a `PLATFORM`/`PLATFORM_DEPENDENCY_MISSING` failure writes `failure_reason`, `failure_origin`, `failure_class` and `failure_fingerprint` on `tasks`, the same three columns plus `failure_json` on `task_executions`, and the stored enum name `PLATFORM_DEPENDENCY_MISSING`.
  - `test_failed_replay_returns_failure_fields`: replaying a FAILED attempt returns the same `failure_class` and `failure_fingerprint`.
  - `test_retry_keeps_attempt_failure`: `resolve_failed("retry")` clears the `tasks` failure columns, and the first attempt's `task_executions` row still holds them.
  - `test_mark_cancelled_is_control_cancelled`: the stored names are `CONTROL` and `CANCELLED`.
  - `test_no_failed_task_without_class`: run the following, then check that `SELECT count(*) FROM tasks WHERE status = 'FAILED' AND failure_class IS NULL` is 0:
    - a run with one success, one failure and one cancellation;
    - a run ended by `finalise` with a QUEUED task (`RUN_ABORTED`);
    - an orphaned run failed by the reconciler (`ORPHANED`);
    - a failed WorkflowRun step, and a container step on a mission without `repo_root` (`ENV_UNAVAILABLE`).
  - `test_skip_clears_failure_columns`: all four columns, `failure_reason` included, are NULL after a skip.
- `test_task_activities.py` (unit, `ActivityEnvironment` from `temporalio.testing`, with the services and `run_single_task` patched):
  - `test_replay_skips_agent`: when `claim` returns outcome `"replay"`, `run_single_task` is not awaited.
  - `test_heartbeats_emitted`: interval 0.01s and an agent that sleeps 0.05s give at least 3 heartbeats, each with a `phase` key.
  - `test_cancel_marks_failed_and_reraises`: cancelling the environment calls `mark_cancelled` and raises `CancelledError`.
  - `test_agent_failure_returns_failed_not_raises`: a FAILED `TaskResult` gives `status == "failed"`.
  - `test_environment_error_fails_task_not_activity`: a patched `build_dispatch_runtime` raising `ExecutionEnvironmentError` gives `status == "failed"`, `failure_class == "env_unavailable"`, and no raise.
  - `test_task_failed_event_published_once`: one failed attempt publishes one `TaskFailedEvent` with `mission_id` set; a replay publishes none.

**Done when:** both test files pass, `python -m modules.backend.temporal.worker` starts with no import errors, and `grep -rnE "\.failure_(reason|origin|class|fingerprint) = " modules/backend --include=*.py --exclude=session_followup.py` matches only `repositories/task.py` and `repositories/execution_record.py` (`session_followup.py` writes the unrelated `session_followups.failure_reason` column).

### 88.2.4a Planning Agent sees task states and failures

The Planning Agent row of contracts 3.8.6. It follows 88.2.4, because it reads the failure columns that 88.2.4 starts writing.

**Files:**
- modify `services/mission_plan_taskio.py`, `services/mission_plan_orchestrator.py`, `agents/mission_control/helpers/agent_executor.py` (`_call_planning_agent`) and `agents/mission_control/helpers/prompt_builder.py` (`_build_planning_prompt`);
- extend `tests/unit/backend/mission_control/test_failure_capture.py`.

**Current state.** `materialize_plan_dict` (`services/mission_plan_taskio.py:25-58`) feeds `current_plan`, which `PlanBuildingSession` seeds into `TaskPlan.model_validate` (`agents/mission/planning/build_session.py:159-161`, `:404`). `TaskDefinition` forbids extra keys (`schemas/task_plan.py:289-292`), so status and failure cannot travel there. The existing `recent_failures` input is cross-run history and is unchanged.

**Change:**
- `materialize_plan_dict` is unchanged and stays TaskPlan-valid.
- Add `mission_plan_taskio.materialize_task_states(plan, *, mission_run_id) -> list[dict]`, scoped like `materialize_plan_dict` (the run's tasks and the backlog). Each entry is `{task_id, status, failure}`: `status` is the lowercase value, and `failure` is `{origin, failure_class, summary}` read from the `tasks` columns for FAILED tasks, otherwise `None`.
- `MissionPlanOrchestrator.refine` passes it to `_call_planning_agent(..., task_states=...)`. `_build_planning_prompt` renders it beside `current_plan`.
- It is never seeded into `PlanBuildingSession.tasks`.

**Tests:**
- `test_materialize_task_states_carries_failure`.
- `test_refine_with_failed_task_finalises`: a plan with one FAILED task refines, and `finalise()` returns a valid `TaskPlan`.

**Done when:** the tests pass, and `tests/unit/backend/mission_control/test_dispatch.py` passes unchanged.

### 88.2.5 Copilot client health check and restart

**Files:**
- modify `core/copilot_model.py`, `temporal/task_activities.py`;
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
- `temporal/task_activities.py` imports `CopilotModel` from `core/copilot_model.py` directly and adds `await CopilotModel.ensure_healthy()` at the start of `execute_plan_task`, before `claim` (change item 6 of 88.2.4, deferred to this step because the method did not exist yet).

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
- modify `temporal/mission_run_workflow.py`, `temporal/mission_run_models.py`, `temporal/config_snapshots.py`, `temporal/supervisor_activities.py`, `temporal/worker.py`, `agents/mission_control/gate_post_run.py`, `agents/adapters/plan_introspection.py`, `services/execution_persistence.py`, `services/mission_run.py`, `services/mission_plan.py`, `services/mission_plan_orchestrator.py`, `repositories/task.py`, `api/v1/endpoints/missions_plan.py`, `api/v1/endpoints/executions.py`, `core/config_schema.py`, `config/settings/temporal.yaml`;
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
   `_supervise(seen)` holds the 88.1.8 supervisor block unchanged (`evaluate_post_run`, `fire_supervisor_followups`, `check_plan_active`, then the branches on `ev.action`), except two points: the `wait` arm (item 5), and the wave fields of `SupervisorFollowupInput`, which now come from the per-task results (item 3): `wave_status=self._wave_status`, `wave_cost_usd=self._wave_cost_usd`, `failure_reason=self._wave_failure_reason`. The `advance_refine` branch formats `REFINE_PROMPT` with a `failures` block rendered by `_render_failures(self._wave_failures, self._wave_failures_truncated)` (item 3), so the Director's refine turn sees the classified failures instead of a bare "had failures". `check_plan_active` stays in Phase 2: 88.4.2 rewrites its body to read `missions.status`, 88.4.5 stops calling it under patch id `p88-lifecycle-signals`, and it is deleted in 88.4.5 only when no caller remains.
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
       self._wave_failures, self._wave_failures_truncated = digest_failures(
           failed_results, cfg.max_failure_digests,
       )
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
               self._wave_results[task_id] = dataclasses.replace(
                   result, status="skipped", failure_origin=None, failure_class=None, failure_fingerprint=None,
               )                                     # 3.3.5: failure fields are set only when status == "failed"
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
   Module-level helper in `mission_run_workflow.py` (pure, no I/O, deterministic). The digests come from `digest_failures` (contracts 3.3.4), the single grouping rule, which also serves the post-run reviewer:
   ```python
   def _render_failures(digests: list[TaskFailureDigest], truncated: int) -> str:
       lines = [f"- [{d.origin}/{d.failure_class}] x{d.occurrences} task {d.task_id}: {d.summary}" for d in digests]
       if truncated:
           lines.append(f"- and {truncated} more distinct failures (see TaskFailedEvent history)")
       return "\n".join(lines) if lines else "- none"
   ```
   A FAILED task without a verification failure stays FAILED and no gate runs; the supervisor sees it in `evaluate_post_run`, now with its class and origin. `_layer_boundary()` runs before each chunk. 88.4.5 and 88.4.6 extend `_layer_boundary` with `_pause_point()` and `_budget_point()`.
   - **Supervisor inputs.** When every layer has run, `_execute_layers` aggregates the final `ExecuteTaskResult` of each task (the retried result after a `retry`, `status="skipped"` after a `skip`) into `self._wave_status` (`"failed"` if any task failed, else `"completed"`), `self._wave_cost_usd` (sum of `cost_usd`) and `self._wave_failure_reason` (the first failed task's `failure_reason`, else `None`). `_supervise` builds `SupervisorFollowupInput` from these three fields (3.3.4, 3.3.5); nothing else feeds them. It also builds `self._wave_failures` and `self._wave_failures_truncated`: one `TaskFailureDigest` per distinct fingerprint, capped by `RunConfigSnapshot.max_failure_digests` (contracts 3.8.6). Only `REFINE_PROMPT` uses them. `build_run_config_snapshot` gains `max_failure_digests` from `get_app_config().failures.supervisor.max_failure_digests` in this step. `REFINE_PROMPT` gains a `{failures}` placeholder.
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
   - **Failures for the reviewer** (decision 15, contracts 3.8.6). Add `summary["failures"]` and `summary["failures_truncated"]` from the run's FAILED tasks, grouped by `failure_fingerprint`.
     - `TaskRepository.failed_tasks_for_run(mission_run_id)` returns the run's FAILED rows ordered by `last_attempt_at, id`. `MissionRunService` passes them to `digest_failures` (contracts 3.3.4), the same function the workflow uses, so the grouping rule exists once.
     - Each entry is `{origin, failure_class, summary, occurrences}`. `summary` is the first task's `failure_reason`; `origin` and `failure_class` are lowercase values.
     - The list is capped at `get_app_config().failures.supervisor.max_failure_digests`. The activity reads config, which workflow code may not.
     - `GateContext.plan_task_summary` carries the result, so both the deterministic rules and the Haiku fallback see the classes, not just a FAILED count.
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
    - `mission_plan_taskio.write_back_task_results`, `derive_subset_task_plan` and `materialize_task_plan`, whose only caller was `dispatch_approved`, with their test classes (`test_mission_plan_orchestrator.py:181-322`). Its `retry_count` increments were already removed in 88.2.4. `load_prior_outputs` and `materialize_plan_dict` stay.

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
- `test_supervisor_input_from_task_results`: one layer with two tasks. The stub returns COMPLETED with `cost_usd=0.5` for the first. For the second it returns FAILED with `cost_usd=0.25`, `failure_reason="boom"`, `failure_origin="agent"`, `failure_class="agent_reported_failure"`, `failure_fingerprint="f1"` and `verification_failed=False`. The `fire_supervisor_followups` stub receives `wave_status == "failed"`, `wave_cost_usd == 0.75` and `failure_reason == "boom"`.
- `test_failures_deduped_by_fingerprint` (unit test of `digest_failures`): three FAILED results, two sharing fingerprint `f1`, give two digests, the first with `occurrences == 2`.
- `test_failures_cap_counts_truncated`: with `max_failure_digests=1` and two distinct fingerprints, one digest is kept and the truncated count is 1.
- `test_skip_clears_failure_fields`: after a gate `skip`, the stored wave result has `status == "skipped"` and no failure fields.
- `tests/integration/backend/temporal/test_supervisor_activities.py::test_post_run_context_carries_failure_digests` (real DB): two FAILED tasks sharing a fingerprint and one with another give `plan_task_summary["failures"]` with two entries, the first with `occurrences == 2`.
- `test_refine_prompt_lists_failures`: evaluate returns `advance_refine` after a failed wave; the `start_director_turn` stub's message contains the digest line `[agent/agent_reported_failure]`.
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
   REDACT_KEYS = frozenset({"objective", "prompt", "output_data", "mission_brief", "message", "instructions",
                            "failure_reason", "summary"})   # failure text (decision 15) never reaches a committed fixture

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
pytest tests/unit/backend/temporal tests/unit/backend/core/test_config_schema_plan88_phase2.py tests/unit/backend/core/test_copilot_health.py tests/unit/backend/core/test_failure_classification.py tests/unit/backend/core/test_failures_config.py tests/unit/backend/mission_control tests/unit/backend/agents tests/unit/backend/config tests/unit/backend/services/test_execution_persistence.py tests/unit/clients/tui/test_gate_modal.py tests/unit/clients/tui/test_mission_panel.py tests/agents/security/test_secret_detection_redaction.py -q
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
grep -rn "_run_local\|falling back to local\|Avoid this error\|Task failed during dispatch" modules/backend   # expect no output
grep -n "find_project_root" modules/backend/agents/mission_control/helpers/cli_executor.py   # expect no output
grep -n "repo_root.*find_project_root" modules/backend/agents/mission_control/runtime.py   # expect no output
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

Then run a failure drill on the dev stack:
1. Start a run in container mode with Docker stopped. Every task's `tasks` row has `failure_class = 'ENV_UNAVAILABLE'` (stored name), no task runs locally, and the run does not end as `task_failures`.
2. Start a run with a task assigned to an agent whose catalog row has no Python module. The task's `task_executions` row has `failure_origin = 'PLATFORM'` and `failure_class = 'PLATFORM_DEFECT'` (stored names). The task is not retried, the mission event stream shows one `task.failed` event, the post-run reviewer's `plan_task_summary["failures"]` holds the digest, and the Director's refine message lists it.

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
5. **Stall detection reads the wrong unit.** Stall detection (`gate_post_run.py:141-153`) reads `recent_run_outcomes` per ExecutionRecord. With one record per run, it measures runs, not waves. **Mitigation (88.2.6 review follow-up):** `MissionRunWorkflowState.zero_completion_waves` counts consecutive waves of the run with no completed task; `evaluate_post_run` passes it as `plan_task_summary["zero_completion_waves"]` and breaker #3 escalates at the stall threshold. The per-record check remains and now reads consecutive runs.
6. **Phases 2 and 3 run without budget enforcement or in-run gates.** contracts 3.0.1 places budget enforcement in 88.4.6 and durable gates in 88.4.8. From 88.2.6, the Temporal path has no plan-ceiling check (it lived in `dispatch_approved`), and the `post_task`, `verification_failed` and `post_layer` gates return `continue` for every gate mode. MANUAL and AI_ASSISTED missions keep human control only through task approval (PROPOSED→APPROVED). **Mitigation:**
   - post-run breaker #1 still escalates a run when the plan's summed task cost reaches `budget_usd_ceiling` (88.2.6 item 8);
   - **Operational rule** (also a Phase 2 entry criterion): until Phase 4 is complete, production keeps mission schedules disabled (`missions.recurrence.enabled: false`, set in 88.2.10 step 1; `MissionScheduleService.create_schedule` and the tick workflow refuse while it is false, 88.1.1) and does not dispatch MANUAL or AI_ASSISTED missions.
7. **Fail-closed boundary breaks work that relied on the silent fallback.** From 88.2.3a, the following fail with `ENV_UNAVAILABLE` instead of running locally:
   - the two write-capable security agents in a local-mode mission (the default), through the write guard;
   - container missions without Docker or without `repo_root`;
   - container workflow steps (for example the `security.webapp-assessment` steps) on a mission without `repo_root`.

   Worktree is rejected at mission create and update, because no backend exists. `codex`, `copilot` and write-capable `claude_code` agents are blocked until CLI engines run inside the container. No catalog agent uses them today. A read-only `claude_code` session can still read outside its worktree, because it runs on the host; this is accepted until that later plan. **Mitigation:** this is the intended behaviour (P8, decision 15). The failure is typed and visible in the Console, and the fix is to provide the environment or set `repo_root`, never to restore the fallback.
8. **Misclassification.** A mechanical rule can put a failure in the wrong class. The costly cases are a deterministic fault marked retryable, which wastes retries, and an agent-caused error labelled a platform defect, which raises false alarms. **Mitigation:**
   - only four classes are retryable, and `UNKNOWN` keeps today's behaviour through config (3.8.3);
   - agent-raised tool errors are `AGENT_TOOL_ERROR`, not platform defects (3.8.3 step 7);
   - the frame-path test uses resolved file paths, so target content cannot claim platform origin;
   - no `TARGET` origin exists in Plan 88, so nothing can mislabel a platform fault as target code (3.8.7);
   - Plan 88 acts on the class only to stop retries and to inform the supervisor; no repair runs on it.
