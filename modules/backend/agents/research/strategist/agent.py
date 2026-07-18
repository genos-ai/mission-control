"""
Research Strategist Agent (research.strategist.agent).

Decomposes research queries into sub-questions with source hints.
Also handles gap-based query refinement between search iterations
(called again with "refine" mode when gaps are identified).

No tools — pure reasoning on structured input.
"""

from pydantic_ai import Agent
from pydantic_ai.models import Model

from modules.backend.agents.deps.base import BaseAgentDeps
from modules.backend.agents.mission_control.helpers import assemble_instructions
from modules.backend.core.logging import get_logger
from modules.backend.schemas.research import ResearchDecomposition

logger = get_logger(__name__)


def create_agent(
    model: str | Model, tool_names: list[str] | None = None
) -> Agent[BaseAgentDeps, ResearchDecomposition]:
    """Factory: create strategist agent.

    Called by AgentRegistry.get_instance() on first use. Cached.
    """
    instructions = assemble_instructions("research", "strategist")

    agent = Agent(
        model,
        deps_type=BaseAgentDeps,
        output_type=ResearchDecomposition,
        instructions=instructions,
        output_retries=3,
    )

    logger.info("Research strategist agent created", extra={"model": str(model)})
    return agent
