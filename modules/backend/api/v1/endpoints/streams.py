"""
SSE Streaming Endpoints.

Server-Sent Event streams for real-time notifications and run monitoring.

Auth note: browser `EventSource` cannot send custom headers, so these
endpoints accept the JWT as a `?token=...` query parameter via the shared
`SseUser` dependency. Ownership/membership checks live in this module so
that an authenticated caller can only stream data for resources they can
actually see via the REST API.
"""

import asyncio
import json
import uuid

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis as AsyncRedis

from modules.backend.core.config import get_redis_url
from modules.backend.core.dependencies import DbSession, SseUser
from modules.backend.core.exceptions import AuthorizationError, NotFoundError
from modules.backend.core.logging import get_logger
from modules.backend.events.bus import SessionEventBus
from modules.backend.services.console import format_event_for_sse
from modules.backend.services.mission import MissionService
from modules.backend.services.session import SessionService

logger = get_logger(__name__)

router = APIRouter()


# ---- Access helpers ----


async def _require_mission_access(
    db, mission_id: str, user,
) -> None:
    """Admin, owner, or mission member. Raises AuthorizationError otherwise."""
    if user.has_role("admin"):
        return
    mission = await MissionService(db).get_mission(mission_id)
    if mission.owner_id == user.id:
        return
    if any(m.user_id == user.id for m in mission.members):
        return
    raise AuthorizationError("You don't have access to this mission")


async def _require_session_access(
    db, session_id: str, user,
) -> None:
    """Admin, session owner, or mission member of the session's mission."""
    if user.has_role("admin"):
        return
    try:
        session = await SessionService(db).get_session(session_id)
    except NotFoundError:
        raise AuthorizationError("Session not found or access denied")
    if session.user_id == user.id:
        return
    if session.mission_id:
        try:
            await _require_mission_access(db, session.mission_id, user)
            return
        except AuthorizationError:
            pass
    raise AuthorizationError("You don't have access to this session")


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
    user: SseUser,
    db: DbSession,
) -> StreamingResponse:
    """Stream execution events for a session as SSE.

    Subscribes to the mission channel and filters by session_id.
    All events go through one channel per mission.
    """
    await _require_session_access(db, session_id, user)

    # Look up mission_id from the session
    session = await SessionService(db).get_session(session_id)
    mission_id = session.mission_id

    async def generate():
        redis = AsyncRedis.from_url(get_redis_url())
        bus = SessionEventBus(redis)
        try:
            yield f"event: connected\ndata: {json.dumps({'session_id': session_id})}\n\n"

            if mission_id:
                async for event in bus.subscribe_mission_filtered(
                    mission_id, uuid.UUID(session_id),
                ):
                    yield f"data: {json.dumps(format_event_for_sse(event))}\n\n"
            else:
                # No mission — nothing to subscribe to
                while True:
                    yield ": keepalive\n\n"
                    await asyncio.sleep(5)
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
    user: SseUser,
    user_id: str = Query(..., description="User ID to receive notifications for"),
) -> StreamingResponse:
    """Stream notifications for a user as SSE."""
    # Admins can subscribe to any user's notifications; everyone else may
    # only subscribe to their own.
    if user_id != user.id and not user.has_role("admin"):
        raise AuthorizationError("Cannot subscribe to another user's notifications")

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
    user: SseUser,
    db: DbSession,
) -> StreamingResponse:
    """Stream all events for a mission as SSE.

    Single channel subscription — no multi-session aggregation needed.
    All events publish to mission_events:{mission_id}.
    """
    await _require_mission_access(db, mission_id, user)

    async def generate():
        redis = AsyncRedis.from_url(get_redis_url())
        bus = SessionEventBus(redis)
        try:
            yield f"event: connected\ndata: {json.dumps({'mission_id': mission_id})}\n\n"

            async for event in bus.subscribe_mission(mission_id):
                yield f"data: {json.dumps(format_event_for_sse(event))}\n\n"
        except asyncio.CancelledError:
            logger.debug(
                "Mission console SSE stream cancelled",
                extra={"mission_id": mission_id},
            )
        finally:
            await redis.close()
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
