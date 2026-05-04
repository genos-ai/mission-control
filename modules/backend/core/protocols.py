"""Cross-boundary protocol definitions.

Protocols that decouple the services layer from the agents layer.
Both layers import from core — neither imports from the other.

EventBusProtocol / NoOpEventBus: event emission interface used by
    services, agents, and temporal activities.
SessionServiceProtocol: agents layer depends on this instead of
    the concrete SessionService.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from modules.backend.core.logging import get_logger
from modules.backend.events.types import SessionEvent

_logger = get_logger(__name__)


@runtime_checkable
class EventBusProtocol(Protocol):
    """Interface for event bus implementations (SessionEventBus, mocks, etc.)."""

    async def publish(self, event: SessionEvent) -> None: ...

    async def publish_to_mission(self, mission_id: str, event: SessionEvent) -> None: ...


class NoOpEventBus:
    """Null-object event bus — satisfies EventBusProtocol, drops all events.

    Logs a warning on first use so silent event loss is visible.
    Use explicitly in tests. Production code should pass a real SessionEventBus.
    """

    _warned = False

    async def publish(self, event: SessionEvent) -> None:
        if not NoOpEventBus._warned:
            _logger.warning(
                "NoOpEventBus in use — events are being silently dropped. "
                "Pass a real SessionEventBus for production visibility.",
            )
            NoOpEventBus._warned = True

    async def publish_to_mission(self, mission_id: str, event: SessionEvent) -> None:
        if not NoOpEventBus._warned:
            _logger.warning(
                "NoOpEventBus in use — events are being silently dropped. "
                "Pass a real SessionEventBus for production visibility.",
            )
            NoOpEventBus._warned = True


class SessionServiceProtocol(Protocol):
    """Interface for session operations used by mission control.

    The agents layer codes against this protocol. The concrete
    SessionService in the services layer satisfies it structurally
    (no explicit registration needed).
    """

    async def get_session(self, session_id: str) -> Any: ...

    async def enforce_budget(
        self, session_id: str, estimated_cost: float = ...,
    ) -> None: ...

    async def get_messages(
        self, session_id: str, limit: int = ..., offset: int = ...,
    ) -> tuple[list, int]: ...

    async def update_cost(
        self,
        session_id: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None: ...

    async def touch_activity(self, session_id: str) -> None: ...

    async def add_message(self, session_id: str, data: Any) -> None: ...

    async def create_streaming_message(
        self, session_id: str, sender_id: str | None = ...,
    ) -> str: ...

    async def update_streaming_content(
        self, message_id: str, content: str,
    ) -> None: ...

    async def finalize_streaming_message(
        self,
        message_id: str,
        content: str,
        *,
        status: str = ...,
        model: str | None = ...,
        input_tokens: int | None = ...,
        output_tokens: int | None = ...,
        cost_usd: float | None = ...,
        thinking: str | None = ...,
    ) -> None: ...


