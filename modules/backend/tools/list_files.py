"""
Tool: list_files

List all Python files in scope, respecting exclusion patterns.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_ai import RunContext

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


# ── Registry integration ─────────────────────────────────

TOOL_DEF = {
    "name": "list_files",
    "description": "List all Python files in scope",
    "category": "filesystem",
    "deps": ["project_root", "scope"],
}

_impl = list_files


def register(agent):
    """Register this tool on a PydanticAI agent."""

    @agent.tool
    async def list_files(ctx: RunContext) -> list[str]:
        """List all Python files in scope, respecting exclusion patterns."""
        exclusions = set()
        config = getattr(ctx.deps, "config", None)
        if config and getattr(config, "exclusions", None):
            exclusions = set(config.exclusions.paths)
        return await _impl(ctx.deps.project_root, ctx.deps.scope, exclusions)
