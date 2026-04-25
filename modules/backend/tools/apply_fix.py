"""
Tool: apply_fix

Replace exact text in a file within the allowed scope.
"""

from pathlib import Path

from pydantic_ai import RunContext

from modules.backend.agents.deps.base import FileScope


async def apply_fix(
    project_root: Path,
    file_path: str,
    old_text: str,
    new_text: str,
    scope: FileScope,
) -> dict:
    """Replace exact text in a file within the allowed scope.

    The old_text must appear exactly once in the file.

    Args:
        project_root: Absolute path to the project root.
        file_path: Path relative to project root.
        old_text: Exact text to find (must appear exactly once).
        new_text: Replacement text.
        scope: FileScope defining allowed write paths.

    Returns:
        Dict with success status and file path or error message.
    """
    scope.check_write(file_path)
    full_path = project_root / file_path

    if not full_path.is_file():
        return {"success": False, "error": f"File not found: {file_path}"}

    content = full_path.read_text(encoding="utf-8")
    count = content.count(old_text)

    if count == 0:
        return {"success": False, "error": "old_text not found in file"}
    if count > 1:
        return {"success": False, "error": f"old_text found {count} times — must be unique"}

    new_content = content.replace(old_text, new_text, 1)
    full_path.write_text(new_content, encoding="utf-8")

    return {"success": True, "file": file_path}


# ── Registry integration ─────────────────────────────────

TOOL_DEF = {
    "name": "apply_fix",
    "description": "Replace exact text in a file within the allowed scope",
    "category": "code",
    "deps": ["project_root", "scope"],
}

_impl = apply_fix


def register(agent):
    """Register this tool on a PydanticAI agent."""
    @agent.tool
    async def apply_fix(
        ctx: RunContext,
        file_path: str,
        old_text: str,
        new_text: str,
    ) -> dict:
        """Replace exact text in a file. old_text must appear exactly once."""
        return await _impl(ctx.deps.project_root, file_path, old_text, new_text, ctx.deps.scope)
