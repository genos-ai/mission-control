"""WASA webapp security assessment agents.

Shared agent module for all security.webapp.* agents:
- security.webapp.scanner.agent — SAST tool orchestration
- security.webapp.triage.agent — LLM false-positive filtering
- security.webapp.reporter.agent — assessment report synthesis

All three resolve to this module via the registry convention:
    security.webapp.*.agent → modules.backend.agents.security.webapp.agent

The create_agent() function builds a generic PydanticAI agent. The
agent's behavior is determined by its system prompt (loaded from
config/prompts/agents/security/webapp/{name}/system.md) and its tool
list (from the agent catalog YAML).
"""

from pydantic_ai import Agent
from pydantic_ai.models import Model

from modules.backend.agents.deps.base import BaseAgentDeps
from modules.backend.agents.mission_control.helpers import assemble_instructions
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def create_agent(
    model: str | Model,
    tool_names: list[str] | None = None,
) -> Agent:
    """Create a WASA security agent.

    The same create_agent function serves all security.webapp.* agents.
    The system prompt and tools differentiate scanner/triage/reporter
    behavior — the agent framework is the same.
    """
    agent = Agent(
        model,
        deps_type=BaseAgentDeps,
        output_type=str,
        instructions=assemble_instructions("security.webapp"),
    )

    # Register tools from the platform tool registry if requested.
    # WASA-specific tools (security.code.scan etc.) are registered
    # via the adapter — they'll be wired when the tool registry
    # integration is complete. For now, the agent works with
    # whatever tools the dispatch loop provides.
    if tool_names:
        from modules.backend.tools.registry import get_tool_registry

        registry = get_tool_registry()
        registered = registry.register_on_agent(agent, tool_names)
        logger.info(
            "WASA agent tools registered",
            extra={"tools": registered, "requested": tool_names},
        )

    return agent
