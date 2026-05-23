"""
Distributional Ethicist Debater (deliberation.debater_ethicist.agent).

One of the four debaters in the Think Tank (Plan 79). Reasons about
who wins, who loses, and which voices are absent from the data.
Counter-weights the three more technocratic frames (Systems, Quant,
Empiricist) — for contested questions, the mainstream framing often
privileges aggregate efficiency and hides distributional consequence.

Output: DebaterTurn with debater_id="ethicist".
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
    """Factory: create the Distributional Ethicist debater agent."""
    instructions = assemble_instructions("deliberation", "debater_ethicist")

    agent = Agent(
        model,
        deps_type=BaseAgentDeps,
        output_type=DebaterTurn,
        instructions=instructions,
        output_retries=2,
    )

    logger.info(
        "Deliberation debater_ethicist agent created",
        extra={"model": str(model)},
    )
    return agent
