"""
Container Backend.

Docker-based execution backend implementing ExecutionBackend protocol.
Provides full runtime isolation via per-mission git worktrees:

  1. A git worktree is created on the HOST at ``{repo_root}/var/worktrees/{name}/workspace/``.
  2. The container is started with that host directory bind-mounted at ``/workspace:rw``.
  3. ``EnvironmentHandle.host_working_dir`` carries the host-side path so agent filesystem
     tools (read_file, list_files, write_file) operate on the worktree — not on the main
     repo.  ``EnvironmentHandle.working_dir`` stays as ``/workspace`` (the container-internal
     path used by execute()).

Security boundary:
  - The container sees ONLY ``/workspace`` from the host.  The full host repo is NOT
    mounted inside the container.
  - Agent commands (run_command) execute inside the container and cannot reach the host
    filesystem beyond the bind-mounted worktree.
  - File reads/writes by agent tools operate on the host-side worktree (fast, native I/O)
    and never touch the main branch.

Requires docker-py (docker) package. Falls back gracefully when Docker is not available.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from modules.backend.core.logging import get_logger
from modules.backend.services.execution_environment import CommandResult, EnvironmentHandle

logger = get_logger(__name__)

_CONTAINER_WORKSPACE = "/workspace"


class ContainerBackend:
    """Docker container execution backend.

    Implements the ExecutionBackend protocol. Creates per-mission containers
    with host-side git worktrees for isolated agent execution.
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
        """Create a Docker container with an isolated host-side git worktree.

        When ``git_aware=True``, a git worktree is created on the HOST at
        ``{repo_root}/var/worktrees/{name}/workspace/`` and bind-mounted into
        the container at ``/workspace``.  The handle's ``host_working_dir`` is
        set to that host path so the executor can redirect ``deps.project_root``.

        Config options:
            image: Docker image name (default: code-workspace:latest)
            git_aware: Create host-side worktree + bind-mount (default: False)
            repo_root: Host repo root path (required if git_aware)
            branch_name: Git branch for the worktree (required if git_aware)
            cpu_limit: CPU limit in cores (default: 2.0)
            memory_limit_mb: Memory limit in MB (default: 2048)
            extra_volumes: Additional bind mounts beyond the worktree.
                List of dicts with keys: host_path, container_path, mode (ro|rw).
                Example: [{"host_path": "/data/target", "container_path": "/workspace/target", "mode": "ro"}]  # noqa: E501
            network_mode: Docker network mode (default: None → Docker default)

        Args:
            name: Unique name for this environment (mission_id or test name).
            config: Backend-specific configuration dict.

        Returns:
            EnvironmentHandle with host_working_dir set when git_aware=True.

        Raises:
            RuntimeError: If Docker is unavailable or the container cannot start.
        """
        client = self._get_client()

        image = config.get("image", "code-workspace:latest")
        git_aware = config.get("git_aware", False)
        repo_root = config.get("repo_root")
        branch_name = config.get("branch_name")
        cpu_limit = config.get("cpu_limit", 2.0)
        memory_limit_mb = config.get("memory_limit_mb", 2048)
        extra_volumes: list[dict[str, str]] = config.get("extra_volumes", [])
        network_mode: str | None = config.get("network_mode")

        container_name = f"mc-{name}-{uuid4().hex[:8]}"

        # --- Host-side worktree (Plan 47 isolation model) ---
        host_working_dir: Path | None = None
        volumes: dict[str, Any] = {}

        if git_aware and repo_root and branch_name:
            host_working_dir = await self._create_host_worktree(
                repo_root=Path(repo_root),
                name=name,
                branch_name=branch_name,
            )
            if host_working_dir is not None:
                # Bind-mount the worktree into the container as /workspace.
                # The container sees ONLY this directory from the host — the
                # full repo is NOT mounted (unlike the previous design).
                volumes[str(host_working_dir)] = {
                    "bind": _CONTAINER_WORKSPACE,
                    "mode": "rw",
                }

        # --- Extra volumes (e.g. read-only target mount, evidence dir) ---
        for vol in extra_volumes:
            hp = vol.get("host_path")
            cp = vol.get("container_path")
            mode = vol.get("mode", "rw")
            if not hp or not cp:
                raise ValueError(f"extra_volumes entry missing host_path or container_path: {vol}")
            if mode not in ("ro", "rw"):
                raise ValueError(f"extra_volumes mode must be 'ro' or 'rw', got '{mode}'")
            volumes[str(hp)] = {"bind": cp, "mode": mode}

        # --- Create and start container ---
        create_kwargs: dict[str, Any] = {
            "image": image,
            "name": container_name,
            "command": "sleep infinity",
            "volumes": volumes,
            "mem_limit": f"{memory_limit_mb}m",
            "nano_cpus": int(cpu_limit * 1e9),
            "working_dir": _CONTAINER_WORKSPACE,
            "detach": True,
            "labels": {
                "mission-control": "true",
                "mc-environment": name,
            },
        }
        if network_mode:
            create_kwargs["network_mode"] = network_mode

        def _create() -> Any:
            return client.containers.create(**create_kwargs)

        container = await asyncio.get_running_loop().run_in_executor(None, _create)
        await asyncio.get_running_loop().run_in_executor(None, container.start)

        handle = EnvironmentHandle(
            environment_id=container_name,
            mode="container",
            working_dir=Path(_CONTAINER_WORKSPACE),
            host_working_dir=host_working_dir,
            branch_name=branch_name,
            container_id=container.id,
            metadata={
                "image": image,
                "git_aware": git_aware,
                "cpu_limit": cpu_limit,
                "memory_limit_mb": memory_limit_mb,
                "extra_volumes_count": len(extra_volumes),
                "network_mode": network_mode,
            },
        )

        logger.info(
            "Container created",
            extra={
                "container_name": container_name,
                "image": image,
                "git_aware": git_aware,
                "host_working_dir": str(host_working_dir) if host_working_dir else None,
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
        """Execute a command inside the container via docker exec.

        Args:
            handle: Active environment handle.
            command: Command + arguments list (e.g. ["sh", "-c", "pytest tests/"]).
            timeout_seconds: Maximum execution time before the exec is cancelled.
            env_vars: Optional environment variable overrides.

        Returns:
            CommandResult with exit_code, stdout, stderr, duration_seconds.
        """
        client = self._get_client()
        start = time.monotonic()

        def _exec() -> tuple[int, bytes, bytes]:
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
                asyncio.get_running_loop().run_in_executor(None, _exec),
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
        """Stop and remove the container, then clean up the host-side worktree.

        Worktree cleanup runs after container removal so the container cannot be
        restarted while the worktree is being torn down.

        Args:
            handle: Active environment handle to clean up.
        """
        if not handle.container_id:
            return

        client = self._get_client()

        def _stop_remove() -> None:
            try:
                container = client.containers.get(handle.container_id)
                container.stop(timeout=10)
                container.remove(force=True)
            except Exception:
                logger.debug(
                    "Container already removed or not found",
                    extra={"container_id": handle.container_id},
                )

        await asyncio.get_running_loop().run_in_executor(None, _stop_remove)
        logger.info(
            "Container stopped and removed",
            extra={"container_id": handle.container_id},
        )

        # Remove the host-side worktree AFTER the container is gone.
        if handle.host_working_dir and handle.host_working_dir.exists():
            await self._remove_host_worktree(handle.host_working_dir)

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    async def _create_host_worktree(
        self,
        repo_root: Path,
        name: str,
        branch_name: str,
    ) -> Path | None:
        """Create a git worktree on the host for the given mission/name.

        The worktree is placed at ``{repo_root}/var/worktrees/{name}/workspace/``
        and checked out from HEAD so that agent filesystem tools see a populated tree.

        Returns the path to the created worktree, or None if creation fails
        (caller falls back to no isolation — logs a warning).

        Args:
            repo_root: Host path to the git repository root.
            name: Unique name for the worktree (mission_id or test name).
            branch_name: Branch name for the worktree.

        Returns:
            Path to the worktree on the host, or None on failure.
        """
        worktree_path = repo_root / "var" / "worktrees" / name / "workspace"

        # Idempotent — if the path already exists as a worktree (e.g. after a
        # backend restart), skip creation.
        if worktree_path.exists():
            git_file = worktree_path / ".git"
            if git_file.exists():
                logger.info(
                    "Reusing existing host worktree",
                    extra={"worktree_path": str(worktree_path)},
                )
                return worktree_path

        worktree_path.parent.mkdir(parents=True, exist_ok=True)

        def _create_worktree() -> subprocess.CompletedProcess:  # type: ignore[type-arg]
            # Attempt 1: create with a new branch
            result = subprocess.run(
                ["git", "worktree", "add", "-b", branch_name, str(worktree_path)],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return result

            # Attempt 2: branch already exists — attach to it
            result = subprocess.run(
                ["git", "worktree", "add", str(worktree_path), branch_name],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
            )
            return result

        result = await asyncio.get_running_loop().run_in_executor(None, _create_worktree)

        if result.returncode != 0:
            logger.warning(
                "Host worktree creation failed — container will launch without "
                "host-side isolation (host_working_dir will be None)",
                extra={
                    "worktree_path": str(worktree_path),
                    "branch_name": branch_name,
                    "stderr": result.stderr,
                },
            )
            return None

        # Populate the worktree from HEAD so agent tools see a full file tree.
        def _checkout() -> subprocess.CompletedProcess:  # type: ignore[type-arg]
            return subprocess.run(
                ["git", "checkout", "HEAD", "--", "."],
                cwd=str(worktree_path),
                capture_output=True,
                text=True,
            )

        checkout = await asyncio.get_running_loop().run_in_executor(None, _checkout)
        if checkout.returncode != 0:
            logger.warning(
                "Worktree checkout failed — files may not be populated",
                extra={
                    "worktree_path": str(worktree_path),
                    "stderr": checkout.stderr,
                },
            )
            # Non-fatal: the worktree exists but may be empty. Agent can still
            # run commands inside the container; filesystem reads will return
            # "file not found" gracefully.

        logger.info(
            "Host worktree created",
            extra={
                "worktree_path": str(worktree_path),
                "branch_name": branch_name,
            },
        )
        return worktree_path

    async def _remove_host_worktree(self, worktree_path: Path) -> None:
        """Remove the host-side git worktree and its directory.

        Uses ``git worktree remove --force`` which deregisters the worktree
        from the main repo's .git metadata and removes the directory.

        Args:
            worktree_path: Path to the worktree to remove.
        """

        def _remove() -> subprocess.CompletedProcess:  # type: ignore[type-arg]
            return subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree_path)],
                cwd=str(worktree_path.parent.parent.parent),  # repo_root: 3 levels up
                capture_output=True,
                text=True,
            )

        result = await asyncio.get_running_loop().run_in_executor(None, _remove)

        if result.returncode != 0:
            logger.warning(
                "Worktree removal failed — directory may need manual cleanup",
                extra={
                    "worktree_path": str(worktree_path),
                    "stderr": result.stderr,
                },
            )
        else:
            logger.info(
                "Host worktree removed",
                extra={"worktree_path": str(worktree_path)},
            )
