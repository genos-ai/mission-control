# Plan 84 — Production Readiness Hardening

**Version:** 1.0.0
**Date:** 2026-07-05
**Author:** Herman + Fable 5 context review (`/prompt-get-context`, 2026-07-05)
**Status:** Ready for implementation
**Depends on:** None (all changes harden existing code)
**Unlocks:** Production deployment from a code & architecture standpoint
**Workflow:** Commit directly to `main`, one commit per sub-phase, working code only (no PRs)

---

## 0. Problem Statement

A full context review (PQI 67.0/100, 520 files, ~90K lines) found the architecture sound but
identified 14 findings standing between the current state and production readiness. They cluster
into four themes:

1. **Durability** — the busiest execution path (interactive workflow runs) is fire-and-forget
   `asyncio.create_task`, not Temporal. A backend restart kills the run.
2. **Error visibility** — 91 log-only error paths emit no mission event, 51 swallowed exceptions,
   ProviderError taxonomy wired only into the Copilot adapter. Failures are invisible to operators.
3. **Enforcement** — every quality gate is client-side and skippable; the rule checker passes with
   150 warnings including breaches of "hard" rules (file size, agent boundaries).
4. **Risk concentration** — three god-files (1,801 / 1,468 / 1,233 lines) are the highest-coupled,
   least-tested, most-modified code in the repo.

This plan sequences all 14 findings into 9 phases on the critical path:
**gates → tests → durability → visibility → decomposition → boundaries → security → hygiene.**

### Priority map (review finding → phase)

| Review # | Finding | Phase | Priority |
|---|---|---|---|
| 12 | README quickstart cliff | 0 | P0 (trivial, do first) |
| 13 | Dead code | 0 | P0 |
| — | SSE `logger` NameError (found during scouting) | 0 | P0 (latent crash) |
| — | Unit suite red on main (found during execution start) | 1.0 | P0 (blocks CI) |
| 4 | No unskippable gate (CI) | 1 | P0 |
| 8 | Untested execution core | 2 | P0 |
| 1 | Non-durable execution paths | 3 | P0 |
| 2 | Error invisibility (014.1 + swallowed) | 4 | P0 |
| 6 | ProviderError not wired beyond Copilot | 4 | P1 |
| 7 | NoOpEventBus in production paths | 4 | P1 |
| 3 | God-objects >1000 lines | 5 | P1 |
| 5 | Rule severity drift (promote to error) | embedded in 4, 5, 6 | P1 |
| 9 | Agent data-layer boundary violations (40×011.1) | 6 | P2 |
| 10 | Security loose ends | 7 | P2 |
| 11 | B608 string-SQL | 7 | P2 |
| 14 | models package coupling (Ce=24) | 8 | P3 (optional) |

### Out of scope

- Operability / operator-experience audit — that is `/prompt-production-readiness-review`, a
  separate review. Do not add dashboards, `--watch` flags, or UX features under this plan.
- New product features of any kind. This plan only hardens what exists.

---

## Global constraints for the implementing agent

These override any instinct to improvise:

1. **Fail fast, fail loud.** No silent fallbacks, no hardcoded defaults. If a required value is
   missing, raise. This plan *removes* fallbacks; never add one.
2. **P3 applies (breaking changes are free).** No shims, no `_legacy` aliases, no deprecation
   wrappers. Delete replaced code in the same commit.
3. **Pure moves in decomposition phases.** Phase 5 and 8 are mechanical restructures — zero
   behavior change. If you find a bug while moving code, fix it in a *separate* commit.
4. **Verify before every commit:**
   ```bash
   python scripts/code_rules_fast.py --all   # must exit 0
   pytest tests/unit -x -q                   # must pass
   ```
   Run `pytest tests/integration -x -q` when the phase touches services/API (requires local
   Postgres + Redis; `python services.py check` verifies they're up).
5. **Never commit broken code.** One commit per sub-phase (e.g. `84.4.2`), message prefix
   `Plan 84 Phase N:`.
6. **House rules that recur in this plan:** absolute imports only; `utc_now()` for all timestamps;
   SQLAlchemy `Enum(native_enum=False)` stores by NAME (uppercase); API responses use the
   `ApiResponse` envelope; `execute_agent_fn` output contract is `{"output": ...}`; DB is
   authoritative for the agent catalog (YAML is seed-only); files target ~500 lines, hard max 1000.
7. **Rule definitions live twice** — `docs/04-rules/*.jsonl` (documentation, read by
   `scripts/code_rules.py`) and `scripts/code_rules_fast.py` (Python functions, the pre-commit
   gate). **Every severity change in this plan must be made in BOTH places.**
8. When a phase says "enumerate via checker", the authoritative list is the live output of
   `python scripts/code_rules_fast.py --all`, not the counts in this document — the tree moves.

---

## 1. Phase 0 — Quick wins (correctness bugs, docs, dead code)

> **Goal:** Fix a latent crash, delete verified-dead code, and close the fresh-clone
> documentation cliff. All items independently committable.

### 0.1 Fix SSE token endpoint `logger` NameError

`modules/backend/api/v1/endpoints/auth.py` — the `except` block around line 99–107 in
`POST /sse-token` calls `logger.warning(...)` but the module never defines `logger`. A Redis
outage during token storage currently raises `NameError` instead of the intended
`ExternalServiceError`.

- Add the module-level logger using the same idiom as sibling endpoint files (check
  `modules/backend/api/v1/endpoints/sessions.py` imports — centralized logging via
  `get_logger(__name__)`, never `import logging` per rule 001.2).

### 0.2 Delete dead code (all verified zero-import before deletion)

| Target | Path | Verification before delete |
|---|---|---|
| 5 deprecated adapters | `modules/backend/agents/adapters/{research,code,filesystem,environment,knowledge}.py` (each has "DEPRECATED: Import from modules.backend.tools instead." at line 2) | `grep -rn "adapters.research\|adapters.code\|adapters.filesystem\|adapters.environment\|adapters.knowledge" modules/ tests/ scripts/` → only the files themselves |
| Orphaned service | `modules/backend/services/branch_manager.py` | `grep -rn "branch_manager" modules/ tests/ scripts/` → zero hits |
| Unused exceptions | `RateLimitError` (lines 67–71), `ModelError` (95–112), `ConfigurationError` (115–124) in `modules/backend/core/exceptions.py` | grep each class name across `modules/ tests/` → only the definition |

**Do NOT delete** `ExternalServiceError` (exceptions.py:60–64) — it is raised at
`modules/backend/services/auth.py:107` and by the 0.1 fix.

Also remove the deleted classes from any `__all__` / re-export lists in `core/exceptions.py` and
`agents/adapters/__init__.py`.

### 0.3 Rewrite README Quick Start

`README.md` lines ~41–90 currently document raw `uvicorn` startup, which skips migrations,
seeding, and Temporal — a fresh clone follows it and gets a running server that cannot run a
mission.

Rewrite the Quick Start to:
1. **Prerequisites:** add Temporal CLI (`brew install temporal`) and Docker to the existing
   Python/Node/PostgreSQL/Redis list — `services.py start` launches `temporal server start-dev`
   and its preflight checks Docker.
2. **Canonical startup:** `python services.py start` — state explicitly that it runs preflight
   checks, Alembic migrations, dev-user seeding, the Temporal dev server, the backend, the
   Temporal worker, and the frontend. Mention `python services.py check` / `status` / `stop`.
3. **First-value loop:** three commands proving the install works —
   `python mc.py login`, `python mc.py mission create ...`, `python mc.py run ...`
   (copy exact invocations from `USAGE.md` sections 1–3; link to USAGE.md for the rest).
4. **Production/non-dev note:** `python admin.py admin bootstrap-user --email ... --name ...`
   creates the first admin instead of dev seeding.
5. Keep the raw-uvicorn snippet only under a "Manual startup (advanced)" note, listing what it
   skips.

### Verification (Phase 0)

```bash
grep -rn "branch_manager\|adapters.filesystem\|RateLimitError\|ModelError\|ConfigurationError" modules/ tests/ | grep -v "RateLimitedError"   # zero hits
python scripts/code_rules_fast.py --all && pytest tests/unit -x -q
python -c "import modules.backend.api.v1.endpoints.auth"   # imports clean
```

---

## 2. Phase 1 — Server-side CI gate

> **Goal:** One unskippable gate between code and `main`. The repo pushes to GitHub
> (`github.com/genos-ai/mission-control`) and currently has **no** `.github/workflows/`.

### 1.0 Repair the unit test suite (prerequisite — CI cannot be green without it)

Measured 2026-07-16 at commit `6ff9750`: `pytest tests/unit -q` → **67 failed, 226 errors,
1600 passed**. Nothing runs tests as a gate today, so this drifted silently. Two workstreams:

1. **The 226 errors share one root cause:** `tests/conftest.py:120` (`db_engine` fixture) calls
   `Base.metadata.drop_all`, which raises `CircularDependencyError: Can't sort tables for DROP;
   an unresolvable foreign key dependency exists between tables: execution_records,
   workflow_runs`. The FK cycle comes from the workflow_run_id threading (commit `6ff9750`)
   combined with the pre-existing reverse FK. Fix in the models (not the fixture): give the
   cycle-closing ForeignKey a `name=` and `use_alter=True` so SQLAlchemy can emit
   `DROP CONSTRAINT` separately (per the error's own guidance). Check both
   `modules/backend/models/execution_record.py` and `modules/backend/models/workflow_run.py`
   for the two FK columns; `use_alter=True` belongs on exactly one side of the cycle. An
   Alembic migration is NOT needed if the constraint already exists in Postgres under an
   auto-generated name — but verify with `admin.py migrate autogenerate --message probe`
   producing an empty migration (then delete it).
2. **Triage the 67 failures** (list them with `pytest tests/unit -q | grep FAILED`). Fix in
   batches by module; every fix must address the code-or-test defect, not skip/xfail it.
   If a test asserts behavior that was deliberately changed (P3), rewrite the test to the new
   contract and say so in the commit message.

Exit criterion: `pytest tests/unit -q` fully green locally. Only then create the workflow file.

### 1.1 Create `.github/workflows/ci.yml`

Three jobs, triggered on `push` to `main` and on `pull_request`:

1. **lint** — Python 3.12, install via `uv pip install -r requirements.txt` (system uv), then:
   `black --check --line-length=100 modules scripts tests`,
   `isort --check-only modules scripts tests`, `flake8 modules scripts tests`.
   Mirror the pre-commit config exactly (`.pre-commit-config.yaml`) — do not invent new arguments.
2. **rules** — `python scripts/code_rules_fast.py --all` (exit code is the gate).
3. **tests** — service containers for `postgres:16` and `redis:7`; export
   `TEST_DATABASE_URL=postgresql+asyncpg://...` per `tests/conftest.py:102-115` expectations,
   then `pytest tests/unit -q` and `pytest tests/integration -q`.
   **Do not pass `--cov`** — the 80% floor in `pyproject.toml` [tool.coverage] would fail the
   build today; coverage ratcheting is not in scope.
   Temporal-dependent integration tests: if any fail for lack of a Temporal server, mark them
   with the existing `slow` or a new `temporal` marker and exclude via `-m "not temporal"` —
   do not install Temporal in CI in this plan.

### 1.2 Post-merge note for Herman (manual, not code)

Record in the completion notes: enable GitHub branch protection on `main` requiring the `ci`
workflow — that is a repo-settings click, not a code change, and is what makes the gate truly
unskippable.

### Verification

Push a commit; confirm the workflow runs green in GitHub Actions (`gh run list --limit 1`,
`gh run watch`).

---

## 3. Phase 2 — Test harness for the execution core

> **Goal:** The three untested highest-risk modules get behavioral tests BEFORE Phases 3–5
> refactor them. Per P11 use `TestModel` (never live LLM calls — `ALLOW_MODEL_REQUESTS=False`
> is already enforced in `tests/conftest.py:14`); per P12 use the real-infra fixtures from the
> root conftest (`db_session`, `redis`), not the legacy mocks in `tests/unit/conftest.py`.

Current coverage of the six risk modules:

| Module | Existing tests |
|---|---|
| `agents/mission_control/dispatch/loop.py` | `tests/unit/backend/mission_control/test_dispatch.py` ✓ |
| `services/workflow_run_waves.py` | `tests/unit/backend/services/test_workflow_run_waves.py` ✓ |
| `agents/mission_control/gate_post_run.py` | `tests/unit/backend/mission_control/test_gate_post_run.py` ✓ |
| `agents/mission_control/dispatch/research_loop.py` | **none** |
| `agents/mission_control/helpers/agent_executor.py` | **none** |
| `services/mission_plan_orchestrator.py` | **none** |

### 2.1 `tests/unit/backend/mission_control/test_research_loop.py`

Cover the deterministic helpers directly (no agent needed):
- `compute_coverage_ratio` (research_loop.py:128) — empty analysis, partial, full coverage.
- `should_stop` (line 138) — each stop condition (max rounds, coverage threshold, no-progress).
- `compress_findings` (line 163) — under and over `max_count`.

Cover `execute_research_loop` (line 184) end-to-end with a stub `execute_agent_fn` returning
canned `{"output": ...}` payloads per phase (decompose → search → synthesize → verify): assert
a `TaskResult` is produced, phases execute in order, and a failing phase surfaces an error (not
a silent empty result).

### 2.2 `tests/unit/backend/mission_control/test_agent_executor.py`

Target `_make_agent_executor` / `execute_agent` (`helpers/agent_executor.py:40,51`):
- Output contract: result is wrapped under `{"output": ...}` — consumers read
  `result.get("output", {})`.
- Cost recording occurs on success (assert via the cost recorder path with real `db_session`).
- Agent exception propagates as a failed task result with the error captured — never swallowed.
- Uses `TestModel(call_tools=[...])` for agent simulation.

### 2.3 `tests/unit/backend/services/test_mission_plan_orchestrator.py`

Target the pure/DB-only methods (no LLM):
- `_reconcile_tasks` (mission_plan_orchestrator.py:308) — new tasks created, removed tasks
  cancelled, completed tasks untouched.
- `_derive_subset_task_plan` (line 1319) — subset preserves dependency closure.
- `_write_back_task_results` (line 1212) — task rows updated with statuses (uppercase enum
  NAMES) and outputs.
- `_persist_plan` (line 350) — version bump and metadata persistence via real `db_session`.

### Verification

```bash
pytest tests/unit/backend/mission_control/test_research_loop.py \
       tests/unit/backend/mission_control/test_agent_executor.py \
       tests/unit/backend/services/test_mission_plan_orchestrator.py -q
pytest tests/unit -q   # full suite still green
```

---

## 4. Phase 3 — Durable dispatch (Temporal instead of asyncio.create_task)

> **Goal:** No user-triggered execution path dies with the process. There is exactly **one**
> offending site, and the Temporal workflow to route it through **already exists**.

### 3.1 Route interactive workflow runs through Temporal

**Site:** `modules/backend/api/v1/endpoints/missions_workflows.py:319` —
`run_mission_workflow()` (line 256) launches `_run_in_background()` via `asyncio.create_task`
when gate mode is interactive (comment at lines 289–290 references Plan 80h).

**Existing infrastructure to reuse:**
- `RunWorkflowWorkflow` (`modules/backend/temporal/tool_fork_workflow.py:118`) already executes
  a DB workflow definition durably via activities.
- The Director agent already starts it: copy the pattern from `_start_tool_fork_workflow`
  (`modules/backend/agents/mission/director/agent.py:59`) — `get_temporal_client()`
  (`temporal/client.py:28`) + `client.start_workflow(RunWorkflowWorkflow.run, input, id=...,
  task_queue=config.task_queue)`.

**Change:**
1. Replace the `asyncio.create_task(_run_in_background())` branch with a Temporal
   `start_workflow` call. Workflow ID must be deterministic for dedup:
   `f"workflow-run-{run.id}"` (the WorkflowRun row is created before dispatch — reuse its ID).
2. Delete `_run_in_background` and any now-unused imports in the same commit (P3 — no dual
   paths).
3. If `temporal.enabled` is false, **fail fast**: raise so the endpoint returns an explicit
   5xx with a "Temporal required for workflow execution" message. Do NOT fall back to
   in-process execution — that silently reintroduces the bug this phase removes.
4. Ensure the response contract is unchanged: the endpoint still returns the ApiResponse
   envelope with the run ID immediately (the workflow proceeds in Temporal).

### 3.2 Add Idempotency-Key to the run endpoint (rule 009.1 / P16)

`run_mission_workflow()` fires background execution but is the only such endpoint **without**
idempotency support (`sessions.py:48`, `executions.py:203`, `missions.py:51`, `agents.py:131`
all have it). Copy the `Idempotency` dependency pattern from
`modules/backend/api/v1/endpoints/executions.py:203` verbatim. Investigate why the 009.1
checker did not flag this endpoint and fix the checker's detection gap in the same commit
(`scripts/code_rules_fast.py`, check function near line 605).

### 3.3 Crash-recovery coverage for workflow runs

`reconcile_orphaned_execution_records` (`services/mission_plan_crash_recovery.py:152`) marks
stuck ExecutionRecords FAILED. Verify it (or a sibling) also reconciles `WorkflowRun` rows
stuck in RUNNING after a restart; if not, extend it following the same pattern
(RUNNING → FAILED with reason `"backend restart — run orphaned"`, emit the same events as
`reconcile_orphaned_task_states` at line 39). With 3.1 in place Temporal resumes its own runs,
so this covers only pre-Temporal orphans and Temporal-worker loss.

### Verification

```bash
pytest tests/unit tests/integration -q
grep -n "asyncio.create_task" modules/backend/api/v1/endpoints/missions_workflows.py   # zero hits
# Manual smoke (documented in commit message): services.py start; mc run <workflow>;
# kill backend mid-run; restart; confirm the run resumes/completes via Temporal UI or mc runs show.
```

---

## 5. Phase 4 — Error visibility & provider error taxonomy

> **Goal:** No failure invisible to the operator; provider failures classified, not flattened.
> This phase closes review findings #2, #6, #7 and promotes rules 012.1 + 014.1 to errors.

### 4.1 Eliminate rule-014.1 violations (91 sites)

Enumerate: `python scripts/code_rules_fast.py --all 2>&1 | grep '014.1'`.

Decision rule for each site (from the rule's own `fix` field in
`docs/04-rules/014_error_visibility.jsonl`):
- **Failure affects the run's outcome or the operator's mental model** → emit a mission event
  alongside the log (`publish_to_mission`, existing `_emit_*` helper, `SystemEvent`, or
  `MissionNarrativeEvent` — match whichever pattern the surrounding module already uses).
- **Genuinely best-effort** (telemetry, cache warm, cosmetic) → annotate the except block with
  `# best-effort` or `# non-fatal` comment marker (the checker exempts these) — and only if a
  human reading it would agree it must never fail the operation.

Budget expectation: the large clusters are `workflow_run_waves.py`, `mission_plan_orchestrator.py`,
`director/agent.py`, `temporal/*` activities — exactly the run-affecting paths; expect most
sites to need events, not markers. Do not blanket-mark files to make the checker pass.

### 4.2 Eliminate `except: pass` swallowed exceptions (51 sites)

Authoritative list: `.codemap/quality.md` → Robustness → swallowed-exception (regenerate via
`python scripts/code_quality.py` if stale). Policy:
- **Backend** (`modules/backend/**`): narrow the exception type and either log-with-context +
  mission event (per 4.1) or re-raise. `except: pass` is never acceptable in backend code.
- **TUI/CLI widgets** (`modules/clients/**` — ~28 of the 51, mostly `tui/app.py`,
  `tui/widgets/cost_bar.py`): narrow to the specific expected exception and log at debug via
  the centralized logger. Rendering must not crash the TUI, but silence must still leave a
  trace.

### 4.3 Wire ProviderError taxonomy across all adapters

Today only the Copilot adapter classifies (`copilot_model.py:425-448` `_classify_session_error`
with `_QUOTA_PATTERN`/`_REQUEST_ID_PATTERN` at 185–189). Anthropic, OpenAI, and Foundry run
through PydanticAI models (`core/model_builder.py:146-187`) whose SDK errors surface unclassified.

1. Create `classify_provider_error(exc: BaseException, *, provider: str, model: str) ->
   BaseException` in `modules/backend/core/exceptions.py` (single home; the taxonomy lives
   there at lines 143–253):
   - PydanticAI `ModelHTTPError` (import from `pydantic_ai.exceptions`) status 429 →
     `RateLimitedError`; status 402 or quota-pattern message → `QuotaExhaustedError`;
     5xx / timeout / connection errors → `TransientProviderError`.
   - `anthropic.RateLimitError` / `openai.RateLimitError` → `RateLimitedError`;
     `APIConnectionError` variants → `TransientProviderError`. Import SDK exception types
     lazily inside the function (Foundry uses the OpenAI SDK path, so it's covered).
   - Anything unrecognized → return `exc` unchanged (same contract as
     `_classify_session_error`).
2. Apply it in the retry handler: `dispatch/retry_handler.py` — the typed handlers at lines
   99–216 already branch on ProviderError subclasses; the generic `except Exception` at
   line 217 must first call `classify_provider_error` and re-dispatch typed results into the
   existing branches (transient → retry, quota → abort loudly, rate-limit → backoff) instead
   of treating everything as generic failure.
3. Refactor Copilot's `_classify_session_error` to delegate its generic patterns to the shared
   helper, keeping only Copilot-specific subclasses (`EmptyCopilotSessionError`,
   `CopilotQuotaExhaustedError`) local. One classification home, no duplicate regexes.

### 4.4 Remove NoOpEventBus from production paths (9 sites)

Definition: `modules/backend/core/protocols.py:31-54`. Sites (verify against live checker
output for 012.1):

| File | Line | Pattern |
|---|---|---|
| `agents/mission_control/mission_dispatch.py` | 50 | default param `= NoOpEventBus()` |
| `agents/mission_control/mission_control.py` | 133 | default param |
| `agents/mission_control/dispatch/convergence.py` | 104 | `event_bus or NoOpEventBus()` |
| `agents/mission_control/dispatch/loop.py` | 108 | `event_bus or NoOpEventBus()` |
| `agents/mission_control/dispatch/research_loop.py` | 210 | `event_bus or NoOpEventBus()` |
| `services/session_followup.py` | 109 | ctor fallback |
| `services/mission_plan.py` | 75 | ctor fallback |
| `services/mission_plan_orchestrator.py` | 67 | ctor fallback |
| `services/workflow_run_waves.py` | 691 (+ `api/v1/endpoints/executions.py:282`) | fallback |

Fix: make `event_bus` a **required** parameter (no default) at each site and update every
caller to pass the real `SessionEventBus` it already has in scope. Where a caller genuinely has
no bus, that caller's caller does — thread it down; do not construct buses ad hoc.
`NoOpEventBus` remains only for tests. If a test needs it, pass it explicitly.

### 4.5 Promote rules 012.1 and 014.1 to error

In `scripts/code_rules_fast.py`: change `"warning"` → `"error"` in the 012.1 check
(~line 860) and the 014.1 check (~line 822). Mirror the severity in
`docs/04-rules/012_event_bus.jsonl` and `docs/04-rules/014_error_visibility.jsonl`
(constraint 7). Checker must still exit 0 — which it will, because 4.1–4.4 cleared the
violations.

### Verification

```bash
python scripts/code_rules_fast.py --all   # exit 0 with 012.1/014.1 now error-severity
python scripts/code_quality.py            # swallowed-exception count: 51 → 0 backend / documented client residue
pytest tests/unit tests/integration -q
```

---

## 6. Phase 5 — God-object decomposition

> **Goal:** No file over 1000 lines; the three waived files split by responsibility; the waiver
> list deleted and rule 002.2 promoted to error. **Pure moves only** (global constraint 3) —
> Phase 2 tests plus existing suites are the safety net. One file per sub-phase commit.

### 5.1 Split `services/workflow_run_waves.py` (1,801 lines)

Keep `WorkflowRunWavesMixin` with `_execute_steps` (line 258), `_execute_wave` (539),
`_execute_step` routing (580), and the plan-sync/publish helpers (164–256) in place. Move step
executors into a new package `modules/backend/services/workflow_run_steps/`:

| New module | Moves (current lines) |
|---|---|
| `control.py` | `_execute_condition_step` (838), `_execute_decision_step` (897), `_resolve_agent_decision` (970), `_resolve_human_decision` (1017), `_resolve_rule_decision` (1067), `_execute_branch_step` (1289), `_execute_merge_step` (1317) |
| `io.py` | `_execute_notification_step` (1090), `_execute_tool_call_step` (1137), `_execute_llm_call_step` (1225) |
| `human_input.py` | `_execute_human_input_step` (1447) |
| `sub_workflow.py` | `_execute_sub_workflow_step` (1372) |
| `helpers.py` | `_resolve_dispatch_params` (1575), `_extract_first_task_failure` (1625), `_should_skip` (1661), `_build_step_objective` (1761), `_compute_waves` (1796) |

Convert moved methods to module-level functions taking an explicit context (the step context /
service handles they already receive) — matching P7's pure-implementation style. `_execute_step`
becomes a thin dispatch table over them. Target: every file ≤ ~500 lines.

### 5.2 Split `services/mission_plan_orchestrator.py` (1,468 lines)

| New module | Moves (current lines) |
|---|---|
| `mission_plan_orchestrator.py` (stays) | public API: `refine` (97), `apply_plan` (395), `run_objective` (453), `_persist_plan` (350), `_emit` (77) |
| `mission_plan_dispatch.py` | `dispatch_autonomous` (573), `dispatch_approved` (659), `_start_temporal_run_workflow` (602), `_create_early_execution_record` (1418) |
| `mission_plan_supervisor.py` | `_post_run_supervisor` (903), `_fire_followups` (1014), `_apply_supervisor_decision` (1071) |
| `mission_plan_taskio.py` | `_materialize_plan_dict` (263), `_materialize_task_plan` (295), `_reconcile_tasks` (308), `_load_prior_outputs` (1186), `_write_back_task_results` (1212), `_resolve_task_execution_id` (1292), `_derive_subset_task_plan` (1319), `_infer_task_type` (1402) |

The orchestrator composes the split modules; external callers (endpoints, director tools,
Temporal activities) keep importing the same public methods from the orchestrator — only
internals move. Update the Phase 2.3 test imports if the helpers' homes change.

### 5.3 Split `agents/mission/director/agent.py` (1,233 lines)

Per P7 (implementation vs registration), keep `create_agent` (line 138) plus the three
`@agent.instructions` hooks (`inject_current_intent` 1080, `inject_capabilities` 1094,
`inject_orientation` 1150) in `agent.py`, and move tool bodies into sibling modules that
`create_agent` imports and registers:

| New module | Tools (current lines) |
|---|---|
| `tools_mission.py` | `list_tools` (153), `get_mission_info` (169), `list_team` (195), `browse_catalog` (232), `get_execution_history` (298), `get_execution_detail` (331), `get_mission_context` (370), `check_background_tasks` (626) |
| `tools_plan.py` | `get_plan` (664), `refine_plan` (692), `approve_plan_tasks` (842), `run_objective` (564) |
| `tools_workflow.py` | `list_workflows` (390), `run_workflow` (439), `design_workflow` (784), `_create_background_record` (31), `_start_tool_fork_workflow` (59), `_schedule_director_followup` (101) |
| `tools_knowledge.py` | `get_artifacts` (509), `capture_mission_intent` (1004), `get_current_mission_intent` (1038), `query_knowledge` (1048) |

Respect the existing `tool_names` filtering parameter of `create_agent` — registration stays
conditional exactly as today.

### 5.4 Delete the waiver list and promote 002.2 to error

In `scripts/code_rules_fast.py`: delete the `FILE_SIZE_WAIVERS` frozenset (lines 40–46) and
simplify `check_file_size` (line ~55) to `severity = "error"` unconditionally. Mirror in
`docs/04-rules/002_code_patterns.jsonl`. If any *other* file has crossed 1000 lines by the time
this runs, split or trim it in this phase too — the gate must exit 0 with the rule at error.

### Verification (after each sub-phase and at end)

```bash
python scripts/code_rules_fast.py --all
pytest tests/unit tests/integration -q
awk 'END{}' ; find modules -name "*.py" | xargs wc -l | sort -rn | head -5   # nothing above 1000
```

---

## 7. Phase 6 — Agent data-layer boundary violations (40 × rule 011.1)

> **Goal:** Zero direct `sqlalchemy` / `models` / `repositories` imports in `agents/**`;
> rule 011.1 promoted to error.

Enumerate the authoritative list: `python scripts/code_rules_fast.py --all 2>&1 | grep '011.1'`.
Known clusters: `agents/mission_control/{gate_manual.py:191,222; gate_post_run.py:34-35,299,320;
helpers/cost_recorder.py:68; mission_control.py:13; persistence_bridge.py:21,85-86;
roster.py:104-107; task_approval.py:98-100}` and `agents/platform/director/agent.py:49-103`.

Method, per site:
1. Find the existing service owning that entity (`services/mission*.py`, `services/task*.py`,
   `services/execution_persistence.py`, ...) and **extend it** with the needed method.
   Create a new service only when no owner exists. Do not duplicate query logic that a
   repository already has — the service delegates to the repository.
2. The agent module receives the service (or a callable) via its deps object — follow the
   existing `MissionDirectorDeps` injection pattern; never have agents open sessions.
3. Where the import is only for a type annotation, use `TYPE_CHECKING` imports — but if the
   agent *calls* the ORM, it moves to a service, full stop.

Then promote 011.1: `scripts/code_rules_fast.py` line ~671–674 `"warning"` → `"error"`, and
mirror in `docs/04-rules/011_agent_boundaries.jsonl`.

### Verification

```bash
python scripts/code_rules_fast.py --all 2>&1 | grep -c '011.1'   # 0, and checker exits 0 with rule at error
pytest tests/unit tests/integration -q
```

---

## 8. Phase 7 — Security hardening

> **Goal:** Close the implemented-but-unwired and fail-open security gaps. Deployment context:
> single-instance, internal; decisions below are explicit for that context.

### 7.1 Wire the GatewayRateLimiter

`modules/backend/gateway/security/rate_limiter.py:26-109` (singleton at 112–120) is imported by
nothing in the request path; the config flag `auth_rate_limit_enabled`
(`core/config_schema.py:152`, `FeaturesSchema`) is read by nothing.

- Wire the limiter into the FastAPI middleware chain (`core/middleware.py`, alongside the
  existing request-ID middleware), keyed per client (API key ID if authenticated, else client
  IP), enforced when `features.auth_rate_limit_enabled` is true.
- Scope minimally: auth-sensitive endpoints (`/auth/login`, `/auth/sse-token`) and the
  execution-triggering POSTs. 429 responses use the ApiResponse error envelope.
- Add a comment stating the in-memory sliding window is per-process — correct for the current
  single-instance deployment, revisit before horizontal scaling.
- Flip the flag default to `true` in the config schema AND add the option to the commented
  header of the relevant `config/settings/*.yaml` (rule 003.3).

### 7.2 Enforce API-key scopes

`services/auth.py:105-124` `resolve_api_key()` returns the user without reading the key's
`scopes` field. Explicit semantics to implement:
- Empty/NULL scopes → full access of the owning user (all existing keys keep working —
  a deliberate, documented decision, not a silent fallback).
- Non-empty scopes → the key is restricted: add a `require_scope(scope: str)` dependency in
  `core/dependencies.py` that reads the resolved key's scopes, and apply
  `require_scope("admin")` to the admin router (`api/v1/endpoints/admin.py`). Resolve the
  scope set during `resolve_api_key` and attach it to the auth context so the dependency can
  read it without a second lookup.

### 7.3 Gate the legacy ADMIN_API_KEY backdoor

`core/dependencies.py:84-87` → `services/auth.py:202-220` (`resolve_legacy_key`) grants the
first active admin on a static env key.
- Add `features.legacy_admin_key_enabled: bool` (default **false**) to `FeaturesSchema`; the
  dependencies.py branch checks it before calling `resolve_legacy_key`.
- Every successful use logs a WARNING through the centralized logger ("legacy admin key used")
  so usage is visible and the key can be retired.

### 7.4 SSE token resolution fails closed

`core/dependencies.py` `_resolve_sse_token` (~line 150): on Redis error (~line 121 broad
except) it currently falls through to treating the presented token as a raw JWT (~line 162) —
an auth fail-open. Change: Redis lookup failure raises `AuthenticationError` (fail closed,
matching P16's note that *idempotency* fails open but auth must not). Keep the raw-JWT branch
only for the documented legitimate case (if one exists — check callers; if the SSE endpoints
are also called with plain JWTs by design, keep that branch for the *token-not-found* case,
never for the *Redis-unreachable* case).

### 7.5 Harden `repositories/embedding.py` SQL construction (B608)

The `where_sql` interpolation in `semantic_search` (line ~153) and `hybrid_search` (~212), and
the `{source_table}` interpolation in `list_missing` (~249): add a module-level frozenset
allowlist of valid source tables (the embeddings sources are a known set) and validate every
table/column fragment against it before interpolation, raising `ValidationError` otherwise.
Values stay bound via `bindparams` as today. `services/database_admin.py` and
`services/mission.py:304` are already mitigated by hardcoded table lists + `_validate_table()`
— leave them, they carry `# noqa: S608` deliberately.

### Verification

```bash
pytest tests/unit tests/integration -q
# New tests required in this phase: scope enforcement (restricted key → 403 on admin route),
# legacy key disabled by default (env key set, flag off → 401), SSE Redis-down → 401.
python scripts/code_rules_fast.py --all
```

---

## 9. Phase 8 — models package coupling (optional, lowest priority)

> **Goal:** Reduce `modules.backend.models` efferent coupling (Ce=24, PQI's worst modularity
> offender). Skip this phase if time-boxed — it is metrics-driven, not risk-driven.

`models/__init__.py` re-exports 47 symbols from 28 files (3,614 lines total).

1. Keep `models/__init__.py` importing the sub**modules** (required so Alembic autogenerate
   sees all mapped classes — check `migrations/env.py` first to confirm how metadata is
   gathered) but stop re-exporting symbols.
2. Mechanically rewrite all `from modules.backend.models import X, Y` sites to concrete-module
   imports (`from modules.backend.models.mission import Mission`). Enumerate with
   `grep -rn "from modules.backend.models import" modules/ tests/ scripts/`; rewrite; run the
   full suite.
3. Re-run `python scripts/code_quality.py` and record the Ce delta in the commit message. If
   the metric doesn't move meaningfully, revert rather than keep churn.

---

## 10. Completion checklist

| # | Gate | Command |
|---|---|---|
| 1 | Rule checker green with 002.2, 011.1, 012.1, 014.1 at **error** severity | `python scripts/code_rules_fast.py --all` |
| 2 | JSONL rule docs match checker severities | diff severities in `docs/04-rules/*.jsonl` vs script |
| 3 | Full test suite green | `pytest tests/unit tests/integration -q` |
| 4 | CI workflow green on GitHub | `gh run list --limit 1` |
| 5 | No `asyncio.create_task` in endpoints | `grep -rn "asyncio.create_task" modules/backend/api/` |
| 6 | No file > 1000 lines | `find modules -name "*.py" -not -path "*node_modules*" \| xargs wc -l \| awk '$1>1000'` |
| 7 | PQI re-run; score recorded (expect Robustness and Modularity to move) | `python scripts/code_quality.py` |
| 8 | TODO.md entries closed for: Temporal async dispatch, ProviderError wiring, rate limiter, scopes, SSE fail-open, dead code | manual edit |
| 9 | Restart-survival smoke test performed and noted | manual (Phase 3 verification) |
| 10 | Note to Herman: enable branch protection requiring CI | completion notes |

**Explicitly not done by this plan (by design):** operability audit
(`/prompt-production-readiness-review`), live `--watch` progress UX, plan version history,
coverage ratcheting, horizontal-scale rate limiting.
