## Phase 3: Memory between runs

Run N must start knowing what run N-1 did, what changed in the Mission Context Document (MCD) since then, and what the mission has learned. This phase adds a mandatory end-of-run digest, the MCD delta between run watermarks, learnings in the context packet, prior outputs limited to the current run, and deterministic MCD compaction in place of rejected writes. It also fixes learning occurrence-count inflation.

**Entry criteria:** Phases 0, 1 and 2 are merged to `main`. Concretely:
- `git status --porcelain` lists no changes under `modules/`, `config/`, `tests/`, `requirements*.txt`, `pyproject.toml` or `mc.py`/`admin.py`/`services.py`. Uncommitted work in progress is committed or stashed first. If such work is committed, re-verify by symbol the line citations in the files it touched before starting this phase.
- `alembic heads` returns only `plan88_003`. Phase 3 adds no migration.
- `plan88_002_mission_runs` is applied, so these exist: `mission_runs`, `mission_run_digests`, `context_changes.mission_run_id`, `ix_context_changes_context_version (context_id, version)`, `tasks.mission_run_id`, `task_executions.mission_run_id`, `task_executions.idempotency_key`, `llm_calls.mission_run_id` and `llm_calls.task_id`.
- These symbols exist on `main`:
  - `MissionRunService.begin`, `plan` and `finalise` (88.1.7), with `begin` writing `context_version_start` and `previous_run_id`, and `finalise` writing `cost_usd` through `LlmLedgerRepository.sum_cost` (`repositories/llm_ledger.py`, 88.1.7);
  - `handle_mission(execution_label, ...)`, renamed from the legacy `mission_run_id` positional in 88.1.7;
  - `MissionRunRepository.get_latest_with_digest`, `MissionRunDigestRepository.get_by_run` and `TaskRepository.list_by_run` (88.1.4);
  - `mc runs digest SEQ` (88.1.13) and `GET /missions/{id}/runs/{run_id_or_seq}` returning `MissionRunDetailResponse.digest` (88.1.7, 88.1.12);
  - `MissionRunWorkflow._end_run(status, reason, detail)`, the module-level `_exec(fn, arg, p)` and `_cause_type(e)`, and `@workflow.init` (88.1.8);
  - `temporal/activity_options.py` with `activity_kwargs(p)` (88.0.2);
  - `DispatchRuntime`, `build_dispatch_runtime(..., mission_run_id, task_id)` in `agents/mission_control/runtime.py`, with `handle_mission` passing `mission_run_id=None`, and `run_single_task` with `_inject_context` in `agents/mission_control/dispatch/task_runner.py` (88.2.3);
  - `execute_plan_task` and `RunTaskExecutionService.record`, which applies MCD updates through `MissionContextManager.apply_updates`, and the `mission_run_id` keyword on `apply_updates` (88.2.4);
  - `record_llm_call(..., mission_run_id=..., task_id=...)` (88.2.3);
  - `temporal/versioning.PATCH_IDS`, `tests/unit/backend/temporal/test_patch_ids.py`, the replay harness `tests/unit/backend/temporal/test_replay_histories.py` with its seven Phase 2 fixtures (88.2.9 item 3) under `tests/fixtures/temporal_histories/mission_run/`, and `tests/unit/backend/temporal/test_no_config_in_workflows.py` over `*workflow*.py` (88.2.2, 88.2.8, 88.2.9).
- If any item is missing, stop. Do not start this phase.

Budget is out of scope here. Phase 3 contains no budget branch: `BudgetService`, `check_run` and budget-aware digest generation belong to Phase 4 (88.4.1, 88.4.6).

Line references were verified at `a28ca771`. Backend and config are identical to `9adaa69d` and `777cd5c5`. Where an earlier Plan 88 step rewrites a file, this phase names the function and the owning step instead of a line number. Paths are relative to `modules/backend/` unless they start with `config/`, `tests/`, `scripts/`, `docs/` or `modules/clients/`.

---

### 88.3.1 Config keys for digest, context packet and compaction

**Files**
- modify `config/settings/missions.yaml`
- modify `core/config_schema.py`
- modify `tests/unit/backend/core/test_config.py`

**Current state**
- `missions.yaml:17-19` has `pcd_max_size_bytes`, `pcd_target_size_bytes` and `pcd_prune_threshold_pct`. Nothing reads `pcd_prune_threshold_pct` today. In `config_schema.py:474-476` all three carry hardcoded defaults.
- `missions.yaml:40-47` (`knowledge.learnings`) has `context_assembler_reserve_tokens` and `context_assembler_max_entries`. `KnowledgeLearningsSchema` (`config_schema.py:421-430`) and `KnowledgeSchema.learnings` use defaults and `default_factory`.
- The context assembler hardcodes fallback budgets, which breaks the no-fallbacks rule:
  - `context_assembler.py:31-42` falls back to `50_000` / `1_500`;
  - `context_assembler.py:46` defines `DEFAULT_TOKEN_BUDGET = 50_000`;
  - `context_assembler.py:49-60` falls back to `1500` / `5`.
- `summarization.py:58` hardcodes `max_age_days: int = 90`, and `summarization.py:128` hardcodes `keep_recent: int = 5`.

**Change**
1. Append to `missions.yaml`, after the blocks Phase 1 added (`recurrence`). Do not add `budgets`; Phase 4 owns it.

```yaml
digest:
  agent_name: "mission.digest.agent"   # catalog agent, config/agents/mission/digest/agent.yaml
  summary_max_chars: 2000
  max_outcomes: 50
  headline_max_chars: 200              # outcome headline and open-item text truncation
  task_excerpt_max_chars: 1500         # per-task output excerpt sent to the digest agent
  agent_output_retries: 2              # pydantic-ai output_retries for the digest agent
context_packet:
  previous_digest_max_chars: 4000
  context_delta_max_changes: 100
  context_delta_max_tokens: 2000
  context_delta_value_max_chars: 200
  assembly_order: [previous_run_digest, context_delta, code_map, learnings, history]
compaction:
  decisions_max_age_days: 90
  keep_recent_milestones: 5
  protected_roots: [identity, guardrails, current_state]
```

2. Add `extraction_window_days: 30` under `knowledge.learnings`.

3. In `config_schema.py`, add these classes above `MissionsSchema`:

```python
_PACKET_LAYERS = ("previous_run_digest", "context_delta", "code_map", "learnings", "history")
_MCD_RESTRICTED_ROOTS = frozenset({"version", "last_updated", "last_updated_by"})


class DigestSchema(_StrictBase):
    agent_name: str = Field(..., min_length=1)
    summary_max_chars: int = Field(..., ge=200)
    max_outcomes: int = Field(..., ge=1)
    headline_max_chars: int = Field(..., ge=50)
    task_excerpt_max_chars: int = Field(..., ge=1)
    agent_output_retries: int = Field(..., ge=0)


class ContextPacketSchema(_StrictBase):
    previous_digest_max_chars: int = Field(..., ge=200)
    context_delta_max_changes: int = Field(..., ge=1)
    context_delta_max_tokens: int = Field(..., ge=1)
    context_delta_value_max_chars: int = Field(..., ge=50)
    assembly_order: list[
        Literal["previous_run_digest", "context_delta", "code_map", "learnings", "history"]
    ] = Field(...)

    @model_validator(mode="after")
    def _order_is_permutation(self) -> "ContextPacketSchema":
        if sorted(self.assembly_order) != sorted(_PACKET_LAYERS):
            raise ValueError("context_packet.assembly_order must list each of the 5 layers exactly once")
        return self


class CompactionSchema(_StrictBase):
    decisions_max_age_days: int = Field(..., ge=1)
    keep_recent_milestones: int = Field(..., ge=1)
    protected_roots: list[str] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _no_restricted_roots(self) -> "CompactionSchema":
        listed = _MCD_RESTRICTED_ROOTS.intersection(self.protected_roots)
        if listed:
            raise ValueError(f"compaction.protected_roots must not list {sorted(listed)}; they are always protected")
        return self
```

4. Wire the schemas in:
   - `MissionsSchema` gains `digest: DigestSchema = Field(...)`, `context_packet: ContextPacketSchema = Field(...)` and `compaction: CompactionSchema = Field(...)`.
   - `MissionsSchema.pcd_prune_threshold_pct` becomes `int = Field(..., ge=1, le=100)`.
   - Add a `@model_validator(mode="after")` on `MissionsSchema` that raises `ValueError` unless `pcd_target_size_bytes < pcd_max_size_bytes`.
   - `KnowledgeLearningsSchema` gains `extraction_window_days: int = Field(..., ge=1)`. Because that field is required, `KnowledgeSchema.learnings` becomes `KnowledgeLearningsSchema = Field(...)` and `MissionsSchema.knowledge` becomes `KnowledgeSchema = Field(...)`; delete both `default_factory` arguments.

**Tests**: in `tests/unit/backend/core/test_config.py`
- `test_context_packet_assembly_order_rejects_duplicate`: `["code_map", "code_map", "learnings", "history", "context_delta"]` raises `ValidationError`.
- `test_context_packet_assembly_order_rejects_missing_layer`: four layers raise `ValidationError`.
- `test_missions_target_below_max_required`: `pcd_target_size_bytes == pcd_max_size_bytes` raises.
- `test_compaction_protected_roots_rejects_restricted`: `protected_roots=["identity", "version"]` raises.
- `test_learnings_extraction_window_required`: a `knowledge.learnings` dict without `extraction_window_days` raises.
- `test_missions_yaml_loads`: `get_app_config().missions.compaction.keep_recent_milestones == 5` and `get_app_config().missions.knowledge.learnings.extraction_window_days == 30`.

**Done when:** `pytest tests/unit/backend/core/test_config.py -v` passes, and `python -c "from modules.backend.core.config import get_app_config; get_app_config().missions.context_packet"` exits 0.

---

### 88.3.2 MCD change attribution, row lock and watermark reads

**Files**
- modify `services/mission_context.py`
- modify `repositories/mission_context.py`
- modify `services/context_curator.py`
- modify `agents/mission_control/models.py` (`ContextCuratorProtocol`)
- modify `agents/mission_control/dispatch/loop.py` (MCD write-back in `_execute_layer`)
- modify `services/run_task_execution.py` (`RunTaskExecutionService.record`, exists since 88.2.4)
- modify `tools/update_context.py`
- modify `services/summarization.py` (two `apply_updates` call sites)
- modify `services/mission_run.py` (`begin`, exists since 88.1.7)
- create `services/mcd_pruning.py` (`mcd_size_bytes` only)

No migration. `ix_context_changes_context_version (context_id, version)` ships in `plan88_002` (88.1.2).

**Current state**
- **Attribution.** `ContextChange.mission_id` (`models/mission_context.py:155-159`) is filled from the caller's `mission_id_ref` (`mission_context.py:342`). The `update_context` tool (`tools/update_context.py:37-48`) and `SummarizationService` (`summarization.py:101,162`) never pass it, so their rows have `mission_id IS NULL`. A delta query on `mission_id` would miss them.
- **Conflict handling.** Change rows are inserted (`mission_context.py:333-345`) before the optimistic version update (`:347-353`). On conflict the method returns an error string (`:355-356`) and leaves orphan `context_changes` rows in the caller's transaction.
- **Size check.** The cap compares `len(str)` (characters) with a byte-named limit (`mission_context.py:324-330`, serialised with `ensure_ascii=False`).
- **Curator path.** `ContextCurator.apply_task_updates` forwards `mission_id_ref` (`context_curator.py:57-63`), and the write-back in `_execute_layer` passes `mission_id_ref=mission_id` (`loop.py:440-446` at baseline; 88.2.3 keeps this block in `_execute_layer`).

**Change**

1. **Repository.** In `MissionContextRepository`, add:

```python
async def get_by_mission_id_for_update(self, mission_id: str) -> MissionContext | None:
    """select(MissionContext).where(MissionContext.mission_id == mission_id).with_for_update()."""

async def get_version(self, mission_id: str) -> int:
    """Current MissionContext.version for the mission; 0 when no MCD exists."""
```

   In `ContextChangeRepository`, add:

```python
async def list_between(self, context_id: str, after_version: int, up_to_version: int,
                       limit: int) -> list[ContextChange]:
    """WHERE context_id = :cid AND version > :after AND version <= :upto
    ORDER BY version DESC, created_at DESC LIMIT :limit (newest kept when truncated)."""

async def count_between(self, context_id: str, after_version: int, up_to_version: int) -> int:
    """COUNT(*) with the same predicate as list_between."""

async def latest_change_at_by_root(self, context_id: str) -> dict[str, datetime]:
    """SELECT split_part(path, '.', 1) AS root, max(created_at) ... GROUP BY root."""
```

   All three filter on `context_id`, never `mission_id`, because legacy rows have `mission_id IS NULL`.

2. **New `apply_updates` signature** (contract 3.5.1; `mission_id_ref` is deleted, P3). The `mission_run_id` keyword exists since 88.2.4 with a `= None` default; this step removes that default, adds `reason` and makes every keyword required:

```python
async def apply_updates(self, mission_id: str, updates: list[dict], *, agent_id: str | None,
                        task_id: str | None, mission_run_id: str | None,
                        reason: str) -> tuple[int, list[str]]:
    """Steps 1 to 7 below."""
```

   `reason` is the batch reason. An update dict's own `reason` key wins; when absent, `reason` replaces today's `"no reason provided"`. The method works in this order:
   1. `ctx = await self._context_repo.get_by_mission_id_for_update(mission_id)`. When `ctx is None`, return `(0, ["MissionContext not found for mission"])` as today. The row lock serialises writers until the caller commits.
   2. Apply the ops to a deep copy, exactly as `mission_context.py:262-318` does today.
   3. Set `data["version"]`, `data["last_updated"]` and `data["last_updated_by"] = agent_id or "system"`.
   4. Measure `size = mcd_size_bytes(data)`. Create `services/mcd_pruning.py` in this step with only `def mcd_size_bytes(value: object) -> int: return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))`; 88.3.3 adds the rest of the module. Until 88.3.3 lands, the over-cap branch keeps today's rejection, compared in bytes.
   5. Call `update_context(...)` **first**, with `size_characters=len(json.dumps(data, ensure_ascii=False))` as today. If `rows_updated == 0`, raise `ConflictError("MCD version conflict")`. With the lock this is unreachable; it must never be swallowed.
   6. Then insert one `ContextChange` per applied change with `mission_id=mission_id` (always the MCD's own mission), `mission_run_id`, `task_id` and `agent_id`.
   7. Pop the cache entry and log as today.

3. **Changes between versions.** Add to `MissionContextManager`:

```python
async def get_changes_between(self, mission_id: str, after_version: int, up_to_version: int,
                              limit: int) -> list[ContextChange]:
    """Resolve the MCD's context_id, then ContextChangeRepository.list_between. [] when no MCD exists."""

async def count_changes_between(self, mission_id: str, after_version: int, up_to_version: int) -> int:
    """Resolve context_id, then ContextChangeRepository.count_between. 0 when no MCD exists."""
```

4. **Callers.** Every caller passes all four keyword arguments:
   - `ContextCurator.apply_task_updates` and `ContextCuratorProtocol.apply_task_updates` replace `mission_id_ref` with `mission_run_id: str | None` and forward `reason=f"task {task_id} context update"`.
   - The write-back in `_execute_layer` (`loop.py`) passes `mission_run_id=runtime.mission_run_id`, where `runtime` is the `DispatchRuntime` that `_execute_layer` passes to `run_single_task` (88.2.3). `DispatchRuntime.mission_run_id` is added in 88.3.5; until then pass `mission_run_id=None`.
   - `RunTaskExecutionService.record` (88.2.4, which already passes `mission_run_id`) calls `apply_updates(mission_id, context_updates, agent_id=agent_name, task_id=task_id, mission_run_id=mission_run_id, reason=f"task {task_id} context update")`.
   - `tools/update_context.py:37` passes `agent_id="workflow", task_id=None, mission_run_id=None, reason=reason or f"workflow update: {path}"`.
   - `summarization.py:101` and `:162` pass `task_id=None, mission_run_id=None` and the reason string they already build.

5. **Watermark.** `MissionRunService.begin` (88.1.7) reads `context_version_start` through `MissionContextRepository.get_version(mission_id)`, replacing its direct `MissionContext.version` read, in the same transaction that moves the run `PENDING → RUNNING`.

**Tests**: `tests/unit/backend/services/test_mission_context.py` (real `db_session`, existing fixtures)
- `test_apply_updates_sets_mission_id_on_every_change`: a call with `agent_id="workflow"` and `mission_run_id=None` produces rows where `mission_id == mission.id`.
- `test_apply_updates_records_mission_run_id`.
- `test_apply_updates_size_measured_in_utf8_bytes`: a value of one 3-byte character counts as 3 bytes in `mcd_size_bytes`.
- `test_apply_updates_no_orphan_changes_on_conflict`: monkeypatch `MissionContextRepository.update_context` to return 0. The call raises `ConflictError`, and the session holds no new `ContextChange`.
- `test_apply_updates_batch_reason_used_when_update_has_none`.
- `test_get_changes_between_bounds_exclusive_inclusive`: with versions 1..5, `(2, 4]` returns versions 4 and 3, in that order.
- `test_get_changes_between_includes_legacy_null_mission_id_rows`.

In `tests/integration/backend/services/test_mission_run_service.py` (exists since 88.1.7):
- `test_begin_sets_context_version_start_to_current_mcd_version`.

**Done when:** these tests pass, and `grep -rn --exclude-dir=migrations "mission_id_ref" modules tests` returns nothing.

---

### 88.3.3 Automatic deterministic MCD compaction

**Files**
- modify `services/mcd_pruning.py` (exists since 88.3.2)
- create `services/mission_context_compaction.py`
- create `schemas/mission_context_compaction.py` (`CompactionResult`)
- modify `services/summarization.py`
- modify `services/mission_context.py`
- create `temporal/run_memory_activities.py`
- modify `temporal/mission_run_models.py` (`CompactContextInput`, `CompactContextResult`)
- modify `temporal/worker.py`
- modify `events/mission_run_types.py` (exists since 88.1.6)
- modify `events/types.py` (`EVENT_TYPE_MAP`)

**Current state**
- Writes that would exceed the cap are rejected (`mission_context.py:324-330`).
- Pruning runs only from the admin CLI: `SummarizationService.run_full_pipeline` (`summarization.py:294`) has one caller, `modules/clients/cli/mission_cmds.py:401` (`python admin.py mission summarize MISSION_ID`).
- `prune_mcd_decisions` and `prune_completed_workstreams` (`summarization.py:55-182`) each call `apply_updates`. Calling them from inside `apply_updates` would recurse, and `summarization.py` imports `MissionContextManager`, so `mission_context.py` cannot import from `summarization.py` without an import cycle.
- `ChangeType.PRUNE` and `ARCHIVE` exist (`models/mission_context.py:25-26`) and are never written.
- `ContextMilestone` requires `mission_id`, `title`, `version_snapshot`, `context_snapshot` and `created_by` (`models/mission_context.py:80-111`).
- 88.1.6 moved `SessionEvent` to `events/base.py` and created `events/mission_run_types.py`, which imports it from there; `events/types.py` imports the run events back for `EVENT_TYPE_MAP`. New run events therefore go in `mission_run_types.py`, which keeps `events/types.py` below 1000 lines.

**Change**

1. **`services/mcd_pruning.py`** (pure functions plus two archive writers; imports repositories and `core` only, never another service). Next to `mcd_size_bytes` (88.3.2), add:

```python
def split_decisions_by_age(decisions: list[dict], cutoff_date: str) -> tuple[list[dict], list[dict]]:
    """Returns (keep, archive). A decision is archived when d.get("date", "") < cutoff_date (summarization.py:78-82)."""

def split_milestones(milestones: list[dict], keep_recent: int) -> tuple[list[dict], list[dict]]:
    """Returns (milestones[:keep_recent], milestones[keep_recent:]) (summarization.py:147-148)."""

async def archive_decision_rows(repo: MissionDecisionRepository, mission_id: str, decisions: list[dict]) -> None:
    """One MissionDecision row per decision, with the field mapping at summarization.py:88-97."""

async def archive_milestone_rows(repo: MilestoneSummaryRepository, mission_id: str, milestones: list[dict]) -> None:
    """One MilestoneSummary row for the batch, with the field mapping at summarization.py:151-159."""
```

2. **`summarization.py`.** `prune_mcd_decisions(mission_id)` and `prune_completed_workstreams(mission_id)` lose their `max_age_days` and `keep_recent` parameters (P3). They read `get_app_config().missions.compaction.decisions_max_age_days` and `.keep_recent_milestones` and delegate to the `mcd_pruning` functions. Their behaviour for `admin mission summarize` is otherwise unchanged.

3. **`MissionContextCompactor(BaseService)`** in `services/mission_context_compaction.py`. It imports `mcd_pruning` and repositories only. It plans and archives; it never writes the `mission_contexts` row.

```python
class MissionContextCompactor(BaseService):
    async def plan(self, mission_id: str, context_id: str, current_version: int,
                   data: dict, target_bytes: int) -> CompactionResult:
        """Mutate `data` in place until mcd_size_bytes(data) <= target_bytes or nothing archivable remains.
        Writes ContextMilestone, MissionDecision and MilestoneSummary rows in the caller's transaction."""
```

   `CompactionResult` (pydantic, `schemas/mission_context_compaction.py`) has `from_bytes: int` and `to_bytes: int` (`mcd_size_bytes(data)` before and after `plan`), `changes: list[dict]` (each `{change_type, path, old_value, new_value, reason}`), `archived_paths: list[str]` and `reached_target: bool`.

   The algorithm is deterministic and makes no LLM call. It checks the size after each sub-step and stops as soon as `mcd_size_bytes(data) <= target_bytes`:
   1. **Snapshot.** Insert a `ContextMilestone` with `mission_id`, `title=f"MCD compaction before v{current_version + 1}"`, `version_snapshot=current_version`, `context_snapshot=copy.deepcopy(data)` (the document as passed in, before anything is archived) and `created_by="system:compaction"`. Every compaction is therefore fully recoverable.
   2. **Decisions.** `split_decisions_by_age(data.get("decisions", []), cutoff)` with `cutoff = (utc_now() - timedelta(days=decisions_max_age_days)).isoformat()[:10]`. When the archive list is not empty: `archive_decision_rows`, set `data["decisions"] = keep`, and record `{change_type: ChangeType.PRUNE, path: "decisions", old_value: archive, new_value: keep, reason: "compaction: decisions older than N days"}`.
   3. **Milestones.** `split_milestones(data.get("current_state", {}).get("recent_milestones", []), keep_recent_milestones)`. When the archive list is not empty: `archive_milestone_rows`, set the kept list, and record `{PRUNE, "current_state.recent_milestones", old_value: archive, new_value: keep}`. This runs although `current_state` is a protected root, because only its milestone list is pruned.
   4. **Unprotected sections.**
      - **Candidates:** every root key of `data` not in `protected_roots` and not in `{"version", "last_updated", "last_updated_by"}`.
      - **Order:** ascending `latest_change_at_by_root(context_id).get(root, <MissionContext.created_at>)`, ties broken by key name.
      - **Action:** remove whole roots in that order. Each removal records `{ChangeType.ARCHIVE, root, old_value: <section>, new_value: None}` and appends `root` to `archived_paths`.
   5. Set `reached_target = mcd_size_bytes(data) <= target_bytes`.

4. **`MissionContextManager` write-path integration.** This replaces the rejection at `mission_context.py:324-330`. `apply_updates` calls the private method below after the ops are applied and before `update_context`; when it returns a tuple, `apply_updates` returns that tuple and writes nothing else.

```python
async def _compact_on_write(self, mission_id: str, ctx: MissionContext, current_version: int, data: dict,
                            updates: list[dict], applied_changes: list[dict]) -> tuple[int, list[str]] | None:
    cfg = get_app_config().missions
    if mcd_size_bytes(data) <= cfg.pcd_max_size_bytes:
        return None
    oversize = [u for u in updates if mcd_size_bytes(u.get("value")) > cfg.pcd_target_size_bytes]
    if oversize:  # a single update alone exceeds target: reject the whole batch, write nothing
        return current_version, [f"Update at {u['path']} exceeds pcd_target_size_bytes" for u in oversize]
    compaction = await MissionContextCompactor(self.session).plan(
        mission_id, ctx.id, current_version, data, cfg.pcd_target_size_bytes)
    if mcd_size_bytes(data) > cfg.pcd_max_size_bytes:
        self._logger.error("MCD protected sections exceed max after compaction",
                           extra={"mission_id": mission_id, "size_bytes": mcd_size_bytes(data)})
        return current_version, ["MCD protected sections exceed pcd_max_size_bytes after compaction"]
    applied_changes[:0] = compaction.changes  # one version bump; compaction rows first
    self._logger.info("MCD compacted on write",
                      extra={"mission_id": mission_id, "from_bytes": compaction.from_bytes,
                             "to_bytes": compaction.to_bytes, "archived_paths": compaction.archived_paths})
    return None
```

   On the early-return paths the snapshot and archive rows written by `plan` stay in the caller's transaction; the caller decides commit or rollback, as for every other `apply_updates` error. The manager never publishes events: the PRUNE and ARCHIVE `context_changes` rows are the record, and they reach the next run through `context_delta`.

   Add the explicit entry point used at run end:

```python
async def compact(self, mission_id: str, *, mission_run_id: str | None, reason: str) -> CompactionResult | None:
    """Lock the MCD row. If mcd_size_bytes(data) < pcd_max_size_bytes * pcd_prune_threshold_pct / 100,
    return None. Otherwise plan(target=pcd_target_size_bytes) on a deep copy, then write the document and
    one ContextChange per change (mission_run_id set, agent_id="system:compaction") under one version bump,
    using the same update-first order as apply_updates."""
```

5. **Event.** Add to `events/mission_run_types.py` (88.1.6), which imports `SessionEvent` from `events.base`:

```python
class ContextCompactedEvent(SessionEvent):
    event_type: str = "context.compacted"
    mission_id: str
    mission_run_id: str | None
    from_bytes: int
    to_bytes: int
    archived_paths: list[str]
```

   - `events/types.py` imports `ContextCompactedEvent` from `events.mission_run_types` alongside the 88.1.6 run events and adds `"context.compacted": ContextCompactedEvent` to `EVENT_TYPE_MAP`.
   - `session_id = mission_id`, per contract 3.6.1.

6. **Activity** in `temporal/run_memory_activities.py`. Add to `temporal/mission_run_models.py`:

```python
@dataclass
class CompactContextInput:
    mission_id: str
    mission_run_id: str


@dataclass
class CompactContextResult:
    compacted: bool
    from_bytes: int
    to_bytes: int
```

```python
@activity.defn
async def compact_mission_context(input: CompactContextInput) -> CompactContextResult:
    """Open get_async_session(); result = await MissionContextManager(db).compact(input.mission_id,
    mission_run_id=input.mission_run_id, reason="run-end compaction"); commit. After the commit, when
    result is not None, publish ContextCompactedEvent(session_id=uuid.UUID(input.mission_id),
    source="compaction", mission_id=input.mission_id, mission_run_id=input.mission_run_id,
    from_bytes=result.from_bytes, to_bytes=result.to_bytes, archived_paths=result.archived_paths)
    through SessionEventBus(redis, mission_id=input.mission_id), with the bus built the way the 88.1.8
    activities in temporal/mission_run_activities.py build it. Return
    CompactContextResult(compacted=result is not None, from_bytes=result.from_bytes if result else 0,
    to_bytes=result.to_bytes if result else 0). from_bytes and to_bytes are the CompactionResult values
    returned by MissionContextManager.compact: mcd_size_bytes(data) before and after compaction."""
```

   Its policy key is `persistence`. Register it in `worker.py`.

**Tests**

In `tests/unit/backend/services/test_mission_context_compaction.py` (real DB):
- `test_write_over_max_triggers_compaction_not_rejection`: seed an MCD at 19.5 KB with a `decisions` section older than 90 days, then apply a 1 KB add. The new version is written, and `context_changes` holds the PRUNE rows and the ADD at the same version.
- `test_compaction_snapshots_to_context_milestone`: exactly one `ContextMilestone` exists with `created_by == "system:compaction"`, and its `context_snapshot` equals the document passed to `plan`.
- `test_compaction_archives_oldest_unprotected_root_first`: two custom roots; the one changed least recently is removed first, and `archived_paths == [<that root>]`.
- `test_compaction_never_touches_protected_roots`.
- `test_single_update_larger_than_target_rejected`: the version is unchanged and the error names the path.
- `test_protected_sections_over_max_returns_error_without_write`.
- `test_compact_below_threshold_is_noop`: `compact()` returns `None` and the version is unchanged.
- `test_compaction_is_deterministic`: the same input document gives identical `CompactionResult.changes` twice.

In `tests/unit/backend/services/test_summarization.py`: update existing tests for the removed parameters.

In `tests/unit/backend/services/test_mcd_pruning.py`: `test_split_decisions_by_age_pure`, `test_split_milestones_pure`, `test_mcd_size_bytes_counts_utf8`.

In `tests/unit/backend/temporal/test_run_memory_activities.py` (`ActivityEnvironment`, real DB):
- `test_compact_mission_context_noop_under_threshold`: returns `compacted=False` and publishes nothing.
- `test_compact_mission_context_publishes_after_commit`: with a patched bus, `publish` is awaited once with a `ContextCompactedEvent`.

**Done when:** these tests pass. `grep -n "would exceed size cap" modules/backend/services/mission_context.py` returns nothing. `lint-imports` passes with no new `ignore_imports` entry. `python admin.py tree | grep "summarize MISSION_ID"` matches, and `wc -l modules/backend/events/types.py` is below 1000.

---

### 88.3.4 Fix learning occurrence-count inflation

**Files**
- modify `services/mission_learning.py`
- modify `repositories/mission_learning.py`
- modify `tests/integration/backend/services/test_mission_learning.py`

**Current state**
- `MissionLearningExtractor.extract_for_mission` re-reads every failed `TaskAttempt` of the mission on every sweep (`mission_learning.py:310-318`). For each group that matches an existing learning it calls `increment_occurrence` (`:370`), which adds `+1` unconditionally (`repositories/mission_learning.py:155`) even when the evidence is identical. The count therefore grows by one per daily sweep with no new failures.
- Groups are keyed `agent::tier` (`mission_learning.py:328`), but dedup looks up `agent + kind` (`:363-367`). Two tiers collapse into one learning, and a kind flip from `FAILURE_PATTERN` to `RETRY_STRATEGY` creates a duplicate.
- `confidence` and `title` are never recomputed on dedup, and the merge passes no `failure_tiers` (`:372-375`).
- `_check_success_after_failures` compares against the string literal `"completed"` (`:430`).
- `_load_learning_config` falls back silently (`:101-119`).
- The existing test `test_dedup_increments_occurrence` (`test_mission_learning.py:337`) asserts only that no new row is created.

**Change**

1. **Repository:** delete `find_by_agent_and_kind` (`:118-140`) and `increment_occurrence` (`:142-170`) (P3), and add:

```python
async def find_failure_learning(self, mission_id: str, agent_name: str,
                                failure_tier: str) -> MissionLearning | None:
    """status ACTIVE, kind IN (FAILURE_PATTERN, RETRY_STRATEGY), mission_id = :mid; then a Python
    post-filter for agent_name in agent_names and failure_tier in evidence["failure_tiers"]
    (as :138-140 does today); newest updated_at first; first match or None."""

async def merge_evidence(self, learning_id: str, new_evidence: dict, *, kind: str,
                         confidence_fn: Callable[[int], float],
                         title_fn: Callable[[int], str]) -> int:
    """Union task_attempt_ids, execution_ids, failure_tiers and artifact_ids with the order-preserving
    dedup at :161-166. occurrence_count = len(evidence["task_attempt_ids"]) (derived, so idempotent).
    Set confidence = confidence_fn(count), title = title_fn(count) and kind = kind. Set updated_at = utc_now()
    only when any of evidence, kind, confidence or title changed. Flush; return occurrence_count."""
```

2. **Extractor:**
   - The query adds `TaskAttempt.created_at >= utc_now() - timedelta(days=extraction_window_days)`. Older evidence is kept by the union.
   - Dedup calls `find_failure_learning(mission_id, agent_name, failure_tier)`, then `merge_evidence(existing.id, {"task_attempt_ids": attempt_ids, "execution_ids": execution_ids, "failure_tiers": [failure_tier]}, kind=kind, confidence_fn=self._compute_confidence, title_fn=<the title format at mission_learning.py:357 with the count substituted>)`.
   - `_check_success_after_failures` compares against `TaskExecutionStatus.COMPLETED`.
   - `extract_for_mission(self, mission_id: str) -> list[MissionLearning]` keeps its signature and still returns only newly created learnings.

3. **Config:** `_load_learning_config` loses its `try/except` fallback and reads `get_app_config().missions.knowledge.learnings` directly, adding `extraction_window_days`.

**Tests**: `tests/integration/backend/services/test_mission_learning.py`
- Replace `test_dedup_increments_occurrence` with `test_repeat_extraction_does_not_inflate_count`: extract twice over the same data; `occurrence_count`, `confidence` and `updated_at` are identical after both.
- `test_new_failure_increments_count_by_exactly_one`: add one failed attempt between sweeps, and the count rises by 1.
- `test_kind_flip_updates_existing_learning`: add a COMPLETED execution for the agent and re-extract. The same learning id now has `kind == "retry_strategy"`, and no second row exists.
- `test_two_tiers_produce_two_learnings`.
- `test_window_excludes_old_attempts_from_creation`: attempts older than `extraction_window_days` create no learning.

**Done when:** these tests pass, and `grep -rn --exclude-dir=migrations "increment_occurrence\|find_by_agent_and_kind" modules tests` returns nothing.

---

### 88.3.5 Run context packet: delta, previous digest, learnings, bounded prior outputs

**Files**
- create `services/run_memory.py` (context-packet half; 88.3.7 adds the digest half)
- create `schemas/run_memory.py`
- modify `services/context_assembler.py`
- modify `agents/mission_control/models.py` (`ContextAssemblerProtocol`)
- modify `agents/mission_control/runtime.py` (`DispatchRuntime`, `build_dispatch_runtime`; exist since 88.2.3)
- modify `agents/mission_control/dispatch/task_runner.py` (`_inject_context`; moved there by 88.2.3)
- modify `services/mission_plan_taskio.py`
- modify `repositories/task.py`
- modify `services/mission_run.py` (`plan`, exists since 88.1.7)

**Current state**
- **Learnings dropped.** `ContextAssembler.build` (`context_assembler.py:98-193`) puts `learnings` into the packet (`:160-171`), only when `domain_tags` is set. `_inject_context` (`loop.py:762-794` at baseline, in `dispatch/task_runner.py` since 88.2.3) copies only `project_context`, `code_map` and `history` (as `project_history`), so learnings are dropped.
- **Learnings budget ignored.** `_assemble_learnings` (`:223-276`) ignores `remaining_budget` and `context_assembler_reserve_tokens`. It reaches into `self._context_manager._context_repo.session` (`:233`) and swallows every exception (`:274-276`).
- **Magic thresholds.** `> 300` (`:161`) and `> 500` (`:174`) gate the learnings and history layers.
- **Prior outputs unbounded.** `load_prior_outputs(orchestrator, mission_plan_id)` (`mission_plan_taskio.py:123-148`) loads every COMPLETED task of the plan, with no run bound.
- **Run id at dispatch.** `build_dispatch_runtime` takes `mission_run_id` (88.2.3) but `DispatchRuntime` does not carry it. `handle_mission` (its legacy positional renamed `execution_label` in 88.1.7) passes `mission_run_id=None`, because its in-process callers hold no `MissionRun` id; `execute_plan_task` (88.2.4) passes the real one.

**Change**

1. **Run id on the runtime.** `DispatchRuntime` gains the field `mission_run_id: str | None`, set by `build_dispatch_runtime` from its existing parameter. `handle_mission` is unchanged and keeps passing `mission_run_id=None`. `run_single_task` passes `mission_run_id=runtime.mission_run_id` to `_inject_context`, which gains a keyword-only `mission_run_id: str | None`.

2. **Schemas** (`schemas/run_memory.py`, pydantic):

```python
class PreviousRunDigest(BaseModel):
    mission_run_id: str
    sequence: int
    status: str            # MissionRunStatus value
    generator: str         # DigestGenerator value
    summary: str           # truncated to previous_digest_max_chars
    open_items: list[dict]
    metrics: dict


class ContextDeltaEntry(BaseModel):
    version: int
    change_type: str       # ChangeType value
    path: str
    value_excerpt: str | None
    reason: str


class ContextDelta(BaseModel):
    from_version: int
    to_version: int
    entries: list[ContextDeltaEntry]
    omitted_count: int


class RunContextPacket(BaseModel):
    mission_run_id: str
    is_first_run: bool
    previous_run_digest: PreviousRunDigest | None
    context_delta: ContextDelta | None
```

3. **`RunMemoryService(BaseService).build_context_packet(run_id) -> RunContextPacket`:**
   - Load the run, then `prev` from `run.previous_run_id`.
   - If `prev is None`, or `prev.context_version_start is None`, or `run.context_version_start is None`, return `is_first_run=True` with both layers `None`.
   - **Digest:** `MissionRunDigestRepository.get_by_run(prev.id)`, mapped to `PreviousRunDigest` with `summary[:previous_digest_max_chars]`.
   - **Delta:** `MissionContextManager.get_changes_between(run.mission_id, prev.context_version_start, run.context_version_start, limit=context_delta_max_changes)`.
     - Render each change as `value_excerpt = json.dumps(new_value, ensure_ascii=False)[:context_delta_value_max_chars]` (`None` for REMOVE and ARCHIVE) and `reason[:context_delta_value_max_chars]`.
     - Drop the oldest entries until `estimate_tokens(delta.model_dump(mode="json")) <= context_delta_max_tokens`.
     - `omitted_count = count_changes_between(...) - len(entries)`.

4. **Planning brief.** Add `RunMemoryService.render_planning_brief(packet: RunContextPacket) -> str`. It renders deterministic markdown:
   - `## Previous run (#{sequence}, {status}, digest: {generator})`, then the summary;
   - `### Open items`, one bullet per item `text`;
   - `## Mission context changes since previous run (v{from_version}→v{to_version})`, one bullet per entry `v{version} {change_type} {path}`, then `({omitted_count} older changes omitted)` when `omitted_count > 0`.

   It returns `""` when `is_first_run`.

5. **`ContextAssembler` rewrite (P3):**
   - Delete `_get_dispatch_config` and `_get_learnings_config` with their `try/except` fallbacks (`:31-42`, `:49-60`), and delete `DEFAULT_TOKEN_BUDGET` (`:46`). Read `get_mission_control_config().dispatch` and `get_app_config().missions` directly; a missing key raises.
   - The constructor gains keyword-only `learning_repo: MissionLearningRepository` and `run_memory: RunMemoryService`. This removes the private `_context_repo.session` access.
   - New signature:

```python
async def build(self, mission_id: str, task_definition: dict, resolved_inputs: dict, *,
                domain_tags: list[str] | None, mission_run_id: str | None) -> dict:
    """Fixed head plus the optional layers below, in assembly_order."""
```

   - **Budget.** `remaining = get_mission_control_config().dispatch.context_token_budget`. `token_budget` and `code_map_max_tokens` are deleted from the method and from `ContextAssemblerProtocol.build`.
   - **Fixed head, never trimmed:** `project_context`, `task`, `inputs` (summarised exactly as `:132-147`).
   - **Optional layers.** Iterate `missions.context_packet.assembly_order`. A layer is included only when its rendered `estimate_tokens(value) <= min(layer_cap, remaining)`; a layer that does not fit is omitted whole. Each included layer subtracts its tokens from `remaining`.

     | Layer | Cap (tokens) | Source |
     |---|---|---|
     | `previous_run_digest` | `previous_digest_max_chars // 4` | `packet.previous_run_digest.model_dump(mode="json")`. The packet is built once per `mission_run_id` and cached on the instance in `self._packets: dict[str, RunContextPacket]`. Skipped when `mission_run_id is None` or the layer is `None` |
     | `context_delta` | `context_delta_max_tokens` | `packet.context_delta.model_dump(mode="json")`; same skip rule |
     | `code_map` | `remaining` minus the sum of the caps of every layer after `code_map` in `assembly_order` | existing `_load_code_map_markdown(cap)` (`:205-221`), only when `_is_coding_task(domain_tags)` |
     | `learnings` | `knowledge.learnings.context_assembler_reserve_tokens` | `learning_repo.list_by_mission(mission_id, domain_tags=domain_tags, limit=max_entries)`, plus `list_platform_promoted(domain_tags=domain_tags, limit=max_entries)` only when `domain_tags` is set; merged, deduped by id and sorted by confidence descending as at `:251-271`. Entries are appended while cumulative tokens stay within the cap, up to `context_assembler_max_entries` |
     | `history` | `dispatch.history_reserve_tokens` | existing `_assemble_history(mission_id, domain_tags, cap)` (`:278-311`), only when `domain_tags` is set |

   - Delete the magic thresholds at `:161` and `:174` and the blanket `except Exception` at `:274`. Repository errors propagate to `_inject_context`.

6. **`_inject_context`** (`dispatch/task_runner.py`) calls `context_assembler.build(..., domain_tags=task.domain_tags or None, mission_run_id=mission_run_id)` and maps every assembled key:

```python
_PACKET_TO_INPUT = {
    "project_context": "project_context",
    "code_map": "code_map",
    "history": "project_history",
    "learnings": "learnings",
    "previous_run_digest": "previous_run_digest",
    "context_delta": "context_delta",
}
for key, input_key in _PACKET_TO_INPUT.items():
    if key in assembled:
        resolved_inputs[input_key] = assembled[key]
```

   Its `except` tuple becomes `(OSError, ValueError, RuntimeError, SQLAlchemyError)`; the logged fallback to the raw PCD is unchanged.

7. **Construction.** The `ContextAssembler(...)` call inside `build_dispatch_runtime` (moved there from `mission_dispatch.py:134-138` by 88.2.3) becomes `ContextAssembler(context_manager=pcd_manager, history_service=history_service, learning_repo=MissionLearningRepository(db_session), run_memory=RunMemoryService(db_session), code_map_loader=code_map_loader)`.

8. **Prior outputs bounded to the run (P3).** New signature:

```python
async def load_prior_outputs(orchestrator: MissionPlanOrchestrator, mission_run_id: str) -> dict[str, dict]:
    tasks = await orchestrator._task_repo.list_by_run(mission_run_id, status=TaskStatus.COMPLETED)
```

   Parsing is unchanged (`:140-148`). Update every caller found with `grep -rn "load_prior_outputs(" modules`; each passes the run id it already holds.

9. **Run-local dependencies.**
   - Add `TaskRepository.list_unfinished_foreign_dependencies(mission_run_id: str) -> list[tuple[str, str]]`. It returns `(task_id, depends_on_id)` for every `task_dependencies` edge whose `task_id` belongs to the run and whose `depends_on_id` task has `mission_run_id IS DISTINCT FROM :run` and a status not in `(COMPLETED, SKIPPED)`. Dependencies on finished tasks of earlier runs stay legal, because `load_dependency_outputs` (88.2.3) reads their outputs.
   - Add `async def assert_run_local_dependencies(task_repo: TaskRepository, mission_run_id: str) -> None` to `mission_plan_taskio.py`. It raises `ValidationError(f"Task {t} depends on unfinished task {d} outside run {mission_run_id}")` for the first edge returned.
   - `MissionRunService.plan` calls it after materialising tasks. A `ValidationError` returns `PlanRunResult(status="failed", detail=str(e))` through the existing error path, so the workflow calls `_end_run("failed", "planning_failed", detail)`.

10. **Planning prompt.** For objective runs, `MissionRunService.plan` builds the planner input as `brief = run_memory.render_planning_brief(await run_memory.build_context_packet(run_id))`, then `prompt = brief + "\n\n## Objective\n" + run.objective if brief else run.objective`, and passes `prompt` to `orchestrator.refine` in place of `run.objective`. The digest is **not** a template placeholder: contract 3.1.5 allows only `{scheduled_for}`, `{sequence}` and `{mission_name}`, and template rendering stays at claim time. A backlog run (`objective IS NULL`) makes no planning call, as in 88.1.7.

**Tests**

In `tests/unit/backend/services/test_context_assembler.py` (rewrite fixtures for the new constructor):
- `test_learnings_respect_reserve_tokens`: 10 learnings of about 400 tokens each with a reserve of 1500 give 3 entries.
- `test_learnings_without_domain_tags_uses_mission_learnings`: platform-promoted learnings are not queried.
- `test_assembly_order_followed`: with order `["history", "code_map", "previous_run_digest", "context_delta", "learnings"]`, history is included before the code map is sized.
- `test_code_map_reserves_later_layer_caps`.
- `test_run_layers_skipped_without_run_id`.
- `test_run_layers_built_once_per_run`: `run_memory.build_context_packet` is awaited once for two `build` calls with the same run id.
- `test_no_fallback_when_config_missing`: patch `get_mission_control_config` to raise `KeyError`; `build` raises `KeyError`.

In `tests/unit/backend/mission_control/test_task_runner.py` (exists since 88.2.3):
- `test_inject_context_maps_learnings_digest_and_delta`: `resolved_inputs` contains `learnings`, `previous_run_digest`, `context_delta` and `project_history`.
- `test_inject_context_passes_runtime_run_id`.

In `tests/unit/backend/services/test_run_memory_packet.py` (real DB):
- `test_first_run_has_no_digest_or_delta`.
- `test_delta_is_changes_between_previous_and_current_watermark`: run 1 starts at v3, the MCD is written to v7, run 2 starts at v7, so the delta covers versions 4 to 7.
- `test_delta_excludes_changes_after_current_start`.
- `test_delta_truncation_reports_omitted_count`.
- `test_planning_brief_empty_for_first_run`.
- `test_planning_brief_contains_previous_summary_and_open_items`.

In `tests/unit/backend/services/test_mission_plan_taskio.py`:
- `test_load_prior_outputs_only_current_run`: completed tasks exist in runs 1 and 2; loading for run 2 returns only run 2's tasks.
- `test_dependency_on_unfinished_task_of_other_run_rejected`.
- `test_dependency_on_completed_task_of_earlier_run_allowed`.

**Done when:** these tests pass. `grep -n '"learnings"' modules/backend/agents/mission_control/dispatch/task_runner.py` matches. `grep -n "50_000\|except Exception\|DEFAULT_TOKEN_BUDGET" modules/backend/services/context_assembler.py` returns nothing. `lint-imports` passes with no new `ignore_imports` entry.

---

### 88.3.6 Digest agent in the catalog

**Files**
- create `config/agents/mission/digest/agent.yaml`
- create `config/prompts/agents/mission/digest/system.md`
- create `agents/mission/digest/__init__.py` (docstring only) and `agents/mission/digest/agent.py`
- modify `schemas/run_memory.py` (`DigestNarrative`)
- modify `temporal/worker.py` (startup check)

**Current state:** no digest agent exists.
- The nearest pattern is `agents/system/summarization/agent.py:51-59` (`create_agent` with `_build_model`, `assemble_instructions` and a pydantic `output_type`), and `config/agents/system/summarization/agent.yaml`.
- Cost is recorded through `record_llm_call` (`helpers/cost_recorder.py:46`) with `extract_usage` and `compute_cost_usd` (`agents/mission_control/cost.py:13`), as `helpers/agent_executor.py:320-345` does.
- The import-linter contract "Services layer must not import from agents layer" (`pyproject.toml:172-200`) forbids `services/run_memory.py` from importing this agent. The agent is therefore called from the activity layer (88.3.7), and its output type lives in `schemas/`.

**Change**

1. **`agent.yaml`.** `produces_artifact` is false, because the digest's single store is `mission_run_digests`; an artifact copy would duplicate it and drift. The model is the `quick` alias (contract 3.7 item 3), which `core/model_builder.py:136-150` resolves.

```yaml
agent_name: mission.digest.agent
agent_type: horizontal
description: "Writes the end-of-run narrative digest (summary, open items, task headlines) from deterministic run facts."
enabled: true
chat_enabled: false
version: "1.0.0"
model:
  name: "quick"
  temperature: 0.0
  max_tokens: 2000
keywords: [digest, summary, run]
tools: []
max_input_length: 32000
max_budget_usd: 0.05
produces_artifact: false
execution:
  mode: local
invocation:
  tier: system
scope:
  read: []
  write: []
interface:
  input:
    draft: object
    objective: string
    task_excerpts: list
  output:
    summary: string
    open_items: list
    headlines: list
```

2. **Output type** in `schemas/run_memory.py`. It has one `$defs` level, well under P17's threshold of more than 5.

```python
class DigestOpenItemOut(BaseModel):
    text: str
    source_task_id: str | None


class DigestHeadlineOut(BaseModel):
    task_id: str
    headline: str


class DigestNarrative(BaseModel):
    summary: str
    open_items: list[DigestOpenItemOut]
    headlines: list[DigestHeadlineOut]
```

3. **`agent.py`:**

```python
async def generate_digest_narrative(*, draft: dict, objective: str | None, task_excerpts: list[dict],
                                    mission_id: str, mission_run_id: str,
                                    session_id: str) -> tuple[DigestNarrative, float]:
    """Run the digest agent once; return its output and the recorded cost in USD."""
```

   - Build `Agent(_build_model(get_registry().get("mission.digest.agent").model), instructions=assemble_instructions("mission", "digest"), output_type=DigestNarrative, output_retries=cfg.digest.agent_output_retries)`, with `cfg = get_app_config().missions`.
   - Add an `@agent.output_validator` that raises `ModelRetry` when `len(summary) > cfg.digest.summary_max_chars`, when any `source_task_id` (not None) or `headline.task_id` is not in `{e["task_id"] for e in task_excerpts}`, or when any headline is longer than `cfg.digest.headline_max_chars`.
   - After the run, compute the cost with `extract_usage` and `compute_cost_usd` as `agent_executor.py:320-330` does, then await `record_llm_call(session_id=session_id, mission_id=mission_id, agent_name="mission.digest.agent", agent_role="horizontal", model=<resolved model name>, usage=result.usage(), cost_usd=cost, mission_run_id=mission_run_id, task_id=None)`.
   - Catch `UnexpectedModelBehavior`, `ModelHTTPError`, `UsageLimitExceeded` (all from `pydantic_ai.exceptions`) and `ProviderError` (`core/exceptions.py:110`), and raise `ExternalServiceError(f"digest agent failed: {type(e).__name__}") from e`. Nothing else is caught.
   - Return `(result.output, cost)`.

4. **`system.md`.** The prompt instructs the agent to:
   - use only facts in the draft and excerpts;
   - write the summary as findings first, then changes to mission context, then what is still open;
   - never restate cost or metrics, because those are deterministic;
   - write open items as actionable single sentences;
   - cite only the task ids given in the excerpts.

5. **Worker startup check.** In `temporal/worker.py` `start_worker()`, before `Worker(...)` is constructed, load `get_app_config().missions.digest.agent_name` with `AgentCatalogService.get_by_name` inside `AgentCatalogService.factory()`. The `NotFoundError` it raises for a missing row propagates, and the worker does not start. Contract 3.4.6 assigns this check to worker startup.

6. **Seeding.** Run `python admin.py admin seed-catalog` without `--force`; it inserts the missing row and leaves existing rows untouched.

**Tests**: `tests/unit/backend/agents/test_digest_agent.py`, using pydantic-ai `TestModel` and `FunctionModel`
- `test_output_validator_rejects_unknown_task_id`.
- `test_output_validator_rejects_long_summary`.
- `test_records_llm_call_with_run_id`: patch `record_llm_call` and assert `mission_run_id`, `task_id=None` and `agent_name`.
- `test_model_failure_raises_external_service_error`: a `FunctionModel` that raises `ModelHTTPError` gives `ExternalServiceError`.
- `test_catalog_yaml_valid`: load the yaml through `AgentConfigSchema` (`schemas/agent_config.py:134`); `agent_name == "mission.digest.agent"` and `produces_artifact is False`.

In `tests/unit/backend/temporal/test_worker_startup.py`:
- `test_worker_refuses_start_without_digest_agent`: with `get_by_name` raising `NotFoundError`, `start_worker()` raises before `Worker` is constructed.

**Done when:** these tests pass, and after seeding `curl -s localhost:$PORT/api/v1/catalog/agents/mission.digest.agent` returns `ApiResponse` with `data.agent_name == "mission.digest.agent"`.

---

### 88.3.7 Digest service and `write_run_digest` activity

**Files**
- modify `services/run_memory.py` (digest half)
- modify `schemas/run_memory.py` (`DigestDraft`, `DigestNarrator`)
- modify `temporal/run_memory_activities.py`
- modify `temporal/mission_run_models.py` (`WriteDigestInput`, `DigestResult`)
- modify `events/mission_run_types.py` and `events/types.py` (`MissionRunDigestWrittenEvent`)
- modify `services/mission_run.py` (`finalise`, exists since 88.1.7)
- modify `temporal/worker.py`

**Current state:** no digest is written. Run end ordering is fixed by contract 3.2.1: `write_run_digest`, then `finalise_mission_run`. `MissionRunService.finalise` sets `context_version_end` from the current MCD version (88.1.7). Artifacts link through `mission_artifacts.task_execution_id` (`models/mission_artifact.py:116-118`), and task executions carry `mission_run_id` and `task_id` from 88.2.4.

**Change**

1. **DTOs** in `temporal/mission_run_models.py`:

```python
@dataclass
class WriteDigestInput:
    mission_run_id: str
    status: str               # intended terminal status, lowercase MissionRunStatus value (3.0.2)
    reason: str | None        # lowercase MissionRunStatusReason value, as FinaliseRunInput.reason
    force_deterministic: bool


@dataclass
class DigestResult:
    digest_id: str
    generator: str            # DigestGenerator value
```

2. **Narrator seam** in `schemas/run_memory.py`. The service receives the agent as a callable, so `services/` never imports `agents/`:

```python
class DigestNarrator(Protocol):
    async def __call__(self, *, draft: dict, objective: str | None, task_excerpts: list[dict],
                       mission_id: str, mission_run_id: str,
                       session_id: str) -> tuple[DigestNarrative, float]: ...
```

3. **Write path.** `RunMemoryService(session, *, event_bus: EventBusProtocol | None = None)` gains:

```python
async def write_digest(self, run_id: str, *, status: MissionRunStatus, reason: MissionRunStatusReason | None,
                       narrator: DigestNarrator | None) -> MissionRunDigest:
    """Steps 1 to 8 below."""
```

   It works in this order:
   1. **Idempotent replay.** If `MissionRunDigestRepository.get_by_run(run_id)` returns a row, return it. No LLM call is made.
   2. **State check.** Load the run without a lock. It must be `RUNNING`, `AWAITING_GATE` or `PAUSED`; otherwise raise `MissionRunStateError`.
   3. **Watermark end.** `end = MissionContextRepository.get_version(run.mission_id)`.
   4. **Deterministic draft** (`DigestDraft`, pydantic, in `schemas/run_memory.py`; every list ordered by `tasks.created_at`):
      - **outcomes:** at most `max_outcomes` of `{task_id, agent, status, headline, artifact_ids}` for the run's tasks.
        - `status` is the `TaskStatus` value (lowercase, per the wire-format convention, because the digest is returned by the API).
        - `headline`: for FAILED tasks, `failure_reason`. Otherwise parse `result_summary` as JSON and take the key `summary`, then `result`, then the raw text. Cut to `headline_max_chars`.
        - `artifact_ids`: `mission_artifacts.id` joined through `task_executions` where `task_executions.mission_run_id = :run AND task_executions.task_id = :task`.
      - **decisions:** `[]`. Gate decisions are added by 88.4.8, which owns the durable `gate_requests` columns (`plan88_006`).
      - **open_items:** one item per FAILED task (`f"{agent} failed: {failure_reason}"`) and one per task of the run still `PROPOSED` or `APPROVED` (`f"Not executed: {description}"`), each with `source_task_id` and cut to `headline_max_chars`.
      - **context_changes:** `get_changes_between(run.mission_id, run.context_version_start, end, limit=context_delta_max_changes)` as `{version, change_type, path}`, with `change_type` as the `ChangeType` value.
      - **metrics:** `cost_usd` from `LlmLedgerRepository.sum_cost`, the ledger query `MissionRunService.finalise` uses for `mission_runs.cost_usd` (88.1.7; do not write a second query), `duration_seconds = (utc_now() - run.started_at).total_seconds()`, the run's task counts from `list_by_run`, and `iteration_count`. `cost_usd` excludes the digest's own generation, which `finalise` later includes.
      - **summary:** `f"Run #{run.sequence} ended {status.value} ({reason.value if reason else 'none'}). {completed}/{total} tasks completed, {failed} failed. Spend ${cost:.2f}."`, followed by `f" Objective: {run.objective}"` when present, truncated to `summary_max_chars`.
   5. **End the read transaction.** `await self._session.commit()`. No row lock is held across the agent call.
   6. **Generator choice.** `generator = DigestGenerator.AGENT` only when `narrator is not None`; otherwise `DETERMINISTIC` with `generation_cost_usd = 0`. Phase 4 (88.4.6) adds the budget conditions (breach, or headroom below the agent's `max_budget_usd`) in the activity, where it decides whether to pass a narrator.
      - **Agent call:** `narrative, cost = await narrator(draft=draft.model_dump(mode="json"), objective=run.objective, task_excerpts=[{task_id, agent, status, excerpt: (result_summary or failure_reason or "")[:task_excerpt_max_chars]}], mission_id=run.mission_id, mission_run_id=run_id, session_id=run.session_id)`.
      - **Merge:** `summary` is replaced by `narrative.summary`; `open_items` becomes the deterministic items followed by the narrative items, deduplicated on `text`; each narrative headline replaces the outcome headline with the same `task_id`. `generation_cost_usd = cost`.
      - **Degraded path:** on `ExternalServiceError`, log a warning with `exc_info=True` and use `DETERMINISTIC` with `generation_cost_usd = 0`. Spend already recorded by the agent stays in `llm_calls`. This is the defined degraded path in contract 3.1.7, not a silent fallback.
   7. **Insert.** Lock the run (`SELECT ... FOR UPDATE`) and repeat the state check. Insert `mission_run_digests` with `schema_version=1` using `INSERT ... ON CONFLICT (mission_run_id) DO NOTHING RETURNING *`. When no row is returned, re-read and return the existing row. Set `run.context_version_end = end`; this step owns the column. Commit.
   8. **Event.** After commit, when `self._event_bus` is set, publish `MissionRunDigestWrittenEvent(session_id=run.session_id, mission_id=run.mission_id, mission_run_id=run_id, digest_id=digest.id, generator=digest.generator.value, source="run_memory")`.

4. **`finalise` delta** (88.1.7). `MissionRunService.finalise` sets `context_version_end` only when it is NULL, so a run without a digest (cancelled before RUNNING) still gets one and a digest's watermark is never overwritten.

5. **Digest read.** Add `RunMemoryService.get_digest(mission_id: str, run_id: str) -> MissionRunDigest | None`. It loads `WHERE mission_run_id = :run AND mission_id = :mid` and returns `None` when no row matches. Callers load the run through `MissionRunService.get_run(mission_id, ...)` first, which raises `NotFoundError` for another mission's run.

6. **Event** in `events/mission_run_types.py`, registered in `EVENT_TYPE_MAP` under `"mission_run.digest_written"`:

```python
class MissionRunDigestWrittenEvent(SessionEvent):
    event_type: str = "mission_run.digest_written"
    mission_id: str
    mission_run_id: str
    digest_id: str
    generator: str
```

7. **Activity** in `temporal/run_memory_activities.py`, registered in `worker.py`:

```python
@activity.defn
async def write_run_digest(input: WriteDigestInput) -> DigestResult:
    """Inside the 88.1.8 heartbeat_every helper, used exactly as plan_mission_run uses it:
    1. Open get_async_session() and a SessionEventBus built as in compact_mission_context.
    2. narrator = None if input.force_deterministic else generate_digest_narrative.
    3. digest = await RunMemoryService(db, event_bus=bus).write_digest(input.mission_run_id,
           status=MissionRunStatus(input.status),
           reason=MissionRunStatusReason(input.reason) if input.reason is not None else None,
           narrator=narrator).
    4. In a fresh session: await MissionLearningExtractor(db).extract_for_mission(digest.mission_id); commit.
       On SQLAlchemyError: logger.warning("learning extraction failed",
       extra={"mission_id": digest.mission_id}, exc_info=True). The knowledge_extraction system schedule
       (extract_all_missions, knowledge_activities.py:157-180) repeats the extraction nightly, and 88.3.4
       makes it idempotent.
    5. Return DigestResult(digest_id=digest.id, generator=digest.generator.value)."""
```

   Its policy key is `write_digest` (`heartbeat_timeout_seconds: 60`). The import of `generate_digest_narrative` from `agents/mission/digest/agent.py` is in the activity module, so the services import contract holds.

**Tests**

In `tests/unit/backend/services/test_run_memory_digest.py` (real DB, narrator is an `AsyncMock`):
- `test_digest_written_once_and_replay_returns_same_row`: the narrator is awaited once across two calls.
- `test_no_narrator_makes_no_llm_call`: generator is `DETERMINISTIC`.
- `test_narrator_failure_falls_back_to_deterministic`: the narrator raises `ExternalServiceError`.
- `test_narrative_merged_into_draft`: summary replaced, open items deduplicated on `text`, headline overridden for a known task.
- `test_digest_context_changes_are_run_window`: with changes at v3..v6, start 3 and end 6, the versions are 4, 5 and 6.
- `test_sets_context_version_end`.
- `test_outcomes_capped_at_max_outcomes`.
- `test_outcome_status_is_lowercase_value`.
- `test_open_items_include_failed_and_unexecuted_tasks`.
- `test_decisions_empty_in_phase_3`.
- `test_digest_rejected_for_pending_run`: raises `MissionRunStateError`.
- `test_artifact_ids_linked_via_task_execution`.
- `test_no_row_lock_held_during_narrator_call`: inside the narrator, a second session runs `SELECT ... FROM mission_runs WHERE id = :run FOR UPDATE NOWAIT` without error.
- `test_get_digest_other_mission_returns_none`.

In `tests/integration/backend/services/test_mission_run_service.py`:
- `test_finalise_keeps_digest_context_version_end`.

In `tests/unit/backend/temporal/test_run_memory_activities.py`:
- `test_write_run_digest_activity_returns_generator`.
- `test_force_deterministic_passes_no_narrator`.
- `test_learning_extraction_failure_does_not_fail_digest`.

**Done when:** these tests pass, `lint-imports` passes with no new `ignore_imports` entry, and in the 88.3.8 workflow test the `mission_run_digests` row count equals the number of runs that reached RUNNING.

---

### 88.3.8 Workflow wiring, notification payload and read surfaces

**Files**
- modify `temporal/mission_run_workflow.py`
- modify `temporal/versioning.py` (`PATCH_IDS`)
- modify `tests/unit/backend/temporal/test_replay_histories.py` (`REQUIRED`)
- create `tests/fixtures/temporal_histories/mission_run/p88-run-memory.json`
- modify `services/mission_run.py` (`finalise`, which builds the run-end `NotificationRequest` that `finalise_mission_run` returns; 88.1.7)
- modify `api/v1/endpoints/missions_runs.py` (exists since 88.1.12) and `MissionRunDigestResponse` in `schemas/mission_run.py` (exists since 88.1.7)
- modify `modules/clients/cli/mc_mission_runs.py` (the `mc runs digest` renderer, exists since 88.1.13)
- create `tests/unit/backend/temporal/test_mission_run_memory_workflow.py`
- create `tests/integration/backend/api/test_mission_runs_digest.py`

**Current state:** 88.1.8 defines `_end_run(status, reason, detail)`, which sets the phase to `"finalising"` and runs `finalise_mission_run`. Phase 2 drained all Phase 1 executions and shipped without patches (88.2.8 rule 4, 88.2.10), so every open execution at Phase 3 deploy has Phase 2 history. The seven fixtures recorded in 88.2.9 from Phase 2 code (`two_layer_success`, `wait_then_signal`, `can_first_run`, `can_carried_state_run`, `verification_failed_continue`, `cancelled_mid_layer`, `max_duration_stop`) are the pre-patch histories for this change; do not re-record them.

**Change**

1. **Run-end sequence.** `_end_run` becomes the following. `self._state` is assigned only after `begin_mission_run` returns or from `inp.state`, so `self._state is not None` means the run reached RUNNING.

```python
async def _end_run(self, status: str, reason: str | None, detail: str | None) -> str:
    self._phase = "finalising"
    inp = self._input
    c = inp.config
    if self._state is not None and workflow.patched("p88-run-memory"):
        try:
            await _exec(compact_mission_context,
                        CompactContextInput(mission_id=inp.mission_id, mission_run_id=inp.mission_run_id),
                        c.persistence)
        except ActivityError:
            workflow.logger.warning("run-end compaction failed; digest continues",
                                    extra={"mission_run_id": inp.mission_run_id})
        await _exec(write_run_digest,
                    WriteDigestInput(mission_run_id=inp.mission_run_id, status=status, reason=reason,
                                     force_deterministic=status in ("budget_stopped", "cancelled")),
                    c.write_digest)
    await _exec(finalise_mission_run, FinaliseRunInput(inp.mission_run_id, status, reason, detail), c.persistence)
    return status
```

   - `status` and `reason` are the lowercase enum values `_end_run` already receives from its callers (88.1.8, 88.2.6; contract 3.0.2).
   - Import `compact_mission_context`, `write_run_digest`, `CompactContextInput` and `WriteDigestInput` the same way the module imports the Phase 1 activities.
   - Compaction runs before the digest, so its PRUNE and ARCHIVE changes fall inside the digest's `(start, end]` window. A compaction failure is logged and does not block the digest; the next write over the cap compacts again.
   - The cancellation handler calls the same `_end_run`, so a cancelled run gets a deterministic digest.
   - The `"budget_stopped"` member of the tuple has no Phase 3 caller; Phase 4 (88.4.6) produces that status and relies on it.

2. **Patch registration** (contracts 3.0.2 convention):
   - Add `"p88-run-memory"` to `temporal/versioning.PATCH_IDS`.
   - Record the patched-branch history from Phase 3 code on the dev stack: start a fixture mission run (objective "replay fixture", `gate_mode=AUTONOMOUS`), let it reach `SUCCEEDED`, then run `python scripts/record_workflow_history.py record --workflow-id "mission-run-$RUN_ID" --name p88-run-memory`. Commit `tests/fixtures/temporal_histories/mission_run/p88-run-memory.json`.
   - Add `"p88-run-memory"` to `REQUIRED` in `test_replay_histories.py`.

3. **Notification payload.** Where `MissionRunService.finalise` (88.1.7) builds the run-end `NotificationRequest` that `finalise_mission_run` returns, for kinds `run_succeeded` and `run_failed`, add to its `payload` `digest_generator` (the `DigestGenerator` value, or `None` when no digest exists) and `digest_summary` (the digest summary, already at most `summary_max_chars`, or `None`), read through `RunMemoryService.get_digest(mission_id, run_id)`. Contract 3.1.7 requires the run-finished notification to state the generator. Phase 3 still only builds and logs the request; it is sent from 88.4.5 under patch id `p88-lifecycle-signals`. Message truncation to `notifications.message_max_chars` belongs to Phase 4 (88.4.4).

4. **API.** In `missions_runs.py`, the `GET /missions/{id}/runs/{run_id_or_seq}` handler sets `digest` from `RunMemoryService.get_digest(mission_id, run.id)` (`null` when it returns `None`), replacing whatever source 88.1.12 used, inside `ApiResponse`. `MissionRunDigestResponse` carries every 3.1.7 column plus `id` and `created_at`, with `generator` and every nested status as lowercase values. Each outcome includes `artifact_ids`.

5. **CLI.** `mc runs digest SEQ` (88.1.13) keeps its call to the run-detail endpoint and its `No digest yet` output for a null digest. Its renderer in `mc_mission_runs.py` shows `data.digest` with `report.py` primitives (`get_console()`, `build_table`): a summary panel, then tables for outcomes, open items, decisions (omitted when empty) and context changes, then a metrics line that includes the generator. No logic runs client-side.

**Tests**

In `tests/unit/backend/temporal/test_mission_run_memory_workflow.py` (`WorkflowEnvironment.start_time_skipping()`, activities stubbed by name):
- `test_end_run_order_compact_digest_finalise`: record call order.
- `test_compaction_failure_does_not_block_digest`: the compaction stub raises a non-retryable error; `write_run_digest` and `finalise_mission_run` still run.
- `test_cancel_path_forces_deterministic_digest`: `handle.cancel()` mid-layer; the digest stub receives `force_deterministic=True` before `finalise_mission_run`.
- `test_no_digest_when_begin_fails`: `begin_mission_run` raises `RunStartRejectedError`; neither the compaction nor the digest stub is called.

In `tests/unit/backend/temporal/test_replay_histories.py` (existing harness): the seven Phase 2 fixtures replay against Phase 3 code (old branch), and `p88-run-memory` replays (new branch).

In `tests/unit/backend/temporal/test_patch_ids.py` (existing): passes with the new literal.

In `tests/unit/backend/temporal/test_mission_run_activities.py` (exists since 88.1.8):
- `test_finalise_payload_states_generator`.

In `tests/integration/backend/api/test_mission_runs_digest.py`:
- `test_run_detail_includes_digest`.
- `test_run_detail_digest_null_for_skipped_run`.
- `test_run_detail_other_mission_404`.

In `tests/unit/clients/cli/test_mc_mission_runs.py` (exists since 88.1.13):
- `test_runs_digest_renders_sections`.

**Done when:** these tests pass, and the end-to-end check in Verification shows run 2's first task inputs containing `previous_run_digest`, `context_delta` and `learnings`.

---

### Verification

```bash
cd /Users/herman.young/development/mission-control
python admin.py migrate upgrade head
python admin.py admin seed-catalog
pytest tests/unit/backend/core/test_config.py \
       tests/unit/backend/services/test_mission_context.py \
       tests/unit/backend/services/test_mission_context_compaction.py \
       tests/unit/backend/services/test_mcd_pruning.py \
       tests/unit/backend/services/test_summarization.py \
       tests/unit/backend/services/test_context_assembler.py \
       tests/unit/backend/services/test_run_memory_packet.py \
       tests/unit/backend/services/test_run_memory_digest.py \
       tests/unit/backend/services/test_mission_plan_taskio.py \
       tests/unit/backend/mission_control/test_task_runner.py \
       tests/unit/backend/agents/test_digest_agent.py \
       tests/unit/backend/temporal/test_worker_startup.py \
       tests/unit/backend/temporal/test_run_memory_activities.py \
       tests/unit/backend/temporal/test_mission_run_activities.py \
       tests/unit/backend/temporal/test_mission_run_memory_workflow.py \
       tests/unit/backend/temporal/test_patch_ids.py \
       tests/unit/backend/temporal/test_replay_histories.py \
       tests/unit/backend/temporal/test_no_config_in_workflows.py \
       tests/unit/clients/cli/test_mc_mission_runs.py -v
pytest tests/integration/backend/services/test_mission_learning.py \
       tests/integration/backend/services/test_mission_run_service.py \
       tests/integration/backend/api/test_mission_runs_digest.py -v
lint-imports
grep -rn --exclude-dir=migrations "mission_id_ref\|increment_occurrence\|find_by_agent_and_kind\|DEFAULT_TOKEN_BUDGET" modules tests   # expect no output
python scripts/code_quality.py --scope modules/ tests/
# End-to-end on a dev stack (API and worker running), two manual runs on one mission:
MISSION_SLUG=memory-check      # an existing mission selected with mc, gate_mode autonomous
python mc.py runs start --objective "Summarise open issues"          # run 1
python mc.py runs digest 1                                           # digest present, generator shown
python mc.py runs start --objective "Continue from previous run"     # run 2
python scripts/trace_execution.py --mission "$MISSION_SLUG" --last --filter transitions
# Confirm run 2's first task_executions.input_data has the keys previous_run_digest, context_delta and learnings.
```

### Risks

1. **The digest agent adds spend to every run.** The catalog figure is $0.05 per digest; a 168-run hourly week is up to $8.40. Phase 3 does not enforce it. Until Phase 4 is complete, production keeps `missions.recurrence.enabled: false` and does not dispatch MANUAL or AI_ASSISTED missions (Phase 2 operational rule). **Mitigation:** the agent uses the `quick` alias with `max_tokens: 2000` and `agent_output_retries: 2`, every call is recorded in `llm_calls` under `mission_run_id`, and cancelled runs are deterministic. Phase 4 (88.4.6) counts the spend against the per-run cap and skips the agent when headroom is below `max_budget_usd`.
2. **Compaction removes a section an agent still needs.** **Mitigation:** every compaction first writes a full `ContextMilestone` snapshot. `identity`, `guardrails` and `current_state` are protected by config. ARCHIVE changes appear in the next run's `context_delta`, so agents see what left the MCD.
3. **Stale MCD reads.** `MissionContextManager.get_context` uses a 30-second process-local cache (`mission_context.py:51-52,188-206`), so the PCD layer can lag one write behind the version watermark across worker processes. **Mitigation:** the delta and the digest read Postgres directly through versioned queries. The lag affects only the PCD snapshot and clears within 30 seconds. The cache is unchanged in this phase.
4. **In-flight runs during deploy.** Runs started under Phase 2 code must not hit non-determinism errors. **Mitigation:** `workflow.patched("p88-run-memory")` guards the change; the seven Phase 2 fixtures replay the old branch and `p88-run-memory.json` replays the new one in CI (88.3.8).
5. **Learning extraction cost grows with history.** **Mitigation:** `extraction_window_days` bounds the scan, and the derived evidence count makes repeated extraction idempotent.
6. **Write-path compaction under the MCD row lock.** `apply_updates` now holds `SELECT ... FOR UPDATE` on the MCD row until the caller commits, and compaction writes archive rows inside that transaction. **Mitigation:** compaction makes no LLM or network call, and every caller (`RunTaskExecutionService.record`, the curator write-back, the `update_context` tool, summarisation) commits immediately after.

Commit granularity: one commit per step, with messages `Plan 88 Phase 3: 88.3.1 config keys for digest, context packet, compaction` through `Plan 88 Phase 3: 88.3.8 workflow wiring and digest read surfaces`.
