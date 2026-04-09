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
    mission_brief: str | None = None,
    user_prompt: str | None = None,
) -> str:
    """Compose layered prompt per Plan 28 section 7.

    Layer order:
        1. Organization prompts  (config/prompts/organization/*.md)
        2. Category prompt        (config/prompts/categories/{category}.md)
        3. Agent system prompt    (config/prompts/agents/{category}/{name}/system.md)
        4. Mission brief          (from missions.brief — shared across all agents)
        5. User prompt            (from mission_team_members.user_prompt — per-agent)

    Layers 1-3 come from files on disk. Layers 4-5 are passed in when
    available (populated from DB at dispatch time). Missing layers are
    silently skipped.
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

    agent_file = prompts_dir / "agents" / category / name / "system.md"
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
    code_map: dict | None = None,
    project_context: dict | None = None,
    recent_failures: list | None = None,
) -> str:
    """Assemble the full prompt for the Planning Agent."""
    parts = [
        f"## Mission Brief\n\n{mission_brief}\n",
        f"## Mission ID\n\n{mission_id}\n",
        roster_description,
    ]

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

    if code_map:
        parts.append(
            "## Code Map (Structural Overview)\n\n"
            "The following JSON contains the complete structural map of the codebase.\n"
            "Use it to:\n"
            "- Identify which files exist and what they contain\n"
            "- Trace dependencies via the import_graph\n"
            "- Generate file_manifest entries for coding tasks\n"
            "- Understand which modules are most important (highest PageRank rank)\n\n"
            "```json\n"
            f"{json.dumps(code_map, indent=None)}\n"
            "```\n"
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
