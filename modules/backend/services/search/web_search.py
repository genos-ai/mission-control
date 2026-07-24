"""
Web search service (Plan 40 §4.1).

Provides web search with automatic fallback chain:
  foundry → perplexity → tavily → brave

Each provider returns SearchResult objects. Foundry, Perplexity, and
Tavily include content directly; Brave returns URLs only (use
ContentExtractService separately for full content).

Foundry is the Azure-billed path: it calls Microsoft Foundry's
Responses API with the web_search tool (Grounding with Bing Search).
It is preferred when configured because billing flows through the
Azure subscription rather than a third-party API key.
"""

from __future__ import annotations

import httpx

from modules.backend.core.config import get_app_config, get_settings
from modules.backend.core.logging import get_logger
from modules.backend.schemas.research import SearchResult
from modules.backend.services.search.bing_grounding_search import FoundryBingGroundingSearch

logger = get_logger(__name__)

_TAVILY_DEPTHS = {"basic", "advanced"}

# Provider priority — first configured provider wins.
# Foundry is preferred so Azure-subscription billing takes precedence
# over personal third-party API keys when both are present.
_PROVIDER_CHAIN = ["foundry", "perplexity", "tavily", "brave"]


class WebSearchService:
    """Web search with automatic provider fallback."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._client = http_client
        settings = get_settings()
        self._perplexity_key = settings.perplexity_api_key
        self._tavily_key = settings.tavily_api_key
        self._brave_key = settings.brave_api_key
        # Foundry has no key — the project-scoped endpoint in providers.yaml
        # (loaded via get_app_config().providers.foundry_project) is the
        # "configured" signal. AAD auth is handled inside the provider
        # factory in modules.backend.core.model_providers.
        try:
            self._foundry_configured = bool(get_app_config().providers.foundry_project.base_url)
        except Exception:
            self._foundry_configured = False

    def _get_key(self, provider: str) -> str:
        if provider == "foundry":
            return "configured" if self._foundry_configured else ""
        return {
            "perplexity": self._perplexity_key,
            "tavily": self._tavily_key,
            "brave": self._brave_key,
        }.get(provider, "")

    def _default_provider(self) -> str:
        """First provider in the chain that has a key configured."""
        for p in _PROVIDER_CHAIN:
            if self._get_key(p):
                return p
        return "none"

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
        """Search with automatic fallback through the provider chain.

        Args:
            query: Search query string.
            max_results: Maximum number of results to return.
            search_depth: Tavily search depth — "basic" or "advanced".
            provider: Force a specific provider. If None, uses the
                      fallback chain: perplexity → tavily → brave.
            include_domains: Only return results from these domains.
            exclude_domains: Exclude results from these domains.

        Returns:
            List of SearchResult with url, title, snippet, and content.
        """
        if provider:
            return await self._search_provider(
                provider,
                query,
                max_results=max_results,
                search_depth=search_depth,
                include_domains=include_domains,
                exclude_domains=exclude_domains,
            )

        # Fallback chain — try each provider in order
        errors: list[tuple[str, Exception]] = []
        for p in _PROVIDER_CHAIN:
            if not self._get_key(p):
                continue
            try:
                return await self._search_provider(
                    p,
                    query,
                    max_results=max_results,
                    search_depth=search_depth,
                    include_domains=include_domains,
                    exclude_domains=exclude_domains,
                )
            except Exception as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                logger.warning(
                    f"{p.capitalize()} search failed"
                    + (", falling back" if len(errors) < len(_PROVIDER_CHAIN) - 1 else ""),
                    extra={
                        "provider": p,
                        "query": query[:80],
                        "status_code": status,
                        "error": str(e)[:200],
                    },
                )
                errors.append((p, e))

        if errors:
            logger.error(
                "All search providers failed",
                extra={
                    "query": query[:80],
                    "providers_tried": [p for p, _ in errors],
                    "errors": {p: str(e)[:150] for p, e in errors},
                },
            )
            # Raise the last error
            raise errors[-1][1]

        logger.error(
            "No search provider available "
            "(set providers.foundry_project.base_url in providers.yaml for "
            "Azure-billed Bing Grounding, or PERPLEXITY_API_KEY / TAVILY_API_KEY "
            "/ BRAVE_API_KEY for third-party providers)"
        )
        return []

    async def _search_provider(
        self,
        provider: str,
        query: str,
        **kwargs,
    ) -> list[SearchResult]:
        """Route to the correct provider method."""
        dispatch = {
            "foundry": self._search_foundry,
            "perplexity": self._search_perplexity,
            "tavily": self._search_tavily,
            "brave": self._search_brave,
        }
        fn = dispatch.get(provider)
        if not fn:
            raise ValueError(f"Unknown search provider: {provider}")
        return await fn(query, **kwargs)

    # ── Foundry (Bing Grounding via Responses API) ────────────────────

    async def _search_foundry(
        self,
        query: str,
        *,
        max_results: int = 10,
        search_depth: str = "advanced",
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> list[SearchResult]:
        """Search via Microsoft Foundry Responses API + web_search tool.

        Billed against the Azure subscription (Bing Grounding +
        synthesising model tokens). The web_search tool ignores
        include/exclude domain filters; use bing_custom_search if
        domain restriction is required.
        """
        svc = FoundryBingGroundingSearch()
        return await svc.search(
            query,
            max_results=max_results,
            search_depth=search_depth,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
        )

    # ── Perplexity ────────────────────────────────────────────────────

    async def _search_perplexity(
        self,
        query: str,
        *,
        max_results: int = 10,
        search_depth: str = "advanced",
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> list[SearchResult]:
        """Search via Perplexity Sonar API.

        Uses the chat completions endpoint with the sonar model.
        Returns results with content from citations.
        """
        messages = [{"role": "user", "content": query}]

        payload: dict = {
            "model": "sonar",
            "messages": messages,
        }
        if include_domains:
            payload["search_domain_filter"] = include_domains
        if search_depth == "basic":
            payload["search_recency_filter"] = "week"

        resp = await self._client.post(
            "https://api.perplexity.ai/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {self._perplexity_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()

        # Extract the response content and citations
        content = ""
        citations: list[str] = []

        choices = data.get("choices", [])
        if choices:
            message = choices[0].get("message", {})
            content = message.get("content", "")

        citations = data.get("citations", [])

        # Build results — one per citation with the full response as context
        results = []
        for i, url in enumerate(citations[:max_results]):
            results.append(
                SearchResult(
                    url=url,
                    title=url.split("/")[-1].replace("-", " ").title() if "/" in url else url,
                    snippet=content[:500] if i == 0 else "",
                    content=content if i == 0 else "",
                    relevance_score=1.0 - (i * 0.05),
                    provider="perplexity",
                )
            )

        # If no citations but we got content, return as a single result
        if not results and content:
            results.append(
                SearchResult(
                    url="",
                    title="Perplexity response",
                    snippet=content[:500],
                    content=content,
                    relevance_score=1.0,
                    provider="perplexity",
                )
            )

        logger.info(
            "Perplexity search complete",
            extra={
                "query": query[:80],
                "results": len(results),
                "citations": len(citations),
            },
        )
        return results

    # ── Tavily ────────────────────────────────────────────────────────

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
            results.append(
                SearchResult(
                    url=item.get("url", ""),
                    title=item.get("title", ""),
                    snippet=item.get("content", "")[:500],
                    content=item.get("content", ""),
                    relevance_score=item.get("score", 0.0),
                    provider="tavily",
                )
            )

        logger.info(
            "Tavily search complete",
            extra={"query": query[:80], "results": len(results)},
        )
        return results

    # ── Brave ─────────────────────────────────────────────────────────

    async def _search_brave(
        self,
        query: str,
        *,
        max_results: int = 10,
        **kwargs,
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
            results.append(
                SearchResult(
                    url=item.get("url", ""),
                    title=item.get("title", ""),
                    snippet=item.get("description", ""),
                    content="",
                    relevance_score=0.0,
                    provider="brave",
                )
            )

        logger.info(
            "Brave search complete",
            extra={"query": query[:80], "results": len(results)},
        )
        return results
