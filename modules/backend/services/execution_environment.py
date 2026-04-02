"""
Execution Environment Service.

Facade over execution backends (container, worktree). Resolves or creates
environments for agent task execution and manages their lifecycle.

The ExecutionBackend protocol defines the interface that all backends
implement. ExecutionEnvironmentService dispatches to the appropriate
backend based on the requested execution mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class EnvironmentHandle:
    """Lightweight handle for an active execution environment."""

    environment_id: str
    mode: str  # "local", "worktree", "container"
    working_dir: Path
    branch_name: str | None = None
    container_id: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CommandResult:
    """Result of executing a command in an environment."""

    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# ExecutionBackend protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ExecutionBackend(Protocol):
    """Shared interface for execution environment backends.

    Both ContainerBackend and WorktreeBackend implement this protocol
    so ExecutionEnvironmentService can dispatch through a uniform
    interface (strategy pattern).
    """

    async def create(
        self,
        name: str,
        config: dict[str, Any],
    ) -> EnvironmentHandle:
        """Create a new execution environment. Returns a handle."""
        ...

    async def execute(
        self,
        handle: EnvironmentHandle,
        command: list[str],
        timeout_seconds: int = 300,
        env_vars: dict[str, str] | None = None,
    ) -> CommandResult:
        """Execute a command in the environment."""
        ...

    async def cleanup(
        self,
        handle: EnvironmentHandle,
    ) -> None:
        """Destroy the environment and free resources."""
        ...


# ---------------------------------------------------------------------------
# Local backend (no-op — runs in-process)
# ---------------------------------------------------------------------------


class LocalBackend:
    """No-op backend for local execution. Environment is the current process."""

    async def create(
        self,
        name: str,
        config: dict[str, Any],
    ) -> EnvironmentHandle:
        from modules.backend.core.config import find_project_root

        return EnvironmentHandle(
            environment_id=f"local-{name}",
            mode="local",
            working_dir=find_project_root(),
        )

    async def execute(
        self,
        handle: EnvironmentHandle,
        command: list[str],
        timeout_seconds: int = 300,
        env_vars: dict[str, str] | None = None,
    ) -> CommandResult:
        import asyncio
        import time

        start = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(handle.working_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env_vars,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return CommandResult(
                exit_code=-1,
                stdout="",
                stderr=f"Command timed out after {timeout_seconds}s",
                duration_seconds=time.monotonic() - start,
            )

        return CommandResult(
            exit_code=proc.returncode or 0,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
            duration_seconds=time.monotonic() - start,
        )

    async def cleanup(self, handle: EnvironmentHandle) -> None:
        pass  # Nothing to clean up for local execution


# ---------------------------------------------------------------------------
# ExecutionEnvironmentService
# ---------------------------------------------------------------------------


class ExecutionEnvironmentService:
    """Facade dispatching to the appropriate backend by execution mode.

    Usage:
        service = ExecutionEnvironmentService()
        handle = await service.resolve_or_create("my-task", mode="container", config={...})
        result = await service.execute(handle, ["pytest", "tests/"])
        await service.cleanup(handle)
    """

    def __init__(self) -> None:
        self._backends: dict[str, ExecutionBackend] = {
            "local": LocalBackend(),
        }

    def register_backend(self, mode: str, backend: ExecutionBackend) -> None:
        """Register a backend for a given execution mode."""
        self._backends[mode] = backend
        logger.info("Registered execution backend", extra={"mode": mode})

    async def resolve_or_create(
        self,
        name: str,
        mode: str = "local",
        config: dict[str, Any] | None = None,
    ) -> EnvironmentHandle:
        """Create or reuse an execution environment.

        Args:
            name: Environment name (typically mission-id or task-id)
            mode: Execution mode — "local", "worktree", or "container"
            config: Backend-specific configuration

        Returns:
            EnvironmentHandle for the provisioned environment

        Raises:
            ValueError: If the requested mode has no registered backend
        """
        backend = self._backends.get(mode)
        if backend is None:
            available = ", ".join(self._backends.keys())
            raise ValueError(
                f"No backend registered for mode '{mode}'. "
                f"Available: {available}"
            )

        handle = await backend.create(name, config or {})
        logger.info(
            "Execution environment created",
            extra={
                "environment_id": handle.environment_id,
                "mode": mode,
                "working_dir": str(handle.working_dir),
            },
        )
        return handle

    async def execute(
        self,
        handle: EnvironmentHandle,
        command: list[str],
        timeout_seconds: int = 300,
        env_vars: dict[str, str] | None = None,
    ) -> CommandResult:
        """Execute a command in the given environment."""
        backend = self._backends.get(handle.mode)
        if backend is None:
            raise ValueError(f"No backend for mode '{handle.mode}'")
        return await backend.execute(handle, command, timeout_seconds, env_vars)

    async def cleanup(self, handle: EnvironmentHandle) -> None:
        """Destroy an environment and free its resources."""
        backend = self._backends.get(handle.mode)
        if backend is None:
            return
        await backend.cleanup(handle)
        logger.info(
            "Execution environment cleaned up",
            extra={"environment_id": handle.environment_id, "mode": handle.mode},
        )
