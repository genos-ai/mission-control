"""Admin CLI — Console — Rich Live terminal dashboard.

Split out of root admin.py (Plan 84 Phase 5.5). Pure move, no behavior change.
"""

import click

from modules.clients.cli.cli_context import ShowHelpOnMissingArgs

# =============================================================================
# Console — Rich Live terminal dashboard
# =============================================================================


@click.group("console", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def console(ctx):
    """Live terminal dashboard for monitoring Mission Control.

    \b
    Examples:
        python admin.py console monitor
        python admin.py console monitor --view developer
        python admin.py console monitor --refresh 5
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@console.command("monitor")
@click.option(
    "--view",
    type=click.Choice(["user", "developer"]),
    default="user",
    help="Display mode: user (default) or developer.",
)
@click.option("--refresh", default=2.0, type=float, help="Refresh interval in seconds.")
@click.pass_obj
def console_monitor(ctx, view, refresh):
    """Live-updating console monitor with missions, runs, and system health."""
    from modules.clients.cli.console_cmds import run_monitor

    run_monitor(view=view, refresh=refresh)
