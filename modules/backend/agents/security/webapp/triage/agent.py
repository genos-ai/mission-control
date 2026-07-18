"""WASA Triage Agent (security.webapp.triage.agent).

LLM false-positive filtering. Reads merged SARIF findings, examines
code context, and produces triage verdicts with rationale.
"""

from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model

from modules.backend.agents.deps.base import BaseAgentDeps
from modules.backend.agents.mission_control.helpers import assemble_instructions
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def create_agent(
    model: str | Model,
    tool_names: list[str] | None = None,
) -> Agent:
    """Create the WASA triage agent."""
    agent = Agent(
        model,
        deps_type=BaseAgentDeps,
        output_type=str,
        instructions=assemble_instructions("security.webapp.triage"),
    )

    # Register read_file from the platform tool registry
    if tool_names:
        from modules.backend.tools.registry import get_tool_registry

        registry = get_tool_registry()
        registry.register_on_agent(agent, tool_names)

    # Register security.load_sarif directly (not in platform registry)
    from modules.backend.agents.adapters.security_scanning import run_load_sarif

    @agent.tool
    async def security_load_sarif(ctx: RunContext[BaseAgentDeps], sarif_path: str) -> str:
        """Load and return SARIF findings as JSON from the given file path."""
        return await run_load_sarif(sarif_path)

    return agent
