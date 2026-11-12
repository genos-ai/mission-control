"""Run-memory activities of MissionRunWorkflow (Plan 88 Phase 3).

``compact_mission_context`` (88.3.3) runs deterministic MCD compaction at run
end. Its policy key is ``persistence``. The ContextCompactedEvent is published
only after the compaction commits.

``write_run_digest`` (88.3.7) writes the run's digest before
``finalise_mission_run``. Its policy key is ``write_digest``. The digest agent
is imported here, not in services/run_memory.py, so the services layer never
imports the agents layer (import-linter contract).
"""

import uuid

from redis.asyncio import Redis as AsyncRedis
from sqlalchemy.exc import SQLAlchemyError
from temporalio import activity

from modules.backend.agents.system.digest.agent import generate_digest_narrative
from modules.backend.core.config import get_app_config, get_redis_url
from modules.backend.core.database import get_async_session
from modules.backend.core.logging import get_logger
from modules.backend.events.bus import SessionEventBus
from modules.backend.events.mission_run_types import ContextCompactedEvent
from modules.backend.events.types import SystemEvent
from modules.backend.models.mission_run import MissionRunStatus, MissionRunStatusReason
from modules.backend.models.mission_run_digest import DigestGenerator
from modules.backend.services.mission_context import MissionContextManager
from modules.backend.services.mission_learning import MissionLearningExtractor
from modules.backend.services.run_memory import RunMemoryService
from modules.backend.temporal.activity_helpers import heartbeat_every
from modules.backend.temporal.mission_run_models import (
    CompactContextInput,
    CompactContextResult,
    DigestResult,
    WriteDigestInput,
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


@activity.defn
async def write_run_digest(input: WriteDigestInput) -> DigestResult:
    """Write the run's digest, then refresh the mission's learnings.

    The digest agent narrates unless ``force_deterministic``. Learning
    extraction runs in its own session after the digest commits; its failure
    is logged and does not fail the digest, because the nightly
    knowledge_extraction schedule repeats it.
    """
    interval = get_app_config().temporal.mission_run.task_heartbeat_interval_seconds
    narrator = None if input.force_deterministic else generate_digest_narrative
    redis = AsyncRedis.from_url(get_redis_url())
    try:
        bus = SessionEventBus(redis, mission_id=None)
        async with heartbeat_every(interval, phase="digest") as hb:
            async with get_async_session() as db:
                digest = await RunMemoryService(db, event_bus=bus).write_digest(
                    input.mission_run_id,
                    status=MissionRunStatus(input.status),
                    reason=(
                        MissionRunStatusReason(input.reason) if input.reason is not None else None
                    ),
                    narrator=narrator,
                )
                mission_id, digest_id = digest.mission_id, digest.id
                generator = DigestGenerator(digest.generator).value

            hb.phase = "learnings"
            try:
                async with get_async_session() as db:
                    await MissionLearningExtractor(db).extract_for_mission(mission_id)
                    await db.commit()
            except SQLAlchemyError:
                # The knowledge_extraction schedule repeats the extraction nightly.
                logger.warning(
                    "learning extraction failed",
                    extra={"mission_id": mission_id},
                    exc_info=True,
                )
                await bus.publish_to_mission(
                    mission_id,
                    SystemEvent(
                        session_id=uuid.UUID(mission_id),
                        source="run_memory",
                        level="warning",
                        message="Learning extraction after the run digest failed; "
                        "the nightly extraction will retry",
                        mission_id=mission_id,
                    ),
                )
    finally:
        await redis.aclose()

    return DigestResult(digest_id=digest_id, generator=generator)
