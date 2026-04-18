# Architecture Compliance: Layer Violations, File Splits, Test Coverage & Idempotency

**Version:** 2.0.0
**Date:** 2026-04-18
**Author:** Herman + Architecture Review
**Status:** Done — all phases complete, all 14 outstanding items resolved
**Triggered by:** Codebase audit against reference architecture (01-core-principles, 08-python-coding-standards, AGENTS.md)
**Re-assessed:** 2026-04-18 — compliance check against codebase revealed regressions and new scope
**Closed:** 2026-04-18 — branch `fix/38-architecture-compliance` (8 commits)

---

## 0. Problem Statement

An audit of the codebase against its own stated principles found concrete violations in four areas:

1. **Layer violations (P1/P2)** — API endpoints and client modules import repositories/models directly, bypassing the service layer
2. **File size drift** — 9 files exceed the 500-line target; the largest API endpoint is at 832 lines (83% of the 1000-line hard limit)
3. **Service-layer test gap** — Zero dedicated unit tests for the core business logic services (auth, session, mission, execution)
4. **P6 idempotency gap** — No idempotency keys on critical mutating endpoints
5. **Frontend page monoliths** — 3 page components exceed 500 lines with mixed concerns

This plan addresses each in priority order with minimal blast radius per phase.

---

## 1. Phase 1 — Fix Layer Violations (Critical) [REGRESSED]

> **Originally completed 2026-04-08** — commits `60b7afb` (code fixes) and `889575d` (plan, checker, test fix).
>
> **⚠ Re-assessment 2026-04-18:** 8 new violations found in API layer. Root cause: `check_layer_violations.py` was never wired into pre-commit, and `code_rules_fast.py` rule 001.6 only catches repository imports (not model imports). 6 of 8 violations are model imports that slip through undetected. Client layer remains clean.
>
> **Goal:** Restore strict API → Service → Repository → Model layering. Remove all repository/model imports from API endpoints and client code.

### 1.1 API Endpoint Violations

| File | Violation | Fix |
|------|-----------|-----|
| `modules/backend/api/v1/endpoints/executions.py:61,144,252,311` | Imports `ExecutionRepository` directly (4 places) | Move all repository calls into `ExecutionService` methods; endpoint calls service only |
| `modules/backend/api/v1/endpoints/missions.py:142` | Imports `ExecutionEnvironmentModel` directly | Add a service method (e.g., `ExecutionEnvironmentService.get_for_mission()`) and call that |

**Implementation notes:**
- For each repository call in an endpoint, identify the operation, create a corresponding service method, move the logic there, and update the endpoint to call the service.
- Do not change HTTP contracts — request/response shapes stay identical.
- Each fix is a single commit with the endpoint change + new service method.

### 1.1b New API Endpoint Violations (found 2026-04-18)

| File | Violation | Fix |
|------|-----------|-----|
| `modules/backend/api/v1/endpoints/missions_plan.py:32` | Imports `MissionPlanStatus`, `PlanTaskStatus` from models | **Re-import from schemas** — `modules.backend.schemas.mission_plan` already re-exports both enums. No new code needed. |
| `modules/backend/api/v1/endpoints/missions_plan.py:73` | Imports `MissionMember` model for inline membership check | **Add `MissionService.is_member(mission_id, user_id) -> bool`**. No equivalent exists today. |
| `modules/backend/api/v1/endpoints/mission_knowledge.py:89,105` | Imports `MissionLearningRepository` for `get()` calls | **Add `MissionLearningService.get_by_id(learning_id)`**. Service exists but lacks this method. |
| `modules/backend/api/v1/endpoints/mission_knowledge.py:74` | Accesses `svc._learning_repo.count_by_mission()` (private attr) | **Add `MissionLearningService.count_by_mission(mission_id) -> int`**. |
| `modules/backend/api/v1/endpoints/streams.py:26` | Imports `User` model | **Type annotation only** — used as param type for `_require_mission_access`. Low severity. Fix by typing as the schema `UserOut` or using `Depends(get_current_user_sse)` return type. |
| `modules/backend/api/v1/endpoints/missions.py:235` | Imports `MissionEvent` for inline SQLAlchemy query in `get_narrative` | **Add `MissionService.get_narrative_events(mission_id)`** or similar. No event query service exists today. |
| `modules/backend/api/v1/endpoints/knowledge.py:92,128` | Imports `MissionDecision`, `MilestoneSummary` for inline queries | **Add `KnowledgeService.list_decisions(mission_id)` and `KnowledgeService.list_milestones(mission_id)`**. `HistoryQueryService` has related methods but not these specific ones. |

### 1.2 Client Module Violations

| File | Violation | Fix |
|------|-----------|-----|
| `modules/clients/cli/mission_context.py:22` | Imports `UserRepository` | Route through `UserService` or a backend HTTP call |
| `modules/clients/cli/mission_cmds.py:110` | Imports `AgentCatalogRepository` | Route through `AgentCatalogService` |
| `modules/clients/cli/mission_cmds.py:259` | Imports `MissionRepository` | Route through `MissionService` |
| `modules/clients/cli/mc_team.py:17` | Imports `AgentCatalogRepository` | Route through `AgentCatalogService` |
| `modules/clients/cli/health.py:53` | Imports `models.base` (Base, TimestampMixin, UUIDMixin) | ~~Originally listed as violation~~ — `check_layer_violations.py` explicitly allows `modules.backend.models.base` (type hints only). **Not a violation.** Remove from list or remove the exception from the script. |
| `modules/clients/tui/services/service_bridge.py:21` | Imports `Mission` model | Use schema/DTO or service method |
| `modules/clients/tui/services/service_bridge.py:36` | Imports `UserRepository` | Route through `UserService` |

**Implementation notes:**
- CLI commands that currently open a DB session and call a repository should instead call an existing service method (many already exist).
- Where the CLI calls the backend in-process (not via HTTP), it should use `Service.factory()` context managers — never instantiate a repository.
- The TUI `service_bridge.py` exists precisely to be a service facade. It should import services, not repositories/models.

### 1.3 Prevention — Automated Enforcement

After fixing violations, add an automated gate so they cannot recur:

**Option A: Compliance scan in pre-commit hook (recommended)**

Add a lightweight script `scripts/check_layer_violations.py` that:
1. Scans `modules/backend/api/` for imports of `modules.backend.repositories` or `modules.backend.models` (allow `schemas` only)
2. Scans `modules/clients/` for imports of `modules.backend.repositories` or `modules.backend.models`
3. Exits non-zero if any violations found
4. Integrates as a pre-commit hook and CI check

```python
"""Layer violation detector — run as pre-commit hook or CI check."""
import ast
import sys
from pathlib import Path

FORBIDDEN_IMPORTS = {
    "modules/backend/api/": [
        "modules.backend.repositories",
        "modules.backend.models",
    ],
    "modules/clients/": [
        "modules.backend.repositories",
        "modules.backend.models",
    ],
}

def check_file(path: Path, forbidden: list[str]) -> list[str]:
    violations = []
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return violations
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = ""
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            elif isinstance(node, ast.Import):
                module = ".".join(alias.name for alias in node.names)
            for prefix in forbidden:
                if module.startswith(prefix):
                    violations.append(
                        f"{path}:{node.lineno}: forbidden import '{module}'"
                    )
    return violations

def main() -> int:
    root = Path(__file__).resolve().parent.parent
    errors = []
    for scope, forbidden in FORBIDDEN_IMPORTS.items():
        for py_file in (root / scope).rglob("*.py"):
            errors.extend(check_file(py_file, forbidden))
    for e in errors:
        print(e, file=sys.stderr)
    return 1 if errors else 0

if __name__ == "__main__":
    sys.exit(main())
```

**Option B: Extend existing compliance service**

The existing `modules/backend/services/compliance.py` already scans for relative imports, direct logging, and datetime misuse. Add a `scan_layer_violations()` method using the same pattern. This keeps all compliance logic in one place but only runs on-demand, not as a gate.

**Recommendation:** Do both. Option A as the automated gate (pre-commit + CI). Option B to keep the compliance service comprehensive for on-demand audits.

**⚠ Status 2026-04-18:** Option A partially done — `scripts/check_layer_violations.py` exists but is **not in `.pre-commit-config.yaml`**. The pre-commit fast checker (`code_rules_fast.py` rule 001.6) only catches `from modules.backend.repositories.` imports in API endpoints — it does **not** catch `from modules.backend.models.` imports. This gap allowed 6 model-import violations to accumulate.

**Recommended fix (simplest path):** Extend rule 001.6 in `code_rules_fast.py` to also match `from modules.backend.models.` in API files. Add to existing `ALL_CHECKS` list — no new hook or config entry needed. Note: rules 001.7 (CLI) and 008.1 (Telegram) already correctly check both models and repositories. Rule 001.6 is the only one with this gap.

**Additional gap:** Rule 008.4 (TUI model/repo imports) is documented in `docs/04-rules/008_thin_clients.jsonl` but has **no enforcement function** in `code_rules_fast.py`. Since `check_layer_violations.py` scans all of `modules/clients/` (which includes TUI), wiring it into pre-commit would cover this. Alternatively, add a `check_tui_imports_models` function to `code_rules_fast.py`.

---

## 2. Phase 2 — Split Oversized Files (High) [PARTIAL]

> **Backend splits completed 2026-04-09** — all target backend files split. Layer violation in `mission_control.py` also fixed as part of this phase.
>
> **⚠ Re-assessment 2026-04-18:** Completed splits are holding. However, 3 deferred files have drifted (mission_control.py grew from 795→920). `mission_plan.py` (1165 lines) now exceeds the 1000-line hard limit — new scope. 16 Python files and 6 frontend files exceed 500 lines total. Frontend Phase 2.2 was never started.

### 2.1 Backend Splits

| File | Lines | Split Strategy | Status |
|------|-------|----------------|--------|
| `api/v1/endpoints/missions.py` | 844→267 | Split into `missions_team.py` (302), `missions_workflows.py` (375), `missions_context.py` (105). Core CRUD stays in `missions.py`. | **DONE** |
| `agents/mission_control/helpers.py` | 755→ pkg | Replaced with `helpers/` package: `model_builder.py`, `prompt_builder.py`, `agent_setup.py`, `routing.py`, `event_emitter.py`, `agent_executor.py`. `__init__.py` re-exports all — zero import changes needed. | **DONE** |
| `agents/mission_control/gate.py` | 538→291 | Extracted `gate_models.py` (99 lines: GateAction, GateContext, GateDecision, GateReviewer, NoOpGate) and `gate_prompt.py` (153 lines: system prompt, _build_gate_prompt, _parse_action). gate.py re-exports models. | **DONE** |
| `agents/mission_control/verification.py` | 525→173 | Extracted `verification_models.py` (48 lines: TierStatus, TierResult, Tier3Result, VerificationResult) and `verification_tiers.py` (322 lines: _run_tier_1, _run_tier_2, _run_tier_3, _elapsed_ms). Pipeline orchestrator stays in verification.py. | **DONE** |
| `agents/mission_control/mission_control.py` | 761→795→**920** | Layer violation fixed. File deferred at 795 but has grown to **920 lines** — approaching 1000-line hard limit. Complex async closures resist clean extraction without increasing coupling. | **DEFERRED — growing** |
| `services/pqi/dimensions.py` | 710→446+232 | Converted to `dimensions/` package: `analysis.py` (maintainability, security, modularity, testability) + `style.py` (robustness, elegance, reusability). Re-exports from `__init__.py`. | **DONE** |
| `services/workflow_run.py` | 664→**606** | Single cohesive class — all methods tightly coupled (wave execution references run state). No natural split boundary. Shrank slightly but still over 500. | **DEFERRED** |
| `services/execution.py` | 570→**628** | Complex lifecycle service. Grew by 58 lines. | **DEFERRED — growing** |

### 2.1b New Oversized Backend Files (found 2026-04-18)

Files not in original Plan 38 scope that now exceed 500 lines:

| File | Lines | Notes |
|------|-------|-------|
| `services/mission_plan.py` | **1165** | **Exceeds 1000-line hard limit.** Highest priority split. Natural boundary: extract dispatch block (~440 lines: `dispatch_approved`, `_write_back_task_results`, `_resolve_task_execution_id`, `_derive_subset_task_plan`, supervisor evaluation) into `services/mission_plan_dispatch.py`. Remaining file drops to ~720 lines. |
| `agents/mission/director/agent.py` | **951** | Near hard limit. |
| `clients/tui/services/service_bridge.py` | **890** | TUI service facade. |
| `clients/tui/app.py` | **840** | TUI main app. |
| `agents/mission_control/dispatch/loop.py` | **703** | Dispatch loop. |
| `clients/cli/report.py` | **672** | CLI report generator. |
| `events/types.py` | **655** | Event type definitions. |
| `services/execution_environment.py` | **574** | Execution environment service. |
| `services/mission.py` | **536** | Mission service. |
| `api/v1/endpoints/admin.py` | **535** | Admin endpoints. |
| `agents/mission_control/gate_post_run.py` | **523** | Post-run gate. |
| `core/config_schema.py` | **518** | Config schema. |
| `services/code_map/assembler.py` | **510** | Code map assembler. |

### 2.2 Frontend Splits [NOT STARTED]

| File | Lines (original) | Lines (2026-04-18) | Split Strategy |
|------|------------------|---------------------|----------------|
| `components/workspace/plan-board.tsx` | — | **1528** | Not in original plan. Largest frontend file — needs split. |
| `pages/mission/tabs/chat-tab.tsx` | 534 (was `chat.tsx`) | **948** | Extract `ChatMessageList`, `ChatInput`, `ChatHeader` into components. File has nearly doubled. |
| `pages/mission/overview.tsx` | 677 | **678** | Extract `MissionStats`, `RecentRuns`, `SetupChecklist`, `MissionSettings` into `components/mission/`. |
| `pages/mission/console.tsx` | — | **650** | Not in original plan. Needs split. |
| `types/index.ts` | 522 | **534** | Split into `types/mission.ts`, `types/session.ts`, `types/execution.ts`, `types/admin.ts`, `types/auth.ts`. Re-export from `types/index.ts`. |
| `pages/admin/catalog.tsx` | — | **510** | Not in original plan. |
| ~~`pages/mission/context.tsx`~~ | 546 | — | No longer exists as standalone file. Context UI is in `components/workspace/context-panel.tsx` (423 lines — under target). |

### 2.3 Implementation Notes

- Each split is a pure refactor — no behavior changes, no new features.
- One commit per file split for clean review.
- Run existing tests after each split to confirm no regressions.

---

## 3. Phase 3 — Service Layer Tests (High) [DONE — on track]

> **Completed 2026-04-08** — 57 integration tests across 4 services.
>
> Tests use real in-memory SQLite (not mocks) for end-to-end service validation.
> All tests go through the full Service → Repository → Database chain.
>
> **Re-assessment 2026-04-18:** 79 integration tests across 7 services (22 more than original target). 3 bonus test files added post-plan. `test_execution.py` still deferred. `test_auth.py` is 1 test short of original target (12 vs 13); `test_mission.py` gained 1 (12 vs 11).

### 3.1 Test Structure

```
tests/integration/backend/services/
├── __init__.py
├── conftest.py                 # Real DB fixtures: admin_user, regular_user, test_mission, etc.
├── test_auth.py                # 12 tests (was 13): login, refresh, API key CRUD, revocation
├── test_session.py             # 12 tests: create, get, ensure, cost tracking, budget enforcement, list
├── test_mission.py             # 12 tests (was 11): create, get, resolve, list, update, delete
├── test_user.py                # 21 tests: get, auth checks, current mission, update, password, deactivate
├── test_mission_intent.py      # 10 tests (post-plan): create, dedup, revision, list, count, summary
├── test_mission_learning.py    # 12 tests (post-plan): CRUD, promote/retract, contradiction, extractor
├── test_knowledge_service.py   # 12 tests (post-plan): get_mission_knowledge, get_current_intent, search
```

### 3.2 Test Approach (Updated)

- **Real database** — in-memory SQLite via `db_session` fixture. No mocks.
- Each test gets an isolated session that auto-rolls back — full isolation.
- Tests exercise the real Service → Repository → Model chain.
- Authorization boundaries tested end-to-end (admin vs user vs unauthorized).
- `test_execution.py` still deferred — execution service requires agent dispatch wiring that is harder to isolate without mocking the LLM layer.

### 3.3 Coverage Summary

| Service | Tests | Happy Path | Error Path | Auth Boundary |
|---------|-------|------------|------------|---------------|
| AuthService | 12 | login, refresh, API key create/resolve | wrong password, inactive user, bad token, invalid key | N/A (auth is the boundary) |
| UserService | 21 | get, update, change password, deactivate | nonexistent, wrong password | owner-only, admin-only, self-only |
| MissionService | 12 | create, get, resolve, list, update, delete | nonexistent | owner filter |
| SessionService | 12 | create, get, ensure, cost, list | nonexistent, budget exceeded | user/mission scoping |
| MissionIntentService | 10 | create, dedup, revision linking, list, count | summary truncation | — |
| MissionLearningService | 12 | CRUD, promote/retract | contradiction detection | — |
| KnowledgeService | 12 | get_mission_knowledge, get_current_intent | structured search | — |

---

## 4. Phase 4 — Idempotency Keys (Medium) [PARTIAL]

> **Partially completed 2026-04-09** — commit `e85c1f5`.
>
> `IdempotencyGuard` created in `core/idempotency.py` (Redis-backed, fail-open, 24h TTL). `Idempotency` dependency injected via `Idempotency-Key` header. Applied to 3 of 5 planned endpoints. Pre-commit rule 009.1 blocks future endpoints that fire background execution without idempotency. P16 added to project principles.
>
> **⚠ Re-assessment 2026-04-18:** 2 of 5 target endpoints still missing idempotency: `POST /agents/chat` and `POST /workflows/schedules`.
>
> **Goal:** Add idempotency protection to critical mutating endpoints per P6.

### 4.1 Mechanism

Add an `Idempotency-Key` header (standard pattern, used by Stripe/GitHub):

1. Client sends `Idempotency-Key: <uuid>` header on POST requests.
2. Middleware checks Redis for the key:
   - **Key exists:** Return the cached response (no re-execution).
   - **Key absent:** Execute the request, cache the response in Redis with a TTL (24h).
3. Key format: `idempotency:{user_id}:{key_value}`.

### 4.2 Target Endpoints

| Endpoint | Why | Status |
|----------|-----|--------|
| `POST /missions` | Prevents duplicate mission creation on retry | **DONE** |
| `POST /sessions` | Prevents duplicate session creation | **DONE** |
| `POST /executions/{id}/execute` | Prevents duplicate execution launches (expensive — triggers agent work) | **DONE** |
| `POST /agents/chat` (streaming) | Streaming variant uses `asyncio.create_task` — retry can launch duplicate agent runs | **NOT DONE** — non-streaming variant is safe (awaits synchronously) |
| `POST /workflows/schedules` | Prevents duplicate schedule creation | **DESCOPED** — no background work, just a DB insert. A unique constraint on `(workflow_definition_id, mission_id, cron_expression)` is simpler and more appropriate than idempotency. |

### 4.3 Implementation

1. Create `modules/backend/core/idempotency.py` — middleware/dependency that handles key checking and caching.
2. Use Redis with `SET NX EX` for atomic check-and-set.
3. Add `IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]` dependency.
4. Apply to target endpoints as an optional dependency (non-breaking — key is optional).

### 4.4 Implementation Notes

- Start with `POST /executions` — highest cost of duplicate execution.
- Idempotency is opt-in per endpoint (not blanket middleware) to avoid caching GET responses or non-critical POSTs.

---

## 5. Phase 5 — Minor Fixes (Low) [NOT STARTED]

### 5.1 Temporal Config Default [NOT DONE]

**File:** `modules/backend/core/config_schema.py:313`

Remove the `localhost:7233` default from `server_url`. When `temporal.enabled` is true, require explicit configuration:

```python
# Before
server_url: str = "localhost:7233"

# After
server_url: str | None = None  # Required when temporal.enabled is true
```

Update the validator to fail on `None` when enabled.

### 5.2 SSE Token Security [NOT DONE]

> **Status 2026-04-18:** Full JWT is still passed as `?token=` query parameter via `api.sse()` in `modules/frontend/src/lib/api.ts:127-134`. Backend `get_current_user_sse` in `modules/backend/core/dependencies.py:101-132` resolves the raw JWT directly. Three SSE hooks (`useRunStream`, `useMissionStream`, `useNotificationStream`) all use this pattern. The JWT appears in server access logs, browser history, and proxy logs.

Replace query-param token passing with one of:
- **Short-lived SSE tokens:** Backend issues a 30-second single-use token for SSE connections. Client exchanges JWT for SSE token, passes SSE token as query param. Limits exposure window.
- **Fetch + ReadableStream:** Replace `EventSource` with `fetch()` using `Authorization` header and manual stream parsing. Modern browsers support this.

**Recommendation:** Short-lived SSE tokens — less client-side complexity, works with all browsers.

---

## 6. Execution Order & Dependencies

```
Phase 1 (Layer Violations)     ← Do first — architectural integrity
  ├── 1.3 Extend rule 001.6   ← Smallest change, biggest prevention impact
  ├── 1.1b Fix 7 violations   ← Create service methods, update endpoints
  └── 1.2 Resolve models.base ← Decide: allow or fix

Phase 2 (File Splits)          ← After Phase 1 (some files overlap)
  ├── 2.1 mission_plan.py     ← Critical — over hard limit
  ├── 2.1 Other backend       ← Independent per file, prioritize by size
  └── 2.2 Frontend splits     ← Independent per file

Phase 3 (Service Tests)        ← Can start in parallel with Phase 2
  └── test_execution.py       ← Only remaining gap

Phase 4 (Idempotency)          ← After Phase 1 (needs clean service layer)
  ├── Streaming chat guard    ← Idempotency on streaming endpoint
  └── Schedule constraint     ← DB unique constraint, not idempotency

Phase 5 (Minor Fixes)          ← Any time, no dependencies
```

**Estimated remaining effort:** Phase 1 (~1 session), Phase 2 (~4–5 sessions including new scope), Phase 3 (~1 session), Phase 4 (~small), Phase 5 (~1 session).

---

## 7. Validation

After all phases:

1. `python scripts/check_layer_violations.py` returns 0 — **currently fails (8 violations)**
2. No Python file in `modules/` exceeds 1000 lines; target ~400-500 lines per AGENTS.md — **currently fails (`mission_plan.py` at 1165; 16 files over 500)**
3. `pytest tests/integration/backend/services/ -v` passes with 50+ test cases — **passes (79 tests)**
4. Pre-commit hook blocks any new layer violation (via extended rule 001.6 in `code_rules_fast.py`) — **not yet: rule 001.6 only catches repository imports, not model imports**
5. Existing tests still pass (`pytest tests/ -v`)

---

## 8. Outstanding Work (as of 2026-04-18)

### Critical — Regressions

| # | Item | Phase | Effort | Notes |
|---|------|-------|--------|-------|
| 1 | Extend `code_rules_fast.py` rule 001.6 to also match `from modules.backend.models.` in API files | 1.3 | Small | Simplest path — add regex, append to `ALL_CHECKS`. No new hook needed. |
| 2 | Fix 7 layer violations in API endpoints (see §1.1b) | 1.1 | 1 session | 1 is schema re-import only; 4 need new service methods; 1 type-annotation-only (low severity); 1 needs narrative query service method |
| 3 | Split `services/mission_plan.py` (1165 lines — **over hard limit**) | 2.1 | 1 session | Extract dispatch block (~440 lines) into `mission_plan_dispatch.py` |

### High

| # | Item | Phase | Effort | Notes |
|---|------|-------|--------|-------|
| 4 | Frontend Phase 2.2 splits — 5 files over 500 lines, `plan-board.tsx` at 1528 | 2.2 | 2 sessions | |
| 5 | Address `mission_control.py` growth (920 lines, trending toward hard limit) | 2.1 | 1 session | |
| 6 | Add integration `test_execution.py` | 3 | 1 session | |

### Medium

| # | Item | Phase | Effort | Notes |
|---|------|-------|--------|-------|
| 7 | Apply idempotency to `POST /agents/chat` (streaming variant only) | 4 | Small | Non-streaming is safe. Streaming uses `create_task` without guard. |
| 8 | Add unique constraint on `(workflow_definition_id, mission_id, cron_expression)` for schedules | 4 | Small | Replaces idempotency — no background work, just a DB insert. |
| 9 | Split remaining deferred backend files (`execution.py` 628, `workflow_run.py` 606) | 2.1 | 1 session | |
| 10 | Address new oversized backend files not in original scope (13 files over 500) | 2.1 | 2–3 sessions | Prioritize files approaching 1000-line limit: `director/agent.py` (951), `service_bridge.py` (890), `app.py` (840) |
| 11 | Add rule 008.4 enforcement (TUI model/repo imports) to `code_rules_fast.py` | 1.3 | Small | Rule documented but not implemented |

### Low

| # | Item | Phase | Effort | Notes |
|---|------|-------|--------|-------|
| 12 | Phase 5.1 — Temporal `server_url` default to `None` | 5 | Small | |
| 13 | Phase 5.2 — SSE short-lived token mechanism | 5 | 1 session | |
| 14 | Resolve `models.base` contradiction — either remove `ALLOWED_EXCEPTIONS` from `check_layer_violations.py` or drop `health.py:53` from §1.2 violation list | 1.2 | Small | Currently contradictory |
