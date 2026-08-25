"""Admin CLI — Workflow group (Plan 84 Phase 5.5, split out of root admin.py).

Pure move, no behavior change.
"""

import click

from modules.clients.cli.cli_context import ShowHelpOnMissingArgs

# =============================================================================
# Workflow group
# =============================================================================


@click.group(cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def workflow(ctx):
    """List, run, and inspect workflows.

    \b
    Examples:
        python admin.py workflow list
        python admin.py workflow run ops.platform-audit --mission my-app
        python admin.py workflow detail ops.platform-audit
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@workflow.command("list")
@click.pass_obj
def workflow_list(ctx):
    """List available workflows."""
    from modules.clients.cli.workflow_cmds import run_workflow_cli

    run_workflow_cli(
        ctx.logger,
        action="list",
        workflow_name=None,
        run_id=None,
        triggered_by="user:admin",
        output_format=ctx.output_format,
    )


@workflow.command("detail")
@click.argument("name")
@click.pass_obj
def workflow_detail(ctx, name):
    """Show workflow configuration and steps."""
    from modules.clients.cli.workflow_cmds import run_workflow_cli

    run_workflow_cli(
        ctx.logger,
        action="detail",
        workflow_name=name,
        run_id=None,
        triggered_by="user:admin",
        output_format=ctx.output_format,
    )


@workflow.command("run")
@click.argument("name")
@click.option("--triggered-by", default="user:admin", help="Trigger origin.")
@click.option("--mission", required=True, help="Mission name to run against (created if new).")
@click.option(
    "--gate",
    type=click.Choice(["off", "interactive", "ai_assisted", "autonomous"], case_sensitive=False),
    default=None,
    help="Gate review mode. Overrides config/settings/gate.yaml.",
)
@click.pass_obj
def workflow_run(ctx, name, triggered_by, mission, gate):
    """Execute a workflow."""
    from modules.clients.cli.workflow_cmds import run_workflow_cli

    gate_obj = None
    if gate and gate != "off":
        from modules.backend.agents.mission_control.gate import create_gate

        gate_obj = create_gate(mode_override=gate)

    run_workflow_cli(
        ctx.logger,
        action="run",
        workflow_name=name,
        run_id=None,
        triggered_by=triggered_by,
        output_format=ctx.output_format,
        mission_name=mission,
        gate=gate_obj,
    )


@workflow.command("runs")
@click.option("--name", default=None, help="Filter by workflow name.")
@click.pass_obj
def workflow_runs(ctx, name):
    """List workflow runs."""
    from modules.clients.cli.workflow_cmds import run_workflow_cli

    run_workflow_cli(
        ctx.logger,
        action="runs",
        workflow_name=name,
        run_id=None,
        triggered_by="user:admin",
        output_format=ctx.output_format,
    )


@workflow.command("run-detail")
@click.argument("run_id")
@click.pass_obj
def workflow_run_detail(ctx, run_id):
    """Show details for a specific workflow run."""
    from modules.clients.cli.workflow_cmds import run_workflow_cli

    run_workflow_cli(
        ctx.logger,
        action="run-detail",
        workflow_name=None,
        run_id=run_id,
        triggered_by="user:admin",
        output_format=ctx.output_format,
    )


@workflow.command("report")
@click.argument("run_id")
@click.pass_obj
def workflow_report(ctx, run_id):
    """Render a report for a past workflow run."""
    from modules.clients.cli.workflow_cmds import run_workflow_cli

    run_workflow_cli(
        ctx.logger,
        action="report",
        workflow_name=None,
        run_id=run_id,
        triggered_by="user:admin",
        output_format=ctx.output_format,
    )
