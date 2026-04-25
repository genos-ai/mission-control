"""Prompt assembly helpers — layered system prompts and planning prompts."""

from __future__ import annotations

import json

from modules.backend.core.config import find_project_root
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def assemble_instructions(
    category: str,
    name: str,
    *,
    variant: str | None = None,
    mission_brief: str | None = None,
    user_prompt: str | None = None,
) -> str:
    """Compose layered prompt per Plan 28 section 7.

    Layer order:
        1. Organization prompts  (config/prompts/organization/*.md)
        2. Category prompt        (config/prompts/categories/{category}.md)
        3. Agent system prompt    (config/prompts/agents/{category}/{name}/{variant or "system"}.md)
        4. Mission brief          (from missions.brief — shared across all agents)
        5. User prompt            (from mission_team_members.user_prompt — per-agent)

    Layers 1-3 come from files on disk. Layers 4-5 are passed in when
    available (populated from DB at dispatch time). Missing layers are
    silently skipped.

    Args:
        variant: Optional prompt file variant. When provided, loads
            ``{variant}.md`` instead of ``system.md`` from the agent's
            prompt directory. Added by Plan 51 Phase D so the supervisor
            can have separate system.md (event-mode) and chat.md
            (chat-mode) prompts without breaking existing callers.
    """
    project_root = find_project_root()
    prompts_dir = project_root / "config" / "prompts"
    layers: list[str] = []

    org_dir = prompts_dir / "organization"
    if org_dir.exists():
        for org_file in sorted(org_dir.glob("*.md")):
            layers.append(org_file.read_text(encoding="utf-8").strip())

    cat_file = prompts_dir / "categories" / f"{category}.md"
    if cat_file.exists():
        layers.append(cat_file.read_text(encoding="utf-8").strip())

    prompt_filename = f"{variant}.md" if variant else "system.md"
    agent_file = prompts_dir / "agents" / category / name / prompt_filename
    if agent_file.exists():
        layers.append(agent_file.read_text(encoding="utf-8").strip())

    if mission_brief:
        layers.append(f"## Mission Brief\n\n{mission_brief}")

    if user_prompt:
        layers.append(f"## Mission-Specific Instructions\n\n{user_prompt}")

    return "\n\n".join(layers)


def _build_roster_prompt(roster: "Roster") -> str:
    """Format roster for the Planning Agent's context."""
    lines = ["## Available Agents\n"]
    for agent in roster.agents:
        lines.append(f"### {agent.agent_name} (v{agent.agent_version})")
        lines.append(f"**Description:** {agent.description}")
        lines.append(f"**Model:** {agent.model.name}")
        lines.append(f"**Tools:** {', '.join(agent.tools) if agent.tools else 'none'}")
        lines.append(f"**Input contract:** {agent.interface.input}")
        lines.append(f"**Output contract:** {agent.interface.output}")
        lines.append(
            f"**Constraints:** timeout={agent.constraints.timeout_seconds}s, "
            f"cost_ceiling=${agent.constraints.cost_ceiling_usd}, "
            f"retry_budget={agent.constraints.retry_budget}"
        )
        lines.append("")
    return "\n".join(lines)


def _build_planning_prompt(
    mission_brief: str,
    mission_id: str,
    roster_description: str,
    upstream_context: dict | None,
    project_context: dict | None = None,
    recent_failures: list | None = None,
    current_plan: dict | None = None,
    refinement_instructions: str | None = None,
    plan_version: int = 1,
) -> str:
    """Assemble the full prompt for the Planning Agent.

    When `current_plan` and `refinement_instructions` are both provided,
    the prompt switches to refinement mode: the agent is told to produce
    a new TaskPlan that incorporates the user's changes while preserving
    task_id strings for semantically-unchanged tasks. This is Plan 42's
    refinement path (§10.4) — the Director delegates here via a tool
    call rather than authoring plans directly.
    """
    is_refinement = current_plan is not None and refinement_instructions

    parts = [
        f"## Mission Brief\n\n{mission_brief}\n",
        f"## Mission ID\n\n{mission_id}\n",
        f"## Plan Version\n\n{plan_version}\n"
        f"Use this version number for task IDs: `v{plan_version}-task-001`, "
        f"`v{plan_version}-task-002`, etc.\n",
        roster_description,
    ]

    if is_refinement:
        parts.append(
            "## Mode: REFINEMENT\n\n"
            "You are refining an **existing TaskPlan**, not creating one from\n"
            "scratch. The user has asked for specific changes. Produce a new\n"
            "TaskPlan that incorporates the user's instructions while keeping\n"
            "unrelated parts of the existing plan intact.\n\n"
            "**Task ID preservation rules:**\n"
            "- If a task's semantics are unchanged (same objective, same agent,\n"
            "  same general approach), **reuse its existing `task_id` string**.\n"
            "  This lets the user's approvals and run history survive refinement.\n"
            "- If a task is genuinely new, generate a fresh `task_id`.\n"
            "- Tasks that should be removed simply do not appear in the output.\n"
            "- Dependencies that point at removed tasks must be updated or dropped.\n\n"
            "### Current TaskPlan\n\n"
            "```json\n"
            f"{json.dumps(current_plan, indent=2)}\n"
            "```\n\n"
            "### User's Refinement Instructions\n\n"
            f"{refinement_instructions}\n"
        )

    if project_context:
        parts.append(
            "## Project Context\n\n"
            "The following is the Project Context Document (PCD) for the target project. "
            "Use it to understand the project's architecture, constraints, current state, "
            "and key decisions when decomposing tasks.\n\n"
            f"```json\n{json.dumps(project_context, indent=2)}\n```\n"
        )

    if recent_failures:
        parts.append(
            "## Recent Failures (Avoid Repeating)\n\n"
            "The following tasks failed in recent runs against this project. "
            "Account for these when planning — e.g., split large modules that "
            "caused token limits, avoid approaches that timed out, adjust task "
            "granularity based on past outcomes.\n\n"
            f"```json\n{json.dumps(recent_failures, indent=2)}\n```\n"
        )

    if upstream_context:
        parts.append(
            f"## Upstream Context\n\n```json\n"
            f"{json.dumps(upstream_context, indent=2)}\n```\n"
        )

    parts.append(
        "## Output Format\n\n"
        "Return your task plan as JSON within <task_plan> tags.\n"
        "Follow the TaskPlan schema exactly. See system prompt for rules.\n"
    )

    return "\n".join(parts)


def _append_validation_feedback(prompt: str, errors: list[str]) -> str:
    """Append validation errors to planning prompt for retry."""
    error_text = "\n".join(f"- {e}" for e in errors)
    return (
        f"{prompt}\n\n"
        f"--- VALIDATION ERRORS FROM PREVIOUS ATTEMPT ---\n"
        f"Your previous TaskPlan failed validation:\n{error_text}\n"
        f"Fix these errors and try again.\n"
    )


def load_agent_system_prompt(agent_name: str) -> str:
    """Load the system prompt markdown for a CLI agent.

    Reads config/prompts/agents/{domain}/{name}/system.md.
    Returns the raw markdown content (no template substitution).
    """
    from modules.backend.core.config import find_project_root

    parts = agent_name.rsplit(".", 1)[0].split(".")
    prompt_path = find_project_root() / "config" / "prompts" / "agents"
    for part in parts:
        prompt_path = prompt_path / part
    prompt_path = prompt_path / "system.md"

    if not prompt_path.is_file():
        return ""

    return prompt_path.read_text(encoding="utf-8")
