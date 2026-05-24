"""
Advocate-Judge Framings Validator Agent
(deliberation.advocate_judge_framings_validator.agent).

Phase 1 of the Advocate-Judge architecture (Plan 80). Audits the
framer's CandidateSet for hidden bias and missing schools of thought,
producing either approval or a revised CandidateSet. P13 compliance:
the framer does not self-evaluate.

Different model family from the framer by design (default GPT vs
framer's Claude) — so the audit catches family-specific priors. See
Plan 80 §5.1.

No tools — pure reasoning over the framer's output. The next phase
(per-side researchers) does the deep evidence gathering.
"""

from pydantic_ai import Agent
from pydantic_ai.models import Model

from modules.backend.agents.deps.base import BaseAgentDeps
from modules.backend.agents.mission_control.helpers import assemble_instructions
from modules.backend.core.logging import get_logger
from modules.backend.schemas.deliberation_advocate_judge import FramingValidation

logger = get_logger(__name__)


def create_agent(
    model: str | Model,
    tool_names: list[str] | None = None,
) -> Agent[BaseAgentDeps, FramingValidation]:
    """Factory: create the Advocate-Judge framings validator agent.

    Called by AgentRegistry.get_instance() on first use. Cached.
    No tools — `tool_names` is accepted for interface uniformity but
    typically ignored (the YAML declares an empty tools list).
    """
    instructions = assemble_instructions(
        "deliberation", "advocate_judge_framings_validator",
    )

    agent = Agent(
        model,
        deps_type=BaseAgentDeps,
        output_type=FramingValidation,
        instructions=instructions,
        # 2 retries: the FramingValidation schema has a non-trivial
        # invariant (revised_set <-> verdict). Copilot occasionally
        # produces verdict="revised" with revised_set=None on first
        # try; retry catches that.
        output_retries=2,
    )

    logger.info(
        "Advocate-Judge framings_validator agent created",
        extra={"model": str(model)},
    )
    return agent
