"""Event and persistence plumbing — publish, emit, tool events, message persistence."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from modules.backend.core.protocols import SessionServiceProtocol

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
)

from modules.backend.agents.mission_control.models import EventBusProtocol
from modules.backend.core.exceptions import ApplicationError
from modules.backend.core.logging import get_logger
from modules.backend.events.types import (
    AgentToolCallEvent,
    AgentToolResultEvent,
    SessionEvent,
)
from modules.backend.schemas.session import SessionMessageCreate

logger = get_logger(__name__)


async def _publish(event_bus: EventBusProtocol, event: SessionEvent) -> None:
    """Publish event to bus. Non-critical — NoOpEventBus silently drops."""
    try:
        await event_bus.publish(event)
    except Exception:
        logger.debug("Event bus publish failed", exc_info=True)


async def _emit(event_bus: EventBusProtocol, event_cls: type[SessionEvent], **kwargs: Any) -> None:
    """Construct and publish an event, catching construction and publish errors."""
    try:
        event = event_cls(**kwargs)
        await event_bus.publish(event)
    except Exception:
        logger.debug("Event emission failed for %s", event_cls.__name__, exc_info=True)


async def _emit_tool_events(
    event_bus: EventBusProtocol,
    stream: Any,
    *,
    session_id: str | uuid.UUID,
    source: str,
    agent_id: str,
) -> tuple[list[str], list[SessionEvent]]:
    """Extract thinking parts and tool events from a completed stream.

    Reads stream.new_messages() retrospectively (after streaming ends)
    to find ThinkingPart, ToolCallPart, and ToolReturnPart entries.
    Publishes tool events to the event bus.

    Returns (thinking_parts, tool_events). Best-effort — errors are logged and swallowed.
    """
    thinking_parts: list[str] = []
    tool_events: list[SessionEvent] = []
    try:
        for msg in stream.new_messages():
            if isinstance(msg, ModelResponse):
                for part in msg.parts:
                    if isinstance(part, ThinkingPart) and part.has_content():
                        thinking_parts.append(part.content)
                    elif isinstance(part, ToolCallPart):
                        try:
                            event = AgentToolCallEvent(
                                session_id=session_id,
                                source=source,
                                agent_id=agent_id,
                                tool_name=part.tool_name,
                                tool_args={
                                    "raw": part.args if isinstance(part.args, str) else str(part.args),
                                },
                                tool_call_id=part.tool_call_id or str(uuid.uuid4()),
                            )
                            await event_bus.publish(event)
                            tool_events.append(event)
                        except Exception:
                            logger.debug("Event emission failed for AgentToolCallEvent", exc_info=True)
            elif isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, ToolReturnPart):
                        try:
                            event = AgentToolResultEvent(
                                session_id=session_id,
                                source=source,
                                agent_id=agent_id,
                                tool_name=part.tool_name,
                                tool_call_id=part.tool_call_id or "",
                                result=(
                                    part.content
                                    if isinstance(part.content, str)
                                    else str(part.content)
                                ),
                            )
                            await event_bus.publish(event)
                            tool_events.append(event)
                        except Exception:
                            logger.debug("Event emission failed for AgentToolResultEvent", exc_info=True)
    except (AttributeError, TypeError, KeyError, ValueError):
        logger.debug("Failed to extract tool events", exc_info=True)
    return thinking_parts, tool_events


async def _persist_messages(
    session_service: "SessionServiceProtocol",
    session_id: str,
    creates: list[SessionMessageCreate],
) -> None:
    """Persist messages to session. Non-critical."""
    try:
        for create in creates:
            await session_service.add_message(session_id, create)
    except (OSError, ApplicationError) as exc:
        logger.warning("Failed to persist session messages: %s", exc)
