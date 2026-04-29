"""WASA security scanning adapter — thin async wrappers for security tool capabilities.

One function per Phase 1 capability. Each delegates to the tool registry
and runner. Agents call these functions via PydanticAI tool registrations;
they never call subprocess or the runner directly. Spec Section 1.2.

Pattern: matches adapters/compliance.py — thin wrappers, no PydanticAI
dependency in the adapter itself.
"""

from __future__ import annotations

from pathlib import Path

from modules.backend.agents.security.sarif import (
    load_sarif,
    merge_sarif,
)
from modules.backend.agents.security.tool_registry import (
    CapabilityInput,
    SecurityToolRegistry,
    SurfaceDetectionResult,
    ToolCapability,
    detect_surface,
)
from modules.backend.agents.security.tool_runner import (
    SarifCapabilityOutput,
    run_capability,
)
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Scanning capabilities (one per Phase 1 capability)
# ---------------------------------------------------------------------------

async def scan_code(
    target_path: str,
    evidence_path: str,
    registry: SecurityToolRegistry,
) -> str:
    """security.code.scan — SAST via Opengrep/CodeQL."""
    cap_input = CapabilityInput(
        target_path=target_path,
        output_path=f"{evidence_path}/sarif/security_code_scan.sarif",
    )
    results = await run_capability(ToolCapability.CODE_SCAN, cap_input, registry)
    if not results:
        return "security.code.scan: all engines failed"
    r = results[0]
    return f"security.code.scan ({r.engine_name}): {r.finding_count} findings at {r.sarif_path}"


async def scan_code_lint(
    target_path: str,
    evidence_path: str,
    registry: SecurityToolRegistry,
) -> str:
    """security.code.lint — Bandit-equivalent lint via Ruff --select S."""
    cap_input = CapabilityInput(
        target_path=target_path,
        output_path=f"{evidence_path}/sarif/security_code_lint.sarif",
    )
    results = await run_capability(ToolCapability.CODE_LINT, cap_input, registry)
    if not results:
        return "security.code.lint: all engines failed"
    r = results[0]
    return f"security.code.lint ({r.engine_name}): {r.finding_count} findings at {r.sarif_path}"


async def scan_deps(
    target_path: str,
    evidence_path: str,
    registry: SecurityToolRegistry,
) -> str:
    """security.deps.scan — dependency CVE scanning via pip-audit."""
    cap_input = CapabilityInput(
        target_path=target_path,
        output_path=f"{evidence_path}/sarif/security_deps_scan.sarif",
    )
    results = await run_capability(ToolCapability.DEPS_SCAN, cap_input, registry)
    if not results:
        return "security.deps.scan: all engines failed"
    r = results[0]
    return f"security.deps.scan ({r.engine_name}): {r.finding_count} findings at {r.sarif_path}"


async def detect_secrets(
    target_path: str,
    evidence_path: str,
    registry: SecurityToolRegistry,
) -> str:
    """security.secrets.detect — hardcoded credential scanning via Betterleaks."""
    cap_input = CapabilityInput(
        target_path=target_path,
        output_path=f"{evidence_path}/sarif/security_secrets_detect.sarif",
    )
    results = await run_capability(ToolCapability.SECRETS_DETECT, cap_input, registry)
    if not results:
        return "security.secrets.detect: all engines failed"
    r = results[0]
    return f"security.secrets.detect ({r.engine_name}): {r.finding_count} findings at {r.sarif_path}"


async def scan_container(
    target_path: str,
    evidence_path: str,
    registry: SecurityToolRegistry,
) -> str:
    """security.container.scan — filesystem + container CVEs via Trivy."""
    cap_input = CapabilityInput(
        target_path=target_path,
        output_path=f"{evidence_path}/sarif/security_container_scan.sarif",
    )
    results = await run_capability(ToolCapability.CONTAINER_SCAN, cap_input, registry)
    if not results:
        return "security.container.scan: all engines failed"
    r = results[0]
    return f"security.container.scan ({r.engine_name}): {r.finding_count} findings at {r.sarif_path}"


async def lint_dockerfile(
    target_path: str,
    evidence_path: str,
    registry: SecurityToolRegistry,
) -> str:
    """security.dockerfile.lint — Dockerfile best practices via Hadolint."""
    cap_input = CapabilityInput(
        target_path=target_path,
        output_path=f"{evidence_path}/sarif/security_dockerfile_lint.sarif",
    )
    results = await run_capability(ToolCapability.DOCKERFILE_LINT, cap_input, registry)
    if not results:
        return "security.dockerfile.lint: all engines failed"
    r = results[0]
    return f"security.dockerfile.lint ({r.engine_name}): {r.finding_count} findings at {r.sarif_path}"


async def scan_infra(
    target_path: str,
    evidence_path: str,
    registry: SecurityToolRegistry,
) -> str:
    """security.infra.scan — IaC security rules via Checkov."""
    cap_input = CapabilityInput(
        target_path=target_path,
        output_path=f"{evidence_path}/sarif/security_infra_scan.sarif",
    )
    results = await run_capability(ToolCapability.INFRA_SCAN, cap_input, registry)
    if not results:
        return "security.infra.scan: all engines failed"
    r = results[0]
    return f"security.infra.scan ({r.engine_name}): {r.finding_count} findings at {r.sarif_path}"


# ---------------------------------------------------------------------------
# Utility tools
# ---------------------------------------------------------------------------

async def run_detect_surface(target_path: str) -> str:
    """security.detect_surface — identify file types and applicable capabilities."""
    result = detect_surface(target_path)
    return result.model_dump_json()


async def run_merge_sarif(
    sarif_paths: list[str],
    output_path: str,
) -> str:
    """security.merge_sarif — merge multiple SARIF files, deduplicate findings."""
    merged_path = merge_sarif(sarif_paths, output_path)
    findings = load_sarif(merged_path)
    return f"Merged {len(sarif_paths)} SARIF files → {len(findings)} findings at {merged_path}"


async def run_load_sarif(sarif_path: str) -> str:
    """security.load_sarif — load and return SARIF findings as JSON."""
    import json

    findings = load_sarif(sarif_path)
    return json.dumps(findings, indent=2)
