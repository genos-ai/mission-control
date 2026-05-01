"""WASA security scanning adapter — thin async wrappers for security tool capabilities.

One parametric function for all scanning capabilities, plus utility tools.
Agents call these functions via PydanticAI tool registrations; they never
call subprocess or the runner directly. Spec Section 1.2.

Pattern: matches adapters/compliance.py — thin wrappers, no PydanticAI
dependency in the adapter itself.
"""

from __future__ import annotations

import json

from modules.backend.agents.security.sarif import (
    load_sarif,
    merge_sarif,
)
from modules.backend.agents.security.tool_registry import (
    CapabilityInput,
    SecurityToolRegistry,
    ToolCapability,
    detect_surface,
)
from modules.backend.agents.security.tool_runner import run_capability
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Parametric scanning capability
# ---------------------------------------------------------------------------

async def run_scan(
    capability: ToolCapability,
    target_path: str,
    evidence_path: str,
    registry: SecurityToolRegistry,
    environment_handle: object | None = None,
) -> str:
    """Run a single scanning capability and return a summary string.

    All Phase 1 scanning capabilities share the same structure:
    build a CapabilityInput, call run_capability, format the result.
    The capability enum determines which tool runs.
    When environment_handle is set, tools execute inside the container.
    """
    # Derive a stable filename from the capability value
    # e.g. "security.code.scan" → "security_code_scan"
    filename = capability.value.replace(".", "_")
    cap_input = CapabilityInput(
        target_path=target_path,
        output_path=f"{evidence_path}/sarif/{filename}.sarif",
    )
    results = await run_capability(
        capability, cap_input, registry, environment_handle=environment_handle,
    )
    if not results:
        return f"{capability.value}: all engines failed"
    r = results[0]
    return f"{capability.value} ({r.engine_name}): {r.finding_count} findings at {r.sarif_path}"


# Convenience aliases for direct tool registration by name.
# Each is a one-liner delegating to run_scan with the correct enum.

async def scan_code(target_path: str, evidence_path: str, registry: SecurityToolRegistry) -> str:
    """security.code.scan — SAST via Opengrep/CodeQL."""
    return await run_scan(ToolCapability.CODE_SCAN, target_path, evidence_path, registry)


async def scan_code_lint(target_path: str, evidence_path: str, registry: SecurityToolRegistry) -> str:
    """security.code.lint — Bandit-equivalent lint via Ruff --select S."""
    return await run_scan(ToolCapability.CODE_LINT, target_path, evidence_path, registry)


async def scan_deps(target_path: str, evidence_path: str, registry: SecurityToolRegistry) -> str:
    """security.deps.scan — dependency CVE scanning via pip-audit."""
    return await run_scan(ToolCapability.DEPS_SCAN, target_path, evidence_path, registry)


async def detect_secrets(target_path: str, evidence_path: str, registry: SecurityToolRegistry) -> str:
    """security.secrets.detect — hardcoded credential scanning via Betterleaks."""
    return await run_scan(ToolCapability.SECRETS_DETECT, target_path, evidence_path, registry)


async def scan_container(target_path: str, evidence_path: str, registry: SecurityToolRegistry) -> str:
    """security.container.scan — filesystem + container CVEs via Trivy."""
    return await run_scan(ToolCapability.CONTAINER_SCAN, target_path, evidence_path, registry)


async def lint_dockerfile(target_path: str, evidence_path: str, registry: SecurityToolRegistry) -> str:
    """security.dockerfile.lint — Dockerfile best practices via Hadolint."""
    return await run_scan(ToolCapability.DOCKERFILE_LINT, target_path, evidence_path, registry)


async def scan_infra(target_path: str, evidence_path: str, registry: SecurityToolRegistry) -> str:
    """security.infra.scan — IaC security rules via Checkov."""
    return await run_scan(ToolCapability.INFRA_SCAN, target_path, evidence_path, registry)


# ---------------------------------------------------------------------------
# Utility tools
# ---------------------------------------------------------------------------

async def run_detect_surface(target_path: str) -> str:
    """security.detect_surface — identify file types and applicable capabilities."""
    result = detect_surface(target_path)
    return result.model_dump_json()


async def run_merge_sarif(sarif_paths: list[str], output_path: str) -> str:
    """security.merge_sarif — merge multiple SARIF files, deduplicate findings."""
    merged_path = merge_sarif(sarif_paths, output_path)
    findings = load_sarif(merged_path)
    return f"Merged {len(sarif_paths)} SARIF files → {len(findings)} findings at {merged_path}"


async def run_load_sarif(sarif_path: str) -> str:
    """security.load_sarif — load and return SARIF findings as JSON."""
    findings = load_sarif(sarif_path)
    return json.dumps(findings, indent=2)
