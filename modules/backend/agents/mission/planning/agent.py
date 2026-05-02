"""Planning Agent — task decomposition via incremental tool calls.

Two modes:
  - **Dispatch mode** (default): Called by _call_planning_agent() in the
    mission dispatch pipeline. Uses 8 planning tools (add_task,
    set_upstream_input, finalise_plan, etc.) to build the plan
    incrementally. Each tool has a trivially small schema — no grammar
    compiler limits, no normaliser layers. Plan 69.
  - **Chat mode** (chat_mode=True): Same 8 planning tools + 3 read-only
    introspection tools (get_current_plan, get_roster, get_mission_info).
    Uses the chat.md prompt variant. Output type is str (conversational).
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model

from modules.backend.agents.deps.base import BaseAgentDeps
from modules.backend.agents.mission_control.helpers import (
    _build_model,
    assemble_instructions,
)
from modules.backend.core.logging import get_logger
from modules.backend.schemas.task_plan import TaskPlan

logger = get_logger(__name__)


@dataclass
class PlanningAgentDeps(BaseAgentDeps):
    """Dependencies injected into the Planning Agent at runtime."""

    mission_brief: str = ""
    roster_description: str = ""
    upstream_context: dict[str, Any] | None = None
    event_bus: Any = None  # EventBusProtocol — for chat-mode plan events
    build_session: Any = None  # PlanBuildingSession — set in dispatch/chat mode


def create_agent(
    model: str | Model,
    tool_names: list[str] | None = None,
    *,
    chat_mode: bool = False,
) -> Agent:
    """Create the Planning Agent instance.

    Args:
        model: Model resolved from caller (registry or direct).
        tool_names: Ignored (tools are registered inline).
        chat_mode: When True, register read-only introspection tools
            alongside the 8 planning tools, and use the chat prompt.
            When False (default), register only the 8 planning tools.
    """
    if isinstance(model, str):
        model = _build_model(model)

    base_prompt = assemble_instructions("mission", "planning")
    if chat_mode:
        chat_prompt = assemble_instructions("mission", "planning", variant="chat")
        system_prompt = f"{base_prompt}\n\n{chat_prompt}"
    else:
        system_prompt = base_prompt

    agent: Agent = Agent(
        model,
        system_prompt=system_prompt,
        deps_type=PlanningAgentDeps,
    )

    # Register the 8 planning tools (shared between dispatch and chat)
    from modules.backend.agents.mission.planning.tools import register_planning_tools
    register_planning_tools(agent)

    # Dynamic instructions: inject current plan state before each LLM call
    @agent.instructions
    async def inject_plan_state(ctx: RunContext[PlanningAgentDeps]) -> str:
        if ctx.deps.build_session is None:
            return ""
        return ctx.deps.build_session.render_plan_summary()

    if chat_mode:
        _register_read_tools(agent)

    return agent


# ---------------------------------------------------------------------------
# Chat-mode read-only introspection tools
# ---------------------------------------------------------------------------

def _register_read_tools(agent: Agent) -> None:
    """Register read-only tools for chat-mode plan interaction."""

    @agent.tool
    async def get_current_plan(ctx: RunContext[PlanningAgentDeps]) -> str:
        """Get the current mission plan with task states, budget, and gate mode."""
        if not ctx.deps.mission_id or not ctx.deps.db_session:
            return json.dumps({"error": "No mission context available"})

        from modules.backend.agents.adapters.plan_introspection import get_plan_state
        result = await get_plan_state(
            ctx.deps.db_session, mission_id=ctx.deps.mission_id,
        )
        return json.dumps(result, indent=2, default=str)

    @agent.tool
    async def get_roster(ctx: RunContext[PlanningAgentDeps]) -> str:
        """List available agents with capabilities, tools, models, and constraints."""
        if not ctx.deps.mission_id or not ctx.deps.db_session:
            return json.dumps({"error": "No mission context available"})

        from modules.backend.agents.mission_control.roster import derive_roster_from_team
        from modules.backend.agents.mission_control.helpers.prompt_builder import (
            _build_roster_prompt,
        )
        roster = await derive_roster_from_team(
            ctx.deps.mission_id, ctx.deps.db_session,
        )
        return _build_roster_prompt(roster)

    @agent.tool
    async def get_mission_info(ctx: RunContext[PlanningAgentDeps]) -> str:
        """Get mission details: name, description, brief, budget, status."""
        if not ctx.deps.mission_id or not ctx.deps.db_session:
            return json.dumps({"error": "No mission context available"})

        from modules.backend.repositories.mission import MissionRepository
        repo = MissionRepository(ctx.deps.db_session)
        mission = await repo.get_by_id(ctx.deps.mission_id)
        return json.dumps({
            "id": mission.id,
            "name": mission.name,
            "description": mission.description,
            "brief": mission.brief,
            "status": mission.status,
            "default_roster": mission.default_roster,
            "execution_environment": mission.execution_environment,
        }, indent=2, default=str)


# ---------------------------------------------------------------------------
# Legacy: blob-based extraction (kept for backward compat — Plan 69 §Phase 3)
# ---------------------------------------------------------------------------

def extract_task_plan_json(text: str, *, mission_id: str | None = None) -> dict:
    """Extract, enrich, and validate a TaskPlan dict from planning agent output.

    LEGACY: This function is no longer called by the primary dispatch path
    (which uses tool-based plan building). Retained for backward
    compatibility with existing code paths and tests. Will be removed
    after Plan 69 Phase 3 cleanup.
    """
    from modules.backend.agents.mission.planning.build_session import semantic_check

    stripped = text.strip()
    plan_dict = _try_parse_json(stripped)

    if plan_dict is None:
        fence_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", stripped, re.DOTALL)
        if fence_match:
            plan_dict = _try_parse_json(fence_match.group(1).strip())

    if plan_dict is None:
        xml_match = re.search(r"<task_plan>\s*(.*?)\s*</task_plan>", stripped, re.DOTALL)
        if xml_match:
            plan_dict = _try_parse_json(xml_match.group(1).strip())

    if plan_dict is None:
        first_brace = stripped.find("{")
        last_brace = stripped.rfind("}")
        if first_brace != -1 and last_brace > first_brace:
            plan_dict = _try_parse_json(stripped[first_brace:last_brace + 1])

    if plan_dict is None:
        raise ValueError(
            f"Could not extract valid TaskPlan JSON from planning agent output "
            f"({len(text)} chars). First 500 chars: {text[:500]}"
        )

    if mission_id and not plan_dict.get("mission_id"):
        plan_dict["mission_id"] = mission_id

    try:
        plan = TaskPlan.model_validate(plan_dict)
    except ValidationError as e:
        raise ValueError(f"TaskPlan schema validation failed: {e}") from e

    errors = semantic_check(plan)
    if errors:
        raise ValueError(
            f"TaskPlan semantic validation failed:\n"
            + "\n".join(f"- {e}" for e in errors)
        )

    return plan.model_dump()


def _try_parse_json(text: str) -> dict | None:
    """Attempt to parse text as JSON dict. Returns None on failure."""
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    return None
