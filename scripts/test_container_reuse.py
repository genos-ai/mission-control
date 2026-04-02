#!/usr/bin/env python3
"""
Test that containers persist across executions within a mission.

Runs two executions on the same mission with execution_mode=container.
The second execution should reuse the container from the first.

Usage:
    python scripts/test_container_reuse.py
"""

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))


async def main() -> None:
    print("=" * 60)
    print("Container Reuse Test")
    print("=" * 60)

    from modules.backend.services.execution_environment import (
        ExecutionEnvironmentService,
    )
    from modules.backend.services.container_backend import ContainerBackend
    from modules.backend.core.config import find_project_root
    from modules.backend.core.database import get_async_session

    async with get_async_session() as db:
        # Find a mission
        from modules.backend.repositories.mission import MissionRepository
        repo = MissionRepository(db)
        missions = await repo.list_active()
        mission = next((m for m in missions if "platform" in m.name), None)

        if not mission:
            print("No platform mission found. Create one first.")
            sys.exit(1)

        mission_id = str(mission.id)
        print(f"Mission: {mission.name} ({mission_id})")

        # Set up service
        svc = ExecutionEnvironmentService(db_session=db)
        svc.register_backend("container", ContainerBackend())

        repo_root = str(find_project_root())
        config = {
            "image": "code-workspace:latest",
            "git_aware": True,
            "repo_root": repo_root,
            "branch_name": f"agent/{mission_id[:8]}/reuse-test",
        }

        # First execution — should CREATE container
        print("\n--- Execution 1: should CREATE container ---")
        handle1 = await svc.get_or_create_for_mission(
            mission_id=mission_id,
            mode="container",
            config=config,
        )
        print(f"  Environment: {handle1.environment_id}")
        print(f"  Container: {handle1.container_id[:12] if handle1.container_id else 'N/A'}")
        print(f"  Execution count: {handle1.metadata.get('execution_count', 'N/A')}")

        # Run a command to prove it works
        result = await svc.execute(handle1, ["python", "--version"])
        print(f"  Python: {result.stdout.strip()}")

        await db.commit()

        # Second execution — should REUSE container
        print("\n--- Execution 2: should REUSE container ---")
        handle2 = await svc.get_or_create_for_mission(
            mission_id=mission_id,
            mode="container",
            config=config,
        )
        print(f"  Environment: {handle2.environment_id}")
        print(f"  Container: {handle2.container_id[:12] if handle2.container_id else 'N/A'}")
        print(f"  Execution count: {handle2.metadata.get('execution_count', 'N/A')}")

        # Verify same container
        same = handle1.container_id == handle2.container_id
        print(f"\n  Same container? {'YES' if same else 'NO'}")

        if same:
            print("  Container was REUSED across executions")
        else:
            print("  WARNING: Container was NOT reused — new one created")

        # Run another command
        result = await svc.execute(handle2, ["echo", "Container reuse works!"])
        print(f"  Output: {result.stdout.strip()}")

        # Check DB records
        from sqlalchemy import text
        r = await db.execute(
            text("SELECT id, status, execution_count, last_execution_at FROM execution_environments WHERE mission_id = :mid"),
            {"mid": mission_id},
        )
        rows = r.all()
        print(f"\n--- DB records for this mission: {len(rows)} ---")
        for row in rows:
            print(f"  {row[0][:8]}... status={row[1]} exec_count={row[2]} last={row[3]}")

        # Cleanup
        print("\n--- Cleanup ---")
        await svc.cleanup(handle2)
        await db.commit()
        print("  Container destroyed")

    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
