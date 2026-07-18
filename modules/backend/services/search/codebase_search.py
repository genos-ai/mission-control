"""
Codebase search service (Plan 40 §4.3).

Wraps existing codemap tools for internal codebase search:
grep, glob, and AST-level search via the code map.
"""

from __future__ import annotations

import asyncio
import glob as globlib
import re
from pathlib import Path

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


class CodebaseSearchService:
    """Search within a local codebase using grep and glob patterns."""

    def __init__(self, project_root: Path | str) -> None:
        self._root = Path(project_root)

    async def search(
        self,
        query: str,
        *,
        file_patterns: list[str] | None = None,
        max_results: int = 20,
    ) -> list[dict]:
        """Search codebase for a query string.

        Args:
            query: Text or regex pattern to search for.
            file_patterns: Glob patterns to filter files (e.g. ["*.py", "*.ts"]).
                          Defaults to ["*.py"].
            max_results: Maximum matches to return.

        Returns:
            List of dicts with file, line, content, and context.
        """
        patterns = file_patterns or ["*.py"]
        files = self._collect_files(patterns)

        results = await asyncio.to_thread(self._grep_files, query, files, max_results)

        logger.info(
            "Codebase search complete",
            extra={"query": query[:60], "files_scanned": len(files), "matches": len(results)},
        )
        return results

    def _collect_files(self, patterns: list[str]) -> list[Path]:
        """Collect files matching glob patterns under project root."""
        files: list[Path] = []
        for pattern in patterns:
            matches = globlib.glob(str(self._root / "**" / pattern), recursive=True)
            files.extend(Path(m) for m in matches)
        return sorted(set(files))

    def _grep_files(self, query: str, files: list[Path], max_results: int) -> list[dict]:
        """Search files for query pattern (runs in thread)."""
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error:
            pattern = re.compile(re.escape(query), re.IGNORECASE)

        results: list[dict] = []
        for filepath in files:
            if len(results) >= max_results:
                break
            try:
                text = filepath.read_text(errors="replace")
                for i, line in enumerate(text.splitlines(), 1):
                    if pattern.search(line):
                        results.append(
                            {
                                "file": str(filepath.relative_to(self._root)),
                                "line": i,
                                "content": line.strip()[:200],
                            }
                        )
                        if len(results) >= max_results:
                            break
            except (OSError, UnicodeDecodeError):
                continue
        return results
