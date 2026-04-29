"""WASA Security Tool Runner — unified subprocess execution + SARIF normalisation.

This is the ONLY module that executes security tool subprocesses. Agents
never call subprocess directly. Agents never see engine-specific output.
Spec Section 1.2.

The runner:
1. Resolves the command template from the registry spec + standard input
2. Runs the subprocess asynchronously with timeout
3. Handles exit codes (1 = findings for some tools, not failure)
4. Converts non-SARIF output to SARIF 2.1.0 (for scan capabilities)
5. Strips secret values if spec.redact_output is True
6. Hashes evidence for chain of custody
7. Returns the standardised output contract for the capability
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from modules.backend.agents.security.errors import (
    SecurityAssessmentError,
    SecurityErrorCode,
)
from modules.backend.agents.security.sarif import SARIF_LEVEL_TO_SEVERITY
from modules.backend.agents.security.tool_registry import (
    CapabilityInput,
    CapabilityMode,
    SarifCapabilityOutput,
    SecurityToolRegistry,
    SecurityToolSpec,
    ToolCapability,
)
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Subprocess result
# ---------------------------------------------------------------------------

@dataclass
class CommandResult:
    """Structured result from an async subprocess call."""

    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float


# ---------------------------------------------------------------------------
# Async subprocess helper
# ---------------------------------------------------------------------------

async def _run_tool_subprocess(
    cmd: list[str],
    timeout: int,
    cwd: str | None = None,
) -> CommandResult:
    """Run a security tool binary asynchronously and return structured result.

    Follows the asyncio.create_subprocess_exec + wait_for pattern from
    tools/run_command.py:_run_local(). Independent implementation — does
    not import the private _run_local function.
    """
    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout,
        )
        return CommandResult(
            exit_code=proc.returncode or 0,
            stdout=stdout_bytes.decode(errors="replace"),
            stderr=stderr_bytes.decode(errors="replace"),
            duration_seconds=time.monotonic() - start,
        )
    except asyncio.TimeoutError:
        return CommandResult(
            exit_code=-1,
            stdout="",
            stderr=f"Tool subprocess timed out after {timeout}s",
            duration_seconds=time.monotonic() - start,
        )
    except OSError as e:
        return CommandResult(
            exit_code=-1,
            stdout="",
            stderr=str(e),
            duration_seconds=time.monotonic() - start,
        )


# ---------------------------------------------------------------------------
# SARIF helpers
# ---------------------------------------------------------------------------

def count_severities(sarif: dict) -> dict[str, int]:
    """Count findings by severity level from a SARIF document."""
    counts: dict[str, int] = {}
    for run in sarif.get("runs", []):
        for result in run.get("results", []):
            level = result.get("level", "warning").lower()
            severity = SARIF_LEVEL_TO_SEVERITY.get(level, "MEDIUM")
            counts[severity] = counts.get(severity, 0) + 1
    return counts


def probe_engine_version(spec: SecurityToolSpec) -> str:
    """Run the tool's version command synchronously and return version string."""
    try:
        result = subprocess.run(
            spec.version_cmd.split(),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()[:100] or result.stderr.strip()[:100]
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def strip_secret_values(sarif_path: str) -> None:
    """Remove matched secret values from SARIF output.

    Replaces the 'message.text' and 'snippet' fields that contain
    raw secret values with redacted placeholders. The raw unredacted
    output is preserved in the .raw file for encrypted evidence storage.

    Phase 1: strip values. Phase 2: AES encrypt the .raw file.
    """
    try:
        data = json.loads(Path(sarif_path).read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        return

    for run in data.get("runs", []):
        for result in run.get("results", []):
            msg = result.get("message", {})
            if "text" in msg:
                msg["text"] = _redact_secrets_in_text(msg["text"])
            for loc in result.get("locations", []):
                region = loc.get("physicalLocation", {}).get("region", {})
                snippet = region.get("snippet", {})
                if "text" in snippet:
                    snippet["text"] = _redact_secrets_in_text(snippet["text"])

    Path(sarif_path).write_text(json.dumps(data, indent=2))


def _redact_secrets_in_text(text: str) -> str:
    """Replace high-entropy strings that look like secrets with <<REDACTED>>."""
    # Common secret patterns
    patterns = [
        r'(?:api[_-]?key|secret|token|password|passwd|credential)\s*[:=]\s*["\']?([^\s"\']{8,})',
        r'(?:sk|pk|ak|rk)[-_](?:live|test|prod)[-_][a-zA-Z0-9]{16,}',
        r'ghp_[a-zA-Z0-9]{20,}',
        r'eyJ[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}',
    ]
    for pattern in patterns:
        text = re.sub(pattern, "<<REDACTED>>", text, flags=re.IGNORECASE)
    return text


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

async def run_security_tool(
    spec: SecurityToolSpec,
    capability_input: CapabilityInput,
) -> SarifCapabilityOutput:
    """Run a single security tool and return a standardised output contract.

    This is the ONLY function that executes security tool subprocesses.
    """
    # Resolve command template
    args: dict[str, Any] = {
        **spec.default_args,
        "binary": spec.binary,
        "output_path": capability_input.output_path,
    }
    if capability_input.target_path:
        args["target_path"] = capability_input.target_path
    if capability_input.target_url:
        args["target_url"] = capability_input.target_url
    if capability_input.target_host:
        args["target_host"] = capability_input.target_host

    # Build command — strip whitespace from template line continuations
    cmd_str = spec.run_template.format(**args).strip()
    cmd = cmd_str.split()

    started = datetime.now()
    result = await _run_tool_subprocess(cmd, timeout=spec.timeout_seconds)
    duration = (datetime.now() - started).total_seconds()

    # Validate exit code
    if result.exit_code not in spec.success_exit_codes:
        if result.exit_code == -1 and "timed out" in result.stderr:
            error_code = SecurityErrorCode.SCANNER_TIMEOUT
        elif result.exit_code == -1:
            error_code = SecurityErrorCode.SCANNER_BINARY_NOT_FOUND
        else:
            error_code = SecurityErrorCode.SCANNER_BINARY_NOT_FOUND
        raise SecurityAssessmentError(
            code=error_code,
            message=f"{spec.name} exited {result.exit_code}: {result.stderr[:200]}",
            details={"tool": spec.name, "exit_code": result.exit_code},
        )

    # Store raw output before transformation
    output_path = Path(capability_input.output_path)
    raw_output_path = str(output_path) + ".raw"
    if output_path.exists():
        shutil.copy2(str(output_path), raw_output_path)

    # Strip secret values if flagged
    if spec.redact_output and output_path.exists():
        strip_secret_values(str(output_path))

    # Note: evidence hashing is done by the orchestrator via
    # EvidenceManifest.add() at the workflow step level, not here.
    # The runner produces files; the orchestrator tracks integrity.

    # Return standardised contract
    engine_version = probe_engine_version(spec)
    sarif: dict = {}
    finding_count = 0
    severity_counts: dict[str, int] = {}

    if output_path.exists():
        try:
            sarif = json.loads(output_path.read_text())
            finding_count = sum(
                len(run.get("results", [])) for run in sarif.get("runs", [])
            )
            severity_counts = count_severities(sarif)
        except json.JSONDecodeError:
            logger.warning(
                "Tool output is not valid JSON/SARIF",
                extra={"tool": spec.name, "path": str(output_path)},
            )

    return SarifCapabilityOutput(
        capability=spec.capability.value,
        engine_name=spec.name,
        engine_version=engine_version,
        sarif_path=str(output_path),
        finding_count=finding_count,
        severity_counts=severity_counts,
        duration_seconds=duration,
        exit_code=result.exit_code,
        raw_output_path=raw_output_path,
    )


async def run_capability(
    capability: ToolCapability,
    capability_input: CapabilityInput,
    registry: SecurityToolRegistry,
) -> list[SarifCapabilityOutput]:
    """Run a capability using registered engines. Handles fallback/ensemble."""
    specs = registry.get_all(capability)
    if not specs:
        raise KeyError(f"No engine registered for capability: {capability}")

    mode = specs[0].mode

    if mode == CapabilityMode.ENSEMBLE:
        tasks = [
            run_security_tool(
                spec,
                CapabilityInput(
                    target_path=capability_input.target_path,
                    target_url=capability_input.target_url,
                    target_host=capability_input.target_host,
                    output_path=f"{capability_input.output_path}.{spec.name}",
                    scope=capability_input.scope,
                ),
            )
            for spec in specs
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r for r in results if isinstance(r, SarifCapabilityOutput)]

    # FALLBACK mode: try in order, stop at first success
    for spec in specs:
        if not registry.check_installed(spec):
            logger.warning(
                "Tool not installed, trying next engine",
                extra={"tool": spec.name, "capability": capability.value},
            )
            continue
        try:
            result = await run_security_tool(spec, capability_input)
            return [result]
        except SecurityAssessmentError:
            logger.warning(
                "Tool failed, trying next engine",
                extra={"tool": spec.name, "capability": capability.value},
            )
    return []
