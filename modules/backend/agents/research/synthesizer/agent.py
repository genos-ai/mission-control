"""
Research Synthesizer Agent (research.synthesizer.agent).

Produces the final research report with [N] inline citations from
the top-K ranked findings. High max_tokens because reports can be long.
Also emits context_updates for the MCD with key findings summary.

Streaming is handled by the agent executor — the research loop does
NOT call this agent directly. The executor streams AgentResponseChunkEvent
with agent_id="research.synthesizer.agent".
"""

from pydantic_ai import Agent
from pydantic_ai.models import Model

from modules.backend.agents.deps.base import BaseAgentDeps
from modules.backend.agents.mission_control.helpers import assemble_instructions
from modules.backend.core.logging import get_logger
from modules.backend.schemas.research import ResearchReportOutput

logger = get_logger(__name__)


def create_agent(model: str | Model, tool_names: list[str] | None = None) -> Agent[BaseAgentDeps, ResearchReportOutput]:
    """Factory: create synthesizer agent.

    Called by AgentRegistry.get_instance() on first use. Cached.
    """
    instructions = assemble_instructions("research", "synthesizer")

    agent = Agent(
        model,
        deps_type=BaseAgentDeps,
        output_type=ResearchReportOutput,
        instructions=instructions,
        output_retries=2,
    )

    logger.info("Research synthesizer agent created", extra={"model": str(model)})
    return agent
