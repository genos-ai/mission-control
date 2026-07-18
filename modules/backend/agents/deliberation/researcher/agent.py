"""
Deliberation Researcher Agent (deliberation.researcher.agent).

Phase 0 of the Think Tank workflow (Plan 79). Assembles the structured
evidence packet that the four debaters will use during the blind
opening and subsequent debate rounds. Sonnet 4.6 — better recall than
Haiku for the synthesis/citation work; not Opus-tier reasoning.

Tool access: search_web, fetch_url, query_knowledge — populated from
agent.yaml via the tool registry.

The researcher does NOT take a position. It produces a `ResearchPacket`
(see modules.backend.schemas.deliberation). A separate
deliberation.research_verifier.agent audits the packet before the
debaters see it (P13 — no self-evaluation).
"""

from pydantic_ai import Agent
from pydantic_ai.models import Model

from modules.backend.agents.mission_control.helpers import assemble_instructions
from modules.backend.agents.research.deps import ResearchAgentDeps
from modules.backend.core.logging import get_logger
from modules.backend.schemas.deliberation import ResearchPacket

logger = get_logger(__name__)


def create_agent(
    model: str | Model,
    tool_names: list[str] | None = None,
) -> Agent[ResearchAgentDeps, ResearchPacket]:
    """Factory: create the deliberation researcher agent.

    Called by AgentRegistry.get_instance() on first use. Cached.
    Tools are injected from the registry based on the agent's YAML config.
    """
    instructions = assemble_instructions("deliberation", "researcher")

    agent = Agent(
        model,
        deps_type=ResearchAgentDeps,
        output_type=ResearchPacket,
        instructions=instructions,
        # 2 retries: same Copilot narrative-vs-tool quirk as the verifier.
        # The packet is large (many sourced claims) so retries cost less
        # than a corrupted run.
        output_retries=2,
    )

    if tool_names:
        from modules.backend.tools.registry import get_tool_registry

        get_tool_registry().register_on_agent(agent, tool_names)

    logger.info(
        "Deliberation researcher agent created",
        extra={"model": str(model), "tools": tool_names or []},
    )
    return agent
