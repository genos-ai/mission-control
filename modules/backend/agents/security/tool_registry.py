"""WASA Security Tool Registry — capability-based tool resolution.

Security tools are resolved by capability, not by name. Agents ask for
a capability (e.g. security.code.scan); the registry resolves which
binary to invoke. Swapping a tool is a YAML config change, not a code
change. Spec Section 1.2.

Layer boundary: I/O contracts (CapabilityInput, SarifCapabilityOutput)
are tool-layer types defined here. Agent output models (Finding,
SecurityAssessmentReport) live in models.py — different layer.
"""

from __future__ import annotations

import shutil
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Capability enum
# ---------------------------------------------------------------------------


class ToolCapability(str, Enum):
    """security.{domain}.{verb} naming convention.

    Phase 1 capabilities only. Phase 2/3 additions (NETWORK_DISCOVER,
    WEB_DISCOVER, PARAMS_DISCOVER, ROUTES_DISCOVER, WEB_SCAN,
    INJECTION_TEST_SQLI, TLS_AUDIT, AUTH_TEST_JWT) added when those
    phases are implemented.
    """

    # Code analysis
    CODE_SCAN = "security.code.scan"
    CODE_LINT = "security.code.lint"

    # Dependencies
    DEPS_SCAN = "security.deps.scan"

    # Secrets
    SECRETS_DETECT = "security.secrets.detect"

    # Container / infrastructure
    CONTAINER_SCAN = "security.container.scan"
    DOCKERFILE_LINT = "security.dockerfile.lint"
    INFRA_SCAN = "security.infra.scan"

    # Phase 2/3 (declared for CAPABILITY_OUTPUT_CONTRACTS completeness)
    NETWORK_DISCOVER = "security.network.discover"
    WEB_DISCOVER = "security.web.discover"
    PARAMS_DISCOVER = "security.params.discover"
    ROUTES_DISCOVER = "security.routes.discover"
    WEB_SCAN = "security.web.scan"
    INJECTION_TEST_SQLI = "security.injection.test_sqli"
    TLS_AUDIT = "security.tls.audit"
    AUTH_TEST_JWT = "security.auth.test_jwt"


class CapabilityMode(str, Enum):
    """How multiple engines for the same capability are executed."""

    FALLBACK = "fallback"
    ENSEMBLE = "ensemble"


# ---------------------------------------------------------------------------
# Standardised I/O contracts (tool layer, not agent layer)
# ---------------------------------------------------------------------------


class CapabilityInput(BaseModel):
    """Standard input for all capabilities."""

    target_path: str | None = None
    target_url: str | None = None
    target_host: str | None = None
    output_path: str
    scope: dict = Field(default_factory=dict)


class SarifCapabilityOutput(BaseModel):
    """Standard output for scanning capabilities (SARIF-shaped)."""

    capability: str
    engine_name: str
    engine_version: str
    sarif_path: str
    finding_count: int
    severity_counts: dict[str, int]
    duration_seconds: float
    exit_code: int
    partial: bool = False
    raw_output_path: str | None = None


class ReconCapabilityOutput(BaseModel):
    """Standard output for reconnaissance capabilities."""

    capability: str
    engine_name: str
    engine_version: str
    output_path: str
    endpoints_discovered: int
    services_discovered: int
    duration_seconds: float
    raw_output_path: str | None = None


class ExploitCapabilityOutput(BaseModel):
    """Standard output for exploitation/testing capabilities."""

    capability: str
    engine_name: str
    engine_version: str
    finding_confirmed: bool
    poc: str
    poc_output: str
    evidence_path: str
    evidence_hash: str
    duration_seconds: float
    raw_output_path: str | None = None


# Capability → output contract mapping
CAPABILITY_OUTPUT_CONTRACTS: dict[str, type] = {
    "security.code.scan": SarifCapabilityOutput,
    "security.code.lint": SarifCapabilityOutput,
    "security.deps.scan": SarifCapabilityOutput,
    "security.secrets.detect": SarifCapabilityOutput,
    "security.container.scan": SarifCapabilityOutput,
    "security.dockerfile.lint": SarifCapabilityOutput,
    "security.infra.scan": SarifCapabilityOutput,
    "security.web.scan": SarifCapabilityOutput,
    "security.network.discover": ReconCapabilityOutput,
    "security.web.discover": ReconCapabilityOutput,
    "security.params.discover": ReconCapabilityOutput,
    "security.routes.discover": ReconCapabilityOutput,
    "security.injection.test_sqli": ExploitCapabilityOutput,
    "security.tls.audit": SarifCapabilityOutput,
    "security.auth.test_jwt": ExploitCapabilityOutput,
}


# ---------------------------------------------------------------------------
# Tool specification
# ---------------------------------------------------------------------------


class SecurityToolSpec(BaseModel):
    """Registry entry for a pluggable security tool."""

    name: str
    capability: ToolCapability
    mode: CapabilityMode = Field(default=CapabilityMode.FALLBACK)
    binary: str
    version_cmd: str
    output_format: str
    sarif_native: bool
    success_exit_codes: list[int] = Field(default=[0])
    run_template: str
    default_args: dict = Field(default_factory=dict)
    redact_output: bool = Field(default=False)
    timeout_seconds: int = Field(default=300, ge=30)
    applies_when: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Surface detection result
# ---------------------------------------------------------------------------


class SurfaceDetectionResult(BaseModel):
    """Result of detecting file types and frameworks in a target directory."""

    has_python: bool = False
    has_javascript: bool = False
    has_dockerfile: bool = False
    has_docker_compose: bool = False
    has_terraform: bool = False
    has_requirements_txt: bool = False
    has_pyproject_toml: bool = False
    detected_frameworks: list[str] = Field(default_factory=list)
    entry_points: list[str] = Field(default_factory=list)


def detect_surface(target_path: str) -> SurfaceDetectionResult:
    """Walk a target directory and detect file types, frameworks, entry points."""
    root = Path(target_path)
    if not root.is_dir():
        raise FileNotFoundError(f"Target path is not a directory: {target_path}")

    result = SurfaceDetectionResult()
    frameworks: set[str] = set()

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        name = path.name.lower()
        suffix = path.suffix.lower()

        if suffix == ".py":
            result.has_python = True
            # Quick framework detection via import scanning
            try:
                text = path.read_text(errors="ignore")[:4096]
                if "fastapi" in text.lower():
                    frameworks.add("fastapi")
                if "django" in text.lower():
                    frameworks.add("django")
                if "flask" in text.lower():
                    frameworks.add("flask")
            except OSError:
                logger.debug(
                    "Could not read file for framework detection", extra={"path": str(path)}
                )
        elif suffix in (".js", ".ts", ".jsx", ".tsx"):
            result.has_javascript = True
        elif name.startswith("dockerfile"):
            result.has_dockerfile = True
        elif name.startswith("docker-compose") and suffix in (".yml", ".yaml"):
            result.has_docker_compose = True
        elif suffix == ".tf":
            result.has_terraform = True
        elif name.startswith("requirements") and suffix == ".txt":
            result.has_requirements_txt = True
        elif name == "pyproject.toml":
            result.has_pyproject_toml = True

    result.detected_frameworks = sorted(frameworks)
    return result


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class SecurityToolRegistry:
    """Resolves security tools by capability. Config-driven."""

    def __init__(self, config_path: Path) -> None:
        raw = yaml.safe_load(config_path.read_text())
        self._tools: dict[ToolCapability, list[SecurityToolSpec]] = {}
        for entry in raw["tools"]:
            spec = SecurityToolSpec(**entry)
            self._tools.setdefault(spec.capability, []).append(spec)
        logger.info(
            "Security tool registry loaded",
            extra={
                "config_path": str(config_path),
                "capabilities": len(self._tools),
                "total_engines": sum(len(v) for v in self._tools.values()),
            },
        )

    def get_primary(self, capability: ToolCapability) -> SecurityToolSpec:
        """Get the primary (first registered) tool for a capability."""
        specs = self._tools.get(capability)
        if not specs:
            raise KeyError(f"No engine registered for capability: {capability}")
        return specs[0]

    def get_all(self, capability: ToolCapability) -> list[SecurityToolSpec]:
        """Get all engines for a capability, ordered by priority."""
        return self._tools.get(capability, [])

    def get_applicable(
        self,
        surface: SurfaceDetectionResult,
    ) -> list[SecurityToolSpec]:
        """Return primary tool for each capability matching the surface."""
        result: list[SecurityToolSpec] = []
        seen: set[ToolCapability] = set()
        for specs in self._tools.values():
            primary = specs[0]
            if primary.capability in seen:
                continue
            if not primary.applies_when:
                result.append(primary)
                seen.add(primary.capability)
            elif any(getattr(surface, cond, False) for cond in primary.applies_when):
                result.append(primary)
                seen.add(primary.capability)
        return result

    def check_installed(self, spec: SecurityToolSpec) -> bool:
        """Verify binary is available on PATH."""
        return shutil.which(spec.binary) is not None
