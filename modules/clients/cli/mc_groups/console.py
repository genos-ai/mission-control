"""mc CLI — Console monitor.

Split out of root mc.py (Plan 84 Phase 5.5). Pure move, no behavior change.
"""

import asyncio

import click

from modules.clients.cli.api_client import api_client, require_mission
from modules.clients.cli.cli_context import ShowHelpOnMissingArgs

# =============================================================================
# Console monitor
# =============================================================================


@click.group("console", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def console(ctx):
    """Live mission console monitor."""
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
    """Live-updating event stream for the current mission."""
    from modules.clients.cli.mc_console import monitor

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await monitor(api, mid, view=view, refresh=refresh)

    asyncio.run(_run())
