"""
Tool: search_codebase

Search the local codebase for a query string using grep-style matching.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_ai import RunContext

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


# ── Registry integration ─────────────────────────────────

TOOL_DEF = {
    "name": "search_codebase",
    "description": "Search the local codebase for a query string",
    "category": "search",
    "deps": ["project_root"],
}

_impl = search_codebase


def register(agent):
    """Register this tool on a PydanticAI agent."""
    @agent.tool
    async def search_codebase(
        ctx: RunContext,
        query: str,
        file_patterns: list[str] | None = None,
        max_results: int = 20,
    ) -> list[dict]:
        """Search the local codebase for a query string.

        Uses grep-style search with glob pattern filtering.
        Returns matches with file path, line number, and content.
        """
        project_root = getattr(ctx.deps, "project_root", None)
        if not project_root:
            return [{"error": "No project root available"}]
        return await _impl(project_root, query, file_patterns=file_patterns, max_results=max_results)
