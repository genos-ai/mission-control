"""
Content extraction service (Plan 40 §4.2).

Cascading extraction: trafilatura → readability-lxml → Jina Reader API.
Each extractor is tried in order; the first to return non-empty text wins.
"""

from __future__ import annotations

import httpx
import trafilatura
from readability import Document as ReadabilityDocument

from modules.backend.core.logging import get_logger
from modules.backend.schemas.research import ExtractedContent

logger = get_logger(__name__)


class ContentExtractService:
    """Extract readable content from URLs with cascading fallback."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._client = http_client

    async def extract(
        self,
        url: str,
        *,
        max_length: int = 50_000,
        timeout_seconds: float = 15.0,
    ) -> ExtractedContent:
        """Extract content from a URL using cascading extraction methods.

        Falls back through: trafilatura → readability-lxml → Jina Reader API.

        Args:
            url: The URL to extract content from.
            max_length: Maximum character length of extracted text.
            timeout_seconds: HTTP request timeout.

        Returns:
            ExtractedContent with extracted text and metadata.
        """
        html = await self._fetch_html(url, timeout_seconds=timeout_seconds)
        if not html:
            return ExtractedContent(url=url, text="", extraction_method="failed")

        # Try trafilatura first (F1 0.958)
        text, title = self._extract_trafilatura(html, url)
        if text and len(text.strip()) > 100:
            return self._build_result(url, text, title, max_length, "trafilatura")

        # Fallback to readability-lxml
        text, title = self._extract_readability(html)
        if text and len(text.strip()) > 100:
            return self._build_result(url, text, title, max_length, "readability")

        # Final fallback: Jina Reader API (no HTML needed)
        text, title = await self._extract_jina(url, timeout_seconds=timeout_seconds)
        if text and len(text.strip()) > 100:
            return self._build_result(url, text, title, max_length, "jina")

        # All methods failed — return whatever we got
        best = text or ""
        return self._build_result(url, best, title, max_length, "partial")

    async def _fetch_html(self, url: str, *, timeout_seconds: float = 15.0) -> str:
        """Fetch raw HTML from URL."""
        try:
            resp = await self._client.get(
                url,
                timeout=timeout_seconds,
                follow_redirects=True,
                headers={"User-Agent": "MissionControl-Research/1.0"},
            )
            resp.raise_for_status()
            return resp.text
        except Exception:
            logger.warning("Failed to fetch HTML", extra={"url": url[:120]}, exc_info=True)
            return ""

    @staticmethod
    def _extract_trafilatura(html: str, url: str) -> tuple[str, str | None]:
        """Extract text using trafilatura."""
        try:
            text = trafilatura.extract(
                html,
                url=url,
                include_comments=False,
                include_tables=True,
                favor_precision=True,
            )
            metadata = trafilatura.extract(
                html,
                url=url,
                output_format="json",
                include_comments=False,
            )
            title = None
            if metadata and isinstance(metadata, str):
                import json
                try:
                    title = json.loads(metadata).get("title")
                except (json.JSONDecodeError, AttributeError):
                    pass
            return text or "", title
        except Exception:
            logger.debug("Trafilatura extraction failed", exc_info=True)
            return "", None

    @staticmethod
    def _extract_readability(html: str) -> tuple[str, str | None]:
        """Extract text using readability-lxml."""
        try:
            doc = ReadabilityDocument(html)
            title = doc.title()
            # readability returns HTML — strip tags for plain text
            summary_html = doc.summary()
            import re
            text = re.sub(r"<[^>]+>", " ", summary_html)
            text = re.sub(r"\s+", " ", text).strip()
            return text, title
        except Exception:
            logger.debug("Readability extraction failed", exc_info=True)
            return "", None

    async def _extract_jina(
        self, url: str, *, timeout_seconds: float = 15.0
    ) -> tuple[str, str | None]:
        """Extract text via Jina Reader API (free tier)."""
        try:
            resp = await self._client.get(
                f"https://r.jina.ai/{url}",
                timeout=timeout_seconds,
                headers={"Accept": "text/plain"},
            )
            resp.raise_for_status()
            text = resp.text
            # Jina returns markdown — first line is often the title
            lines = text.split("\n", 1)
            title = lines[0].lstrip("# ").strip() if lines else None
            return text, title
        except Exception:
            logger.debug("Jina extraction failed", extra={"url": url[:120]}, exc_info=True)
            return "", None

    @staticmethod
    def _build_result(
        url: str,
        text: str,
        title: str | None,
        max_length: int,
        method: str,
    ) -> ExtractedContent:
        """Build an ExtractedContent from raw extraction output."""
        truncated = text[:max_length] if len(text) > max_length else text
        word_count = len(truncated.split())
        # Simple quality heuristic: longer text with a title scores higher
        quality = min(1.0, word_count / 500) * (0.9 if title else 0.7)
        return ExtractedContent(
            url=url,
            title=title,
            text=truncated,
            word_count=word_count,
            quality_score=round(quality, 2),
            extraction_method=method,
        )
