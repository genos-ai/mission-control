"""WASA Reporter Agent (security.webapp.reporter.agent).

Synthesises findings from all assessment phases into a structured
SecurityAssessmentReport with OWASP mapping, CVSS scoring, attack
paths, and prioritised remediation roadmap.
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
    """Create the WASA reporter agent."""
    agent = Agent(
        model,
        deps_type=BaseAgentDeps,
        output_type=str,
        instructions=assemble_instructions("security.webapp.reporter"),
    )

    if tool_names:
        from modules.backend.tools.registry import get_tool_registry

        registry = get_tool_registry()
        registry.register_on_agent(agent, tool_names)

    return agent
