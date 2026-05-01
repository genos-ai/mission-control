"""Planning Agent — task decomposition via extended thinking.

Two modes:
  - **Dispatch mode** (default): Called by _call_planning_agent() in the
    mission dispatch pipeline. Output type is str — the model produces
    raw JSON, which is parsed and validated against TaskPlan by the
    caller (_call_planning_agent). Thinking trace captured for audit.
  - **Chat mode** (chat_mode=True): Called via handle() for interactive
    plan inspection and modification. Has tools (get_current_plan,
    get_roster, get_mission_info, save_plan). Uses the chat.md prompt
    variant instead of system.md. Output type is str (conversational).
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
            Output type is str — the agent responds conversationally and
            uses the save_plan tool to persist validated plans.
            When False (default), output type is str — the model produces
            raw TaskPlan JSON, validated by the caller.
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

    if chat_mode:
        _register_chat_tools(agent)

    return agent


def extract_task_plan_json(text: str, *, mission_id: str | None = None) -> dict:
    """Extract, enrich, and validate a TaskPlan dict from planning agent output.

    Handles:
      1. Raw JSON (entire output is valid JSON)
      2. JSON inside markdown fences (```json ... ```)
      3. JSON inside <task_plan> XML tags (legacy fallback)

    When mission_id is provided, it's injected before validation — the
    model doesn't always include it but we know it at dispatch time.

    Raises ValueError if no valid JSON found or TaskPlan validation fails.
    """
    # Try 1: entire output is JSON
    stripped = text.strip()
    plan_dict = _try_parse_json(stripped)

    # Try 2: markdown code fence
    if plan_dict is None:
        fence_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", stripped, re.DOTALL)
        if fence_match:
            plan_dict = _try_parse_json(fence_match.group(1).strip())

    # Try 3: <task_plan> XML tags (legacy)
    if plan_dict is None:
        xml_match = re.search(r"<task_plan>\s*(.*?)\s*</task_plan>", stripped, re.DOTALL)
        if xml_match:
            plan_dict = _try_parse_json(xml_match.group(1).strip())

    if plan_dict is None:
        raise ValueError(
            f"Could not extract valid TaskPlan JSON from planning agent output "
            f"({len(text)} chars). First 500 chars: {text[:500]}"
        )

    # Inject known fields before validation
    if mission_id and not plan_dict.get("mission_id"):
        plan_dict["mission_id"] = mission_id

    return _validate_plan_dict(plan_dict)


def _try_parse_json(text: str) -> dict | None:
    """Attempt to parse text as JSON dict. Returns None on failure."""
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _validate_plan_dict(data: dict) -> dict:
    """Validate a dict against TaskPlan schema and run semantic checks.

    Returns the validated plan as a dict (via model_dump).
    Raises ValueError with details on failure.
    """
    try:
        plan = TaskPlan.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"TaskPlan schema validation failed: {e}") from e

    # Semantic checks (same as the old output_validator)
    errors = _semantic_check(plan)
    if errors:
        raise ValueError(
            f"TaskPlan semantic validation failed:\n"
            + "\n".join(f"- {e}" for e in errors)
        )

    return plan.model_dump()


def _semantic_check(plan: TaskPlan) -> list[str]:
    """Run semantic validation rules that Pydantic schema cannot enforce."""
    errors: list[str] = []

    if plan.estimated_cost_usd < 0:
        errors.append(
            f"estimated_cost_usd must be >= 0, got {plan.estimated_cost_usd}"
        )
    if plan.estimated_duration_seconds < 0:
        errors.append(
            f"estimated_duration_seconds must be >= 0, got {plan.estimated_duration_seconds}"
        )

    # task_id format: v{N}-task-{NNN}
    id_pattern = re.compile(r"^v\d+-task-\d{3,}$")
    for task in plan.tasks:
        if not id_pattern.match(task.task_id):
            errors.append(
                f"tasks[{task.task_id}].task_id: must match v{{N}}-task-{{NNN}}, "
                f"got '{task.task_id}'"
            )

    # Dependency references must exist in plan
    all_ids = {t.task_id for t in plan.tasks}
    for task in plan.tasks:
        for dep in task.dependencies:
            if dep not in all_ids:
                errors.append(
                    f"tasks[{task.task_id}].dependencies: '{dep}' not in plan"
                )

    # from_upstream source_task must be in dependencies
    for task in plan.tasks:
        for field_name, ref_or_list in task.inputs.from_upstream.items():
            refs = ref_or_list if isinstance(ref_or_list, list) else [ref_or_list]
            for ref in refs:
                if ref.source_task not in task.dependencies:
                    errors.append(
                        f"tasks[{task.task_id}].inputs.from_upstream[{field_name}]: "
                        f"source_task '{ref.source_task}' not in dependencies"
                    )

    # DAG cycle detection (Kahn's algorithm)
    in_degree: dict[str, int] = {t.task_id: 0 for t in plan.tasks}
    adjacency: dict[str, list[str]] = {t.task_id: [] for t in plan.tasks}
    for task in plan.tasks:
        for dep in task.dependencies:
            if dep in in_degree:
                adjacency[dep].append(task.task_id)
                in_degree[task.task_id] += 1
    queue = [tid for tid, deg in in_degree.items() if deg == 0]
    sorted_count = 0
    while queue:
        node = queue.pop()
        sorted_count += 1
        for neighbor in adjacency[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
    if sorted_count != len(plan.tasks):
        errors.append("TaskPlan contains a dependency cycle")

    # Tier 3 consistency
    for task in plan.tasks:
        t3 = task.verification.tier_3
        if t3.requires_ai_evaluation:
            if not t3.evaluation_criteria:
                errors.append(
                    f"tasks[{task.task_id}].verification.tier_3: "
                    f"requires_ai_evaluation=true but evaluation_criteria is empty"
                )
            if not t3.evaluator_agent:
                errors.append(
                    f"tasks[{task.task_id}].verification.tier_3: "
                    f"requires_ai_evaluation=true but evaluator_agent is missing"
                )

    return errors


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
