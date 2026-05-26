"""
Deliberation Research Packet Builder Agent
(deliberation.research_packet_builder.agent).

Plan 81 Phase 0 — step 3 of 3. Takes the question + sub_questions +
EvidenceCorpus (from the upstream gatherer) and reshapes them into
the existing ResearchPacket schema consumed by ~10 downstream
deliberation steps.

This is a low-creativity, refusal-resistant agent: its primary task
is shape adaptation on already-gathered evidence. Tool access is
provided for gap-filling only (e.g. finding a second camp when the
corpus shows only one side), and the prompt actively discourages
re-doing the gatherer's work.

Tool access: search_web, fetch_url, query_knowledge — populated from
agent.yaml via the tool registry.
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
    """Factory: create the deliberation research packet builder agent.

    Called by AgentRegistry.get_instance() on first use. Cached.
    Tools are injected from the registry based on the agent's YAML
    config.
    """
    instructions = assemble_instructions(
        "deliberation", "research_packet_builder",
    )

    agent = Agent(
        model,
        deps_type=ResearchAgentDeps,
        output_type=ResearchPacket,
        instructions=instructions,
        # ResearchPacket has hard minima (3 sourced claims,
        # 2 disagreements, 3 under-discussed angles). Give the
        # model two retries on schema validation failures.
        output_retries=2,
    )

    if tool_names:
        from modules.backend.tools.registry import get_tool_registry
        get_tool_registry().register_on_agent(agent, tool_names)

    logger.info(
        "Deliberation research packet builder agent created",
        extra={"model": str(model), "tools": tool_names or []},
    )
    return agent
