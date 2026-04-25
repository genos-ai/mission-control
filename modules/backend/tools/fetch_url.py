"""
Tool: fetch_url

Fetch a URL and extract readable text content from the HTML.
"""

from __future__ import annotations

import httpx

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
