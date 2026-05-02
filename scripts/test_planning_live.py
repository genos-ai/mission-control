#!/usr/bin/env python3
"""
Planning Agent Test Harness — exercises the full planning flow without
needing a running server, database, or workflow dispatch.

Tests: model → prompt assembly → LLM call → JSON extraction →
       schema validation → semantic checks → plan_validator rules.

Usage:
    # Default: Opus 4.6 with WASA security brief
    python scripts/test_planning_live.py

    # Try different models
    python scripts/test_planning_live.py --model anthropic:claude-sonnet-4-6
    python scripts/test_planning_live.py --model copilot:claude-sonnet-4.6

    # Try different briefs
    python scripts/test_planning_live.py --brief wasa
    python scripts/test_planning_live.py --brief research
    python scripts/test_planning_live.py --brief custom "Audit the codebase for SQL injection"

    # Show the full prompt sent to the model
    python scripts/test_planning_live.py --show-prompt

    # Show raw model output before parsing
    python scripts/test_planning_live.py --show-raw

    # Dry run — build prompt + roster only, no LLM call
    python scripts/test_planning_live.py --dry-run

    # Verbose logging
    python scripts/test_planning_live.py -v
    python scripts/test_planning_live.py -d   # debug
"""

import asyncio
import json
import sys
import time
from pathlib import Path

import click

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Test briefs
# ---------------------------------------------------------------------------

BRIEFS = {
    "wasa": (
        "Run a Web Application Security Assessment (WASA) against the target codebase. "
        "Phase 1 scope: SAST only (no DAST, no exploitation). "
        "Steps:\n"
        "1. Scan — run all registered security scanning tools (opengrep, ruff, pip-audit, "
        "betterleaks, trivy, hadolint, checkov) against the target path. Merge SARIF output.\n"
        "2. Triage — LLM false-positive filtering of merged findings with code context.\n"
        "3. Report — synthesise findings into a structured security assessment report "
        "with OWASP mapping, CVSS scores, and remediation roadmap.\n\n"
        "Target: /workspace/target\n"
        "Evidence: /workspace/evidence"
    ),
    "research": (
        "Research the current state of Python async frameworks for building "
        "multi-agent AI systems. Compare FastAPI, LangGraph, CrewAI, and "
        "PydanticAI. Produce a structured report with pros/cons and recommendation."
    ),
    "audit": (
        "Audit the Mission Control codebase for compliance violations. "
        "Scan all Python files under modules/ and config/. "
        "Check for: hardcoded values, relative imports, direct logging imports, "
        "datetime.now() usage, os.getenv() fallbacks, and file size limits. "
        "Produce a structured report of all violations with severity ratings."
    ),
}


# ---------------------------------------------------------------------------
# Build a roster from the agent catalog (no DB needed)
# ---------------------------------------------------------------------------

def build_roster_from_catalog(agent_names: list[str] | None = None):
    """Build a Roster from the on-disk agent catalog YAML files.

    If agent_names is None, includes all enabled agents.
    No database required — reads YAML directly.
    """
    from modules.backend.agents.mission_control.roster import (
        Roster,
        RosterAgentEntry,
        RosterConstraintsSchema,
        RosterInterfaceSchema,
        RosterModelSchema,
    )
    from modules.backend.core.agent_registry import AgentRegistry

    registry = AgentRegistry()
    catalog = registry.list_all()  # list[dict] with agent_name, description, etc.

    entries = []
    for item in catalog:
        name = item.get("agent_name", "")
        if agent_names and name not in agent_names:
            continue

        try:
            config = registry.get(name)
        except KeyError:
            continue

        model_schema = config.model
        model_name = model_schema.name if hasattr(model_schema, "name") else str(model_schema)

        interface = getattr(config, "interface", None)
        input_schema = getattr(interface, "input", {}) if interface else {}
        output_schema = getattr(interface, "output", {}) if interface else {}

        entries.append(RosterAgentEntry(
            agent_name=name,
            agent_version=config.version or "1.0.0",
            description=config.description or "",
            model=RosterModelSchema(
                name=model_name,
                temperature=getattr(model_schema, "temperature", 0.0) if hasattr(model_schema, "temperature") else 0.0,
                max_tokens=getattr(model_schema, "max_tokens", 4096) if hasattr(model_schema, "max_tokens") else 4096,
            ),
            tools=config.tools or [],
            interface=RosterInterfaceSchema(
                input=input_schema if isinstance(input_schema, dict) else {},
                output=output_schema if isinstance(output_schema, dict) else {},
            ),
            constraints=RosterConstraintsSchema(
                timeout_seconds=120,
                cost_ceiling_usd=config.max_budget_usd or 1.0,
            ),
        ))

    return Roster(agents=entries)


# ---------------------------------------------------------------------------
# Main test flow
# ---------------------------------------------------------------------------

async def run_planning_test(
    model_override: str | None,
    brief_key: str,
    custom_brief: str | None,
    mission_id: str,
    show_prompt: bool,
    show_raw: bool,
    dry_run: bool,
    agent_names: list[str] | None,
) -> dict:
    """Run the planning agent and return the full result with diagnostics."""
    from modules.backend.agents.deps.base import FileScope
    from modules.backend.agents.mission.planning.agent import (
        PlanningAgentDeps,
        create_agent,
        extract_task_plan_json,
    )
    from modules.backend.agents.mission_control.helpers.model_builder import (
        _build_model,
        _get_model_name,
        build_model_settings,
    )
    from modules.backend.agents.mission_control.helpers.prompt_builder import (
        _build_planning_prompt,
        _build_roster_prompt,
    )
    from modules.backend.agents.mission_control.plan_validator import validate_plan
    from modules.backend.agents.mission_control.registry import get_registry
    from modules.backend.core.config import find_project_root, get_default_budget_usd

    click.echo(click.style("=" * 70, fg="cyan"))
    click.echo(click.style("  PLANNING AGENT TEST HARNESS", fg="cyan", bold=True))
    click.echo(click.style("=" * 70, fg="cyan"))

    # ── Resolve model ────────────────────────────────────────────
    registry = get_registry()
    planning_cfg = registry.get("mission.planning.agent")

    if model_override:
        model = _build_model(model_override)
        model_name = model_override
        model_settings = build_model_settings(planning_cfg)
    else:
        model = _build_model(planning_cfg.model)
        model_name = _get_model_name(planning_cfg.model)
        model_settings = build_model_settings(planning_cfg)

    click.echo(f"\n  Model:      {click.style(model_name, bold=True)}")

    # ── Build roster ─────────────────────────────────────────────
    roster = build_roster_from_catalog(agent_names)
    roster_desc = _build_roster_prompt(roster)
    click.echo(f"  Roster:     {len(roster.agents)} agents")
    for a in roster.agents:
        click.echo(f"              - {a.agent_name} ({a.model.name})")

    # ── Build brief ──────────────────────────────────────────────
    brief = custom_brief or BRIEFS.get(brief_key, BRIEFS["wasa"])
    click.echo(f"  Brief:      {brief_key}" + (" (custom)" if custom_brief else ""))
    click.echo(f"  Mission ID: {mission_id}")

    # ── Build prompt ─────────────────────────────────────────────
    planning_prompt = _build_planning_prompt(
        mission_brief=brief,
        mission_id=mission_id,
        roster_description=roster_desc,
        upstream_context=None,
    )

    prompt_tokens_est = len(planning_prompt) // 4
    click.echo(f"  Prompt:     ~{prompt_tokens_est} tokens ({len(planning_prompt)} chars)")

    if show_prompt:
        click.echo(click.style("\n── FULL PROMPT ──", fg="yellow"))
        click.echo(planning_prompt)
        click.echo(click.style("── END PROMPT ──\n", fg="yellow"))

    if dry_run:
        click.echo(click.style("\n  [DRY RUN] Skipping LLM call.\n", fg="yellow"))
        return {"dry_run": True, "prompt_chars": len(planning_prompt)}

    # ── Call the planning agent ──────────────────────────────────
    agent = create_agent(model)
    deps = PlanningAgentDeps(
        project_root=find_project_root(),
        scope=FileScope(read_paths=[], write_paths=[]),
        mission_brief=brief,
        roster_description=roster_desc,
    )

    click.echo(click.style("\n  Calling planning agent...", fg="cyan"))
    start = time.monotonic()
    full_content = ""

    try:
        async with agent.run_stream(
            planning_prompt, deps=deps, model_settings=model_settings,
        ) as stream:
            async for text in stream.stream_text(delta=True):
                full_content += text

            usage = stream.usage()

        duration = time.monotonic() - start

        # Extract thinking trace
        thinking_trace = None
        if hasattr(stream, "all_messages"):
            for msg in stream.all_messages():
                for part in getattr(msg, "parts", []):
                    if hasattr(part, "content") and hasattr(part, "part_kind"):
                        if "thinking" in str(getattr(part, "part_kind", "")):
                            thinking_trace = part.content

    except Exception as e:
        duration = time.monotonic() - start
        click.echo(click.style(f"\n  LLM call failed ({duration:.1f}s): {e}", fg="red", bold=True))
        return {"error": str(e), "duration": duration}

    # ── Display raw output ───────────────────────────────────────
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0

    click.echo(f"  Duration:   {duration:.1f}s")
    click.echo(f"  Tokens:     {input_tokens} in / {output_tokens} out")
    click.echo(f"  Output:     {len(full_content)} chars")

    if thinking_trace:
        click.echo(f"  Thinking:   {len(thinking_trace)} chars")

    if show_raw:
        click.echo(click.style("\n── RAW OUTPUT ──", fg="yellow"))
        click.echo(full_content)
        click.echo(click.style("── END RAW OUTPUT ──\n", fg="yellow"))

    # ── Extract JSON ─────────────────────────────────────────────
    click.echo(click.style("\n  Extracting TaskPlan JSON...", fg="cyan"))

    try:
        plan_dict = extract_task_plan_json(full_content, mission_id=mission_id)
        click.echo(click.style("  Schema + semantic validation: PASSED", fg="green", bold=True))
    except ValueError as e:
        click.echo(click.style(f"  Extraction/validation FAILED:", fg="red", bold=True))
        click.echo(f"  {e}")
        # Try to show what was parsed
        try:
            import re
            raw_json = None
            stripped = full_content.strip()
            if stripped.startswith("{"):
                raw_json = json.loads(stripped)
            else:
                m = re.search(r"```(?:json)?\s*\n(.*?)\n```", stripped, re.DOTALL)
                if m:
                    raw_json = json.loads(m.group(1))
            if raw_json:
                click.echo(click.style("\n  Parsed JSON (pre-validation):", fg="yellow"))
                click.echo(json.dumps(raw_json, indent=2)[:2000])
        except Exception:
            pass
        return {
            "error": str(e),
            "raw_output": full_content[:1000],
            "duration": duration,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }

    # ── Plan validator (requires roster) ─────────────────────────
    click.echo(click.style("  Running plan_validator (11 rules)...", fg="cyan"))

    from modules.backend.schemas.task_plan import TaskPlan
    plan = TaskPlan.model_validate(plan_dict)
    budget = get_default_budget_usd()
    validation = validate_plan(plan, roster, budget)

    if validation.is_valid:
        click.echo(click.style("  Plan validator: PASSED", fg="green", bold=True))
    else:
        click.echo(click.style("  Plan validator: FAILED", fg="red", bold=True))
        for err in validation.errors:
            click.echo(click.style(f"    - {err}", fg="red"))

    # ── Display plan ─────────────────────────────────────────────
    tasks = plan_dict.get("tasks", [])
    click.echo(click.style(f"\n── TASK PLAN ({len(tasks)} tasks) ──", fg="cyan", bold=True))
    click.echo(f"  Summary:  {plan_dict.get('summary', '')}")
    click.echo(f"  Version:  {plan_dict.get('version', '?')}")
    click.echo(f"  Est cost: ${plan_dict.get('estimated_cost_usd', 0):.4f}")
    click.echo(f"  Est time: {plan_dict.get('estimated_duration_seconds', 0)}s")

    click.echo(f"\n  {'Task ID':<20s} {'Agent':<40s} {'Deps'}")
    click.echo(f"  {'─' * 20} {'─' * 40} {'─' * 20}")
    for task in tasks:
        tid = task.get("task_id", "?")
        agent = task.get("agent", "?")
        deps = ", ".join(task.get("dependencies", [])) or "—"
        click.echo(f"  {tid:<20s} {agent:<40s} {deps}")

    for task in tasks:
        click.echo(f"\n  {click.style(task.get('task_id', '?'), bold=True)}")
        click.echo(f"    Description:  {task.get('description', '')[:100]}")
        click.echo(f"    Instructions: {task.get('instructions', '')[:150]}")
        inputs = task.get("inputs", {})
        static = inputs.get("static", {})
        upstream = inputs.get("from_upstream", {})
        if static:
            click.echo(f"    Static inputs: {json.dumps(static, default=str)[:150]}")
        if upstream:
            click.echo(f"    Upstream refs: {json.dumps(upstream, default=str)[:150]}")
        verification = task.get("verification", {})
        t3 = verification.get("tier_3", {})
        if t3.get("requires_ai_evaluation"):
            click.echo(f"    Tier 3 eval:  {t3.get('evaluator_agent', '?')}")

    # ── Full JSON dump ───────────────────────────────────────────
    click.echo(click.style("\n── FULL PLAN JSON ──", fg="yellow"))
    click.echo(json.dumps(plan_dict, indent=2, default=str))

    if thinking_trace:
        click.echo(click.style("\n── THINKING TRACE (truncated) ──", fg="magenta"))
        click.echo(thinking_trace[:1000])

    click.echo(click.style("\n" + "=" * 70, fg="cyan"))

    return {
        "success": validation.is_valid,
        "task_count": len(tasks),
        "model": model_name,
        "duration": duration,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "plan": plan_dict,
        "validation_errors": validation.errors if not validation.is_valid else [],
        "has_thinking": thinking_trace is not None,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command()
@click.option("--model", "-m", default=None, help="Model override, e.g. anthropic:claude-sonnet-4-6")
@click.option(
    "--brief", "-b",
    type=click.Choice(list(BRIEFS.keys()) + ["custom"]),
    default="wasa",
    help="Mission brief to use.",
)
@click.option("--custom", "custom_brief", default=None, help="Custom brief text (use with --brief custom).")
@click.option("--mission-id", default="test-planning-001", help="Mission ID for the plan.")
@click.option("--show-prompt", is_flag=True, help="Print the full prompt sent to the model.")
@click.option("--show-raw", is_flag=True, help="Print raw model output before parsing.")
@click.option("--dry-run", is_flag=True, help="Build prompt and roster only, skip LLM call.")
@click.option("--agents", default=None, help="Comma-separated agent names to include in roster.")
@click.option("-v", "--verbose", is_flag=True, help="INFO logging.")
@click.option("-d", "--debug", is_flag=True, help="DEBUG logging.")
def main(
    model: str | None,
    brief: str,
    custom_brief: str | None,
    mission_id: str,
    show_prompt: bool,
    show_raw: bool,
    dry_run: bool,
    agents: str | None,
    verbose: bool,
    debug: bool,
) -> None:
    """Test the Planning Agent flow without a full server run."""
    from modules.backend.core.logging import setup_logging

    if debug:
        setup_logging(level="DEBUG", format_type="console")
    elif verbose:
        setup_logging(level="INFO", format_type="console")
    else:
        setup_logging(level="WARNING", format_type="console")

    agent_names = [a.strip() for a in agents.split(",")] if agents else None

    result = asyncio.run(run_planning_test(
        model_override=model,
        brief_key=brief,
        custom_brief=custom_brief,
        mission_id=mission_id,
        show_prompt=show_prompt,
        show_raw=show_raw,
        dry_run=dry_run,
        agent_names=agent_names,
    ))

    # Exit code: 0 on success, 1 on validation failure, 2 on LLM error
    if result.get("error"):
        sys.exit(2)
    elif result.get("dry_run"):
        sys.exit(0)
    elif not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
