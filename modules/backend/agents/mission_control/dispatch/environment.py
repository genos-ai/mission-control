"""Execution mode resolution.

Determines whether a task runs in local, worktree, or container mode
based on task characteristics, agent config, and explicit overrides.

Resolution priority:
    1. Explicit mode on the task/workflow step
    2. Agent YAML execution.mode (if not "auto")
    3. Mission-level default (mission.execution_environment)
    4. Auto-resolution based on agent tools
    5. Fallback: "local"
"""

from __future__ import annotations

from typing import Any

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

# Tools that require container execution (runtime isolation)
_CONTAINER_TOOLS: frozenset[str] = frozenset({
    "code.run_tests",
    "code.build",
    "system.install_packages",
    "system.run_migrations",
    "system.exec_command",
})

# Tools that write files (worktree or container)
_WRITE_TOOLS: frozenset[str] = frozenset({
    "filesystem.write_file",
    "code.apply_fix",
    "filesystem.create_file",
    "filesystem.delete_file",
})


def resolve_execution_mode(
    *,
    task_environment: str | None = None,
    agent_config: dict[str, Any] | None = None,
    mission_environment: str | None = None,
    mission_repo_root: str | None = None,
) -> str:
    """Resolve the execution mode for a task.

    Args:
        task_environment: Explicit mode from workflow step or task definition
        agent_config: Agent YAML config dict (has execution.mode, tools, etc.)
        mission_environment: Mission-level default execution environment
        mission_repo_root: Mission's repo_root — needed for worktree/container

    Returns:
        Resolved mode: "local", "worktree", or "container"
    """
    # 1. Explicit task-level override
    if task_environment and task_environment != "auto":
        resolved = _validate_mode(task_environment, mission_repo_root)
        logger.debug("Mode from task definition", extra={"mode": resolved})
        return resolved

    # 2. Agent config mode (if not auto)
    if agent_config:
        agent_mode = agent_config.get("execution", {}).get("mode", "local")
        if agent_mode != "auto":
            resolved = _validate_mode(agent_mode, mission_repo_root)
            logger.debug("Mode from agent config", extra={"mode": resolved})
            return resolved

    # 3. Mission-level default
    if mission_environment and mission_environment != "auto":
        resolved = _validate_mode(mission_environment, mission_repo_root)
        logger.debug("Mode from mission default", extra={"mode": resolved})
        return resolved

    # 4. Auto-resolution based on agent tools
    if agent_config:
        tools = set(agent_config.get("tools", []))
        prefer = agent_config.get("execution", {}).get("prefer", "worktree")

        if tools & _CONTAINER_TOOLS:
            resolved = _validate_mode("container", mission_repo_root)
            logger.debug("Auto-resolved to container (execution tools)", extra={"mode": resolved})
            return resolved

        if tools & _WRITE_TOOLS:
            resolved = _validate_mode(prefer, mission_repo_root)
            logger.debug("Auto-resolved to preferred mode (write tools)", extra={"mode": resolved, "prefer": prefer})
            return resolved

    # 5. Fallback
    return "local"


def _validate_mode(mode: str, repo_root: str | None) -> str:
    """Validate that the resolved mode is feasible.

    If worktree or container is requested but repo_root is missing,
    fall back to local with a warning.
    """
    if mode in ("worktree", "container") and not repo_root:
        logger.warning(
            "Execution mode '%s' requires repo_root but mission has none — falling back to local",
            mode,
            extra={"requested_mode": mode},
        )
        return "local"
    return mode
