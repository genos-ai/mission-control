"""
Tool: search_codebase

Search the local codebase for a query string using grep-style matching.
"""

from __future__ import annotations

from pathlib import Path

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


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
