# Plan 63 — Thin CLI Client: Rewrite mc.py to Use API Only

**Version:** 1.0.0
**Date:** 2026-04-22
**Author:** Herman + Architecture Review
**Status:** Implemented
**Depends on:** Plan 62 (unified execution path), all existing API endpoints
**Unlocks:** True feature parity between CLI and web frontend, testable via the same e2e bench

---

## 0. Problem Statement

The CLI (`mc.py` + `modules/clients/cli/`) violates the platform's core principle: **"Clients must be as thin as possible — all business logic lives in `modules/backend/services/`."** (AGENTS.md §Critical Rules).

Currently the CLI has **85+ direct imports** from `modules.backend.services`, `modules.backend.repositories`, `modules.backend.core.database`, and even raw SQL queries. It constructs database sessions, instantiates service classes, calls service methods directly, and manages transactions. This means:

1. **The CLI and web frontend are not feature-equivalent** — the CLI bypasses the API layer, so bugs in the API layer are invisible to CLI users.
2. **The CLI cannot be deployed remotely** — it requires direct database access, not just an API URL.
3. **The e2e test bench can't verify CLI/API parity** — they go through different code paths.
4. **Security boundaries are bypassed** — no auth, no rate limiting, no request validation when the CLI calls services directly.

**The fix:** Rewrite every CLI command to call HTTP API endpoints. The CLI becomes: parse input → HTTP call → render response. Zero service imports, zero DB access.

---

## 1. Architecture After Rewrite

```
┌──────────────────────────────────────────────────────┐
│  mc.py CLI                                           │
│  ┌────────────────────────────────────────────────┐  │
│  │  Click commands (parse args + flags)           │  │
│  │          │                                     │  │
│  │          ▼                                     │  │
│  │  ApiClient (HTTP + auth + SSE)                 │  │
│  │          │                                     │  │
│  │          ▼                                     │  │
│  │  report.py (Rich rendering of API responses)   │  │
│  └────────────────────────────────────────────────┘  │
│                                                      │
│  Allowed imports:                                     │
│    modules.clients.cli.*     (own package)           │
│    modules.clients.common.*  (shared CLI utils)      │
│    httpx / click / rich      (3rd party)             │
│                                                      │
│  FORBIDDEN imports:                                   │
│    modules.backend.*         (services, repos, etc)  │
│    sqlalchemy / redis        (infrastructure)        │
└──────────────────────────────────────────────────────┘
          │ HTTP only
          ▼
┌──────────────────────────────────────────────────────┐
│  FastAPI Backend  (localhost:8100/api/v1)             │
│  ┌─────────────┐  ┌──────────┐  ┌────────────────┐  │
│  │ API Layer   │→ │ Services │→ │ Repositories   │  │
│  └─────────────┘  └──────────┘  └────────────────┘  │
└──────────────────────────────────────────────────────┘
```

### CLI ApiClient

A thin HTTP client that handles:
- Base URL configuration (`MC_API_URL` env var or `config/settings/application.yaml`)
- Authentication (JWT login with stored token, auto-refresh on 401)
- `ApiResponse` envelope unwrapping (reads `.data`, raises on `.error`)
- SSE streaming for chat and live execution display
- Timeout configuration

This client already partially exists in the frontend (`modules/frontend/src/lib/api.ts`). The Python equivalent is a simple `httpx` wrapper.

---

## 2. Existing API Coverage

The API surface is **comprehensive** — most endpoints the CLI needs already exist.

### Fully covered (CLI can switch today)

| CLI Command | API Endpoint | Status |
|-------------|-------------|--------|
| `mc mission create` | `POST /missions` | Exists |
| `mc mission list` | `GET /missions` | Exists |
| `mc mission use` | `PUT /auth/me/current-mission` | Exists |
| `mc mission info` | `GET /missions/{id}` | Exists |
| `mc mission delete` | `DELETE /missions/{id}` | Exists |
| `mc mission archive` | `PATCH /missions/{id}` (status=ARCHIVED) | Exists |
| `mc mission unarchive` | `PATCH /missions/{id}` (status=ACTIVE) | Exists |
| `mc mission set-gate` | `PATCH /missions/{id}/plan` (gate_mode) | Exists |
| `mc run <objective>` | `POST /missions/{id}/plan/run-objective` | Exists (Plan 62) |
| `mc status` | `GET /missions/{id}` + `GET /missions/{id}/plan` | Exists |
| `mc history` | `GET /executions?mission_id={id}` | Exists |
| `mc team list` | `GET /missions/{id}/team` | Exists |
| `mc context show` | `GET /missions/{id}/context` | Exists |
| `mc context history` | `GET /missions/{id}/context/history` | Exists |
| `mc intent show` | `GET /missions/{id}/intent` | Exists |
| `mc intent history` | `GET /missions/{id}/intent/history` | Exists |
| `mc intent set` | `POST /missions/{id}/intent` | Exists |
| `mc learnings list` | `GET /missions/{id}/learnings` | Exists |
| `mc learnings show` | `GET /missions/{id}/learnings/{id}` | Exists |
| `mc knowledge search` | `GET /knowledge/search` | Exists |
| `mc design` | `POST /missions/{id}/architect/chat` | Exists |

### Needs new endpoints

| CLI Command | What's missing | Proposed endpoint |
|-------------|---------------|-------------------|
| `mc chat` | Streaming chat with agent | `POST /agents/chat/stream` exists but may need mission context wiring |
| `mc run <workflow>` | Run named workflow | `POST /missions/{id}/workflows/{name}/run` exists |
| `mc retry` | Retry failed plan tasks | `POST /missions/{id}/plan/retry-failed` — NEW |
| `mc console monitor` | Live SSE event stream | `GET /streams/missions/{id}` exists |

### Chat endpoint analysis

`mc chat` is the most complex command. It currently:
1. Creates/resumes a session
2. Connects to Redis for SSE events
3. Calls `handle()` (the agent handler) directly
4. Streams response chunks to the terminal

The thin client version should:
1. `POST /sessions` or `GET /sessions?mission_id={id}&limit=1` to get/create session
2. `POST /agents/chat/stream` with SSE response — the endpoint already exists
3. Read SSE chunks and render them

---

## 3. Implementation Plan

### Phase 1 — ApiClient foundation (~2 hours)

Create `modules/clients/cli/api_client.py`:

- [ ] **1.1** `CliApiClient` class wrapping `httpx.AsyncClient`
  - Base URL from `MC_API_URL` env var (default: `http://localhost:8100/api/v1`)
  - `get()`, `post()`, `patch()`, `put()`, `delete()` methods
  - Automatic `ApiResponse` envelope unwrapping (return `.data`, raise on `.error`)
  - JSON error messages rendered as click errors
- [ ] **1.2** Auth flow
  - On first use: prompt for email/password, call `POST /auth/login`, store token in `~/.config/mission-control/token.json`
  - On 401: auto-refresh via `POST /auth/refresh`, retry original request
  - `mc login` command to explicitly authenticate
  - `mc logout` command to clear stored token
- [ ] **1.3** SSE streaming helper
  - `stream_sse(path)` async generator that yields parsed SSE events
  - Used by `mc chat` and `mc console monitor`
- [ ] **1.4** Mission context helper
  - `get_current_mission_id()` reads from stored user state (via `GET /auth/me` → `.current_mission_id`)
  - `mc mission use` sets via `PUT /auth/me/current-mission`
  - **Dependency chain:** `mc login` must run before `mc mission use` (needs auth token to call API). Make `mc login` the first command implemented. All other commands should auto-prompt for login if no stored token exists.

### Phase 2 — Rewrite simple commands (~3 hours)

Convert each command from service-direct to API-only. Start with commands that have straightforward 1:1 endpoint mappings.

- [ ] **2.1** `mc mission create` → `POST /missions`
- [ ] **2.2** `mc mission list` → `GET /missions`
- [ ] **2.3** `mc mission use` → `PUT /auth/me/current-mission`
- [ ] **2.4** `mc mission info` → `GET /missions/{id}`
- [ ] **2.5** `mc mission archive` → `PATCH /missions/{id}` with `{"status": "ARCHIVED"}`
- [ ] **2.6** `mc mission unarchive` → `PATCH /missions/{id}` with `{"status": "ACTIVE"}`
- [ ] **2.7** `mc mission delete` → `DELETE /missions/{id}`
- [ ] **2.8** `mc mission set-gate` → `PATCH /missions/{id}/plan` with `{"gate_mode": "..."}`
- [ ] **2.9** `mc team list` → `GET /missions/{id}/team`
- [ ] **2.10** `mc status` → `GET /missions/{id}` + `GET /missions/{id}/plan`
- [ ] **2.11** `mc history` → `GET /executions?mission_id={id}`
- [ ] **2.12** `mc context show` → `GET /missions/{id}/context`
- [ ] **2.13** `mc context history` → `GET /missions/{id}/context/history`
- [ ] **2.14** `mc intent show` → `GET /missions/{id}/intent`
- [ ] **2.15** `mc intent history` → `GET /missions/{id}/intent/history`
- [ ] **2.16** `mc intent set` → `POST /missions/{id}/intent`
- [ ] **2.17** `mc learnings list` → `GET /missions/{id}/learnings`
- [ ] **2.18** `mc learnings show` → `GET /missions/{id}/learnings/{id}`
- [ ] **2.19** `mc knowledge search` → `GET /knowledge/search`

### Phase 3 — Rewrite execution commands (~2 hours)

- [ ] **3.1** `mc run <objective>` → `POST /missions/{id}/plan/run-objective` with `async_dispatch=true`
  - Do NOT use `async_dispatch=false` — sync HTTP blocks for 60-300s and will timeout
  - After the POST returns `"dispatching"`, connect to `GET /streams/missions/{id}` (SSE) for live task progress events (`PlanStepStartedEvent`, `PlanStepCompletedEvent`)
  - Poll `GET /missions/{id}/plan` every 10s as a fallback until all tasks are terminal
  - Render live progress with Rich (same `LiveExecutionDisplay` approach, fed by SSE events instead of in-process event bus)
- [ ] **3.2** `mc run <workflow>` → detect workflow name, call `POST /missions/{id}/workflows/{name}/run`
- [ ] **3.3** `mc retry` → `POST /missions/{id}/plan/retry-failed` (NEW endpoint needed)
  - Endpoint calls `retry_task()` on each failed task then `dispatch_approved()`
- [ ] **3.4** `mc design` → `POST /missions/{id}/architect/chat` in loop

### Phase 4 — Rewrite chat (~3 hours)

The most complex rewrite. `mc chat` currently opens a direct connection to the agent handler and Redis.

- [ ] **4.1** Session management: `GET /sessions?mission_id={id}` to find existing, `POST /sessions` to create new
- [ ] **4.2** Message sending: `POST /agents/chat/stream` — returns SSE stream with response chunks
- [ ] **4.3** Live rendering: read SSE chunks, render with Rich (thinking indicators, tool calls, final response)
- [ ] **4.4** Thread resumption: `--new` flag creates new session, default resumes last
- [ ] **4.5** Agent targeting: `--agent` flag passed as parameter to chat endpoint

### Phase 5 — New API endpoints (~1 hour)

Create any missing endpoints discovered during rewrite:

- [ ] **5.1** `POST /missions/{id}/plan/retry-failed` — retries all failed tasks and dispatches
- [ ] **5.2** Any other gaps found during Phase 2-4

### Phase 6 — Cleanup and enforcement (~1 hour)

- [ ] **6.1** Add pre-commit rule: CLI files (`modules/clients/cli/`) must not import from `modules.backend` at all — no services, repositories, models, schemas, core, agents. Zero backend imports. This prevents transitive SQLAlchemy dependencies and ensures the CLI can run with only `httpx` + the API URL.
- [ ] **6.2** Update `scripts/code_rules_fast.py` with the new rule
- [ ] **6.3** Remove all dead imports from CLI files
- [ ] **6.4** Run the e2e test bench (`scripts/verify_unified_execution.py`) to verify parity

**Total effort:** ~16 hours

---

## 4. Critical Violations to Fix First

These are the worst offenders — direct DB access in the CLI:

| Severity | File | Line | What it does |
|----------|------|------|-------------|
| CRITICAL | `mc.py:655` | Imports `MissionLearningRepository` + `get_async_session` — raw repo access | Replace with `GET /missions/{id}/learnings/{id}` |
| CRITICAL | `mc_status.py:92` | Raw SQL: `SELECT data FROM mission_events WHERE...` | Replace with `GET /missions/{id}/plan` (status includes supervisor info) |
| CRITICAL | `mc_run.py:69` | `get_async_session()` + `MissionPlanService` + `db.commit()` | Replace with `POST /missions/{id}/plan/run-objective` |
| CRITICAL | `mc_chat.py:34` | `get_async_session()` + direct agent `handle()` call + Redis connection | Replace with `POST /agents/chat/stream` (SSE) |

---

## 5. What the CLI is Allowed to Import

After rewrite, CLI files may only import:

```python
# Own package
from modules.clients.cli.api_client import CliApiClient
from modules.clients.cli.report import render_*, get_console
from modules.clients.common.display import get_console

# 3rd party
import click
import httpx
from rich import ...
```

**FORBIDDEN — zero imports from modules.backend:**
```python
from modules.backend.*                # ← NEVER (any subpackage)
from sqlalchemy import *              # ← NEVER
from redis import *                   # ← NEVER
```

**Why no schema imports either:** Schemas import models (`modules.backend.schemas.mission_plan` imports `modules.backend.models.mission_plan`), which transitively pull in SQLAlchemy. The CLI should use plain strings for enum values (e.g., `"failed"` not `PlanTaskStatus.FAILED`) — this is what the API returns in JSON anyway.

---

## 6. Auth Strategy

The CLI needs to authenticate with the API. Two approaches:

### Option A: JWT token (recommended)
1. `mc login` → prompts email/password → `POST /auth/login` → stores token in `~/.config/mission-control/token.json`
2. Every subsequent command reads token from file and sends as `Authorization: Bearer <token>`
3. On 401, auto-refresh via `POST /auth/refresh`
4. `mc logout` deletes the token file

### Option B: API key (simpler)
1. User creates an API key via web UI or `mc login --api-key`
2. Stored in `~/.config/mission-control/api-key`
3. Sent as `X-API-Key` header on every request

**Recommendation:** Start with Option A (JWT) since the auth endpoints already exist and the frontend uses the same flow. Add API key support later as a convenience.

---

## 7. Chat Streaming Architecture

The `mc chat` REPL is the most complex command. After rewrite:

```
User types message
      │
      ▼
POST /agents/chat/stream
  Body: { mission_id, session_id, message, agent? }
  Response: SSE stream
      │
      ▼
CLI reads SSE events:
  event: thinking    → show "🧠 agent thinking"
  event: tool_call   → show "🔧 calling tool..."
  event: chunk       → append to response buffer
  event: complete    → show final response, cost, token count
  event: error       → show error message
```

The SSE stream endpoint (`POST /agents/chat/stream`) already exists. The CLI just needs to parse the SSE events and render them with Rich.

---

## 8. Configuration

The CLI needs to know the API base URL:

```yaml
# config/settings/application.yaml
server:
  host: "0.0.0.0"
  port: 8100

# CLI reads this OR uses MC_API_URL env var
# Default: http://localhost:8100/api/v1
```

For remote deployments:
```bash
export MC_API_URL=https://mission-control.example.com/api/v1
mc login
mc mission list
```

---

## 9. Testing

After rewrite, the CLI becomes fully testable via the e2e bench:

```bash
# Test CLI path (uses API under the hood)
python scripts/verify_unified_execution.py --cli-only --reset

# Test API path directly
python scripts/verify_unified_execution.py --api-only --reset

# Both — should produce identical DB state
python scripts/verify_unified_execution.py --reset
```

The parity section of the test bench verifies that CLI and API produce the same DB state because they now go through the same API endpoints.

---

## 10. Files Changed

### New files
- `modules/clients/cli/api_client.py` — HTTP client with auth, SSE, envelope unwrapping

### Rewritten files (every CLI handler)
- `modules/clients/cli/mc_run.py` — API calls instead of service calls
- `modules/clients/cli/mc_chat.py` — SSE streaming instead of direct agent handler
- `modules/clients/cli/mc_status.py` — API calls instead of service + raw SQL
- `modules/clients/cli/mission_cmds.py` — API calls instead of service calls
- `modules/clients/cli/execution_cmds.py` — API calls
- `modules/clients/cli/workflow_cmds.py` — API calls
- `modules/clients/cli/context.py` — API calls
- `modules/clients/cli/workshop_cmds.py` — API calls
- `modules/clients/cli/schedule_cmds.py` — API calls
- `modules/clients/cli/admin_cmds.py` — API calls
- `modules/clients/cli/catalog_cmds.py` — API calls
- `modules/clients/cli/agent.py` — API calls
- `modules/clients/cli/console_cmds.py` — API calls / SSE
- `mc.py` — remove inline service calls, delegate to handler modules

### New endpoints
- `POST /missions/{id}/plan/retry-failed` — retry all failed tasks

### Updated pre-commit rules
- `scripts/code_rules_fast.py` — new rule blocking service imports in CLI

---

## 11. Migration Strategy

The rewrite can be done incrementally — one command group at a time:

1. **Phase 1:** Build `CliApiClient` — no commands change yet
2. **Phase 2:** Rewrite `mission` commands (create, list, use, etc.) — lowest risk, most used
3. **Phase 3:** Rewrite `run` and `retry` — execution path
4. **Phase 4:** Rewrite `chat` and `design` — streaming, most complex
5. **Phase 5:** Rewrite remaining (status, history, context, knowledge, admin)
6. **Phase 6:** Enforce with pre-commit rule, run e2e bench

Each phase can be tested independently. The old code paths can coexist during migration (import the old handler if the new one isn't ready yet).

---

## 12. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Chat SSE streaming doesn't match CLI's current rich display | Medium | Medium | Phase 4 — test against current UX, match event types |
| API endpoint returns different shape than service call | Medium | Low | Check response schemas match CLI rendering expectations |
| Auth adds friction for local development | Medium | Medium | Auto-login with default dev credentials when `MC_API_URL` is localhost |
| Some admin operations don't have API endpoints | Low | Low | Phase 5 — create missing endpoints as discovered |
| Performance regression from HTTP overhead | Low | Low | Negligible — LLM calls are the bottleneck, not HTTP |

---

## 13. Non-Goals

- Rewriting `admin.py` (ops CLI) — separate effort, admin operations have different security model
- Changing the API layer or service layer — this plan only changes the CLI client
- Adding new CLI features — this is a rewrite for parity, not new functionality
- Changing the frontend — already thin, no changes needed
