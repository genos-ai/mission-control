# TODO — Findings from SRS Extraction Audit (2026-05-10)

Findings discovered during deep codebase analysis for the SRS template (029).
Each item references the actual code and the specific issue.

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

- [ ] `modules/backend/gateway/security/rate_limiter.py` — `GatewayRateLimiter` exists with in-memory sliding window implementation but is **not integrated** into any production middleware or request path. Only referenced in unit tests. The `auth_rate_limit_enabled` feature flag exists in `features.yaml` but has no backend enforcement.
- [ ] Rate limiter field name mismatch: `security.yaml` defines `requests_per_minute` / `requests_per_hour` (via `ApiRateLimitSchema`), but `GatewayRateLimiter.check()` reads `messages_per_minute` / `messages_per_hour`. The `channel=="api"` path would not apply configured limits.

### API Key Scopes Defined But Unused

- [ ] `modules/backend/models/api_key.py` — `ApiKey.scopes` field (JSON, nullable) is stored in the database but **never checked** during `AuthService.resolve_api_key()`. Either implement scope enforcement or remove the field to avoid false security assumptions.

### Legacy Admin Key Backdoor

- [ ] `modules/backend/core/dependencies.py` / `modules/backend/services/auth.py` — `resolve_legacy_key()` does constant-time compare against `settings.admin_api_key` and returns the **first admin user** from the database. If `ADMIN_API_KEY` env var leaks, it grants full admin access. Document the risk, add rotation guidance, or deprecate in favour of per-user API keys.

### SSE Token Fail-Open

- [ ] `modules/backend/api/v1/endpoints/auth.py` — `POST /sse-token` swallows Redis exceptions and still returns a token UUID even when Redis write fails. The SSE endpoint falls back to treating the (non-stored) token as a raw JWT, but the user receives a token that appears valid. Consider failing the request instead.

---

## Layer Violations

### admin.py Direct Service Imports

- [ ] `admin.py` `admin migrate-planning-agent` command — directly imports `MissionRepository`, `MissionTeamService`, and `get_async_session`. Bypasses the API layer. Should delegate to a service method or admin API endpoint.
- [ ] `admin.py` `admin seed-workflows` command — directly imports `WorkflowDefinitionService` and `seed_workflows`. Same violation.

---

## Unused / Dead Code

### Exception Classes Never Raised

- [ ] `modules/backend/core/exceptions.py` — the following exceptions are defined with error codes and HTTP handler mappings but have **no production `raise` sites** in the codebase:
  - `ExternalServiceError` (`SYS_EXTERNAL_SERVICE_ERROR`)
  - `RateLimitError` (`RATE_LIMITED`)
  - `ModelError` (`SYS_MODEL_ERROR`)
  - `ConfigurationError` (`SYS_CONFIGURATION_ERROR`)

  Either wire them into the appropriate failure paths or remove them to avoid confusion about error handling coverage.

### Deprecated Adapters

- [ ] `modules/backend/agents/adapters/code.py` — marked deprecated; re-exports from `modules.backend.tools`. Remove and update imports.
- [ ] `modules/backend/agents/adapters/research.py` — same: deprecated re-exports.
- [ ] `modules/backend/agents/adapters/filesystem.py` — same: deprecated re-exports.

### Branch Manager Unused

- [ ] `modules/backend/services/branch_manager.py` — fully implemented (branch naming, commit messages, PR automation, cleanup) but **no other module imports it**. Either wire it into the dispatch loop for code-producing agents or document it as a future capability.

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

## Plan Version History

The plan board shows a version counter (e.g. v18) that increments on each refinement, but previous versions are not stored. There's no way to view what the plan looked like at v15 vs v18.

- [ ] **Backend: plan snapshot table** — create a `plan_snapshots` table that captures the full task list (as JSON or normalized rows) each time the plan version is bumped during refinement. Write the snapshot in the same transaction as the version increment.
- [ ] **Backend: history endpoint** — add `GET /missions/{id}/plan/history` returning a list of `{ version, snapshot_at, summary, task_count }` and `GET /missions/{id}/plan?version=N` to retrieve a specific snapshot.
- [ ] **Frontend: version dropdown** — replace the static `v{N}` badge on the plan top bar with a dropdown that lists available versions. Selecting a previous version renders the board in read-only mode with the historical task data.
