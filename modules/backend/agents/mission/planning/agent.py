"""Planning Agent — task decomposition via extended thinking.

Two modes:
  - **Dispatch mode** (default): Called by _call_planning_agent() in the
    mission dispatch pipeline. Produces TaskPlan JSON within <task_plan>
    XML tags. No tools. Thinking trace captured for audit trail.
  - **Chat mode** (chat_mode=True): Called via handle() for interactive
    plan inspection and modification. Has tools (get_current_plan,
    get_roster, get_mission_info, save_plan). Uses the chat.md prompt
    variant instead of system.md.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model

from modules.backend.agents.deps.base import BaseAgentDeps
from modules.backend.agents.mission_control.helpers import (
    _build_model,
    assemble_instructions,
)
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PlanningAgentDeps(BaseAgentDeps):
    """Dependencies injected into the Planning Agent at runtime."""

    mission_brief: str = ""
    roster_description: str = ""
    upstream_context: dict[str, Any] | None = None
    event_bus: Any = None  # EventBusProtocol — for chat-mode plan events


def create_agent(
    model: str | Model,
    tool_names: list[str] | None = None,
    *,
    chat_mode: bool = False,
) -> Agent:
    """Create the Planning Agent instance.

    Args:
        model: Model resolved from caller (registry or direct).
        tool_names: Ignored (tools are registered inline for chat mode).
        chat_mode: When True, register tools and use the chat prompt variant.
            When False (default), create a tool-less agent for dispatch.
    """
    if isinstance(model, str):
        model = _build_model(model)

    # Chat mode loads BOTH system.md (full TaskPlan schema) and chat.md
    # (conversational tools/instructions). The schema is essential for the
    # agent to produce valid JSON when modifying plans via save_plan.
    base_prompt = assemble_instructions("mission", "planning")
    if chat_mode:
        chat_prompt = assemble_instructions("mission", "planning", variant="chat")
        system_prompt = f"{base_prompt}\n\n{chat_prompt}"
    else:
        system_prompt = base_prompt

    agent = Agent(
        model,
        system_prompt=system_prompt,
        deps_type=PlanningAgentDeps,
    )

    if chat_mode:
        _register_chat_tools(agent)

    return agent


def _register_chat_tools(agent: Agent) -> None:
    """Register tools for chat-mode plan interaction."""

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

    @agent.tool
    async def save_plan(
        ctx: RunContext[PlanningAgentDeps],
        task_plan_json: str,
    ) -> str:
        """Validate and persist a TaskPlan. Pass the complete TaskPlan as a JSON string.

        Runs full validation (schema + 11 semantic rules) and reconciles task
        states. Returns success with version info, or validation errors.

        Args:
            task_plan_json: Complete TaskPlan JSON string conforming to the
                TaskPlan schema. Must include version, mission_id, summary,
                tasks, etc.
        """
        if not ctx.deps.mission_id or not ctx.deps.db_session:
            return json.dumps({"error": "No mission context available"})

        try:
            plan_dict = json.loads(task_plan_json)
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON: {e}"})

        from modules.backend.services.mission_plan_orchestrator import (
            MissionPlanOrchestrator,
        )

        orchestrator = MissionPlanOrchestrator(
            ctx.deps.db_session, event_bus=ctx.deps.event_bus,
        )
        try:
            result = await orchestrator.apply_plan(
                mission_id=ctx.deps.mission_id,
                plan_dict=plan_dict,
                user_id="mission.planning.agent",
            )
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)})


async def run_agent(
    agent: Agent,
    deps: PlanningAgentDeps,
    user_prompt: str,
    **kwargs: Any,
) -> dict:
    """Run the Planning Agent. Returns parsed TaskPlan dict and thinking trace.

    The agent returns JSON within <task_plan> tags. This function extracts,
    parses, and returns the JSON as a dict. The caller (Mission Control)
    validates it via plan_validator.
    """
    result = await agent.run(user_prompt, deps=deps, **kwargs)

    response_text = result.output
    plan_json = extract_task_plan_json(response_text)

    # Capture thinking trace if available
    thinking_trace = None
    if hasattr(result, "all_messages"):
        for msg in result.all_messages():
            for part in getattr(msg, "parts", []):
                if hasattr(part, "content") and hasattr(part, "part_kind"):
                    if "thinking" in str(getattr(part, "part_kind", "")):
                        thinking_trace = part.content

    return {
        "task_plan": plan_json,
        "thinking_trace": thinking_trace,
        "usage": result.usage() if hasattr(result, "usage") else None,
    }


def extract_task_plan_json(text: str) -> dict:
    """Extract TaskPlan JSON from within <task_plan> XML tags.

    Raises ValueError if tags are missing or JSON is malformed.
    """
    pattern = r"<task_plan>\s*(.*?)\s*</task_plan>"
    match = re.search(pattern, text, re.DOTALL)

    if not match:
        raise ValueError(
            "Planning Agent response does not contain <task_plan> tags. "
            "Response must include JSON within <task_plan>...</task_plan> tags."
        )

    json_str = match.group(1).strip()

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Planning Agent response contains invalid JSON within <task_plan> tags: {e}"
        ) from e
