"""Agent executor — the execute_agent closure and planning agent caller."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from pydantic_ai import UsageLimits, UserError

from modules.backend.agents.mission_control.models import EventBusProtocol, ExecuteAgentFn
from modules.backend.agents.mission_control.registry import get_registry
from modules.backend.agents.mission_control.cost import compute_cost_usd
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
)

from modules.backend.agents.mission_control.helpers.agent_setup import _build_agent_deps, _import_agent_module
from modules.backend.agents.mission_control.helpers.event_emitter import _emit, _emit_tool_events
from modules.backend.agents.mission_control.helpers.model_builder import _build_model, _get_model_name
from modules.backend.agents.mission_control.helpers.prompt_builder import _build_planning_prompt, _build_roster_prompt

logger = get_logger(__name__)


def _make_agent_executor(
    event_bus: EventBusProtocol,
    *,
    session_id: str,
    mission_id: str,
    environment_handle: object | None = None,
    current_user_id: str | None = None,
) -> ExecuteAgentFn:
    """Create the execute_agent_fn closure for the dispatch loop."""
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
        agent = module.create_agent(model)
        deps = _build_agent_deps(agent_name, agent_config)

        # Inject environment handle and redirect project_root for user-tier agents.
        # Platform/system agents always resolve to local mode (enforced by YAML schema
        # validator), so environment_handle is None for them — this block is never
        # entered.  The explicit tier check below is a second line of defence.
        agent_tier = agent_config.invocation.tier  # "user", "platform", "system"
        effective_handle = (
            environment_handle
            if environment_handle is not None and agent_tier == "user"
            else None
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

        if hasattr(deps, 'on_progress') and event_bus is not None:
            import asyncio as _asyncio

            def _on_progress(evt: dict) -> None:
                tool = evt.get("tool", "")
                detail = evt.get("detail", "")
                evt_type = evt.get("type", "")
                if evt_type == "tool_start":
                    _asyncio.ensure_future(_emit(
                        event_bus, AgentToolCallEvent,
                        session_id=session_id,
                        source=f"dispatch:{mission_id}",
                        agent_id=agent_name,
                        tool_name=tool,
                        tool_args={"detail": detail} if detail else {},
                    ))
                elif evt_type == "tool_done":
                    _asyncio.ensure_future(_emit(
                        event_bus, AgentToolResultEvent,
                        session_id=session_id,
                        source=f"dispatch:{mission_id}",
                        agent_id=agent_name,
                        tool_name=tool,
                        tool_call_id="",
                        result=detail or None,
                    ))

            deps.on_progress = _on_progress

        await _emit(event_bus, AgentThinkingEvent,
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
                logger.warning("pre_execute hook failed for %s", agent_name, exc_info=True)

        source = f"dispatch:{mission_id}"

        async with agent.run_stream(
            user_message, deps=deps, usage_limits=usage_limits,
        ) as stream:
            try:
                async for text in stream.stream_text(delta=True):
                    await _emit(event_bus, AgentResponseChunkEvent,
                        session_id=session_id,
                        source=source,
                        agent_id=agent_name,
                        content=text,
                    )
            except UserError:
                pass  # Structured output agent — no text stream

            output = await stream.get_output()
            await _emit_tool_events(
                event_bus, stream,
                session_id=session_id,
                source=source,
                agent_id=agent_name,
            )
            usage = stream.usage()

        if hook_data is not None and hasattr(module, "post_execute"):
            try:
                module.post_execute(output, hook_data)
            except Exception:
                logger.warning("post_execute hook failed for %s", agent_name, extra={"mission_id": mission_id}, exc_info=True)

        if hasattr(output, "model_dump"):
            output_dict = output.model_dump()
        elif isinstance(output, dict):
            output_dict = output
        else:
            output_dict = {"result": str(output)}

        # Emit artifact if agent produced a meaningful textual result
        _artifact_content: str | None = None
        if isinstance(output_dict.get("summary"), str):
            _artifact_content = output_dict["summary"]
        elif isinstance(output_dict.get("result"), str):
            _artifact_content = output_dict["result"]
        if _artifact_content and _artifact_content.strip():
            await _emit(
                event_bus,
                MissionArtifactFoundEvent,
                session_id=session_id,
                source=f"dispatch:{mission_id}",
                mission_id=mission_id,
                agent_id=agent_name,
                artifact_type="report",
                title=f"{agent_name} — result",
                content=_artifact_content[:3000],
                content_type="markdown",
            )

        input_tokens = usage.input_tokens or 0
        output_tokens = usage.output_tokens or 0
        model_name = _get_model_name(agent_config.model)
        cost_usd = compute_cost_usd(input_tokens, output_tokens, model_name)
        cumulative_cost_usd += cost_usd

        output_dict["_meta"] = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "thinking_tokens": 0,
            "cost_usd": cost_usd,
        }

        full_content = json.dumps(output_dict, default=str)
        if len(full_content) > 2000:
            full_content = full_content[:2000] + "…"

        await _emit(event_bus, AgentResponseCompleteEvent,
            session_id=session_id,
            source=f"dispatch:{mission_id}",
            agent_id=agent_name,
            full_content=full_content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            model=model_name,
        )

        await _emit(event_bus, CostUpdateEvent,
            session_id=session_id,
            source=f"dispatch:{mission_id}",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            cumulative_cost_usd=cumulative_cost_usd,
            model=model_name,
            source_event_type="agent.response.complete",
        )

        return output_dict

    return execute_agent


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
) -> dict:
    """Call the Planning Agent and return the raw result.

    When `current_plan` and `refinement_instructions` are both provided,
    the Planning Agent operates in refinement mode: it's given the
    existing TaskPlan JSON + the user's change instructions and asked
    to produce a new plan that preserves task_ids where possible.
    Plan 42 §10.4 — this is the single refinement entry point.
    """
    import uuid as _uuid

    from modules.backend.agents.deps.base import FileScope
    from modules.backend.agents.system.planning.agent import (
        PlanningAgentDeps,
        create_agent,
        extract_task_plan_json,
    )
    from modules.backend.events.types import AgentResponseChunkEvent
    from modules.backend.services.code_map.loader import CodeMapLoader

    project_root = find_project_root()

    loader = CodeMapLoader(project_root)
    code_map = loader.ensure_fresh()

    registry = get_registry()
    planning_cfg = registry.get("system.planning.agent")
    model = _build_model(planning_cfg.model)
    agent = create_agent(model)

    roster_desc = _build_roster_prompt(roster)
    planning_prompt = _build_planning_prompt(
        mission_brief=prompt,
        mission_id=mission_id or "pending",
        roster_description=roster_desc,
        upstream_context=upstream_context,
        code_map=code_map,
        current_plan=current_plan,
        refinement_instructions=refinement_instructions,
    )

    deps = PlanningAgentDeps(
        project_root=project_root,
        scope=FileScope(read_paths=[], write_paths=[]),
        mission_brief=prompt,
        roster_description=roster_desc,
        upstream_context=upstream_context,
        code_map=code_map,
    )

    planning_agent_id = "system.planning.agent"
    sid = _uuid.UUID(session_id) if session_id else _uuid.uuid4()
    full_content = ""

    async with agent.run_stream(planning_prompt, deps=deps) as stream:
        async for text in stream.stream_text(delta=True):
            full_content += text
            if event_bus:
                await event_bus.publish(AgentResponseChunkEvent(
                    session_id=sid,
                    source="mission_control",
                    agent_id=planning_agent_id,
                    content=text,
                ))

        usage = stream.usage()

    plan_json = extract_task_plan_json(full_content)

    thinking_trace = None
    if hasattr(stream, "all_messages"):
        for msg in stream.all_messages():
            for part in getattr(msg, "parts", []):
                if hasattr(part, "content") and hasattr(part, "part_kind"):
                    if "thinking" in str(getattr(part, "part_kind", "")):
                        thinking_trace = part.content

    return {
        "task_plan": plan_json,
        "thinking_trace": thinking_trace,
        "usage": usage,
    }
