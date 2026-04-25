"""
Tool: list_files

List all Python files in scope, respecting exclusion patterns.
"""

from __future__ import annotations

from pathlib import Path

from modules.backend.agents.deps.base import FileScope


async def list_files(
    project_root: Path,
    scope: FileScope,
    exclusion_paths: set[str] | None = None,
) -> list[str]:
    """List all Python files in scope, respecting exclusion patterns.

    Args:
        project_root: Absolute path to the project root.
        scope: FileScope defining allowed read paths.
        exclusion_paths: Set of path prefixes to exclude.

    Returns:
        Sorted list of relative paths to Python files within scope.
    """
    exclusions = exclusion_paths or set()
    files: list[str] = []

    for py_file in sorted(project_root.rglob("*.py")):
        rel = str(py_file.relative_to(project_root))
        if not scope.is_readable(rel):
            continue
        excluded = False
        for excl in exclusions:
            if rel.startswith(excl) or rel.startswith(excl.rstrip("/")):
                excluded = True
                break
        if not excluded:
            files.append(rel)

    return files
