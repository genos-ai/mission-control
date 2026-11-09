"""mc CLI — runs — mission runs (Plan 88 step 88.1.13, contracts 3.5.4).

A run is addressed by its per-mission sequence number. The WorkflowRun
group that used to be `mc runs` is now `mc workflow-runs`.
"""

import asyncio

import click

from modules.clients.cli.api_client import api_client, require_mission
from modules.clients.cli.cli_context import ShowHelpOnMissingArgs


@click.group("runs", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def runs(ctx):
    """Mission runs: list, show, digest, cancel and start.

    \b
    Examples:
        mc runs list --status running --limit 5
        mc runs show 37
        mc runs digest 37
        mc runs cancel 37
        mc runs start --objective "audit the auth module"
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@runs.command("list")
@click.option(
    "--status",
    "statuses",
    multiple=True,
    help="Filter by lowercase run status, e.g. running or missed (repeatable).",
)
@click.option("--limit", type=int, default=None, help="Rows to show (default from cli.yaml).")
@click.pass_obj
def runs_list(ctx, statuses, limit):
    """List the mission's runs, newest first."""
    from modules.backend.core.config import get_app_config
    from modules.clients.cli.mc_mission_runs import list_runs

    page_size = limit if limit is not None else get_app_config().cli.mc.runs_list_limit

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await list_runs(api, mission_id=mid, statuses=list(statuses), limit=page_size)

    asyncio.run(_run())


@runs.command("show")
@click.argument("seq")
@click.pass_obj
def runs_show(ctx, seq):
    """Show one run and its tasks."""
    from modules.clients.cli.mc_mission_runs import show_run

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await show_run(api, mission_id=mid, sequence=seq)

    asyncio.run(_run())


@runs.command("digest")
@click.argument("seq")
@click.pass_obj
def runs_digest(ctx, seq):
    """Show the run's digest."""
    from modules.clients.cli.mc_mission_runs import show_digest

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await show_digest(api, mission_id=mid, sequence=seq)

    asyncio.run(_run())


@runs.command("cancel")
@click.argument("seq")
@click.pass_obj
def runs_cancel(ctx, seq):
    """Cancel an active run."""
    from modules.clients.cli.mc_mission_runs import cancel_run

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await cancel_run(api, mission_id=mid, sequence=seq)

    asyncio.run(_run())


@runs.command("start")
@click.option("--objective", "-o", required=True, help="Objective for the run.")
@click.pass_obj
def runs_start(ctx, objective):
    """Start a manual run for an objective."""
    from modules.clients.cli.mc_mission_runs import start_run

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await start_run(api, mission_id=mid, objective=objective)

    asyncio.run(_run())
