"""
CLI handler for workflow commands.

List available workflows, execute workflow runs, inspect results,
and render reports in multiple output formats.
"""

import asyncio
import sys

import click

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def run_workflow_cli(
    cli_logger,
    action: str,
    workflow_name: str | None,
    run_id: str | None,
    triggered_by: str,
    output_format: str = "human",
    project_name: str | None = None,
    gate: object | None = None,
) -> None:
    """Dispatch workflow CLI actions."""
    actions = {
        "list": _action_list,
        "detail": _action_detail,
        "run": _action_run,
        "runs": _action_runs,
        "run-detail": _action_run_detail,
        "report": _action_report,
    }

    handler = actions.get(action)
    if not handler:
        click.echo(
            click.style(
                f"Unknown workflow action: {action}. "
                f"Valid: {', '.join(actions.keys())}",
                fg="red",
            ),
            err=True,
        )
        sys.exit(1)

    try:
        asyncio.run(handler(
            cli_logger,
            workflow_name=workflow_name,
            run_id=run_id,
            triggered_by=triggered_by,
            output_format=output_format,
            project_name=project_name,
            gate=gate,
        ))
    except Exception as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)
        cli_logger.error(
            "Workflow action failed",
            extra={"action": action, "error": str(e)},
        )
        sys.exit(1)


# =============================================================================
# Actions
# =============================================================================


async def _action_list(cli_logger, *, workflow_name, run_id, triggered_by, output_format, **_):
    """List available workflows."""
    from modules.clients.cli.report import get_console, build_table
    from modules.backend.services.workflow import WorkflowService

    service = WorkflowService()
    workflows = service.list_workflows(enabled_only=False)

    if not workflows:
        click.echo("No workflows found.")
        return

    console = get_console()
    table = build_table(f"Workflows ({len(workflows)} available)", columns=[
        ("Name",        {"style": "cyan", "width": 36}),
        ("Ver",         {"justify": "right", "width": 4}),
        ("Enabled",     {"width": 8}),
        ("Budget",      {"justify": "right", "width": 8}),
        ("Steps",       {"justify": "right", "width": 6}),
        ("Description", {"ratio": 1}),
    ])

    for w in workflows:
        enabled = "[green]yes[/green]" if w.enabled else "[red]no[/red]"
        table.add_row(
            w.workflow_name,
            str(w.version),
            enabled,
            f"${w.budget.max_cost_usd:.2f}",
            str(len(w.steps)),
            w.description[:80],
        )

    console.print(table)


async def _action_detail(cli_logger, *, workflow_name, run_id, triggered_by, output_format, **_):
    """Show workflow detail."""
    if not workflow_name:
        click.echo(click.style("Error: workflow name is required for detail.", fg="red"), err=True)
        sys.exit(1)

    from modules.clients.cli.report import get_console, build_table, primary_panel, info_panel
    from modules.backend.services.workflow import WorkflowService

    service = WorkflowService()
    workflow = service.get_workflow(workflow_name)

    if not workflow:
        click.echo(click.style(f"Workflow '{workflow_name}' not found.", fg="red"), err=True)
        sys.exit(1)

    console = get_console()

    enabled_str = "[green]yes[/green]" if workflow.enabled else "[red]no[/red]"
    info_lines = [
        f"[bold]Name:[/bold]        {workflow.workflow_name}",
        f"[bold]Description:[/bold] {workflow.description}",
        f"[bold]Version:[/bold]     {workflow.version}",
        f"[bold]Enabled:[/bold]     {enabled_str}",
        f"[bold]Trigger:[/bold]     {workflow.trigger.type}",
        f"[bold]Budget:[/bold]      ${workflow.budget.max_cost_usd:.2f}",
    ]
    console.print(primary_panel(content="\n".join(info_lines), title="Workflow Detail"))

    obj_lines = [
        f"[bold]Statement:[/bold] {workflow.objective.statement}",
        f"[bold]Category:[/bold]  {workflow.objective.category}",
        f"[bold]Owner:[/bold]     {workflow.objective.owner}",
        f"[bold]Priority:[/bold]  {workflow.objective.priority}",
    ]
    if workflow.trigger.match_patterns:
        obj_lines.append(f"[bold]Triggers:[/bold]  {', '.join(workflow.trigger.match_patterns)}")
    console.print(info_panel(content="\n".join(obj_lines), title="Objective"))

    if workflow.context:
        ctx_lines = [f"[bold]{k}:[/bold] {v}" for k, v in workflow.context.items()]
        console.print(info_panel(content="\n".join(ctx_lines), title="Context"))

    table = build_table("Steps", columns=[
        ("ID",          {"style": "cyan", "width": 20}),
        ("Capability",  {"width": 28}),
        ("Budget",      {"justify": "right", "width": 8}),
        ("Env",         {"width": 10}),
        ("Depends On",  {"style": "dim", "width": 20}),
        ("Description", {"ratio": 1}),
    ], show_lines=True)

    for step in workflow.steps:
        ceiling = f"${step.cost_ceiling_usd:.2f}" if step.cost_ceiling_usd else "default"
        deps = ", ".join(step.depends_on) if step.depends_on else ""
        table.add_row(
            step.id,
            step.capability,
            ceiling,
            step.environment,
            deps,
            step.description or "",
        )

    console.print(table)


async def _action_run(cli_logger, *, workflow_name, run_id, triggered_by, output_format, project_name=None, gate=None, **_):
    """Execute a workflow."""
    if not workflow_name:
        click.echo(click.style("Error: --workflow-name is required for run.", fg="red"), err=True)
        sys.exit(1)

    await _preflight_gate(workflow_name)

    from modules.backend.core.database import get_async_session
    from modules.clients.cli.report import (
        get_console, build_table, styled_status, status_panel,
        info_panel, render_mission_outcomes,
        workflow_run_to_dict, generate_narrative, colorize_narrative,
    )
    from modules.backend.services.mission import MissionService
    from modules.backend.services.workflow_run import WorkflowRunService

    from rich.live import Live

    console = get_console()
    console.print(f"[bold]Running workflow:[/bold] {workflow_name}\n")

    progress_state: dict = {"steps": {}, "total": 0, "workflow": workflow_name}

    def _build_progress_table():
        table = build_table(columns=[
            ("Step",        {"style": "cyan", "width": 22}),
            ("Capability",  {"width": 28}),
            ("Status",      {"width": 12}),
            ("Cost",        {"justify": "right", "width": 8}),
            ("Description", {"ratio": 1}),
        ])

        for step_id, info in progress_state["steps"].items():
            status = info.get("status", "running")
            if status == "running":
                status_str = "[yellow]running...[/yellow]"
            else:
                status_str = styled_status(status)
            cost = f"${info.get('cost_usd', 0):.4f}" if "cost_usd" in info else "—"
            table.add_row(
                step_id,
                info.get("capability", ""),
                status_str,
                cost,
                info.get("description", ""),
            )
        return table

    live = Live(_build_progress_table(), console=console, refresh_per_second=4)

    def on_progress(event: dict) -> None:
        etype = event.get("type", "")
        if etype == "workflow_start":
            progress_state["total"] = event.get("total_steps", 0)
        elif etype == "step_start":
            progress_state["steps"][event["step_id"]] = {
                "capability": event.get("capability", ""),
                "description": event.get("description", ""),
                "status": "running",
            }
            live.update(_build_progress_table())
        elif etype == "step_done":
            sid = event["step_id"]
            if sid in progress_state["steps"]:
                progress_state["steps"][sid]["status"] = event.get("status", "done")
                progress_state["steps"][sid]["cost_usd"] = event.get("cost_usd", 0)
            live.update(_build_progress_table())

    async with get_async_session() as db:
        run_service = WorkflowRunService(
            session=db,
            mission_service_factory=MissionService.factory,
        )

        with live:
            run = await run_service.run_workflow(
                workflow_name=workflow_name,
                triggered_by=triggered_by,
                on_progress=on_progress,
                project_name=project_name,
                gate=gate,
            )

        mission_service = MissionService(session=db)
        missions, _ = await mission_service.list_missions(
            playbook_run_id=run.id,
        )
        await db.commit()

    header = (
        f"[bold]{run.workflow_name}[/bold] v{run.workflow_version}    "
        f"Status: {styled_status(run.status)}    "
        f"Cost: ${run.total_cost_usd:.4f}"
    )
    if run.budget_usd:
        pct = (run.total_cost_usd / run.budget_usd) * 100
        header += f"  ({pct:.0f}% of ${run.budget_usd:.2f} budget)"

    console.print()
    console.print(status_panel(content=header, status=run.status))

    narrative = await generate_narrative(workflow_run_to_dict(run, missions))
    narrative = colorize_narrative(narrative)
    console.print(info_panel(content=narrative.strip(), title="Summary"))

    console.print()
    render_mission_outcomes(console, missions)


async def _action_runs(cli_logger, *, workflow_name, run_id, triggered_by, output_format, **_):
    """List workflow runs."""
    from modules.clients.cli.report import get_console, build_table, styled_status, DOTTED_ROWS
    from modules.backend.core.database import get_async_session
    from modules.backend.services.workflow_run import WorkflowRunService

    async with get_async_session() as db:
        run_service = WorkflowRunService(session=db)
        runs, total = await run_service.list_runs(
            workflow_name=workflow_name,
            limit=20,
        )

    if not runs:
        click.echo("No workflow runs found.")
        return

    console = get_console()
    table = build_table(f"Workflow Runs ({total} total)", columns=[
        ("Date/Time", {"style": "dim", "width": 16}),
        ("ID",        {"style": "cyan", "width": 36}),
        ("Workflow",  {"width": 24}),
        ("Status",    {"width": 10}),
        ("Cost",      {"justify": "right", "width": 8}),
        ("Trigger",   {"style": "dim", "width": 10}),
        ("Summary",   {"ratio": 1}),
    ], show_lines=True, table_box=DOTTED_ROWS)

    for r in runs:
        dt_str = r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "—"
        raw_summary = r.result_summary or ""
        summary = raw_summary[:80] + "..." if len(raw_summary) > 80 else raw_summary
        table.add_row(
            dt_str,
            str(r.id),
            r.workflow_name,
            styled_status(r.status),
            f"${r.total_cost_usd:.4f}",
            r.triggered_by,
            summary,
        )

    console.print(table)


async def _action_run_detail(cli_logger, *, workflow_name, run_id, triggered_by, output_format, **_):
    """Show workflow run detail with missions — uses the report renderer."""
    if not run_id:
        click.echo(click.style("Error: --run-id is required for run-detail.", fg="red"), err=True)
        sys.exit(1)

    run, missions = await _load_run_with_missions(run_id)
    from modules.clients.cli.report import render_workflow_run
    await render_workflow_run(run, missions, "human")


async def _action_report(cli_logger, *, workflow_name, run_id, triggered_by, output_format, **_):
    """Render a report for a past workflow run in the requested format."""
    if not run_id:
        click.echo(click.style("Error: --run-id is required for report.", fg="red"), err=True)
        sys.exit(1)

    run, missions = await _load_run_with_missions(run_id)
    from modules.clients.cli.report import render_workflow_run
    await render_workflow_run(run, missions, output_format)


# =============================================================================
# Helpers
# =============================================================================


async def _preflight_gate(workflow_name: str) -> None:
    """Run preflight credit check using rosters referenced by the workflow."""
    from modules.backend.agents.preflight import preflight_check
    from modules.backend.services.workflow import WorkflowService

    service = WorkflowService()
    workflow = service.get_workflow(workflow_name)
    if not workflow:
        return

    rosters = {step.roster for step in workflow.steps if step.roster}
    if not rosters:
        rosters = {"default"}

    click.echo("Preflight credit check...")
    for roster_name in sorted(rosters):
        result = await preflight_check(roster_name=roster_name)
        if result.ok:
            click.echo(click.style(f"  All models OK (roster: {roster_name})", fg="green"))
        else:
            for check in result.failed:
                label = "insufficient credits" if check.error_type == "insufficient_credits" else check.error
                click.echo(click.style(f"  ✗ {check.model_name}: {label}", fg="red"))
            click.echo()
            click.echo(click.style("Aborting — fix credit issues before running.", fg="red"), err=True)
            sys.exit(1)
    click.echo()


async def _load_run_with_missions(run_id: str):
    """Load a workflow run and its missions from the database."""
    from modules.backend.core.database import get_async_session
    from modules.backend.services.mission import MissionService
    from modules.backend.services.workflow_run import WorkflowRunService

    async with get_async_session() as db:
        mission_service = MissionService(session=db)
        run_service = WorkflowRunService(session=db)
        run = await run_service.get_run(run_id)
        if not run:
            click.echo(click.style(f"Workflow run '{run_id}' not found.", fg="red"), err=True)
            sys.exit(1)

        missions, _ = await mission_service.list_missions(
            playbook_run_id=run.id,
        )

    return run, missions
