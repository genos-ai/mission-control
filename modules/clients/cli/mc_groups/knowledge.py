"""mc CLI — Knowledge platform commands.

Split out of root mc.py (Plan 84 Phase 5.5). Pure move, no behavior change.
"""

import asyncio

import click

from modules.clients.cli.api_client import api_client, require_mission
from modules.clients.cli.cli_context import ShowHelpOnMissingArgs

# =============================================================================
# Knowledge platform commands
# =============================================================================


@click.group("knowledge", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def knowledge(ctx):
    """Platform knowledge."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@knowledge.command("search")
@click.option("--query", "-q", required=True, help="Search query.")
@click.option("--tags", "-t", default=None, help="Comma-separated domain tags")
@click.option("--kinds", "-k", default=None, help="Comma-separated kinds")
@click.option("--mode", default="hybrid", type=click.Choice(["structured", "hybrid", "semantic"]))
@click.option("--mission", default=None, help="Mission ID (uses current if omitted)")
@click.option("--platform-only", is_flag=True, help="Only platform-promoted entries")
@click.pass_obj
def knowledge_search(ctx, query, tags, kinds, mode, mission, platform_only):
    """Search the knowledge platform."""
    from modules.clients.cli.mc_knowledge import knowledge_search as _search

    async def _run():
        async with api_client() as api:
            mid = mission
            if not mid and not platform_only:
                try:
                    mid = await require_mission(api)
                except SystemExit:
                    mid = None
            await _search(
                api,
                query,
                mission_id=mid,
                tags=tags,
                kinds=kinds,
                mode=mode,
                platform_only=platform_only,
            )

    asyncio.run(_run())
