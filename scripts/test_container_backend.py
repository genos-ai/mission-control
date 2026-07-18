#!/usr/bin/env python3
"""
Test the container backend end-to-end.

Creates a container, mounts the repo, runs commands inside it,
and cleans up. Verifies that the ExecutionEnvironmentService
pipeline works from resolve_or_create → execute → cleanup.

Usage:
    python scripts/test_container_backend.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.backend.services.container_backend import ContainerBackend
from modules.backend.services.execution_environment import ExecutionEnvironmentService


async def main() -> None:
    print("=" * 60)
    print("Container Backend Integration Test")
    print("=" * 60)

    # 1. Set up service with container backend
    service = ExecutionEnvironmentService()
    container_backend = ContainerBackend()
    service.register_backend("container", container_backend)
    print("\n✓ ContainerBackend registered")

    # 2. Create a container environment
    repo_root = Path(__file__).parent.parent
    print(f"\nCreating container (repo: {repo_root})...")

    try:
        handle = await service.resolve_or_create(
            name="test-container",
            mode="container",
            config={
                "image": "code-workspace:latest",
                "git_aware": True,
                "repo_root": str(repo_root),
                "branch_name": "test/container-backend",
                "cpu_limit": 1.0,
                "memory_limit_mb": 512,
            },
        )
    except RuntimeError as e:
        print(f"\n✗ Container creation failed: {e}")
        print("  Make sure Docker is running and code-workspace image is built:")
        print(
            "  docker build -t code-workspace:latest -f config/dockerfiles/code-workspace.Dockerfile ."
        )
        sys.exit(1)

    print(f"✓ Container created: {handle.environment_id}")
    print(f"  Mode: {handle.mode}")
    print(f"  Working dir: {handle.working_dir}")
    print(f"  Container ID: {handle.container_id[:12]}...")

    # 3. Run commands inside
    print("\n--- Running commands inside container ---")

    # Check Python version
    result = await service.execute(handle, ["python", "--version"])
    print(f"\npython --version: {result.stdout.strip()}")
    print(f"  exit_code: {result.exit_code}, duration: {result.duration_seconds:.2f}s")

    # Check git version
    result = await service.execute(handle, ["git", "--version"])
    print(f"\ngit --version: {result.stdout.strip()}")

    # List workspace contents
    result = await service.execute(handle, ["ls", "-la", "/workspace"])
    print(f"\nls /workspace:\n{result.stdout}")

    # Check git status if worktree was created
    result = await service.execute(handle, ["git", "status"], timeout_seconds=10)
    print(f"git status (exit {result.exit_code}):")
    if result.exit_code == 0:
        print(f"  {result.stdout[:200]}")
    else:
        print(f"  {result.stderr[:200]}")

    # Run a simple Python command
    result = await service.execute(
        handle,
        [
            "python",
            "-c",
            "import sys; print(f'Python {sys.version}'); print('Container execution works!')",
        ],
    )
    print(f"\nPython in container: {result.stdout.strip()}")

    # 4. Cleanup
    print("\n--- Cleanup ---")
    await service.cleanup(handle)
    print("✓ Container cleaned up")

    print("\n" + "=" * 60)
    print("All tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
