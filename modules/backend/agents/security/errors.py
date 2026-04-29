"""WASA error taxonomy.

Typed errors for the security assessment pipeline. Every error has a
machine-readable code, HTTP status, message template, retry policy,
and documented recovery action. Spec Section 2.6.

Phase 1 codes only. Phase 2/3 codes (DAST_*, APPSEC_*, EXPLOIT_*,
EVIDENCE_PROXY_BYPASS, BURP_MCP_UNAVAILABLE) added when those phases
are implemented.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SecurityErrorCode(str, Enum):
    """Machine-readable error codes for WASA assessment failures."""

    # Scope enforcement
    ROE_SCOPE_VIOLATION = "ROE_SCOPE_VIOLATION"
    ROE_HASH_MISMATCH = "ROE_HASH_MISMATCH"
    ROE_MISSING = "ROE_MISSING"

    # Scanner
    SCANNER_BINARY_NOT_FOUND = "SCANNER_BINARY_NOT_FOUND"
    SCANNER_TIMEOUT = "SCANNER_TIMEOUT"
    SARIF_MERGE_FAILED = "SARIF_MERGE_FAILED"
    SARIF_TRUNCATED = "SARIF_TRUNCATED"

    # Triage
    TRIAGE_BUDGET_EXCEEDED = "TRIAGE_BUDGET_EXCEEDED"

    # Infrastructure
    OPA_UNAVAILABLE = "OPA_UNAVAILABLE"
    COST_LIMIT_EXCEEDED = "COST_LIMIT_EXCEEDED"


@dataclass(frozen=True)
class SecurityErrorSpec:
    """Specification for a single error code."""

    code: SecurityErrorCode
    http_status: int
    message_template: str
    retryable: bool
    retry_after_seconds: int | None
    recovery_action: str


SECURITY_ERROR_SPECS: dict[SecurityErrorCode, SecurityErrorSpec] = {
    SecurityErrorCode.ROE_SCOPE_VIOLATION: SecurityErrorSpec(
        code=SecurityErrorCode.ROE_SCOPE_VIOLATION,
        http_status=403,
        message_template=(
            "Tool call to {target} is outside ROE scope. "
            "Allowed: {scope_allowlist}."
        ),
        retryable=False,
        retry_after_seconds=None,
        recovery_action=(
            "Log as breach event in audit trail. Halt current tool call. "
            "Continue assessment with in-scope targets."
        ),
    ),
    SecurityErrorCode.ROE_HASH_MISMATCH: SecurityErrorSpec(
        code=SecurityErrorCode.ROE_HASH_MISMATCH,
        http_status=409,
        message_template="ROE hash changed mid-assessment: expected {expected}, got {actual}.",
        retryable=False,
        retry_after_seconds=None,
        recovery_action="Halt phase. Require re-authorisation.",
    ),
    SecurityErrorCode.ROE_MISSING: SecurityErrorSpec(
        code=SecurityErrorCode.ROE_MISSING,
        http_status=422,
        message_template="Rules of Engagement not provided.",
        retryable=False,
        retry_after_seconds=None,
        recovery_action="Return error to operator. Do not proceed.",
    ),
    SecurityErrorCode.SCANNER_BINARY_NOT_FOUND: SecurityErrorSpec(
        code=SecurityErrorCode.SCANNER_BINARY_NOT_FOUND,
        http_status=422,
        message_template="Scanner binary not found: {tool_name}.",
        retryable=False,
        retry_after_seconds=None,
        recovery_action="Add to scanners_failed. Continue with remaining scanners.",
    ),
    SecurityErrorCode.SCANNER_TIMEOUT: SecurityErrorSpec(
        code=SecurityErrorCode.SCANNER_TIMEOUT,
        http_status=504,
        message_template="Scanner {tool_name} timed out after {timeout}s.",
        retryable=False,
        retry_after_seconds=None,
        recovery_action="Mark scanner as failed. Continue with partial results.",
    ),
    SecurityErrorCode.SARIF_MERGE_FAILED: SecurityErrorSpec(
        code=SecurityErrorCode.SARIF_MERGE_FAILED,
        http_status=500,
        message_template="Failed to merge SARIF files: {detail}.",
        retryable=False,
        retry_after_seconds=None,
        recovery_action="Return individual SARIF paths.",
    ),
    SecurityErrorCode.SARIF_TRUNCATED: SecurityErrorSpec(
        code=SecurityErrorCode.SARIF_TRUNCATED,
        http_status=200,
        message_template="SARIF output truncated at {max_findings} findings.",
        retryable=False,
        retry_after_seconds=None,
        recovery_action="Proceed with truncated results. Log warning.",
    ),
    SecurityErrorCode.TRIAGE_BUDGET_EXCEEDED: SecurityErrorSpec(
        code=SecurityErrorCode.TRIAGE_BUDGET_EXCEEDED,
        http_status=200,
        message_template="Triage budget exceeded at {count} findings (max {max_count}).",
        retryable=False,
        retry_after_seconds=None,
        recovery_action="Triage remaining findings as UNCERTAIN.",
    ),
    SecurityErrorCode.OPA_UNAVAILABLE: SecurityErrorSpec(
        code=SecurityErrorCode.OPA_UNAVAILABLE,
        http_status=503,
        message_template="OPA policy engine unavailable at {endpoint}.",
        retryable=True,
        retry_after_seconds=5,
        recovery_action=(
            "Retry once. If still unavailable, halt assessment — "
            "cannot validate scope without OPA."
        ),
    ),
    SecurityErrorCode.COST_LIMIT_EXCEEDED: SecurityErrorSpec(
        code=SecurityErrorCode.COST_LIMIT_EXCEEDED,
        http_status=200,
        message_template="Cost limit ${limit} exceeded at ${current}. Assessment terminated.",
        retryable=False,
        retry_after_seconds=None,
        recovery_action="Skip remaining phases. Proceed to REPORT with findings so far.",
    ),
}


class SecurityAssessmentError(Exception):
    """Typed exception for WASA assessment failures.

    Always carries a SecurityErrorCode so callers can match on the code
    without parsing message strings.
    """

    def __init__(
        self,
        code: SecurityErrorCode,
        message: str,
        details: dict | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{code.value}] {message}")

    @property
    def spec(self) -> SecurityErrorSpec:
        return SECURITY_ERROR_SPECS[self.code]
