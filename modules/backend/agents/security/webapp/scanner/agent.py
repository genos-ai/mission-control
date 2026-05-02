"""WASA Scanner Agent (security.webapp.scanner.agent).

Deterministic SAST tool orchestrator. Runs registered security tools
by capability against a target codebase and collects SARIF output.
Does NOT assess findings — the triage agent does that.
"""

from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model

from modules.backend.agents.mission_control.helpers import assemble_instructions
from modules.backend.agents.security.deps import ScanDeps
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

# Scan capabilities: (ToolCapability enum member name, tool function name, docstring)
_SCAN_CAPABILITIES = [
    ("CODE_SCAN", "security_code_scan", "Run SAST code scanning via Opengrep."),
    ("CODE_LINT", "security_code_lint", "Run security lint via Ruff --select S."),
    ("DEPS_SCAN", "security_deps_scan", "Run dependency CVE scan via pip-audit."),
    ("SECRETS_DETECT", "security_secrets_detect", "Detect hardcoded credentials via Betterleaks."),
    ("CONTAINER_SCAN", "security_container_scan", "Run container/filesystem CVE scan via Trivy."),
    ("DOCKERFILE_LINT", "security_dockerfile_lint", "Lint Dockerfile via Hadolint."),
    ("INFRA_SCAN", "security_infra_scan", "Run IaC security scan via Checkov."),
]


def _make_scan_tool(capability_name: str, tool_name: str, doc: str):
    """Factory for uniform scan tool wrappers."""
    from modules.backend.agents.adapters.security_scanning import run_scan
    from modules.backend.agents.security.tool_registry import ToolCapability

    capability = ToolCapability[capability_name]

    async def tool_fn(ctx: RunContext[ScanDeps], target_path: str) -> str:
        return await run_scan(
            capability, target_path, ctx.deps.evidence_path,
            ctx.deps.tool_registry, environment_handle=ctx.deps.environment_handle,
        )

    tool_fn.__name__ = tool_name
    tool_fn.__qualname__ = tool_name
    tool_fn.__doc__ = doc
    return tool_fn


def create_agent(
    model: str | Model,
    tool_names: list[str] | None = None,
) -> Agent:
    """Create the WASA scanner agent with all security tools registered."""
    agent = Agent(
        model,
        deps_type=ScanDeps,
        output_type=str,
        instructions=assemble_instructions("security.webapp.scanner"),
    )

    # Register 7 scan capability tools via factory
    for cap_name, fn_name, doc in _SCAN_CAPABILITIES:
        agent.tool(_make_scan_tool(cap_name, fn_name, doc))

    # Register utility tools (different signatures, registered inline)
    from modules.backend.agents.adapters.security_scanning import (
        run_detect_surface,
        run_merge_sarif,
    )

    @agent.tool
    async def security_detect_surface(ctx: RunContext[ScanDeps], target_path: str) -> str:
        """Detect file types and frameworks present in the target directory."""
        return await run_detect_surface(target_path)

    @agent.tool
    async def security_merge_sarif(ctx: RunContext[ScanDeps], sarif_paths: list[str], output_path: str) -> str:
        """Merge multiple SARIF files, deduplicating by (cwe_id, file_path, line_number)."""
        return await run_merge_sarif(sarif_paths, output_path)

    return agent
