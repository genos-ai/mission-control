"""
Tool: run_tests

Run the unit test suite and return results.
"""

import subprocess
import sys
from pathlib import Path

from pydantic_ai import RunContext


TOOL_DEF = {
    "name": "run_tests",
    "description": "Run the unit test suite and return results",
    "category": "code",
    "deps": ["project_root"],
}


async def run_tests(project_root: Path) -> dict:
    """Run the unit test suite and return results.

    Returns:
        Dict with passed (bool), exit_code (int), and output (str tail).
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit", "-v", "--tb=short"],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )

    output_lines = result.stdout.splitlines()
    tail = "\n".join(output_lines[-50:]) if len(output_lines) > 50 else result.stdout
    passed = result.returncode == 0

    return {
        "passed": passed,
        "exit_code": result.returncode,
        "output": tail,
    }


# ── Registry integration ─────────────────────────────────

_impl = run_tests


def register(agent):
    """Register this tool on a PydanticAI agent."""
    @agent.tool
    async def run_tests(ctx: RunContext) -> dict:
        """Run the unit test suite and return results."""
        return await _impl(ctx.deps.project_root)
