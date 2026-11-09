"""MissionScheduleTickWorkflow activities (Plan 88 step 88.1.8, contract 3.3.5).

claim_occurrence records one scheduled occurrence in Postgres. sync_mission_schedules
mirrors schedules to Temporal; 88.1.10 moves it into reconciler_activities.py.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from temporalio import activity

from modules.backend.core.logging import get_logger
from modules.backend.temporal.mission_run_models import (
    ClaimOccurrenceInput,
    ClaimOccurrenceResult,
    ScheduleSyncStats,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from modules.backend.services.mission_schedule import MissionScheduleService

logger = get_logger(__name__)


@asynccontextmanager
async def _schedule_service() -> AsyncIterator[tuple["MissionScheduleService", "AsyncSession"]]:
    """A MissionScheduleService on a fresh session, schedule gateway and event bus."""
    from redis.asyncio import Redis as AsyncRedis

    from modules.backend.core.config import get_redis_url
    from modules.backend.core.database import get_async_session
    from modules.backend.events.bus import SessionEventBus
    from modules.backend.services.mission_schedule import MissionScheduleService
    from modules.backend.temporal.schedule_gateway import TemporalScheduleGateway

    gateway = await TemporalScheduleGateway.create()
    redis = AsyncRedis.from_url(get_redis_url())
    try:
        async with get_async_session() as db:
            yield MissionScheduleService(db, gateway, SessionEventBus(redis)), db
    finally:
        await redis.aclose()


@activity.defn
async def claim_occurrence(input: ClaimOccurrenceInput) -> ClaimOccurrenceResult:
    """Claim the occurrence, commit, then delete the Temporal schedule if it completed."""
    from modules.backend.models.mission_schedule import MissionScheduleStatus

    async with _schedule_service() as (svc, db):
        claim = await svc.claim_occurrence(input.mission_schedule_id, input.scheduled_for)
        await db.commit()
        run = claim.run
        if claim.outcome == "run" and run is not None:
            schedule = await svc.get_schedule(run.mission_id, input.mission_schedule_id)
            if schedule.status == MissionScheduleStatus.COMPLETED:
                await svc.sync_to_temporal(input.mission_schedule_id)
        return ClaimOccurrenceResult(
            outcome=claim.outcome,
            mission_run_id=run.id if run is not None else None,
            run_input=claim.run_input,
            notifications=claim.notifications,
        )


@activity.defn
async def sync_mission_schedules(mission_id: str | None) -> ScheduleSyncStats:
    """Sync one mission's schedules to Temporal, or every schedule when mission_id is None."""
    async with _schedule_service() as (svc, _db):
        if mission_id is None:
            return await svc.sync_all()
        return await svc.sync_mission(mission_id)
