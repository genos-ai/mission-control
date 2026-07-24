#!/usr/bin/env python3
"""
Test running a real agent execution inside a container.

Creates an ad-hoc execution, forces execution_mode=container,
and runs the health check agent inside Docker.

Usage:
    python scripts/test_container_execution.py
"""

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))


async def main() -> None:
    print("=" * 60)
    print("Container Execution Integration Test")
    print("=" * 60)

    from redis.asyncio import Redis as AsyncRedis

    from modules.backend.agents.mission_control.dispatch_adapter import (
        MissionControlDispatchAdapter,
    )
    from modules.backend.core.config import get_redis_url
    from modules.backend.events.bus import SessionEventBus
    from modules.backend.services.session import SessionService

    redis = AsyncRedis.from_url(get_redis_url())
    event_bus = SessionEventBus(redis)

    # Find the platform-test mission

    from modules.backend.core.database import get_async_session
    from modules.backend.repositories.mission import MissionRepository

    async with get_async_session() as db:
        repo = MissionRepository(db)
        missions = await repo.list_active()
        mission = next((m for m in missions if "platform" in m.name), None)

        if not mission:
            print("\nNo platform mission found. Create one first:")
            print(
                "  python admin.py mission create --name platform-test --description 'Test' --tier platform --repo-root ."  # noqa: E501
            )
            sys.exit(1)

        print(f"\nMission: {mission.name} ({mission.id})")
        print(f"Tier: {mission.tier}")

        # Create execution service with dispatch adapter
        session_service = SessionService(db)
        adapter = MissionControlDispatchAdapter(
            session_service=session_service,
            db_session=db,
            event_bus=event_bus,
        )

        print("\n--- Dispatching with execution_mode=container ---\n")

        # Call the adapter directly with forced container mode
        result = await adapter.execute(
            mission_brief="Run a quick platform health check. Check service connectivity only.",
            roster_ref="default",
            complexity_tier="simple",
            cost_ceiling_usd=0.50,
            session_id=str(uuid4()),
            mission_id=str(mission.id),
            execution_mode="container",
        )

        print("\n--- Result ---")
        print(f"Success: {result.get('success')}")
        print(f"Status: {result.get('status')}")
        print(f"Cost: ${result.get('total_cost_usd', 0):.4f}")
        print(f"Tasks: {len(result.get('task_results', []))}")
        print(f"Summary: {result.get('summary', 'N/A')}")

        if result.get("task_results"):
            for tr in result["task_results"]:
                print(f"\n  Task: {tr.get('task_id')} ({tr.get('agent_name')})")
                print(f"  Status: {tr.get('status')}")
                print(f"  Summary: {tr.get('summary', '')[:200]}")

    await redis.aclose()
    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
