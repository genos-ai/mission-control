"""
Critic Agent (deliberation.critic.agent).

Position-free adversarial critic. Invoked every round. Attacks the
load-bearing assumption of every debater. Identifies convergence by
shared hidden assumption (the proper detector for sycophancy-by-
agreement, which the stance-delta tool cannot see).

P13 compliance: a separate agent from the debaters, so debater output
is never judged by the same agent that produced it.

Important: each critic invocation is INDEPENDENT — the critic does not
see its own prior reports. This prevents the critic developing its own
committed line. Per-round freshness is the design.

Output: CriticReport with a 4-key `attacks` dict (one per debater) and
a `convergence_flag` for the round. The field_validator on CriticReport
enforces all four debater IDs are present.
"""

from pydantic_ai import Agent
from pydantic_ai.models import Model

from modules.backend.agents.deps.base import BaseAgentDeps
from modules.backend.agents.mission_control.helpers import assemble_instructions
from modules.backend.core.logging import get_logger
from modules.backend.schemas.deliberation import CriticReport

logger = get_logger(__name__)


def create_agent(
    model: str | Model,
    tool_names: list[str] | None = None,
) -> Agent[BaseAgentDeps, CriticReport]:
    """Factory: create the critic agent."""
    instructions = assemble_instructions("deliberation", "critic")

    agent = Agent(
        model,
        deps_type=BaseAgentDeps,
        output_type=CriticReport,
        instructions=instructions,
        # output_retries=3 per Plan 79 §6.1 — the CriticReport schema has
        # a strict field_validator that requires all four debater IDs in
        # the `attacks` dict. The LLM may miss one on the first try; the
        # retry lets it self-correct.
        output_retries=3,
    )

    logger.info(
        "Deliberation critic agent created",
        extra={"model": str(model)},
    )
    return agent
