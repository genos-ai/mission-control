"""mc CLI — Intent commands.

Split out of root mc.py (Plan 84 Phase 5.5). Pure move, no behavior change.
"""

import asyncio

import click

from modules.clients.cli.api_client import api_client, require_mission
from modules.clients.cli.cli_context import ShowHelpOnMissingArgs

# =============================================================================
# Intent commands
# =============================================================================


@click.group("intent", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def intent(ctx):
    """View and manage mission intent."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@intent.command("show")
@click.pass_obj
def intent_show(ctx):
    """Show the current mission intent."""
    from modules.clients.cli.mc_knowledge import intent_show as _show

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await _show(api, mid)

    asyncio.run(_run())


@intent.command("history")
@click.option("--limit", "-n", default=20, help="Max revisions to show")
@click.pass_obj
def intent_history(ctx, limit):
    """Show intent revision timeline."""
    from modules.clients.cli.mc_knowledge import intent_history as _history

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await _history(api, mid, limit=limit)

    asyncio.run(_run())


@intent.command("set")
@click.option("--text", required=True, help="Intent text.")
@click.option("--reason", "-r", default="User-set via CLI", help="Reason for change")
@click.pass_obj
def intent_set(ctx, text, reason):
    """Set a new mission intent."""
    from modules.clients.cli.mc_knowledge import intent_set as _set

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await _set(api, mid, text, reason=reason)

    asyncio.run(_run())
