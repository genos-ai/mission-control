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
from modules.backend.agents.mission_control.dispatch import dispatch
from modules.backend.agents.mission_control.gate import GateReviewer
from modules.backend.agents.mission_control.persistence_bridge import persist_mission_results
from modules.backend.agents.mission_control.helpers import (
    _build_agent_deps,
    _build_model,
    _build_planning_prompt,
    _build_roster_prompt,
    _append_validation_feedback,
    _call_planning_agent,
    _emit_tool_events,
    _get_model_name,
    _get_usage_limits,
    _make_agent_executor,
    _persist_messages,
    _publish,
    _resolve_agent,
    assemble_instructions,
    build_deps_from_config,
)
from modules.backend.agents.mission_control.history import (
    session_messages_to_model_history,
)
from modules.backend.agents.mission_control.middleware import check_guardrails
from modules.backend.agents.mission_control.models import CollectResult, EventBusProtocol, NoOpEventBus
from modules.backend.core.protocols import SessionServiceProtocol
from modules.backend.agents.mission_control.outcome import ExecutionOutcome, ExecutionStatus
from modules.backend.agents.mission_control.plan_validator import validate_plan
from modules.backend.agents.mission_control.registry import get_registry
from modules.backend.agents.mission_control.roster import derive_roster_from_team
from modules.backend.core.logging import get_logger
from modules.backend.events.types import (
    AgentResponseChunkEvent,
    AgentResponseCompleteEvent,
    AgentThinkingEvent,
    AgentToolCallEvent,
    AgentToolResultEvent,
    CostUpdateEvent,
    PlanningPhaseEvent,
    SessionEvent,
    UserMessageEvent,
)
from modules.backend.schemas.session import SessionMessageCreate
from modules.backend.schemas.task_plan import TaskPlan
from modules.backend.services.context_assembler import ContextAssembler
from modules.backend.services.context_curator import ContextCurator
from modules.backend.services.history_query import HistoryQueryService
from modules.backend.services.mission_context import MissionContextManager

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
    from modules.backend.core.database import get_async_session
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
        async with get_async_session() as db:
            team_svc = MissionTeamService(db)
            members = await team_svc.list_team(mission_id)
            if members:
                from modules.backend.repositories.agent_catalog import AgentCatalogRepository
                catalog_repo = AgentCatalogRepository(db)
                team_lines = []
                for member in members:
                    entry = await catalog_repo.get_by_id_or_none(member.agent_catalog_id)
                    if not entry:
                        continue
                    line = f"  - {entry.agent_name}: {entry.description}"
                    if entry.tools:
                        line += f"\n    Tools: {', '.join(entry.tools)}"
                    scope = entry.scope or {}
                    read_paths = scope.get("read", [])
                    write_paths = scope.get("write", [])
                    if read_paths or write_paths:
                        access = []
                        if read_paths:
                            access.append(f"read: {', '.join(read_paths)}")
                        if write_paths:
                            access.append(f"write: {', '.join(write_paths)}")
                        line += f"\n    Access: {'; '.join(access)}"
                    if entry.keywords:
                        line += f"\n    Capabilities: {', '.join(entry.keywords)}"
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
            logger.error("Mission dispatch error", exc_info=True)
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

        # 3. Yield UserMessageEvent
        user_event = UserMessageEvent(
            session_id=sid,
            source=source,
            content=message,
            channel=channel,
        )
        yield user_event
        await _publish(event_bus, user_event)

        # 4. Apply guardrails
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

        async def _stream_handler(ctx, events):
            """Callback for agent.run() — pushes SessionEvents to queue."""
            async for event in events:
                if isinstance(event, PartDeltaEvent):
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
            if isinstance(event, AgentResponseChunkEvent):
                full_content += event.content
            yield event
            await _publish(event_bus, event)

        # Await agent result for usage stats
        result = await agent_task
        usage = result.usage()
        input_tokens = usage.input_tokens or 0
        output_tokens = usage.output_tokens or 0
        cost_usd = compute_cost_usd(input_tokens, output_tokens, model_str)

        # Always prefer result.output — streaming chunks miss the first token.
        # Chunks are used for live display only; result.output is authoritative.
        output = result.output
        if isinstance(output, str) and output:
            full_content = output
        elif hasattr(output, "model_dump_json"):
            full_content = output.model_dump_json()
        elif output is not None and str(output):
            full_content = str(output)
        # else: keep full_content from chunks as fallback

        # 8. Yield complete event
        metadata: dict[str, Any] = {}
        if thinking_parts:
            metadata["thinking"] = "\n\n".join(thinking_parts)

        complete_event = AgentResponseCompleteEvent(
            session_id=sid,
            source=source,
            agent_id=agent_name,
            full_content=full_content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
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
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
            )
        except (SQLAlchemyError, ApplicationError):
            logger.warning("Failed to update session cost", exc_info=True)

        # 10. Yield cost update event
        updated_session = await session_service.get_session(session_id)
        budget_remaining = None
        if updated_session.cost_budget_usd is not None:
            budget_remaining = max(0.0, updated_session.cost_budget_usd - updated_session.total_cost_usd)

        cost_event = CostUpdateEvent(
            session_id=sid,
            source=source,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            cumulative_cost_usd=updated_session.total_cost_usd,
            budget_remaining_usd=budget_remaining,
            model=model_str,
        )
        yield cost_event
        await _publish(event_bus, cost_event)

        # 11. Persist messages
        user_create = SessionMessageCreate(role="user", content=message, sender_id=sender_id)
        assistant_create = SessionMessageCreate(
            role="assistant",
            content=full_content,
            sender_id=agent_name,
            model=model_str,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )
        await _persist_messages(session_service, session_id, [user_create, assistant_create])

        # 12. Touch activity
        try:
            await session_service.touch_activity(session_id)
        except (SQLAlchemyError, ApplicationError):
            logger.debug("Failed to touch session activity", exc_info=True)

    except Exception as exc:
        logger.error(
            "Agent execution error",
            extra={"session_id": session_id, "agent_id": agent_name, "error": str(exc)},
        )
        logger.debug("Agent execution traceback", exc_info=True)
        # Yield a partial complete event so the stream always terminates cleanly
        yield AgentResponseCompleteEvent(
            session_id=sid,
            source=source,
            agent_id=agent_name,
            full_content=str(exc),
            metadata={"error": True},
        )


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


async def handle_mission(
    mission_run_id: str,
    mission_brief: str,
    *,
    session_service: SessionServiceProtocol,
    event_bus: EventBusProtocol = NoOpEventBus(),
    roster_name: str = "default",
    mission_budget_usd: float = 10.0,
    upstream_context: dict | None = None,
    session_id: str | None = None,
    mission_id: str | None = None,
    db_session: Any | None = None,
    gate: GateReviewer | None = None,
    execution_mode: str = "local",
) -> ExecutionOutcome:
    """Dispatch entry point for complex multi-agent missions.

    1. Load roster
    2. Call Planning Agent for task decomposition
    3. Validate TaskPlan against all 11 rules
    4. Execute dispatch loop
    5. Return ExecutionOutcome

    Simple requests continue through handle() from Plan 12.
    Complex requests (explicit mission_brief or matched workflow)
    route here.
    """
    if not mission_id or not db_session:
        raise ValueError(
            "mission_id and db_session are required for dispatch. "
            "Agents are resolved from the mission team in the database."
        )
    _plan_sid = uuid.UUID(session_id) if session_id else uuid.uuid4()

    async def _phase(step: str, message: str) -> None:
        await _publish(event_bus, PlanningPhaseEvent(
            session_id=_plan_sid, source="mission_control",
            step=step, message=message,
        ))

    await _phase("roster", "Deriving agent roster from team")
    roster = await derive_roster_from_team(mission_id, db_session)
    roster_description = _build_roster_prompt(roster)
    await _phase("roster", f"Roster ready — {len(roster.agents)} agents")

    # Create context services BEFORE planning so the planner gets PCD + history
    context_curator = None
    context_assembler = None
    project_context = None
    recent_failures = None

    if mission_id and db_session:
        pcd_manager = MissionContextManager(db_session)
        context_curator = ContextCurator(pcd_manager)
        history_service = HistoryQueryService(db_session)

        from modules.backend.core.config import find_project_root
        from modules.backend.services.code_map.loader import CodeMapLoader

        code_map_loader = CodeMapLoader(find_project_root())
        context_assembler = ContextAssembler(
            context_manager=pcd_manager,
            history_service=history_service,
            code_map_loader=code_map_loader,
        )

        # Load project context for the planner (non-fatal)
        await _phase("context", "Loading mission context")
        try:
            project_context = await context_curator.get_mission_context(mission_id)
        except (OSError, ValueError, RuntimeError):
            logger.warning(
                "Failed to load PCD for planning (non-fatal)",
                extra={"mission_id": mission_id},
                exc_info=True,
            )

        # Load recent failures so the planner can avoid repeating them
        try:
            recent_failures = await history_service.get_recent_failures(
                mission_id, limit=5,
            )
        except (OSError, ValueError, RuntimeError):
            logger.warning(
                "Failed to load failure history for planning (non-fatal)",
                extra={"mission_id": mission_id},
                exc_info=True,
            )
        await _phase("context", "Context assembled")

    # Build planning prompt WITH project context
    planning_prompt = _build_planning_prompt(
        mission_brief=mission_brief,
        mission_id=mission_run_id,
        roster_description=roster_description,
        upstream_context=upstream_context,
        project_context=project_context,
        recent_failures=recent_failures,
    )

    # Call Planning Agent (with retry on validation failure)
    plan = None
    thinking_trace = None
    max_planning_attempts = 3
    planning_agent_id = "system.planning.agent"

    # Emit planning started event
    await _phase("thinking", "Planning agent decomposing objective")
    await _publish(event_bus, AgentThinkingEvent(
        session_id=_plan_sid,
        source="mission_control",
        agent_id=planning_agent_id,
    ))

    last_error = ""
    for attempt in range(max_planning_attempts):
        try:
            planning_result = await _call_planning_agent(
                planning_prompt, roster, upstream_context,
                event_bus=event_bus, session_id=session_id,
            )
            thinking_trace = planning_result.get("thinking_trace")

            plan = TaskPlan.model_validate(planning_result["task_plan"])

            validation = validate_plan(plan, roster, mission_budget_usd)
            if validation.is_valid:
                break

            last_error = "; ".join(validation.errors)
            await _phase("error", f"Attempt {attempt + 1} failed: plan validation — {last_error}")
            logger.warning(
                "TaskPlan validation failed, retrying Planning Agent",
                extra={
                    "attempt": attempt + 1,
                    "errors": validation.errors,
                    "mission_id": mission_run_id,
                },
            )
            planning_prompt = _append_validation_feedback(
                planning_prompt, validation.errors,
            )
            plan = None

        except (ValueError, Exception) as e:
            last_error = str(e)
            await _phase("error", f"Attempt {attempt + 1} failed: {last_error}")
            logger.warning(
                "Planning Agent error, retrying",
                extra={
                    "attempt": attempt + 1,
                    "error": last_error,
                    "mission_id": mission_run_id,
                },
            )
            planning_prompt = _append_validation_feedback(
                planning_prompt, [last_error],
            )

    # Emit planning complete event
    _sid = uuid.UUID(session_id) if session_id else uuid.uuid4()
    if plan is not None:
        await _publish(event_bus, AgentResponseCompleteEvent(
            session_id=_sid,
            source="mission_control",
            agent_id=planning_agent_id,
            full_content=f"Plan created: {len(plan.tasks)} tasks",
        ))
    else:
        await _publish(event_bus, AgentResponseCompleteEvent(
            session_id=_sid,
            source="mission_control",
            agent_id=planning_agent_id,
            full_content=last_error or "Planning failed after retries",
            metadata={"error": True},
        ))
        return ExecutionOutcome(
            mission_id=mission_run_id,
            status=ExecutionStatus.FAILED,
            planning_trace_reference=thinking_trace,
        )

    # Provision execution environment if non-local
    # Container persists across executions within the mission — get or create.
    env_handle = None
    if execution_mode != "local":
        try:
            from modules.backend.services.execution_environment import (
                ExecutionEnvironmentService,
            )
            from modules.backend.services.container_backend import ContainerBackend
            from modules.backend.core.config import find_project_root

            env_service = ExecutionEnvironmentService(db_session=db_session)
            env_service.register_backend("container", ContainerBackend())

            repo_root = str(find_project_root())
            env_handle = await env_service.get_or_create_for_mission(
                mission_id=mission_id or mission_run_id,
                mode=execution_mode,
                config={
                    "image": "code-workspace:latest",
                    "git_aware": True,
                    "repo_root": repo_root,
                    "branch_name": f"agent/{(mission_id or mission_run_id)[:8]}/dispatch",
                },
            )
            logger.info(
                "Execution environment ready",
                extra={
                    "mode": execution_mode,
                    "environment_id": env_handle.environment_id,
                    "reused": env_handle.metadata.get("execution_count", 0) > 1,
                },
            )
        except Exception:
            logger.warning(
                "Failed to provision execution environment, falling back to local",
                exc_info=True,
            )
            env_handle = None

    # Execute dispatch loop (context services already created above)
    # Note: container is NOT cleaned up here — it persists for the next
    # execution within this mission. Cleanup happens on:
    #   - mission archive/delete
    #   - idle timeout (cleanup_stale_environments scheduled task)
    #   - explicit admin command
    outcome = await dispatch(
        plan=plan,
        roster=roster,
        execute_agent_fn=_make_agent_executor(
            event_bus,
            session_id=session_id or mission_run_id,
            mission_id=mission_run_id,
            environment_handle=env_handle,
        ),
        mission_budget_usd=mission_budget_usd,
        gate=gate,
        mission_id=mission_id,
        context_curator=context_curator,
        context_assembler=context_assembler,
        event_bus=event_bus,
        session_id=session_id or mission_run_id,
        execution_mode=execution_mode,
    )

    outcome.planning_trace_reference = thinking_trace
    outcome.task_plan_reference = plan.model_dump_json()

    # Best-effort synthesis — generate human narrative summary
    from modules.backend.services.synthesis import summarize_outcome

    outcome.summary = await summarize_outcome(outcome)

    # Best-effort persistence — does not block or fail the mission
    if db_session is not None:
        await persist_mission_results(
            outcome,
            session_id=session_id or mission_run_id,
            roster_name=roster_name,
            task_plan_json=plan.model_dump(),
            thinking_trace=thinking_trace,
            mission_id=mission_id,
            db_session=db_session,
        )

    return outcome
