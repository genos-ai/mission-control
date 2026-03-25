"""
CLI handler for execution commands.

Full execution lifecycle: create, execute, list, detail, cost.
All operations go through proper service layers with real DB persistence.
"""

import asyncio
import sys

import click

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


class _AbortExecution(Exception):
    """Raised by async actions to signal a clean exit (output already printed)."""
    pass


def run_execution(
    cli_logger,
    action: str,
    objective: str | None,
    execution_id: str | None,
    roster: str,
    budget: float | None,
    triggered_by: str,
    output_format: str = "human",
    mission_id: str | None = None,
) -> None:
    """Dispatch execution CLI actions."""
    actions = {
        "create": _action_create,
        "execute": _action_execute,
        "run": _action_run,
        "list": _action_list,
        "detail": _action_detail,
        "plan": _action_plan,
        "cost": _action_cost,
    }

    handler = actions.get(action)
    if not handler:
        click.echo(
            click.style(
                f"Unknown execution action: {action}. "
                f"Valid: {', '.join(actions.keys())}",
                fg="red",
            ),
            err=True,
        )
        sys.exit(1)

    try:
        asyncio.run(handler(
            cli_logger,
            objective=objective,
            execution_id=execution_id,
            roster=roster,
            budget=budget,
            triggered_by=triggered_by,
            output_format=output_format,
            mission_id=mission_id,
        ))
    except _AbortExecution:
        sys.exit(1)
    except Exception as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)
        cli_logger.error("Execution action failed", extra={"action": action, "error": str(e)})
        sys.exit(1)


# =============================================================================
# Actions
# =============================================================================


async def _action_create(cli_logger, *, objective, execution_id, roster, budget, triggered_by, output_format, mission_id):
    """Create an execution (PENDING state)."""
    if not objective:
        click.echo(click.style("Error: --objective is required for create.", fg="red"), err=True)
        raise _AbortExecution("objective required")

    from modules.backend.services.execution import ExecutionService
    from modules.clients.cli.mission_context import _async_resolve_current_mission_id

    if not mission_id:
        mission_id = await _async_resolve_current_mission_id()

    async with ExecutionService.factory() as service:
        execution = await service.create_adhoc_execution(
            objective=objective,
            triggered_by=triggered_by,
            session_id=_generate_session_id(),
            roster_ref=roster,
            cost_ceiling_usd=budget,
            mission_id=mission_id,
        )

    click.echo(click.style("Execution created", fg="green", bold=True))
    click.echo(f"  ID:        {execution.id}")
    click.echo(f"  Status:    {execution.status.value}")
    click.echo(f"  Roster:    {execution.roster_ref}")
    click.echo(f"  Budget:    ${execution.cost_ceiling_usd:.2f}" if execution.cost_ceiling_usd else "  Budget:    default")
    click.echo(f"  Objective: {execution.objective[:100]}")
    click.echo()
    click.echo(f"Execute with: python cli.py execution execute {execution.id}")


async def _action_execute(cli_logger, *, objective, execution_id, roster, budget, triggered_by, output_format, mission_id):
    """Execute an existing execution (PENDING -> RUNNING -> COMPLETED)."""
    if not execution_id:
        click.echo(click.style("Error: --execution-id is required for execute.", fg="red"), err=True)
        raise _AbortExecution("execution-id required")

    await _preflight_gate(roster)

    from modules.clients.cli.live_display import LiveExecutionDisplay
    from modules.clients.cli.report import render_execution
    from modules.backend.services.execution import ExecutionService

    click.echo(f"Executing {execution_id}...")
    click.echo()

    display = LiveExecutionDisplay()
    event_bus = display.create_event_bus()

    async with ExecutionService.factory(event_bus=event_bus) as service:
        with display.start():
            execution = await service.run_execution(execution_id)

    await render_execution(execution, output_format)


async def _action_run(cli_logger, *, objective, execution_id, roster, budget, triggered_by, output_format, mission_id):
    """Create + execute in one step (convenience)."""
    if not objective:
        click.echo(click.style("Error: --objective is required for run.", fg="red"), err=True)
        raise _AbortExecution("objective required")

    await _preflight_gate(roster)

    from modules.clients.cli.live_display import LiveExecutionDisplay
    from modules.clients.cli.report import render_execution
    from modules.backend.services.execution import ExecutionService
    from modules.clients.cli.mission_context import _async_resolve_current_mission_id

    if not mission_id:
        mission_id = await _async_resolve_current_mission_id()

    click.echo("Creating and executing...")
    click.echo()

    display = LiveExecutionDisplay()
    event_bus = display.create_event_bus()

    async with ExecutionService.factory(event_bus=event_bus) as service:
        execution = await service.create_adhoc_execution(
            objective=objective,
            triggered_by=triggered_by,
            session_id=_generate_session_id(),
            roster_ref=roster,
            cost_ceiling_usd=budget,
            mission_id=mission_id,
        )
        click.echo(f"  Execution ID: {execution.id}")

        with display.start():
            execution = await service.run_execution(execution.id)

    await render_execution(execution, output_format)


async def _action_list(cli_logger, *, objective, execution_id, roster, budget, triggered_by, output_format, mission_id):
    """List executions."""
    from modules.clients.cli.report import get_console, build_table, styled_status
    from modules.backend.services.execution import ExecutionService

    async with ExecutionService.factory() as service:
        executions, total = await service.list_executions(limit=20)

    if not executions:
        click.echo("No executions found.")
        return

    console = get_console()
    table = build_table(f"Executions ({total} total)", columns=[
        ("Date/Time",  {"style": "dim", "width": 16}),
        ("ID",         {"style": "cyan", "width": 36}),
        ("Status",     {"width": 10}),
        ("Cost",       {"justify": "right", "width": 8}),
        ("Trigger",    {"style": "dim", "width": 12}),
        ("Objective",  {"ratio": 1}),
    ])

    for e in executions:
        obj_preview = e.objective[:60] + "..." if len(e.objective) > 60 else e.objective
        dt_str = e.created_at.strftime("%Y-%m-%d %H:%M") if e.created_at else "—"
        table.add_row(
            dt_str, str(e.id), styled_status(e.status),
            f"${e.total_cost_usd:.4f}", e.triggered_by, obj_preview,
        )

    console.print(table)


async def _action_detail(cli_logger, *, objective, execution_id, roster, budget, triggered_by, output_format, mission_id):
    """Show execution detail."""
    if not execution_id:
        click.echo(click.style("Error: --execution-id is required for detail.", fg="red"), err=True)
        raise _AbortExecution("execution-id required")

    from modules.clients.cli.report import (
        get_console, styled_status,
        primary_panel, info_panel, status_panel,
        render_task_outputs,
    )
    from modules.backend.services.execution import ExecutionService

    async with ExecutionService.factory() as service:
        try:
            execution = await service.get_execution(execution_id)
        except Exception as e:
            logger.warning("Execution lookup failed", extra={"execution_id": execution_id, "error": str(e)})
            click.echo(click.style(f"Execution '{execution_id}' not found.", fg="red"), err=True)
            raise _AbortExecution("execution not found")

    console = get_console()

    info_lines = [
        f"[bold]ID:[/bold]        {execution.id}",
        f"[bold]Status:[/bold]    {styled_status(execution.status)}",
        f"[bold]Created:[/bold]   {execution.created_at.strftime('%Y-%m-%d %H:%M:%S') if execution.created_at else '—'}",
        f"[bold]Started:[/bold]   {execution.started_at or '—'}",
        f"[bold]Finished:[/bold]  {execution.completed_at or '—'}",
        f"[bold]Roster:[/bold]    {execution.roster_ref}",
        f"[bold]Cost:[/bold]      ${execution.total_cost_usd:.4f}" + (f"  (ceiling: ${execution.cost_ceiling_usd:.2f})" if execution.cost_ceiling_usd else ""),
        f"[bold]Trigger:[/bold]   {execution.triggered_by}",
        f"[bold]Session:[/bold]   {execution.session_id}",
    ]
    console.print(primary_panel(content="\n".join(info_lines), title="Execution Detail"))

    console.print(info_panel(content=execution.objective, title="Objective"))

    if execution.result_summary:
        console.print(status_panel(content=execution.result_summary, status="completed", title="Result Summary"))

    outcome = execution.execution_outcome
    if outcome and isinstance(outcome, dict):
        tasks = outcome.get("task_results") or outcome.get("task_outcomes") or []
        if tasks:
            render_task_outputs(console, tasks)

    if execution.error_data:
        console.print(status_panel(content=str(execution.error_data), status="failed", title="Error"))


async def _action_plan(cli_logger, *, objective, execution_id, roster, budget, triggered_by, output_format, mission_id):
    """Show the TaskPlan DAG for an execution."""
    if not execution_id:
        click.echo(click.style("Error: --execution-id is required for plan.", fg="red"), err=True)
        raise _AbortExecution("execution-id required")

    import json as _json

    from modules.clients.cli.report import (
        get_console, build_table, primary_panel, info_panel, styled_status,
    )
    from modules.backend.services.execution import ExecutionService

    async with ExecutionService.factory() as service:
        try:
            execution = await service.get_execution(execution_id)
        except Exception as e:
            logger.warning("Execution lookup failed", extra={"execution_id": execution_id, "error": str(e)})
            click.echo(click.style(f"Execution '{execution_id}' not found.", fg="red"), err=True)
            raise _AbortExecution("execution not found")

    outcome = execution.execution_outcome
    if not outcome or not isinstance(outcome, dict):
        click.echo(click.style("No plan data — execution may not have been run.", fg="yellow"))
        return

    plan_ref = outcome.get("task_plan_reference")
    if not plan_ref:
        click.echo(click.style("No task plan stored for this execution.", fg="yellow"))
        return

    plan = _json.loads(plan_ref) if isinstance(plan_ref, str) else plan_ref

    task_results = outcome.get("task_results") or outcome.get("task_outcomes") or []
    results_by_id = {r.get("task_id"): r for r in task_results if isinstance(r, dict)}

    console = get_console()

    actual_cost = outcome.get("total_cost_usd", 0)
    actual_duration = outcome.get("total_duration_seconds", 0)
    info_lines = [
        f"[bold]Execution:[/bold]    {execution_id}",
        f"[bold]Status:[/bold]       {styled_status(outcome.get('status', '—'))}",
        f"[bold]Summary:[/bold]      {plan.get('summary', '—')}",
        f"[bold]Est. Cost:[/bold]    ${plan.get('estimated_cost_usd', 0):.4f}    [bold]Actual:[/bold] ${actual_cost:.4f}",
        f"[bold]Est. Duration:[/bold] {plan.get('estimated_duration_seconds', 0)}s      [bold]Actual:[/bold] {actual_duration:.1f}s",
        f"[bold]Version:[/bold]      {plan.get('version', '—')}",
    ]
    hints = plan.get("execution_hints", {})
    if hints.get("critical_path"):
        info_lines.append(f"[bold]Critical Path:[/bold] {', '.join(hints['critical_path'])}")
    if hints.get("min_success_threshold"):
        info_lines.append(f"[bold]Min Success:[/bold]  {hints['min_success_threshold']:.0%}")

    console.print(primary_panel(content="\n".join(info_lines), title="Task Plan"))

    tasks = plan.get("tasks", [])
    if tasks:
        def _tier_icon(verification_outcome: dict, tier: str) -> str:
            tier_data = verification_outcome.get(tier, {})
            status = tier_data.get("status", "skipped")
            if status == "pass":
                return "[green]\u2713[/green]"
            elif status == "fail":
                return "[red]\u2717[/red]"
            return "[dim]\u2014[/dim]"

        table = build_table(f"Tasks ({len(tasks)})", columns=[
            ("Task ID",      {"style": "cyan", "width": 20}),
            ("Agent",        {"width": 28}),
            ("Status",       {"width": 10}),
            ("Cost",         {"justify": "right", "width": 10}),
            ("Duration",     {"justify": "right", "width": 10}),
            ("Retries",      {"justify": "right", "width": 8}),
            ("T1",           {"justify": "center", "width": 4}),
            ("T2",           {"justify": "center", "width": 4}),
            ("T3",           {"justify": "center", "width": 4}),
            ("Dependencies", {"style": "dim", "width": 20}),
        ], show_lines=True)

        for t in tasks:
            tid = t.get("task_id", "—")
            deps = ", ".join(t.get("dependencies", []))
            result = results_by_id.get(tid, {})
            verification = result.get("verification_outcome", {})

            table.add_row(
                tid,
                t.get("agent", "—"),
                styled_status(result.get("status", "—")),
                f"${result.get('cost_usd', 0):.4f}" if result else "—",
                f"{result.get('duration_seconds', 0):.1f}s" if result else "—",
                str(result.get("retry_count", 0)) if result else "—",
                _tier_icon(verification, "tier_1"),
                _tier_icon(verification, "tier_2"),
                _tier_icon(verification, "tier_3"),
                deps or "—",
            )
        console.print(table)

    for t in tasks:
        tid = t.get("task_id", "—")
        plan_verification = t.get("verification", {})
        inputs = t.get("inputs", {})
        result = results_by_id.get(tid, {})

        detail_lines = [
            f"[bold]Agent:[/bold]    {t.get('agent', '—')} v{t.get('agent_version', '?')}",
        ]

        static = inputs.get("static", {})
        if static:
            detail_lines.append(f"[bold]Inputs:[/bold]   {_json.dumps(static, default=str)[:120]}")

        upstream = inputs.get("from_upstream", {})
        if upstream:
            refs = [f"{k} \u2190 {v.get('source_task', '?')}.{v.get('source_field', '?')}" for k, v in upstream.items()]
            detail_lines.append(f"[bold]Upstream:[/bold] {', '.join(refs)}")

        t1 = plan_verification.get("tier_1", {})
        t2 = plan_verification.get("tier_2", {})
        t3 = plan_verification.get("tier_3", {})
        if t1.get("required_output_fields"):
            detail_lines.append(f"[bold]T1 Fields:[/bold] {', '.join(t1['required_output_fields'])}")
        if t2.get("deterministic_checks"):
            checks = [c.get("check") for c in t2["deterministic_checks"]]
            detail_lines.append(f"[bold]T2 Checks:[/bold] {', '.join(checks)}")
        if t3.get("requires_ai_evaluation"):
            detail_lines.append(f"[bold]T3 Eval:[/bold]  {t3.get('evaluator_agent', '—')} (min: {t3.get('min_evaluation_score', '—')})")

        retry_history = result.get("retry_history", [])
        if retry_history:
            detail_lines.append("")
            detail_lines.append("[bold]Retry History:[/bold]")
            for entry in retry_history:
                tier = entry.get("failure_tier", "?")
                reason = entry.get("failure_reason", "")[:80]
                detail_lines.append(f"  Attempt {entry.get('attempt', '?')} \u2014 Tier {tier}: {reason}")

        console.print(info_panel(content="\n".join(detail_lines), title=tid))

    console.print()


async def _action_cost(cli_logger, *, objective, execution_id, roster, budget, triggered_by, output_format, mission_id):
    """Show execution cost breakdown."""
    if not execution_id:
        click.echo(click.style("Error: --execution-id is required for cost.", fg="red"), err=True)
        raise _AbortExecution("execution-id required")

    # Same data source as list/detail/plan — no bridge to execution_records.
    from modules.backend.services.execution import ExecutionService

    async with ExecutionService.factory() as service:
        try:
            execution = await service.get_execution(execution_id)
        except Exception as e:
            logger.warning("Execution lookup failed", extra={"execution_id": execution_id, "error": str(e)})
            click.echo(click.style(f"Execution '{execution_id}' not found.", fg="red"), err=True)
            raise _AbortExecution("execution not found")

    outcome = execution.execution_outcome
    if not outcome or not isinstance(outcome, dict):
        click.echo(click.style("No cost data — execution may not have been run.", fg="yellow"))
        return

    from modules.clients.cli.report import get_console, build_table, primary_panel

    console = get_console()

    task_results = outcome.get("task_results") or []
    total_input = 0
    total_output = 0
    for tr in task_results:
        usage = tr.get("token_usage", {})
        total_input += usage.get("input", 0)
        total_output += usage.get("output", 0)

    info_lines = [
        f"[bold]Execution:[/bold]     {execution_id}",
        f"[bold]Total Cost:[/bold]    ${execution.total_cost_usd:.4f}",
        f"[bold]Input Tokens:[/bold]  {total_input:,}",
        f"[bold]Output Tokens:[/bold] {total_output:,}",
    ]
    console.print(primary_panel(content="\n".join(info_lines), title="Cost Breakdown"))

    if task_results:
        table = build_table("Task Costs", columns=[
            ("Task",     {"style": "cyan", "width": 12}),
            ("Agent",    {"width": 28}),
            ("Cost",     {"justify": "right", "width": 10}),
            ("Tokens",   {"justify": "right", "width": 14}),
            ("Duration", {"justify": "right", "width": 10}),
        ])
        for tr in task_results:
            usage = tr.get("token_usage", {})
            tokens = f"{usage.get('input', 0) + usage.get('output', 0):,}"
            dur = f"{tr.get('duration_seconds', 0):.1f}s" if tr.get('duration_seconds') else "—"
            table.add_row(
                tr.get("task_id", "—"), tr.get("agent_name", "—"),
                f"${tr.get('cost_usd', 0):.4f}", tokens, dur,
            )
        console.print(table)


# =============================================================================
# Helpers
# =============================================================================


def _generate_session_id() -> str:
    """Generate a session ID for CLI executions."""
    from uuid import uuid4
    return str(uuid4())


async def _preflight_gate(roster: str) -> None:
    """Run preflight credit check; abort if any model fails."""
    from modules.backend.agents.preflight import preflight_check

    click.echo("Preflight credit check...")
    result = await preflight_check(roster_name=roster)
    if result.ok:
        click.echo(click.style("  All models OK", fg="green"))
        click.echo()
        return

    for check in result.failed:
        label = "insufficient credits" if check.error_type == "insufficient_credits" else check.error
        click.echo(click.style(f"  \u2717 {check.model_name}: {label}", fg="red"))
    click.echo()
    click.echo(click.style("Aborting — fix credit issues before running.", fg="red"), err=True)
    raise _AbortExecution("preflight failed")
