"""
Reductionist Quant Debater (deliberation.debater_quant.agent).

One of the four debaters in the Think Tank (Plan 79). Reasons
reductionistically in mechanisms and measurable quantities. Optimises
for efficiency and falsifiability — a claim with no falsifier is, for
this debater's purposes, not a claim. Commits to numerical forecasts
with horizons; "it depends" is not a position.

Output: DebaterTurn with debater_id="quant".
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
    """Factory: create the Reductionist Quant debater agent."""
    instructions = assemble_instructions("deliberation", "debater_quant")

    agent = Agent(
        model,
        deps_type=BaseAgentDeps,
        output_type=DebaterTurn,
        instructions=instructions,
        output_retries=2,
    )

    logger.info(
        "Deliberation debater_quant agent created",
        extra={"model": str(model)},
    )
    return agent
