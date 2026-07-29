# Plan 78: Code Security Review Mission (SCAR → Mission Control)

## Status: Draft v3 — extends WASA P1 under `security.code.*` namespace (2026-05-22)

**Priority:** High
**Branch:** TBD — `feature/78-code-security-review-mission`
**Reference implementation:** `/Users/herman.young/development/security-code-review` (SCAR — Security Code AI Review).

**Dependencies:**
- **Plan 78a (Rename WASA P1 `webapp` → `code` namespace)** — must merge first; provides `security.code.{scanner,triage,reporter}` as the foundation
- Plan 47 (Agent Execution Isolation — host-side worktrees + Docker)
- Plan 65 (Tool Registry — capability-resolved scanner binaries)
- Plan 66 (WASA Spec — security taxonomy + ROE contract; **authoritative**)
- Plan 67 (WASA Phase 1 — Pydantic models + `tool_runner` + SARIF + scanner/triage/reporter agents). **This plan extends Plan 67. It does not modify any P1 behaviour; the only P1 change is the namespace rename in Plan 78a.**
- ~~Plan 73 (Knowledge Graph and Vector Upgrades)~~ — **dropped from this plan.** Vector-indexed similarity FP learning is a follow-up; this plan uses exact-match fingerprint suppression via `MissionContext`, no vector store needed.
- Plan 75 (Composable Workflows with Decision Nodes — `decision` / `sub_workflow` / `edges`)

**Revision notes:**
- v1 → v2 (2026-05-22): Quality review caught ~50% duplication of WASA Phase 1 infrastructure. v2 anchored to the shipped P1 code.
- v2 → v3 (2026-05-22): Recognised WASA P1 is not webapp-specific — it's generic code SAST mislabeled as `webapp`. Plan 78a now does the rename; this plan depends on it. `security.web.*` is reserved for future DAST/HTTP work. The new workflow extends the renamed `security.code-assessment.workflow.yaml` in place rather than building a sibling.

---

## Summary

Compose SCAR's distinctive features (holistic CWE pass, config review, run-over-run baseline) on top of the **already-shipped WASA Phase 1 code** (renamed to `security.code.*` per Plan 78a) to deliver a repeatable, container-isolated, mission-scoped code security review. Everything P1 ships — the scanner/triage/reporter agents, `security-assessment-worker:latest` image, `tool_runner`, SARIF utilities, Pydantic models, ROE enforcement, evidence manifest — is reused unchanged.

This plan delivers four things P1 does not:
1. **Holistic CWE pass** — a new `security.code.holistic` agent driven by a 26-CWE registry, with cross-file analysis.
2. **Config review pass** — a new `security.code.config_review` agent for misconfiguration findings.
3. **Mission shape** — persistent baseline, FP fingerprints, CWE coverage history; baseline-diff gate with optional human review.
4. **Egress-locked containers** — extension to `ContainerBackend` so SAST + LLM-using steps run with `network_mode: none` (no outbound network at all — LLM HTTP call originates from API process, not container). `acquire` runs with bridge + tool-layer URL ROE check. Hostname-allowlisting infrastructure deferred to a follow-up plan.

---

## Architectural decisions (recorded before design)

These are committed for v3; revisit in a follow-up if measurement contradicts them.

| Decision | Choice | Why |
|---|---|---|
| **Fork** | D — extend the renamed `security.code-assessment.workflow.yaml` in place, reusing the scanner/triage/reporter agents and `security-assessment-worker:latest` image | Plan 78a's rename collapses the "two workflows?" debate — there's one code-review workflow that grows new steps. No sibling workflow. |
| **Capability namespace** | New holistic + config-review agents land under `security.code.*` (post Plan 78a) | The rename in 78a makes this clean. `security.web.*` reserved for future DAST. |
| **Mission "family"** (informal) | No mission-family infrastructure exists in MC today. The "family" is just a naming convention + a default workflow attachment + a `MissionContext` keyspace. No new registry. | Code review cadence (pre-merge, weekly, on dep-bump) and consumers differ from pentest engagements, but that difference lives in the workflow YAML's `context:` defaults and the mission's name pattern — not in any taxonomy table. If formal family taxonomy is needed later, it's a separate plan. |
| **Container image** | Reuse `security-assessment-worker:latest` | No new binaries required for holistic/config-review (they are LLM-only steps). Trivy/Roslyn/etc. already in the worker image. Renaming the image is out of scope (see 78a). |
| **SAST orchestration** | Stay inside the existing `security.code.scanner` agent (one step, internal tool dispatch) | P1 ships this. Re-architecting to one workflow step per scanner is observable but a substantial change with no proven benefit yet. Deferred. |
| **Triage shape** | One-shot, as in P1 today | Per-finding fan-out (P17) is a follow-up plan with required measurement. Adding fan-out here doubles the P1 change footprint for unproven gain. |
| **Holistic shape** | Single `agent_step` that internally iterates the CWE registry and emits one `record_holistic_finding` tool call per finding | Sub-workflow per CWE would defeat per-session prompt caching (Anthropic cache is per-session). Single agent keeps the 26 checks in one cached session — SCAR's measured cost model relies on this. P17 compliance via tool calls per finding. |
| **Findings merge** | New `merge_findings` tool step between (triage, holistic, config-review) and reporter | Keeps the reporter agent's input contract (`triaged_findings: list`) unchanged. Reuse beats interface churn. |
| **Egress policy** | `network_mode: none` for scanner + LLM-using steps (no outbound network from container); `network_mode: bridge` for `acquire` with tool-layer URL ROE check | LLM HTTP call originates from API process, not container — so LLM-using containers don't need provider egress. `acquire` is the only container needing outbound network (git clone). Hostname-allowlisting (sidecar proxy) deferred to Plan 78b. |
| **CWE registry binding to runs** | Snapshot at workflow run start, stored in workflow input | YAML at workflow load time can drift across runs of a long-lived mission. Snapshot makes the run reproducible. |

---

## WASA Phase 1 reuse manifest

Explicit list of every existing function this plan invokes. Verifies no duplication.

| Concern | File | Symbol | Used by |
|---|---|---|---|
| SARIF merge | [modules/backend/agents/security/sarif.py:115](modules/backend/agents/security/sarif.py#L115) | `merge_sarif(paths, output_path) -> str` | `merge_findings` tool calls this |
| SARIF load | [modules/backend/agents/security/sarif.py:44](modules/backend/agents/security/sarif.py#L44) | `load_sarif(path)` | `merge_findings`, holistic agent |
| Tool subprocess + SARIF normalisation | [modules/backend/agents/security/tool_runner.py:219](modules/backend/agents/security/tool_runner.py#L219) | `run_security_tool(...)` | `security.code.scanner` (already wired) |
| Capability resolution | [modules/backend/agents/security/tool_runner.py:317](modules/backend/agents/security/tool_runner.py#L317) | `run_capability(...)` | scanner |
| Tool registry | [modules/backend/agents/security/tool_registry.py:240](modules/backend/agents/security/tool_registry.py#L240) | `SecurityToolRegistry` | scanner |
| Target surface detection | [modules/backend/agents/security/tool_registry.py:191](modules/backend/agents/security/tool_registry.py#L191) | `detect_surface(target_path) -> SurfaceDetectionResult` | scanner (already); holistic agent uses for CWE file selection |
| ROE target-path validation | [modules/backend/agents/security/roe.py:165](modules/backend/agents/security/roe.py#L165) | `validate_target_path(...)` | Used as a defensive check after clone (validates the resulting worktree path). Does NOT validate URLs — see `validate_target_url` below. |
| ROE target-URL validation | [modules/backend/agents/security/roe.py](modules/backend/agents/security/roe.py) (NEW function) | `validate_target_url(url: str, expected_target: str)` | **Extension to roe.py.** Validates a git URL against the mission's single `target_url` (one mission = one repo per the explicit out-of-scope item). Normalises both inputs (strip scheme, `.git` suffix, trailing slash, lowercase host), compares; fails loud on mismatch. `clone_repo` calls this FIRST, then clones. |
| Evidence integrity manifest | [modules/backend/agents/security/evidence.py:29](modules/backend/agents/security/evidence.py#L29) | `EvidenceManifest` | `store-artifacts` step hashes via this |
| Security models | [modules/backend/agents/security/models.py](modules/backend/agents/security/models.py) | `Finding`, `TriageVerdict`, `SecurityAssessmentReport`, `AssessmentState` (414 lines) | All new agents/tools use these types as-is |
| Container backend | [modules/backend/services/container_backend.py](modules/backend/services/container_backend.py) | `ContainerBackend.create(...)` | All container steps. Extended with `egress_allowlist` field (only addition). |
| Container worker image | `security-assessment-worker:latest` | (Docker registry) | All container steps reuse |
| Existing scanner agent | [modules/backend/agents/security/code/scanner/agent.py](modules/backend/agents/security/code/scanner/agent.py) | `create_agent()` | Used in the new workflow's `scan` step — unchanged |
| Existing triage agent | [modules/backend/agents/security/code/triage/agent.py](modules/backend/agents/security/code/triage/agent.py) | `create_agent()` | Used in `triage` step — unchanged |
| Existing reporter agent | [modules/backend/agents/security/code/reporter/agent.py](modules/backend/agents/security/code/reporter/agent.py) | `create_agent()` | Used in `report` step — unchanged |
| Workflow step types | [modules/backend/schemas/workflow.py](modules/backend/schemas/workflow.py) | `WorkflowStepSchema` with `environment`, `container_image`, `extra_volumes`, `network_mode`, `condition` | Workflow YAML uses these |
| Decision/edges/sub-workflow | Plan 75 | `decision_config`, edge labels, `_branch` routing | mode-gate, baseline-diff |
| `store_artifact` | [modules/backend/tools/store_artifact.py](modules/backend/tools/store_artifact.py) | tool | store-artifacts step |
| `store_learning` | [modules/backend/tools/store_learning.py](modules/backend/tools/store_learning.py) | tool | store-learnings step |
| `update_context` | [modules/backend/tools/update_context.py](modules/backend/tools/update_context.py) | tool | `update_security_baseline` may delegate to this for context writes |
| Cost middleware | [modules/backend/agents/mission_control/cost.py](modules/backend/agents/mission_control/cost.py) | middleware | Per-session budget enforcement (no per-step branch needed) |
| MCD update mechanism | [modules/backend/services/mission_context.py:229](modules/backend/services/mission_context.py#L229) | `MissionContextManager.apply_updates(mission_id, updates=[{op, path, value, reason}])` | `update_security_baseline` calls this — JSON-Patch ops on the MCD |
| MCD update tool (single-field) | [modules/backend/tools/update_context.py](modules/backend/tools/update_context.py) | `update_context(mission_id, path, value, reason)` | Reference pattern for thin wrapper tools that write to MCD; `update_security_baseline` follows the same shape |
| Provider models | [modules/backend/core/copilot_model.py](modules/backend/core/copilot_model.py), Anthropic, Claude SDK adapters | model factory | LLM steps |
| Existing WASA workflow (extended in place by this plan) | [config/workflow_templates/security.code-assessment.workflow.yaml](config/workflow_templates/security.code-assessment.workflow.yaml) | YAML | Adds new steps (mode-gate, holistic, config-review, merge-findings, baseline-diff, human-gate, store-artifacts, store-learnings, update-baseline); existing `scan → triage → report` chain unchanged |
| Existing WASA prompts (reused) | [config/prompts/agents/security/code/scanner/system.md](config/prompts/agents/security/code/scanner/system.md), `triage/system.md`, `reporter/system.md` | prompts | Unchanged |

---

## Problem statement

We have three things that don't yet connect:

1. **SCAR** runs a 5-pass code-security review (Inventory → SAST → Triage → Holistic CWE → Config Review → Merge) as a CLI on a developer machine. Strong output (SARIF + CWE-tagged findings) but no scheduling, no gating, no state, no replay, no multi-channel visibility.
2. **WASA Phase 1** ships the SAST + Triage + Report shape inside Mission Control, in containers, with full ROE/evidence/Pydantic-model rigour. But it has no holistic CWE pass, no config review pass, and no run-over-run state.
3. **Plan 75 composable workflows** just shipped — decision nodes, edges, sub-workflows. Nothing yet exercises it on a real, long-running, repeatable workload.

The gap: a **mission-scoped, repeatable code security review** that adds SCAR's holistic CWE pass and config review pass to the WASA P1 foundation, with persistent baseline and FP suppression across runs.

### Why a mission, not a one-shot

A code security review of `repo X` happens on a cadence — pre-merge, weekly, on dependency bumps, on release. Each run wants to know what the previous run said. Confirmed FPs, accepted risks, and CWE coverage trends accumulate over time. SCAR cannot remember; missions can.

### Why containers from the start

SAST tools execute against untrusted code. Running them in the API process or unsandboxed worktree is a day-one security hole. WASA P1 already runs scanner/triage/reporter in containers via `environment: container` + `security-assessment-worker:latest`. This plan adds an **egress-locked default**: scanner + LLM-using containers get `network_mode: none` (no outbound network at all — verified that LLM HTTP calls originate from the API process via the model adapter, not from the container). Only `acquire` needs outbound network (to git-clone), and it pairs `network_mode: bridge` with a tool-layer URL ROE check.

---

## Design

### Mission shape

| Concept | Mapped to |
|---|---|
| User-facing unit | A mission named "Code Security Review — `{repo}`", attached to `security.code-assessment.workflow`. Created once per codebase. No mission-family infrastructure; the naming convention + workflow attachment is the "family". |
| Per-run unit | Session + `workflow_run` of `security.code-assessment.workflow`. |
| Persistent context | `MissionContext.context_data["security_code_review"]` — single top-level MCD key. Pydantic schema below; validation at tool/service layer (model stores `dict[str, Any]`). |
| Run-over-run intelligence | `SecurityMissionState.baseline.findings` for exact-match fingerprint suppression (within MissionContext); `scanner_runtime_baselines` for per-tool runtime stats. Similarity-based FP suggestions deferred to a follow-up plan. |
| Per-run output | `MissionArtifact` rows: merged SARIF, full markdown, summary markdown, JSON export, CSV export, triage audit trail. |
| Cost ceiling | Mission-level USD ceiling + per-run ceiling. Enforced by existing cost middleware. |
| Authorisation | ROE on mission; `validate_target_path()` from `agents/security/roe.py` enforces at workflow entry. |

### `MissionContext` keyspace (committed Pydantic schema)

**Storage and enforcement layer.** The `MissionContext` model stores `context_data: dict[str, Any]` as a JSON column (verified in [models/mission_context.py:45](modules/backend/models/mission_context.py#L45)). There is no model-level schema enforcement. The Pydantic schema below is enforced at the **tool and service layer** by:

- `update_security_baseline` tool — validates inputs against `SecurityMissionState` before calling `MissionContextManager.apply_updates(...)`.
- A `SecurityMissionStateReader` helper (in `services/security_mission_state.py`, new) that wraps `context_data["security_code_review"]` → `SecurityMissionState` on read; raises if the key is missing or malformed.
- No Alembic migration on the MCD; existing missions without a `security_code_review` key continue to work — the reader returns `None` and the workflow treats it as "first run".

The security namespace lives at **`context_data["security_code_review"]`** — a single top-level key inside the existing MCD JSON. Sibling to whatever other top-level keys the MCD uses today; verify during Phase 1 that no collision exists.



```python
# modules/backend/schemas/security_mission_state.py
class SecurityCodeReviewBaseline(BaseModel):
    """Accepted findings carried forward across runs."""
    findings: list[BaselineFinding]
    last_updated_run_id: UUID
    schema_version: int = 1

class BaselineFinding(BaseModel):
    fingerprint: str  # sha256(rule_id + normalized_file_path + sliding_window_hash)
    rule_id: str
    cwe: str | None
    severity: SeverityLevel
    accepted_at: datetime
    accepted_by: UUID  # users.id
    rationale: str

class SecurityCodeReviewCoverageHistory(BaseModel):
    """Per-run CWE coverage stats; rolling N most recent."""
    runs: list[CoverageEntry]
    max_runs_retained: int = 20

class SecurityCodeReviewConfig(BaseModel):
    """User-set config that persists on the mission."""
    target_url: str
    default_ref: str
    allowed_refs: list[str]
    triage_min_score: float = 0.20
    fp_confidence_threshold: float = 0.85
    escalate_on_urgent: bool = True
    baseline_diff_threshold: int = 1
    cwe_subset: list[str] | None = None  # None = all 26
    provider_models: ProviderModelMatrix  # triage/holistic/config/reporter

class SecurityMissionState(BaseModel):
    """Top-level state for a security.code-review mission's MissionContext row."""
    config: SecurityCodeReviewConfig
    baseline: SecurityCodeReviewBaseline | None = None
    coverage_history: SecurityCodeReviewCoverageHistory | None = None
    scanner_runtime_baselines: dict[str, ScannerRuntimeStats] = Field(default_factory=dict)
```

All `MissionContext` reads for security missions go through `SecurityMissionStateReader`. All writes go through `update_security_baseline` (for the baseline) or `MissionContextManager.apply_updates` directly (for ad-hoc field updates from the workflow — same pattern as the existing `update_context` tool). Free-form dict keys inside `security_code_review` are not allowed; the schema is closed (`extra="forbid"` on the Pydantic models).

### `update_security_baseline` concurrency & semantics

Verified facts about [`MissionContextManager.apply_updates`](modules/backend/services/mission_context.py#L229):

- It uses optimistic concurrency on `MissionContext.version`. On version conflict it returns `(current_version, ["Version conflict — MCD was updated concurrently"])` — **it does not retry internally**. The caller owns the retry loop.
- `op: "replace"` fails when the path doesn't exist (`"Path not found for replace"`). It also reports identical-value writes as `"No-op replace (value unchanged)"` in the errors list.
- `op: "add"` always succeeds — upserts (creates the path if missing, overwrites if present). This is the right operation for baseline writes.

Required wrapper algorithm:

```python
async def update_security_baseline(
    mission_id: str,
    run_id: str,
    new_baseline: SecurityCodeReviewBaseline,
    *,
    max_retries: int = 3,
) -> str:
    """Idempotent baseline write with OCC retry."""
    new_baseline_dict = new_baseline.model_dump(mode="json")
    benign_errors = {"No-op replace (value unchanged):", }

    for attempt in range(max_retries):
        # Read current state via SecurityMissionStateReader to honour the schema.
        current_state = await reader.read(mission_id)

        # Idempotency: if this run already wrote a baseline, return early.
        if current_state and current_state.baseline and \
           current_state.baseline.last_updated_run_id == UUID(run_id):
            return f"Baseline already written by run {run_id} (idempotent skip)"

        async with MissionContextManager.factory() as mgr:
            new_version, errors = await mgr.apply_updates(
                mission_id,
                updates=[{
                    "op": "add",                                       # B2 fix: add upserts; replace fails on first run
                    "path": "security_code_review.baseline",
                    "value": new_baseline_dict,
                    "reason": f"baseline update from run {run_id}",
                }],
                agent_id=f"workflow:security.code-assessment:run-{run_id}",  # S4: explicit audit attribution
            )

        # S1: distinguish benign "no-op" reports from real errors.
        real_errors = [e for e in errors if not any(e.startswith(b) for b in benign_errors)]
        version_conflict = any("Version conflict" in e for e in real_errors)

        if not real_errors:
            return f"Baseline updated at security_code_review.baseline (MCD v{new_version})"

        if version_conflict and attempt < max_retries - 1:
            # B3: caller-side retry on OCC conflict. Re-read on next loop iteration.
            await asyncio.sleep(0.05 * (2 ** attempt))   # small backoff
            continue

        raise BaselineUpdateError(
            f"Baseline write failed after {attempt + 1} attempts: {real_errors}"
        )

    raise BaselineUpdateError(f"Baseline write lost OCC race after {max_retries} attempts")
```

Key properties (verified against the apply_updates implementation):
- **B2:** `op: "add"` — upserts, never fails on missing path. Works for first-run and subsequent runs.
- **B3:** Caller-side retry loop; `apply_updates` does not retry. Bounded at 3 attempts with exponential backoff.
- **S1:** "No-op replace" is filtered out of the errors list — treated as success.
- **S4:** `agent_id` is explicit (`"workflow:security.code-assessment:run-{run_id}"`) for audit-trail attribution.
- **Idempotency on `(mission_id, run_id)`** via a pre-read check on `last_updated_run_id`. A retry of the same run (Temporal replay) is a no-op.

Test plan (in addition to the integration tests already listed):
- First run on a fresh mission writes baseline successfully (B2 regression — would have failed with `op: "replace"`).
- Second run with identical findings is treated as success (S1 regression — no-op replace is filtered).
- Two simulated concurrent writes: one succeeds first try, the other succeeds after one retry (B3 regression).
- A Temporal replay of the same run (same `run_id`) is a no-op early return (idempotency regression).

### Workflow-engine skip semantics (foundation for the DAG below)

**Verified:** [condition_evaluator.py:283](modules/backend/services/condition_evaluator.py#L283) `_resolve_ref(path, completed_outcomes, workflow_context)` returns `None` when a referenced step is missing from `completed_outcomes` (i.e., was skipped by decision routing). This is the foundation on which mode-gate routing works in this workflow:

- In `mode=sast`: triage / holistic / config-review / merge-findings's triage input are all skipped. `merge_findings`'s `triaged_findings` arg resolves to `None`. Tool treats `None` as empty list. Workflow proceeds.
- In `mode=sast-triage`: holistic / config-review skipped. `holistic_findings` and `config_findings` resolve to `None`. Same handling.
- In `mode=full`: all upstream sources present.

Every downstream step that consumes a potentially-skipped upstream output MUST handle `None` gracefully. The integration tests in Phase 6 exercise all three modes end-to-end to lock this in.

### Workflow DAG: `security.code-assessment.workflow`

```
[acquire] ── tool_call (container, egress=git-only) ───► workspace_path
    │   (clone_repo → validate_target_url → shallow clone → rm -rf .git)
    ▼
[scan] ── agent_step: security.code.scanner (container, egress=none) ──► sarif_path
    │   (unchanged from WASA P1 — runs SAST internally, emits merged SARIF)
    ▼
[mode-gate] ── decision (rule, on @context.mode) ─────────────────────►
    │
    ├── edge: "sast" ──────────────► [merge-findings]
    │
    └── edge: "sast-triage" | "full"
            │
            ▼
        [triage] ── agent_step: security.code.triage (container, egress=LLM-only)
            │   (unchanged from WASA P1 — one-shot triage, emits triaged_findings)
            ▼
        [mode-gate-2] ── decision (rule, on @context.mode) ────────────►
            │
            ├── edge: "sast-triage" ──► [merge-findings]
            │
            └── edge: "full"
                    │
                    ├──► [holistic] ── agent_step: security.code.holistic (NEW; container)
                    │       (internal CWE iteration; emits record_holistic_finding per finding)
                    │
                    └──► [config-review] ── agent_step: security.code.config_review (NEW; container)
                            (emits findings list)
                            │
                            ▼ (both join into merge-findings)
                       ┌────────────┐
                       ▼            ▼
                [merge-findings] ── tool_call ──► unified findings list
                       │
                       ▼
                [report] ── agent_step: security.code.reporter (unchanged)
                       │
                       ▼
                [baseline-diff] ── decision (rule)
                       │   evaluates count(new URGENT findings vs MissionContext.baseline)
                       │
                       ├── edge: "no-new-urgent" ─► [store-artifacts]
                       └── edge: "new-urgent" ────► [human-gate] ── human_input
                                                          │
                                                          ▼
                                                  [store-artifacts] ── tool_call × 5
                                                          │
                                                          ▼
                                                  [store-learnings] ── tool_call
                                                          │
                                                          ▼
                                                  [update-baseline] ── tool_call
```

The reporter agent ([code/reporter/agent.py](modules/backend/agents/security/code/reporter/agent.py)) is unchanged — `merge-findings` produces the unified `triaged_findings` list it already expects.

### Per-step contract

| Step id | Type | Capability / tool | Container | Egress | Inputs | Outputs |
|---|---|---|---|---|---|---|
| `acquire` | `tool_call` (requires wave-engine extension — see below) | `clone_repo` (new) | `security-assessment-worker:latest` | `bridge` + URL-layer ROE check | `@context.target_url`, `@context.ref` | `workspace_path` |
| `scan` | `agent_step` | `security.code.scanner` (existing) | `security-assessment-worker:latest` | none | `target_path` | `sarif_path` |
| `mode-gate` | `decision` (rule) | — | n/a | n/a | `@context.mode` | `_branch` |
| `triage` | `agent_step` | `security.code.triage` (existing) | `security-assessment-worker:latest` | LLM provider host | `sarif_path`, `target_path` | `triaged_findings` |
| `mode-gate-2` | `decision` (rule) | — | n/a | n/a | `@context.mode` | `_branch` |
| `holistic` | `agent_step` | `security.code.holistic` (new) | `security-assessment-worker:latest` | LLM provider host | `target_path`, `cwe_registry_snapshot`, manifest from `detect_surface()` | `holistic_findings` (built via `record_holistic_finding` tool calls) |
| `config-review` | `agent_step` | `security.code.config_review` (new) | `security-assessment-worker:latest` | LLM provider host | `target_path`, config files from `detect_surface()` | `config_findings` |
| `merge-findings` | `tool_call` | `merge_findings` (new; calls existing `merge_sarif`) | n/a | n/a | `triaged_findings`, `holistic_findings`, `config_findings` | unified `findings` list + merged SARIF |
| `report` | `agent_step` | `security.code.reporter` (existing) | `security-assessment-worker:latest` | LLM provider host | unified `findings`, target info | `SecurityAssessmentReport` |
| `baseline-diff` | `decision` (rule) | — | n/a | n/a | report.findings, `MissionContext.baseline` | `_branch` |
| `human-gate` | `human_input` | — | n/a | n/a | new URGENT findings | gate decision |
| `store-artifacts` | `tool_call` × 5 | `store_artifact` (existing) + `EvidenceManifest` for hashing | n/a | n/a | report + SARIF + JSON + CSV + triage audit | artifact rows |
| `store-learnings` | `tool_call` | `store_learning` (existing) | n/a | n/a | confirmed-FP fingerprints, scanner runtime stats | learning rows |
| `update-baseline` | `tool_call` | `update_security_baseline` (new) | n/a | n/a | report.findings + gate decisions | updated `MissionContext.baseline` (versioned, idempotent on run_id) |

---

## Components to add (real delta)

| Component | Type | Location |
|---|---|---|
| `egress_allowlist: list[str] \| None` field on `ContainerBackend.create()` | Backend extension (small) | [modules/backend/services/container_backend.py](modules/backend/services/container_backend.py). Semantics: `None` → unchanged; `[]` → `network_mode: none`; non-empty → `network_mode: bridge` (proxy-sidecar enforcement deferred to Plan 78b). |
| `tool_call` step type honours `environment: container` | **Wave-engine extension** (~50 lines) | [modules/backend/services/workflow_run_waves.py:814](modules/backend/services/workflow_run_waves.py#L814) `_execute_tool_call_step`. Today the method calls `_impl(**resolved_args)` directly in the API process — `environment: container` is ignored. Extension: when step.environment == "container", provision an `EnvironmentHandle` via `execution_environment` service (same pattern as `_execute_step` for agent_steps), inject it into the tool's resolved_args (deps gains "environment_handle"), let the tool subprocess `git`/etc. inside the container. **Required by `acquire` step.** Beneficial for any future tool that needs sandboxed subprocess execution. |
| `security.code.holistic` agent (four-file blueprint) | New agent | `modules/backend/agents/security/code/holistic/` + `config/agents/security/code/holistic.yaml` + `config/prompts/agents/security/code/holistic/system.md` + roster entry |
| `security.code.config_review` agent (four-file blueprint) | New agent | `modules/backend/agents/security/code/config_review/` + YAML + prompt + roster |
| CWE registry YAML | Content | `config/taxonomy/cwe.yaml` (new directory) |
| 26 CWE check prompts | Content | `config/prompts/agents/security/code/holistic/cwe-*.md` (one per CWE) |
| Config-review system prompt | Content | Already covered by `config_review/system.md` above |
| `validate_target_url` function | **Extension to `roe.py`** (~30 lines) | New sibling to `validate_target_path()`. Signature: `validate_target_url(url: str, expected_target: str) -> None`. Normalises both URL and expected target (strip scheme `https://`/`git@`/`ssh://`, strip `.git` suffix, strip trailing `/`, lowercase host, normalise to `host/path` form). Compares normalised forms; raises `ROEViolationError` on mismatch. Single-target only — matches `SecurityCodeReviewConfig.target_url: str` (one mission = one repo, per the explicit out-of-scope item). |
| `clone_repo` tool | New tool (~60 lines) | `modules/backend/tools/clone_repo.py`. Declares `deps = ["mission_id", "environment_handle"]` — requires the wave-engine extension above. Sequence:<br>1. `validate_target_url(url, expected_target)` — **before any network call**, reading `expected_target` from `SecurityMissionState.config.target_url`. Fails loud on mismatch.<br>2. `git clone --depth 1 --branch {ref} --no-tags {url} {worktree}` — shallow clone of the configured ref directly into the worktree (executed via env handle inside the container).<br>3. `rm -rf {worktree}/.git` — strip git metadata after checkout. The working tree no longer contains a `.git` directory; downstream container mounts of `/workspace:ro` expose code only, no git history. **(S2 fix: replaces the malformed `--bare --separate-git-dir` sequence; Docker bind mounts have no exclude semantics, so the `.git` directory must not exist inside the mount.)**<br>4. Defensive `validate_target_path(worktree_path, …)` to confirm the worktree landed where expected.<br>The host worktree is cleaned up when the per-mission worktree is torn down (Plan 47's existing lifecycle). |
| `record_holistic_finding` tool | New tool | `modules/backend/tools/record_holistic_finding.py` — single-finding accumulator (P17) |
| `merge_findings` tool | New tool (~40 lines, trivial) | `modules/backend/tools/merge_findings.py` — **typed concat + dedup on `Finding` Pydantic objects** (from [agents/security/models.py](modules/backend/agents/security/models.py)). Inputs: `triaged_findings: list[Finding] \| None`, `holistic_findings: list[Finding] \| None`, `config_findings: list[Finding] \| None`. **Each input is `\| None` because upstream steps may be skipped by mode-gate decisions** — verified via [condition_evaluator.py:283](modules/backend/services/condition_evaluator.py#L283) `_resolve_ref` which returns `None` for missing/skipped step references. Tool treats `None` as `[]`. Output: `unified: list[Finding]` deduped by `(file_path, line_range, rule_id_or_cwe)`. **Does NOT touch SARIF** — that's `merge_sarif()`'s job and stays unchanged. **Does NOT reimplement the merger** — `merge_sarif()` continues to handle SARIF-level merge for the scanner's per-tool outputs upstream. Hashing of final artifacts is delegated to `EvidenceManifest` in the `store-artifacts` step, not here. |
| `update_security_baseline` tool | **Thin typed wrapper with retry loop** (~80 lines) | `modules/backend/tools/update_security_baseline.py`. See "Concurrency & semantics" below for the algorithm. Reuses the pattern of [tools/update_context.py](modules/backend/tools/update_context.py); does **not** reimplement MCD write logic. |
| `SecurityMissionState` Pydantic schema | New schema (validation only) | `modules/backend/schemas/security_mission_state.py`. Closed schema (`extra="forbid"`). Not enforced at the model layer — `MissionContext.context_data` remains `dict[str, Any]`. Validated at tool/service entry only. |
| `SecurityMissionStateReader` helper | New service helper (~30 lines) | `modules/backend/services/security_mission_state.py`. Wraps `MissionContext.context_data["security_code_review"]` → `SecurityMissionState`; returns `None` for missions without the key (first-run case). |
| Workflow YAML edit | Extension (not new file) | `config/workflow_templates/security.code-assessment.workflow.yaml` — adds the new steps after `report`, inserts `mode-gate` after `scan`, restructures `report`'s upstream to consume `merge-findings` output |
| Workflow seeder registration | One-line addition | `modules/backend/services/workflow_seeder.py` |
| Workflow `context:` block defaults (in the renamed YAML) | Extension of existing workflow YAML | Add `mode`, `triage_min_score`, `escalate_on_urgent`, `baseline_diff_threshold`, `cwe_subset`, `provider_models` to the existing `context:` section of `security.code-assessment.workflow.yaml`. No new preset file. |
| ~~Mission family registration~~ | Removed | No mission-family registry exists in MC; nothing to register. See architectural decisions. |
| Eval harness port | New tests | `tests/integration/security/code_review/` — ports SCAR's `eval/` directory; runs with `TestModel` against recorded LLM fixtures |

That's **7 new code modules** (2 agent dirs + 4 tools + 1 schema) + **3 small extensions** (`ContainerBackend.egress_allowlist`, `roe.validate_target_url`, workflow YAML `context:` block edits) + **1 service helper** (`SecurityMissionStateReader`). Plus content (26 CWE prompts + CWE registry + 2 system prompts). The v1 plan listed nearly twice this; v3 dropped invented infrastructure (mission family, mission preset).

---

## Container model

### Image

Reuses `security-assessment-worker:latest`. No new image required — all SAST binaries already present from WASA P1.

### Mount layout per step

| Step | `/workspace` | `/findings` |
|---|---|---|
| `acquire` | rw (host worktree) | rw |
| `scan` | ro (set by scanner agent today) | rw |
| `triage` | ro (only files referenced by findings, via context_builder) | rw |
| `holistic` | ro (only files selected per CWE rule) | rw |
| `config-review` | ro (only config files from `detect_surface()`) | rw |
| `merge-findings` / `report` | — | rw |

`.git` is never present in the worktree — `clone_repo` does a shallow clone (`--depth 1 --branch {ref} --no-tags`) directly into the worktree, then `rm -rf {worktree}/.git`. Downstream container mounts see code only, no git history (no risk of secret leakage via `.git/objects`).

### Container egress policy

**Verified architectural fact (informs the policy):** PydanticAI `Agent` runs its reasoning loop in the API process. The LLM HTTP call originates from the API process via the model adapter (`CopilotModel`, etc.), NOT from inside the container. Containers sandbox the agent's **tool subprocess calls** (e.g., `opengrep`, `pip-audit`) — not the LLM call itself.

This collapses the egress story significantly:

| Step | Container | Egress needed | Why |
|---|---|---|---|
| `acquire` | yes | git hosts only | `git clone` runs inside the container; needs network reach to the git host |
| `scan` | yes | **none** | Scanner subprocesses (opengrep, bandit, etc.) need no network. Trivy/pip-audit use cached CVE DBs baked into the worker image. CVE refresh is a separate ops job. |
| `triage` / `holistic` / `config-review` / `report` | yes | **none** | LLM call originates from API process. Container only sandboxes file reads/writes the agent's tools perform on the workspace. No outbound network needed from the container. |
| `merge-findings` / `store-*` / `update-baseline` | no | n/a | Pure Python tools running in API process |

**This means the `ContainerBackend` egress extension reduces to a binary choice:** `network_mode: none` vs. `network_mode: bridge` (with hostname allowlist applied OUTSIDE the container — see below).

### `ContainerBackend.egress_allowlist` extension

`ContainerBackend.create()` config gains:

```python
egress_allowlist: list[str] | None = None
```

Semantics:
- `None` → unchanged behaviour (today's `network_mode` honoured as-is).
- `[]` → `network_mode: none` (no egress, no rules).
- `["host1", "host2"]` → see "Hostname allowlist enforcement" below.

### Hostname allowlist enforcement (the `acquire` step's problem)

Naive `iptables` rules inside the container don't work for hostname allowlisting — iptables operates on IPs, hostnames rotate (especially github.com / dev.azure.com behind CDN), and `iptables` inside container requires `CAP_NET_ADMIN` which weakens the sandbox.

**Production-grade approach (deferred to a follow-up):** Forward-proxy sidecar (squid / tinyproxy / Envoy) in the same Docker network namespace as the scanner container. Sidecar enforces hostname allowlist at the HTTP/TLS-SNI layer. Container talks only to the sidecar. This is the right answer long-term but it adds an image, a config layer, and a coordination dance. Defer to **Plan 78b: Egress Hardening**.

**v1 approach (this plan):** `acquire` runs with `network_mode: bridge` (full egress) + a **strict ROE URL allowlist check via `validate_target_url()` BEFORE any network operation**. The defense-in-depth is at the tool layer (URL allowlist before clone) rather than the network layer. This is acceptable for v1 because:
- The threat is malicious target_url, not malicious in-container code (we control the agent code).
- `validate_target_url` is fail-loud — wrong URL = no clone attempted.
- A future Plan 78b adds the sidecar proxy if attackers find ways around `validate_target_url`.

For all other container steps (scan, triage, holistic, config-review, report), `egress_allowlist = []` → `network_mode: none`. **No CAP_NET_ADMIN needed for any container.** No iptables tricks. No DNS-rotation fragility. The container has zero outbound network capability.

### Per-step egress declaration in workflow YAML

| Step | `egress_allowlist` config | Result |
|---|---|---|
| `acquire` | not set; instead `network_mode: bridge` + tool-layer `validate_target_url` | full egress; defense at URL layer |
| `scan` / `triage` / `holistic` / `config-review` / `report` | `[]` | `network_mode: none` |
| `merge-findings` / `store-*` / `update-baseline` | n/a (no container) | runs in API process |

**Trade-off accepted:** `acquire` has wider egress than ideal. The proxy-sidecar hardening is captured in Plan 78b risks section, not silently dropped.

---

## Build order

Each phase produces a runnable, demonstrable artifact. No phase ships broken code.

### Phase 0 — Platform primitives + image hardening (offline-capable scanner image, egress, wave-engine extension)

Three small changes ship in the same PR. None are SCAR-specific — all are platform-level improvements that any future security mission will benefit from.

**0a. Scanner image hardening — bake CVE DBs for offline operation** (Dockerfile edit):

Verified [config/dockerfiles/security-assessment-worker.Dockerfile](config/dockerfiles/security-assessment-worker.Dockerfile) does NOT bake Trivy's CVE DB. With `network_mode: none`, Trivy fails to fetch the DB on first invocation. Same for `pip-audit` (queries OSV/PyPI at runtime).

Add to the Dockerfile after the Trivy install line and before the non-root user step:

```dockerfile
# ── Bake CVE DBs for offline operation (network_mode: none) ────────────
# Trivy: download DBs at build time, set offline env so runtime never fetches.
RUN trivy --cache-dir /opt/trivy-cache image --download-db-only \
    && trivy --cache-dir /opt/trivy-cache image --download-java-db-only \
    && chown -R pentester:pentester /opt/trivy-cache
ENV TRIVY_CACHE_DIR=/opt/trivy-cache
ENV TRIVY_SKIP_UPDATE=true
ENV TRIVY_SKIP_JAVA_DB_UPDATE=true

# pip-audit: vendor a static OSV snapshot at build time (offline mode).
# pip-audit supports OSV_OFFLINE_DB via its `--vulnerability-service` config.
# Vendor approach: download the OSV ecosystems we care about at build time.
RUN mkdir -p /opt/osv-cache && \
    curl -sfL https://osv-vulnerabilities.storage.googleapis.com/PyPI/all.zip \
        -o /opt/osv-cache/PyPI.zip && \
    chown -R pentester:pentester /opt/osv-cache
ENV PIP_AUDIT_OFFLINE_DB=/opt/osv-cache
```

Image size grows by ~500MB (mostly the Trivy DB). Acceptable trade-off for offline operation.

Also include in this step (resolves C3):

```dockerfile
# Betterleaks (SCAR uses this for secret detection; WASA's image
# originally deferred to Phase 2 but the comment in the Dockerfile
# says betterleaks not installed yet; install it here)
RUN curl -sSLo /tmp/betterleaks.tar.gz \
        https://github.com/.../betterleaks-linux-amd64.tar.gz && \
    tar -xzf /tmp/betterleaks.tar.gz -C /usr/local/bin/ && \
    rm /tmp/betterleaks.tar.gz
```

(Exact URL/version pinned at PR time; out-of-scope for the plan to specify the release tag.)

Acceptance for 0a: `docker run --network none security-assessment-worker:latest trivy fs /workspace/target/ --skip-update` succeeds against a fixture with known CVEs. Same for `pip-audit --offline`.

**0b. `ContainerBackend.egress_allowlist`** (small backend extension):

1. Add `egress_allowlist: list[str] | None` field on `ContainerBackend.create()`.
2. Semantics: `None` → unchanged; `[]` → `network_mode: none`; non-empty → `network_mode: bridge` (proxy-sidecar hostname enforcement deferred to Plan 78b — for v1, non-empty allowlist is treated as advisory metadata + full bridge, with a logged warning that strict enforcement requires 78b).
3. Integration test: real Docker; `[]` produces a container that cannot reach the network.

**0c. Wave-engine extension: `_execute_tool_call_step` honours `environment: container`** (~50 lines):

1. Modify [services/workflow_run_waves.py:814](modules/backend/services/workflow_run_waves.py#L814) `_execute_tool_call_step` to provision an `EnvironmentHandle` via the `execution_environment` service when `step.environment == "container"`, matching the pattern used by `_execute_step` for agent_steps.
2. Inject the handle into the tool's resolved_args when the tool declares `deps = [..., "environment_handle"]` (extend `_HANDLED_DEPS = {"http_client", "mission_id"}` to include `"environment_handle"`).
3. The handle is torn down at step end via existing lifecycle.
4. Backward-compat: tool_calls without `environment: container` continue running in-process (unchanged behaviour).
5. **Side effect worth declaring:** verified at [tools/run_command.py:22](modules/backend/tools/run_command.py#L22) that `run_command` already declares `deps = ["environment_handle"]` but currently cannot be called from any `tool_call` step (would error `unsupported deps`). This extension unblocks `run_command` from `tool_call` for the first time. Useful for future tools beyond `clone_repo`.
6. Integration test matrix:
   - A `tool_call` step with `environment: container` provisions a handle and runs the tool inside the container.
   - A `tool_call` step **without** `environment: container` runs in-process (no regression).
   - A `tool_call: run_command` step with `environment: container` executes the command inside the container (public-tool regression test — exercises the side effect from item 5).

**Deliverable:** Three primitives shipped + tested. Scanner image runs offline. The egress allowlist's hostname-enforcement is acknowledged as "advisory until 78b"; the binary none/bridge choice is the only enforced semantic in v1.

### Phase 1 — `SecurityMissionState` schema + reader

1. `schemas/security_mission_state.py` with the Pydantic schema above. Closed schema (`extra="forbid"`).
2. `services/security_mission_state.py` with `SecurityMissionStateReader` (wraps `MissionContext.context_data["security_code_review"]` → typed model; returns `None` if missing).
3. **MCD shape audit:** read an existing mission's `MissionContext.context_data` and confirm no top-level `security_code_review` key collision. Document existing top-level keys for future reference.
4. Integration test (P12 — real Postgres): create a mission, write a `SecurityMissionState` via `MissionContextManager.apply_updates`, read it back through the reader, confirm type roundtrip.

**Deliverable:** A typed read/write path exists for the security MCD keyspace. No mission-family registry, no preset file — those concepts don't exist in MC. The "code security review" identity is the mission's name + workflow attachment + this MCD keyspace.

### Phase 2 — Content port (no code)

1. `config/taxonomy/cwe.yaml` — port SCAR's registry.
2. `config/prompts/agents/security/code/holistic/cwe-*.md` (26 files) — port SCAR's prompts.
3. `config/prompts/agents/security/code/holistic/system.md` — port SCAR's triage-of-CWE shell prompt.
4. `config/prompts/agents/security/code/config_review/system.md` — port SCAR's config review prompt.

**Deliverable:** All SCAR content is in the MC repo; no code changes.

### Phase 3 — `security.code.holistic` agent + `record_holistic_finding` tool

1. Agent four-file blueprint under `agents/security/code/holistic/`.
2. Agent dependency on `detect_surface()` for file selection per CWE.
3. `record_holistic_finding` tool — single-finding accumulator (P17). Each tool call appends to the agent's accumulating `holistic_findings` list.
4. Unit tests using `TestModel(call_tools=[...])` with canned CWE responses.

**Deliverable:** The holistic agent can be invoked in isolation and produces `holistic_findings`. Not yet wired to the workflow.

### Phase 4 — `security.code.config_review` agent

1. Agent four-file blueprint under `agents/security/code/config_review/`.
2. Uses `detect_surface()` to pull `config_files` from the manifest.
3. Unit tests.

**Deliverable:** Config-review agent invocable in isolation.

### Phase 5 — `merge_findings` and `clone_repo` tools

1. `merge_findings` — calls existing `merge_sarif()`, combines triage + holistic + config findings, hashes outputs via existing `EvidenceManifest`.
2. `clone_repo` — sequence: `validate_target_url()` (URL ROE check, pre-network), `git clone --depth 1 --branch {ref} --no-tags {url} {worktree}`, `rm -rf {worktree}/.git`, defensive `validate_target_path()` post-clone.

**Deliverable:** Both tools callable from workflow YAML.

### Phase 6 — Workflow YAML + seeder + end-to-end run

1. Extend `config/workflow_templates/security.code-assessment.workflow.yaml` (renamed by Plan 78a) with the DAG above (no baseline-diff or human-gate yet — just the linear path through report → store-artifacts). Insert `mode-gate` after `scan`; insert `holistic`, `config-review`, `merge-findings` after `triage`; rewire `report` to consume `merge-findings` output.
2. Seeder registration.
3. Integration test: real Postgres + real Docker + `TestModel` for LLM steps. Validates mode=sast, mode=sast-triage, mode=full.

**Deliverable:** From TUI/CLI, a user creates a code-security-review mission and runs all three modes end-to-end against a fixture target repo. SARIF + markdown + JSON + CSV stored as `MissionArtifact` rows.

### Phase 7 — Baseline diff + human gate + update-baseline

1. `update_security_baseline` tool, idempotent on `(mission_id, run_id)`.
2. `baseline-diff` decision node in the workflow.
3. `human-gate` `human_input` node (uses existing gate infrastructure).
4. Integration test: second run on the same mission consults baseline; suppresses previously-accepted FPs; gates on new URGENT.

**Deliverable:** Run-over-run intelligence works. Second run is quieter than first. New URGENT triggers the gate.

### Phase 8 — `store-learnings` enrichment (exact-match only)

1. Confirmed-FP fingerprint extraction from triage verdicts (sha256 of `rule_id + normalized_file_path + 5-line sliding window hash`). Stored in `SecurityMissionState.baseline.findings` — used for **exact-match suppression** on next run via `baseline-diff`.
2. Per-scanner runtime statistics aggregation (mean / p95 per tool) → `SecurityMissionState.scanner_runtime_baselines`.
3. CWE coverage entry append to `SecurityMissionState.coverage_history` (rolling N most recent).

**Deliverable:** Cross-run exact-match suppression and runtime baselines accumulate. Previously-accepted FPs (identical fingerprint) are dropped from the next run's report.

**Explicitly NOT in this phase:** Similarity-based FP learning ("findings *similar* to this previously-confirmed FP"). That requires embedding finding text (description + location + code snippet around the line) and a vector index — *fingerprints themselves are sha256 hashes and embedding them adds zero signal*. The similarity-based feature is captured as a follow-up plan that depends on Plan 73 (Knowledge Graph) shipping first; not blocking this plan.

### Phase 9 — Eval harness in CI

1. Port SCAR's `eval/` fixtures (or reference manifest pointing at git-LFS / public commit shas — do not vendor multi-GB fixtures).
2. CI job runs the workflow with `TestModel` + recorded LLM fixtures (P11 — no live LLM in CI).
3. F2 / MCC / per-CWE recall report published as a `MissionArtifact` in a synthetic "eval" mission.
4. CI gate: fail PR if score drops >5% from baseline.

**Deliverable:** Regression gate on prompt/workflow changes.

### Phase 10 — Scheduling + webhook (autonomy)

1. Wire code-security-review missions into Plan 54 scheduling (cron-style).
2. Webhook handler (GitHub / Azure DevOps) creates new workflow runs on configured ref changes.
3. Hard ROE gate at workflow entry — target URL must match `SecurityCodeReviewConfig.target_url`.

**Deliverable:** A mission runs autonomously on schedule or on push; ROE enforcement is at the platform boundary.

---

## Cost, budget, and fan-out controls

Layered, in priority order:

1. **Deterministic pre-filter before triage** — handled by existing triage agent; LOW findings filtered by `triage_min_score`.
2. **`max_fan_out` parameter on the holistic agent's internal iteration** — hard cap on simultaneous CWE checks the agent will run before waiting (default: 4 concurrent CWE checks per provider concurrency limit).
3. **Per-session cost middleware** — existing infrastructure aborts the session when the per-run ceiling is hit. Workflow does not branch on this; middleware kills it.
4. **Anthropic prompt caching across the 26 CWE checks** — single-agent-internal-loop preserves session, so cache is reused. Phase 3 acceptance gate verifies measurable cache hits.

If the holistic pass exceeds budget mid-iteration, the agent emits whatever findings it accumulated before abort. The workflow continues to `merge-findings` with partial holistic results; the report flags the degradation.

---

## Failure modes

| Failure | Classification | Response |
|---|---|---|
| Scanner timeout / crash | Non-fatal | Scanner agent today logs and continues with partial SARIF. Unchanged. |
| Scanner step attempts network egress | Fatal | `network_mode: none` rejects the connection at the kernel; step fails fast. Tripwire — should never happen with shipped scanner image. |
| `acquire` step receives out-of-ROE URL | Fatal | `validate_target_url()` raises `ROEViolationError` before any network operation; step fails fast; security event logged. |
| LLM timeout / 429 | Non-fatal | Backoff + retry per existing provider config. |
| Holistic agent partial completion (budget exhausted) | Non-fatal | Findings accumulated so far are kept; report flags degradation. |
| Workspace clone failure | Fatal | `acquire` aborts before any LLM cost incurred. |
| ROE violation | Fatal | `clone_repo` aborts; security event logged. |
| `update_security_baseline` fails after run | **Recoverable** | Tool is idempotent on `(mission_id, run_id)`. Operator can re-run the tool out-of-band or the next workflow run will write a baseline that supersedes this one's. The baseline write is the last step; failure does not invalidate artifacts. |
| **Two scheduled runs overlap, both write baseline** | **Resolved by optimistic concurrency on `MissionContext.version`** | [services/mission_context.py:242](modules/backend/services/mission_context.py#L242) `apply_updates` already uses optimistic concurrency on the `version` integer. If run A and run B both compute baselines from version V, the second writer's version check fails → `apply_updates` returns an error → `update_security_baseline` re-reads the now-version-(V+1) baseline, recomputes the merge of its findings against the latest baseline, and retries. Bounded retries (3); after that, the later run is the winner via last-write-wins on a re-read of fresh state. No advisory lock needed. |
| Docker daemon unavailable | Fatal | Workflow run marked `infrastructure_failure`; replayable. |
| Missing CWE prompt file | Fatal at workflow load | Workflow seeder validates prompt-file existence on registration. |
| Temporal replay mid-run | Recoverable | Container steps replay from last completed step (scan / triage / holistic each emit deterministic outputs persisted to the workflow run). Acquire is idempotent on `(workspace_path, ref)`. |

---

## Testing strategy

P11 (no LLMs in CI) + P12 (real infrastructure).

| Layer | What is tested | How |
|---|---|---|
| `network_mode: none` enforcement | Scanner + LLM-using containers cannot reach external hosts (curl example.com fails) | Integration test with real Docker daemon |
| `acquire` URL validation | Out-of-ROE URL raises `ROEViolationError` before clone; in-ROE URL clones successfully | Unit + integration |
| Wave-engine `_execute_tool_call_step` container provisioning | `environment: container` triggers env handle injection; tool runs subprocess inside container; non-container tool_call unchanged | Integration with real Docker |
| `clone_repo` tool | ROE validation pass/fail; `.git` not present in worktree; idempotent on `(url, ref)` | Unit + integration |
| `merge_findings` tool | Combines three sources; dedupes by location; `EvidenceManifest` hashes match | Unit |
| `update_security_baseline` | Idempotent on `(mission_id, run_id)`; schema validation | Unit + integration (real Postgres) |
| `security.code.holistic` agent | Tool wiring; per-CWE file selection from `detect_surface()`; `record_holistic_finding` accumulation | `TestModel(call_tools=[...])` |
| `security.code.config_review` agent | Tool wiring; config-file selection | `TestModel` |
| Workflow mode=sast | End-to-end, real Docker, `TestModel` LLMs | Integration |
| Workflow mode=sast-triage | Same | Integration |
| Workflow mode=full | Same | Integration |
| Baseline-diff | Second run on same mission suppresses previously-accepted FPs | Integration |
| Human-gate | New URGENT triggers the gate; gate decision honoured | Integration (gate stub) |
| Eval harness | F2 / MCC / per-CWE recall against ground truth | Nightly job; recorded LLM fixtures |

No live LLM in CI. Provider matrix runs nightly, not on PRs.

---

## Out of scope (explicit)

- **DAST / dynamic testing / exploitation.** Belongs in WASA Phases 2+.
- **Per-finding triage fan-out (P17).** Follow-up plan; requires cost/quality measurement.
- **Sub-workflow per CWE.** Follow-up plan; requires cache-miss measurement.
- **`security.webapp.*` → `security.code.*` rename.** Handled by Plan 78a (this plan's dependency).
- **Languages outside Python and C#.** Add JS/TS/Go in a follow-up; architecture supports it (capability resolution + prompts).
- **Multi-repo / monorepo subtree review.** One mission = one repo.
- **Replacing any WASA P1 code.** Explicit non-goal.
- **CWE rule authoring inside the platform.** Editorial work outside this plan.
- **Per-user provider auth.** Use the platform's existing provider-credential model.
- **Forward-proxy sidecar for hostname-allowlisted egress.** Deferred to Plan 78b (Egress Hardening). v1 uses `network_mode: none` for steps that don't need network and `network_mode: bridge` + URL-layer ROE check for `acquire`.
- **Similarity-based FP suggestions** (embed finding text → vector search). Follow-up plan; depends on Plan 73 shipping first. v1 uses exact-match fingerprint suppression only.

---

## Acceptance criteria

The plan is done when **all** of the following are true on a clean checkout against a non-trivial target repo:

1. A code-security-review mission can be created and persists across restarts with its `SecurityMissionState` intact.
2. Container egress is correctly scoped: scanner + LLM-using steps run with `network_mode: none` (zero outbound network from container, verified by attempting `curl example.com` from inside the container and observing failure). `acquire` step runs with `network_mode: bridge` and rejects out-of-ROE URLs at the tool layer (verified by attempting a non-allowlisted URL and observing `ROEViolationError` before any network operation).
2b. Wave engine `_execute_tool_call_step` correctly provisions a container when `environment: container` is set on a tool_call step (verified: `acquire` step succeeds; a control tool_call step without `environment: container` continues to run in-process).
3. `mode=sast` completes end-to-end in containers with no `.git` exposed to any container.
4. `mode=sast-triage` reduces SAST findings by the expected ratio (per WASA P1 measured baseline ± 10%).
5. `mode=full` produces holistic CWE findings and config-review findings in the merged report.
6. Prompt caching across the 26 CWE checks shows **cache hit ratio ≥ 70%** on a fixture target with 5+ files per CWE (verified via provider response headers or cost-log delta vs no-cache baseline). Provider-specific: Anthropic via `prompt_caching_beta`; Copilot per its caching behaviour as exposed by `CopilotModel`. If the provider doesn't expose cache hit telemetry, fall back to cost-delta measurement.
7. A second run on the same mission consults the baseline and suppresses previously-accepted FPs.
8. Introducing a new URGENT finding triggers the human-gate; gate decision is honoured.
9. Per-session cost ceiling aborts the session cleanly; partial holistic findings preserved.
10. Eval harness reports F2 / MCC; CI gate fails on >5% regression.
11. Temporal-resume mid-run does not re-execute completed steps.
12. No `var/output/`, no `.project_root` marker, no *per-invocation* `gh auth` subprocess shells from this plan's code (MC's existing `CopilotModel` adapter may use `gh auth` internally for OAuth — that's the platform's existing provider auth path, out of scope for this criterion). None of SCAR's *environment couplings* (relative `config/` paths, hardcoded run directories, developer-machine assumptions) are present.
13. No edits to WASA P1 *agent code*. The scanner / triage / reporter agents, `tool_runner`, `sarif.py`, `evidence.py`, `models.py` are renamed by Plan 78a but their Python logic is untouched. **What does change in P1's surface:**
    - `roe.py` gains a new sibling function `validate_target_url()` — extension, not behavioural change.
    - `services/workflow_run_waves.py::_execute_tool_call_step` is extended to honour `environment: container` — affects all tool_call steps, not just security ones; document the behaviour change in the PR.
    - `security.code-assessment.workflow.yaml` (the renamed P1 workflow) has new steps inserted and the `report` step's `depends_on` shifts from `triage` to `merge-findings` (its input mapping changes from `@steps.triage.triaged_findings` to `@steps.merge-findings.unified`). The reporter *agent's* Python is unchanged; only its workflow attachment changes.

---

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Anthropic prompt cache isn't reused across the 26 CWE checks despite single-session | High | Phase 3 explicit acceptance gate measures cache hits. If not measurable, abort Phase 3, switch to sub-workflow + provider-level cross-session caching (Plan 60). |
| Holistic agent's internal iteration exceeds session timeout on large repos | Medium | Per-CWE timeout inside the agent; emit partial findings before timeout. |
| Scanner image-baked CVE DB drifts as long-running missions reuse the image | Medium | Phase 0a bakes Trivy + pip-audit CVE DBs into the worker image at build time. **The DB is fresh as of image build, stale thereafter.** Operational concern: image rebuild cadence determines DB freshness. Recommendation: nightly CI rebuild of the worker image; document the freshness expectation in the worker image README. Without rebuild cadence, scanner findings will miss newly-published CVEs. |
| `update_security_baseline` retry loop has unbounded edge case | Low | Wrapper retries 3 times on OCC conflict. If 3 concurrent writes race, one fails permanently — caller raises `BaselineUpdateError` and the workflow run is marked degraded but artifacts are preserved. Worst-case impact is one missed baseline update; the next run picks up from the prior baseline. |
| ROE bypass via a tool that accepts URLs | Medium-High | `clone_repo` is the only new URL-accepting tool. It routes through the new `validate_target_url()` before any network call. URL normalisation (scheme strip, .git strip, lowercase host) covered by Phase 5 unit tests including the obvious circumvention cases (URL-encoded characters, IDN homographs, alternate ports). |
| Acquire step has wide egress (`network_mode: bridge`) | Medium | Defense at URL layer (`validate_target_url`) before network; container has no agent code that makes outbound HTTP — only `git`. Forward-proxy sidecar hardening deferred to Plan 78b. Acknowledged trade-off, not silent. |
| Wave-engine extension to support `environment: container` for `tool_call` affects all tool_calls | Medium | Change is opt-in (only steps that declare `environment: container` get a provisioned env handle). Existing tool_call steps without that field continue unchanged. Integration test covers a non-container tool_call to confirm no regression. |
| `SecurityMissionState` schema evolution | Medium | Schema versioning field; migrations live in `schemas/security_mission_state.py` migration helpers (mirror existing schema-evolution pattern). |
| 26 CWE prompts drift in quality as customised | Medium | Phase 9 eval harness; >5% regression fails CI. |
| `merge_findings` dedup misses cross-source duplicates (e.g., SAST finds a CWE-89 that holistic also finds) | Medium | Dedup key = `(file_path, line_range, rule_id_or_cwe)`; integration test with synthetic overlap. |
| New URGENT cascade overwhelms the human-gate inbox | Low | Gate UI shows count + sample; user can bulk-accept or bulk-dismiss. |
| Trivy CVE DB inside the worker image goes stale | Low | Image rebuild cadence is a separate ops concern (already exists for WASA P1). Document the freshness expectation. |
| Roslyn skip when no `.csproj` is misclassified as failure | Low | `condition` field on the relevant scanner sub-step in WASA P1's scanner agent already handles this; unchanged. |

---

## Open questions (smaller list)

1. **MCD top-level key collision check.** Read an existing mission's `context_data` to confirm no existing top-level key conflicts with `security_code_review`. (Done in Phase 1.)
2. **Eval fixture hosting.** Manifest pointing at git-LFS / public commit shas, or vendored small fixtures? **Recommendation:** manifest + small fixtures (a few hundred KB at most in repo).
3. ~~`update_security_baseline` write-quorum on long-running missions.~~ **Resolved.** [services/mission_context.py:242](modules/backend/services/mission_context.py#L242) `apply_updates` already implements optimistic concurrency on the `version` integer; `update_security_baseline` reuses it with bounded retries. See Failure Modes table.

---

## Done definition checklist

- [ ] Phase 0 — image hardening (CVE DBs baked offline + betterleaks) + `ContainerBackend.egress_allowlist` + wave-engine `tool_call` container support
- [ ] Phase 1 — `SecurityMissionState` schema + `SecurityMissionStateReader` + MCD-shape audit
- [ ] Phase 2 — content port (CWE registry, 26 prompts, config-review prompt)
- [ ] Phase 3 — `security.code.holistic` agent + `record_holistic_finding` + cache-hit acceptance
- [ ] Phase 4 — `security.code.config_review` agent
- [ ] Phase 5 — `merge_findings` + `clone_repo` tools
- [ ] Phase 6 — workflow YAML + seeder + end-to-end run (all three modes)
- [ ] Phase 7 — baseline diff + human gate + `update_security_baseline`
- [ ] Phase 8 — `store-learnings` enrichment (exact-match FP suppression + runtime baselines; no vector indexing)
- [ ] Phase 9 — eval harness in CI
- [ ] Phase 10 — scheduling + webhook + hard ROE gate
- [ ] All acceptance criteria met
- [ ] All risks mitigated or accepted with explicit rationale
- [ ] No edits to WASA P1 *behaviour* (rename via 78a is permitted; agent logic unchanged)
