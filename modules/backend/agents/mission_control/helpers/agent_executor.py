"""Agent executor — the execute_agent closure and planning agent caller."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from modules.backend.agents.mission_control.roster import Roster

from pydantic_ai import UsageLimits, UserError

from modules.backend.agents.mission_control.cost import compute_cost_usd
from modules.backend.agents.mission_control.helpers.agent_setup import (
    _build_agent_deps,
    _import_agent_module,
)
from modules.backend.agents.mission_control.helpers.cost_recorder import (
    extract_usage,
    record_llm_call,
)
from modules.backend.agents.mission_control.helpers.event_emitter import _emit, _emit_tool_events
from modules.backend.agents.mission_control.helpers.model_builder import (
    _build_model,
    _get_model_name,
    build_model_settings,
)
from modules.backend.agents.mission_control.helpers.prompt_builder import (
    _build_planning_prompt,
    _build_roster_prompt,
)
from modules.backend.agents.mission_control.models import EventBusProtocol, ExecuteAgentFn
from modules.backend.agents.mission_control.registry import get_registry
from modules.backend.core.config import find_project_root
from modules.backend.core.exceptions import ValidationError
from modules.backend.core.logging import get_logger
from modules.backend.events.types import (
    AgentResponseChunkEvent,
    AgentResponseCompleteEvent,
    AgentThinkingEvent,
    AgentToolCallEvent,
    AgentToolResultEvent,
    CostUpdateEvent,
    MissionArtifactFoundEvent,
    SystemEvent,
)

logger = get_logger(__name__)


def _make_agent_executor(
    event_bus: EventBusProtocol,
    *,
    session_id: str,
    mission_id: str,
    environment_handle: object | None = None,
    current_user_id: str | None = None,
    mission_run_id: str | None = None,
) -> ExecuteAgentFn:
    """Create the execute_agent_fn closure for the dispatch loop.

    mission_run_id tags every ledger row so the run's cost is summed at
    finalise; None when the dispatch is not part of a mission run.
    """
    cumulative_cost_usd = 0.0

    async def execute_agent(
        agent_name: str,
        instructions: str,
        inputs: dict,
        usage_limits: UsageLimits,
    ) -> dict:
        """Execute a single agent with streaming event emission."""
        nonlocal cumulative_cost_usd

        registry = get_registry()
        agent_config = registry.get(agent_name)
        if agent_config is None:
            raise ValidationError(f"Agent '{agent_name}' not found in registry")

        module = _import_agent_module(agent_name)
        model = _build_model(agent_config.model)
        agent = module.create_agent(model, tool_names=agent_config.tools or [])
        model_settings = build_model_settings(agent_config)
        deps = _build_agent_deps(agent_name, agent_config)

        # Inject environment handle and redirect project_root for user-tier agents.
        # Platform/system agents always resolve to local mode (enforced by YAML schema
        # validator), so environment_handle is None for them — this block is never
        # entered.  The explicit tier check below is a second line of defence.
        agent_tier = agent_config.invocation.tier  # "user", "platform", "system"
        effective_handle = (
            environment_handle if environment_handle is not None and agent_tier == "user" else None
        )

        # ── Engine routing (Plan 55) ────────────────────────────────
        engine = getattr(agent_config, "engine", "pydantic_ai")

        if engine != "pydantic_ai":
            from modules.backend.agents.mission_control.helpers.cli_executor import (
                execute_claude_code,
                execute_codex,
                execute_copilot,
            )
            from modules.backend.agents.mission_control.helpers.prompt_builder import (
                load_agent_system_prompt,
            )

            system_prompt = load_agent_system_prompt(agent_name)
            working_dir = None
            if effective_handle is not None:
                working_dir = getattr(effective_handle, "host_working_dir", None)

            engine_fn = {
                "claude_code": execute_claude_code,
                "codex": execute_codex,
                "copilot": execute_copilot,
            }[engine]

            engine_kwargs: dict = {
                "agent_name": agent_name,
                "instructions": instructions,
                "inputs": inputs,
                "system_prompt": system_prompt,
                "working_dir": working_dir,
                "event_bus": event_bus,
                "session_id": session_id,
            }
            if engine == "claude_code":
                if getattr(agent_config, "effort", None):
                    engine_kwargs["effort"] = agent_config.effort
                engine_kwargs["scope_read"] = agent_config.scope.read
                engine_kwargs["scope_write"] = agent_config.scope.write

            result = await engine_fn(**engine_kwargs)
            cumulative_cost_usd += result.get("_meta", {}).get("cost_usd", 0.0)
            return result

        # ── Existing PydanticAI path (unchanged) ──────────────────

        if effective_handle is not None:
            deps.environment_handle = effective_handle
            # Redirect filesystem root to the isolated host-side worktree so that
            # all agent tool calls (read_file, list_files, write_file) operate on
            # the worktree and never touch the main repo.
            if (
                hasattr(effective_handle, "host_working_dir")
                and effective_handle.host_working_dir is not None
            ):
                deps.project_root = effective_handle.host_working_dir

            # Resolve @workspace paths for security agents — evidence_path
            # must point to the container's /workspace, not create @workspace/
            # in the project root.
            if hasattr(deps, "evidence_path") and deps.evidence_path.startswith("@workspace"):
                deps.evidence_path = deps.evidence_path.replace(
                    "@workspace",
                    str(effective_handle.working_dir),
                )

        if hasattr(deps, "on_progress") and event_bus is not None:
            import asyncio as _asyncio

            def _on_progress(evt: dict) -> None:
                tool = evt.get("tool", "")
                detail = evt.get("detail", "")
                evt_type = evt.get("type", "")
                if evt_type == "tool_start":
                    _asyncio.ensure_future(
                        _emit(
                            event_bus,
                            AgentToolCallEvent,
                            session_id=session_id,
                            source=f"dispatch:{mission_id}",
                            agent_id=agent_name,
                            tool_name=tool,
                            tool_args={"detail": detail} if detail else {},
                        )
                    )
                elif evt_type == "tool_done":
                    _asyncio.ensure_future(
                        _emit(
                            event_bus,
                            AgentToolResultEvent,
                            session_id=session_id,
                            source=f"dispatch:{mission_id}",
                            agent_id=agent_name,
                            tool_name=tool,
                            tool_call_id="",
                            result=detail or None,
                        )
                    )

            deps.on_progress = _on_progress

        await _emit(
            event_bus,
            AgentThinkingEvent,
            session_id=session_id,
            source=f"dispatch:{mission_id}",
            agent_id=agent_name,
        )

        user_message = instructions
        if inputs:
            user_message = (
                f"{instructions}\n\n"
                f"## Inputs\n\n```json\n"
                f"{json.dumps(inputs, indent=2, default=str)}\n```"
            )

        hook_data = None
        if hasattr(module, "pre_execute"):
            try:
                user_message, hook_data = await module.pre_execute(user_message, deps)
            except Exception:
                # best-effort — the agent still runs with the unmodified
                # user_message; only the hook's pre-processing is skipped.
                logger.warning("pre_execute hook failed for %s", agent_name, exc_info=True)

        source = f"dispatch:{mission_id}"

        try:
            async with agent.run_stream(
                user_message,
                deps=deps,
                usage_limits=usage_limits,
                model_settings=model_settings,
            ) as stream:
                try:
                    async for text in stream.stream_text(delta=True):
                        await _emit(
                            event_bus,
                            AgentResponseChunkEvent,
                            session_id=session_id,
                            source=source,
                            agent_id=agent_name,
                            content=text,
                        )
                except UserError:
                    logger.debug(
                        "Structured output agent — no text stream", extra={"agent_name": agent_name}
                    )

                output = await stream.get_output()
                await _emit_tool_events(
                    event_bus,
                    stream,
                    session_id=session_id,
                    source=source,
                    agent_id=agent_name,
                )
                usage = stream.usage()
        except Exception as exc:
            await _emit(
                event_bus,
                SystemEvent,
                session_id=session_id,
                source=source,
                level="error",
                message=f"{agent_name} failed: {exc}",
                mission_id=mission_id,
            )
            raise

        # Trace — log full message history at DEBUG level and optionally
        # emit to the mission event bus for frontend console visibility.
        from modules.backend.core.agent_trace import trace_and_emit

        await trace_and_emit(
            agent_name,
            stream,
            mission_id=mission_id,
            session_id=session_id,
            model=_get_model_name(agent_config.model),
            event_bus=event_bus,
        )

        if hook_data is not None and hasattr(module, "post_execute"):
            try:
                module.post_execute(output, hook_data)
            except Exception:
                # best-effort — the agent already produced its output;
                # only the hook's post-processing is skipped.
                logger.warning(
                    "post_execute hook failed for %s",
                    agent_name,
                    extra={"mission_id": mission_id},
                    exc_info=True,
                )

        if hasattr(output, "model_dump"):
            output_dict = {"output": output.model_dump()}
        elif isinstance(output, dict):
            output_dict = {"output": output}
        else:
            output_dict = {"output": str(output)}

        # Emit artifact SSE event only for agents that declare
        # produces_artifact — stops the firehose of junk artifacts
        # from every agent's summary/result field.
        if agent_config.produces_artifact:
            _inner = output_dict.get("output", {})
            _inner = _inner if isinstance(_inner, dict) else {}
            _artifact_content = (
                _inner.get("report_markdown") or _inner.get("summary") or _inner.get("result")
            )
            if isinstance(_artifact_content, str) and _artifact_content.strip():
                _title = (
                    _inner.get("title") or _inner.get("report_title") or f"{agent_name} — output"
                )
                await _emit(
                    event_bus,
                    MissionArtifactFoundEvent,
                    session_id=session_id,
                    source=f"dispatch:{mission_id}",
                    mission_id=mission_id,
                    agent_id=agent_name,
                    artifact_type=agent_config.artifact_type or "report",
                    title=_title,
                    content=_artifact_content[:3000],
                    content_type="markdown",
                )

        fields = extract_usage(usage)
        model_name = _get_model_name(agent_config.model)
        cost_usd = compute_cost_usd(
            fields["input_tokens"],
            fields["output_tokens"],
            model_name,
            cache_read_tokens=fields["cache_read_tokens"],
            cache_write_1h_tokens=fields["cache_write_tokens"],
            thinking_tokens=fields["thinking_tokens"],
        )
        cumulative_cost_usd += cost_usd

        # Record to llm_calls table (Plan 60 §0.7)
        try:
            await record_llm_call(
                session_id=session_id,
                mission_id=mission_id,
                agent_name=agent_name,
                agent_role=agent_config.agent_type,
                model=model_name,
                usage=usage,
                cost_usd=cost_usd,
                latency_ms=0,
                tool_count=len(agent_config.tools),
                mission_run_id=mission_run_id,
            )
        except Exception:
            logger.warning(
                "Failed to record LLM call for %s — cost data will be missing",
                agent_name,
                exc_info=True,
                extra={"mission_id": mission_id},
            )
            await _emit(
                event_bus,
                SystemEvent,
                session_id=session_id,
                source=f"dispatch:{mission_id}",
                level="warning",
                message=f"Cost tracking failed for {agent_name} — budget data may be inaccurate",
                mission_id=mission_id,
            )

        output_dict["_meta"] = {
            "input_tokens": fields["input_tokens"],
            "output_tokens": fields["output_tokens"],
            "thinking_tokens": fields["thinking_tokens"],
            "cost_usd": cost_usd,
        }

        full_content = json.dumps(output_dict, default=str)
        if len(full_content) > 2000:
            full_content = full_content[:2000] + "…"

        await _emit(
            event_bus,
            AgentResponseCompleteEvent,
            session_id=session_id,
            source=f"dispatch:{mission_id}",
            agent_id=agent_name,
            full_content=full_content,
            input_tokens=fields["input_tokens"],
            output_tokens=fields["output_tokens"],
            cost_usd=cost_usd,
            model=model_name,
        )

        await _emit(
            event_bus,
            CostUpdateEvent,
            session_id=session_id,
            source=f"dispatch:{mission_id}",
            input_tokens=fields["input_tokens"],
            output_tokens=fields["output_tokens"],
            cost_usd=cost_usd,
            cumulative_cost_usd=cumulative_cost_usd,
            model=model_name,
            source_event_type="agent.response.complete",
        )

        return output_dict

    return execute_agent


def _format_plan_summary(plan_json: dict) -> str:
    """Format a TaskPlan dict as a markdown summary for the chat sidebar."""
    tasks = plan_json.get("tasks", [])
    version = plan_json.get("version", "?")
    summary = plan_json.get("summary", "")
    cost = plan_json.get("estimated_cost_usd", 0)
    duration = plan_json.get("estimated_duration_seconds", 0)

    lines = [f"## Task Plan v{version} — {summary}", ""]
    lines.append("| # | Task ID | Description | Agent | Dependencies |")
    lines.append("|---|---------|-------------|-------|-------------|")
    for i, task in enumerate(tasks, 1):
        tid = task.get("task_id", "?")
        desc = task.get("description", "")[:50]
        agent = task.get("agent", "?")
        deps = ", ".join(task.get("dependencies", [])) or "—"
        lines.append(f"| {i} | {tid} | {desc} | {agent} | {deps} |")
    lines.append("")
    duration_min = duration / 60 if duration else 0
    lines.append(f"**Estimated cost:** ${cost:.2f} | **Duration:** ~{duration_min:.0f} min")
    return "\n".join(lines)


async def _call_planning_agent(
    prompt: str,
    roster: "Roster",
    upstream_context: dict | None,
    event_bus: "EventBusProtocol | None" = None,
    session_id: str | None = None,
    *,
    current_plan: dict | None = None,
    refinement_instructions: str | None = None,
    mission_id: str | None = None,
    plan_version: int = 1,
    project_context: dict | None = None,
    recent_failures: list | None = None,
    mission_run_id: str | None = None,
) -> dict:
    """Call the Planning Agent using incremental tool calls (Plan 69).

    The agent builds the plan by calling tools (add_task, set_upstream_input,
    finalise_plan, etc.) instead of producing a monolithic JSON blob.
    Each tool has a trivially small schema — no grammar compiler limits.

    When `current_plan` is provided, the PlanBuildingSession is seeded
    with existing tasks (refinement mode).
    """
    import uuid as _uuid

    from pydantic_ai import UsageLimits

    from modules.backend.agents.deps.base import FileScope
    from modules.backend.agents.mission.planning.agent import PlanningAgentDeps, create_agent
    from modules.backend.agents.mission.planning.build_session import PlanBuildingSession
    from modules.backend.core.config import get_default_budget_usd

    project_root = find_project_root()

    registry = get_registry()
    planning_cfg = registry.get("mission.planning.agent")
    model = _build_model(planning_cfg.model)
    planning_model_settings = build_model_settings(planning_cfg)
    agent = create_agent(model)
    logger.info(
        "Planning agent instance created for dispatch",
        extra={
            "agent_id": id(agent),
            "tools": list(agent._function_toolset.tools.keys()),
            "mission_id": mission_id,
        },
    )

    roster_desc = _build_roster_prompt(roster)
    planning_prompt = _build_planning_prompt(
        mission_brief=prompt,
        mission_id=mission_id or "pending",
        roster_description=roster_desc,
        upstream_context=upstream_context,
        project_context=project_context,
        recent_failures=recent_failures,
        current_plan=current_plan,
        refinement_instructions=refinement_instructions,
        plan_version=plan_version,
    )

    # Build the incremental session
    build_session = PlanBuildingSession(
        mission_id=mission_id or "pending",
        version=plan_version,
        roster=roster,
        budget_usd=get_default_budget_usd(),
        current_plan=current_plan,
    )

    planning_agent_id = "mission.planning.agent"
    sid = _uuid.UUID(session_id) if session_id else _uuid.uuid4()

    deps = PlanningAgentDeps(
        project_root=project_root,
        scope=FileScope(read_paths=[], write_paths=[]),
        mission_brief=prompt,
        roster_description=roster_desc,
        upstream_context=upstream_context,
        build_session=build_session,
        event_bus=event_bus,
        session_id=str(sid),
        mission_id=mission_id,
    )

    if deps.build_session is None:
        raise ValueError(
            "_call_planning_agent: build_session is None before agent.run(). "
            "This should never happen — check PlanBuildingSession creation above."
        )

    if event_bus:
        await _emit(
            event_bus,
            AgentThinkingEvent,
            session_id=str(sid),
            source="mission_control",
            agent_id=planning_agent_id,
        )

    # Tool-based flow: agent.run() — the plan builds via tool calls,
    # not via text output.
    result = await agent.run(
        planning_prompt,
        deps=deps,
        model_settings=planning_model_settings,
        usage_limits=UsageLimits(request_limit=50),
    )
    usage = result.usage()

    # Trace — log full message history at DEBUG level
    from modules.backend.core.agent_trace import trace_and_emit

    await trace_and_emit(
        planning_agent_id,
        result,
        mission_id=mission_id,
        session_id=session_id,
        model=_get_model_name(planning_cfg.model),
        event_bus=event_bus,
    )

    # Extract thinking trace
    thinking_trace = None
    for msg in result.all_messages():
        for part in getattr(msg, "parts", []):
            if hasattr(part, "content") and hasattr(part, "part_kind"):
                if "thinking" in str(getattr(part, "part_kind", "")):
                    thinking_trace = part.content

    # Check the session produced a finalised plan
    if build_session.finalised_plan is None:
        task_count = len(build_session.tasks)
        logger.warning(
            "Planning Agent did not call finalise_plan",
            extra={
                "mission_id": mission_id,
                "tasks_added": task_count,
                "task_ids": list(build_session.tasks.keys()),
            },
        )
        raise ValueError(
            f"Planning Agent did not call finalise_plan. "
            f"{task_count} tasks added but plan was not finalised."
        )

    plan_dict = build_session.finalised_plan

    logger.info(
        "Planning agent produced TaskPlan",
        extra={
            "mission_id": mission_id,
            "task_count": len(plan_dict.get("tasks", [])),
            "task_plan": plan_dict,
        },
    )

    if event_bus:
        await _emit(
            event_bus,
            AgentResponseCompleteEvent,
            session_id=str(sid),
            source="mission_control",
            agent_id=planning_agent_id,
            full_content=f"Plan generated ({len(plan_dict.get('tasks', []))} tasks)",
        )

        if plan_dict.get("tasks"):
            from modules.backend.events.types import PlanCreatedEvent

            await event_bus.publish(
                PlanCreatedEvent(
                    session_id=sid,
                    source="mission_control",
                    plan_id=mission_id or "pending",
                    goal=plan_dict.get("summary", ""),
                    step_count=len(plan_dict["tasks"]),
                    metadata={
                        "plan_markdown": _format_plan_summary(plan_dict),
                        "task_plan": plan_dict,
                    },
                )
            )

    # Record planning agent cost
    try:
        fields = extract_usage(usage)
        model_name = _get_model_name(planning_cfg.model)
        planning_cost = compute_cost_usd(
            fields["input_tokens"],
            fields["output_tokens"],
            model_name,
            cache_read_tokens=fields["cache_read_tokens"],
            cache_write_1h_tokens=fields["cache_write_tokens"],
            thinking_tokens=fields["thinking_tokens"],
        )
        await record_llm_call(
            session_id=session_id,
            mission_id=mission_id,
            agent_name=planning_agent_id,
            agent_role=planning_cfg.agent_type,
            model=model_name,
            usage=usage,
            cost_usd=planning_cost,
            latency_ms=0,
            tool_count=len(build_session.tasks),
            mission_run_id=mission_run_id,
        )
    except Exception:
        logger.warning(
            "Failed to record planning agent LLM call",
            exc_info=True,
            extra={"mission_id": mission_id},
        )
        if event_bus is not None:
            await _emit(
                event_bus,
                SystemEvent,
                session_id=uuid.UUID(session_id) if session_id else uuid.uuid4(),
                source="mission_control:planning_agent",
                level="warning",
                message="Cost tracking failed for planning agent — budget data may be inaccurate",
                mission_id=mission_id,
            )

    return {
        "task_plan": plan_dict,
        "thinking_trace": thinking_trace,
        "usage": usage,
    }
