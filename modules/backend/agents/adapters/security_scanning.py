"""WASA security scanning adapter — thin async wrappers for security tool capabilities.

One parametric function for all scanning capabilities, plus utility tools.
Agents call these functions via PydanticAI tool registrations; they never
call subprocess or the runner directly. Spec Section 1.2.

Pattern: matches adapters/compliance.py — thin wrappers, no PydanticAI
dependency in the adapter itself.
"""

from __future__ import annotations

import json

from modules.backend.agents.security.sarif import load_sarif, merge_sarif
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
        capability,
        cap_input,
        registry,
        environment_handle=environment_handle,
    )
    if not results:
        return f"{capability.value}: all engines failed"
    r = results[0]
    return f"{capability.value} ({r.engine_name}): {r.finding_count} findings at {r.sarif_path}"


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
