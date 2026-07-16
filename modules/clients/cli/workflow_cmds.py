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
    mission_name: str | None = None,
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
                f"Unknown workflow action: {action}. " f"Valid: {', '.join(actions.keys())}",
                fg="red",
            ),
            err=True,
        )
        sys.exit(1)

    try:
        asyncio.run(
            handler(
                cli_logger,
                workflow_name=workflow_name,
                run_id=run_id,
                triggered_by=triggered_by,
                output_format=output_format,
                mission_name=mission_name,
                gate=gate,
            )
        )
    except (OSError, RuntimeError, ValueError) as e:
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
    from modules.backend.services.workflow import WorkflowService
    from modules.clients.cli.report import build_table, get_console

    service = WorkflowService()
    workflows = service.list_workflows(enabled_only=False)

    if not workflows:
        click.echo("No workflows found.")
        return

    console = get_console()
    table = build_table(
        f"Workflows ({len(workflows)} available)",
        columns=[
            ("Name", {"style": "cyan", "width": 36}),
            ("Ver", {"justify": "right", "width": 4}),
            ("Enabled", {"width": 8}),
            ("Budget", {"justify": "right", "width": 8}),
            ("Steps", {"justify": "right", "width": 6}),
            ("Description", {"ratio": 1}),
        ],
    )

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

    from modules.backend.services.workflow import WorkflowService
    from modules.clients.cli.report import build_table, get_console, info_panel, primary_panel

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

    table = build_table(
        "Steps",
        columns=[
            ("ID", {"style": "cyan", "width": 20}),
            ("Capability", {"width": 28}),
            ("Budget", {"justify": "right", "width": 8}),
            ("Env", {"width": 10}),
            ("Depends On", {"style": "dim", "width": 20}),
            ("Description", {"ratio": 1}),
        ],
        show_lines=True,
    )

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


async def _action_run(
    cli_logger,
    *,
    workflow_name,
    run_id,
    triggered_by,
    output_format,
    mission_name=None,
    gate=None,
    context_overrides=None,
    **_,
):
    """Execute a workflow."""
    if not workflow_name:
        click.echo(click.style("Error: --workflow-name is required for run.", fg="red"), err=True)
        sys.exit(1)

    await _preflight_gate(workflow_name)

    from modules.backend.services.workflow_run import WorkflowRunService
    from modules.clients.cli.live_display import LiveExecutionDisplay
    from modules.clients.cli.report import get_console, render_workflow_completion

    console = get_console()
    console.print(f"[bold]Running workflow:[/bold] {workflow_name}\n")

    # Live display handles both step progress and agent-level events
    display = LiveExecutionDisplay()
    event_bus = display.create_event_bus()

    # Resolve mission name → ID
    mission_id = None
    if mission_name:
        from modules.backend.core.database import get_async_session
        from modules.backend.services.mission import MissionService

        async with get_async_session() as db:
            mission_svc = MissionService(db)
            mission = await mission_svc.get_mission_by_name(mission_name)
            if not mission:
                raise click.ClickException(f"Mission '{mission_name}' not found")
            mission_id = str(mission.id)

    async with WorkflowRunService.factory(event_bus=event_bus) as run_service:
        with display.start():
            run = await run_service.run_workflow(
                workflow_name=workflow_name,
                triggered_by=triggered_by,
                on_progress=display.handle_progress,
                mission_id=mission_id,
                gate=gate,
            )

    async with WorkflowRunService.factory() as run_service:
        step_records = await run_service.get_run_executions(run.id)

    await render_workflow_completion(console, run, step_records)


async def _action_runs(cli_logger, *, workflow_name, run_id, triggered_by, output_format, **_):
    """List workflow runs."""
    from modules.backend.services.workflow_run import WorkflowRunService
    from modules.clients.cli.report import DOTTED_ROWS, build_table, get_console, styled_status

    async with WorkflowRunService.factory() as run_service:
        runs, total = await run_service.list_runs(
            workflow_name=workflow_name,
            limit=20,
        )

    if not runs:
        click.echo("No workflow runs found.")
        return

    console = get_console()
    table = build_table(
        f"Workflow Runs ({total} total)",
        columns=[
            ("Date/Time", {"style": "dim", "width": 16}),
            ("ID", {"style": "cyan", "width": 36}),
            ("Workflow", {"width": 24}),
            ("Status", {"width": 10}),
            ("Cost", {"justify": "right", "width": 8}),
            ("Trigger", {"style": "dim", "width": 10}),
            ("Summary", {"ratio": 1}),
        ],
        show_lines=True,
        table_box=DOTTED_ROWS,
    )

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


async def _action_run_detail(
    cli_logger, *, workflow_name, run_id, triggered_by, output_format, **_
):
    """Show workflow run detail with missions — uses the report renderer."""
    if not run_id:
        click.echo(click.style("Error: --run-id is required for run-detail.", fg="red"), err=True)
        sys.exit(1)

    run, executions = await _load_run_with_executions(run_id)
    from modules.clients.cli.report import render_workflow_run

    await render_workflow_run(run, executions, "human")


async def _action_report(cli_logger, *, workflow_name, run_id, triggered_by, output_format, **_):
    """Render a report for a past workflow run in the requested format."""
    if not run_id:
        click.echo(click.style("Error: --run-id is required for report.", fg="red"), err=True)
        sys.exit(1)

    run, executions = await _load_run_with_executions(run_id)
    from modules.clients.cli.report import render_workflow_run

    await render_workflow_run(run, executions, output_format)


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
                label = (
                    "insufficient credits"
                    if check.error_type == "insufficient_credits"
                    else check.error
                )
                click.echo(click.style(f"  ✗ {check.model_name}: {label}", fg="red"))
            click.echo()
            click.echo(
                click.style("Aborting — fix credit issues before running.", fg="red"), err=True
            )
            sys.exit(1)
    click.echo()


async def _load_run_with_executions(run_id: str):
    """Load a workflow run and its step execution records via the run service."""
    from modules.backend.services.workflow_run import WorkflowRunService

    async with WorkflowRunService.factory() as run_service:
        run = await run_service.get_run(run_id)
        if not run:
            click.echo(click.style(f"Workflow run '{run_id}' not found.", fg="red"), err=True)
            sys.exit(1)
        step_records = await run_service.get_run_executions(run.id)

    return run, step_records
