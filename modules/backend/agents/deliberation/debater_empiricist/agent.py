"""
Adversarial Empiricist Debater (deliberation.debater_empiricist.agent).

One of the four debaters in the Think Tank (Plan 79). The MAVERICK
seat. Reasons from historical priors, falsifiable prediction, and
prediction track records. Specifically tasked with challenging the
mainstream consensus stated in the research packet. The other three
debaters are not assigned this role.

This is the load-bearing anti-collapse-to-mainstream mechanism. If
Claude's strong consensus prior pushes the other three toward the
mainstream view, the Adversarial Empiricist's job is to hold the
contrarian position when the historical track record supports it.

Output: DebaterTurn with debater_id="empiricist".
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
    """Factory: create the Adversarial Empiricist debater agent."""
    instructions = assemble_instructions("deliberation", "debater_empiricist")

    agent = Agent(
        model,
        deps_type=BaseAgentDeps,
        output_type=DebaterTurn,
        instructions=instructions,
        output_retries=2,
    )

    logger.info(
        "Deliberation debater_empiricist agent created",
        extra={"model": str(model)},
    )
    return agent
