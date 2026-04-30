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

    from modules.backend.agents.adapters.security_scanning import (
        run_scan,
        run_detect_surface,
        run_merge_sarif,
    )
    from modules.backend.agents.security.tool_registry import ToolCapability

    @agent.tool
    async def security_code_scan(ctx: RunContext[ScanDeps], target_path: str) -> str:
        """Run SAST code scanning via Opengrep."""
        return await run_scan(ToolCapability.CODE_SCAN, target_path, ctx.deps.evidence_path, ctx.deps.tool_registry)

    @agent.tool
    async def security_code_lint(ctx: RunContext[ScanDeps], target_path: str) -> str:
        """Run security lint via Ruff --select S."""
        return await run_scan(ToolCapability.CODE_LINT, target_path, ctx.deps.evidence_path, ctx.deps.tool_registry)

    @agent.tool
    async def security_deps_scan(ctx: RunContext[ScanDeps], target_path: str) -> str:
        """Run dependency CVE scan via pip-audit."""
        return await run_scan(ToolCapability.DEPS_SCAN, target_path, ctx.deps.evidence_path, ctx.deps.tool_registry)

    @agent.tool
    async def security_secrets_detect(ctx: RunContext[ScanDeps], target_path: str) -> str:
        """Detect hardcoded credentials via Betterleaks."""
        return await run_scan(ToolCapability.SECRETS_DETECT, target_path, ctx.deps.evidence_path, ctx.deps.tool_registry)

    @agent.tool
    async def security_container_scan(ctx: RunContext[ScanDeps], target_path: str) -> str:
        """Run container/filesystem CVE scan via Trivy."""
        return await run_scan(ToolCapability.CONTAINER_SCAN, target_path, ctx.deps.evidence_path, ctx.deps.tool_registry)

    @agent.tool
    async def security_dockerfile_lint(ctx: RunContext[ScanDeps], target_path: str) -> str:
        """Lint Dockerfile via Hadolint."""
        return await run_scan(ToolCapability.DOCKERFILE_LINT, target_path, ctx.deps.evidence_path, ctx.deps.tool_registry)

    @agent.tool
    async def security_infra_scan(ctx: RunContext[ScanDeps], target_path: str) -> str:
        """Run IaC security scan via Checkov."""
        return await run_scan(ToolCapability.INFRA_SCAN, target_path, ctx.deps.evidence_path, ctx.deps.tool_registry)

    @agent.tool
    async def security_detect_surface(ctx: RunContext[ScanDeps], target_path: str) -> str:
        """Detect file types and frameworks present in the target directory."""
        return await run_detect_surface(target_path)

    @agent.tool
    async def security_merge_sarif(ctx: RunContext[ScanDeps], sarif_paths: list[str], output_path: str) -> str:
        """Merge multiple SARIF files, deduplicating by (cwe_id, file_path, line_number)."""
        return await run_merge_sarif(sarif_paths, output_path)

    return agent
