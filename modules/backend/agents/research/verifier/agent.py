"""
Research Verifier Agent (research.verifier.agent).

NLI-style citation verification. For each claim+citation pair,
checks whether the cited source text actually supports the claim.
Flags hallucinated or unsupported citations.

Uses Haiku for cost efficiency — structured checking doesn't need
a large model.
"""

from pydantic_ai import Agent
from pydantic_ai.models import Model

from modules.backend.agents.deps.base import BaseAgentDeps
from modules.backend.agents.mission_control.helpers import assemble_instructions
from modules.backend.core.logging import get_logger
from modules.backend.schemas.research import CitationVerificationResult

logger = get_logger(__name__)


def create_agent(model: str | Model, tool_names: list[str] | None = None) -> Agent[BaseAgentDeps, CitationVerificationResult]:
    """Factory: create verifier agent.

    Called by AgentRegistry.get_instance() on first use. Cached.
    """
    instructions = assemble_instructions("research", "verifier")

    agent = Agent(
        model,
        deps_type=BaseAgentDeps,
        output_type=CitationVerificationResult,
        instructions=instructions,
        output_retries=2,
    )

    logger.info("Research verifier agent created", extra={"model": str(model)})
    return agent
