"""
Systems Mapper Debater (deliberation.debater_systems.agent).

One of the four debaters in the Think Tank (Plan 79). Reasons in
systems, feedback loops, and second-order effects. Optimises for
systemic resilience under shock. The Systems Mapper produces an
incompatible answer format to the Reductionist Quant (qualitative
second-order narrative vs falsifiable quantitative claim), which is
the design feature that prevents trivial convergence.

Output: DebaterTurn with debater_id="systems".
"""

from pydantic_ai import Agent
from pydantic_ai.models import Model

from modules.backend.agents.deps.base import BaseAgentDeps
from modules.backend.agents.mission_control.helpers import assemble_instructions
from modules.backend.core.logging import get_logger
from modules.backend.schemas.deliberation import DebaterTurn

logger = get_logger(__name__)


def create_agent(
    model: str | Model,
    tool_names: list[str] | None = None,
) -> Agent[BaseAgentDeps, DebaterTurn]:
    """Factory: create the Systems Mapper debater agent."""
    instructions = assemble_instructions("deliberation", "debater_systems")

    agent = Agent(
        model,
        deps_type=BaseAgentDeps,
        output_type=DebaterTurn,
        instructions=instructions,
        output_retries=3,
    )

    logger.info(
        "Deliberation debater_systems agent created",
        extra={"model": str(model)},
    )
    return agent
