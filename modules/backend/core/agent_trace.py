"""
Agent Trace — unified tracing for all agent interactions.

Single module for tracing prompts, tool calls, and responses across
all agents and all model providers (Anthropic, CopilotModel, OpenAI).

Uses PydanticAI's result.all_messages() which is provider-agnostic.
Emits traces in two channels:
  1. Structured log at DEBUG level → var/logs/system.jsonl
  2. Mission event bus → frontend console (when trace_enabled=True)

Enable tracing:
  - CLI:      python services.py restart --log-level DEBUG
  - mc chat:  python mc.py --debug chat ...
  - Runtime:  set MC_AGENT_TRACE=1 env var
  - Frontend: toggle trace mode in console (emits via event bus)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from modules.backend.core.logging import get_logger

if TYPE_CHECKING:
    from modules.backend.core.protocols import EventBusProtocol

logger = get_logger(__name__)


def is_trace_enabled() -> bool:
    """Check if agent tracing is enabled via environment variable.

    DEBUG log level always captures traces to the log file.
    MC_AGENT_TRACE=1 additionally emits trace events to the mission
    event bus so the frontend console can display them.
    """
    return os.environ.get("MC_AGENT_TRACE", "").strip() in ("1", "true")


def trace_agent_run(
    agent_name: str,
    result: Any,
    *,
    mission_id: str | None = None,
    session_id: str | None = None,
    model: str = "",
) -> list[dict]:
    """Extract and log the full message trace from an agent run.

    Works with any PydanticAI result that has .all_messages() —
    provider-agnostic. Returns the extracted trace entries for
    callers that want to emit them to the event bus.

    Args:
        agent_name: The agent that ran (e.g. "mission.director.agent")
        result: PydanticAI AgentRunResult or StreamedRunResult
        mission_id: Mission context for log correlation
        session_id: Session context for log correlation
        model: Model string (e.g. "copilot:claude-sonnet-4.6")

    Returns:
        List of trace entry dicts, each with:
            role, content_preview, tool_name, tool_args_preview
    """
    try:
        messages = result.all_messages()
    except Exception:
        return []

    entries = _extract_trace(messages)

    if not entries:
        return []

    # Log the full trace at DEBUG level — always captured in
    # var/logs/system.jsonl when log level is DEBUG.
    logger.debug(
        "Agent trace",
        extra={
            "agent_name": agent_name,
            "model": model,
            "mission_id": mission_id,
            "session_id": session_id,
            "turn_count": len(entries),
            "trace": entries,
        },
    )

    return entries


async def trace_and_emit(
    agent_name: str,
    result: Any,
    *,
    mission_id: str | None = None,
    session_id: str | None = None,
    model: str = "",
    event_bus: "EventBusProtocol | None" = None,
) -> None:
    """Trace an agent run and emit to event bus if tracing is enabled.

    Convenience wrapper that combines trace_agent_run + emit_trace_events.
    Call sites use this single function instead of the two-step pattern.
    """
    entries = trace_agent_run(
        agent_name, result,
        mission_id=mission_id, session_id=session_id, model=model,
    )
    if is_trace_enabled() and entries and event_bus and mission_id:
        await emit_trace_events(
            entries,
            agent_name=agent_name,
            mission_id=mission_id,
            session_id=session_id,
            event_bus=event_bus,
        )


async def emit_trace_events(
    entries: list[dict],
    *,
    agent_name: str,
    mission_id: str,
    session_id: str | None = None,
    event_bus: "EventBusProtocol | None" = None,
) -> None:
    """Emit one agent.trace event per trace entry to the mission event bus.

    Per-entry (not batched) so the frontend console renders each line
    chronologically — same pattern as agent.tool.called events. Only
    emitted when MC_AGENT_TRACE=1 (explicit opt-in for debugging).
    """
    if not event_bus or not mission_id or not entries:
        return

    import uuid

    from modules.backend.events.types import SessionEvent

    sid = uuid.UUID(session_id) if session_id else uuid.uuid4()

    for entry in entries:
        try:
            event = SessionEvent(
                session_id=sid,
                source=agent_name,
                event_type="agent.trace",
                metadata={
                    "role": entry.get("role", ""),
                    "content_preview": entry.get("content_preview", ""),
                    "tool_name": entry.get("tool_name", ""),
                    "tool_args_preview": entry.get("tool_args_preview", ""),
                    "mission_id": mission_id,
                },
            )
            await event_bus.publish_to_mission(mission_id, event)
        except Exception:
            pass  # best-effort — trace emission never blocks


def _extract_trace(messages: list) -> list[dict]:
    """Extract a human-readable trace from PydanticAI messages.

    Handles ModelRequest (instructions, user prompts, tool returns)
    and ModelResponse (text parts, tool calls).
    """
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        TextPart,
        ToolCallPart,
        ToolReturnPart,
        UserPromptPart,
        SystemPromptPart,
    )

    entries: list[dict] = []

    for msg in messages:
        if isinstance(msg, ModelRequest):
            # Instructions (system prompt)
            if msg.instructions:
                entries.append({
                    "role": "system",
                    "content_preview": msg.instructions[:500],
                })

            for part in msg.parts:
                if isinstance(part, SystemPromptPart):
                    entries.append({
                        "role": "system",
                        "content_preview": part.content[:500],
                    })
                elif isinstance(part, UserPromptPart):
                    content = part.content if isinstance(part.content, str) else str(part.content)
                    entries.append({
                        "role": "user",
                        "content_preview": content[:500],
                    })
                elif isinstance(part, ToolReturnPart):
                    content = part.model_response_str()
                    entries.append({
                        "role": "tool_result",
                        "tool_name": part.tool_name,
                        "content_preview": content[:500],
                    })

        elif isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, TextPart):
                    entries.append({
                        "role": "assistant",
                        "content_preview": part.content[:500],
                    })
                elif isinstance(part, ToolCallPart):
                    args_str = str(part.args)[:300] if part.args else ""
                    entries.append({
                        "role": "tool_call",
                        "tool_name": part.tool_name,
                        "tool_args_preview": args_str,
                    })

    return entries
