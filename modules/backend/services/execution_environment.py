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
from modules.backend.core.utils import utc_now

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class EnvironmentHandle:
    """Lightweight handle for an active execution environment.

    For container mode, ``working_dir`` is the container-internal path used
    as workdir for exec commands (always ``/workspace``). ``host_working_dir``
    is the host-side git worktree path that agent filesystem tools should use
    as their ``project_root``. Only non-None for container environments created
    with ``git_aware=True`` (i.e. Plan 47 + onwards).
    """

    environment_id: str
    mode: str  # "local", "worktree", "container"
    working_dir: Path          # container-internal path (used by execute())
    host_working_dir: Path | None = None  # host-side worktree (used by agent tools)
    branch_name: str | None = None
    container_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
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

    Supports persistent environments: containers stay alive across
    multiple executions within a mission. Use get_or_create_for_mission()
    to reuse an existing environment or create a new one.

    Usage:
        service = ExecutionEnvironmentService(db_session)
        handle = await service.get_or_create_for_mission(mission_id, mode="container", config={...})
        result = await service.execute(handle, ["pytest", "tests/"])
        # Don't cleanup — container persists for next execution
    """

    def __init__(self, db_session: Any = None) -> None:
        self._backends: dict[str, ExecutionBackend] = {
            "local": LocalBackend(),
        }
        self._db = db_session

    def register_backend(self, mode: str, backend: ExecutionBackend) -> None:
        """Register a backend for a given execution mode."""
        self._backends[mode] = backend
        logger.info("Registered execution backend", extra={"mode": mode})

    async def get_or_create_for_mission(
        self,
        mission_id: str,
        mode: str = "local",
        config: dict[str, Any] | None = None,
    ) -> EnvironmentHandle:
        """Get an existing environment for this mission or create a new one.

        If a running environment already exists for this mission+mode,
        returns a handle to it. Otherwise creates a new one and persists
        the record in the DB.

        Args:
            mission_id: Mission ID to scope the environment to
            mode: Execution mode — "local", "worktree", or "container"
            config: Backend-specific configuration (only used on create)

        Returns:
            EnvironmentHandle for the environment
        """
        if mode == "local":
            return await self.resolve_or_create(f"local-{mission_id}", mode, config)

        # Check DB for existing running environment
        existing = await self._find_running_environment(mission_id, mode)
        if existing is not None:
            logger.info(
                "Reusing existing environment",
                extra={
                    "environment_id": existing.environment_id,
                    "mission_id": mission_id,
                    "mode": mode,
                    "execution_count": existing.metadata.get("execution_count", 0),
                },
            )
            # Update last execution timestamp
            await self._touch_environment(existing.environment_id)
            return existing

        # Create new environment
        handle = await self.resolve_or_create(mission_id, mode, config)

        # Persist to DB
        await self._persist_environment(mission_id, handle, config)

        return handle

    async def resolve_or_create(
        self,
        name: str,
        mode: str = "local",
        config: dict[str, Any] | None = None,
    ) -> EnvironmentHandle:
        """Create a new execution environment (no DB persistence).

        For persistent environments, use get_or_create_for_mission() instead.
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

        # Mark as destroyed in DB
        await self._mark_destroyed(handle.environment_id)

        logger.info(
            "Execution environment cleaned up",
            extra={"environment_id": handle.environment_id, "mode": handle.mode},
        )

    async def list_environments_for_mission(
        self, mission_id: str,
    ) -> dict:
        """List execution environments for a mission.

        Returns a dict with mission_id, active_environment, and all_environments.
        """
        if not self._db:
            return {
                "mission_id": mission_id,
                "active_environment": None,
                "all_environments": [],
            }

        from sqlalchemy import select
        from modules.backend.models.execution_environment import ExecutionEnvironmentModel

        result = await self._db.execute(
            select(ExecutionEnvironmentModel).where(
                ExecutionEnvironmentModel.mission_id == mission_id,
            ).order_by(ExecutionEnvironmentModel.created_at.desc())
        )
        envs = list(result.scalars().all())

        environments = []
        for env in envs:
            environments.append({
                "id": str(env.id),
                "mode": env.mode,
                "status": env.status,
                "container_name": env.container_name,
                "image": env.image,
                "execution_count": env.execution_count,
                "last_execution_at": env.last_execution_at,
                "created_at": str(env.created_at),
            })

        active = next(
            (e for e in environments if e["status"].lower() == "running"),
            None,
        )

        return {
            "mission_id": mission_id,
            "active_environment": active,
            "all_environments": environments,
        }

    async def cleanup_for_mission(self, mission_id: str) -> int:
        """Destroy all environments for a mission. Returns count destroyed."""
        if not self._db:
            return 0

        from sqlalchemy import select, text
        from modules.backend.models.execution_environment import (
            ExecutionEnvironmentModel,
            EnvironmentStatus,
        )

        result = await self._db.execute(
            select(ExecutionEnvironmentModel).where(
                ExecutionEnvironmentModel.mission_id == mission_id,
                ExecutionEnvironmentModel.status.in_([
                    EnvironmentStatus.RUNNING.value,
                    EnvironmentStatus.CREATING.value,
                ]),
            )
        )
        envs = list(result.scalars().all())

        count = 0
        for env in envs:
            handle = EnvironmentHandle(
                environment_id=env.container_name or str(env.id),
                mode=env.mode,
                working_dir=Path(env.working_dir or "/workspace"),
                container_id=env.container_id,
            )
            try:
                await self.cleanup(handle)
                count += 1
            except Exception:
                logger.debug("Failed to cleanup env", extra={"env_id": str(env.id)})

        return count

    # --- DB persistence helpers ---

    async def _find_running_environment(
        self, mission_id: str, mode: str,
    ) -> EnvironmentHandle | None:
        """Find a running environment for this mission+mode in the DB."""
        if not self._db:
            return None

        from sqlalchemy import select
        from modules.backend.models.execution_environment import (
            ExecutionEnvironmentModel,
            EnvironmentStatus,
        )

        result = await self._db.execute(
            select(ExecutionEnvironmentModel).where(
                ExecutionEnvironmentModel.mission_id == mission_id,
                ExecutionEnvironmentModel.mode == mode,
                ExecutionEnvironmentModel.status.in_([
                    EnvironmentStatus.RUNNING.value,
                    "RUNNING",  # handle case mismatch from DB
                ]),
            )
        )
        env = result.scalar_one_or_none()
        if env is None:
            return None

        # Verify the container is actually still running
        if mode == "container" and env.container_id:
            try:
                import docker
                client = docker.from_env()
                container = client.containers.get(env.container_id)

                if container.status == "running":
                    pass  # All good — reuse it

                elif container.status in ("exited", "created", "paused"):
                    # Container exists but stopped — restart it to preserve state
                    logger.info(
                        "Restarting stopped container to preserve state",
                        extra={
                            "container_name": env.container_name,
                            "container_id": env.container_id,
                            "container_status": container.status,
                            "executions_preserved": env.execution_count,
                        },
                    )
                    container.start()
                    env.status = EnvironmentStatus.RUNNING.value
                    await self._db.flush()

                else:
                    # Dead/removing — can't recover
                    logger.warning(
                        "Container in unrecoverable state — state lost, creating new",
                        extra={
                            "container_name": env.container_name,
                            "container_id": env.container_id,
                            "container_status": container.status,
                            "executions_lost": env.execution_count,
                            "last_execution_at": env.last_execution_at,
                            "mission_id": mission_id,
                        },
                    )
                    env.status = EnvironmentStatus.FAILED.value
                    await self._db.flush()
                    return None

            except docker.errors.NotFound:
                logger.warning(
                    "Container no longer exists — state lost, creating new",
                    extra={
                        "container_name": env.container_name,
                        "container_id": env.container_id,
                        "executions_lost": env.execution_count,
                        "last_execution_at": env.last_execution_at,
                        "mission_id": mission_id,
                    },
                )
                env.status = EnvironmentStatus.FAILED.value
                await self._db.flush()
                return None

            except Exception as e:
                logger.warning(
                    "Docker unreachable — cannot verify container, creating new",
                    extra={
                        "container_name": env.container_name,
                        "container_id": env.container_id,
                        "executions_at_risk": env.execution_count,
                        "error": str(e),
                        "mission_id": mission_id,
                    },
                )
                env.status = EnvironmentStatus.FAILED.value
                await self._db.flush()
                return None

        # Reconstruct host_working_dir from persisted config (set by ContainerBackend
        # when git_aware=True — only present for Plan 47+ environments).
        host_working_dir: Path | None = None
        if env.config and env.config.get("host_working_dir"):
            host_working_dir = Path(env.config["host_working_dir"])

        return EnvironmentHandle(
            environment_id=env.container_name or str(env.id),
            mode=env.mode,
            working_dir=Path(env.working_dir or "/workspace"),
            host_working_dir=host_working_dir,
            branch_name=env.branch_name,
            container_id=env.container_id,
            created_at=env.created_at,
            metadata={
                "db_id": str(env.id),
                "execution_count": env.execution_count,
                "image": env.image,
            },
        )

    async def _persist_environment(
        self, mission_id: str, handle: EnvironmentHandle, config: dict | None,
    ) -> None:
        """Save a new environment record to the DB."""
        if not self._db:
            return

        from modules.backend.models.execution_environment import (
            ExecutionEnvironmentModel,
            EnvironmentStatus,
        )
        from modules.backend.core.utils import utc_now

        # Merge host_working_dir into persisted config so it can be reconstructed
        # from the DB on backend restart (see _find_running_environment).
        persisted_config = dict(config) if config else {}
        if handle.host_working_dir is not None:
            persisted_config["host_working_dir"] = str(handle.host_working_dir)

        env = ExecutionEnvironmentModel(
            mission_id=mission_id,
            mode=handle.mode,
            status=EnvironmentStatus.RUNNING.value,
            container_id=handle.container_id,
            container_name=handle.environment_id,
            branch_name=handle.branch_name,
            working_dir=str(handle.working_dir),
            image=handle.metadata.get("image"),
            execution_count=1,
            last_execution_at=utc_now(),
            config=persisted_config,
        )
        self._db.add(env)
        await self._db.flush()

    async def _touch_environment(self, environment_id: str) -> None:
        """Update last_execution_at and increment execution_count."""
        if not self._db:
            return

        from sqlalchemy import text
        from modules.backend.core.utils import utc_now

        await self._db.execute(
            text(
                "UPDATE execution_environments "
                "SET last_execution_at = :ts, execution_count = execution_count + 1 "
                "WHERE container_name = :eid AND LOWER(status) = 'running'"
            ),
            {"ts": utc_now(), "eid": environment_id},
        )
        await self._db.flush()

    async def _mark_destroyed(self, environment_id: str) -> None:
        """Mark an environment as destroyed in the DB."""
        if not self._db:
            return

        from sqlalchemy import text

        await self._db.execute(
            text(
                "UPDATE execution_environments "
                "SET status = 'destroyed' "
                "WHERE container_name = :eid"
            ),
            {"eid": environment_id},
        )
        await self._db.flush()
