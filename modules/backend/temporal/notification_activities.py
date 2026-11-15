"""Mission notification activity (Plan 88 step 88.4.4, contract 3.3.5).

``send_mission_notification`` delivers one NotificationRequest through
NotificationService.notify. Its policy key is ``notify``. A failed recipient
raises ExternalServiceError after the others are attempted; the retry is
idempotent because SENT delivery rows are never sent again. The workflows
start calling it in 88.4.5.
"""

from redis.asyncio import Redis as AsyncRedis
from temporalio import activity

from modules.backend.core.config import get_redis_url
from modules.backend.core.database import get_async_session
from modules.backend.events.bus import SessionEventBus
from modules.backend.services.notification import NotificationService
from modules.backend.temporal.mission_run_models import NotificationRequest


@activity.defn
async def send_mission_notification(request: NotificationRequest) -> list[str]:
    """Deliver one notification to the mission's subscribed recipients; returns delivery ids."""
    redis = AsyncRedis.from_url(get_redis_url())
    try:
        bus = SessionEventBus(redis, mission_id=request.mission_id)
        async with get_async_session() as db:
            deliveries = await NotificationService(db, event_bus=bus).notify(request)
            return [str(d.id) for d in deliveries]
    finally:
        await redis.aclose()
