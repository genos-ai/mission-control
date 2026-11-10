"""
Tool: run_command

Run a shell command in the agent's execution environment.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import RunContext

from modules.backend.core.logging import get_logger
from modules.backend.services.execution_environment import run_in_environment

logger = get_logger(__name__)


TOOL_DEF = {
    "name": "run_command",
    "description": "Run a shell command in the execution environment",
    "category": "execution",
    "deps": ["environment_handle"],
}


async def run_command(
    command: str,
    *,
    environment_handle: Any = None,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Run a shell command in the agent's execution environment.

    Commands never run on the worker host: a ``None`` handle raises
    ``ExecutionEnvironmentError`` (Plan 88 contracts 3.8.5).

    Args:
        command: Shell command to execute (e.g., "pytest tests/ -x")
        environment_handle: EnvironmentHandle from deps
        timeout_seconds: Maximum execution time

    Returns:
        Dict with exit_code, stdout, stderr, duration_seconds
    """
    result = await run_in_environment(
        environment_handle,
        ["sh", "-c", command],
        timeout_seconds=timeout_seconds,
    )
    return {
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "duration_seconds": result.duration_seconds,
        "environment": environment_handle.mode,
        "success": result.exit_code == 0,
    }


# ── Registry integration ─────────────────────────────────

_impl = run_command


def register(agent):
    """Register this tool on a PydanticAI agent."""

    @agent.tool
    async def run_command(
        ctx: RunContext,
        command: str,
        timeout_seconds: int = 120,
    ) -> dict:
        """Run a shell command in the execution environment.

        Returns exit_code, stdout, stderr, and duration.
        """
        handle = getattr(ctx.deps, "environment_handle", None)
        return await _impl(command, environment_handle=handle, timeout_seconds=timeout_seconds)
