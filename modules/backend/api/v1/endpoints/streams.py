"""
SSE Streaming Endpoints.

Server-Sent Event streams for real-time notifications and run monitoring.
"""

import asyncio
import json
import uuid

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis as AsyncRedis

from modules.backend.core.config import get_redis_url
from modules.backend.core.logging import get_logger
from modules.backend.events.bus import SessionEventBus
from modules.backend.services.console import MissionEventAggregator

logger = get_logger(__name__)

router = APIRouter()


# ---- Run event stream ----


@router.get(
    "/runs/{session_id}",
    summary="Stream run events via SSE",
    description=(
        "Subscribe to real-time execution events for a session. "
        "Events include agent thinking, tool calls, responses, cost updates, "
        "and workflow lifecycle events."
    ),
)
async def stream_run_events(
    session_id: str,
) -> StreamingResponse:
    """Stream execution events for a session as SSE."""

    async def generate():
        redis = AsyncRedis.from_url(get_redis_url())
        bus = SessionEventBus(redis)
        try:
            # Send initial connected event (named so onmessage ignores it)
            yield f"event: connected\ndata: {json.dumps({'session_id': session_id})}\n\n"

            async for event in bus.subscribe(uuid.UUID(session_id)):
                yield f"data: {event.model_dump_json()}\n\n"
        except asyncio.CancelledError:
            logger.debug("Run SSE stream cancelled", extra={"session_id": session_id})
        finally:
            await redis.close()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---- Notification stream ----


NOTIFY_CHANNEL_PREFIX = "notify"


@router.get(
    "/notifications",
    summary="Stream user notifications via SSE",
    description=(
        "Subscribe to real-time notifications for the authenticated user. "
        "Events include gate approvals, run completions, failures, and budget warnings."
    ),
)
async def stream_notifications(
    user_id: str = Query(..., description="User ID to receive notifications for"),
) -> StreamingResponse:
    """Stream notifications for a user as SSE."""

    async def generate():
        redis = AsyncRedis.from_url(get_redis_url())
        pubsub = redis.pubsub()
        channel = f"{NOTIFY_CHANNEL_PREFIX}:{user_id}"
        await pubsub.subscribe(channel)
        logger.debug("Subscribed to notification channel", extra={"channel": channel})

        try:
            # Send initial connected event
            yield f"event: connected\ndata: {json.dumps({'user_id': user_id})}\n\n"

            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message is None:
                    # Send keepalive comment every second to detect disconnects
                    yield ": keepalive\n\n"
                    await asyncio.sleep(1)
                    continue

                if message["type"] != "message":
                    continue

                try:
                    data = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    logger.warning("Invalid JSON in notification event")
                    continue

                event_type = data.get("type", "notification")
                yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

        except asyncio.CancelledError:
            logger.debug("Notification SSE stream cancelled", extra={"user_id": user_id})
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
            await redis.close()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---- Mission console stream ----


@router.get(
    "/missions/{mission_id}",
    summary="Stream mission console events via SSE",
    description=(
        "Subscribe to real-time events across all sessions in a mission. "
        "Events are classified into execution, chat, and system categories."
    ),
)
async def stream_mission_events(
    mission_id: str,
    token: str | None = None,
) -> StreamingResponse:
    """Stream aggregated events for a mission as SSE."""

    async def generate():
        from modules.backend.core.database import get_session_factory

        redis = AsyncRedis.from_url(get_redis_url())
        db_session = get_session_factory()()
        aggregator = MissionEventAggregator(
            redis=redis,
            db_session=db_session,
            mission_id=mission_id,
        )
        try:
            await aggregator.start()

            # Send initial connected event
            yield f"event: connected\ndata: {json.dumps({'mission_id': mission_id})}\n\n"

            async for event_payload in aggregator:
                yield f"data: {json.dumps(event_payload)}\n\n"
        except asyncio.CancelledError:
            logger.debug(
                "Mission console SSE stream cancelled",
                extra={"mission_id": mission_id},
            )
        finally:
            await aggregator.stop()
            await db_session.close()
            await redis.close()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
