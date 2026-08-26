"""mc CLI — Team commands.

Split out of root mc.py (Plan 84 Phase 5.5). Pure move, no behavior change.
"""

import asyncio

import click

from modules.clients.cli.api_client import api_client, require_mission
from modules.clients.cli.cli_context import ShowHelpOnMissingArgs

# =============================================================================
# Team commands
# =============================================================================


@click.group("team", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def team(ctx):
    """Manage your agent team."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@team.command("list")
@click.pass_obj
def team_list(ctx):
    """List agents on the current mission's roster."""
    from modules.clients.cli.mc_team import list_team

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await list_team(api, mid)

    asyncio.run(_run())


@team.command("ping")
@click.pass_obj
def team_ping(ctx):
    """Ping every agent on the current mission's team with a trivial LLM call.

    Probes each agent's catalog row → builds the model → sends "Reply with OK"
    in parallel (bounded). Reports per-agent latency, tokens, cost, and status.
    Health check for the full provider/auth/model chain.
    """
    from modules.clients.cli.mc_team import ping_team

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await ping_team(api, mid)

    asyncio.run(_run())


@team.command("available")
@click.option("--search", "-s", default=None, help="Search query.")
def team_available(search):
    """Browse the global agent catalog."""
    from modules.clients.cli.mc_team import list_available

    async def _run():
        async with api_client() as api:
            await list_available(api, search)

    asyncio.run(_run())


@team.command("add")
@click.option("--agent", required=True, help="Agent name to add.")
@click.pass_obj
def team_add(ctx, agent):
    """Add an agent to the current mission."""
    from modules.clients.cli.mc_team import add_agent

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await add_agent(api, mid, agent)

    asyncio.run(_run())


@team.command("remove")
@click.option("--agent", required=True, help="Agent name to remove.")
@click.pass_obj
def team_remove(ctx, agent):
    """Remove an agent from the current mission."""
    from modules.clients.cli.mc_team import remove_agent

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await remove_agent(api, mid, agent)

    asyncio.run(_run())
