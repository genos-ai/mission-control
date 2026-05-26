"""
Deliberation Evidence Gatherer Agent (deliberation.evidence_gatherer.agent).

Plan 81 Phase 0 — step 2 of 3. Takes 3-7 sub-questions from the
strategist, performs web searches against each, returns a flat
EvidenceCorpus the packet builder reshapes into a ResearchPacket.

Wide cast, shallow shape. Refusal-safe: when a sub-question yields no
sources, the prompt instructs the agent to add it to `gaps` and move
on rather than refuse the whole task. The schema permits
`findings=[]` so the gatherer never has to fabricate to satisfy
minima.

Tool access: search_web, fetch_url, query_knowledge — populated from
agent.yaml via the tool registry.
"""

from pydantic_ai import Agent
from pydantic_ai.models import Model

from modules.backend.agents.mission_control.helpers import assemble_instructions
from modules.backend.agents.research.deps import ResearchAgentDeps
from modules.backend.core.logging import get_logger
from modules.backend.schemas.deliberation import EvidenceCorpus

logger = get_logger(__name__)


def create_agent(
    model: str | Model,
    tool_names: list[str] | None = None,
) -> Agent[ResearchAgentDeps, EvidenceCorpus]:
    """Factory: create the deliberation evidence gatherer agent.

    Called by AgentRegistry.get_instance() on first use. Cached.
    Tools are injected from the registry based on the agent's YAML
    config.
    """
    instructions = assemble_instructions("deliberation", "evidence_gatherer")

    agent = Agent(
        model,
        deps_type=ResearchAgentDeps,
        output_type=EvidenceCorpus,
        instructions=instructions,
        output_retries=2,
    )

    if tool_names:
        from modules.backend.tools.registry import get_tool_registry
        get_tool_registry().register_on_agent(agent, tool_names)

    logger.info(
        "Deliberation evidence gatherer agent created",
        extra={"model": str(model), "tools": tool_names or []},
    )
    return agent
