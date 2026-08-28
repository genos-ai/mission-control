# TODO — Findings from SRS Extraction Audit (2026-05-10)

Findings discovered during deep codebase analysis for the SRS template (029).
Each item references the actual code and the specific issue.

---

## Reliability — Provider error taxonomy (2026-06-05)

Implemented `modules/backend/core/provider_errors.py` with a
provider-neutral hierarchy: `ProviderError` base + `QuotaExhaustedError`,
`RateLimitedError`, `TransientProviderError`, `ContractViolationError`
subclasses. Each subclass owns its `log_event`, `remediation`, and
`retry_policy` as class-level constants. Catch sites use the
`log_provider_error(logger, exc, **context)` helper so the structured-log
shape (provider, model, request_id, raw, remediation) is uniform across
the codebase.

Copilot-specific errors (`CopilotQuotaExhaustedError`,
`EmptyCopilotSessionError`) now inherit from the taxonomy so the retry
handler catches the abstract bases (`QuotaExhaustedError`,
`TransientProviderError`) — adding a new provider is now subclassing the
right base, not editing the retry handler.

Open follow-ups:

- [x] **Wire Anthropic / OpenAI / Foundry adapters into the taxonomy.**
  Each provider's adapter should catch its native SDK exceptions
  (`anthropic.RateLimitError`, `openai.APIStatusError`, etc.) and
  re-raise as the matching `ProviderError` subclass. Today only Copilot
  is wired up; an Anthropic 429 still propagates as a generic exception.
  — **Resolved (Plan 84, Phase 4.3):** `classify_provider_error()`
  (`core/exceptions.py`) classifies PydanticAI/Anthropic/OpenAI SDK
  errors into the taxonomy; `dispatch/retry_handler.py` calls it before
  falling back to generic-exception handling.

- [ ] **Audit the ~22 `agent.run()` call sites** outside the retry
  handler that have generic `except Exception` blocks (workflow_architect,
  gate_post_run, mission_control, software/quality, software/architecture,
  knowledge/officer, summarization, etc.). Most should adopt the
  `except ProviderError as exc: log_provider_error(...); <degrade>`
  pattern so quota / rate-limit / transient signals are visible
  everywhere, not just on the workflow path.

- [ ] **Implement actual backoff for `RateLimitedError`.** The retry
  handler currently treats it the same as `TransientProviderError`
  (immediate retry). When a provider adapter starts raising
  `RateLimitedError`, the handler should use the `retry_policy="backoff"`
  marker to apply exponential delay.

- [ ] **Investigate why Copilot sessions sometimes produce 0 tokens
  even when the account has quota.** First observed during rapid retries
  of the verify step (3 attempts in <5s, 2 produced empty responses).
  Now classified as `EmptyCopilotSessionError` and retried correctly,
  but the underlying GitHub Copilot SDK behavior is worth understanding.

---

## Code Size Violations

Files exceeding the 1,000-line hard limit (AGENTS.md rule: target ~400-500, max 1,000).

- [ ] `modules/backend/services/mission_plan_orchestrator.py` — **1,388 lines** (39% over limit). Highest-PageRank service in the codebase. Needs decomposition into focused submodules (dispatch prep, plan lifecycle, budget enforcement, etc.).
- [ ] `modules/backend/agents/mission/director/agent.py` — **1,291 lines** (29% over limit). Monolithic director agent. Extract tool fork handling, chat routing, and plan refinement into separate modules.
- [ ] `modules/backend/services/workflow_run_waves.py` — **1,101 lines** (10% over limit). Wave execution engine. Extract human input handling, condition evaluation dispatch, and notification logic.
- [ ] `admin.py` — **~1,300 lines**. Entry point CLI. Lower risk but still exceeds limit. Consider lazy-loading command groups from separate modules.

### Approaching Limits (monitor)

- `modules/clients/tui/services/service_bridge.py` — 893 lines
- `modules/backend/events/types.py` — 872 lines
- `modules/backend/agents/mission_control/dispatch/loop.py` — 834 lines
- `modules/backend/api/v1/endpoints/admin.py` — 791 lines
- `modules/backend/agents/mission_control/dispatch/research_loop.py` — 734 lines

---

## Security Gaps

### GatewayRateLimiter Not Wired

- [x] `modules/backend/gateway/security/rate_limiter.py` — `GatewayRateLimiter` exists with in-memory sliding window implementation but is **not integrated** into any production middleware or request path. Only referenced in unit tests. The `auth_rate_limit_enabled` feature flag exists in `features.yaml` but has no backend enforcement. — **Resolved (Plan 84, Phase 7.1):** wired into `RateLimitMiddleware` (`core/middleware.py`), enforced when `features.auth_rate_limit_enabled` is true.
- [x] Rate limiter field name mismatch: `security.yaml` defines `requests_per_minute` / `requests_per_hour` (via `ApiRateLimitSchema`), but `GatewayRateLimiter.check()` reads `messages_per_minute` / `messages_per_hour`. The `channel=="api"` path would not apply configured limits. — **Resolved (Plan 84, Phase 7.1):** `GatewayRateLimiter.check()` now reads `requests_per_minute`/`requests_per_hour` with a fallback to the old field names.

### API Key Scopes Defined But Unused

- [x] `modules/backend/models/api_key.py` — `ApiKey.scopes` field (JSON, nullable) is stored in the database but **never checked** during `AuthService.resolve_api_key()`. Either implement scope enforcement or remove the field to avoid false security assumptions. — **Resolved (Plan 84, Phase 7.2):** `resolve_api_key` attaches the resolved scopes; `require_scope()` (`core/dependencies.py`) enforces them on the admin router. Empty/NULL scopes remain full access of the owning user (documented, deliberate).

### Legacy Admin Key Backdoor

- [x] `modules/backend/core/dependencies.py` / `modules/backend/services/auth.py` — `resolve_legacy_key()` does constant-time compare against `settings.admin_api_key` and returns the **first admin user** from the database. If `ADMIN_API_KEY` env var leaks, it grants full admin access. Document the risk, add rotation guidance, or deprecate in favour of per-user API keys. — **Mitigated (Plan 84, Phase 7.3):** gated behind `features.legacy_admin_key_enabled` (default `false`); every successful use logs a WARNING. Not removed — kept as an explicit break-glass path.

### SSE Token Fail-Open

- [x] `modules/backend/api/v1/endpoints/auth.py` — `POST /sse-token` swallows Redis exceptions and still returns a token UUID even when Redis write fails. The SSE endpoint falls back to treating the (non-stored) token as a raw JWT, but the user receives a token that appears valid. Consider failing the request instead. — **Resolved:** the endpoint now raises `ExternalServiceError` when the Redis write fails instead of returning a token. Separately, the *read*-side fail-open in `_resolve_sse_token` (Redis error during token lookup) was closed in Plan 84 Phase 7.4.

---

## Layer Violations

### admin.py Direct Service Imports

- [ ] `admin.py` `admin migrate-planning-agent` command — directly imports `MissionRepository`, `MissionTeamService`, and `get_async_session`. Bypasses the API layer. Should delegate to a service method or admin API endpoint.
- [ ] `admin.py` `admin seed-workflows` command — directly imports `WorkflowDefinitionService` and `seed_workflows`. Same violation.

---

## Unused / Dead Code

### Exception Classes Never Raised

- [x] `modules/backend/core/exceptions.py` — the following exceptions are defined with error codes and HTTP handler mappings but have **no production `raise` sites** in the codebase:
  - `ExternalServiceError` (`SYS_EXTERNAL_SERVICE_ERROR`)
  - `RateLimitError` (`RATE_LIMITED`)
  - `ModelError` (`SYS_MODEL_ERROR`)
  - `ConfigurationError` (`SYS_CONFIGURATION_ERROR`)

  Either wire them into the appropriate failure paths or remove them to avoid confusion about error handling coverage. — **Resolved:** `ExternalServiceError` now has a production raise site (`api/v1/endpoints/auth.py`, SSE token issuance). `RateLimitError`, `ModelError`, and `ConfigurationError` have been removed from `exceptions.py`.

### Deprecated Adapters

- [x] `modules/backend/agents/adapters/code.py` — marked deprecated; re-exports from `modules.backend.tools`. Remove and update imports. — **Resolved:** file removed.
- [x] `modules/backend/agents/adapters/research.py` — same: deprecated re-exports. — **Resolved:** file removed.
- [x] `modules/backend/agents/adapters/filesystem.py` — same: deprecated re-exports. — **Resolved:** file removed.

### Branch Manager Unused

- [x] `modules/backend/services/branch_manager.py` — fully implemented (branch naming, commit messages, PR automation, cleanup) but **no other module imports it**. Either wire it into the dispatch loop for code-producing agents or document it as a future capability. — **Resolved:** file removed.

---

## Event System Inconsistencies

### Event Type Name Mismatch

- [ ] `config/settings/events.yaml` excludes `session.cost.update` from DB persistence, but the actual event type string in `modules/backend/events/types.py` is `session.cost.updated` (with trailing "d"). The YAML exclusion may not match, causing these high-volume events to be persisted unnecessarily.

### Docstring vs Implementation Contradiction

- [ ] `modules/backend/events/types.py` module docstring says session events are "not persisted by the event bus", but `modules/backend/events/bus.py` **does persist** mission-scoped events (all types not in the exclude list). Update the docstring to match the actual behaviour.

---

## Test Coverage Gaps

- [ ] Test-to-source ratio is ~0.35:1 (30k test lines covering 86k source lines). The following critical paths appear under-tested relative to their complexity and risk:
  - `agents/mission_control/dispatch/loop.py` (834 lines — DAG execution engine)
  - `agents/mission_control/dispatch/research_loop.py` (734 lines — research pipeline orchestration)
  - `agents/mission_control/helpers/agent_executor.py` (523 lines — agent invocation with cost tracking)
  - `services/mission_plan_orchestrator.py` (1,388 lines — plan lifecycle)
  - `services/workflow_run_waves.py` (1,101 lines — wave execution)
  - `agents/mission_control/gate_post_run.py` (523 lines — 8-branch supervisor decision matrix)

---

## Configuration / Documentation

### Missing YAML Header Comments

- [ ] Some `config/settings/*.yaml` files may lack the commented option reference at the top (per coding standards: "always add a commented list of all the options at the top of a yaml config file for easy reference"). Run compliance scanner rule `yaml_header_comment` to identify.

### events.yaml Stale Reference

- [ ] Verify and fix the `exclude_event_types` list in `config/settings/events.yaml` against actual event type strings in `modules/backend/events/types.py`.

---

## Container Execution Hardening (from NVIDIA/OpenShell study)

Ideas from studying [NVIDIA/OpenShell](https://github.com/NVIDIA/OpenShell) — a sandboxed agent runtime.
Decision: do NOT adopt OpenShell directly (requires gateway server, mTLS PKI, gRPC relay — more complex than our existing `ContainerBackend`).
Borrow the concepts instead.

- [ ] **Network containment via Docker network mode** — `ContainerBackend` already accepts `network_mode` in config. Pass a restricted Docker network (or `"none"`) at task creation time to block uncontrolled egress. Per-task policy: map allowed hosts to a Docker bridge network with explicit DNS allowlist.
- [ ] **Credential injection hardening** — currently API keys are passed as `env_vars` to `docker exec` (visible to any process in the container). Inject secrets only at container start (`docker run --env`) and drop them before handing off to the agent subprocess. Consider passing via a tmpfs-mounted secrets file instead.
- [ ] **Workflow chain documentation in AGENTS.md** — add a "Workflow Chains" section showing how plans flow end-to-end (research → plan doc → issue → build → PR). OpenShell's AGENTS.md is a good reference for this pattern.
- [ ] **Agent skills for Mission Control development** — add `.agents/skills/` with skills that use the human-gate pattern (`state:agent-ready` is human-only): `plan-from-issue`, `build-from-plan`. Mirror OpenShell's `triage-issue → build-from-issue` pipeline for our own plan execution flow.

---

## Live Agent Activity Visibility (CLI / Console)

While walking through the v1 workflow with `--gate manual`, when a task transitions to RUNNING the operator is **blind to what the agent is doing**. Tool calls, intermediate reasoning, token usage, cost accumulation, and progress are all happening in the backend but only visible by grepping `var/logs/system.jsonl`. The CLI `mc plan task <id>` shows post-hoc state but doesn't stream live activity.

The backend already emits rich events (`Copilot tool call`, `Tool call → PydanticAI`, `Tool result`, `Copilot request completed`) for every agent step — these need to surface to the operator in real time.

- [ ] **`mc plan task <id> --watch`** — open an SSE stream filtered to the given task's lifecycle events. Print: tool calls + arguments, tool results (summarised), token deltas, status changes, completion.
- [ ] **`mc agent watch <agent_name>`** — live tail of one agent's activity across whatever it's running (useful when debugging a specific agent).
- [ ] **Default `mc plan show` enriches RUNNING rows** with a one-liner like `[3 tool calls, 12.4k input tokens, 6s elapsed]` so static `mc plan show` snapshots also tell some story about active work.
- [ ] **Verify what `mc console monitor` already shows** — it may already cover some of this; confirm the gap before duplicating.

This isn't just polish — it's the difference between operator-controlled debugging (the whole point of `manual` mode) and "approve and pray."

---

## Async Run Endpoint Hardening (Plan 80h follow-up)

- [x] **Temporal-backed dispatch for workflow runs in interactive modes** — `modules/backend/api/v1/endpoints/missions_workflows.py` currently uses `asyncio.create_task` to fire-and-return when the gate mode is `manual` / `interactive` / `ai_assisted`. The background task dies if the backend process restarts (e.g. uvicorn `--reload` triggers, deploy, crash), orphaning any waiting dispatchers and leaving `workflow_runs.status='RUNNING'` rows stuck. Production-grade: route through `MissionRunWorkflow` (Plan 52) so durability survives process restarts. Marked in the endpoint code with a follow-up comment. — **Resolved (Plan 84, Phase 3.1):** `missions_workflows.py` routes through Temporal (`RunWorkflowWorkflow`); zero `asyncio.create_task` sites remain in that file.

- [ ] Three other endpoints still fire `asyncio.create_task` for background execution: `api/v1/endpoints/sessions.py:421` and `agents.py:218` (`_run_agent`) — deliberately not durable, per ADR-004's in-process chat path (`docs/02-architecture/004-adr-unified-async-architecture.md`); and `api/v1/endpoints/executions.py:333` (`_run_in_background`) — belongs to the legacy execution engine, excluded from Plan 84 pending Plan 71 convergence. Documented as deliberate exclusions in the Phase 3.1 commit message (`c7e9384`); not a Plan 84 gap, but flagged here so the completion checklist's "no asyncio.create_task in endpoints" gate reads correctly against the three remaining sites.

---

## Plan Version History

The plan board shows a version counter (e.g. v18) that increments on each refinement, but previous versions are not stored. There's no way to view what the plan looked like at v15 vs v18.

- [ ] **Backend: plan snapshot table** — create a `plan_snapshots` table that captures the full task list (as JSON or normalized rows) each time the plan version is bumped during refinement. Write the snapshot in the same transaction as the version increment.
- [ ] **Backend: history endpoint** — add `GET /missions/{id}/plan/history` returning a list of `{ version, snapshot_at, summary, task_count }` and `GET /missions/{id}/plan?version=N` to retrieve a specific snapshot.
- [ ] **Frontend: version dropdown** — replace the static `v{N}` badge on the plan top bar with a dropdown that lists available versions. Selecting a previous version renders the board in read-only mode with the historical task data.
