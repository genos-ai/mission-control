"""mc CLI — Learnings commands.

Split out of root mc.py (Plan 84 Phase 5.5). Pure move, no behavior change.
"""

import asyncio

import click

from modules.clients.cli.api_client import api_client, require_mission
from modules.clients.cli.cli_context import ShowHelpOnMissingArgs

# =============================================================================
# Learnings commands
# =============================================================================


@click.group("learnings", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def learnings(ctx):
    """View mission learnings."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@learnings.command("list")
@click.option("--kind", "-k", default=None, help="Filter by kind")
@click.option("--domain", "-d", default=None, help="Filter by domain tag")
@click.pass_obj
def learnings_list(ctx, kind, domain):
    """List learnings for the current mission."""
    from modules.clients.cli.mc_knowledge import learnings_list as _list

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await _list(api, mid, kind=kind, domain=domain)

    asyncio.run(_run())


@learnings.command("show")
@click.option("--id", "learning_id", required=True, help="Learning ID.")
@click.pass_obj
def learnings_show(ctx, learning_id):
    """Show a specific learning in detail."""
    from modules.clients.cli.mc_knowledge import learnings_show as _show

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await _show(api, mid, learning_id)

    asyncio.run(_run())
