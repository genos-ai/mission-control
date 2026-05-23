"""
Research Packet Verifier Agent (deliberation.research_verifier.agent).

Audits the Researcher's evidence packet for the Think Tank deliberation
(Plan 79). Cheap Haiku check that fails LOUD if the packet is unsound:
fabricated sources, a strawman of the mainstream consensus, or
"under-discussed angles" that are in fact widely discussed.

P13 compliance: the Researcher does not self-evaluate. This separate
agent audits its work before the four-debater blind opening runs.

If the verifier returns passed=False, the workflow halts via the
halt_workflow tool — the run status becomes `failed`, not `completed`.
"""

from pydantic_ai import Agent
from pydantic_ai.models import Model

from modules.backend.agents.deps.base import BaseAgentDeps
from modules.backend.agents.mission_control.helpers import assemble_instructions
from modules.backend.core.logging import get_logger
from modules.backend.schemas.deliberation import ResearchPacketVerification

logger = get_logger(__name__)


def create_agent(
    model: str | Model,
    tool_names: list[str] | None = None,
) -> Agent[BaseAgentDeps, ResearchPacketVerification]:
    """Factory: create the research packet verifier agent.

    Called by AgentRegistry.get_instance() on first use. Cached.
    """
    instructions = assemble_instructions("deliberation", "research_verifier")

    agent = Agent(
        model,
        deps_type=BaseAgentDeps,
        output_type=ResearchPacketVerification,
        instructions=instructions,
        # output_retries=1 per Plan 79 §6.1: the verifier's schema is
        # tolerant (issues + issues_text + a handful of booleans). One
        # retry is enough for transient formatting errors.
        output_retries=1,
    )

    logger.info(
        "Deliberation research_verifier agent created",
        extra={"model": str(model)},
    )
    return agent
