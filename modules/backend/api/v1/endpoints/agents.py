"""
Agent Endpoints.

REST API for agent interaction: chat, streaming, and registry listing.
All chat goes through sessions. Auto-creates ephemeral session when none provided.
Multi-agent missions go through the missions API, not here.
"""

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from modules.backend.core.dependencies import DbSession, Idempotency, RequestId
from modules.backend.core.logging import get_logger
from modules.backend.schemas.base import ApiResponse

logger = get_logger(__name__)

router = APIRouter()


class ChatRequest(BaseModel):
    """Request body for agent chat."""

    message: str = Field(
        ...,
        min_length=1,
        description="User message to send to the agent",
    )
    mission_id: str = Field(
        ...,
        description="Mission ID. Every conversation must be scoped to a mission.",
    )
    agent: str | None = Field(
        default=None,
        description="Target a specific agent by name, bypassing routing.",
    )
    session_id: str | None = Field(
        default=None,
        description="Session ID. Auto-created if omitted.",
    )


class ChatResponse(BaseModel):
    """Response from an agent."""

    agent_name: str
    output: str
    session_id: str | None = None


class AgentInfo(BaseModel):
    """Agent registry entry."""

    agent_name: str
    description: str
    keywords: list[str]
    tools: list[str]


async def _resolve_shared_session(
    service,
    session_id: str | None,
    mission_id: str,
    user_id: str | None = None,
) -> str:
    """Resolve or create a shared mission session.

    Reuses the mission's most recent active session for this user, or creates
    one with mission.director.agent as the default fallback.
    """
    if session_id:
        return session_id
    from modules.backend.schemas.session import SessionCreate

    existing = await service.find_active_for_mission(mission_id, user_id=user_id)
    if existing:
        return str(existing.id)
    session = await service.create_session(
        SessionCreate(
            agent_id="mission.director.agent",
            mission_id=mission_id,
            goal="Mission Chat",
        ),
        user_id=user_id,
    )
    return str(session.id)


@router.post(
    "/chat",
    response_model=ApiResponse[ChatResponse],
    summary="Chat with an agent",
    description="Send a message to an agent via single-agent routing. Auto-creates a session if none provided.",  # noqa: E501
)
async def agent_chat(
    data: ChatRequest,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse[ChatResponse]:
    """Send a message to an agent. Auto-creates ephemeral session when no session_id provided."""
    from modules.backend.agents.mission_control.mission_control import collect
    from modules.backend.services.session import SessionService

    service = SessionService(db)
    session_id = await _resolve_shared_session(service, data.session_id, data.mission_id)

    result = await collect(
        session_id,
        data.message,
        mission_id=data.mission_id,
        target_agent=data.agent,
        session_service=service,
        db_session=db,
    )

    return ApiResponse(
        data=ChatResponse(
            agent_name=result.get("agent_name", ""),
            output=result.get("output", ""),
            session_id=session_id,
        ),
    )


@router.post(
    "/chat/stream",
    summary="Chat with an agent (streaming SSE)",
    description="Send a message to an agent and stream progress events as SSE.",
)
async def agent_chat_stream(
    data: ChatRequest,
    db: DbSession,
    idempotency: Idempotency,
):
    """Stream agent events. Agent runs in background task that survives disconnect."""
    import asyncio

    from fastapi.responses import StreamingResponse
    from redis.asyncio import Redis as AsyncRedis

    from modules.backend.agents.mission_control.mission_control import handle
    from modules.backend.core.config import get_redis_url
    from modules.backend.core.database import get_async_session
    from modules.backend.events.bus import SessionEventBus
    from modules.backend.schemas.session import SessionMessageCreate
    from modules.backend.services.session import SessionService

    # Return cached response if this stream was already started
    if idempotency:
        cached = await idempotency.get_cached_response()
        if cached:
            return ApiResponse(**cached)

    service = SessionService(db)
    session_id = await _resolve_shared_session(service, data.session_id, data.mission_id)

    user_msg = SessionMessageCreate(role="user", content=data.message)
    await service.add_message(session_id, user_msg, target_agent=data.agent)
    await db.commit()

    queue: asyncio.Queue = asyncio.Queue()

    async def _run_agent() -> None:
        redis = AsyncRedis.from_url(get_redis_url())
        event_bus = SessionEventBus(redis, mission_id=data.mission_id)
        try:
            async with get_async_session() as bg_db:
                bg_service = SessionService(bg_db)
                async for event in handle(
                    session_id,
                    data.message,
                    mission_id=data.mission_id,
                    target_agent=data.agent,
                    session_service=bg_service,
                    event_bus=event_bus,
                    db_session=bg_db,
                    skip_persistence=True,
                ):
                    await queue.put(event)
                await bg_db.commit()
        except Exception as exc:
            logger.exception(
                "Background agent task failed",
                extra={"session_id": session_id},
            )
            try:
                from modules.backend.events.types import SystemEvent

                await event_bus.publish(
                    SystemEvent(
                        session_id=(uuid.UUID(session_id) if session_id else uuid.uuid4()),
                        source="agents_endpoint:background_task",
                        level="error",
                        message=f"Background agent task failed: {exc}",
                        mission_id=data.mission_id,
                    )
                )
            except Exception:
                # best-effort — this IS the event-emission path; there is
                # nowhere further to escalate to.
                logger.warning("Failed to emit background-task-failure SystemEvent", exc_info=True)
        finally:
            await redis.aclose()
            await queue.put(None)

    asyncio.create_task(_run_agent())

    if idempotency:
        await idempotency.cache_response({"success": True, "data": {"session_id": session_id}})

    async def generate():
        from modules.backend.core.config import get_app_config

        keepalive_sec = get_app_config().application.timeouts.sse_keepalive
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=keepalive_sec)
                except asyncio.TimeoutError:
                    # SSE comment line — keeps the connection alive during
                    # long tool executions (e.g. Planning Agent building a DAG)
                    yield ": keepalive\n\n"
                    continue
                if event is None:
                    break
                yield f"event: {event.event_type}\ndata: {event.model_dump_json()}\n\n"
            yield "event: done\ndata: {}\n\n"
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/registry",
    response_model=ApiResponse[list[AgentInfo]],
    summary="List available agents",
    description="Returns all enabled agents with their capabilities and keywords.",
)
async def agent_registry(
    request_id: RequestId,
) -> ApiResponse[list[AgentInfo]]:
    """List all available agents."""
    from modules.backend.agents.mission_control.mission_control import list_agents

    agents = list_agents()
    return ApiResponse(
        data=[AgentInfo(**a) for a in agents],
    )
