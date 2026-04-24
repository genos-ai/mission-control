"""
Research Analyst Agent (research.analyst.agent).

Evaluates research coverage after each search round. Classifies which
sub-questions are covered (with source IDs) and which remain as gaps.
Returns structured data — the loop executor computes coverage score
deterministically. Does NOT generate new sub-questions.
"""

from pydantic_ai import Agent
from pydantic_ai.models import Model

from modules.backend.agents.deps.base import BaseAgentDeps
from modules.backend.agents.mission_control.helpers import assemble_instructions
from modules.backend.core.logging import get_logger
from modules.backend.schemas.research import CoverageAnalysisData

logger = get_logger(__name__)


def create_agent(model: str | Model) -> Agent[BaseAgentDeps, CoverageAnalysisData]:
    """Factory: create analyst agent.

    Called by AgentRegistry.get_instance() on first use. Cached.
    """
    instructions = assemble_instructions("research", "analyst")

    agent = Agent(
        model,
        deps_type=BaseAgentDeps,
        output_type=CoverageAnalysisData,
        instructions=instructions,
        output_retries=3,
    )

    logger.info("Research analyst agent created", extra={"model": str(model)})
    return agent
