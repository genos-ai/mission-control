# Plan 70 — Codebase Health & Standards Compliance

**Version:** 1.2.0
**Date:** 2026-05-03
**Author:** Herman + Opus 4.6 Full Codebase Audit
**Status:** Ready for implementation
**Depends on:** None (all changes are fixes to existing code)
**Unlocks:** Cursor pagination at scale, clean layer boundaries, type-safe models, test confidence
**Branch:** `fix/70-codebase-health`

---

## 0. Problem Statement

A full codebase audit (486 files, 86K lines) against the reference architecture (01-core-principles, 03-backend-architecture, 04-module-structure, 08-python-coding-standards, AGENTS.md) found **27 violations** across 7 categories. Plan 38 (architecture compliance) addressed an earlier round of violations but several have regressed and new ones have appeared. Plan 64 (database hardening) fixed timestamp/enum/FK issues but 4 model-level type mismatches remain.

The violations cluster at **boundaries** — where layers meet, where clients meet backend, and where agents meet services. Left unchecked, each violation becomes a precedent that accelerates architectural erosion.

### Audit Scope

- 5 parallel exploration agents (structure, data layer, agents, clients, security)
- Manual verification of all findings against source code
- Cross-referenced against Plans 38 and 64 to avoid duplicate work

### What's Working Well (no action needed)

- Exception hierarchy and HTTP status mapping
- Configuration management (.env + YAML split, no hardcoded secrets)
- Security fundamentals (bcrypt, JWT, CORS restrictive, Pydantic validation)
- Frontend thin-client compliance (centralized API client, envelope unwrap)
- Agent tool registry (pure functions + adapters + thin wiring)
- Prompt management (5-layer assembly, file-based)
- No relative imports, no bare `except:`, no `os.getenv()` with defaults
- Import linter contracts actively guarding service/agent boundary

---

## 1. Phase A — Fix Model Type Mismatches (P0, correctness bugs)

> **Goal:** Every `Mapped[...]` annotation matches its column type. These are real bugs that confuse mypy, break serialisation, and cause runtime surprises.
>
> **Effort:** ~30 minutes. No migrations needed (column types are already correct in the DB; only the Python annotations are wrong).

| # | File | Line | Current | Fix |
|---|------|------|---------|-----|
| A1 | `modules/backend/models/mission_learning.py` | 92 | `promoted_at: Mapped[str \| None]` with `DateTime(timezone=True)` column | Change to `Mapped[datetime \| None]` |
| A2 | `modules/backend/models/mission_event.py` | 37 | `timestamp: Mapped[str]` with `DateTime(timezone=True)` column | Change to `Mapped[datetime]` |
| A3 | `modules/backend/models/workflow_definition.py` | 82 | `locked_at: Mapped[datetime \| None]` with bare `mapped_column()` | Add explicit `DateTime(timezone=True)` column type |
| A4 | `modules/backend/models/mission_history.py` | 108-113 | `period_start`, `period_end` as `String(30)` | Migrate to `DateTime(timezone=True)` with Alembic migration |

**Notes:**
- A1-A3 are annotation-only fixes (DB schema is already correct from Plan 64 Phase I).
- A4 requires an Alembic migration. Existing `String(30)` values are ISO-8601 strings from `utc_now().isoformat()`. Migration: `ALTER COLUMN ... TYPE timestamptz USING period_start::timestamptz`. Update all write sites to pass `utc_now()` directly.
- A4 write sites to update: `modules/backend/services/summarization.py` (search for `period_start`, `period_end` assignments).

### Verification

```bash
# After fixes, grep should return zero results:
grep -rn 'Mapped\[str.*\].*DateTime' modules/backend/models/
```

---

## 2. Phase B — Fix Layer Violations (P0, architecture erosion)

> **Goal:** Restore strict API -> Service -> Repository -> Model layering. Zero repository or model imports in API endpoints. Zero API imports in services.
>
> **Effort:** ~2-3 hours. Each fix creates a service method and updates the endpoint to call it.
>
> **Regression from Plan 38:** Plan 38 Phase 1 fixed an earlier round. These are new violations introduced after Plan 38 closed.

### B1. API Endpoints Importing Repositories/Models (6 violations)

| # | File | Line(s) | Import | Fix |
|---|------|---------|--------|-----|
| B1.1 | `api/v1/endpoints/missions_workflows.py` | 82-83 | `WorkflowRunState` model, `WorkflowRunRepository` | **Extend existing** `WorkflowRunService.list_runs()` (line 507) — it already delegates to `_run_repo.list_runs()` but is missing the `mission_id`, `status`, and `offset` params that the repo method accepts. Add these params to the service method; endpoint calls service. |
| B1.2 | `api/v1/endpoints/missions_workflows.py` | 414 | `WorkflowRunRepository` (second import) | **Use existing** `WorkflowRunService.get_run()` (line 518) — it already wraps `_run_repo.get_by_id()`. Add a mission_id ownership check to the service method. |
| B1.3 | `api/v1/endpoints/missions_workflows.py` | 645, 698 | `HumanInputRequest` model + raw `select()` | No `HumanInputService` exists. **Create** `HumanInputService` with `list_pending(mission_id)` and `respond(request_id, response)`. Endpoint currently does raw SQLAlchemy queries inline. |
| B1.4 | `api/v1/endpoints/admin.py` | 755 | `MissionPlan` model | Add service method; endpoint calls service |
| B1.5 | `api/v1/endpoints/executions.py` | 360 | `ExecutionRecordRepository` | **Extend existing** `ExecutionPersistenceService` (line 51 of `execution_persistence.py`) — add `get_by_id_or_none()` and `cancel_record()` methods. Endpoint currently instantiates the repo directly to check terminal state before cancelling. |
| B1.6 | `api/v1/endpoints/missions_team.py` | 193 | `MissionTeamRepository` | **Extend existing** `MissionTeamService` — add `update_member_constraints(member_id, data)`. Endpoint currently opens repo directly, merges dicts, flushes, and commits inline. |

**Pattern for each fix:**
1. Check if a service method already exists for the operation (many do — just missing params)
2. If it exists, extend the signature to accept the missing parameters
3. If it doesn't exist, create a new method in the appropriate existing service
4. Update the endpoint to call the service method
5. Remove the repository/model import from the endpoint
6. Verify no HTTP contract changes (same request/response shapes)

### B2. Service Importing from API Layer (1 violation — inverted dependency)

| # | File | Line | Import | Fix |
|---|------|------|--------|-----|
| B2.1 | `services/health.py` | 49 | `from modules.backend.api.health import check_database, check_redis` | Move `check_database()` and `check_redis()` into `services/health.py`. The API health endpoint then calls the service. |

### B3. Prevention — Wire Existing Enforcement into Pre-Commit

Plan 38 created `scripts/check_layer_violations.py` which already checks **both** `modules.backend.repositories` and `modules.backend.models` imports in API endpoints and client code (lines 24-33). It also has a correct allowlist for `modules.backend.models.base` (line 37-44). The script works — the problem is it was **never wired into pre-commit or CI**, so violations reappear uncaught.

**Actions:**
1. Add `check_layer_violations.py` to `.pre-commit-config.yaml` as a local hook (alongside existing `code-rules` hook)
2. Add to CI pipeline as a blocking check
3. No changes needed to the script itself — it already catches the violations found in this audit

### Verification

```bash
python scripts/check_layer_violations.py  # Should exit 0
lint-imports  # import-linter contracts should pass
```

---

## 3. Phase C — Cursor-Based Pagination (P1, scaling wall)

> **Goal:** Replace offset-based pagination with keyset/cursor pagination in all repositories. The architecture doc (03-core-backend-architecture, line 329) states: *"Cursor-based pagination is mandatory. Offset-based pagination is forbidden."*
>
> **Effort:** ~4-6 hours.
>
> **Impact:** 13+ repository methods currently use `.offset(offset)`. At scale (>10K rows), offset pagination degrades to O(n) per page.
>
> **Existing infrastructure:** `core/pagination.py` already provides `encode_cursor()`, `decode_cursor()`, `PaginationParams` (with `is_cursor_based` property), `PagedResult`, and `create_paginated_response()`. `schemas/base.py` defines `PaginatedResponse` with `cursor`/`next_cursor` fields. The plumbing exists — it's just not wired into repositories.

### C1. Add Cursor Pagination to BaseRepository

Extend `BaseRepository` with a cursor-aware list method that **uses the existing** `encode_cursor()`/`decode_cursor()` from `core/pagination.py`:

```python
# modules/backend/repositories/base.py

from modules.backend.core.pagination import encode_cursor, decode_cursor

async def list_paginated(
    self,
    *,
    limit: int = 50,
    cursor: str | None = None,
    order_by: str = "created_at",
    descending: bool = True,
) -> tuple[list[ModelType], str | None]:
    """Keyset-paginated list. Returns (items, next_cursor).

    Uses encode_cursor/decode_cursor from core.pagination.
    Cursor encodes {sort_value}:{id} as specified in doc 03.
    """
    ...
```

**Do NOT recreate** cursor encoding/decoding — `core/pagination.py` already has it. However, the existing `encode_cursor()` accepts a single value. It needs to be extended to encode a composite `{sort_value}:{id}` tiebreaker key (or create a `encode_keyset_cursor(sort_value, id)` variant).

**Tiebreaker:** Always include `id` as secondary sort to guarantee deterministic ordering.

### C2. Migrate Repository Methods

| Repository | Method(s) | Notes |
|------------|-----------|-------|
| `base.py` | `get_all()` | Replace offset with cursor; keep offset version as `get_all_offset()` (deprecated) for backward compat during migration |
| `mission.py` | `list_by_owner()`, `list_by_status()` | Sort by `created_at DESC, id DESC` |
| `session.py` | `list_by_user()`, `list_by_mission()`, `list_active()` | Sort by `last_activity_at DESC, id DESC` |
| `execution.py` | `list_executions()` | Already returns `(items, total)` — change to `(items, next_cursor)` |
| `execution_record.py` | `list_executions()` | Sort by `started_at DESC, id DESC` |
| `mission_intent.py` | `list_by_mission()` | Sort by `created_at DESC` |
| `mission_learning.py` | `list_by_mission()`, `list_active()` | Sort by `created_at DESC` |
| `user.py` | `get_all()` | Sort by `created_at DESC` |
| `workflow_run.py` | `list_by_workflow()` | Sort by `created_at DESC` |

### C3. Update API Endpoints

All list endpoints that currently accept `offset` should accept `cursor` instead. Response wraps in `PaginatedResponse` with `next_cursor`.

**HTTP contract change:** This is a breaking change for clients. Strategy:
- Accept both `offset` and `cursor` parameters during transition
- If `cursor` is provided, use keyset; if `offset` is provided, use legacy offset with deprecation warning
- Log deprecation warnings for offset usage
- Remove offset support in next major version

### C4. Update Frontend

`modules/frontend/src/lib/api.ts` — update list methods to pass `cursor` instead of `offset`. Read `next_cursor` from `PaginatedResponse.pagination`.

### Verification

```bash
# After migration, grep for .offset( in repositories should return 0:
grep -rn '\.offset(' modules/backend/repositories/
```

---

## 4. Phase D — Externalise Hardcoded Model Strings (P1, config violation)

> **Goal:** Zero hardcoded LLM model identifiers in source code. All model strings come from YAML config. Violates P7 (No Hardcoded Values) and `feedback_no_silent_fallbacks.md`.
>
> **Effort:** ~1 hour.

### D1. Violations Found

| # | File | Line(s) | String | Severity | Fix |
|---|------|---------|--------|----------|-----|
| D1.1 | `agents/mission_control/gate_post_run.py` | 369, 394, 427, 440 | `"copilot:claude-haiku-4.5"` | **HIGH** — bypasses config entirely | Read from `get_app_config().gate.ai.model` (config key already exists at `gate.yaml:23`) |
| D1.2 | `agents/mission_control/gate.py` | 52 | `"copilot:claude-haiku-4.5"` | **LOW** — constructor default only; overridden when called through `create_gate()` (line 156-160 reads `config.ai.model`) | Change default to `None`, fail if no config provided and no model given |
| D1.3 | `services/synthesis.py` | 28 | `_MODEL = "copilot:claude-haiku-4.5"` | **HIGH** — no config path exists | Add `synthesis_model` to agents YAML config |
| D1.4 | `services/agent_catalog.py` | ~100 | Default model in create | **MEDIUM** | Read from config |

### D2. Config Changes

`config/settings/gate.yaml` **already has** the gate AI model at line 23:
```yaml
ai:
  model: "copilot:claude-haiku-4.5"   # Already exists — gate_post_run.py just doesn't read it
```

**Only new config needed** — add to `config/settings/agents.yaml`:
```yaml
agents:
  synthesis_model: "copilot:claude-haiku-4.5"
```

Update `config_schema.py` with `synthesis_model` field in the agents schema. No new gate config needed.

### Verification

```bash
# After fixes, no model strings in non-config source:
grep -rn '"copilot:' modules/backend/ --include='*.py' | grep -v config | grep -v test
grep -rn '"anthropic:' modules/backend/ --include='*.py' | grep -v config | grep -v test
grep -rn '"openai:' modules/backend/ --include='*.py' | grep -v config | grep -v test
```

---

## 5. Phase E — Split Oversized Files (P1, maintainability)

> **Goal:** All files under 1000 lines (hard limit), targeting ~400-500 (soft target).
>
> **Effort:** ~3-4 hours.

### E1. Files Exceeding 1000-Line Limit

| File | Lines | Over by | Split Strategy |
|------|------:|--------:|----------------|
| `admin.py` (root) | 1,316 | +316 | Extract command groups into `modules/clients/cli/admin_*.py` handler files, matching the pattern `mc.py` uses. Move business logic (migration loop at L933, workflow seeding at L965, gate instantiation at L456) into services. |
| `services/mission_plan_orchestrator.py` | 1,370 | +370 | Split into `orchestrator_dispatch.py` (dispatch_approved + helpers), `orchestrator_refine.py` (refine + plan persistence), `orchestrator_events.py` (event emission). This also naturally reduces the 8 import-linter exceptions for this file. |
| `agents/mission/director/agent.py` | 1,268 | +268 | Separate tool registration from agent creation. Extract prompt construction into a dedicated module. |

### E2. Files Approaching Limit (monitor)

| File | Lines | Action |
|------|------:|--------|
| `services/workflow_run_waves.py` | 967 | Monitor — split if it grows past 1000 |
| `clients/tui/services/service_bridge.py` | 893 | Will shrink when Phase F decouples TUI |
| `events/types.py` | 871 | Event types are data classes — size is acceptable if no logic |
| `clients/tui/app.py` | 841 | Monitor |
| `api/v1/endpoints/admin.py` | 791 | Monitor |

---

## 6. Phase F — Decouple Client Boundary Violations (P2, module independence)

> **Goal:** Client modules (TUI, CLI) communicate with backend only through services or HTTP API — never by importing agent internals, models, or repositories.
>
> **Effort:** ~4-6 hours. This is the largest refactor.

### F1. Extract SYSTEM_CLI_ID to Shared Location

The constant `SYSTEM_CLI_ID` is defined in `modules/backend/models/base.py:24` and imported by 4 client files + 1 service file:

| File | Line | Module |
|------|------|--------|
| `clients/tui/services/service_bridge.py` | 23 | client |
| `clients/tui/screens/profile.py` | 27 | client |
| `clients/cli/schedule_cmds.py` | 10 | client |
| `clients/cli/mission_context.py` | 17 | client |
| `services/workflow_run.py` | 30 | backend |

**Fix:** Move `SYSTEM_CLI_ID` (and the related `SYSTEM_NAMESPACE`, `SYSTEM_ACCOUNTS` dict) from `models/base.py` to `modules/backend/core/constants.py` (new file). This is a `core/` module, which both services and clients are permitted to import. Update all 5 import sites. `models/base.py` re-imports from `core/constants.py` for backward compat with migrations.

**Do NOT** create an API endpoint for this — it's a build-time deterministic UUID5, not runtime state.

### F2. Decouple TUI Service Bridge from Agent Internals

`modules/clients/tui/services/service_bridge.py` imports 5 agent-internal modules. Several already have canonical locations outside the agents layer:

```python
# Current (violating) imports:
from modules.backend.agents.mission_control.gate import GateReviewer          # ALREADY in schemas/gate.py:88
from modules.backend.agents.mission_control.mission_control import handle_mission  # No alternative yet
from modules.backend.agents.mission_control.models import EventBusProtocol, NoOpEventBus  # ALREADY in core/protocols.py
from modules.backend.agents.mission_control.outcome import ExecutionOutcome   # ALREADY in schemas/execution_outcome.py:147
from modules.backend.agents.mission_control.roster import derive_roster_from_team, Roster  # No alternative yet
```

**Fix strategy (incremental):**

**Full scope of client -> agent import violations (16 imports across 10 files):**

| Client File | Agent Import | Schema/Core Alternative |
|-------------|-------------|------------------------|
| `tui/services/service_bridge.py:13` | `gate.GateReviewer` | `schemas.gate.GateReviewer` |
| `tui/services/service_bridge.py:15` | `models.EventBusProtocol, NoOpEventBus` | `core.protocols.EventBusProtocol, NoOpEventBus` |
| `tui/services/service_bridge.py:16` | `outcome.ExecutionOutcome` | `schemas.execution_outcome.ExecutionOutcome` |
| `tui/services/service_bridge.py:17` | `roster.derive_roster_from_team, Roster` | **None yet** |
| `tui/services/gate_reviewer.py:17` | `gate.{GateAction,GateContext,GateDecision,GateReviewer}` | `schemas.gate.*` |
| `tui/services/state.py:12-17` | `gate.GateContext`, `outcome.{ExecutionOutcome,TaskResult,TaskStatus}`, `roster.RosterAgentEntry` | `schemas.gate.GateContext`, `schemas.execution_outcome.*`, **roster: none yet** |
| `tui/services/event_listener.py:11` | `models.EventBusProtocol` | `core.protocols.EventBusProtocol` |
| `tui/widgets/gate_modal.py:17` | `gate.{GateAction,GateContext,GateDecision}` | `schemas.gate.*` |
| `tui/widgets/mission_panel.py:15` | `outcome.TaskResult, TaskStatus` | `schemas.execution_outcome.TaskResult, TaskStatus` |
| `tui/widgets/agent_sidebar.py:17` | `roster.RosterAgentEntry` | **None yet** |
| `tui/messages.py:10` | `gate.GateContext, GateDecision` | `schemas.gate.*` |
| `tui/app.py:50` | `outcome.TaskResult, TaskStatus` | `schemas.execution_outcome.*` |
| `cli/live_display.py:35` | `models.EventBusProtocol` | `core.protocols.EventBusProtocol` |
| `cli/gate.py:20` | `gate.{GateAction,...}` | `schemas.gate.*` |

**Fix strategy (incremental):**

1. **Immediate re-pointing (no new code, 13 of 16 imports):** The canonical non-agent locations already exist:
   - `GateReviewer`, `GateAction`, `GateContext`, `GateDecision`, `NoOpGate` -> `schemas.gate`
   - `EventBusProtocol`, `NoOpEventBus` -> `core.protocols`
   - `ExecutionOutcome`, `TaskResult`, `TaskStatus` -> `schemas.execution_outcome`

2. **Short-term (3 remaining imports):** Move `Roster`, `RosterAgentEntry` (Pydantic BaseModels) to `schemas/roster.py`. Move `derive_roster_from_team()` to a service method.

3. **Medium-term:** Create `MissionDispatchService` in the service layer that wraps `handle_mission()`. TUI calls `service.dispatch(mission_id, ...)` instead of calling agent code directly.

4. **Long-term:** TUI communicates via HTTP API like the frontend does.

### F3. Decouple TUI App from Dispatch/Outcome Imports

`modules/clients/tui/app.py` imports `topological_sort`, `TaskResult`, `TaskStatus`, `TaskPlan` from backend internals.

**Fix:** Re-export the needed schemas from a shared DTO module that clients are allowed to import (e.g., `modules/backend/schemas/task_plan.py` is already a schema — TUI importing schemas is acceptable; importing from `agents.mission_control.dispatch` is not).

### F4. Fix admin.py Business Logic

`admin.py` lines 933-941 contain a full migration loop with `MissionRepository` and `get_async_session()`:

**Fix:** Create `MissionTeamService.backfill_rosters()` method. The admin CLI calls `service.factory()` and delegates.

Similarly for lines 965-970 (workflow seeding) and 456-459 (gate instantiation).

### F5. Fix Direct Logging Import

`modules/clients/cli/api_client.py:20` uses `import logging` instead of `get_logger()`.

**Fix:** Replace with `from modules.backend.core.logging import get_logger`.

---

## 7. Phase G — Test Coverage for Critical Paths (P2, safety net)

> **Goal:** Integration tests for the mission dispatch pipeline, plan orchestration, and workflow execution. These are the highest-risk code paths with the least test coverage.
>
> **Effort:** ~6-8 hours.

### Current State

| Category | Count |
|----------|------:|
| Unit tests | 122 files |
| Integration tests | 13 files |
| E2E tests | 0 files |

### G1. Priority Integration Tests to Add

| Test File | Covers | Why Critical |
|-----------|--------|-------------|
| `tests/integration/services/test_mission_plan_orchestrator.py` | Plan creation, approval, dispatch flow | 1,370-line file with 8 import-linter exceptions — most complex service |
| `tests/integration/services/test_workflow_run.py` | Workflow execution, wave dispatch, status transitions | Orchestrates multi-agent runs |
| `tests/integration/services/test_mission_plan.py` | CRUD, task state machine transitions | State machine correctness |
| `tests/integration/api/test_missions_workflows.py` | Workflow API endpoints | High-violation file (Phase B fixes) |
| `tests/integration/services/test_session.py` | Session lifecycle, expiry, followup scheduling | Long-lived state management |

### G2. Unit Tests for Untested Services

The following services have no dedicated test files:

| Service | File | Lines | Risk |
|---------|------|------:|------|
| `mission_plan_orchestrator.py` | `services/` | 1,370 | Highest |
| `workflow_run_waves.py` | `services/` | 967 | High |
| `execution_dispatch.py` | `services/` | varies | High |
| `knowledge.py` | `services/` | 506 | Medium |
| `context_assembler.py` | `services/` | varies | Medium |

---

## 8. Phase H — Minor Standards Violations (P3, consistency)

> **Goal:** Clean up remaining minor violations for full standards compliance.
>
> **Effort:** ~30 minutes.

| # | File | Line(s) | Issue | Fix |
|---|------|---------|-------|-----|
| H1 | `agents/security/tool_runner.py` | 246, 250 | `datetime.now()` for timing | Replace with `time.monotonic()` |
| H2 | `clients/cli/live_display.py` | 122 | `Console()` created directly | Replace with `get_console()` from `report.py` |
| H3 | `frontend/vite.config.ts` | 26, 49 | Hardcoded `http://localhost:8100` | Read from `VITE_API_URL` env var |
| H4 | `services/health.py` | — | `except Exception: pass` in Redis fallback | Add `logger.info("Redis unavailable for SSE token lookup, falling back to JWT")` |

---

## 9. Implementation Order

Phases are ordered by: correctness risk first, then architectural impact, then effort.

| Order | Phase | Effort | Risk if Deferred |
|-------|-------|--------|-----------------|
| 1 | **A** — Model type mismatches | 30 min | Runtime bugs, mypy failures |
| 2 | **B** — Layer violations | 2-3 hrs | Architecture erosion accelerates |
| 3 | **D** — Hardcoded model strings | 1 hr | Deployment inflexibility |
| 4 | **H** — Minor violations | 30 min | Inconsistency |
| 5 | **E** — File splits | 3-4 hrs | Maintainability debt |
| 6 | **C** — Cursor pagination | 4-6 hrs | Scaling wall (deferred OK if data volume is small) |
| 7 | **F** — Client decoupling | 4-6 hrs | Module independence (deferred OK short-term) |
| 8 | **G** — Test coverage | 6-8 hrs | Safety net (ongoing effort) |

**Total estimated effort:** ~22-30 hours across all phases.

**Minimum viable fix (Phases A+B+D+H):** ~4 hours. Fixes all correctness bugs, all layer violations, all hardcoded strings, and all minor violations.

---

## 10. Success Criteria

- [ ] `grep -rn 'Mapped\[str.*\].*DateTime' modules/backend/models/` returns 0 results
- [ ] `python scripts/check_layer_violations.py` exits 0 (no layer violations)
- [ ] `lint-imports` exits 0 (import-linter contracts pass)
- [ ] `grep -rn '"copilot:\|"anthropic:\|"openai:' modules/backend/ --include='*.py' | grep -v config | grep -v test` returns 0 results
- [ ] No file in `modules/` exceeds 1000 lines (`find modules/ -name '*.py' | xargs wc -l | awk '$1 > 1000'`)
- [ ] `grep -rn '\.offset(' modules/backend/repositories/` returns 0 results (Phase C)
- [ ] `grep -rn 'from modules\.backend\.agents' modules/clients/tui/services/service_bridge.py` returns 0 results (Phase F)
- [ ] Integration tests exist for `mission_plan_orchestrator`, `workflow_run`, `mission_plan` (Phase G)

---

## 11. Quality Review

### v1.2 corrections (second review pass)

| # | Phase | Issue Found | Correction |
|---|-------|-------------|------------|
| 9 | D1.2 | Plan said gate.py:52 is a hardcoded model string — but `create_gate()` at line 156-160 reads `config.ai.model` from `gate.yaml:23`. The constructor default is only a fallback for direct instantiation. | Downgraded from HIGH to LOW. Config path already works. |
| 10 | D2 | Plan proposed adding `reviewer_model` and `post_run_model` to gate.yaml | **Already exists.** `gate.yaml:23` already has `ai.model: "copilot:claude-haiku-4.5"`. Only `synthesis_model` in agents YAML is genuinely new config. |
| 11 | F2 | Plan listed 5 service_bridge.py imports but missed 11 more client files with agent imports | Expanded to full 16-import, 10-file scope. Found `TaskResult`/`TaskStatus` also exist in `schemas/execution_outcome.py`. 13 of 16 imports can be re-pointed immediately with zero new code. |

### v1.1 corrections (first review pass)

| # | Phase | Issue Found | Correction |
|---|-------|-------------|------------|
| 1 | B1.1 | Plan proposed "add WorkflowRunService methods" — `list_runs()` already exists at `services/workflow_run.py:507` but is missing `mission_id`/`status` params | Changed to "extend existing method signature" |
| 2 | B1.2 | Plan proposed creating a new method — `get_run()` already exists at `services/workflow_run.py:518` | Changed to "use existing, add ownership check" |
| 3 | B1.5 | Plan proposed "add ExecutionPersistenceService method" without noting the service already exists | Clarified: extend existing `ExecutionPersistenceService` (line 51) |
| 4 | B1.6 | Plan proposed "add MissionTeamService method" without noting the service already exists | Clarified: extend existing `MissionTeamService` |
| 5 | B3 | Plan said `check_layer_violations.py` "only catches repository imports" | **Wrong.** Script already checks both `modules.backend.repositories` AND `modules.backend.models` (lines 24-33). Real gap is it's not in pre-commit. Corrected. |
| 6 | C | Plan proposed building cursor encoding/decoding from scratch in `BaseRepository` | **Duplicate.** `core/pagination.py` already provides `encode_cursor()`, `decode_cursor()`, `PaginationParams`, `PagedResult`, `create_paginated_response()`, and a `paginate_query()` helper. Corrected to reference and extend existing utilities. Note: existing `encode_cursor()` encodes single value (ID only); needs extension to composite `{sort_value}:{id}` for proper keyset pagination. |
| 7 | F1 | Plan missed that `SYSTEM_CLI_ID` is also imported by backend `services/workflow_run.py:30` | Added to import site list; adjusted fix to account for backend consumer |
| 8 | F2 | Plan proposed extracting protocols that already exist in canonical locations | **3 of 5 imports already have non-agent alternatives:** `GateReviewer` in `schemas/gate.py:88`, `EventBusProtocol`/`NoOpEventBus` in `core/protocols.py`, `ExecutionOutcome` in `schemas/execution_outcome.py:147`. Corrected to re-point first, create only what's missing. |

### Modularity Check

- **No new abstractions created unnecessarily** — every fix either extends an existing service/method or re-points an import to an existing canonical location
- **No premature generalization** — `list_paginated()` in BaseRepository is the only new generic method; all others are domain-specific service methods
- **No circular dependencies introduced** — all fixes move imports in the correct layer direction (clients -> core/schemas, endpoints -> services)
- **Phase independence** — each phase can be implemented and merged independently without blocking others
- **Existing infrastructure reused** — `core/pagination.py` (cursor encoding), `schemas/gate.py` (gate types), `core/protocols.py` (event bus), `schemas/execution_outcome.py` (task types), `scripts/check_layer_violations.py` (enforcement)
