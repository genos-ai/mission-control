"""
Shared research tool implementations (Plan 40 §4.4).

Thin async wrappers over search service methods. Each function
accepts an httpx client and delegates to the service layer.
No PydanticAI dependency — tools are registered via @agent.tool
in each agent's create_agent() factory.

Tavily results include content snippets. Call fetch_and_extract
only when the Tavily snippet is too short (< 500 chars) or the
source is from Brave (no content included).
"""

from __future__ import annotations

from pathlib import Path

import httpx

from modules.backend.core.logging import get_logger
from modules.backend.services.search.content_extract import ContentExtractService
from modules.backend.services.search.web_search import WebSearchService

logger = get_logger(__name__)


async def web_search(
    http_client: httpx.AsyncClient,
    query: str,
    *,
    max_results: int = 10,
    search_depth: str = "advanced",
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> list[dict]:
    """Search the web using Tavily (primary) or Brave (fallback).

    Returns a list of results, each with url, title, snippet, content,
    relevance_score, and provider. Tavily results include content directly;
    Brave results have empty content (use fetch_and_extract separately).
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


async def fetch_and_extract(
    http_client: httpx.AsyncClient,
    url: str,
    *,
    max_length: int = 50_000,
    timeout_seconds: float = 15.0,
) -> dict:
    """Fetch a URL and extract readable content.

    Uses cascading extraction: trafilatura → readability-lxml → Jina Reader.
    Returns extracted text, title, word_count, quality_score, and method.
    """
    svc = ContentExtractService(http_client)
    result = await svc.extract(url, max_length=max_length, timeout_seconds=timeout_seconds)
    return result.model_dump()


async def search_codebase(
    project_root: str | Path,
    query: str,
    *,
    file_patterns: list[str] | None = None,
    max_results: int = 20,
) -> list[dict]:
    """Search the local codebase for a query string.

    Uses grep-style search with glob pattern filtering.
    Returns matches with file path, line number, and content.
    """
    from modules.backend.services.search.codebase_search import CodebaseSearchService

    svc = CodebaseSearchService(project_root)
    return await svc.search(query, file_patterns=file_patterns, max_results=max_results)
