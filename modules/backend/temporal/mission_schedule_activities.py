"""MissionScheduleTickWorkflow activities (Plan 88 step 88.1.8, contract 3.3.5).

claim_occurrence records one scheduled occurrence in Postgres. schedule_service is
shared with sync_mission_schedules in reconciler_activities.py (moved there by 88.1.10)
and with the worker's startup sync.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from temporalio import activity

from modules.backend.core.logging import get_logger
from modules.backend.temporal.mission_run_models import (
    ClaimOccurrenceInput,
    ClaimOccurrenceResult,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from modules.backend.services.mission_schedule import MissionScheduleService

logger = get_logger(__name__)


@asynccontextmanager
async def schedule_service() -> AsyncIterator[tuple["MissionScheduleService", "AsyncSession"]]:
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
    """Claim the occurrence and commit.

    Then delete the Temporal schedule if it completed, or pause the mission's
    Temporal schedules if a breached budget cap paused the mission (88.4.6).
    """
    from modules.backend.models.mission_schedule import MissionScheduleStatus

    async with schedule_service() as (svc, db):
        claim = await svc.claim_occurrence(input.mission_schedule_id, input.scheduled_for)
        await db.commit()
        run = claim.run
        if claim.mission_paused and run is not None:
            await svc.sync_mission(run.mission_id)
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
