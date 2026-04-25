"""Mission Control — routes messages to agents, enforces budgets, streams events.

Infrastructure, not intelligence (P6). Does not call LLMs directly.

Public: handle(), handle_mission(), collect(), list_agents().
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any

from pydantic_ai import UserError
from sqlalchemy.exc import SQLAlchemyError

from modules.backend.agents.mission_control.cost import compute_cost_usd, estimate_cost
from modules.backend.core.exceptions import ApplicationError, BudgetExceededError
from modules.backend.agents.mission_control.mission_dispatch import handle_mission  # noqa: F401
from modules.backend.agents.mission_control.helpers import (
    _build_agent_deps,
    _build_model,
    _get_model_name,
    _get_usage_limits,
    _persist_messages,
    _publish,
    _resolve_agent,
    assemble_instructions,
    build_model_settings,
    build_deps_from_config,
)
from modules.backend.agents.mission_control.history import (
    session_messages_to_model_history,
)
from modules.backend.agents.mission_control.middleware import check_guardrails
from modules.backend.agents.mission_control.models import CollectResult, EventBusProtocol, NoOpEventBus
from modules.backend.core.protocols import SessionServiceProtocol
from modules.backend.agents.mission_control.registry import get_registry
from modules.backend.core.logging import get_logger
from modules.backend.events.types import (
    AgentResponseChunkEvent,
    AgentResponseCompleteEvent,
    AgentThinkingEvent,
    AgentToolCallEvent,
    AgentToolResultEvent,
    CostUpdateEvent,
    MissionArtifactFoundEvent,
    SessionEvent,
    UserMessageEvent,
)
from modules.backend.schemas.session import SessionMessageCreate

logger = get_logger(__name__)

# Re-export for backwards compatibility (vertical agents import these)
__all__ = [
    "handle",
    "handle_mission",
    "collect",
    "list_agents",
    "assemble_instructions",
    "build_deps_from_config",
    "_build_model",
]


def list_agents() -> list[dict[str, Any]]:
    """List all available agents with their metadata."""
    return get_registry().list_all()


async def _prepend_mission_context(mission_id: str, message: str) -> str:
    """Load mission and prepend context to the user message.

    Gives the agent awareness of the active mission (name, description,
    brief, team) so it can answer questions and plan within that scope.
    """
    from modules.backend.services.mission import MissionService
    from modules.backend.services.mission_team import MissionTeamService

    try:
        async with MissionService.factory() as svc:
            mission = await svc.get_mission(mission_id)
    except Exception:
        logger.warning("Could not load mission context", extra={"mission_id": mission_id})
        return message

    parts = ["[Mission Context]", f"Mission: {mission.name}"]
    if mission.description:
        parts.append(f"Description: {mission.description}")
    if mission.brief:
        parts.append(f"Brief: {mission.brief}")

    # Load team members with full capabilities
    try:
        async with MissionTeamService.factory() as team_svc:
            team_details = await team_svc.list_team_with_details(mission_id)
            if team_details:
                team_lines = []
                for entry in team_details:
                    line = f"  - {entry['agent_name']}: {entry['description']}"
                    if entry["tools"]:
                        line += f"\n    Tools: {', '.join(entry['tools'])}"
                    read_paths = entry["scope"].get("read", [])
                    write_paths = entry["scope"].get("write", [])
                    if read_paths or write_paths:
                        access = []
                        if read_paths:
                            access.append(f"read: {', '.join(read_paths)}")
                        if write_paths:
                            access.append(f"write: {', '.join(write_paths)}")
                        line += f"\n    Access: {'; '.join(access)}"
                    if entry["keywords"]:
                        line += f"\n    Capabilities: {', '.join(entry['keywords'])}"
                    team_lines.append(line)
                if team_lines:
                    parts.append("Team:")
                    parts.extend(team_lines)
    except Exception:
        logger.debug("Could not load team for mission context", extra={"mission_id": mission_id})

    parts.append("[End Mission Context]")
    parts.append("")
    parts.append(message)

    return "\n".join(parts)


async def handle(
    session_id: str,
    message: str,
    *,
    mission_id: str,
    session_service: SessionServiceProtocol,
    event_bus: EventBusProtocol = NoOpEventBus(),
    channel: str = "api",
    sender_id: str | None = None,
    mission_brief: str | None = None,
    db_session: Any | None = None,
    skip_persistence: bool = False,
) -> AsyncIterator[SessionEvent]:
    """Universal streaming mission control entry point.

    Every conversation happens within a mission — mission_id is required.
    Mission context is injected into the agent's first message so it
    knows what mission it's operating in.

    Simple requests: existing direct-agent path (Plan 12).
    Complex requests: routed to dispatch via handle_mission() (Plan 13).
    A request is complex if mission_brief is explicitly provided.

    Yields SessionEvent instances as the agent works.
    Error handling yields events instead of throwing — the stream
    always terminates cleanly.
    """
    sid = uuid.UUID(session_id) if not isinstance(session_id, uuid.UUID) else session_id
    source = "mission_control"

    # Complex request — route to dispatch loop
    if mission_brief is not None:
        try:
            outcome = await handle_mission(
                mission_run_id=f"mission-{session_id}",
                mission_brief=mission_brief,
                session_service=session_service,
                event_bus=event_bus,
                session_id=session_id,
            )
            yield AgentResponseCompleteEvent(
                session_id=sid,
                source=source,
                agent_id="mission_control",
                full_content=outcome.model_dump_json(),
                metadata={"mission_status": outcome.status},
            )
        except Exception as exc:
            logger.error("Mission dispatch error", extra={"mission_id": mission_id}, exc_info=True)
            yield AgentResponseCompleteEvent(
                session_id=sid,
                source=source,
                agent_id="mission_control",
                full_content=str(exc),
                metadata={"error": True},
            )
        return

    agent_name = "unknown"
    try:
        # 1. Validate session exists
        session = await session_service.get_session(session_id)

        # 2. Enforce budget
        model_str = ""
        try:
            agent_name = _resolve_agent(session, message)
            agent_config = get_registry().get(agent_name)
            model_str = _get_model_name(agent_config.model)
            estimated = estimate_cost(len(message) * 4, model_str)
            await session_service.enforce_budget(session_id, estimated_cost=estimated)
        except Exception as budget_err:
            if isinstance(budget_err, BudgetExceededError):
                yield CostUpdateEvent(
                    session_id=sid,
                    source=source,
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=0.0,
                    cumulative_cost_usd=session.total_cost_usd,
                    budget_remaining_usd=0.0,
                    model=model_str,
                    metadata={"budget_exceeded": True},
                )
                return
            raise

        # 3. Engine routing — CLI engines use a separate handler (Plan 55b)
        engine = getattr(agent_config, "engine", "pydantic_ai")
        if engine != "pydantic_ai":
            from modules.backend.agents.mission_control.chat_cli_handler import handle_cli_chat
            async for event in handle_cli_chat(
                session_id, message,
                agent_name=agent_name,
                agent_config=agent_config,
                mission_id=mission_id,
                session_service=session_service,
                event_bus=event_bus,
                channel=channel,
                sender_id=sender_id,
                db_session=db_session,
                skip_persistence=skip_persistence,
            ):
                yield event
                await _publish(event_bus, event)
            return

        # 4. Yield UserMessageEvent
        user_event = UserMessageEvent(
            session_id=sid,
            source=source,
            content=message,
            channel=channel,
        )
        yield user_event
        await _publish(event_bus, user_event)

        # 5. Apply guardrails
        check_guardrails(message, agent_config)

        # 5. Yield AgentThinkingEvent
        thinking_event = AgentThinkingEvent(
            session_id=sid,
            source=source,
            agent_id=agent_name,
        )
        yield thinking_event
        await _publish(event_bus, thinking_event)

        # 6. Build agent and load history
        registry = get_registry()
        model = _build_model(agent_config.model)
        agent = registry.get_instance(agent_name, model)
        deps = _build_agent_deps(agent_name, agent_config, session_id, mission_id=mission_id, db_session=db_session)
        limits = _get_usage_limits(agent_name)

        # Build model settings (enables thinking when agent config supports it)
        model_settings = build_model_settings(agent_config)

        # Load conversation history
        history_messages, _ = await session_service.get_messages(session_id, limit=100)
        model_history = session_messages_to_model_history(history_messages)

        # Inject mission context on first turn so the agent knows
        # what mission it's operating in
        if not model_history:
            message = await _prepend_mission_context(mission_id, message)

        # 7. Execute agent with full tool-call support
        #
        # Uses agent.run() with event_stream_handler instead of
        # run_stream(). This ensures tool-using agents (like the
        # Mission Director) complete the full tool→LLM→response
        # cycle. run_stream stops at the first text output.
        import asyncio as _asyncio
        from pydantic_ai.messages import (
            PartDeltaEvent,
            PartStartEvent,
            TextPart,
            FunctionToolCallEvent,
            FunctionToolResultEvent,
            TextPartDelta,
            ThinkingPartDelta,
        )

        full_content = ""
        input_tokens = 0
        output_tokens = 0
        cost_usd = 0.0
        thinking_parts: list[str] = []
        event_queue: _asyncio.Queue[SessionEvent | None] = _asyncio.Queue()

        # Plan 56 Phase A: Create a streaming message placeholder so content
        # is persisted incrementally. If the SSE drops, the data is in the DB.
        streaming_msg_id: str | None = None
        _last_flush_len = 0
        _FLUSH_INTERVAL = 500  # flush every 500 chars
        try:
            streaming_msg_id = await session_service.create_streaming_message(
                session_id, sender_id=agent_name,
            )
        except Exception:
            logger.debug("Failed to create streaming message placeholder", exc_info=True)

        async def _stream_handler(ctx, events):
            """Callback for agent.run() — pushes SessionEvents to queue."""
            async for event in events:
                if isinstance(event, PartStartEvent):
                    # PartStartEvent carries the first chunk of a text
                    # part — PydanticAI does not emit it as a
                    # PartDeltaEvent, so we capture it here.
                    part = event.part
                    if isinstance(part, TextPart) and part.content:
                        chunk_event = AgentResponseChunkEvent(
                            session_id=sid,
                            source=source,
                            agent_id=agent_name,
                            content=part.content,
                        )
                        await event_queue.put(chunk_event)
                elif isinstance(event, PartDeltaEvent):
                    delta = event.delta
                    if isinstance(delta, TextPartDelta):
                        chunk_event = AgentResponseChunkEvent(
                            session_id=sid,
                            source=source,
                            agent_id=agent_name,
                            content=delta.content_delta,
                        )
                        await event_queue.put(chunk_event)
                    elif isinstance(delta, ThinkingPartDelta):
                        if delta.content_delta:
                            thinking_parts.append(delta.content_delta)
                            thinking_event = AgentResponseChunkEvent(
                                session_id=sid,
                                source=source,
                                agent_id=agent_name,
                                content=delta.content_delta,
                                metadata={"thinking": True},
                            )
                            await event_queue.put(thinking_event)
                elif isinstance(event, FunctionToolCallEvent):
                    tool_event = AgentToolCallEvent(
                        session_id=sid,
                        source=source,
                        agent_id=agent_name,
                        tool_name=event.part.tool_name,
                        tool_args={"raw": str(event.part.args) if event.part.args else ""},
                        tool_call_id=event.tool_call_id or "",
                    )
                    await event_queue.put(tool_event)
                elif isinstance(event, FunctionToolResultEvent):
                    result_str = str(event.content) if event.content else "ok"
                    status = "error" if "error" in result_str.lower()[:50] else "success"
                    result_event = AgentToolResultEvent(
                        session_id=sid,
                        source=source,
                        agent_id=agent_name,
                        tool_name=event.tool_call_id or "unknown",
                        tool_call_id=event.tool_call_id or "",
                        result=result_str[:200],
                        status=status,
                    )
                    await event_queue.put(result_event)

        async def _run_agent():
            """Run agent in background task, signal completion via None."""
            try:
                result = await agent.run(
                    message,
                    message_history=model_history or None,
                    deps=deps,
                    usage_limits=limits,
                    model_settings=model_settings,
                    event_stream_handler=_stream_handler,
                )
                return result
            finally:
                await event_queue.put(None)  # sentinel

        # Start agent in background, yield events as they arrive
        agent_task = _asyncio.create_task(_run_agent())

        while True:
            event = await event_queue.get()
            if event is None:
                break
            if isinstance(event, AgentResponseChunkEvent) and not event.metadata.get("thinking"):
                full_content += event.content
                # Incremental flush — persist every _FLUSH_INTERVAL chars
                if (
                    streaming_msg_id
                    and len(full_content) - _last_flush_len >= _FLUSH_INTERVAL
                ):
                    try:
                        await session_service.update_streaming_content(
                            streaming_msg_id, full_content,
                        )
                        _last_flush_len = len(full_content)
                    except Exception:
                        pass  # best-effort flush
            yield event
            await _publish(event_bus, event)

        # Await agent result for usage stats
        result = await agent_task
        usage = result.usage()
        from modules.backend.agents.mission_control.helpers.cost_recorder import extract_usage, record_llm_call
        fields = extract_usage(usage)
        cost_usd = compute_cost_usd(
            fields["input_tokens"], fields["output_tokens"], model_str,
            cache_read_tokens=fields["cache_read_tokens"],
            cache_write_1h_tokens=fields["cache_write_tokens"],
            thinking_tokens=fields["thinking_tokens"],
        )

        # Record to llm_calls table (Plan 60 §0.7)
        try:
            await record_llm_call(
                session_id=str(sid), mission_id=mission_id,
                agent_name=agent_name, agent_role=agent_config.agent_type,
                model=model_str, usage=usage, cost_usd=cost_usd,
                tool_count=len(agent_config.tools),
            )
        except Exception:
            logger.warning(
                "Failed to record LLM call for %s — cost data will be missing",
                agent_name, exc_info=True,
            )

        # Chunks are authoritative — they capture all text across all
        # turns (including the first token from PartStartEvent). Only
        # fall back to result.output for structured-output agents that
        # don't stream text chunks (e.g. VerificationEvaluation).
        if not full_content:
            output = result.output
            if isinstance(output, str) and output:
                full_content = output
            elif hasattr(output, "model_dump_json"):
                full_content = output.model_dump_json()
            elif output is not None and str(output):
                full_content = str(output)

        # 8. Yield complete event
        metadata: dict[str, Any] = {}
        if thinking_parts:
            metadata["thinking"] = "\n\n".join(thinking_parts)

        complete_event = AgentResponseCompleteEvent(
            session_id=sid,
            source=source,
            agent_id=agent_name,
            full_content=full_content,
            input_tokens=fields["input_tokens"],
            output_tokens=fields["output_tokens"],
            cost_usd=cost_usd,
            model=model_str,
            metadata=metadata,
        )
        yield complete_event
        await _publish(event_bus, complete_event)

        # 9. Update session cost
        try:
            await session_service.update_cost(
                session_id,
                input_tokens=fields["input_tokens"],
                output_tokens=fields["output_tokens"],
                cost_usd=cost_usd,
            )
        except (SQLAlchemyError, ApplicationError):
            logger.warning("Failed to update session cost", extra={"mission_id": mission_id}, exc_info=True)

        # 10. Yield cost update event
        updated_session = await session_service.get_session(session_id)
        budget_remaining = None
        if updated_session.cost_budget_usd is not None:
            budget_remaining = max(0.0, updated_session.cost_budget_usd - updated_session.total_cost_usd)

        cost_event = CostUpdateEvent(
            session_id=sid,
            source=source,
            input_tokens=fields["input_tokens"],
            output_tokens=fields["output_tokens"],
            cost_usd=cost_usd,
            cumulative_cost_usd=updated_session.total_cost_usd,
            budget_remaining_usd=budget_remaining,
            model=model_str,
        )
        yield cost_event
        await _publish(event_bus, cost_event)

        # 11. Persist messages
        # When skip_persistence is True (Temporal path), the user message
        # was already persisted by persist_user_message activity — only
        # persist the assistant response here.
        if not skip_persistence:
            await _persist_messages(
                session_service, session_id,
                [SessionMessageCreate(role="user", content=message, sender_id=sender_id)],
            )

        # Finalize the streaming message with final content and LLM metadata,
        # or fall back to creating a new message if streaming wasn't set up.
        if streaming_msg_id:
            try:
                await session_service.finalize_streaming_message(
                    streaming_msg_id,
                    full_content,
                    model=model_str,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost_usd,
                    thinking="\n\n".join(thinking_parts) if thinking_parts else None,
                )
            except Exception:
                logger.warning("Failed to finalize streaming message", extra={"mission_id": mission_id}, exc_info=True)
        else:
            await _persist_messages(
                session_service, session_id,
                [SessionMessageCreate(
                    role="assistant",
                    content=full_content,
                    sender_id=agent_name,
                    model=model_str,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost_usd,
                    thinking="\n\n".join(thinking_parts) if thinking_parts else None,
                )],
            )

        # 11b. Persist artifact + emit SSE event (Plan 43 chat path)
        # Only for substantive, non-error responses with a mission context.
        is_error = metadata.get("error") is True
        is_substantive = len(full_content) > 100
        if mission_id and is_substantive and not is_error:
            # Derive a title from the first non-empty line of content
            _title_line = next(
                (ln.lstrip("#").strip() for ln in full_content.splitlines() if ln.strip()),
                "Director response",
            )
            _artifact_title = _title_line[:120] if len(_title_line) > 120 else _title_line

            # SSE event — triggers live artifact panel update
            try:
                artifact_event = MissionArtifactFoundEvent(
                    session_id=sid,
                    source=source,
                    mission_id=mission_id,
                    agent_id=agent_name,
                    artifact_type="response",
                    title=_artifact_title,
                    content=full_content[:3000],
                    content_type="markdown",
                )
                yield artifact_event
                await _publish(event_bus, artifact_event)
            except Exception:
                logger.debug("Failed to emit artifact event", exc_info=True)

            # DB persistence — survives page refresh
            if db_session is not None:
                try:
                    from modules.backend.services.mission_artifact import MissionArtifactService
                    artifact_svc = MissionArtifactService(db_session)
                    await artifact_svc.create_artifact(
                        mission_id=mission_id,
                        agent_id=agent_name,
                        title=_artifact_title,
                        content_text=full_content,
                        artifact_type="response",
                        content_type="markdown",
                    )
                except Exception:
                    logger.debug("Failed to persist chat artifact", exc_info=True)

        # 12. Touch activity
        try:
            await session_service.touch_activity(session_id)
        except (SQLAlchemyError, ApplicationError):
            logger.debug("Failed to touch session activity", exc_info=True)

        # 13. Session memory compression (Plan 57 Phase C)
        try:
            from modules.backend.services.session_memory import SessionMemoryService
            mem_svc = SessionMemoryService(session_service._session)
            await mem_svc.compress_if_needed(session_id)
        except Exception:
            logger.debug("Session memory compression skipped", exc_info=True)

    except Exception as exc:
        logger.error(
            "Agent execution error",
            extra={"session_id": session_id, "agent_id": agent_name, "error": str(exc), "mission_id": mission_id},
            exc_info=True,
        )
        # Yield error event so the stream terminates cleanly
        yield AgentResponseCompleteEvent(
            session_id=sid,
            source=source,
            agent_id=agent_name,
            full_content=str(exc),
            metadata={"error": True},
        )
        # Persist the error — finalize the streaming message as failed,
        # or create a new error message if streaming wasn't set up.
        if streaming_msg_id:
            try:
                await session_service.finalize_streaming_message(
                    streaming_msg_id,
                    full_content or str(exc),
                    status="failed",
                )
            except Exception:
                pass  # best-effort
        else:
            error_create = SessionMessageCreate(
                role="assistant",
                content=str(exc),
                sender_id=agent_name,
            )
            await _persist_messages(session_service, session_id, [error_create])
        # Emit system error event to mission channel
        if mission_id:
            from modules.backend.events.types import SystemEvent
            await _publish(event_bus, SystemEvent(
                session_id=sid,
                source=agent_name,
                level="error",
                message=f"Agent error: {str(exc)[:200]}",
                mission_id=mission_id,
            ))
            try:
                await event_bus.publish_to_mission(mission_id, SystemEvent(
                    session_id=sid,
                    source=agent_name,
                    level="error",
                    message=f"Agent error: {str(exc)[:200]}",
                    mission_id=mission_id,
                ))
            except Exception:
                pass  # best-effort


async def collect(session_id: str, message: str, **kwargs: Any) -> CollectResult:
    """Collect all events from handle(), return a typed result dict."""
    agent_name = ""
    output = ""
    cost_usd = 0.0
    thinking: str | None = None

    async for event in handle(session_id, message, **kwargs):
        if isinstance(event, AgentResponseCompleteEvent):
            agent_name = event.agent_id
            output = event.full_content
            cost_usd = event.cost_usd
            if event.metadata and "thinking" in event.metadata:
                thinking = event.metadata["thinking"]
        elif isinstance(event, AgentResponseChunkEvent):
            pass  # chunks are already accumulated in full_content

    return CollectResult(
        agent_name=agent_name,
        output=output,
        cost_usd=cost_usd,
        session_id=session_id,
        thinking=thinking,
    )


# =============================================================================
# Mission dispatch — multi-agent mission execution (Plan 13)
# =============================================================================
# handle_mission() has been extracted to mission_dispatch.py (Plan 38 §2.1).
# It is re-exported above via:
#   from modules.backend.agents.mission_control.mission_dispatch import handle_mission
