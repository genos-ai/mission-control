"""Planning Agent tools — incremental plan building via tool calls.

8 mutation tools + register function. Each tool delegates to
PlanBuildingSession methods. Schemas are trivially small — no
grammar compiler limits, no normaliser layers. Plan 69.

Plan 72: tools emit AgentToolCallEvent so the console/UI shows
planning progress in real-time.
"""

from __future__ import annotations

import json
import uuid as _uuid
from typing import Any

from pydantic_ai import Agent, ModelRetry, RunContext

from modules.backend.agents.mission.planning.build_session import PlanBuildingSession
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def _require_build_session(ctx: RunContext) -> PlanBuildingSession:
    """Get build_session from deps or raise ModelRetry with clear error.

    Fails fast when the planning agent is invoked in chat mode without
    a PlanBuildingSession (e.g. via handle() route instead of
    _call_planning_agent dispatch).
    """
    session = ctx.deps.build_session
    if session is None:
        logger.error(
            "build_session is None — planning tool called without PlanBuildingSession",
            extra={
                "mission_id": getattr(ctx.deps, "mission_id", None),
                "session_id": getattr(ctx.deps, "session_id", None),
            },
        )
        raise ModelRetry(
            "Plan modification tools require a PlanBuildingSession. "
            "This context does not have one — use get_current_plan to "
            "inspect the plan, or ask the user to refine via the Director."
        )
    return session


async def _emit_tool_event(
    ctx: RunContext,
    tool_name: str,
    tool_args: dict | None = None,
) -> None:
    """Emit an AgentToolCallEvent if event_bus is available on deps.

    Best-effort — a failed emit never blocks plan building.
    """
    event_bus = getattr(ctx.deps, "event_bus", None)
    if not event_bus:
        return
    session_id = getattr(ctx.deps, "session_id", None)
    try:
        from modules.backend.events.types import AgentToolCallEvent
        await event_bus.publish(AgentToolCallEvent(
            session_id=_uuid.UUID(session_id) if session_id else _uuid.uuid4(),
            source="mission.planning.agent",
            agent_id="mission.planning.agent",
            tool_name=tool_name,
            tool_args=tool_args or {},
        ))
    except Exception:
        logger.debug("Failed to emit planning tool event", exc_info=True)


def register_planning_tools(agent: Agent) -> None:
    """Register the 8 incremental plan-building tools on the agent."""

    @agent.tool
    async def add_task(
        ctx: RunContext,
        description: str,
        agent: str,
        instructions: str,
        dependencies: list[str] = [],
        domain_tags: list[str] = [],
    ) -> str:
        """Add a task to the plan. Returns the assigned task_id.

        Args:
            description: What the task does (1-2 sentences).
            agent: Agent name from the roster (e.g. "security.webapp.scanner.agent").
            instructions: Detailed instructions for the agent.
            dependencies: task_ids this task depends on (must be added first).
            domain_tags: Tags for categorisation (e.g. ["security", "scan"]).
        """
        session = _require_build_session(ctx)
        result = session.add_task(
            description=description,
            agent=agent,
            instructions=instructions,
            dependencies=dependencies,
            domain_tags=domain_tags,
        )
        await _emit_tool_event(ctx, "add_task", {
            "agent": agent,
            "description": description[:100],
            "task_id": result.get("task_id", ""),
        })
        return json.dumps(result)

    @agent.tool
    async def update_task(
        ctx: RunContext,
        task_id: str,
        description: str | None = None,
        agent: str | None = None,
        instructions: str | None = None,
        dependencies: list[str] | None = None,
        domain_tags: list[str] | None = None,
    ) -> str:
        """Update fields on an existing task.

        Only pass the fields you want to change — others are left as-is.

        Args:
            task_id: The task to update.
            description: New description (optional).
            agent: New agent from roster (optional).
            instructions: New instructions (optional).
            dependencies: New dependency list (optional, replaces existing).
            domain_tags: New tags (optional, replaces existing).
        """
        session = _require_build_session(ctx)
        result = session.update_task(
            task_id=task_id,
            description=description,
            agent=agent,
            instructions=instructions,
            dependencies=dependencies,
            domain_tags=domain_tags,
        )
        return json.dumps(result)

    @agent.tool
    async def remove_task(ctx: RunContext, task_id: str) -> str:
        """Remove a task from the plan. Also cancels any tasks that depend on it.

        Args:
            task_id: The task to remove.
        """
        session = _require_build_session(ctx)
        result = session.remove_task(task_id=task_id)
        return json.dumps(result)

    @agent.tool
    async def set_upstream_input(
        ctx: RunContext,
        task_id: str,
        input_name: str,
        source_task: str,
        source_field: str,
    ) -> str:
        """Wire an upstream task's output to this task's input.

        The source_task must be in this task's dependencies.

        Args:
            task_id: The task receiving the input.
            input_name: Name for this input binding.
            source_task: task_id of the upstream provider.
            source_field: Field name in the upstream task's output.
        """
        session = _require_build_session(ctx)
        result = session.set_upstream_input(
            task_id=task_id,
            input_name=input_name,
            source_task=source_task,
            source_field=source_field,
        )
        await _emit_tool_event(ctx, "set_upstream_input", {
            "task_id": task_id[:12],
            "source_task": source_task[:12],
            "input_name": input_name,
        })
        return json.dumps(result)

    @agent.tool
    async def set_static_input(
        ctx: RunContext,
        task_id: str,
        key: str,
        value: str,
    ) -> str:
        """Set a static input value on a task.

        For complex values (lists, dicts), pass them as a JSON string
        and they will be parsed automatically.

        Args:
            task_id: The task to set the input on.
            key: Input key name.
            value: Input value (string, or JSON string for complex values).
        """
        session = _require_build_session(ctx)
        # Try to parse JSON values (lists, dicts, numbers)
        parsed_value: Any = value
        try:
            parsed_value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            pass
        result = session.set_static_input(
            task_id=task_id, key=key, value=parsed_value,
        )
        return json.dumps(result)

    @agent.tool
    async def set_file_manifest(
        ctx: RunContext,
        task_id: str,
        read_for_pattern: list[dict] = [],
        read_first: list[dict] = [],
        modify: list[dict] = [],
    ) -> str:
        """Set the file manifest for a coding task.

        Each entry is {"path": "...", "reason": "..."}.
        Only for tasks where the agent creates or modifies files.

        Args:
            task_id: The coding task.
            read_for_pattern: Exemplar files showing the correct pattern (max 2).
            read_first: Files to read for context (max 5).
            modify: Files to create or change (max 5).
        """
        session = _require_build_session(ctx)
        result = session.set_file_manifest(
            task_id=task_id,
            read_for_pattern=read_for_pattern or None,
            read_first=read_first or None,
            modify=modify or None,
        )
        return json.dumps(result)

    @agent.tool
    async def set_verification(
        ctx: RunContext,
        task_id: str,
        tier: int,
        config: dict,
    ) -> str:
        """Set verification config for a task.

        Tier 1: {"schema_validation": true, "required_output_fields": ["field1"]}
        Tier 2: {"deterministic_checks": [{"check": "check_name", "params": {}}]}
        Tier 3: {"requires_ai_evaluation": true, "evaluation_criteria": ["..."],
                  "evaluator_agent": "system.verification.agent"}

        Args:
            task_id: The task to configure verification for.
            tier: 1, 2, or 3.
            config: Tier-specific configuration dict.
        """
        session = _require_build_session(ctx)
        result = session.set_verification(
            task_id=task_id, tier=tier, config=config,
        )
        return json.dumps(result)

    @agent.tool
    async def finalise_plan(
        ctx: RunContext,
        summary: str,
        estimated_cost_usd: float,
        estimated_duration_seconds: int,
    ) -> str:
        """Validate and finalise the plan. Call this when all tasks are added.

        Returns validation_errors if the plan is invalid — fix the issues
        with update_task/remove_task, then call finalise_plan again.

        Args:
            summary: Brief description of what the plan accomplishes.
            estimated_cost_usd: Total estimated LLM cost for the plan.
            estimated_duration_seconds: Estimated wall-clock time (accounting for parallelism).
        """
        session = _require_build_session(ctx)
        result = session.finalise(
            summary=summary,
            estimated_cost_usd=estimated_cost_usd,
            estimated_duration_seconds=estimated_duration_seconds,
        )
        if not result["valid"]:
            await _emit_tool_event(ctx, "finalise_plan", {
                "status": "invalid",
                "error_count": len(result["errors"]),
            })
            return json.dumps({
                "status": "invalid",
                "validation_errors": result["errors"],
                "hint": "Fix the errors above with update_task/remove_task, then call finalise_plan again.",
            })
        task_count = len(session.tasks)
        await _emit_tool_event(ctx, "finalise_plan", {
            "status": "finalised",
            "task_count": task_count,
            "summary": summary[:100],
        })
        return json.dumps({
            "status": "finalised",
            "task_count": task_count,
        })
