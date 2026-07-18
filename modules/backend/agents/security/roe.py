"""WASA Rules of Engagement (ROE) — scope enforcement and SSRF prevention.

Every tool call that reads target files or makes outbound requests is
validated against the ROE before execution. This is harness-level
enforcement, not in-prompt guardrails. Spec Sections 2.3, 2.7.4, 2.7.6.

Phase 1: path-based scope checks only (validate_target_path).
Phase 2: OPA HTTP client (validate_scope) for DAST tool calls.
"""

from __future__ import annotations

import hashlib
import ipaddress
import socket
from fnmatch import fnmatch
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from modules.backend.agents.security.errors import SecurityAssessmentError, SecurityErrorCode
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# ROE schema
# ---------------------------------------------------------------------------


class RulesOfEngagement(BaseModel):
    """Machine-readable scope contract. Validated by OPA on every tool call."""

    engagement_id: str
    roe_sha256: str = Field(
        description="SHA-256 of the ROE document for non-repudiation",
    )
    scope_allowlist: list[str] = Field(
        min_length=1,
        description="Allowed target FQDN/CIDR/URL/path patterns",
    )
    scope_denylist: list[str] = Field(
        default_factory=list,
        description="Explicitly excluded patterns",
    )
    allowed_techniques: list[str] = Field(
        default=["recon", "scanning", "enumeration", "authenticated_testing"],
    )
    prohibited_actions: list[str] = Field(
        default=[
            "DROP/TRUNCATE SQL",
            "os-shell",
            "lateral_movement",
            "password_spray>5/account",
            "DoS",
            "data_modification",
        ],
    )
    max_tool_calls: int = Field(default=200, ge=10)
    max_cost_usd: float = Field(default=50.0, ge=1.0)
    time_window_utc: str | None = Field(
        default=None,
        description="ISO 8601 interval: allowed testing window",
    )
    human_gate_stages: list[int] = Field(
        default=[2, 3, 4],
        description="Stages requiring human approval before execution",
    )


class AssessmentContext(BaseModel):
    """Mission Context Document structure for security assessments."""

    target_name: str
    target_path: str | None = None
    target_url: str | None = None
    target_framework: str | None = None
    roe: RulesOfEngagement
    authorisation_confirmed: bool = Field(default=False)
    authorisation_confirmed_by: str | None = None
    authorisation_confirmed_at: str | None = None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class RoeScopeViolationError(SecurityAssessmentError):
    """Raised when a tool call targets a resource outside the ROE scope."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(
            code=SecurityErrorCode.ROE_SCOPE_VIOLATION,
            message=message,
            details=details,
        )


class OpaUnavailableError(SecurityAssessmentError):
    """Raised when the OPA policy engine is unreachable."""

    def __init__(self, message: str) -> None:
        super().__init__(
            code=SecurityErrorCode.OPA_UNAVAILABLE,
            message=message,
        )


# ---------------------------------------------------------------------------
# SSRF prevention
# ---------------------------------------------------------------------------

BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local + cloud metadata
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def validate_url(url: str) -> str:
    """Validate URL before agent fetches it. Raises ValueError if blocked.

    Blocks private IPs (RFC1918), loopback, link-local, cloud metadata
    (169.254.169.254), and non-HTTP schemes.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Blocked scheme: {parsed.scheme}")
    if not parsed.hostname:
        raise ValueError(f"No hostname in URL: {url}")
    try:
        for _, _, _, _, addr in socket.getaddrinfo(parsed.hostname, None):
            ip = ipaddress.ip_address(addr[0])
            for network in BLOCKED_NETWORKS:
                if ip in network:
                    raise ValueError(f"Blocked: {url} resolves to private address {ip}")
    except socket.gaierror:
        raise ValueError(f"Cannot resolve hostname: {parsed.hostname}")
    return url


def resolve_and_pin(url: str) -> tuple[str, str]:
    """Validate URL and return (url, resolved_ip) for pinned connections.

    DNS rebinding defence: resolve once and pin the IP so downstream
    tool wrappers can use --resolve / --connect-to flags.
    """
    parsed = urlparse(url)
    validate_url(url)
    addrs = socket.getaddrinfo(parsed.hostname, None)
    resolved_ip = addrs[0][4][0]
    return url, resolved_ip


# ---------------------------------------------------------------------------
# Path-based scope validation (Phase 1)
# ---------------------------------------------------------------------------


def validate_target_path(
    path: str,
    roe: RulesOfEngagement,
) -> str:
    """Validate that a target path is within the ROE scope_allowlist.

    Phase 1 scope enforcement for SAST — checks that the path matches
    at least one allowlist pattern and no denylist pattern.

    Raises:
        RoeScopeViolationError: If the path is outside scope.
    """
    resolved = str(Path(path).resolve())

    # Check denylist first
    for pattern in roe.scope_denylist:
        if fnmatch(resolved, pattern) or fnmatch(path, pattern):
            raise RoeScopeViolationError(
                f"Path '{path}' matches denylist pattern '{pattern}'",
                details={"path": path, "pattern": pattern},
            )

    # Check allowlist
    for pattern in roe.scope_allowlist:
        if fnmatch(resolved, pattern) or fnmatch(path, pattern):
            return path

    raise RoeScopeViolationError(
        f"Path '{path}' is not in ROE scope_allowlist: {roe.scope_allowlist}",
        details={"path": path, "scope_allowlist": roe.scope_allowlist},
    )


def verify_roe_hash(roe: RulesOfEngagement, expected_sha256: str) -> None:
    """Verify ROE integrity by checking its SHA-256 hash.

    Called at the start of every phase. If the ROE changes mid-assessment,
    the phase halts (ROE-02).
    """
    roe_json = roe.model_dump_json(exclude={"roe_sha256"})
    actual = hashlib.sha256(roe_json.encode()).hexdigest()
    if actual != expected_sha256:
        raise SecurityAssessmentError(
            code=SecurityErrorCode.ROE_HASH_MISMATCH,
            message=f"ROE hash changed: expected {expected_sha256[:16]}..., got {actual[:16]}...",
            details={"expected": expected_sha256, "actual": actual},
        )
