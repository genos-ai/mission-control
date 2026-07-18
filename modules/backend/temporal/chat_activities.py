"""
Chat turn activities (Plan 52 Phase B).

Three activities that decompose a chat turn into independently
retryable steps:

1. persist_user_message — writes the user message to session_messages
   before the agent starts. Survives any subsequent failure.
2. execute_chat_turn — drains handle() with a real event bus so
   events publish to Redis Pub/Sub in real-time. Returns the
   accumulated response content.
3. persist_assistant_message — writes the assistant response to
   session_messages after the agent completes.

Each activity opens its own DB session and commits independently.
Temporal retries each one separately on failure.
"""

from temporalio import activity

from modules.backend.core.logging import get_logger
from modules.backend.temporal.chat_models import ChatTurnInput, ChatTurnResult

logger = get_logger(__name__)


@activity.defn
async def persist_user_message(input: ChatTurnInput) -> str:
    """Persist the user message to session_messages. Returns the message ID.

    This runs BEFORE the agent starts. If the user navigates away,
    closes the browser, or the worker crashes during agent execution,
    the user message is already safely in the database.
    """
    from modules.backend.core.database import get_async_session
    from modules.backend.schemas.session import SessionMessageCreate
    from modules.backend.services.session import SessionService

    activity.logger.info(
        "Persisting user message",
        extra={"session_id": input.session_id, "content_len": len(input.message)},
    )

    async with get_async_session() as db:
        svc = SessionService(db)
        msg = SessionMessageCreate(
            role="user",
            content=input.message,
            sender_id=input.sender_id,
        )
        await svc.add_message(input.session_id, msg)
        await db.commit()

    return input.session_id


@activity.defn
async def execute_chat_turn(input: ChatTurnInput) -> ChatTurnResult:
    """Run a chat turn via handle(), publishing events to Redis in real-time.

    handle() is an async generator that yields SessionEvent objects.
    Activities must return a value, not yield. We drain the generator
    internally, but handle() publishes every event to the event bus
    via _publish(event_bus, event) at each step — so events flow to
    Redis Pub/Sub live as handle() yields them.

    The frontend subscribes to /streams/runs/{sessionId} via EventSource
    and sees streaming in real-time. Same UX, different transport.

    handle() persists messages at step 11. The user message is already
    persisted by persist_user_message (activity 1), so we pass
    skip_persistence=True — handle() skips the user message write
    but still persists the assistant response inline. No separate
    persist_assistant_message activity needed.
    """
    from redis.asyncio import Redis as AsyncRedis

    from modules.backend.agents.mission_control.mission_control import handle
    from modules.backend.core.config import get_redis_url
    from modules.backend.core.database import get_async_session
    from modules.backend.events.bus import SessionEventBus
    from modules.backend.services.session import SessionService

    activity.logger.info(
        "Executing chat turn",
        extra={
            "session_id": input.session_id,
            "mission_id": input.mission_id,
            "message_preview": input.message[:100],
        },
    )

    redis = AsyncRedis.from_url(get_redis_url())
    event_bus = SessionEventBus(redis, mission_id=input.mission_id)

    full_content = ""
    agent_name = ""
    input_tokens = 0
    output_tokens = 0
    cost_usd = 0.0
    model = ""
    error: str | None = None
    thinking: str | None = None

    try:
        async with get_async_session() as db:
            session_service = SessionService(db)

            async for event in handle(
                input.session_id,
                input.message,
                mission_id=input.mission_id,
                session_service=session_service,
                event_bus=event_bus,
                channel=input.channel,
                sender_id=input.sender_id,
                db_session=db,
                skip_persistence=True,
            ):
                # Extract metadata from the complete event
                if hasattr(event, "full_content") and event.full_content:
                    full_content = event.full_content
                if hasattr(event, "agent_id") and event.agent_id:
                    agent_name = event.agent_id
                if hasattr(event, "input_tokens") and event.input_tokens:
                    input_tokens = event.input_tokens
                if hasattr(event, "output_tokens") and event.output_tokens:
                    output_tokens = event.output_tokens
                if hasattr(event, "cost_usd") and event.cost_usd:
                    cost_usd = event.cost_usd
                if hasattr(event, "model") and event.model:
                    model = event.model
                if hasattr(event, "metadata"):
                    meta = event.metadata or {}
                    if meta.get("error"):
                        error = full_content
                    if meta.get("thinking"):
                        thinking = meta.get("thinking")

            await db.commit()

    except Exception as exc:
        activity.logger.error(
            "Chat turn failed",
            extra={
                "session_id": input.session_id,
                "error": str(exc),
                "mission_id": input.mission_id,
            },
        )
        error = str(exc)
    finally:
        await redis.aclose()

    return ChatTurnResult(
        session_id=input.session_id,
        content=full_content,
        agent_name=agent_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        model=model,
        error=error,
        thinking=thinking,
    )


@activity.defn
async def persist_assistant_message(
    session_id: str,
    result: ChatTurnResult,
) -> bool:
    """Persist the assistant response to session_messages.

    Runs AFTER the agent completes. If this activity fails, Temporal
    retries it — the agent doesn't re-execute, just the persistence.

    Note: handle() may have already persisted the assistant message
    at step 11. This is a safety net — if the handle() persistence
    failed (or was skipped due to error), this ensures the response
    is saved. Duplicate messages are harmless (frontend deduplicates
    on refetch).
    """
    from modules.backend.core.database import get_async_session
    from modules.backend.schemas.session import SessionMessageCreate
    from modules.backend.services.session import SessionService

    if not result.content and not result.error:
        activity.logger.info("No content to persist", extra={"session_id": session_id})
        return True

    activity.logger.info(
        "Persisting assistant message",
        extra={
            "session_id": session_id,
            "content_len": len(result.content),
            "cost_usd": result.cost_usd,
        },
    )

    async with get_async_session() as db:
        svc = SessionService(db)
        msg = SessionMessageCreate(
            role="error" if result.error and not result.content else "assistant",
            content=result.error if result.error and not result.content else result.content,
            sender_id=result.agent_name or None,
            model=result.model or None,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=result.cost_usd,
            thinking=result.thinking,
        )
        await svc.add_message(session_id, msg)
        await db.commit()

    return True
