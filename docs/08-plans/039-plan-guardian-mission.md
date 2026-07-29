# Guardian Mission: Autonomous Platform Self-Monitoring

**Version:** 1.0.0
**Date:** 2026-04-08
**Author:** Herman (Group CISO, Icarus) + Architecture Review
**Status:** Draft — ideation
**Target:** BFA Reference Architecture v3.6.0
**Codebase alignment:** v1.1.0 — validated against mission-control repository 2026-04-08

---

## 0. Summary

The **Guardian Mission** is a long-running, always-on `tier=platform` mission that uses the platform's own infrastructure to continuously monitor, diagnose, and remediate platform health issues — with graduated human oversight.

It is **event-driven** (reacts to platform events, not polling), starts with **human-in-the-loop for all actions**, and autonomously graduates trust per remediation pattern as confidence grows. It is the platform's first Level 5 (fully autonomous) mission.

### Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Trigger mechanism | Event-driven | React to platform events (error spikes, health degradation), not cron polling. Aligns with existing event bus. |
| Fix scope | All types (graduated) | Restarts, config changes, code patches, DB migrations — each at different trust levels. |
| Mission identity | Own dedicated mission | Auto-created at platform startup. Not user-managed. Always active. |
| Infinite loop prevention | Detection layer is deterministic code (P2) | Can't fail in the same way agents fail. |
| Budget | Per-execution ceiling + daily tracking in MCD | `Mission.budget_ceiling_usd` is a lifetime total cap (not daily). Guardian uses per-execution budgets (`$0.25/execution`) and tracks daily spend in the MCD `budget_tracking` section. `GuardianService` refuses new executions when MCD daily spend exceeds the configured daily ceiling. No model change needed. |
| Access control | `sysadmin` role only | Guardian mission, its history, events, and configuration are invisible and inaccessible to non-sysadmin users. New `SYSADMIN` role added above `ADMIN`. |

---

## 1. Codebase Alignment

### Existing Infrastructure (extend these)

| Plan Concept | Actual Location | What Exists | What to Add |
|-------------|----------------|-------------|-------------|
| Platform mission tier | `modules/backend/models/mission.py` → `MissionTier` | `user` and `platform` tiers exist. Platform missions require admin. | Guardian mission auto-creates as `tier=platform` at startup. **Do NOT change existing `admin` requirement for platform tier** — existing `platform.director` and `platform.health` remain admin-accessible. Instead, Guardian access is gated by `MissionTierMiddleware` checking the `__guardian__` mission name specifically. See Section 3.2. |
| User roles | `modules/backend/models/user.py` → `SystemRole` | Three roles: `VIEWER`, `USER`, `ADMIN`. | Add `SYSADMIN` above `ADMIN`. Guardian mission and all platform-tier operations require `sysadmin`. |
| Role checking | `modules/backend/core/dependencies.py` → `require_admin`, `AdminRole` | `require_admin` checks `has_role("admin")`. | New `require_sysadmin` dependency + `SysadminRole` type alias. |
| Mission list filtering | `modules/backend/api/v1/endpoints/missions.py:97` | Platform missions filtered out for non-admin users. | Filter platform missions for non-sysadmin users. Admins can see user missions but NOT Guardian/platform missions. |
| Gate system | `modules/backend/agents/mission_control/gate.py` | `NoOpGate`, `CliGateReviewer`, `LlmGateReviewer`, `ConfigurableGate` with per-gate-point routing and auto-continue rules. | Extend `ConfigurableGate._effective_mode()` to resolve mode from pattern trust level when `GateContext` includes a `pattern_id`. No new gate class needed. |
| Escalation chain | `modules/backend/agents/mission_control/escalation.py` | 4-level deterministic escalation with `RiskThresholds`. Rule-based, no LLM. | Extend `RiskThresholds` config schema with `platform_operations` dict mapping fix types to risk levels. No new code — config-driven via `mission_control.yaml`. |
| Scheduled tasks | `modules/backend/tasks/scheduled.py` | `hourly_health_check`, `daily_cleanup`, `metrics_aggregation`, `cleanup_stale_environments`. Taskiq + cron. | New `guardian_health_collect` task (collects health snapshot). Event-driven trigger layer (new). |
| Health check service | `modules/backend/services/health.py` → `HealthCheckService`, `HealthReport`, `ComponentStatus` | Structured health report with `.is_healthy` property. Used by `hourly_health_check`. Also `modules/backend/api/health.py` with `/health/ready` and `/health/detailed` endpoints. | Extend `HealthCheckService.check_readiness()` with: execution success rates, agent error rates, event bus throughput, pool utilization, log error rates. Guardian consumes `HealthReport` directly — no new health model needed. |
| Existing health agent | `config/agents/platform/health/agent.yaml` → `platform.health.agent` | Haiku model, platform tier, `required_role: admin`, tools: `scan_log_errors`, `validate_config`, `check_dependencies`, `check_file_structure`, `get_app_info`, `check_services`. | Extend with Guardian-specific tools (`query_execution_stats`, `query_pool_stats`). Do NOT create a new agent — reuse this one. **Keep `required_role: admin`** — admins still need health checks. Sysadmins pass the admin check (level 4 >= 3). New tools are read-only, harmless for admins. |
| Notification service | `modules/backend/services/run_notifier.py` → `RunNotifierService` | Multi-channel dispatch (Telegram, SSE). `notify_run_completed()`, `notify_run_failed()`, `notify_budget_warning()`. Also `modules/clients/telegram/services/notifications.py` → `NotificationService` with alert types + rate limiting. | Add `notify_anomaly_detected()` and `notify_remediation_result()` to `RunNotifierService`. Route to sysadmin-only channels. Do NOT create a new notification system. |
| Service accounts | `modules/backend/models/user.py` → `User.is_service_account` | Boolean field exists, used in APIs and TUI admin panel. | Guardian mission owned by a service account user with `sysadmin` role. Created at startup alongside the mission. |
| Role hierarchy config | `config/settings/security.yaml` → `roles` | Config-driven levels: `viewer: 1`, `user: 2`, `admin: 3`. `check_role_level()` in `core/security.py` compares levels. | Add `sysadmin: level: 4`. All existing `has_role("admin")` checks continue to work — sysadmin (level 4) passes admin (level 3) checks. |
| Agent config validator | `modules/backend/agents/config_schema.py:168` | Enforces `platform.* agents must set required_role: admin`. | Update validator to accept `required_role: admin` OR `required_role: sysadmin` for `platform.*` agents. Existing agents keep `admin`. New write-capable Guardian agents (`platform.diagnostics`, `platform.remediation`) use `sysadmin`. |
| Event bus (domain) | `modules/backend/events/broker.py` | FastStream Redis broker for domain events. Singleton, middleware-instrumented. **No consumers exist yet. No domain events are published to FastStream Streams — all current events are session-scoped Pub/Sub.** | **Prerequisite:** Publish domain events (`execution.completed`, `execution.failed`, `health.check.degraded`) from dispatch loop, execution service, and health checks to FastStream Streams. Then Guardian trigger subscribes to these streams. This is foundational infrastructure work. |
| Event bus (session) | `modules/backend/events/bus.py` → `SessionEventBus` | Redis Pub/Sub for real-time session events. Requires `session_id`. | Guardian session for streaming Guardian activity to TUI/frontend. Only used for in-execution events (remediation progress), not for pre-session events (anomaly detection). |
| Event types (session) | `modules/backend/events/types.py` | Session events: agent, user, approval, cost, plan events. All extend `SessionEvent` which requires `session_id`. | New `RemediationProposedEvent`, `RemediationAppliedEvent` as `SessionEvent` subclasses (these occur during an execution that has a session). |
| Event types (domain) | `modules/backend/events/schemas.py` → `EventEnvelope` | Domain event envelope with `event_type`, `payload`, `correlation_id`. Published via FastStream Streams. | New `PlatformHealthEvent`, `AnomalyDetectedEvent` as `EventEnvelope` payloads (NOT `SessionEvent` — these occur before any session exists). Published to FastStream Streams, consumed by Guardian trigger. |
| Mission service | `modules/backend/services/mission.py` | `create_mission()`, `set_gate_mode()`, `resolve_gate()` | New `ensure_guardian_mission()` — idempotent startup hook. |
| Execution environments | `modules/backend/services/execution_environment.py` | `ExecutionEnvironmentService` with `LocalBackend`, `ContainerBackend`, `WorktreeBackend` | Guardian remediations use `worktree` for code patches, `local` for config/restart operations. |
| Verification pipeline | `modules/backend/agents/mission_control/verification.py` | 3-tier: structural → deterministic → AI evaluation. | Verification checks for remediation outputs: "did the fix actually resolve the anomaly?" |
| Mission Context (MCD) | `modules/backend/services/mission_context.py` | JSON blob + version + size tracking. Dot-notation path access. | Guardian's MCD stores: known patterns, trust levels, remediation history, platform topology. |
| Agent catalog | `modules/backend/services/agent_catalog.py` | CRUD for global agent catalog. | New Guardian agents registered in catalog at startup alongside mission. |
| Execution persistence | `modules/backend/services/execution_persistence.py` | `MissionRecord`, `TaskExecution`, `TaskAttempt`, `MissionDecision` | Full audit trail for every Guardian remediation — who approved, what changed, did it work. |
| Dispatch loop | `modules/backend/agents/mission_control/dispatch/loop.py` | Layer-by-layer task orchestration with topological sort, gates, verification. | Guardian playbook steps are dispatched through the same loop. No special path. |

### What Does NOT Exist (create from scratch)

| Component | Target Path | Notes |
|-----------|-------------|-------|
| `GuardianService` | `modules/backend/services/guardian.py` | Lifecycle management: ensure mission exists, health collection, anomaly evaluation, remediation dispatch |
| `platform.diagnostics` agent | `config/agents/platform/diagnostics/agent.yaml` + `modules/backend/agents/platform/diagnostics/agent.py` | Root cause analysis using logs, traces, code reading |
| `platform.remediation` agent | `config/agents/platform/remediation/agent.yaml` + `modules/backend/agents/platform/remediation/agent.py` | Proposes and generates fixes (code patches, config changes, restart commands) |
| Anomaly detector | `modules/backend/services/guardian_detector.py` | Deterministic (P2). Threshold checks, rate-of-change, pattern matching. No LLM. |
| Pattern trust store | Part of Guardian MCD (`known_patterns` section) | Per-pattern trust levels that govern gate mode. **Constraint:** MCD has 20KB hard cap — implement pattern archival when > 20 active patterns. |
| Event-driven trigger | `modules/backend/events/consumers/guardian_trigger.py` | FastStream consumer that reacts to platform events and triggers Guardian execution |
| Guardian health tools | `modules/backend/agents/tools/system.py` (extend) | Add `query_execution_stats`, `query_pool_stats` tool implementations to existing `system.py` where all `platform.health.agent` tools live. Do NOT create a separate `platform_health.py` — follow existing pattern. |
| Guardian remediation tools | `modules/backend/agents/tools/platform_remediation.py` | Tool implementations: apply_config_change, restart_service, create_code_patch, run_tests |
| `ops.guardian` workflow template | `config/workflow_templates/ops/guardian.yaml` | COLLECT → DETECT → DIAGNOSE → PROPOSE → APPLY → VERIFY pipeline. **Note:** No `config/playbooks/` directory exists — playbooks are stored as workflow definitions in DB, loaded from `config/workflow_templates/`. Follow existing pattern. |
| Domain event publishers | `modules/backend/agents/mission_control/dispatch/loop.py`, `modules/backend/services/execution.py`, `modules/backend/tasks/scheduled.py` | **Prerequisite.** Publish `execution.completed`, `execution.failed`, `agent.error` domain events to FastStream Streams from dispatch loop, execution service, and agent executor. Currently nothing writes to these streams. |
| Domain event payloads | `modules/backend/events/schemas.py` (extend) | `PlatformHealthPayload`, `AnomalyDetectedPayload` as `BaseModel` classes (NOT `SessionEvent`). Published as `EventEnvelope` payloads to FastStream Streams. |
| Session event types | `modules/backend/events/types.py` (extend) | `RemediationProposedEvent`, `RemediationAppliedEvent` as `SessionEvent` subclasses. **Register in `EVENT_TYPE_MAP`.** |
| `SYSADMIN` role | `config/settings/security.yaml` | Add `sysadmin: level: 4` to roles. Also add enum value to `SystemRole` in `models/user.py`. |
| `require_sysadmin` dependency | `modules/backend/core/dependencies.py` | New FastAPI dependency that checks `has_role("sysadmin")`, rejects admin/user/viewer |
| `SysadminRole` type alias | `modules/backend/core/dependencies.py` | `SysadminRole = Annotated[User, Depends(require_sysadmin)]` |
| `MissionTierMiddleware` | `modules/backend/core/middleware.py` | Intercepts all mission-scoped requests. Returns 404 (not 403) for platform-tier missions accessed by non-sysadmin. Security-critical — implement in Phase 1 before any Guardian exposure. |

---

## 2. Architecture

### 2.1 Guardian as a Platform Mission

The Guardian is a first-class mission, not a background service:

```
Platform Startup
  └── ensure_guardian_mission()
        ├── If Guardian mission exists and ACTIVE → no-op
        ├── If Guardian mission exists and ARCHIVED → unarchive
        └── If no Guardian mission → create:
              name: "__guardian__"
              tier: platform
              owner_id: system service account (sysadmin role)
              gate_mode: interactive  (initial, graduates over time)
              description: "Platform self-monitoring and remediation"
              budget_ceiling_usd: 365.0 (lifetime, ~$1/day annualized)
              execution_environment: local (default), worktree (for code patches)
              brief: { known_patterns: [], platform_topology: {...} }
```

This means:
- Guardian is **invisible** to `admin`, `user`, and `viewer` roles — only `sysadmin` users can see it
- Guardian shows up in `mc mission list` only for sysadmin users
- Guardian history, events, and configuration are sysadmin-only
- Guardian costs tracked like any other mission (visible in sysadmin dashboards)
- Guardian uses the same dispatch loop, gates, verification, persistence

### 2.2 Event-Driven Trigger Architecture

```
FastStream Redis Streams (domain events — NEW, must be published first)
│
├── "execution.completed"  — published by dispatch loop on task completion
├── "execution.failed"     — published by dispatch loop on task failure
├── "agent.error"          — published by agent executor on unhandled exception
├── "platform.health"      — published by hourly_health_check scheduled task
│
│   NOTE: These streams do NOT exist today. Phase 1 must add publishing
│   to the dispatch loop, execution service, and health check task.
│
└── FastStream Consumer: guardian_trigger (consumer group: "guardian")
      │
      ├── Sliding Window (Redis sorted sets, configurable 60s)
      │   Persists across worker restarts. ZADD on each event,
      │   ZREMRANGEBYSCORE to prune expired entries.
      │
      ├── Anomaly Detector (deterministic, P2)
      │   ├── Threshold rules: error_rate > X in Y seconds
      │   ├── Rate-of-change: metric degrading over N samples
      │   ├── Pattern matching: known failure signatures
      │   └── Output: list[Anomaly] with severity + category
      │
      ├── Cooldown check (Redis key with TTL: guardian:cooldown:{anomaly_id})
      │
      ├── Daily budget check (read from Guardian MCD)
      │
      └── IF anomalies detected AND not in cooldown AND budget remaining:
            ├── Publish AnomalyDetectedPayload to "platform.anomaly" stream
            └── Trigger Guardian execution:
                  ExecutionService.create_adhoc_execution(
                      mission_id=guardian_mission_id,
                      objective=f"Investigate and remediate: {anomaly.summary}",
                      context={"anomalies": [...], "health_snapshot": {...}},
                      cost_ceiling_usd=0.25,  # per-execution budget
                  )
```

**Key design choices:**
1. The trigger and detector are **deterministic code** (P2), not agents. They can't hallucinate or fail in the same way LLM-based agents fail. This prevents infinite loops.
2. All trigger state (window, cooldown, active remediations) lives in **Redis**, not in-process memory. Worker restarts don't lose state.
3. Domain events use **FastStream Streams** (not SessionEventBus Pub/Sub) because they're platform-wide, not session-scoped, and don't require a `session_id`.

### 2.3 Guardian Execution Pipeline

Once triggered, the Guardian runs through the standard platform flow:

```
Guardian Mission (tier=platform, gate=per-pattern)
│
├── Step 1: COLLECT (platform.health.agent (existing))
│   ├── Tools: query_health, query_logs, query_execution_stats, query_pool_stats
│   ├── Input: { anomalies: [...] from trigger }
│   └── Output: HealthReport { services: {...}, metrics: {...}, errors: [...] }
│
├── Step 2: DIAGNOSE (platform.diagnostics agent)
│   ├── Tools: read_file, grep_code, query_execution_history, read_logs
│   ├── Input: { health_report, anomalies }
│   ├── Gate: NONE (read-only, no risk)
│   └── Output: Diagnosis {
│         root_cause: str,
│         affected_components: [...],
│         confidence: float,
│         matches_known_pattern: str | null,
│         proposed_approach: str
│       }
│
├── Step 3: PROPOSE (platform.remediation agent)
│   ├── Tools: generate_patch, generate_config_change, generate_restart_command
│   ├── Input: { diagnosis, health_report }
│   ├── Gate: PER-PATTERN (known pattern → check trust level, novel → interactive)
│   └── Output: Proposal {
│         fix_type: "code_patch" | "config_change" | "restart" | "migration",
│         changes: [...],
│         risk_assessment: str,
│         estimated_impact: str,
│         rollback_plan: str
│       }
│
├── Step 4: APPLY (code, not agent)
│   ├── If code_patch → create worktree, apply patch, run tests
│   ├── If config_change → update config, validate
│   ├── If restart → graceful restart via admin tooling
│   ├── Gate: PER-PATTERN (see trust graduation below)
│   └── Output: FixResult { applied: bool, test_results: {...}, errors: [...] }
│
├── Step 5: VERIFY (existing 3-tier verification)
│   ├── Tier 1: Structural — fix output has required fields
│   ├── Tier 2: Deterministic — re-run health checks, anomaly resolved?
│   ├── Tier 3: AI — was the fix appropriate? Any side effects?
│   └── Output: VerificationOutcome { passed: bool, details: [...] }
│
└── Step 6: REPORT
    ├── Update Guardian MCD: add/update known_pattern entry
    ├── Emit RemediationAppliedEvent
    ├── Notify via Telegram/Slack (existing notification service)
    └── If fix_type == "code_patch" → create PR for human review
```

### 2.4 Fix Types and Risk Hierarchy

| Fix Type | Risk | Default Gate | Graduation Speed | Execution Environment |
|----------|------|---|---|---|
| **Restart** (peripheral services only — NEVER backend/temporal/event worker) | Low | `ai_assisted` | Fast (3 successes) | `local` |
| **Config change** (YAML/env) | Low-Medium | `interactive` | Medium (5 successes) | `local` |
| **Code patch** (Python/TS) | Medium-High | `interactive` | Slow (10 successes) | `worktree` |
| **DB migration** | High | `interactive` (always) | Never auto-graduates | `local` (staging first) |

### 2.5 Autonomy Graduation (Pattern Trust)

The Guardian builds **per-pattern trust**, not global autonomy. Each remediation pattern has its own trust level stored in the Guardian's MCD:

```json
{
  "known_patterns": [
    {
      "pattern_id": "db-pool-exhaustion-sse",
      "description": "SSE endpoints holding DB sessions beyond request lifecycle",
      "detection_rule": {
        "metric": "db_pool_available",
        "operator": "<",
        "threshold": 3,
        "AND": { "metric": "active_sse_connections", "operator": ">", "threshold": 5 }
      },
      "fix_template": "refactor-session-scope",
      "fix_type": "code_patch",
      "trust_level": "interactive",
      "successful_remediations": 0,
      "failed_remediations": 0,
      "last_remediated": null,
      "graduation_threshold": 10,
      "created_at": "2026-04-08T00:00:00Z"
    }
  ]
}
```

**Trust graduation state machine:**

```
NEW PATTERN
  │
  └── interactive (human approves every step)
        │ after N successes with zero failures
        │ N = graduation_threshold (per fix_type)
        │
        └── ai_assisted (LLM recommends, human decides)
              │ after 2*N successes with ≤ 1 failure
              │
              └── autonomous (auto-remediated, human notified)
                    │ any failure
                    │
                    └── ai_assisted (demoted, requires re-graduation)
```

**Demotion rule:** Any failed remediation at `autonomous` level immediately demotes the pattern to `ai_assisted`. This ensures the system never silently breaks things.

### 2.6 Guardian MCD Structure

```json
{
  "version": 1,
  "identity": {
    "name": "__guardian__",
    "purpose": "Platform self-monitoring and autonomous remediation"
  },
  "platform_topology": {
    "services": ["backend", "frontend", "redis", "postgresql", "temporal", "event_worker", "task_worker"],
    "health_endpoints": { "backend": "/health/ready", "redis": "PING", "postgresql": "SELECT 1" },
    "log_locations": { "system": "var/logs/system.jsonl" }
  },
  "known_patterns": [],
  "active_anomalies": [],
  "guardrails": [
    "NEVER modify user data or user mission state",
    "NEVER force-push or rebase user branches",
    "NEVER change authentication/authorization config without human approval",
    "NEVER exceed daily budget ceiling",
    "DB migrations ALWAYS require human approval regardless of trust level",
    "Code patches ALWAYS create a PR — never merge directly",
    "NEVER restart backend, Temporal worker, or event worker (self-restart kills in-flight execution)"
  ]
}
```

---

## 3. Access Control: Sysadmin-Only

### 3.1 New `SYSADMIN` Role

The Guardian requires a new role **above** `ADMIN` in the role hierarchy:

```python
# modules/backend/models/user.py

class SystemRole(str, enum.Enum):
    VIEWER = "viewer"
    USER = "user"
    ADMIN = "admin"
    SYSADMIN = "sysadmin"   # NEW — platform operations, Guardian access
```

**Role hierarchy:** `SYSADMIN` > `ADMIN` > `USER` > `VIEWER`. The existing `has_role(minimum)` / `check_role_level()` pattern already supports ordered comparisons — add `SYSADMIN` at the top.

**Why not reuse `ADMIN`?** Admins manage users, missions, and agent catalogs. Sysadmins manage the platform itself — infrastructure, monitoring, remediation. Separation of duties: an admin cannot accidentally (or intentionally) interfere with platform self-healing.

### 3.2 Enforcement Points

**Scope clarification:** Existing platform missions (`platform.director`, `platform.health`) remain accessible to `admin` users. Only the Guardian mission (`__guardian__`) requires `sysadmin`. This avoids a breaking change to existing platform mission access.

The `MissionTierMiddleware` checks: if mission name is `__guardian__` AND user is not sysadmin → return 404. All other platform missions retain their existing `admin` requirement.

| Surface | Current Gate | New Gate | Implementation |
|---------|---|---|---|
| `POST /api/v1/missions` (create, name=`__guardian__`) | `admin` | `sysadmin` | `MissionTierMiddleware` — auto-created at startup, not via API. API rejects manual creation of `__guardian__`. |
| `GET /api/v1/missions` (list) | Filters platform for non-admin | Also filter `__guardian__` for non-sysadmin | Add name check alongside existing tier filter: admins see platform missions except `__guardian__`. |
| `GET /api/v1/missions/{id}` (detail) | No guardian check | Return 404 for `__guardian__` if not sysadmin | `MissionTierMiddleware` (cached lookup). |
| `GET /api/v1/missions/{id}/executions` | No guardian check | Return 404 for `__guardian__` if not sysadmin | Same middleware. |
| `GET /api/v1/agents/catalog` | Shows all agents | No change needed | Guardian agents are `platform.*` tier — already admin-only. Sysadmins are also admin (level 4 > level 3). |
| `GET /api/v1/streams/{session_id}` (SSE) | No mission-tier check | Reject if session belongs to `__guardian__` and user is not sysadmin | Add session→mission→name check. |
| `mc mission use __guardian__` | No guardian check on CLI | Resolve mission, check name, reject if not sysadmin | Add check in `mission_context.py`. |
| `mc chat` (when Guardian selected) | No guardian check | Reject if active mission is `__guardian__` and user is not sysadmin | Add check in chat entry. |
| TUI Guardian panel | N/A (does not exist yet) | Only render for sysadmin sessions | Gate at widget level. |
| Frontend Guardian dashboard | N/A (does not exist yet) | Only visible if authenticated user is sysadmin | Gate at route + API level. |

### 3.3 Middleware Approach

Rather than adding tier checks to every endpoint individually, add a **mission-tier middleware** that intercepts all mission-scoped requests:

```python
# modules/backend/core/middleware.py (extend)

class MissionTierMiddleware:
    """Reject non-sysadmin access to the Guardian mission.

    Intercepts any request that resolves to a mission_id. If the mission
    is __guardian__ and the authenticated user is not sysadmin, return 404.
    Returns 404 (not 403) to avoid leaking existence of Guardian mission.

    Performance: Uses an in-memory LRU cache (TTL 5 min) for
    mission_id → (name, tier) lookups. Mission name/tier essentially
    never changes, so a 5-minute cache eliminates repeated DB queries.
    Cache is bounded (max 256 entries) to prevent memory growth.
    """
```

**Key detail:** Return `404 Not Found`, not `403 Forbidden`. Non-sysadmin users should not know the Guardian mission exists at all.

### 3.4 Guardian Event Stream Isolation

Guardian session events (published via `SessionEventBus`) must only be delivered to sysadmin-authenticated subscribers:

1. **SSE endpoint** (`/api/v1/streams/{session_id}`): Before subscribing, resolve session → mission → tier. If platform-tier, require sysadmin.
2. **WebSocket** (if added): Same check on connection handshake.
3. **TUI event listener** (`modules/clients/tui/services/event_listener.py`): The TUI runs in-process (no HTTP auth), but the Guardian panel should only render if the TUI session is launched by a sysadmin user.

### 3.5 Notification Channel Separation

Guardian notifications (Telegram, Slack) must go to sysadmin-only channels, not the general notification channel:

```yaml
# config/settings/guardian.yaml (extend)

guardian:
  notifications:
    telegram_chat_id: "${GUARDIAN_TELEGRAM_CHAT_ID}"  # Separate from user notifications
    slack_channel: "#platform-ops"                     # Sysadmin-only Slack channel
    notify_on: [anomaly_detected, remediation_proposed, remediation_applied, remediation_failed]
```

---

## 4. New Platform Event Types

Guardian events use **two different transports** depending on whether a session exists:

### 4.1 Domain Events (pre-session, via FastStream Streams + EventEnvelope)

These fire in the trigger consumer before any Guardian execution/session exists. They are published as `EventEnvelope` payloads to FastStream Redis Streams, NOT via `SessionEventBus`.

```python
# Published via EventPublisher.publish(stream="platform.health", event=envelope)
# Payload schemas — not SessionEvent subclasses (no session_id required)

class PlatformHealthPayload(BaseModel):
    """Periodic platform health snapshot. Payload inside EventEnvelope."""
    overall_status: str  # healthy | degraded | critical
    checks: dict  # component -> {status, latency_ms, details}

class AnomalyDetectedPayload(BaseModel):
    """Anomaly detected by Guardian detector. Payload inside EventEnvelope."""
    anomaly_id: str
    severity: str  # low | medium | high | critical
    category: str  # health | performance | error_rate | cost | security
    component: str
    description: str
    metrics: dict  # evidence
```

### 4.2 Session Events (in-execution, via SessionEventBus)

These fire during a Guardian execution that has a session. They extend `SessionEvent` (require `session_id`). Register in `EVENT_TYPE_MAP` for deserialization.

```python
# In modules/backend/events/types.py (extend)

class RemediationProposedEvent(SessionEvent):
    """Guardian proposed a fix."""
    event_type: str = "platform.remediation.proposed"
    anomaly_id: str
    fix_type: str  # restart | config_change | code_patch | migration
    pattern_id: str | None
    trust_level: str
    requires_human: bool

class RemediationAppliedEvent(SessionEvent):
    """Guardian applied a fix."""
    event_type: str = "platform.remediation.applied"
    anomaly_id: str
    fix_type: str
    success: bool
    verification_passed: bool
    cost_usd: float
```

---

## 5. New Components

### 5.1 Guardian Service

```
modules/backend/services/guardian.py

GuardianService
├── ensure_guardian_mission() → str (mission_id)
│   Idempotent. Called at startup. Creates or finds __guardian__ mission.
│   Also ensures sysadmin service account exists as owner.
│
├── get_guardian_config() → GuardianConfig
│   Loads from config/settings/guardian.yaml
│   Budget, thresholds, graduation rules, guardrails.
│
├── get_pattern_trust(pattern_id: str) → TrustLevel
│   Reads from Guardian MCD. Returns current trust level.
│
├── record_remediation_outcome(pattern_id: str, success: bool) → TrustLevel
│   Updates pattern trust in MCD. Returns new trust level.
│   Handles graduation and demotion.
│
└── resolve_guardian_gate(pattern_id: str | None, fix_type: str) → GateReviewer
    If known pattern → gate based on trust level.
    If novel pattern → interactive (always).
    If fix_type == "migration" → interactive (always).

NOTE: Anomaly evaluation lives in AnomalyDetector (Section 5.3), NOT here.
GuardianService is lifecycle/config/trust management only. Detector is a
separate deterministic service (P2 separation of concerns).
```

### 5.2 Guardian Agents (Four-File Contract)

**Agent 1: `platform.health.agent` (EXISTING — extend, do not create)**

| File | Status | Change |
|------|--------|--------|
| `config/agents/platform/health/agent.yaml` | EXISTS | Add `query_execution_stats`, `query_pool_stats` tools. **Keep `required_role: admin`** — shared between admin health checks and Guardian collection. |
| `config/prompts/agents/platform/health/system.md` | EXISTS | Extend system prompt with Guardian health collection instructions. |
| `modules/backend/agents/platform/health/agent.py` | EXISTS | Register new tool functions. |
| Output schema in `modules/backend/agents/schemas.py` | EXTEND | Add `GuardianHealthReport` model (extends existing `HealthReport` from `services/health.py` with execution stats, error rates). |

**Agent 2: `platform.diagnostics` (NEW — `required_role: sysadmin`)**

| File | Purpose |
|------|---------|
| `config/agents/platform/diagnostics/agent.yaml` | model: sonnet (reasoning), `required_role: sysadmin`, tools: filesystem + logs + execution_history, scope: read-only |
| `config/prompts/agents/platform/diagnostics/system.md` | "You are a platform diagnostics specialist..." |
| `modules/backend/agents/platform/diagnostics/agent.py` | PydanticAI agent with diagnostic tools |
| Output schema | `Diagnosis` model |

**Agent 3: `platform.remediation` (NEW — `required_role: sysadmin`)**

| File | Purpose |
|------|---------|
| `config/agents/platform/remediation/agent.yaml` | model: opus (complex reasoning), `required_role: sysadmin`, tools: code + filesystem + config, scope: write to platform code only |
| `config/prompts/agents/platform/remediation/system.md` | "You are a platform remediation specialist..." |
| `modules/backend/agents/platform/remediation/agent.py` | PydanticAI agent with remediation tools |
| Output schema | `RemediationProposal` model |

**Agent role summary:**

| Agent | `required_role` | Why |
|-------|----------------|-----|
| `platform.health.agent` | `admin` | Read-only. Shared between admin health checks and Guardian. No breaking change. |
| `platform.diagnostics` | `sysadmin` | Reads logs, traces, code — platform internals that only sysadmins should access. |
| `platform.remediation` | `sysadmin` | Proposes code patches, config changes — write-capable, sysadmin-level power. |

### 5.3 Anomaly Detector (Deterministic — P2)

```
modules/backend/services/guardian_detector.py

AnomalyDetector
├── Rules engine (no LLM):
│   ├── ThresholdRule:    metric > X for Y seconds → anomaly
│   ├── RateOfChangeRule: metric degrading over N samples → anomaly
│   ├── PatternRule:      error signature matches known pattern → anomaly
│   ├── AbsenceRule:      expected heartbeat missing for Z seconds → anomaly
│   └── CompositeRule:    AND/OR combinations of the above
│
├── evaluate(health_snapshot: HealthSnapshot) → list[Anomaly]
│   Runs all active rules. Deduplicates. Scores severity.
│
└── Built-in rules (default, configurable via guardian.yaml):
    ├── db_pool_low:        db_pool_available < 3
    ├── redis_latency_high: redis_latency_ms > 100
    ├── error_rate_spike:   errors_per_minute > 10 (over 5 min window)
    ├── execution_failures: failed_executions / total > 0.3 (over 1 hour)
    ├── event_bus_backlog:  pending_events > 1000
    ├── agent_timeout_rate: timeouts / total > 0.2 (over 1 hour)
    └── budget_burn_rate:   daily_spend > 0.8 * daily_ceiling
```

### 5.4 Event-Driven Trigger (FastStream Consumer)

```
modules/backend/events/consumers/guardian_trigger.py

Subscribes to FastStream Redis Streams (consumer group: "guardian"):
├── "platform.health"      — health check results (from extended hourly_health_check)
├── "execution.completed"  — execution outcomes (NEW: publish from dispatch loop)
├── "execution.failed"     — execution failures (NEW: publish from dispatch loop)
├── "agent.error"          — agent exceptions (NEW: publish from agent executor)

NOTE: These streams do NOT exist yet. Phase 1 must add domain event
publishing to the dispatch loop, execution service, and health checks
before the Guardian trigger can consume them. See Section 1 "Event bus (domain)".

State management (survives worker restarts):
├── Redis sorted set "guardian:window:{rule_id}" — events in current window, scored by timestamp
├── Redis key "guardian:cooldown:{anomaly_id}" — TTL-based cooldown (SET EX 300)
├── Redis key "guardian:active:{anomaly_id}" — maps to execution_id (prevents duplicates)
│
├── On worker restart: window state persists in Redis, consumer group offset
│   tracked by Redis Streams — no events lost, no duplicates
└── ZADD + ZRANGEBYSCORE for sliding window; ZREMRANGEBYSCORE to prune expired entries

Flow:
1. On each event: ZADD to window sorted set, ZREMRANGEBYSCORE to prune expired
2. Run AnomalyDetector.evaluate() against current window data (ZRANGEBYSCORE)
3. If anomalies found AND no active cooldown (GET guardian:cooldown:{id}):
   a. Check daily budget in Guardian MCD (refuse if exceeded)
   b. SET guardian:active:{anomaly_id} → execution_id
   c. SET guardian:cooldown:{anomaly_id} EX 300
   d. Create adhoc execution on Guardian mission
```

### 5.5 Guardian Configuration

```yaml
# config/settings/guardian.yaml

guardian:
  enabled: true
  mission_name: "__guardian__"

  budget:
    # Mission.budget_ceiling_usd is a lifetime cap (set at mission creation).
    # Daily spend is tracked in Guardian MCD and enforced by GuardianService.
    daily_ceiling_usd: 1.00          # Soft limit — GuardianService refuses new executions past this
    per_execution_ceiling_usd: 0.25  # Hard limit — passed to ExecutionService.create_adhoc_execution()
    lifetime_ceiling_usd: 365.0      # Set on Mission.budget_ceiling_usd at creation

  trigger:
    accumulation_window_seconds: 60
    cooldown_seconds: 300  # Don't re-trigger same anomaly for 5 min
    max_concurrent_remediations: 2

  detection:
    rules:
      db_pool_low:
        metric: db_pool_available
        operator: "<"
        threshold: 3
        severity: high
      redis_latency_high:
        metric: redis_latency_ms
        operator: ">"
        threshold: 100
        severity: medium
      error_rate_spike:
        metric: errors_per_minute
        operator: ">"
        threshold: 10
        window_seconds: 300
        severity: high
      execution_failure_rate:
        metric: execution_failure_ratio
        operator: ">"
        threshold: 0.3
        window_seconds: 3600
        severity: high

  graduation:
    restart:
      threshold: 3          # Successes needed to graduate
    config_change:
      threshold: 5
    code_patch:
      threshold: 10
    migration:
      threshold: null        # Never auto-graduates

  guardrails:
    - "Never modify user data or user mission state"
    - "Never force-push or rebase user branches"
    - "Never change auth config without human approval"
    - "DB migrations always require human approval"
    - "Code patches always create a PR, never merge directly"
```

---

## 6. Implementation Phases

### Phase 1: Read-Only Monitor (low risk, high value)

**Goal:** Guardian collects health data, detects anomalies, notifies humans. Zero remediation.

**Build:**
1. `SystemRole.SYSADMIN` + `require_sysadmin` dependency + `MissionTierMiddleware` with LRU cache (access control foundation)
2. **Domain event publishing (prerequisite):** Publish `execution.completed`, `execution.failed`, `health.check.degraded` from dispatch loop, execution service, and health checks to FastStream Streams. This is the foundation the Guardian trigger consumes. Without this, the trigger has nothing to read.
3. `GuardianService.ensure_guardian_mission()` — auto-create at startup, owned by system service account. Budget: per-execution ceiling ($0.25) + daily spend tracking in MCD.
4. Extend existing `platform.health.agent` with Guardian health tools (`query_execution_stats`, `query_pool_stats`)
5. `AnomalyDetector` — deterministic rules engine
6. `PlatformHealthPayload`, `AnomalyDetectedPayload` domain event payloads (BaseModel, NOT SessionEvent)
7. Extend `hourly_health_check` to emit `PlatformHealthPayload` to FastStream
8. Guardian trigger consumer (FastStream, consumer group, Redis-backed sliding window state)
9. Add `notify_anomaly_detected()` to existing `RunNotifierService` — route to sysadmin-only Telegram channel

**Gate mode:** `off` (read-only, nothing to gate)
**Cost:** Near zero — `platform.health.agent` uses Haiku, detection is deterministic code

### Phase 2: Diagnosis (add intelligence)

**Goal:** When anomalies detected, diagnose root cause and present to human.

**Build:**
1. `platform.diagnostics` agent + diagnostic tools
2. `ops.guardian` workflow template: COLLECT → DETECT → DIAGNOSE → REPORT
3. Guardian execution pipeline (workflow dispatched through standard dispatch loop)
4. TUI/frontend panel for Guardian activity (sysadmin-only, hidden from other roles)

**Gate mode:** `off` for COLLECT/DETECT, `interactive` for accepting diagnosis recommendations
**Cost:** Low — diagnosis only triggers on actual anomalies (Sonnet, ~$0.05/diagnosis)

### Phase 3: Remediation (add agency)

**Goal:** Propose and apply fixes with human approval.

**Build:**
1. `platform.remediation` agent + remediation tools
2. Full pipeline: COLLECT → DETECT → DIAGNOSE → PROPOSE → APPLY → VERIFY
3. Worktree integration for code patches
4. PR creation for code changes
5. Verification step: re-check health after fix

**Gate mode:** `interactive` for all proposals and applications
**Cost:** Medium — remediation uses Opus (~$0.15/remediation), but rare

### Phase 4: Autonomy (build trust)

**Goal:** Known patterns auto-remediate. Novel issues escalate.

**Build:**
1. Pattern trust store in Guardian MCD
2. Extend `ConfigurableGate._effective_mode()` to resolve mode from pattern trust level in `GateContext`
3. Graduation/demotion logic in `GuardianService`
4. Sysadmin UI for trust level management (override, manual promote/demote)
5. Daily Guardian summary report (what was detected, what was fixed, what's pending)

**Gate mode:** Per-pattern (see Section 2.5)
**Cost:** Decreasing over time — autonomous patterns skip LLM gate review

---

## 7. Interaction with Existing Systems

### 7.1 How Sysadmins Interact with Guardian

**Access control:** Only users with `SystemRole.SYSADMIN` can see, select, or interact with the Guardian mission. All commands below fail with `403 Forbidden` for admin/user/viewer roles.

```
mc mission use __guardian__     # Select Guardian mission (sysadmin only)
mc status                       # See active anomalies, pending remediations
mc history                      # See past remediations with outcomes
mc chat                         # Talk to Guardian's Mission Director
                                # "What anomalies have you seen today?"
                                # "Show me the diagnosis for anomaly X"
                                # "I approve the proposed fix for Y"
mc console monitor              # Watch Guardian events in real-time
```

The Guardian uses the same CLI and TUI as any other mission. No special tooling needed — access is gated by role, not by UI.

**What non-sysadmin users see:** Nothing. The Guardian mission is filtered from all list endpoints, search results, and event streams. Platform-tier agents (`platform.*`) are hidden from the agent catalog for non-sysadmin users. The Guardian's session events are only delivered to sysadmin-authenticated channels.

### 7.2 How Guardian Interacts with Existing Services

| Guardian Action | Uses | Notes |
|---|---|---|
| Health collection | `check_database()`, `check_redis()` from `api/health.py` | Existing health checks, extended |
| Log analysis | Structured logs in `var/logs/system.jsonl` | Existing log infrastructure |
| Execution stats | `ExecutionPersistenceService` queries | Existing persistence layer |
| Fix application | `ExecutionEnvironmentService` (worktree) | Existing environment infrastructure |
| Verification | 3-tier verification pipeline | Existing verification |
| Notification | Telegram notification service | Existing notification |
| Audit trail | `MissionRecord`, `TaskExecution`, `MissionDecision` | Existing persistence |
| Context memory | `MissionContextManager` | Existing MCD system |

### 7.3 Guardian Guardrails (Hard Limits)

These are **never graduated** — they require human approval regardless of trust level:

1. **User data isolation:** Guardian can never read/modify user missions, executions, or data.
2. **Auth/security config:** Changes to authentication, authorization, or security settings always require human.
3. **DB migrations:** Schema changes always require human approval and staging verification.
4. **Force operations:** No force-push, force-kill, or destructive git operations.
5. **Budget override:** Guardian cannot increase its own budget ceiling.
6. **Self-modification:** Guardian cannot modify its own agent configs, prompts, or detection rules.
7. **No self-restart:** Guardian NEVER restarts its own host processes (backend, Temporal worker, event worker). If Guardian restarts the backend, it kills itself mid-execution — Temporal retries the activity from scratch, causing duplicate work and wasted budget. Guardian may only restart peripheral services (frontend, task workers) that don't host the Guardian process.

---

## 8. Preventing Infinite Loops

| Scenario | Prevention |
|---|---|
| Guardian agent errors → detected as anomaly → triggers Guardian → errors again | Cooldown window (300s). If same anomaly re-triggers within cooldown, escalate to human instead of re-running. |
| Guardian fix breaks something → new anomaly detected | Rollback detection: if anomaly appears within 5 min of a remediation, auto-rollback the fix and escalate to human. |
| Detection layer itself fails | Detection is deterministic code (P2), not an agent. It either runs or the process is dead. If process is dead, external monitoring (systemd/Docker health checks) handles it. |
| Cascading failures (fix A causes anomaly B) | Max concurrent remediations = 2 (configurable). If both slots are occupied, new anomalies queue for human review. |

---

## 9. Metrics & Observability

The Guardian reports on itself (all metrics visible to sysadmin only):

```
guardian.anomalies.detected_total       Counter by severity, category
guardian.anomalies.auto_remediated_total Counter by pattern_id
guardian.anomalies.escalated_total      Counter by reason
guardian.remediation.success_rate        Gauge (rolling 30 days)
guardian.remediation.mean_time_to_fix    Gauge (rolling 30 days)
guardian.patterns.trust_levels          Gauge by pattern_id, trust_level
guardian.budget.daily_spend_usd         Gauge
guardian.budget.remaining_usd           Gauge
```

---

## 10. Open Questions

1. **Should Guardian have its own dedicated session, or create a new session per remediation?** Recommendation: one long-lived session for the Guardian mission, with correlation_ids per remediation for grouping.

2. **How do we handle multi-service outages?** If Redis is down, the event bus is down, so the trigger can't fire. Fallback: the existing `hourly_health_check` scheduled task (Taskiq) detects degradation and creates a Guardian execution directly via `ExecutionService`, bypassing the event bus.

3. **Should the Guardian's known patterns be shareable across deployments?** If we run multiple Mission Control instances, patterns learned by one Guardian could be valuable to others. Future consideration — for now, per-instance MCD is sufficient.
