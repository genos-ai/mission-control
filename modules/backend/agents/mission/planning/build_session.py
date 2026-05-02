"""PlanBuildingSession — in-memory TaskPlan assembly via incremental mutations.

The Planning Agent calls tools that mutate this session. Each tool call
is validated eagerly (agent name against roster, dependency refs exist,
etc.). On finalise(), the assembled plan is validated against the full
TaskPlan schema + plan_validator rules.

This replaces the monolithic JSON blob approach where the LLM had to
produce a perfectly-structured multi-KB JSON in one shot. Plan 69.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from modules.backend.agents.mission_control.plan_validator import validate_plan
from modules.backend.agents.mission_control.roster import Roster
from modules.backend.core.logging import get_logger
from modules.backend.schemas.task_plan import TaskPlan

logger = get_logger(__name__)

# task_id format: v{version}-task-{NNN}
_TASK_ID_PATTERN = re.compile(r"^v\d+-task-\d{3,}$")


def generate_task_id(version: int, sequence: int) -> str:
    """Generate a task_id: v{version}-task-{NNN}.

    Shared by PlanBuildingSession and MissionPlanService.add_task().
    """
    return f"v{version}-task-{sequence:03d}"


def extract_task_sequence(task_id: str) -> int:
    """Extract the sequence number from a task_id. Returns 0 if unparseable."""
    match = re.search(r"task-(\d+)$", task_id)
    return int(match.group(1)) if match else 0


def resolve_agent_version(agent_name: str) -> str:
    """Look up agent version from the registry. Returns '1.0.0' if not found.

    Shared by PlanBuildingSession and MissionPlanService.add_task().
    """
    from modules.backend.core.agent_registry import AgentRegistry
    registry = AgentRegistry()
    if registry.has(agent_name):
        return registry.get(agent_name).version or "1.0.0"
    return "1.0.0"


def semantic_check(plan: TaskPlan) -> list[str]:
    """Run semantic validation rules that Pydantic schema cannot enforce.

    Checks: non-negative cost/duration, task_id format, dependency refs,
    from_upstream consistency, DAG cycles, tier_3 completeness.

    Shared by PlanBuildingSession.finalise() and the legacy
    extract_task_plan_json() path.
    """
    errors: list[str] = []

    if plan.estimated_cost_usd < 0:
        errors.append(
            f"estimated_cost_usd must be >= 0, got {plan.estimated_cost_usd}"
        )
    if plan.estimated_duration_seconds < 0:
        errors.append(
            f"estimated_duration_seconds must be >= 0, got {plan.estimated_duration_seconds}"
        )

    for task in plan.tasks:
        if not _TASK_ID_PATTERN.match(task.task_id):
            errors.append(
                f"tasks[{task.task_id}].task_id: must match v{{N}}-task-{{NNN}}, "
                f"got '{task.task_id}'"
            )

    all_ids = {t.task_id for t in plan.tasks}
    for task in plan.tasks:
        for dep in task.dependencies:
            if dep not in all_ids:
                errors.append(
                    f"tasks[{task.task_id}].dependencies: '{dep}' not in plan"
                )

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


class PlanBuildingSession:
    """In-memory TaskPlan assembly used by planning tools.

    Holds an evolving plan dict and provides mutation methods.
    Does NOT touch the database — persistence happens on finalise()
    in the caller.
    """

    def __init__(
        self,
        mission_id: str,
        version: int,
        roster: Roster,
        budget_usd: float,
        *,
        current_plan: dict | None = None,
    ):
        self.mission_id = mission_id
        self.version = version
        self.roster = roster
        self.budget_usd = budget_usd
        self._task_counter = 0
        self.tasks: dict[str, dict] = {}  # task_id -> task body
        self.finalised_plan: dict | None = None

        # Seed from existing plan (refinement mode)
        if current_plan and "tasks" in current_plan:
            for task in current_plan["tasks"]:
                tid = task.get("task_id", "")
                self.tasks[tid] = dict(task)
                self._task_counter = max(
                    self._task_counter,
                    extract_task_sequence(tid),
                )

    def _next_task_id(self) -> str:
        """Generate the next task_id using the shared utility."""
        self._task_counter += 1
        return generate_task_id(self.version, self._task_counter)

    def _get_task(self, task_id: str) -> dict:
        """Get a task by ID. Raises KeyError if not found."""
        if task_id not in self.tasks:
            raise KeyError(f"Task '{task_id}' not found in plan")
        return self.tasks[task_id]

    # ── Mutation methods ─────────────────────────────────────────

    def add_task(
        self,
        *,
        description: str,
        agent: str,
        instructions: str,
        dependencies: list[str] | None = None,
        domain_tags: list[str] | None = None,
    ) -> dict:
        """Add a task to the plan. Returns {"task_id": ..., "status": "proposed"}."""
        # Validate agent exists in roster
        entry = self.roster.get_agent_by_name(agent)
        if entry is None:
            return {"error": f"Agent '{agent}' not found in roster"}

        # Validate dependencies exist
        deps = dependencies or []
        for dep in deps:
            if dep not in self.tasks:
                return {"error": f"Dependency '{dep}' not found in plan. Add it first."}

        task_id = self._next_task_id()
        agent_version = resolve_agent_version(agent)

        self.tasks[task_id] = {
            "task_id": task_id,
            "agent": agent,
            "agent_version": agent_version,
            "description": description,
            "instructions": instructions,
            "inputs": {"static": {}, "from_upstream": {}},
            "dependencies": deps,
            "verification": {
                "tier_1": {"schema_validation": True, "required_output_fields": []},
                "tier_2": {"deterministic_checks": []},
                "tier_3": {"requires_ai_evaluation": False},
            },
            "constraints": {},
            "domain_tags": domain_tags or [],
        }

        return {"task_id": task_id, "status": "proposed"}

    def update_task(
        self,
        *,
        task_id: str,
        description: str | None = None,
        agent: str | None = None,
        instructions: str | None = None,
        dependencies: list[str] | None = None,
        domain_tags: list[str] | None = None,
    ) -> dict:
        """Update fields on an existing task. Returns updated field names."""
        try:
            task = self._get_task(task_id)
        except KeyError as e:
            return {"error": str(e)}

        updated = []
        if description is not None:
            task["description"] = description
            updated.append("description")
        if agent is not None:
            entry = self.roster.get_agent_by_name(agent)
            if entry is None:
                return {"error": f"Agent '{agent}' not found in roster"}
            task["agent"] = agent
            task["agent_version"] = resolve_agent_version(agent)
            updated.append("agent")
        if instructions is not None:
            task["instructions"] = instructions
            updated.append("instructions")
        if dependencies is not None:
            for dep in dependencies:
                if dep not in self.tasks and dep != task_id:
                    return {"error": f"Dependency '{dep}' not found in plan"}
            task["dependencies"] = dependencies
            updated.append("dependencies")
        if domain_tags is not None:
            task["domain_tags"] = domain_tags
            updated.append("domain_tags")

        return {"task_id": task_id, "updated_fields": updated}

    def remove_task(self, *, task_id: str) -> dict:
        """Remove a task and cancel any tasks that depend on it."""
        if task_id not in self.tasks:
            return {"error": f"Task '{task_id}' not found in plan"}

        del self.tasks[task_id]

        # Cancel dependents
        cancelled = []
        for tid, task in list(self.tasks.items()):
            if task_id in task.get("dependencies", []):
                del self.tasks[tid]
                cancelled.append(tid)

        return {"task_id": task_id, "cancelled_dependents": cancelled}

    def set_upstream_input(
        self,
        *,
        task_id: str,
        input_name: str,
        source_task: str,
        source_field: str,
    ) -> dict:
        """Wire an upstream output to a task's input."""
        try:
            task = self._get_task(task_id)
        except KeyError as e:
            return {"error": str(e)}

        if source_task not in self.tasks:
            return {"error": f"Source task '{source_task}' not found in plan"}
        if source_task not in task.get("dependencies", []):
            return {
                "error": f"Source task '{source_task}' must be in dependencies. "
                f"Current deps: {task.get('dependencies', [])}"
            }

        upstream = task.setdefault("inputs", {}).setdefault("from_upstream", {})
        upstream[input_name] = {
            "source_task": source_task,
            "source_field": source_field,
        }

        return {"task_id": task_id, "input_name": input_name}

    def set_static_input(
        self,
        *,
        task_id: str,
        key: str,
        value: Any,
    ) -> dict:
        """Set a static input value on a task."""
        try:
            task = self._get_task(task_id)
        except KeyError as e:
            return {"error": str(e)}

        static = task.setdefault("inputs", {}).setdefault("static", {})
        static[key] = value

        return {"task_id": task_id, "key": key}

    def set_file_manifest(
        self,
        *,
        task_id: str,
        read_for_pattern: list[dict] | None = None,
        read_first: list[dict] | None = None,
        modify: list[dict] | None = None,
    ) -> dict:
        """Set the file manifest for a coding task."""
        try:
            task = self._get_task(task_id)
        except KeyError as e:
            return {"error": str(e)}

        manifest = {}
        if read_for_pattern is not None:
            manifest["read_for_pattern"] = read_for_pattern[:2]
        if read_first is not None:
            manifest["read_first"] = read_first[:5]
        if modify is not None:
            manifest["modify"] = modify[:5]

        task.setdefault("inputs", {})["file_manifest"] = manifest

        return {"task_id": task_id}

    def set_verification(
        self,
        *,
        task_id: str,
        tier: int,
        config: dict,
    ) -> dict:
        """Set verification config for a specific tier (1, 2, or 3)."""
        try:
            task = self._get_task(task_id)
        except KeyError as e:
            return {"error": str(e)}

        if tier not in (1, 2, 3):
            return {"error": f"tier must be 1, 2, or 3, got {tier}"}

        verification = task.setdefault("verification", {})
        verification[f"tier_{tier}"] = config

        return {"task_id": task_id, "tier": tier}

    # ── Finalisation ─────────────────────────────────────────────

    def finalise(
        self,
        *,
        summary: str,
        estimated_cost_usd: float,
        estimated_duration_seconds: int,
    ) -> dict:
        """Assemble, validate, and finalise the plan.

        Returns {"valid": True, "plan": dict} on success, or
        {"valid": False, "errors": list[str]} on failure.
        """
        if not self.tasks:
            return {"valid": False, "errors": ["Plan has no tasks"]}

        plan_dict = {
            "version": f"{self.version}.0.0",
            "mission_id": self.mission_id,
            "summary": summary,
            "estimated_cost_usd": estimated_cost_usd,
            "estimated_duration_seconds": estimated_duration_seconds,
            "tasks": list(self.tasks.values()),
            "execution_hints": {
                "min_success_threshold": 1.0,
                "critical_path": [],
            },
        }

        # Stage 1: Pydantic schema validation
        try:
            plan = TaskPlan.model_validate(plan_dict)
        except ValidationError as e:
            return {"valid": False, "errors": [str(e)]}

        # Stage 2: Semantic checks (cycles, refs, format)
        errors = semantic_check(plan)
        if errors:
            return {"valid": False, "errors": errors}

        # Stage 3: Full plan_validator (11 rules against roster + budget)
        validation = validate_plan(plan, self.roster, self.budget_usd)
        if not validation.is_valid:
            return {"valid": False, "errors": validation.errors}

        self.finalised_plan = plan.model_dump()
        return {"valid": True, "plan": self.finalised_plan}

    # ── Rendering ────────────────────────────────────────────────

    def render_plan_summary(self) -> str:
        """Compact text view for the dynamic system prompt."""
        if not self.tasks:
            return "Plan is empty. Start by adding tasks."

        lines = [f"## Current Plan ({len(self.tasks)} tasks)"]
        for tid, task in self.tasks.items():
            agent = task.get("agent", "?")
            deps = task.get("dependencies", [])
            dep_str = f"depends: {', '.join(deps)}" if deps else "no deps"
            lines.append(f"{tid}: {task.get('description', '')[:60]} [{agent}] ({dep_str})")

        return "\n".join(lines)
