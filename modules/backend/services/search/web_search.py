"""
Web search service (Plan 40 §4.1).

Provides web search with automatic fallback: Tavily → Brave.
Tavily returns content snippets directly; Brave returns URLs only
(content extraction needed separately via ContentExtractService).
"""

from __future__ import annotations

import httpx

from modules.backend.core.config import get_settings
from modules.backend.core.logging import get_logger
from modules.backend.schemas.research import SearchResult

logger = get_logger(__name__)

# Tavily search depth options
_TAVILY_DEPTHS = {"basic", "advanced"}


class WebSearchService:
    """Web search with Tavily primary, Brave fallback."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._client = http_client
        settings = get_settings()
        self._tavily_key = settings.tavily_api_key
        self._brave_key = settings.brave_api_key

    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        search_depth: str = "advanced",
        provider: str | None = None,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> list[SearchResult]:
        """Search with automatic fallback: tavily → brave.

        Args:
            query: Search query string.
            max_results: Maximum number of results to return.
            search_depth: Tavily search depth — "basic" or "advanced".
            provider: Force a specific provider ("tavily" or "brave").
                      If None, tries Tavily first, falls back to Brave.
            include_domains: Only return results from these domains.
            exclude_domains: Exclude results from these domains.

        Returns:
            List of SearchResult with url, title, snippet, and content
            (content populated for Tavily results, empty for Brave).
        """
        chosen = provider or ("tavily" if self._tavily_key else "brave")

        if chosen == "tavily" and self._tavily_key:
            try:
                return await self._search_tavily(
                    query,
                    max_results=max_results,
                    search_depth=search_depth,
                    include_domains=include_domains,
                    exclude_domains=exclude_domains,
                )
            except Exception as tavily_err:
                # Extract HTTP status if available (httpx.HTTPStatusError)
                status = getattr(getattr(tavily_err, "response", None), "status_code", None)
                logger.warning(
                    "Tavily search failed, falling back to Brave",
                    extra={
                        "query": query[:80],
                        "status_code": status,
                        "error": str(tavily_err)[:200],
                    },
                )
                if self._brave_key:
                    try:
                        return await self._search_brave(
                            query,
                            max_results=max_results,
                        )
                    except Exception as brave_err:
                        logger.error(
                            "Both search providers failed",
                            extra={
                                "query": query[:80],
                                "tavily_error": str(tavily_err)[:150],
                                "brave_error": str(brave_err)[:150],
                            },
                        )
                        raise brave_err from tavily_err
                raise

        if chosen == "brave" and self._brave_key:
            return await self._search_brave(query, max_results=max_results)

        logger.error("No search provider available (set TAVILY_API_KEY or BRAVE_API_KEY)")
        return []

    async def _search_tavily(
        self,
        query: str,
        *,
        max_results: int = 10,
        search_depth: str = "advanced",
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> list[SearchResult]:
        """Search via Tavily API. Returns results with content included."""
        depth = search_depth if search_depth in _TAVILY_DEPTHS else "advanced"
        payload: dict = {
            "query": query,
            "max_results": max_results,
            "search_depth": depth,
            "include_answer": False,
        }
        if include_domains:
            payload["include_domains"] = include_domains
        if exclude_domains:
            payload["exclude_domains"] = exclude_domains

        resp = await self._client.post(
            "https://api.tavily.com/search",
            json=payload,
            headers={"Authorization": f"Bearer {self._tavily_key}"},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("results", [])[:max_results]:
            results.append(SearchResult(
                url=item.get("url", ""),
                title=item.get("title", ""),
                snippet=item.get("content", "")[:500],
                content=item.get("content", ""),
                relevance_score=item.get("score", 0.0),
                provider="tavily",
            ))

        logger.info(
            "Tavily search complete",
            extra={"query": query[:80], "results": len(results)},
        )
        return results

    async def _search_brave(
        self,
        query: str,
        *,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """Search via Brave Search API. Returns URLs + snippets (no content)."""
        resp = await self._client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results},
            headers={
                "X-Subscription-Token": self._brave_key,
                "Accept": "application/json",
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("web", {}).get("results", [])[:max_results]:
            results.append(SearchResult(
                url=item.get("url", ""),
                title=item.get("title", ""),
                snippet=item.get("description", ""),
                content="",  # Brave doesn't return content — use ContentExtractService
                relevance_score=0.0,
                provider="brave",
            ))

        logger.info(
            "Brave search complete",
            extra={"query": query[:80], "results": len(results)},
        )
        return results
