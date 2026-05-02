"""WASA structured output models.

Pydantic models for all security assessment agent outputs. These are the
executable form of Spec Section 4.3. If code and spec diverge, the spec
(docs/97-plans/66-spec-webapp-security-assessment.md) is authoritative.

Layer boundary: these are *agent output* models consumed by the dispatch
loop, reporter, and API layer. Tool-layer I/O contracts (CapabilityInput,
SarifCapabilityOutput) live in tool_registry.py — different layer, no
cross-import.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SeverityLevel(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFORMATIONAL = "INFORMATIONAL"


class TriageVerdict(str, Enum):
    TRUE_POSITIVE = "TRUE_POSITIVE"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    UNCERTAIN = "UNCERTAIN"


class OWASPCategory(str, Enum):
    A01_BROKEN_ACCESS_CONTROL = "A01"
    A02_CRYPTOGRAPHIC_FAILURES = "A02"
    A03_INJECTION = "A03"
    A04_INSECURE_DESIGN = "A04"
    A05_SECURITY_MISCONFIGURATION = "A05"
    A06_VULNERABLE_COMPONENTS = "A06"
    A07_AUTH_FAILURES = "A07"
    A08_SOFTWARE_INTEGRITY = "A08"
    A09_LOGGING_FAILURES = "A09"
    A10_SSRF = "A10"


class ExploitStage(int, Enum):
    """Human-in-the-loop staging model (spec doc 022 Section 4.5)."""

    PASSIVE_RECON = 0
    ACTIVE_UNAUTH = 1
    AUTHENTICATED_TESTING = 2
    POC_EXPLOITATION = 3
    DESTRUCTIVE = 4


class RemediationPriority(str, Enum):
    IMMEDIATE = "IMMEDIATE"
    SHORT_TERM = "SHORT_TERM"
    MEDIUM_TERM = "MEDIUM_TERM"
    BACKLOG = "BACKLOG"


class AssessmentPhase(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PLANNING = "PLANNING"
    SCANNING = "SCANNING"
    TRIAGING = "TRIAGING"
    ANALYSING = "ANALYSING"
    EXPLOITING = "EXPLOITING"
    REPORTING = "REPORTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Assessment state
# ---------------------------------------------------------------------------

class AssessmentState(BaseModel):
    """Tracks current progress through the assessment pipeline."""

    phase: AssessmentPhase = Field(default=AssessmentPhase.NOT_STARTED)
    scanner_summary: dict | None = Field(
        default=None,
        description="{tool: {status, finding_count, duration_ms}}",
    )
    triaged_findings_count: int | None = None
    appsec_findings_count: int | None = None
    exploit_stage_reached: ExploitStage | None = None
    dast_performed: bool = Field(default=False)
    report_artifact_id: str | None = None
    total_cost_usd: float = Field(default=0.0, ge=0.0)
    total_tool_calls: int = Field(default=0, ge=0)


# ---------------------------------------------------------------------------
# Credentials (Vault refs — never plaintext)
# ---------------------------------------------------------------------------

class TestCredential(BaseModel):
    """Per-role credential for authenticated DAST testing.

    Values are Vault secret references, not plaintext. The agent
    receives the role alias only; Vault resolves at runtime.
    """

    role: str = Field(description="Alias: 'user_a', 'admin', 'teller'")
    vault_path: str = Field(
        description="Vault path: 'secret/data/wasa/{engagement_id}/{role}'",
    )
    auth_method: str = Field(
        default="cookie",
        description="cookie | bearer | basic | oauth2_pkce",
    )
    target_login_url: str | None = Field(
        default=None,
        description="URL to POST credentials for session establishment",
    )
    notes: str | None = Field(
        default=None,
        description="Role description: 'Standard retail customer'",
    )


# ---------------------------------------------------------------------------
# Pentest Task Tree
# ---------------------------------------------------------------------------

class PentestTask(BaseModel):
    """Single node in the Pentest Task Tree (PTT)."""

    task_id: str
    phase: str = Field(
        description="SCOPE | SCAN | RECON | TRIAGE | APPSEC | EXPLOIT | REPORT",
    )
    wstg_id: str | None = Field(
        default=None,
        description="OWASP WSTG test case ID, e.g. WSTG-ATHN-01",
    )
    description: str
    target: str = Field(description="URL, IP, or file path this task targets")
    stage: ExploitStage
    status: str = Field(
        default="pending",
        description="pending | running | completed | failed | skipped",
    )
    depends_on: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Core finding model
# ---------------------------------------------------------------------------

class Finding(BaseModel):
    """Unified finding model across all assessment phases."""

    finding_id: str
    title: str = Field(min_length=5)
    description: str = Field(min_length=20)
    severity: SeverityLevel
    owasp_category: OWASPCategory
    cwe_id: str | None = Field(default=None, description="CWE-NNN format")
    wstg_id: str | None = Field(
        default=None, description="OWASP WSTG test case ID",
    )

    # Location
    file_path: str | None = Field(
        default=None, description="Source file for SAST/AppSec findings",
    )
    line_number: int | None = Field(default=None, ge=1)
    url: str | None = Field(
        default=None, description="Target URL for DAST findings",
    )
    http_method: str | None = None

    # Evidence
    evidence: str = Field(
        description="Code snippet, HTTP request/response, or tool output",
    )
    poc: str | None = Field(
        default=None,
        description="Reproducible PoC: curl command, script, or Burp request",
    )
    poc_validated: bool = Field(
        default=False, description="True if PoC was executed and confirmed",
    )

    # Metadata
    source_phase: str = Field(
        description="scan | recon | triage | appsec | exploit",
    )
    source_tool: str = Field(
        description="Tool or agent that produced this finding",
    )
    triage_verdict: TriageVerdict | None = None
    fp_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    triage_rationale: str | None = None
    remediation: str = Field(min_length=20)

    # CVSS + enrichment
    cvss_score: float | None = Field(default=None, ge=0.0, le=10.0)
    cvss_vector: str | None = Field(
        default=None, description="CVSS v4.0 vector string",
    )
    epss_score: float | None = Field(default=None, ge=0.0, le=1.0)
    epss_percentile: float | None = Field(default=None, ge=0.0, le=1.0)
    kev_listed: bool = Field(default=False)
    ssvc_outcome: str | None = Field(
        default=None, description="Track | Track* | Attend | Act",
    )

    # Dedup fingerprint
    dedup_hash: str | None = Field(
        default=None,
        description="SHA-256 of canonical (cwe, url, parameter, sink, method, auth_state)",
    )
    match_based_id: str | None = Field(
        default=None,
        description="Stable structural ID from SAST engine",
    )

    # Calibration
    raw_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    calibrated_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    calibration_version: str | None = None

    # Validation (producer never verifies own output)
    validated: bool = Field(
        default=False, description="True only if validator agent confirmed",
    )
    validated_by: str | None = Field(
        default=None, description="'validator' or null — never producing agent",
    )
    validator_evidence_hash: str | None = None

    @field_validator("triage_rationale", mode="before")
    @classmethod
    def rationale_required_for_fp(cls, v: str | None, info: object) -> str | None:
        data = info.data if hasattr(info, "data") else {}
        if data.get("triage_verdict") == TriageVerdict.FALSE_POSITIVE and not v:
            raise ValueError(
                "triage_rationale required for FALSE_POSITIVE verdict",
            )
        return v

    @field_validator("severity", mode="before")
    @classmethod
    def normalise_severity(cls, v: object) -> object:
        if isinstance(v, str):
            return v.upper()
        return v

    @model_validator(mode="after")
    def require_location(self) -> Finding:
        """A finding must have at least one location."""
        has_file = self.file_path is not None and self.line_number is not None
        has_url = self.url is not None
        if not has_file and not has_url:
            raise ValueError(
                "Finding must have (file_path + line_number) or (url)",
            )
        return self


# ---------------------------------------------------------------------------
# Digest agent output
# ---------------------------------------------------------------------------

class HttpResponseSummary(BaseModel):
    """Typed summary of raw HTTP response. Free-text fields clamped to 200 chars."""

    status: int
    content_type: str | None = None
    interesting_urls: list[str] = Field(default_factory=list, max_length=20)
    forms: list[dict[str, str]] = Field(default_factory=list, max_length=20)
    error_signals: list[str] = Field(default_factory=list, max_length=10)
    auth_indicators: list[str] = Field(default_factory=list, max_length=5)
    notes: str = Field(default="", max_length=200)


# ---------------------------------------------------------------------------
# Validator agent output
# ---------------------------------------------------------------------------

class ValidationResult(BaseModel):
    """Non-LLM deterministic validation result."""

    finding_id: str
    validated: bool
    primitive: str = Field(
        description="canary_read | canary_write | oob_dns | time_based | reflected_callback | status_diff",
    )
    reproduction_request: str
    expected_observable: str
    actual_observable: str
    evidence_hash: str
    validator_version: str
    duration_seconds: float


# ---------------------------------------------------------------------------
# Report components
# ---------------------------------------------------------------------------

class AttackPath(BaseModel):
    """Chained attack narrative connecting multiple findings."""

    path_id: str
    title: str
    scenario: str = Field(description="Step-by-step attack narrative")
    source_findings: list[str] = Field(
        min_length=2,
        description="Finding IDs that form this chain",
    )
    combined_severity: SeverityLevel
    attacker_prerequisites: str
    business_impact: str


class RemediationItem(BaseModel):
    """Single remediation action in the roadmap."""

    finding_ref: str
    priority: RemediationPriority
    action: str = Field(min_length=20)
    effort_estimate: str
    code_example: str | None = None


class CoverageCell(BaseModel):
    """Single cell in the coverage matrix."""

    endpoint: str
    vuln_class: str = Field(description="OWASP category or CWE")
    auth_zone: str = Field(description="unauth | user_a | admin | etc.")
    tested: bool
    finding_ids: list[str] = Field(default_factory=list)


class CoverageMatrix(BaseModel):
    """Tracks what was tested vs not."""

    total_cells: int
    tested_cells: int
    untested_cells: int
    coverage_pct: float = Field(ge=0.0, le=100.0)
    gaps: list[CoverageCell] = Field(
        description="Untested cells — the coverage blind spots",
    )


# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------

class SecurityAssessmentReport(BaseModel):
    """Final structured security assessment report. Primary deliverable."""

    report_id: str
    target_name: str
    target_url: str | None = None
    target_path: str | None = None
    assessment_date: str
    engagement_id: str
    roe_sha256: str
    assessor: str = Field(default="Mission Control Security Assessment")

    # Risk
    overall_risk_score: float = Field(ge=0.0, le=10.0)
    overall_risk_posture: SeverityLevel
    executive_summary: str = Field(min_length=300)

    # Findings
    finding_counts: dict = Field(description="{severity: count}")
    owasp_coverage: dict = Field(description="{A01..A10: [finding_ids]}")
    confirmed_findings: list[Finding]
    suppressed_findings: list[Finding] = Field(
        default_factory=list, description="FP findings for audit trail",
    )

    # Analysis
    attack_paths: list[AttackPath] = Field(default_factory=list)
    remediation_roadmap: list[RemediationItem]

    # Assessment metadata
    phases_completed: list[str]
    scanners_run: list[str]
    dast_performed: bool
    exploit_stage_reached: ExploitStage
    total_tool_calls: int
    total_cost_usd: float
    duration_hours: float
    assessment_scope: str
    evidence_manifest_sha256: str

    # Coverage tracking
    coverage: CoverageMatrix | None = Field(default=None)

    # Validation summary
    validation_summary: dict = Field(
        default_factory=dict,
        description="{validated: N, rejected: N, pending: N}",
    )

    known_limitations: list[str] = Field(
        min_length=1,
        description="Documented gaps: timing attacks, race conditions, etc.",
    )
