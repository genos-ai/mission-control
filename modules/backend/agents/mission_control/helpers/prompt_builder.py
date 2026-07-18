"""Prompt assembly helpers — layered system prompts and planning prompts."""

from __future__ import annotations

import json

from modules.backend.core.config import find_project_root
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def assemble_instructions(
    category_or_agent_name: str,
    name: str | None = None,
    *,
    variant: str | None = None,
    mission_brief: str | None = None,
    user_prompt: str | None = None,
) -> str:
    """Load the system prompt for an agent.

    Primary source: DB (agent_catalog.system_prompt via the registry).
    The DB stores the fully assembled prompt (organization + category +
    agent layers) written by seed-catalog. Edits via the admin API go
    straight to DB with version tracking.

    Fallback: disk files (for seed-catalog itself, which needs to
    assemble layers before the DB has them, and for when the DB is
    unavailable).

    Runtime-only layers (mission_brief, user_prompt) are always
    appended on top of the base prompt regardless of source.

    Accepts either:
        assemble_instructions("software", "quality")       — 2-arg (legacy)
        assemble_instructions("security.webapp.scanner")   — dotted agent path
        assemble_instructions("security.webapp.scanner.agent") — full agent name

    Args:
        variant: Optional prompt file variant. When set, always reads
            from disk (variants are not stored in the DB catalog).
    """
    # Resolve agent_name for DB lookup
    if name is not None:
        agent_name = f"{category_or_agent_name}.{name}.agent"
    else:
        cleaned = category_or_agent_name
        if not cleaned.endswith(".agent"):
            cleaned = cleaned + ".agent"
        agent_name = cleaned

    # Try DB first (unless variant is requested — variants are disk-only)
    base_prompt = ""
    if not variant:
        base_prompt = _load_prompt_from_registry(agent_name)

    # Fallback to disk assembly
    if not base_prompt:
        base_prompt = _assemble_from_disk(category_or_agent_name, name, variant=variant)

    # Append runtime-only layers
    layers = [base_prompt] if base_prompt else []
    if mission_brief:
        layers.append(f"## Mission Brief\n\n{mission_brief}")
    if user_prompt:
        layers.append(f"## Mission-Specific Instructions\n\n{user_prompt}")

    return "\n\n".join(layers)


def _load_prompt_from_registry(agent_name: str) -> str:
    """Load the system prompt from the agent registry (DB-backed).

    Returns empty string if the registry is unavailable or the agent
    has no stored prompt. Callers fall back to disk assembly.
    """
    try:
        from modules.backend.agents.mission_control.registry import get_registry

        registry = get_registry()
        config = registry.get(agent_name)
        if config and config.system_prompt:
            return config.system_prompt
    except Exception:
        logger.debug("registry lookup failed for agent %s", agent_name, exc_info=True)
    return ""


def _assemble_from_disk(
    category_or_agent_name: str,
    name: str | None = None,
    *,
    variant: str | None = None,
) -> str:
    """Assemble prompt from disk files (organization + category + agent).

    Used by seed-catalog to build the full prompt before writing to DB,
    and as fallback when the DB is unavailable.
    """
    if name is not None:
        parts = [category_or_agent_name, name]
    else:
        cleaned = category_or_agent_name
        if cleaned.endswith(".agent"):
            cleaned = cleaned[: -len(".agent")]
        parts = cleaned.split(".")

    category = parts[0]

    project_root = find_project_root()
    prompts_dir = project_root / "config" / "prompts"
    layers: list[str] = []

    # Agent identity FIRST — defines who the agent is before
    # any generic org/category guidelines. This matches LLM best
    # practice: identity → context → constraints.
    prompt_filename = f"{variant}.md" if variant else "system.md"
    agent_file = prompts_dir / "agents" / "/".join(parts) / prompt_filename
    if agent_file.exists():
        layers.append(agent_file.read_text(encoding="utf-8").strip())

    # Category prompt (e.g. "research", "software")
    cat_file = prompts_dir / "categories" / f"{category}.md"
    if cat_file.exists():
        layers.append(cat_file.read_text(encoding="utf-8").strip())

    # Organization-level guidelines (coding standards, security, etc.)
    org_dir = prompts_dir / "organization"
    if org_dir.exists():
        for org_file in sorted(org_dir.glob("*.md")):
            layers.append(org_file.read_text(encoding="utf-8").strip())

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
            f"## Upstream Context\n\n```json\n" f"{json.dumps(upstream_context, indent=2)}\n```\n"
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
    """Load the system prompt for a CLI agent.

    DB first (via registry), disk fallback. Same source as
    assemble_instructions but without the runtime layers
    (mission_brief, user_prompt).
    """
    # Try DB
    prompt = _load_prompt_from_registry(agent_name)
    if prompt:
        return prompt

    # Fallback to disk
    from modules.backend.core.config import find_project_root

    parts = agent_name.rsplit(".", 1)[0].split(".")
    prompt_path = find_project_root() / "config" / "prompts" / "agents"
    for part in parts:
        prompt_path = prompt_path / part
    prompt_path = prompt_path / "system.md"

    if not prompt_path.is_file():
        return ""

    return prompt_path.read_text(encoding="utf-8")
