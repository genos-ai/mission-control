"""Run-memory activities of MissionRunWorkflow (Plan 88 Phase 3).

``compact_mission_context`` (88.3.3) runs deterministic MCD compaction at run
end. Its policy key is ``persistence``. The ContextCompactedEvent is published
only after the compaction commits.
"""

import uuid

from redis.asyncio import Redis as AsyncRedis
from temporalio import activity

from modules.backend.core.config import get_redis_url
from modules.backend.core.database import get_async_session
from modules.backend.core.logging import get_logger
from modules.backend.events.bus import SessionEventBus
from modules.backend.events.mission_run_types import ContextCompactedEvent
from modules.backend.services.mission_context import MissionContextManager
from modules.backend.temporal.mission_run_models import (
    CompactContextInput,
    CompactContextResult,
)

logger = get_logger(__name__)


@activity.defn
async def compact_mission_context(input: CompactContextInput) -> CompactContextResult:
    """Compact the mission's MCD when it has reached the prune threshold."""
    async with get_async_session() as db:
        result = await MissionContextManager(db).compact(
            input.mission_id,
            mission_run_id=input.mission_run_id,
            reason="run-end compaction",
        )
        await db.commit()

    if result is None:
        return CompactContextResult(compacted=False, from_bytes=0, to_bytes=0)

    redis = AsyncRedis.from_url(get_redis_url())
    try:
        await SessionEventBus(redis, mission_id=input.mission_id).publish(
            ContextCompactedEvent(
                session_id=uuid.UUID(input.mission_id),
                source="compaction",
                mission_id=input.mission_id,
                mission_run_id=input.mission_run_id,
                from_bytes=result.from_bytes,
                to_bytes=result.to_bytes,
                archived_paths=result.archived_paths,
            )
        )
    finally:
        await redis.aclose()

    logger.info(
        "Run-end MCD compaction",
        extra={
            "mission_id": input.mission_id,
            "mission_run_id": input.mission_run_id,
            "from_bytes": result.from_bytes,
            "to_bytes": result.to_bytes,
            "archived_paths": result.archived_paths,
        },
    )
    return CompactContextResult(
        compacted=True, from_bytes=result.from_bytes, to_bytes=result.to_bytes
    )
