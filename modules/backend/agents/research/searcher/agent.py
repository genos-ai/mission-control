"""
Research Searcher Agent (research.searcher.agent).

Executes search for ONE sub-question. Each instance gets its own
context window (context isolation). Searches, extracts content,
produces structured findings with citations.
"""

from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model

from modules.backend.agents.mission_control.helpers import assemble_instructions
from modules.backend.agents.research.deps import ResearchAgentDeps
from modules.backend.agents.tools import research as research_tools
from modules.backend.core.logging import get_logger
from modules.backend.schemas.research import SearchFindings

logger = get_logger(__name__)


def create_agent(model: str | Model) -> Agent[ResearchAgentDeps, SearchFindings]:
    """Factory: create searcher agent with web search tools.

    Called by AgentRegistry.get_instance() on first use. Cached.
    """
    instructions = assemble_instructions("research", "searcher")

    agent = Agent(
        model,
        deps_type=ResearchAgentDeps,
        output_type=SearchFindings,
        instructions=instructions,
        output_retries=3,
    )

    @agent.tool
    async def web_search(
        ctx: RunContext[ResearchAgentDeps],
        query: str,
        max_results: int = 10,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> list[dict]:
        """Search the web for information on a topic.

        Returns results with url, title, snippet, content, and relevance_score.
        Tavily results include content directly. For Brave results (empty content),
        use fetch_and_extract to get the page content.

        Args:
            query: Search query string.
            max_results: Max results to return.
            include_domains: Only return results from these domains.
            exclude_domains: Exclude results from these domains.
        """
        if not ctx.deps.http_client:
            return [{"error": "No HTTP client available"}]
        return await research_tools.web_search(
            ctx.deps.http_client,
            query,
            max_results=max_results,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
        )

    @agent.tool
    async def fetch_and_extract(
        ctx: RunContext[ResearchAgentDeps],
        url: str,
    ) -> dict:
        """Fetch a URL and extract readable text content.

        Use this when a search result's content is empty or too short (< 500 chars).
        Returns extracted text, title, word_count, and quality_score.
        """
        if not ctx.deps.http_client:
            return {"error": "No HTTP client available"}
        return await research_tools.fetch_and_extract(
            ctx.deps.http_client,
            url,
        )

    logger.info("Research searcher agent created", extra={"model": str(model)})
    return agent
