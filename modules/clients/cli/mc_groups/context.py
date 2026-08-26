"""mc CLI — Context commands.

Split out of root mc.py (Plan 84 Phase 5.5). Pure move, no behavior change.
"""

import asyncio

import click

from modules.clients.cli.api_client import api_client, require_mission
from modules.clients.cli.cli_context import ShowHelpOnMissingArgs

# =============================================================================
# Context commands
# =============================================================================


@click.group("context", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def context(ctx):
    """View mission context."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@context.command("show")
@click.pass_obj
def context_show(ctx):
    """View the Mission Context Document."""
    from modules.clients.cli.mc_mission import context_show as _show

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await _show(api, mid)

    asyncio.run(_run())


@context.command("history")
@click.pass_obj
def context_history(ctx):
    """MCD change audit trail."""
    from modules.clients.cli.mc_mission import context_history as _history

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await _history(api, mid)

    asyncio.run(_run())
