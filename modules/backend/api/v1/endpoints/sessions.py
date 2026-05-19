"""Session management REST endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query

from modules.backend.core.dependencies import DbSession, Idempotency, RequestId
from modules.backend.core.pagination import (
    PaginationParams,
    create_paginated_response,
    get_pagination_params,
)
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.session import (
    ChannelBindRequest,
    ChannelResponse,
    SessionCreate,
    SessionListResponse,
    SessionMessageCreate,
    SessionMessageResponse,
    SessionResponse,
    SessionUpdate,
)
from modules.backend.services.session import SessionService

router = APIRouter()


# --- Session CRUD ---


@router.post(
    "",
    response_model=ApiResponse[SessionResponse],
    status_code=201,
    summary="Create a session",
    description="Create a new interactive session with optional goal, agent, and cost budget.",
)
async def create_session(
    data: SessionCreate,
    db: DbSession,
    request_id: RequestId,
    idempotency: Idempotency,
    user_id: str | None = Query(default=None, description="Owner user ID (temporary — will come from auth context)"),
) -> ApiResponse[SessionResponse]:
    """Supports Idempotency-Key header — safe to retry on network timeout."""
    if idempotency:
        cached = await idempotency.get_cached_response()
        if cached:
            return ApiResponse(**cached)

    service = SessionService(db)
    session = await service.create_session(data, user_id=user_id)
    result = ApiResponse(data=SessionResponse.model_validate(session))
    if idempotency:
        await idempotency.cache_response(result.model_dump())
    return result


@router.get(
    "/{session_id}",
    response_model=ApiResponse[SessionResponse],
    summary="Get a session",
    description="Get a session by ID with current cost and status.",
)
async def get_session(
    session_id: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse[SessionResponse]:
    service = SessionService(db)
    session = await service.get_session(session_id)
    return ApiResponse(data=SessionResponse.model_validate(session))


@router.patch(
    "/{session_id}",
    response_model=ApiResponse[SessionResponse],
    summary="Update a session",
    description="Update session fields (goal, agent, budget, metadata).",
)
async def update_session(
    session_id: str,
    data: SessionUpdate,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse[SessionResponse]:
    service = SessionService(db)
    session = await service.update_session(session_id, data)
    return ApiResponse(data=SessionResponse.model_validate(session))


@router.get(
    "",
    summary="List sessions",
    description="List sessions for the current user with optional status filter.",
)
async def list_sessions(
    db: DbSession,
    request_id: RequestId,
    pagination: PaginationParams = Depends(get_pagination_params),
    user_id: str | None = Query(default=None, description="Filter by user ID"),
    mission_id: str | None = Query(default=None, description="Filter by mission ID"),
    status: str | None = Query(default=None, description="Filter by status"),
) -> dict:
    service = SessionService(db)
    sessions, total = await service.list_sessions(
        user_id=user_id,
        mission_id=mission_id,
        status_filter=status,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    return create_paginated_response(
        items=sessions,
        item_schema=SessionListResponse,
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
        request_id=request_id,
    )


# --- State Transitions ---


@router.post(
    "/{session_id}/suspend",
    response_model=ApiResponse[SessionResponse],
    summary="Suspend a session",
    description="Suspend a session — pauses for human/AI input or approval.",
)
async def suspend_session(
    session_id: str,
    db: DbSession,
    request_id: RequestId,
    reason: str = Query(..., description="Reason for suspension"),
) -> ApiResponse[SessionResponse]:
    service = SessionService(db)
    session = await service.suspend_session(session_id, reason)
    return ApiResponse(data=SessionResponse.model_validate(session))


@router.post(
    "/{session_id}/resume",
    response_model=ApiResponse[SessionResponse],
    summary="Resume a session",
    description="Resume a suspended session.",
)
async def resume_session(
    session_id: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse[SessionResponse]:
    service = SessionService(db)
    session = await service.resume_session(session_id)
    return ApiResponse(data=SessionResponse.model_validate(session))


@router.post(
    "/{session_id}/complete",
    response_model=ApiResponse[SessionResponse],
    summary="Complete a session",
    description="Mark a session as completed — goal achieved or user ended.",
)
async def complete_session(
    session_id: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse[SessionResponse]:
    service = SessionService(db)
    session = await service.complete_session(session_id)
    return ApiResponse(data=SessionResponse.model_validate(session))


# --- Channel Binding ---


@router.post(
    "/{session_id}/channels",
    response_model=ApiResponse[ChannelResponse],
    status_code=201,
    summary="Bind a channel",
    description="Bind a communication channel to this session.",
)
async def bind_channel(
    session_id: str,
    data: ChannelBindRequest,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse[ChannelResponse]:
    service = SessionService(db)
    binding = await service.bind_channel(session_id, data.channel_type, data.channel_id)
    return ApiResponse(data=ChannelResponse.model_validate(binding))


@router.delete(
    "/{session_id}/channels/{channel_type}/{channel_id}",
    status_code=204,
    summary="Unbind a channel",
    description="Unbind a communication channel from this session.",
)
async def unbind_channel(
    session_id: str,
    channel_type: str,
    channel_id: str,
    db: DbSession,
    request_id: RequestId,
) -> None:
    service = SessionService(db)
    await service.unbind_channel(session_id, channel_type, channel_id)


@router.get(
    "/by-channel/{channel_type}/{channel_id}",
    response_model=ApiResponse[SessionResponse],
    summary="Find session by channel",
    description="Find the active session bound to a specific channel.",
)
async def get_session_by_channel(
    channel_type: str,
    channel_id: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse[SessionResponse]:
    service = SessionService(db)
    session = await service.get_session_by_channel(channel_type, channel_id)
    return ApiResponse(data=SessionResponse.model_validate(session))


# --- Messages ---


@router.get(
    "/{session_id}/messages",
    summary="Get session messages",
    description="Get conversation history for a session, optionally filtered by sender.",
)
async def get_messages(
    session_id: str,
    db: DbSession,
    request_id: RequestId,
    pagination: PaginationParams = Depends(get_pagination_params),
    sender_id: str | None = Query(default=None, description="Filter to messages from this sender (plus user/system messages). Used for agent-scoped views in shared sessions."),
) -> dict:
    service = SessionService(db)
    messages, total = await service.get_messages(
        session_id, limit=pagination.limit, offset=pagination.offset,
        sender_ids=[sender_id] if sender_id else None,
    )
    return create_paginated_response(
        items=messages,
        item_schema=SessionMessageResponse,
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
        request_id=request_id,
    )


# --- Send message ---


@router.post(
    "/{session_id}/messages",
    summary="Send message and stream events",
    description=(
        "Persist the user message, run the agent, and stream "
        "progress events as SSE in the response body."
    ),
)
async def send_message(
    session_id: str,
    mission_id: str,
    data: SessionMessageCreate,
    db: DbSession,
    target_agent: str | None = Query(default=None, description="Route to a specific agent"),
):
    """Send a message and stream agent events.

    target_agent routes the message to a specific agent within the shared
    session. If omitted, routing falls back to session.agent_id or keyword matching.

    The agent runs in a background task that survives browser
    disconnect. Events flow through an asyncio.Queue to the SSE
    response AND to Redis for other watchers. If the client
    disconnects mid-stream, the background task continues —
    handle() completes, persists the response, and publishes
    to Redis. When the user comes back, the response is in the DB.
    """
    if target_agent:
        from modules.backend.agents.mission_control.registry import get_registry
        if not get_registry().has(target_agent):
            raise HTTPException(status_code=422, detail=f"Unknown agent: {target_agent}")

    import asyncio

    from fastapi.responses import StreamingResponse
    from redis.asyncio import Redis as AsyncRedis

    from modules.backend.agents.mission_control.mission_control import handle
    from modules.backend.core.config import get_redis_url
    from modules.backend.core.database import get_async_session
    from modules.backend.core.logging import get_logger
    from modules.backend.events.bus import SessionEventBus

    logger = get_logger(__name__)

    # 1. Persist user message (request DB session, synchronous)
    service = SessionService(db)
    user_msg = SessionMessageCreate(
        role="user",
        content=data.content,
        sender_id=data.sender_id,
    )
    await service.add_message(session_id, user_msg, target_agent=target_agent)
    await db.commit()

    # 2. Shared queue bridges background task → SSE response
    queue: asyncio.Queue = asyncio.Queue()

    # 3. Background task — runs handle() with its own DB session,
    #    drains events into the queue, survives client disconnect.
    async def _run_agent() -> None:
        redis = AsyncRedis.from_url(get_redis_url())
        event_bus = SessionEventBus(redis, mission_id=mission_id)
        try:
            async with get_async_session() as bg_db:
                bg_service = SessionService(bg_db)
                async for event in handle(
                    session_id,
                    data.content,
                    mission_id=mission_id,
                    target_agent=target_agent,
                    session_service=bg_service,
                    event_bus=event_bus,
                    sender_id=data.sender_id,
                    db_session=bg_db,
                    skip_persistence=True,
                ):
                    await queue.put(event)
                await bg_db.commit()
        except Exception:
            logger.exception(
                "Background agent task failed",
                extra={"session_id": session_id},
            )
        finally:
            await redis.aclose()
            await queue.put(None)  # sentinel — closes the SSE stream

    asyncio.create_task(_run_agent())

    # 4. SSE generator — reads from queue, yields to client.
    #    If client disconnects, this generator is cancelled but
    #    the background task continues independently.
    async def generate():
        from modules.backend.core.config import get_app_config
        keepalive_sec = get_app_config().application.timeouts.sse_keepalive
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=keepalive_sec)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if event is None:
                    break
                yield f"event: {event.event_type}\ndata: {event.model_dump_json()}\n\n"
            yield "event: done\ndata: {}\n\n"
        except asyncio.CancelledError:
            pass  # client disconnected — background task continues

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
