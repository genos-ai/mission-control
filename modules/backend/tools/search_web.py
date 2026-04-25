"""
Tool: search_web

Search the web for information using the configured search provider.
"""

from __future__ import annotations

import httpx

from pydantic_ai import RunContext

from modules.backend.core.logging import get_logger
from modules.backend.services.search.web_search import WebSearchService

logger = get_logger(__name__)


async def search_web(
    http_client: httpx.AsyncClient,
    query: str,
    *,
    max_results: int = 10,
    search_depth: str = "advanced",
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> list[dict]:
    """Search the web for information on a topic.

    Returns ranked results with url, title, snippet, content,
    relevance_score, and provider. Provider is selected from config
    (perplexity > tavily > brave fallback chain).
    """
    svc = WebSearchService(http_client)
    results = await svc.search(
        query,
        max_results=max_results,
        search_depth=search_depth,
        include_domains=include_domains,
        exclude_domains=exclude_domains,
    )
    return [r.model_dump() for r in results]


# ── Registry integration ─────────────────────────────────

TOOL_DEF = {
    "name": "search_web",
    "description": "Search the web for information on a topic",
    "category": "search",
    "deps": ["http_client"],
}

_impl = search_web


def register(agent):
    """Register this tool on a PydanticAI agent."""
    @agent.tool
    async def search_web(
        ctx: RunContext,
        query: str,
        max_results: int = 10,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> list[dict]:
        """Search the web for information on a topic.

        Returns results with url, title, snippet, content, and relevance_score.
        Provider is selected from config (perplexity > tavily > brave).
        For results with empty content, use fetch_url to get the page content.
        """
        http_client = getattr(ctx.deps, "http_client", None)
        if not http_client:
            return [{"error": "No HTTP client available"}]
        return await _impl(
            http_client, query,
            max_results=max_results,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
        )
