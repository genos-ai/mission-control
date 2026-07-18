"""
Research Searcher Agent (research.searcher.agent).

Executes search for ONE sub-question. Each instance gets its own
context window (context isolation). Searches, extracts content,
produces structured findings with citations.
"""

from pydantic_ai import Agent
from pydantic_ai.models import Model

from modules.backend.agents.mission_control.helpers import assemble_instructions
from modules.backend.agents.research.deps import ResearchAgentDeps
from modules.backend.core.logging import get_logger
from modules.backend.schemas.research import SearchFindings

logger = get_logger(__name__)


def create_agent(
    model: str | Model,
    tool_names: list[str] | None = None,
) -> Agent[ResearchAgentDeps, SearchFindings]:
    """Factory: create searcher agent with web search tools.

    Called by AgentRegistry.get_instance() on first use. Cached.
    Tools are injected from the registry based on the agent's config.
    """
    instructions = assemble_instructions("research", "searcher")

    agent = Agent(
        model,
        deps_type=ResearchAgentDeps,
        output_type=SearchFindings,
        instructions=instructions,
        output_retries=3,
    )

    # Shared tools from registry (driven by agent YAML config)
    if tool_names:
        from modules.backend.tools.registry import get_tool_registry

        get_tool_registry().register_on_agent(agent, tool_names)

    logger.info("Research searcher agent created", extra={"model": str(model)})
    return agent
