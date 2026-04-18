"""CLI engine chat handler — routes chat messages to CLI agents.

Counterpart to the PydanticAI streaming path in handle().
Yields the same SessionEvent types so callers (SSE, TUI, Telegram)
see identical event streams regardless of engine.

Differences from PydanticAI path:
  - No real-time streaming (MVP limitation §3.7b) — yields complete response
  - Conversation history serialized into the prompt (CLI agents are stateless)
  - cost_usd always 0.0 (subscription-based, no API billing)
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from modules.backend.agents.mission_control.helpers.cli_executor import (
    execute_claude_code,
    execute_codex,
    execute_copilot,
)
from modules.backend.agents.mission_control.helpers.prompt_builder import (
    load_agent_system_prompt,
)
from modules.backend.agents.mission_control.models import EventBusProtocol
from modules.backend.core.config import find_project_root
from modules.backend.core.logging import get_logger
from modules.backend.core.protocols import SessionServiceProtocol
from modules.backend.events.types import (
    AgentResponseCompleteEvent,
    AgentThinkingEvent,
    CostUpdateEvent,
    SessionEvent,
    UserMessageEvent,
)
from modules.backend.schemas.session import SessionMessageCreate

logger = get_logger(__name__)

_ENGINE_FNS = {
    "claude_code": execute_claude_code,
    "codex": execute_codex,
    "copilot": execute_copilot,
}


def _serialize_history(messages: list) -> str:
    """Serialize session messages into text for CLI agent context.

    CLI agents are stateless — they don't carry conversation history
    natively. We prepend the history as structured text so the agent
    has context from prior turns.
    """
    lines: list[str] = []
    for msg in messages:
        role = getattr(msg, "role", "user")
        content = getattr(msg, "content", "")
        if not content:
            continue
        if role == "user":
            lines.append(f"User: {content}")
        elif role == "assistant":
            # Truncate long assistant responses to avoid blowing the context
            truncated = content[:2000] + ("..." if len(content) > 2000 else "")
            lines.append(f"Assistant: {truncated}")
    return "\n".join(lines)


async def handle_cli_chat(
    session_id: str,
    message: str,
    *,
    agent_name: str,
    agent_config: Any,
    mission_id: str,
    session_service: SessionServiceProtocol,
    event_bus: EventBusProtocol,
    channel: str = "api",
    sender_id: str | None = None,
    db_session: Any | None = None,
    skip_persistence: bool = False,
) -> AsyncIterator[SessionEvent]:
    """Execute a chat turn via a CLI engine agent.

    Mirrors handle()'s event contract:
        UserMessageEvent → AgentThinkingEvent → AgentResponseCompleteEvent
        → CostUpdateEvent → message persistence

    No streaming chunks — the CLI engine returns a complete response.
    This is a documented MVP limitation (Plan 55 §3.7b).
    """
    sid = uuid.UUID(session_id) if not isinstance(session_id, uuid.UUID) else session_id
    source = "mission_control"
    engine = agent_config.engine

    # 1. Yield UserMessageEvent
    user_event = UserMessageEvent(
        session_id=sid, source=source, content=message, channel=channel,
    )
    yield user_event

    # 2. Yield AgentThinkingEvent
    yield AgentThinkingEvent(
        session_id=sid, source=source, agent_id=agent_name,
    )

    # 3. Load conversation history and serialize
    history_messages, _ = await session_service.get_messages(session_id, limit=50)
    history_text = _serialize_history(history_messages)

    # 4. Build full message with history context
    full_message = message
    if history_text:
        full_message = (
            f"[Previous conversation]\n{history_text}\n"
            f"[End previous conversation]\n\n{message}"
        )

    # 5. Inject mission context on first turn
    if not history_messages:
        from modules.backend.agents.mission_control.mission_control import (
            _prepend_mission_context,
        )
        full_message = await _prepend_mission_context(mission_id, full_message)

    # 6. Load system prompt and execute
    system_prompt = load_agent_system_prompt(agent_name)
    engine_fn = _ENGINE_FNS[engine]

    engine_kwargs: dict = {
        "agent_name": agent_name,
        "instructions": full_message,
        "inputs": {},
        "system_prompt": system_prompt,
        "working_dir": str(find_project_root()),
        "event_bus": event_bus,
        "session_id": session_id,
    }
    if engine == "claude_code":
        if getattr(agent_config, "effort", None):
            engine_kwargs["effort"] = agent_config.effort
        engine_kwargs["scope_read"] = agent_config.scope.read
        engine_kwargs["scope_write"] = agent_config.scope.write

    result = await engine_fn(**engine_kwargs)
    output = result.get("output", "")

    # 7. Yield AgentResponseCompleteEvent
    model_label = f"cli:{engine}"
    yield AgentResponseCompleteEvent(
        session_id=sid,
        source=source,
        agent_id=agent_name,
        full_content=output,
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        model=model_label,
    )

    # 8. Yield CostUpdateEvent
    session = await session_service.get_session(session_id)
    budget_remaining = None
    if session.cost_budget_usd is not None:
        budget_remaining = max(
            0.0, session.cost_budget_usd - session.total_cost_usd,
        )
    yield CostUpdateEvent(
        session_id=sid,
        source=source,
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        cumulative_cost_usd=session.total_cost_usd,
        budget_remaining_usd=budget_remaining,
        model=model_label,
    )

    # 9. Persist messages
    if not skip_persistence:
        from modules.backend.agents.mission_control.helpers import _persist_messages
        await _persist_messages(
            session_service, session_id,
            [SessionMessageCreate(role="user", content=message, sender_id=sender_id)],
        )
    # Persist assistant response
    from modules.backend.agents.mission_control.helpers import _persist_messages
    await _persist_messages(
        session_service, session_id,
        [SessionMessageCreate(
            role="assistant",
            content=output,
            sender_id=agent_name,
            model=model_label,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
        )],
    )

    # 10. Touch activity
    try:
        await session_service.touch_activity(session_id)
    except Exception:
        logger.debug("Failed to touch session activity", exc_info=True)
