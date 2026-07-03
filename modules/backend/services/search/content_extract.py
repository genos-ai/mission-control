"""
Content extraction service (Plan 40 §4.2).

Cascading extraction: trafilatura → readability-lxml → Jina Reader API.
Each extractor is tried in order; the first to return non-empty text wins.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
from readability import Document as ReadabilityDocument

from modules.backend.core.logging import get_logger
from modules.backend.schemas.research import ExtractedContent

logger = get_logger(__name__)

# SSRF guard. fetch_url targets are chosen by LLM agents and can be steered
# by untrusted input (user prompts, fetched web content), so a target may
# point at internal infrastructure. We allow only http(s) and refuse any
# host that resolves to a non-public address.
_ALLOWED_SCHEMES = frozenset({"http", "https"})
_MAX_REDIRECTS = 5


def _ip_is_blocked(ip_str: str) -> bool:
    """True if the address is private/loopback/link-local/reserved etc."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparseable — refuse
    # Unwrap IPv4-mapped IPv6 (e.g. ::ffff:10.0.0.1) so the checks apply.
    if ip.version == 6 and getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def _assert_url_allowed(url: str) -> None:
    """Raise ValueError if the URL is non-http(s) or resolves to a
    non-public address. Resolution closes DNS-based SSRF; redirects are
    validated per hop by the caller. (A determined DNS-rebinding attacker
    could still race the resolve/connect window — out of scope here.)
    """
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"Blocked URL scheme: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise ValueError("URL has no host")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    loop = asyncio.get_event_loop()
    try:
        infos = await loop.getaddrinfo(
            host,
            port,
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror as e:
        raise ValueError(f"DNS resolution failed for host {host!r}") from e
    for info in infos:
        ip_str = info[4][0]
        if _ip_is_blocked(ip_str):
            raise ValueError(f"Blocked non-public address {ip_str} for host {host!r}")


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
        # SSRF guard: refuse non-public targets before any network call
        # (covers the Jina relay fallback too).
        try:
            await _assert_url_allowed(url)
        except ValueError as e:
            logger.warning(
                "Blocked content extraction for unsafe URL",
                extra={"url": url[:120], "reason": str(e)},
            )
            return ExtractedContent(url=url, text="", extraction_method="blocked")

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
        """Fetch raw HTML from URL.

        Follows redirects manually so each hop is SSRF-validated before we
        connect — a public URL that 30x-redirects to an internal address
        (e.g. cloud metadata) is otherwise a classic bypass.
        """
        try:
            current = url
            for _ in range(_MAX_REDIRECTS + 1):
                await _assert_url_allowed(current)
                resp = await self._client.get(
                    current,
                    timeout=timeout_seconds,
                    follow_redirects=False,
                    headers={"User-Agent": "MissionControl-Research/1.0"},
                )
                if resp.is_redirect and "location" in resp.headers:
                    current = urljoin(current, resp.headers["location"])
                    continue
                resp.raise_for_status()
                return resp.text
            logger.warning("Too many redirects", extra={"url": url[:120]})
            return ""
        except Exception:
            logger.warning("Failed to fetch HTML", extra={"url": url[:120]}, exc_info=True)
            return ""

    @staticmethod
    def _extract_trafilatura(html: str, url: str) -> tuple[str, str | None]:
        """Extract text using trafilatura.

        Single call with output_format="json" returns both text and
        metadata (title, author, date). Avoids double-parsing the HTML.
        """
        try:
            raw = trafilatura.extract(
                html,
                url=url,
                output_format="json",
                include_comments=False,
                include_tables=True,
                favor_precision=True,
            )
            if not raw or not isinstance(raw, str):
                return "", None
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                return raw, None  # raw is plain text if JSON parse fails
            text = parsed.get("text", "")
            title = parsed.get("title") or None
            return text, title
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
