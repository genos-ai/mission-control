"""Reconciler activities (Plan 88 steps 88.0.10 and 88.1.10, contract 3.3.5)."""

from temporalio import activity

from modules.backend.core.logging import get_logger
from modules.backend.temporal.mission_run_models import (
    ReconcileInput,
    ReconcileStats,
    ScheduleSyncStats,
)
from modules.backend.temporal.mission_schedule_activities import schedule_service

logger = get_logger(__name__)


@activity.defn
async def reconcile_mission_runs(input: ReconcileInput) -> ReconcileStats:
    """Fail in-flight rows whose Temporal workflow is gone (RunReconciliationService).

    Raises ExternalServiceError when Temporal is unreachable, after writing
    nothing; the retry policy decides.
    """
    from redis.asyncio import Redis as AsyncRedis

    from modules.backend.core.config import get_redis_url
    from modules.backend.core.database import get_async_session
    from modules.backend.events.bus import SessionEventBus
    from modules.backend.services.run_reconciliation import RunReconciliationService
    from modules.backend.temporal.workflow_gateway import TemporalWorkflowGateway

    gateway = await TemporalWorkflowGateway.connect()
    redis = AsyncRedis.from_url(get_redis_url())
    try:
        event_bus = SessionEventBus(redis)
        async with get_async_session() as db:
            stats = await RunReconciliationService(db, gateway, event_bus).reconcile(
                input.orphan_grace_seconds
            )
            await db.commit()
        return stats
    finally:
        await redis.aclose()


@activity.defn
async def sync_mission_schedules(mission_id: str | None) -> ScheduleSyncStats:
    """Sync one mission's schedules to Temporal, or every schedule when mission_id is None."""
    async with schedule_service() as (svc, _db):
        if mission_id is None:
            return await svc.sync_all()
        return await svc.sync_mission(mission_id)
