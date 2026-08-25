"""Admin CLI — Schedule commands (Plan 84 Phase 5.5, split out of root admin.py).

Pure move, no behavior change.
"""

import click

from modules.clients.cli.cli_context import ShowHelpOnMissingArgs

# =============================================================================
# Schedule commands
# =============================================================================


@click.group("schedule", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def schedule(ctx):
    """Manage cron-based workflow schedules.

    \b
    Examples:
        python admin.py schedule list --mission <id>
        python admin.py schedule create --mission <id> --workflow <id> --cron "0 5 * * *"
        python admin.py schedule enable <id>
        python admin.py schedule disable <id>
        python admin.py schedule delete <id>
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@schedule.command("list")
@click.option("--mission", "mission_id", required=True, help="Mission ID.")
@click.pass_obj
def schedule_list(ctx, mission_id):
    """List schedules for a mission."""
    from modules.clients.cli.schedule_cmds import run_schedule

    run_schedule(ctx.logger, "list", mission_id=mission_id, output_format=ctx.output_format)


@schedule.command("create")
@click.option("--mission", "mission_id", required=True, help="Mission ID.")
@click.option("--workflow", "workflow_definition_id", required=True, help="Workflow definition ID.")
@click.option("--cron", required=True, help='Cron expression, e.g. "0 5 * * *".')
@click.option("--description", default="", help="Schedule description.")
@click.option("--budget", type=float, default=None, help="Budget per run (USD).")
@click.option("--max-iterations", type=int, default=None, help="Max total runs (NULL = unlimited).")
@click.option("--cooldown", type=int, default=0, help="Min seconds between runs.")
@click.pass_obj
def schedule_create(
    ctx, mission_id, workflow_definition_id, cron, description, budget, max_iterations, cooldown
):
    """Create a cron-based workflow schedule."""
    from modules.clients.cli.schedule_cmds import run_schedule

    run_schedule(
        ctx.logger,
        "create",
        mission_id=mission_id,
        workflow_definition_id=workflow_definition_id,
        cron=cron,
        description=description,
        budget=budget,
        max_iterations=max_iterations,
        cooldown=cooldown,
        output_format=ctx.output_format,
    )


@schedule.command("enable")
@click.argument("schedule_id")
@click.pass_obj
def schedule_enable(ctx, schedule_id):
    """Enable a schedule."""
    from modules.clients.cli.schedule_cmds import run_schedule

    run_schedule(ctx.logger, "enable", schedule_id=schedule_id, output_format=ctx.output_format)


@schedule.command("disable")
@click.argument("schedule_id")
@click.pass_obj
def schedule_disable(ctx, schedule_id):
    """Disable a schedule."""
    from modules.clients.cli.schedule_cmds import run_schedule

    run_schedule(ctx.logger, "disable", schedule_id=schedule_id, output_format=ctx.output_format)


@schedule.command("delete")
@click.argument("schedule_id")
@click.pass_obj
def schedule_delete(ctx, schedule_id):
    """Delete a schedule."""
    from modules.clients.cli.schedule_cmds import run_schedule

    run_schedule(ctx.logger, "delete", schedule_id=schedule_id, output_format=ctx.output_format)
