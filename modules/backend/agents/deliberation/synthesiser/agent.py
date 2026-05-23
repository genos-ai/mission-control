"""
Synthesiser Agent (deliberation.synthesiser.agent).

Reads the full transcript and produces the FinalDeliverable. Does NOT
vote, does NOT declare a winner. Maps cruxes, preserves minority
positions, audits the deliberation against the mainstream prior, and
emits both the structured deliverable AND its Markdown rendering.

The schema constraints are the anti-flattening guarantee
(min_length=2 cruxes, required minority_position, merely_reproduces
enum). The Markdown is emitted by the synthesiser itself — not by a
downstream Haiku renderer — so the schema-enforced anti-flattening
survives into the persisted artifact.

Output: FinalDeliverable (see modules.backend.schemas.deliberation).
"""

from pydantic_ai import Agent
from pydantic_ai.models import Model

from modules.backend.agents.deps.base import BaseAgentDeps
from modules.backend.agents.mission_control.helpers import assemble_instructions
from modules.backend.core.logging import get_logger
from modules.backend.schemas.deliberation import FinalDeliverable

logger = get_logger(__name__)


def create_agent(
    model: str | Model,
    tool_names: list[str] | None = None,
) -> Agent[BaseAgentDeps, FinalDeliverable]:
    """Factory: create the synthesiser agent."""
    instructions = assemble_instructions("deliberation", "synthesiser")

    agent = Agent(
        model,
        deps_type=BaseAgentDeps,
        output_type=FinalDeliverable,
        instructions=instructions,
        output_retries=3,
    )

    logger.info(
        "Deliberation synthesiser agent created",
        extra={"model": str(model)},
    )
    return agent
