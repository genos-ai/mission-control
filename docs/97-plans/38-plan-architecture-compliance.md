# Architecture Compliance: Layer Violations, File Splits, Test Coverage & Idempotency

**Version:** 1.1.0
**Date:** 2026-04-08
**Author:** Herman + Architecture Review
**Status:** In progress — Phase 1 complete, Phase 2 active
**Triggered by:** Codebase audit against reference architecture (01-core-principles, 08-python-coding-standards, AGENTS.md)

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

## 1. Phase 1 — Fix Layer Violations (Critical) [DONE]

> **Completed 2026-04-08** — commits `60b7afb` (code fixes) and `889575d` (plan, checker, test fix).
>
> All repository/model imports removed from API endpoints and client code. New service methods added to absorb the operations. `scripts/check_layer_violations.py` created as automated prevention gate. 1532 unit tests pass.
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

### 1.2 Client Module Violations

| File | Violation | Fix |
|------|-----------|-----|
| `modules/clients/cli/mission_context.py:22` | Imports `UserRepository` | Route through `UserService` or a backend HTTP call |
| `modules/clients/cli/mission_cmds.py:110` | Imports `AgentCatalogRepository` | Route through `AgentCatalogService` |
| `modules/clients/cli/mission_cmds.py:259` | Imports `MissionRepository` | Route through `MissionService` |
| `modules/clients/cli/mc_team.py:17` | Imports `AgentCatalogRepository` | Route through `AgentCatalogService` |
| `modules/clients/cli/health.py:53` | Imports `models.base` (Base, TimestampMixin, UUIDMixin) | Refactor health check to not depend on ORM internals |
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

---

## 2. Phase 2 — Split Oversized Files (High) [IN PROGRESS]

> **Goal:** Bring all files under 500 lines. No behavior changes.

### 2.1 Backend Splits

| File | Lines | Split Strategy | Status |
|------|-------|----------------|--------|
| `api/v1/endpoints/missions.py` | 844→194 | Split into `missions_team.py` (302), `missions_workflows.py` (298), `missions_context.py` (105). Core CRUD stays in `missions.py`. | **DONE** |
| `agents/mission_control/mission_control.py` | 761 | Extract prompt assembly and tool registration into separate modules. Keep orchestration entry point. | TODO |
| `agents/mission_control/helpers.py` | 755 | Group helpers by concern (context helpers, formatting helpers, result helpers) into sub-files under `helpers/`. | TODO |
| `services/pqi/dimensions.py` | 710→446+232 | Converted to `dimensions/` package: `analysis.py` (maintainability, security, modularity, testability) + `style.py` (robustness, elegance, reusability). Re-exports from `__init__.py`. | **DONE** |
| `services/workflow_run.py` | 664 | Separate orchestration (run lifecycle) from state management (status tracking, cost aggregation). | TODO |
| `services/execution.py` | 570 | Extract environment resolution and cost tracking into focused modules. | TODO |

### 2.2 Frontend Splits

| File | Lines | Split Strategy |
|------|-------|----------------|
| `pages/mission/overview.tsx` | 677 | Extract `MissionStats`, `RecentRuns`, `SetupChecklist`, `MissionSettings` into `components/mission/`. |
| `pages/mission/context.tsx` | 546 | Extract context editor and history viewer into components. |
| `pages/mission/chat.tsx` | 534 | Extract `ChatMessageList`, `ChatInput`, `ChatHeader` into components. |
| `types/index.ts` | 522 | Split into `types/mission.ts`, `types/session.ts`, `types/execution.ts`, `types/admin.ts`, `types/auth.ts`. Re-export from `types/index.ts`. |

### 2.3 Implementation Notes

- Each split is a pure refactor — no behavior changes, no new features.
- One commit per file split for clean review.
- Run existing tests after each split to confirm no regressions.

---

## 3. Phase 3 — Service Layer Tests (High) [DONE]

> **Completed 2026-04-08** — 57 integration tests across 4 services.
>
> Tests use real in-memory SQLite (not mocks) for end-to-end service validation.
> All tests go through the full Service → Repository → Database chain.
> 1574 total tests pass (1517 existing + 57 new).

### 3.1 Test Structure

Created `tests/integration/backend/services/` with:

```
tests/integration/backend/services/
├── __init__.py
├── conftest.py          # Real DB fixtures: admin_user, regular_user, test_mission, etc.
├── test_auth.py         # 13 tests: login, refresh, API key CRUD, revocation
├── test_session.py      # 12 tests: create, get, ensure, cost tracking, budget enforcement, list
├── test_mission.py      # 11 tests: create, get, resolve, list, update, delete
├── test_user.py         # 21 tests: get, auth checks, current mission, update, password, deactivate
```

### 3.2 Test Approach (Updated)

- **Real database** — in-memory SQLite via `db_session` fixture. No mocks.
- Each test gets an isolated session that auto-rolls back — full isolation.
- Tests exercise the real Service → Repository → Model chain.
- Authorization boundaries tested end-to-end (admin vs user vs unauthorized).
- `test_execution.py` deferred — execution service requires agent dispatch wiring that is harder to isolate without mocking the LLM layer.

### 3.3 Coverage Summary

| Service | Tests | Happy Path | Error Path | Auth Boundary |
|---------|-------|------------|------------|---------------|
| AuthService | 13 | login, refresh, API key create/resolve | wrong password, inactive user, bad token, invalid key | N/A (auth is the boundary) |
| UserService | 21 | get, update, change password, deactivate | nonexistent, wrong password | owner-only, admin-only, self-only |
| MissionService | 11 | create, get, resolve, list, update, delete | nonexistent | owner filter |
| SessionService | 12 | create, get, ensure, cost, list | nonexistent, budget exceeded | user/mission scoping |

---

## 4. Phase 4 — Idempotency Keys (Medium)

> **Goal:** Add idempotency protection to critical mutating endpoints per P6.

### 4.1 Mechanism

Add an `Idempotency-Key` header (standard pattern, used by Stripe/GitHub):

1. Client sends `Idempotency-Key: <uuid>` header on POST requests.
2. Middleware checks Redis for the key:
   - **Key exists:** Return the cached response (no re-execution).
   - **Key absent:** Execute the request, cache the response in Redis with a TTL (24h).
3. Key format: `idempotency:{user_id}:{key_value}`.

### 4.2 Target Endpoints

| Endpoint | Why |
|----------|-----|
| `POST /missions` | Prevents duplicate mission creation on retry |
| `POST /sessions` | Prevents duplicate session creation |
| `POST /executions` | Prevents duplicate execution launches (expensive — triggers agent work) |
| `POST /agents/chat` | Prevents duplicate message sends |
| `POST /workflows/schedules` | Prevents duplicate schedule creation |

### 4.3 Implementation

1. Create `modules/backend/core/idempotency.py` — middleware/dependency that handles key checking and caching.
2. Use Redis with `SET NX EX` for atomic check-and-set.
3. Add `IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]` dependency.
4. Apply to target endpoints as an optional dependency (non-breaking — key is optional).

### 4.4 Implementation Notes

- Start with `POST /executions` — highest cost of duplicate execution.
- Idempotency is opt-in per endpoint (not blanket middleware) to avoid caching GET responses or non-critical POSTs.

---

## 5. Phase 5 — Minor Fixes (Low)

### 5.1 Temporal Config Default

**File:** `modules/backend/core/config_schema.py:310`

Remove the `localhost:7233` default from `server_url`. When `temporal.enabled` is true, require explicit configuration:

```python
# Before
server_url: str = "localhost:7233"

# After
server_url: str | None = None  # Required when temporal.enabled is true
```

Update the validator to fail on `None` when enabled.

### 5.2 SSE Token Security

Replace query-param token passing with one of:
- **Short-lived SSE tokens:** Backend issues a 30-second single-use token for SSE connections. Client exchanges JWT for SSE token, passes SSE token as query param. Limits exposure window.
- **Fetch + ReadableStream:** Replace `EventSource` with `fetch()` using `Authorization` header and manual stream parsing. Modern browsers support this.

**Recommendation:** Short-lived SSE tokens — less client-side complexity, works with all browsers.

---

## 6. Execution Order & Dependencies

```
Phase 1 (Layer Violations)     ← Do first — architectural integrity
  ├── 1.1 API endpoints        ← Independent
  ├── 1.2 Client modules       ← Independent
  └── 1.3 Prevention gate      ← After 1.1 + 1.2 are clean

Phase 2 (File Splits)          ← After Phase 1 (some files overlap)
  ├── 2.1 Backend splits       ← Independent per file
  └── 2.2 Frontend splits      ← Independent per file

Phase 3 (Service Tests)        ← Can start in parallel with Phase 2
  └── One service at a time    ← Sequential within phase

Phase 4 (Idempotency)          ← After Phase 1 (needs clean service layer)

Phase 5 (Minor Fixes)          ← Any time, no dependencies
```

**Estimated effort:** Phase 1 (~2 sessions), Phase 2 (~3 sessions), Phase 3 (~3 sessions), Phase 4 (~1 session), Phase 5 (~1 session).

---

## 7. Validation

After all phases:

1. `python scripts/check_layer_violations.py` returns 0
2. No Python file in `modules/` exceeds 1000 lines; none exceeds 600 lines
3. `pytest tests/unit/backend/services/ -v` passes with 50+ test cases
4. Pre-commit hook blocks any new layer violation
5. Existing tests still pass (`pytest tests/ -v`)
