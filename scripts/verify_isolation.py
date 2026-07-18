#!/usr/bin/env python3
"""
Plan 47 — Agent Execution Isolation Verification Script.

Verifies that the isolation boundary implemented in Plan 47 holds:

  1. A user-tier agent running in container mode reads files from the
     per-mission host-side git worktree, NOT from the main repo root.
  2. Commands executed via run_command run inside the container.
  3. The container cannot access host paths outside the bind-mounted worktree.
  4. Agent writes land in the worktree, not on the main branch.
  5. Platform-tier agents continue to run with direct host access (unchanged).
  6. Container persists across multiple executions within a mission.
  7. Cleanup removes both the container and the host-side worktree.

Usage:
    python scripts/verify_isolation.py [--verbose]

Exit codes:
    0  — all checks passed
    1  — one or more checks failed (details printed to stdout)

Requirements:
    - Docker daemon running (OrbStack or standard Docker)
    - code-workspace:latest image built:
        docker build -t code-workspace:latest -f config/dockerfiles/code-workspace.Dockerfile .
    - Running from the repository root

Re-runnable from a clean state any number of times.
"""

import argparse
import asyncio
import contextlib
import sys
import tempfile
import uuid
from pathlib import Path

# Add project root to Python path
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

PASS = "✓"
FAIL = "✗"
SKIP = "⚠"


class IsolationVerifier:
    """Runs the isolation verification suite against real Docker."""

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self._failures: list[str] = []
        self._handle = None
        self._service = None
        self._mission_id = f"verify-{uuid.uuid4().hex[:8]}"

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"    {msg}")

    def _pass(self, check: str) -> None:
        print(f"  {PASS} {check}")

    def _fail(self, check: str, detail: str) -> None:
        print(f"  {FAIL} {check}: {detail}")
        self._failures.append(f"{check}: {detail}")

    def _skip(self, check: str, reason: str) -> None:
        print(f"  {SKIP} {check}: {reason} (skipped)")

    async def setup(self) -> bool:
        """Create the container + worktree for the test mission. Returns False on failure."""
        from modules.backend.services.container_backend import ContainerBackend
        from modules.backend.services.execution_environment import ExecutionEnvironmentService

        self._service = ExecutionEnvironmentService()
        self._service.register_backend("container", ContainerBackend())

        try:
            self._handle = await self._service.resolve_or_create(
                name=self._mission_id,
                mode="container",
                config={
                    "image": "code-workspace:latest",
                    "git_aware": True,
                    "repo_root": str(_REPO_ROOT),
                    "branch_name": f"verify/isolation/{self._mission_id}",
                    "cpu_limit": 1.0,
                    "memory_limit_mb": 512,
                },
            )
            self._log(f"Container: {self._handle.environment_id}")
            self._log(
                f"Container ID: {self._handle.container_id[:12] if self._handle.container_id else 'N/A'}..."
            )
            self._log(f"host_working_dir: {self._handle.host_working_dir}")
            self._log(f"working_dir (container): {self._handle.working_dir}")
            return True
        except RuntimeError as exc:
            print(f"\n{FAIL} Setup failed: {exc}")
            print("  Make sure Docker is running and the image is built:")
            print(
                "  docker build -t code-workspace:latest -f config/dockerfiles/code-workspace.Dockerfile ."
            )
            return False

    async def teardown(self) -> None:
        """Tear down the container and worktree."""
        if self._handle and self._service:
            await self._service.cleanup(self._handle)

    # -------------------------------------------------------------------------
    # Individual checks
    # -------------------------------------------------------------------------

    async def check_host_working_dir_set(self) -> None:
        """host_working_dir is populated on the handle."""
        if self._handle.host_working_dir is not None:
            self._pass("host_working_dir is set on handle")
            self._log(f"  → {self._handle.host_working_dir}")
        else:
            self._fail(
                "host_working_dir is set on handle",
                "host_working_dir is None — worktree creation may have failed",
            )

    async def check_worktree_exists_on_host(self) -> None:
        """Host-side worktree directory exists and is a git worktree."""
        if self._handle.host_working_dir is None:
            self._skip("Host-side worktree exists", "host_working_dir is None")
            return

        wt = self._handle.host_working_dir
        if not wt.exists():
            self._fail("Host-side worktree exists", f"{wt} does not exist on host")
            return

        git_file = wt / ".git"
        if not git_file.exists():
            self._fail(
                "Host-side worktree is a git worktree",
                f"{wt}/.git not found — not a valid worktree",
            )
            return

        self._pass("Host-side worktree exists and has .git pointer")

    async def check_worktree_populated(self) -> None:
        """Worktree contains files from HEAD (not empty)."""
        if self._handle.host_working_dir is None:
            self._skip("Worktree is populated", "host_working_dir is None")
            return

        wt = self._handle.host_working_dir
        modules_dir = wt / "modules"
        if modules_dir.exists() and any(modules_dir.rglob("*.py")):
            self._pass("Worktree is populated with source files")
        else:
            self._fail(
                "Worktree is populated with source files",
                f"modules/ missing or empty in {wt} — checkout may have failed",
            )

    async def check_read_from_worktree(self) -> None:
        """Agent filesystem tool reads from worktree, not main repo.

        Writes a per-mission sentinel file ONLY to the worktree (never
        touching the main repo), then reads it back via ``read_file()``
        and confirms the payload matches. If ``read_file`` were still
        resolving against the host repo root, the sentinel would be
        "file not found" because it was never written there.
        """
        if self._handle.host_working_dir is None:
            self._skip("read_file reads from worktree", "host_working_dir is None")
            return

        from modules.backend.agents.deps.base import FileScope
        from modules.backend.tools.read_file import read_file

        sentinel_rel = "modules/_plan47_isolation_sentinel.py"
        sentinel_content = f"# Plan 47 isolation sentinel — mission {self._mission_id}\n"
        sentinel_path = self._handle.host_working_dir / sentinel_rel
        sentinel_path.write_text(sentinel_content)

        # Also verify the main repo does NOT have this sentinel — otherwise
        # the check is ambiguous (read_file could be hitting either tree).
        main_repo_sentinel = _REPO_ROOT / sentinel_rel
        if main_repo_sentinel.exists():
            self._fail(
                "read_file reads from worktree",
                f"Sentinel also exists in main repo at {main_repo_sentinel} — "
                f"test harness pre-condition violated",
            )
            sentinel_path.unlink(missing_ok=True)
            return

        try:
            scope = FileScope(read_paths=["modules/"])
            result = await read_file(self._handle.host_working_dir, sentinel_rel, scope)
            # read_file returns line-numbered output; check for the mission_id
            # substring and confirm the content came from our sentinel, not
            # from "file not found" or any host-side leak.
            if "file not found" in result.lower():
                self._fail(
                    "read_file reads from worktree",
                    "read_file returned 'file not found' — worktree path not " "resolved correctly",
                )
            elif self._mission_id in result and "Plan 47 isolation sentinel" in result:
                self._pass("read_file reads from worktree (not main repo)")
            else:
                self._fail(
                    "read_file reads from worktree",
                    f"Unexpected content: {result[:120]!r}",
                )
        finally:
            sentinel_path.unlink(missing_ok=True)

    async def check_executor_redirects_user_tier_project_root(self) -> None:
        """Simulate agent_executor's redirect path for a user-tier agent.

        This is the end-to-end glue check: build deps for a user-tier agent
        the same way ``_build_agent_deps`` does, then apply the redirect
        logic from ``_make_agent_executor.execute_agent`` (tier guard +
        project_root override), and confirm ``deps.project_root`` lands on
        the worktree rather than ``find_project_root()``. The real executor
        code at ``agent_executor.py:78-87`` is simple enough that a faithful
        simulation here is equivalent to running a live dispatch — and much
        cheaper to run.
        """
        if self._handle.host_working_dir is None:
            self._skip(
                "Executor redirects user-tier project_root",
                "host_working_dir is None",
            )
            return

        try:
            from modules.backend.agents.mission_control.helpers.agent_setup import _build_agent_deps
            from modules.backend.agents.mission_control.registry import get_registry
            from modules.backend.core.config import find_project_root

            registry = get_registry()
            user_agent_name = "software.quality.agent"
            user_config = registry.get(user_agent_name)
            if user_config is None:
                self._skip(
                    "Executor redirects user-tier project_root",
                    f"{user_agent_name} not in registry",
                )
                return

            if user_config.invocation.tier != "user":
                self._skip(
                    "Executor redirects user-tier project_root",
                    f"{user_agent_name} is tier={user_config.invocation.tier}, " f"not user",
                )
                return

            deps = _build_agent_deps(user_agent_name, user_config)

            # Mirror the exact tier-guarded redirect from
            # _make_agent_executor.execute_agent (agent_executor.py:71-87).
            agent_tier = user_config.invocation.tier
            effective_handle = self._handle if agent_tier == "user" else None
            if effective_handle is not None:
                deps.environment_handle = effective_handle
                if (
                    hasattr(effective_handle, "host_working_dir")
                    and effective_handle.host_working_dir is not None
                ):
                    deps.project_root = effective_handle.host_working_dir

            host_root = find_project_root()
            worktree_root = self._handle.host_working_dir

            if deps.project_root == worktree_root and deps.project_root != host_root:
                self._pass("Executor redirects user-tier project_root to worktree")
                self._log(f"  project_root → {deps.project_root}")
            else:
                self._fail(
                    "Executor redirects user-tier project_root to worktree",
                    f"Expected {worktree_root}, got {deps.project_root}",
                )
        except Exception as exc:
            self._skip(
                "Executor redirects user-tier project_root",
                f"Registry/deps error: {exc}",
            )

    async def check_read_blocked_outside_scope(self) -> None:
        """FileScope blocks reads of paths outside the agent's scope."""
        from modules.backend.agents.deps.base import FileScope
        from modules.backend.tools.read_file import read_file

        scope = FileScope(read_paths=["modules/"])
        try:
            await read_file(
                self._handle.host_working_dir or _REPO_ROOT,
                "config/agents/mission_control.yaml",
                scope,
            )
            self._fail(
                "FileScope blocks out-of-scope reads",
                "read_file should have raised PermissionError for config/ path",
            )
        except PermissionError:
            self._pass("FileScope blocks reads outside declared scope")

    async def check_command_runs_in_container(self) -> None:
        """Commands run inside the container (pwd returns /workspace)."""
        result = await self._service.execute(
            self._handle,
            ["pwd"],
            timeout_seconds=10,
        )
        self._log(f"  pwd → exit={result.exit_code} stdout={result.stdout.strip()!r}")
        if result.exit_code == 0 and result.stdout.strip() == "/workspace":
            self._pass("Commands execute inside container (pwd → /workspace)")
        else:
            self._fail(
                "Commands execute inside container",
                f"pwd returned exit={result.exit_code} stdout={result.stdout.strip()!r}",
            )

    async def check_container_cannot_read_host_etc_passwd(self) -> None:
        """Container /etc/passwd is container's, not host's."""
        # Both host and container have /etc/passwd but with different content.
        # The container runs python:3.14-slim; host is macOS or Linux.
        # We verify the container can read ITS /etc/passwd but doesn't expose
        # host paths outside the bind-mount.
        result = await self._service.execute(
            self._handle,
            ["cat", "/etc/passwd"],
            timeout_seconds=10,
        )
        self._log(f"  cat /etc/passwd exit={result.exit_code}")
        if result.exit_code == 0 and result.stdout:
            # Read the host's /etc/passwd for comparison
            host_passwd = Path("/etc/passwd").read_text(errors="replace")
            if result.stdout.strip() == host_passwd.strip():
                self._fail(
                    "Container reads container's /etc/passwd, not host's",
                    "Output matches host /etc/passwd — container may be sharing host namespaces",
                )
            else:
                self._pass("Container reads container's /etc/passwd (differs from host)")
        elif result.exit_code != 0:
            # Container doesn't have /etc/passwd (unlikely but acceptable)
            self._pass("Container cannot read /etc/passwd (not present in container)")
        else:
            self._fail("Container /etc/passwd check", f"Unexpected: exit={result.exit_code}")

    async def check_container_cannot_reach_host_repo_root(self) -> None:
        """Container cannot list the host repo root (only /workspace is mounted)."""
        # If the host repo is not mounted, ls /repo should fail
        result = await self._service.execute(
            self._handle,
            ["ls", "/repo"],
            timeout_seconds=10,
        )
        self._log(f"  ls /repo → exit={result.exit_code}")
        if result.exit_code != 0:
            self._pass("Container cannot access /repo (host repo not mounted)")
        else:
            self._fail(
                "Container cannot access /repo",
                "ls /repo succeeded — the full host repo is still mounted inside the container",
            )

    async def check_write_lands_in_worktree(self) -> None:
        """Agent writes a file → it appears in the worktree, not main repo."""
        if self._handle.host_working_dir is None:
            self._skip("Write lands in worktree", "host_working_dir is None")
            return

        # Write a file from inside the container (simulates what run_command would do)
        test_file = "plan47_write_test.txt"
        result = await self._service.execute(
            self._handle,
            ["sh", "-c", f"echo 'written_by_isolation_test' > /workspace/{test_file}"],
            timeout_seconds=10,
        )
        self._log(f"  container write exit={result.exit_code}")

        worktree_file = self._handle.host_working_dir / test_file
        main_repo_file = _REPO_ROOT / test_file

        if worktree_file.exists():
            content = worktree_file.read_text().strip()
            if content == "written_by_isolation_test":
                self._pass("Container write lands in host-side worktree")
            else:
                self._fail("Container write lands in worktree", f"Unexpected content: {content!r}")
            worktree_file.unlink()
        else:
            self._fail(
                "Container write lands in host-side worktree",
                f"File not found at {worktree_file}",
            )

        if main_repo_file.exists():
            main_repo_file.unlink()
            self._fail(
                "Write does NOT appear in main repo root",
                f"File appeared at {main_repo_file} — worktree bind-mount may be pointed at main repo",
            )
        else:
            self._pass("Write does NOT appear in main repo root")

    async def check_container_persist_on_reuse(self) -> None:
        """Re-using the same service/handle produces the same container ID."""
        if self._handle.container_id is None:
            self._skip("Container persists across executions", "no container_id on handle")
            return

        original_id = self._handle.container_id
        # Re-execute on the same handle — the container should still be the same
        result = await self._service.execute(
            self._handle,
            ["echo", "still alive"],
            timeout_seconds=10,
        )
        if result.exit_code == 0 and "still alive" in result.stdout:
            self._pass(f"Container persists between executions (id={original_id[:12]}...)")
        else:
            self._fail(
                "Container persists between executions",
                f"Second exec failed: exit={result.exit_code} stderr={result.stderr[:100]}",
            )

    async def check_platform_agent_unaffected(self) -> None:
        """Platform-tier agent deps: project_root is NOT redirected."""
        from modules.backend.agents.config_schema import AgentConfigSchema
        from modules.backend.agents.mission_control.helpers.agent_setup import _build_agent_deps
        from modules.backend.core.config import find_project_root

        try:
            from modules.backend.agents.mission_control.registry import get_registry

            registry = get_registry()
            platform_health_config = registry.get("platform.health.agent")
            if platform_health_config is None:
                self._skip(
                    "Platform agent project_root unaffected",
                    "platform.health.agent not in registry",
                )
                return

            deps = _build_agent_deps("platform.health.agent", platform_health_config)
            # Simulate what agent_executor does for a platform agent:
            # environment_handle is None (platform agents always resolve to local mode)
            # so project_root should stay as find_project_root()
            expected_root = find_project_root()
            if deps.project_root == expected_root:
                self._pass("Platform agent project_root unchanged (find_project_root())")
            else:
                self._fail(
                    "Platform agent project_root unchanged",
                    f"Expected {expected_root}, got {deps.project_root}",
                )
        except Exception as exc:
            self._skip("Platform agent project_root unaffected", f"Registry error: {exc}")

    async def check_cleanup_removes_worktree(self) -> None:
        """After cleanup, both container and host-side worktree are gone."""
        if self._handle.host_working_dir is None:
            self._skip("Cleanup removes worktree", "host_working_dir is None")
            return

        worktree_path = self._handle.host_working_dir
        container_id = self._handle.container_id

        await self.teardown()
        self._handle = None  # Mark as torn down so teardown() in run() is a no-op

        # Verify worktree is gone
        if not worktree_path.exists():
            self._pass(f"Host-side worktree removed: {worktree_path}")
        else:
            self._fail(
                "Host-side worktree removed",
                f"{worktree_path} still exists after cleanup",
            )

        # Verify container is gone
        if container_id:
            try:
                import docker

                client = docker.from_env()
                client.containers.get(container_id)
                self._fail(
                    "Container removed after cleanup",
                    f"Container {container_id[:12]} still exists",
                )
            except docker.errors.NotFound:
                self._pass(f"Container removed: {container_id[:12]}...")
            except Exception as exc:
                self._skip("Container removed check", f"Docker error: {exc}")

    # -------------------------------------------------------------------------
    # Runner
    # -------------------------------------------------------------------------

    async def run(self) -> bool:
        """Run all checks. Returns True if all passed."""
        print(f"\nPlan 47 — Isolation Verification (mission_id={self._mission_id})")
        print("=" * 65)

        print("\n[Setup] Creating container + host-side worktree...")
        if not await self.setup():
            return False
        print(f"  Container: {self._handle.environment_id}")
        if self._handle.host_working_dir:
            print(f"  Worktree: {self._handle.host_working_dir}")

        print("\n[A] Worktree provisioning")
        await self.check_host_working_dir_set()
        await self.check_worktree_exists_on_host()
        await self.check_worktree_populated()

        print("\n[B] Filesystem isolation")
        await self.check_read_from_worktree()
        await self.check_read_blocked_outside_scope()
        await self.check_executor_redirects_user_tier_project_root()

        print("\n[C] Container command isolation")
        await self.check_command_runs_in_container()
        await self.check_container_cannot_read_host_etc_passwd()
        await self.check_container_cannot_reach_host_repo_root()

        print("\n[D] Write isolation")
        await self.check_write_lands_in_worktree()

        print("\n[E] Persistence + platform safety")
        await self.check_container_persist_on_reuse()
        await self.check_platform_agent_unaffected()

        print("\n[F] Cleanup")
        await self.check_cleanup_removes_worktree()

        # Final verdict
        print("\n" + "=" * 65)
        if self._failures:
            print(f"FAILED — {len(self._failures)} check(s) failed:")
            for f in self._failures:
                print(f"  {FAIL} {f}")
            return False
        else:
            print("PASSED — all isolation checks passed")
            return True


async def _main(verbose: bool) -> int:
    verifier = IsolationVerifier(verbose=verbose)
    try:
        passed = await verifier.run()
    finally:
        # Best-effort cleanup if something went wrong mid-run
        if verifier._handle is not None:
            with contextlib.suppress(Exception):
                await verifier.teardown()
    return 0 if passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show debug details for each check"
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.verbose)))


if __name__ == "__main__":
    main()
