"""
Branch Manager.

Git branch lifecycle management for agent-generated code. Handles
branch naming conventions, cleanup of stale branches, and PR automation.

Branch convention: agent/{mission-id-short}/{task-slug}
Examples:
    agent/m-abc123/qa-cycle
    agent/m-def456/refactor-auth

All git operations use asyncio.create_subprocess_exec to avoid
blocking the event loop.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

# Max length for the task slug portion of the branch name
_MAX_SLUG_LEN = 40


def make_branch_name(mission_id: str, task_description: str) -> str:
    """Generate a branch name following the agent convention.

    Format: agent/{mission-id-short}/{task-slug}

    Args:
        mission_id: Full or short mission UUID
        task_description: Human-readable task description (slugified)

    Returns:
        Branch name like 'agent/m-abc123/refactor-auth'
    """
    # Short mission id: first 8 chars
    short_id = f"m-{mission_id[:8]}" if len(mission_id) > 8 else mission_id

    # Slugify task description
    slug = re.sub(r"[^a-z0-9]+", "-", task_description.lower()).strip("-")
    slug = slug[:_MAX_SLUG_LEN].rstrip("-")
    if not slug:
        slug = "task"

    return f"agent/{short_id}/{slug}"


def make_commit_message(
    agent_name: str,
    description: str,
    *,
    mission_id: str | None = None,
    task_id: str | None = None,
    cycle_number: int | None = None,
) -> str:
    """Format an agent commit message.

    Format:
        [AGENT:{agent-name}] Short description

        Mission: {mission-id}
        Task: {task-id}
        Cycle: {cycle-number}
        Agent: {agent-name}
    """
    subject = f"[AGENT:{agent_name}] {description[:72]}"
    lines = [subject, ""]

    if mission_id:
        lines.append(f"Mission: {mission_id}")
    if task_id:
        lines.append(f"Task: {task_id}")
    if cycle_number is not None:
        lines.append(f"Cycle: {cycle_number}")
    lines.append(f"Agent: {agent_name}")

    return "\n".join(lines)


async def create_branch(
    repo_root: Path,
    branch_name: str,
    base_branch: str = "main",
) -> bool:
    """Create a new branch from base_branch.

    Returns True if created, False if branch already exists.
    """
    # Check if branch already exists
    proc = await asyncio.create_subprocess_exec(
        "git", "rev-parse", "--verify", f"refs/heads/{branch_name}",
        cwd=str(repo_root),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    if proc.returncode == 0:
        logger.debug("Branch already exists", extra={"branch": branch_name})
        return False

    proc = await asyncio.create_subprocess_exec(
        "git", "branch", branch_name, base_branch,
        cwd=str(repo_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.error(
            "Failed to create branch",
            extra={"branch": branch_name, "stderr": stderr.decode()},
        )
        return False

    logger.info("Branch created", extra={"branch": branch_name, "base": base_branch})
    return True


async def push_branch(
    repo_root: Path,
    branch_name: str,
    remote: str = "origin",
) -> bool:
    """Push a branch to the remote. Returns True on success."""
    proc = await asyncio.create_subprocess_exec(
        "git", "push", "-u", remote, branch_name,
        cwd=str(repo_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.error(
            "Failed to push branch",
            extra={"branch": branch_name, "stderr": stderr.decode()},
        )
        return False

    logger.info("Branch pushed", extra={"branch": branch_name, "remote": remote})
    return True


async def delete_branch(
    repo_root: Path,
    branch_name: str,
    *,
    remote: bool = False,
    force: bool = False,
) -> bool:
    """Delete a local (and optionally remote) branch."""
    flag = "-D" if force else "-d"
    proc = await asyncio.create_subprocess_exec(
        "git", "branch", flag, branch_name,
        cwd=str(repo_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()

    if remote:
        proc = await asyncio.create_subprocess_exec(
            "git", "push", "origin", "--delete", branch_name,
            cwd=str(repo_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    logger.info("Branch deleted", extra={"branch": branch_name, "remote": remote})
    return True


async def list_agent_branches(repo_root: Path) -> list[str]:
    """List all branches matching the agent/ prefix."""
    proc = await asyncio.create_subprocess_exec(
        "git", "branch", "--list", "agent/*",
        cwd=str(repo_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    branches = [
        line.strip().lstrip("* ")
        for line in stdout.decode().splitlines()
        if line.strip()
    ]
    return branches


async def cleanup_merged_branches(
    repo_root: Path,
    base_branch: str = "main",
) -> list[str]:
    """Delete agent branches that have been merged into base_branch."""
    proc = await asyncio.create_subprocess_exec(
        "git", "branch", "--merged", base_branch, "--list", "agent/*",
        cwd=str(repo_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()

    merged = [
        line.strip().lstrip("* ")
        for line in stdout.decode().splitlines()
        if line.strip() and "agent/" in line
    ]

    for branch in merged:
        await delete_branch(repo_root, branch)

    if merged:
        logger.info("Cleaned up merged agent branches", extra={"count": len(merged), "branches": merged})

    return merged


async def create_pull_request(
    repo_root: Path,
    branch_name: str,
    *,
    title: str,
    body: str,
    base_branch: str = "main",
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Create a pull request using the gh CLI.

    Returns dict with PR URL and number on success, error on failure.
    Requires gh CLI to be installed and authenticated.
    """
    cmd = [
        "gh", "pr", "create",
        "--title", title,
        "--body", body,
        "--base", base_branch,
        "--head", branch_name,
    ]
    if labels:
        for label in labels:
            cmd.extend(["--label", label])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(repo_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode().strip()
        logger.error("Failed to create PR", extra={"error": error_msg})
        return {"success": False, "error": error_msg}

    pr_url = stdout.decode().strip()
    logger.info("PR created", extra={"url": pr_url, "branch": branch_name})
    return {"success": True, "url": pr_url}
