"""
Tool: run_command

Run a shell command in the agent's execution environment.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import RunContext

from modules.backend.core.logging import get_logger

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
    working_dir: str | None = None,
) -> dict[str, Any]:
    """Run a shell command in the agent's execution environment.

    When environment_handle is set, executes inside the container/worktree.
    When None, executes locally with subprocess.

    Args:
        command: Shell command to execute (e.g., "pytest tests/ -x")
        environment_handle: EnvironmentHandle from deps (None = local)
        timeout_seconds: Maximum execution time
        working_dir: Override working directory (relative to workspace)

    Returns:
        Dict with exit_code, stdout, stderr, duration_seconds
    """
    if environment_handle is not None:
        return await _run_in_environment(
            command, environment_handle, timeout_seconds, working_dir,
        )
    return await _run_local(command, timeout_seconds)


async def _run_in_environment(
    command: str,
    handle: Any,
    timeout_seconds: int,
    working_dir: str | None,
) -> dict[str, Any]:
    """Execute command inside a container/worktree environment."""
    from modules.backend.services.execution_environment import (
        ExecutionEnvironmentService,
    )

    service = ExecutionEnvironmentService()
    if handle.mode == "container":
        from modules.backend.services.container_backend import ContainerBackend
        service.register_backend("container", ContainerBackend())

    result = await service.execute(
        handle,
        ["sh", "-c", command],
        timeout_seconds=timeout_seconds,
    )

    return {
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "duration_seconds": result.duration_seconds,
        "environment": handle.mode,
        "success": result.exit_code == 0,
    }


async def _run_local(command: str, timeout_seconds: int) -> dict[str, Any]:
    """Execute command locally with timeout protection."""
    import asyncio
    import time

    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_seconds,
        )
        return {
            "exit_code": proc.returncode or 0,
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
            "duration_seconds": time.monotonic() - start,
            "environment": "local",
            "success": proc.returncode == 0,
        }
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Command timed out after {timeout_seconds}s",
            "duration_seconds": time.monotonic() - start,
            "environment": "local",
            "success": False,
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
