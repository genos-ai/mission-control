# WASA Phase 1 Implementation Plan — SAST Foundation

**Spec:** `docs/97-plans/66-spec-webapp-security-assessment.md`
**Branch:** `feature/wasa-phase-1`
**Goal:** Scanner + Triage + Report pipeline. No DAST. No exploitation. Calibrate against human benchmark.
**Phase 1 invariants:** S-01..S-04, T-01..T-04, R-01..R-06, EV-01
**Cost per run:** $5-15. **Target metric:** Reproduce 70% of human-found SAST issues.

---

## Quality Review Notes

Reviewed against existing codebase for duplication and pattern consistency:

1. **Config pattern:** Schema in `core/config_schema.py` (where ALL platform schemas live), loaded via `_load_validated_optional()` in `AppConfig`, accessed via `get_app_config().security_assessment`. Thin re-export in `agents/security/config.py`. NOT `pydantic-settings.BaseSettings`.
2. **SHA-256 hashing:** Uses `hashlib.sha256` (stdlib) directly. Does NOT import `core/embeddings.py:content_hash()` (truncates to 16 chars — unsuitable for integrity).
3. **Subprocess execution:** `tool_runner.py` implements its own `_run_tool_subprocess()` following the `asyncio.create_subprocess_exec` pattern from `tools/run_command.py:_run_local()`. Does NOT import `_run_local()` (private function — independent implementation of trivial pattern).
4. **PQI Finding vs WASA Finding:** Different layers. PQI `Finding` (dataclass) is tool-level results. WASA `Finding` (Pydantic model) is agent output schema. No inheritance — different types for different purposes. Spec Section 2.8.1 is explicit about this boundary.
5. **OPA integration:** Phase 1 uses path-based scope checks only (`validate_target_path()`). OPA HTTP client (`validate_scope()`) deferred to Phase 2 when DAST tools make outbound requests. Rego policy file written in Phase 1 for completeness.
6. **No existing code for:** SARIF parsing, surface detection, URL/SSRF validation, OPA integration, secret redaction of tool output. All built new.

---

## Prerequisites (completed)

- [x] Step-level `condition` field on `WorkflowStepSchema` (commit `95b8a47`)
- [x] Container image resolution via `container_image` on workflow steps (commit `95b8a47`)
- [x] Extra volumes + network mode in `ContainerBackend` (commit `95b8a47`)

---

## Build Order

Modules are ordered by dependency. Each step produces testable output before the next begins. Steps within a group have no mutual dependencies and can be built in parallel.

### Step 1: Pydantic Output Models

**File:** `modules/backend/agents/security/models.py` (~350 lines)
**Spec:** Section 4.3

All downstream code depends on these types. Build first, test immediately.

**What to build:**
- Enums: `SeverityLevel`, `TriageVerdict`, `OWASPCategory`, `ExploitStage`, `RemediationPriority`, `AssessmentPhase`
- State: `AssessmentState`
- Credentials: `TestCredential` (Vault refs, not plaintext — `pydantic.SecretStr` for sensitive fields)
- PTT: `PentestTask`
- Core finding: `Finding` with validators:
  - `rationale_required_for_fp` — FP verdict requires non-empty rationale
  - `normalise_severity` — uppercase coercion
  - `require_location` — must have (file_path + line_number) or (url)
- Digest: `HttpResponseSummary` (max_length=200 on free-text fields)
- Validation: `ValidationResult`
- Report components: `AttackPath` (min_length=2 on source_findings), `RemediationItem`, `CoverageCell`, `CoverageMatrix`
- Report: `SecurityAssessmentReport` (min_length=300 on executive_summary, min_length=1 on known_limitations)

**What NOT to build yet:** `SurfaceDetectionResult` — built in Step 4 alongside `detect_surface()`.

**Imports from platform:** None. Pure Pydantic.

**Test file:** `tests/agents/security/test_models.py`
- FP without rationale rejected
- Severity normalisation (lowercase → uppercase)
- Finding without location rejected
- AttackPath with < 2 findings rejected
- Report with executive_summary < 300 chars rejected
- Report with empty known_limitations rejected
- HttpResponseSummary notes field clamped to 200 chars

---

### Step 2: Configuration + Errors + Evidence (parallel group)

These three modules have no dependencies on each other. Build in parallel.

#### Step 2a: Configuration

**YAML file:** `config/settings/security_assessment.yaml`
**Schema:** Add `SecurityAssessmentSchema` to `modules/backend/core/config_schema.py`
**Integration:** Add to `AppConfig` in `modules/backend/core/config.py`
**Convenience re-export:** `modules/backend/agents/security/config.py` (~10 lines)
**Spec:** Section 1.5

**Pattern:** Follow the platform's existing config pattern exactly:
1. Schema class in `core/config_schema.py` (where ALL config schemas live)
2. YAML in `config/settings/security_assessment.yaml`
3. Loaded via `_load_validated_optional()` in `AppConfig.__init__`
4. Accessed via `get_app_config().security_assessment`
5. Thin re-export in `agents/security/config.py` for domain-local imports

Do NOT use `pydantic-settings.BaseSettings` — the platform uses YAML + Pydantic schema validation.
Do NOT create a standalone config loader — use `AppConfig`.

**What to build:**

In `core/config_schema.py`:
- `SecurityAssessmentSchema(_StrictBase)` — Phase 1 subset only:
  - `roe_opa_endpoint: str` — **required** (fail fast if OPA not configured)
  - `scope_validation_mode: Literal["strict", "permissive"]` — default `"strict"`
  - `scanner_max_file_size_bytes: int` — default 1MB
  - `tool_registry_path: str` — default `"config/security/tools.yaml"`
  - `triage_fp_confidence_threshold: float` — default 0.75
  - `triage_code_context_lines: int` — default 10
  - `triage_max_findings_per_run: int` — default 500
  - `evidence_sha256_on_write: bool` — default True
  - `evidence_base_path: str` — default `"@workspace/evidence/"`
  - `cost_hard_limit_usd: float` — default 50.0
  - `cost_alert_threshold_pct: float` — default 0.80
  - `report_min_executive_summary_chars: int` — default 300
  - `report_risk_score_weights: dict` — default `{"cvss": 0.40, "exploitability": 0.30, "business_impact": 0.30}`

In `core/config.py`:
- Add `self._security_assessment = _load_validated_optional(SecurityAssessmentSchema, "security_assessment.yaml")` to `AppConfig.__init__`
- Add `security_assessment` property

In `agents/security/config.py` (thin re-export):
- `from modules.backend.core.config import get_app_config`
- `def get_security_assessment_config() -> SecurityAssessmentSchema: return get_app_config().security_assessment`

YAML file with commented header listing all options.

**Phase 2/3 fields deferred:** `recon_rate_limit_rps`, `dast_proxy_port`, `appsec_*`, `exploit_*`, `auth_*`.

**Test:** Loading YAML with missing `roe_opa_endpoint` raises `ValidationError`.

#### Step 2b: Error Taxonomy

**File:** `modules/backend/agents/security/errors.py` (~80 lines)
**Spec:** Section 2.6

**What to build:**
- `SecurityErrorCode(str, Enum)` — Phase 1 codes only:
  - Scope: `ROE_SCOPE_VIOLATION`, `ROE_HASH_MISMATCH`, `ROE_MISSING`
  - Scanner: `SCANNER_BINARY_NOT_FOUND`, `SCANNER_TIMEOUT`, `SARIF_MERGE_FAILED`, `SARIF_TRUNCATED`
  - Triage: `TRIAGE_BUDGET_EXCEEDED`
  - Infrastructure: `OPA_UNAVAILABLE`, `COST_LIMIT_EXCEEDED`
- `SecurityErrorSpec` dataclass: code, http_status, message_template, retryable, retry_after_seconds, recovery_action
- `SECURITY_ERROR_SPECS` dict mapping codes to specs
- `SecurityAssessmentError(Exception)` with code, message, details

**Phase 2/3 codes deferred:** `DAST_*`, `APPSEC_*`, `EXPLOIT_*`, `EVIDENCE_PROXY_BYPASS`, `BURP_MCP_UNAVAILABLE`.

#### Step 2c: Evidence Integrity

**File:** `modules/backend/agents/security/evidence.py` (~80 lines)
**Spec:** Section 2.7, invariants EV-01, EV-02

**What to build:**
- `EvidenceManifest` class:
  - `entries: dict[str, str]` — path → SHA-256
  - `add(path: str)` — compute SHA-256 via `hashlib.sha256` (stdlib — no wrapper needed), append to manifest (EV-02: append-only)
  - `verify(path: str) -> bool` — check hash matches
  - `save(manifest_path: str)` — write JSON manifest
  - `load(manifest_path: str)` — read JSON manifest

**Note:** `core/embeddings.py:content_hash()` exists but truncates to 16 chars — not suitable for integrity. Use `hashlib.sha256` directly (one-liner, no import from embeddings).

**Test file:** `tests/agents/security/test_evidence_integrity.py`
- Every added file has a SHA-256 entry (EV-01)
- Manifest is append-only — cannot remove or modify entries (EV-02)
- Verify detects tampered files

---

### Step 3: Tool Registry + Tool Runner

**Depends on:** Step 1 (models), Step 2a (config)

#### Step 3a: Tool Registry

**File:** `modules/backend/agents/security/tool_registry.py` (~120 lines)
**Config:** `config/security/tools.yaml` (~150 lines — Phase 1 tools only)
**Spec:** Section 1.2

**What to build:**
- `ToolCapability(str, Enum)` — Phase 1 subset:
  - `CODE_SCAN`, `CODE_LINT`, `DEPS_SCAN`, `SECRETS_DETECT`, `CONTAINER_SCAN`, `DOCKERFILE_LINT`, `INFRA_SCAN`
- `CapabilityMode(str, Enum)` — `FALLBACK`, `ENSEMBLE`
- I/O contracts: `CapabilityInput`, `SarifCapabilityOutput`, `ReconCapabilityOutput`, `ExploitCapabilityOutput` — defined in `tool_registry.py` (per spec Section 1.2). These are tool-layer contracts, not agent output models. `models.py` holds agent output types (`Finding`, `SecurityAssessmentReport`). No cross-import — different layers.
- `SecurityToolSpec(BaseModel)` — name, capability, mode, binary, version_cmd, output_format, sarif_native, success_exit_codes, run_template, default_args, redact_output, timeout_seconds, applies_when
- `SecurityToolRegistry` class:
  - `__init__(config_path: Path)` — loads YAML, builds capability → specs dict
  - `get_primary(capability) -> SecurityToolSpec`
  - `get_all(capability) -> list[SecurityToolSpec]`
  - `get_applicable(surface: SurfaceDetectionResult) -> list[SecurityToolSpec]`
  - `check_installed(spec) -> bool` — `shutil.which(spec.binary)`
- `CAPABILITY_OUTPUT_CONTRACTS` dict

**Config file:** `config/security/tools.yaml`
- Phase 1 tools only: opengrep, ruff, pip-audit, betterleaks, trivy, hadolint, checkov
- No recon/DAST tools (Phase 2)
- Commented header listing all config options

**Test file:** `tests/agents/security/test_scanner_exit_codes.py`
- Exit code 1 is in `success_exit_codes` for opengrep, ruff, pip-audit (S-03)
- Registry loads YAML correctly
- `get_applicable()` filters by surface conditions
- `check_installed()` returns False for missing binary

#### Step 3b: Tool Runner

**File:** `modules/backend/agents/security/tool_runner.py` (~150 lines)
**Spec:** Section 1.2

**What to build:**
- `_run_tool_subprocess(cmd: list[str], timeout: int, cwd: str | None) -> CommandResult` — async subprocess helper returning `{exit_code, stdout, stderr, duration_seconds}`. Implements the same `asyncio.create_subprocess_exec` + `wait_for` pattern as `tools/run_command.py:_run_local()` (~10 lines). Does NOT import `_run_local()` (it's a private function in another module — independent implementation of a trivial pattern, not duplication).
- `run_security_tool(spec, input, config) -> SarifCapabilityOutput` — the unified runner:
  1. Resolve command from template + args
  2. Run subprocess via `_run_tool_subprocess()`
  3. Validate exit code against `spec.success_exit_codes`
  4. Copy raw output to `.raw` path
  5. Convert to SARIF if `not spec.sarif_native` (calls `convert_to_sarif()`)
  6. Redact if `spec.redact_output` (calls `redact_and_encrypt()`)
  7. Hash evidence if `config.evidence_sha256_on_write`
  8. Return typed output contract
- `run_capability(capability, input, registry, config) -> list[output]` — fallback/ensemble dispatch
- `convert_to_sarif(path, source_format, tool_name)` — converts JSON/JSONL → SARIF 2.1.0
- `count_severities(sarif: dict) -> dict[str, int]` — count findings by severity
- `probe_engine_version(spec) -> str` — run `spec.version_cmd`, parse output

**What to defer:** `redact_and_encrypt()` — Phase 1 can log a warning and skip encryption. The `redact_output: true` flag triggers stripping secret values from SARIF output, but AES encryption of raw output is Phase 2.

**Test file:** `tests/agents/security/test_secret_detection_redaction.py`
- Raw secret values never appear in SARIF output when `redact_output: true` (S-02)
- Tool runner raises `SecurityAssessmentError` for unexpected exit codes

---

### Step 4: ROE + SSRF Prevention + Surface Detection

**Depends on:** Step 2a (config), Step 2b (errors)

#### Step 4a: ROE + Scope Enforcement

**File:** `modules/backend/agents/security/roe.py` (~120 lines)
**Rego:** `config/roe/default.rego` (~30 lines)
**Spec:** Sections 2.3, 2.7.4, 2.7.6

**What to build:**
- `RulesOfEngagement(BaseModel)` — engagement_id, roe_sha256, scope_allowlist, scope_denylist, allowed_techniques, prohibited_actions, max_tool_calls, max_cost_usd, time_window_utc, human_gate_stages, credentials
- `AssessmentContext(BaseModel)` — target_name, target_path, target_url, target_framework, roe, authorisation_confirmed, assessment_state, pentest_task_tree
- `BLOCKED_NETWORKS` — RFC1918, link-local, cloud metadata
- `validate_url(url: str) -> str` — SSRF prevention (blocks private IPs)
- `resolve_and_pin(url: str) -> tuple[str, str]` — DNS rebinding defence
- `validate_target_path(path: str, roe: RulesOfEngagement) -> str` — path-based scope check for SAST (Phase 1)
- Custom exceptions: `RoeScopeViolationError`, `OpaUnavailableError`

**Phase 1 scope enforcement:** Path-based only. `validate_target_path()` checks that the target directory is within the ROE `scope_allowlist` patterns. No outbound HTTP in Phase 1, so no OPA HTTP client needed.

**Phase 2 additions (deferred):**
- `validate_scope(url, roe, config) -> str` — OPA HTTP client with retry (needed when DAST tools make outbound requests)
- `config/roe/default.rego` — OPA Rego policy (deployed alongside OPA service in Phase 2)

**Rego policy:** `config/roe/default.rego` — write the policy now (it's just a file), but the OPA HTTP integration that calls it is Phase 2.
- `allow` rule: url_in_scope AND NOT url_in_denylist AND NOT action_prohibited AND within_time_window
- Glob matching on scope_allowlist/denylist

**Test files:**
- `tests/agents/security/test_roe_enforcement.py` — `validate_target_path()` blocks out-of-scope paths; allows in-scope
- `tests/agents/security/test_ssrf_prevention.py` — `validate_url()` blocks all `BLOCKED_NETWORKS`, allows public URLs

#### Step 4b: Surface Detection

**File:** Add to `modules/backend/agents/security/tool_registry.py` (or separate `surface.py` ~50 lines)

**What to build:**
- `SurfaceDetectionResult(BaseModel)` — has_python, has_javascript, has_dockerfile, has_docker_compose, has_terraform, has_requirements_txt, has_pyproject_toml, detected_frameworks (list[str]), entry_points (list[str])
- `detect_surface(target_path: str) -> SurfaceDetectionResult` — walks the target directory, checks for file patterns:
  - `*.py` → has_python
  - `*.js`, `*.ts` → has_javascript
  - `Dockerfile*` → has_dockerfile
  - `docker-compose*.y*ml` → has_docker_compose
  - `*.tf` → has_terraform
  - `requirements*.txt` → has_requirements_txt
  - `pyproject.toml` → has_pyproject_toml
  - Framework detection: look for `fastapi`, `django`, `flask` in imports

**Test:** detect_surface on fixture apps returns correct flags.

---

### Step 5: SARIF Utilities

**Depends on:** Step 1 (models)
**File:** `modules/backend/agents/security/sarif.py` (~120 lines)

**What to build:**
- `load_sarif(path: str) -> list[dict]` — reads SARIF file, returns flattened finding list with normalised fields (cwe_id, file_path, line_number, severity, message, rule_id, tool_name)
- `merge_sarif(paths: list[str], output_path: str) -> str` — merges multiple SARIF files:
  - Deduplicates by (cwe_id, file_path, line_number) triple
  - When tools disagree on severity, takes highest (S-04)
  - Returns path to merged file
- `convert_to_sarif(source_path: str, source_format: str, tool_name: str)` — converts non-SARIF outputs:
  - `json` (ruff, pip-audit, hadolint) → SARIF 2.1.0
  - `jsonl` (nuclei) → SARIF 2.1.0

**Test file:** `tests/agents/security/test_sarif_merge.py`
- Deduplication by composite key (S-04)
- Severity normalisation — highest wins
- merge_sarif on empty list returns empty SARIF
- convert_to_sarif for ruff JSON produces valid SARIF

**Fixture:** `tests/fixtures/sarif/sample_merged.sarif.json` — 5 findings from 3 tools, 2 duplicates.

---

### Step 6: Security Scanning Adapter (PydanticAI tools)

**Depends on:** Steps 3, 4, 5
**File:** `modules/backend/agents/adapters/security_scanning.py` (~200 lines)
**Spec:** Section 1.2 adapter code

**What to build:**

One PydanticAI tool registration per Phase 1 capability. Each is a thin wrapper:

```
@agent.tool(name="security.code.scan")
async def scan_code(ctx, target_path: str) -> str:
    # Build CapabilityInput, call run_capability(), return summary string
```

Phase 1 tools:
- `security.code.scan` → Opengrep
- `security.code.lint` → Ruff --select S
- `security.deps.scan` → pip-audit
- `security.secrets.detect` → Betterleaks
- `security.container.scan` → Trivy
- `security.dockerfile.lint` → Hadolint
- `security.infra.scan` → Checkov

Utility tools:
- `security.detect_surface` → calls `detect_surface()` from Step 4b
- `security.merge_sarif` → calls `merge_sarif()` from Step 5
- `security.load_sarif` → calls `load_sarif()` from Step 5

**Deps type:** `ScanDeps(BaseAgentDeps)` — adds `tool_registry: SecurityToolRegistry`, `config: SecurityAssessmentConfig`, `evidence_path: str`

---

### Step 7: Agent YAMLs + Prompts (Phase 1 agents only)

**Depends on:** Step 6 (adapter tools)

#### 7a: Scanner Agent

**Files:**
- `config/agents/security/webapp/scanner/agent.yaml`
- `config/prompts/agents/security/webapp/scanner/system.md`

**YAML fields:**
- `agent_name: security.webapp.scanner.agent`
- `agent_type: vertical`
- `model.name: copilot:claude-haiku-4.5` (tool orchestration only)
- `tools:` security.code.scan, security.code.lint, security.deps.scan, security.secrets.detect, security.container.scan, security.dockerfile.lint, security.infra.scan, security.merge_sarif, security.detect_surface
- `execution.mode: container`
- `max_budget_usd: 1.50`
- `produces_artifact: false`

**Prompt:** Spec Section 5.2 verbatim.

#### 7b: Triage Agent

**Files:**
- `config/agents/security/webapp/triage/agent.yaml`
- `config/prompts/agents/security/webapp/triage/system.md`

**YAML fields:**
- `agent_name: security.webapp.triage.agent`
- `model.name: copilot:claude-sonnet-4.6` (code comprehension for FP assessment)
- `tools:` security.load_sarif, read_file
- `max_budget_usd: 5.00`

**Prompt:** Spec Section 5.4 verbatim.

#### 7c: Reporter Agent

**Files:**
- `config/agents/security/webapp/reporter/agent.yaml`
- `config/prompts/agents/security/webapp/reporter/system.md`

**YAML fields:**
- `agent_name: security.webapp.reporter.agent`
- `model.name: copilot:claude-sonnet-4.6` (structured writing)
- `tools: []` (no tools — input only)
- `max_budget_usd: 5.00`
- `produces_artifact: true`
- `artifact_type: security_report`

**Prompt:** Spec Section 5.7 verbatim.

---

### Step 8: Workflow Template (Phase 1 version)

**File:** `config/workflow_templates/security.webapp-assessment.workflow.yaml`
**Spec:** Section 6.2 — Phase 1 subset

Phase 1 workflow: **scan → triage → report** only. Three steps.
No scope/planner step (Phase 2), no recon (Phase 2), no appsec (Phase 2), no exploit (Phase 3), no validate (Phase 3).

```yaml
steps:
  - id: scan
    capability: security.webapp.scanner
    condition: "@context.target_path != null"
    environment: container
    container_image: "security-assessment-worker:latest"
    ...

  - id: triage
    capability: security.webapp.triage
    environment: container
    depends_on: [scan]
    ...

  - id: report
    capability: security.webapp.reporter
    environment: container
    depends_on: [triage]
    produces_artifact: true
    artifact_type: security_report
    ...
```

Gate mode: all steps `off`.
Budget: $15.00 (Phase 1 ceiling).

---

### Step 9: Test Fixtures

**Depends on:** Steps 1-5 (models, SARIF utilities)

#### 9a: Vulnerable FastAPI App

**Directory:** `tests/fixtures/vulnerable_fastapi_app/`

A minimal FastAPI app with known vulnerabilities that SAST tools will detect:
- `main.py` — SQL injection via `text(f"SELECT * FROM users WHERE id = {user_id}")"`
- `config.py` — hardcoded API key: `API_KEY = "sk-live-abc123def456"`
- `routes/users.py` — IDOR: `/api/users/{id}` with no ownership check
- `auth.py` — weak JWT secret: `SECRET = "password123"`
- `requirements.txt` — include a known-vulnerable package version
- `Dockerfile` — missing USER directive (hadolint finding)

**Expected:** >= 5 TRUE_POSITIVE across SAST tools.

#### 9b: Clean FastAPI App

**Directory:** `tests/fixtures/clean_fastapi_app/`

A minimal FastAPI app with no true-positive findings:
- ORM queries only (no raw SQL)
- No hardcoded secrets (uses env vars)
- All endpoints auth-guarded with ownership checks
- Pinned, non-vulnerable dependencies
- Dockerfile follows best practices

**Expected:** 0 TRUE_POSITIVE after triage.

#### 9c: SARIF + ROE Fixtures

- `tests/fixtures/sarif/sample_merged.sarif.json` — 5 findings from 3 tools, 2 duplicates
- `tests/fixtures/roe/sample_roe.yaml` — known-good ROE with scope, prohibited actions
- `tests/fixtures/secret_detection/raw_output.json` — sample secret values for redaction testing

---

### Step 10: Integration Tests

**Depends on:** All previous steps

| Test File | Invariants | What It Tests |
|---|---|---|
| `test_models.py` | T-01, R-01, R-02, R-04 | Pydantic validators (Step 1 tests) |
| `test_scanner_exit_codes.py` | S-03 | Exit code 1 = success |
| `test_sarif_merge.py` | S-04 | Dedup, severity normalisation |
| `test_secret_detection_redaction.py` | S-02 | No secret values in output |
| `test_triage_threshold.py` | T-01, T-02, T-03, T-04 | FP threshold, rationale, completeness |
| `test_roe_enforcement.py` | ROE-01 | Path-based scope validation (Phase 1); OPA HTTP validation (Phase 2) |
| `test_ssrf_prevention.py` | — | validate_url blocks private addresses |
| `test_risk_score.py` | R-02 | Composite formula |
| `test_evidence_integrity.py` | EV-01, EV-02 | SHA-256 manifest |
| `test_pipeline_sast.py` | S-01 | End-to-end SAST against fixture SARIF data (uses fixture output, not live tool binaries — CI-safe) |

**Note on `test_pipeline_sast.py`:** This test validates the scan → triage → report pipeline using **pre-generated fixture SARIF** (from `tests/fixtures/sarif/`), not live security tool binaries. Live tool integration tests require the `security-assessment-worker` Docker image (Phase 2). Phase 1 CI tests are fully offline.

**conftest.py:** `tests/agents/security/conftest.py` — shared fixtures (vulnerable_app, clean_app, sample_roe, sample_sarif)

---

## File Inventory

### New Python Files (10)

| File | Lines (est.) | Depends On |
|---|---|---|
| `modules/backend/agents/security/__init__.py` | 5 | — |
| `modules/backend/agents/security/models.py` | 350 | — |
| `modules/backend/agents/security/config.py` | 10 | core/config (thin re-export) |
| `modules/backend/agents/security/errors.py` | 80 | — |
| `modules/backend/agents/security/evidence.py` | 80 | — |
| `modules/backend/agents/security/tool_registry.py` | 150 | models |
| `modules/backend/agents/security/tool_runner.py` | 150 | registry, config |
| `modules/backend/agents/security/roe.py` | 120 | config, errors |
| `modules/backend/agents/security/sarif.py` | 120 | models |
| `modules/backend/agents/adapters/security_scanning.py` | 200 | registry, runner, roe, sarif |

### Modified Platform Files (2)

| File | Change |
|---|---|
| `modules/backend/core/config_schema.py` | Add `SecurityAssessmentSchema(_StrictBase)` |
| `modules/backend/core/config.py` | Add `_security_assessment` to `AppConfig`, add property |

### New Config Files (6)

| File | Purpose |
|---|---|
| `config/settings/security_assessment.yaml` | WASA settings (follows platform YAML config pattern) |
| `config/security/tools.yaml` | Security tool registry (Phase 1 tools) |
| `config/roe/default.rego` | OPA scope enforcement policy (written now, OPA integration Phase 2) |
| `config/agents/security/webapp/scanner/agent.yaml` | Scanner agent config |
| `config/agents/security/webapp/triage/agent.yaml` | Triage agent config |
| `config/agents/security/webapp/reporter/agent.yaml` | Reporter agent config |

### New Prompt Files (3)

| File | Source |
|---|---|
| `config/prompts/agents/security/webapp/scanner/system.md` | Spec Section 5.2 |
| `config/prompts/agents/security/webapp/triage/system.md` | Spec Section 5.4 |
| `config/prompts/agents/security/webapp/reporter/system.md` | Spec Section 5.7 |

### New Workflow Template (1)

| File | Purpose |
|---|---|
| `config/workflow_templates/security.webapp-assessment.workflow.yaml` | Phase 1: scan → triage → report |

### New Test Files (10)

| File | Invariants |
|---|---|
| `tests/agents/security/conftest.py` | Shared fixtures |
| `tests/agents/security/test_models.py` | T-01, R-01, R-02, R-04 |
| `tests/agents/security/test_scanner_exit_codes.py` | S-03 |
| `tests/agents/security/test_sarif_merge.py` | S-04 |
| `tests/agents/security/test_secret_detection_redaction.py` | S-02 |
| `tests/agents/security/test_triage_threshold.py` | T-01..T-04 |
| `tests/agents/security/test_roe_enforcement.py` | ROE-01 |
| `tests/agents/security/test_ssrf_prevention.py` | SSRF prevention |
| `tests/agents/security/test_risk_score.py` | R-02 |
| `tests/agents/security/test_evidence_integrity.py` | EV-01, EV-02 |

### Fixture Directories (3)

| Directory | Purpose |
|---|---|
| `tests/fixtures/vulnerable_fastapi_app/` | Deliberate vulns for SAST |
| `tests/fixtures/clean_fastapi_app/` | Clean app (0 TPs expected) |
| `tests/fixtures/sarif/` + `roe/` + `secret_detection/` | Test data |

---

## Platform Reuse (DO NOT rebuild)

| Capability | Existing Code | How WASA Uses It |
|---|---|---|
| Gate/approval | `gate.py`, `gate_models.py` | All steps `gate: off` in Phase 1 |
| Audit trail | `models/execution_record.py` | Extend `DecisionType` in Phase 2 |
| Container isolation | `container_backend.py` | Use with `container_image: security-assessment-worker:latest` |
| Subprocess execution | `tools/run_command.py` pattern | Follow `_run_local()` pattern in `tool_runner.py` |
| Verification pipeline | `verification.py`, `check_registry.py` | Phase 2: register WASA Tier 2 checks |
| Tool registration | `tools/registry.py` | Register security tools as PydanticAI tools |
| Agent config schema | `schemas/agent_config.py` | Standard YAML structure |
| Workflow dispatch | `workflow_run_waves.py` | Standard step execution |
| Artifact persistence | `MissionArtifact` model | `produces_artifact: true` on report step |

---

## What Phase 1 Does NOT Build

- Planner agent + PTT (Phase 2)
- Recon agent + nmap/ffuf/arjun tools (Phase 2)
- AppSec agent + `extract_api_surface` tool (Phase 2)
- Exploit agent + sqlmap/nuclei/jwt-cli tools (Phase 3)
- Validator agent — deterministic PoC replay (Phase 3)
- Digest agent — HTTP response quarantine (Phase 2)
- Burp MCP / mitmproxy integration (Phase 2)
- `security_proxy.py`, `security_auth.py` adapters (Phase 2/3)
- `security-assessment-worker` Dockerfile (Phase 2 — Phase 1 runs tools locally or validates against fixtures)
- Confidence calibration model (Phase 2 — `calibration_version` field present but unused)
- DAST authorisation gates (Phase 2)
- Network egress policy on containers (Phase 2)

---

## Commit Strategy

One commit per step (or sub-step for parallel groups). Each commit must:
1. Pass all existing tests (zero regressions)
2. Pass all new tests for that step
3. Be independently reviewable

Suggested commit sequence:
1. `models.py` + `test_models.py`
2. `config.py` + `errors.py` + `evidence.py` + `test_evidence_integrity.py`
3. `tool_registry.py` + `tools.yaml` + `test_scanner_exit_codes.py`
4. `tool_runner.py` + `sarif.py` + `test_sarif_merge.py` + `test_secret_detection_redaction.py`
5. `roe.py` + `default.rego` + `test_roe_enforcement.py` + `test_ssrf_prevention.py`
6. `security_scanning.py` (adapter) + `test_risk_score.py`
7. Agent YAMLs + prompts + workflow template
8. Fixture apps + `conftest.py` + `test_triage_threshold.py`
9. `test_pipeline_sast.py` (end-to-end)
