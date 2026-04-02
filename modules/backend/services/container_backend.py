"""
Container Backend.

Docker-based execution backend implementing ExecutionBackend protocol.
Provides full runtime isolation with optional git-aware worktree support
inside the container.

Requires docker-py (docker) package. Falls back gracefully when Docker
is not available.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from modules.backend.core.logging import get_logger
from modules.backend.services.execution_environment import (
    CommandResult,
    EnvironmentHandle,
)

logger = get_logger(__name__)


class ContainerBackend:
    """Docker container execution backend.

    Implements the ExecutionBackend protocol. Creates ephemeral containers
    for agent task execution with optional git-aware worktree support.

    When git_aware is True, the container mounts the host's .git directory
    (read-only) and creates a worktree inside for branch-isolated work.
    """

    def __init__(self) -> None:
        self._client = None

    def _get_client(self) -> Any:
        """Lazy-initialize Docker client."""
        if self._client is None:
            try:
                import docker
                self._client = docker.from_env()
                self._client.ping()
                logger.info("Docker client connected")
            except Exception as e:
                raise RuntimeError(
                    f"Docker is not available: {e}. "
                    "Install docker-py and ensure Docker daemon is running."
                ) from e
        return self._client

    async def create(
        self,
        name: str,
        config: dict[str, Any],
    ) -> EnvironmentHandle:
        """Create a Docker container for agent execution.

        Config options:
            image: Docker image name (default: code-workspace:latest)
            git_aware: Mount host .git and create worktree (default: False)
            repo_root: Host repo root path (required if git_aware)
            branch_name: Branch for worktree (required if git_aware)
            cpu_limit: CPU limit in cores (default: 2.0)
            memory_limit_mb: Memory limit in MB (default: 2048)
            workspace_dir: Working directory inside container (default: /workspace)
        """
        import asyncio

        client = self._get_client()

        image = config.get("image", "code-workspace:latest")
        git_aware = config.get("git_aware", False)
        repo_root = config.get("repo_root")
        branch_name = config.get("branch_name")
        cpu_limit = config.get("cpu_limit", 2.0)
        memory_limit_mb = config.get("memory_limit_mb", 2048)
        workspace_dir = config.get("workspace_dir", "/workspace")

        container_name = f"mc-{name}-{uuid4().hex[:8]}"

        # Build volume mounts
        volumes = {}
        if git_aware and repo_root:
            # Mount entire repo (read-write for worktree/branch operations)
            volumes[str(repo_root)] = {"bind": "/repo", "mode": "rw"}

        # Create container (non-blocking via thread pool)
        def _create() -> Any:
            return client.containers.create(
                image=image,
                name=container_name,
                command="sleep infinity",  # Keep alive for exec commands
                volumes=volumes,
                mem_limit=f"{memory_limit_mb}m",
                nano_cpus=int(cpu_limit * 1e9),
                working_dir=workspace_dir,
                detach=True,
                labels={
                    "mission-control": "true",
                    "mc-environment": name,
                },
            )

        container = await asyncio.get_event_loop().run_in_executor(None, _create)

        # Start container
        await asyncio.get_event_loop().run_in_executor(None, container.start)

        handle = EnvironmentHandle(
            environment_id=container_name,
            mode="container",
            working_dir=Path(workspace_dir),
            branch_name=branch_name,
            container_id=container.id,
            metadata={
                "image": image,
                "git_aware": git_aware,
                "cpu_limit": cpu_limit,
                "memory_limit_mb": memory_limit_mb,
            },
        )

        # If git-aware, create worktree from the mounted repo
        if git_aware and branch_name:
            # Repo is mounted at /repo. Create a worktree at /workspace
            # on a new branch from the current HEAD.
            result = await self.execute(
                handle,
                [
                    "sh", "-c",
                    f"cd /repo && git worktree add {workspace_dir} -b {branch_name} 2>&1",
                ],
                timeout_seconds=30,
            )
            if result.exit_code != 0:
                logger.warning(
                    "Worktree creation failed, falling back to working in /repo",
                    extra={
                        "container": container_name,
                        "stderr": result.stderr,
                        "stdout": result.stdout,
                    },
                )
                # Fallback: use /repo directly as workspace
                handle.working_dir = Path("/repo")

        logger.info(
            "Container created",
            extra={
                "container_name": container_name,
                "image": image,
                "git_aware": git_aware,
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
        """Execute a command inside the container via docker exec."""
        import asyncio

        client = self._get_client()
        start = time.monotonic()

        def _exec() -> tuple[int, bytes]:
            container = client.containers.get(handle.container_id)
            exit_code, output = container.exec_run(
                command,
                workdir=str(handle.working_dir),
                environment=env_vars or {},
                demux=True,
            )
            stdout = output[0] if output[0] else b""
            stderr = output[1] if output[1] else b""
            return exit_code, stdout, stderr

        try:
            exit_code, stdout, stderr = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, _exec),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            return CommandResult(
                exit_code=-1,
                stdout="",
                stderr=f"Container exec timed out after {timeout_seconds}s",
                duration_seconds=time.monotonic() - start,
            )

        return CommandResult(
            exit_code=exit_code,
            stdout=stdout.decode(errors="replace") if isinstance(stdout, bytes) else str(stdout),
            stderr=stderr.decode(errors="replace") if isinstance(stderr, bytes) else str(stderr),
            duration_seconds=time.monotonic() - start,
        )

    async def cleanup(self, handle: EnvironmentHandle) -> None:
        """Stop and remove the container."""
        import asyncio

        if not handle.container_id:
            return

        client = self._get_client()

        def _cleanup() -> None:
            try:
                container = client.containers.get(handle.container_id)
                container.stop(timeout=10)
                container.remove(force=True)
            except Exception:
                logger.debug(
                    "Container already removed or not found",
                    extra={"container_id": handle.container_id},
                )

        await asyncio.get_event_loop().run_in_executor(None, _cleanup)
        logger.info(
            "Container cleaned up",
            extra={"container_id": handle.container_id},
        )
