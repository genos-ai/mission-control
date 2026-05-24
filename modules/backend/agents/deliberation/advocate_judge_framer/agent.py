"""
Advocate-Judge Framer Agent (deliberation.advocate_judge_framer.agent).

Phase 1 of the Advocate-Judge architecture (Plan 80). Decomposes a
contested question into 3-5 candidate answers (the live answer space)
plus the mainstream consensus. Output feeds the framings validator
(P13 separate-agent audit) and then drives the N parallel per-side
researchers.

Tool access: search_web, fetch_url. Used lightly — one or two searches
to anchor framing in real positions. Deep research happens in the
per-side researcher phase, not here.
"""

from pydantic_ai import Agent
from pydantic_ai.models import Model

from modules.backend.agents.mission_control.helpers import assemble_instructions
from modules.backend.agents.research.deps import ResearchAgentDeps
from modules.backend.core.logging import get_logger
from modules.backend.schemas.deliberation_advocate_judge import CandidateSet

logger = get_logger(__name__)


def create_agent(
    model: str | Model,
    tool_names: list[str] | None = None,
) -> Agent[ResearchAgentDeps, CandidateSet]:
    """Factory: create the Advocate-Judge framer agent.

    Called by AgentRegistry.get_instance() on first use. Cached.
    Tools (search_web, fetch_url) are injected from the YAML config.
    """
    instructions = assemble_instructions("deliberation", "advocate_judge_framer")

    agent = Agent(
        model,
        deps_type=ResearchAgentDeps,
        output_type=CandidateSet,
        instructions=instructions,
        # 2 retries: Copilot occasionally returns Markdown narrative
        # instead of invoking the final_result tool. The CandidateSet
        # schema has tight constraints (kebab-case labels, unique
        # labels, 3-5 candidates) that the model sometimes misses on
        # first try.
        output_retries=2,
    )

    if tool_names:
        from modules.backend.tools.registry import get_tool_registry
        get_tool_registry().register_on_agent(agent, tool_names)

    logger.info(
        "Advocate-Judge framer agent created",
        extra={"model": str(model), "tools": tool_names or []},
    )
    return agent
