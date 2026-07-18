"""
Tool: fetch_url

Fetch a URL and extract readable text content from the HTML.
"""

from __future__ import annotations

import httpx
from pydantic_ai import RunContext

from modules.backend.core.logging import get_logger
from modules.backend.services.search.content_extract import ContentExtractService

logger = get_logger(__name__)


async def fetch_url(
    http_client: httpx.AsyncClient,
    url: str,
    *,
    max_length: int = 50_000,
    timeout_seconds: float = 15.0,
) -> dict:
    """Fetch a URL and extract readable content.

    Uses cascading extraction: trafilatura > readability-lxml > Jina Reader.
    Returns extracted text, title, word_count, quality_score, and method.
    """
    svc = ContentExtractService(http_client)
    result = await svc.extract(url, max_length=max_length, timeout_seconds=timeout_seconds)
    return result.model_dump()


# ── Registry integration ─────────────────────────────────

TOOL_DEF = {
    "name": "fetch_url",
    "description": "Fetch a URL and extract readable text content",
    "category": "search",
    "deps": ["http_client"],
}

_impl = fetch_url


def register(agent):
    """Register this tool on a PydanticAI agent."""

    @agent.tool
    async def fetch_url(ctx: RunContext, url: str) -> dict:
        """Fetch a URL and extract readable text content.

        Use this when a search result's content is empty or too short (< 500 chars).
        Returns extracted text, title, word_count, and quality_score.
        """
        http_client = getattr(ctx.deps, "http_client", None)
        if not http_client:
            return {"error": "No HTTP client available"}
        return await _impl(http_client, url)
