"""
Tool: read_file

Read a file within the allowed scope and return content with line numbers.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_ai import RunContext

from modules.backend.agents.deps.base import FileScope


async def read_file(project_root: Path, file_path: str, scope: FileScope) -> str:
    """Read a file within the allowed scope. Returns content with line numbers.

    Args:
        project_root: Absolute path to the project root.
        file_path: Path relative to project root.
        scope: FileScope defining allowed read paths.

    Raises:
        PermissionError: If the path is not in the read scope.
    """
    scope.check_read(file_path)
    full_path = project_root / file_path

    if not full_path.is_file():
        return f"Error: file not found: {file_path}"

    lines = full_path.read_text(encoding="utf-8").splitlines()
    numbered = [f"{i:4d}| {line}" for i, line in enumerate(lines, 1)]
    return "\n".join(numbered)


# ── Registry integration ─────────────────────────────────

TOOL_DEF = {
    "name": "read_file",
    "description": "Read a file within the allowed scope",
    "category": "filesystem",
    "deps": ["project_root", "scope"],
}

_impl = read_file


def register(agent):
    """Register this tool on a PydanticAI agent."""
    @agent.tool
    async def read_file(ctx: RunContext, file_path: str) -> str:
        """Read a file and return its contents with line numbers."""
        return await _impl(ctx.deps.project_root, file_path, ctx.deps.scope)
