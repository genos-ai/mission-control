"""mc CLI — Mission commands.

Split out of root mc.py (Plan 84 Phase 5.5). Pure move, no behavior change.
"""

import asyncio

import click

from modules.clients.cli.api_client import api_client, require_mission
from modules.clients.cli.cli_context import ShowHelpOnMissingArgs

# =============================================================================
# Mission commands
# =============================================================================


@click.group("mission", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def mission(ctx):
    """Manage missions."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@mission.command("create")
@click.option("--name", required=True, help="Mission name.")
@click.option("--description", required=True, help="Mission description.")
@click.option("--brief", default=None, help="Strategic brief for agents.")
@click.option(
    "--gate-mode",
    "gate_mode",
    required=True,
    type=click.Choice(["interactive", "manual", "ai_assisted", "autonomous"]),
    help="Plan gate mode.",
)
@click.option(
    "--budget-per-run", type=float, default=None, help="Per-run cap in USD (default from config)."
)
@click.option(
    "--budget-per-month",
    type=float,
    default=None,
    help="Per-calendar-month cap in USD (default from config).",
)
@click.option(
    "--budget-lifetime", type=float, default=None, help="Lifetime cap in USD (default: no limit)."
)
def mission_create(
    name, description, brief, gate_mode, budget_per_run, budget_per_month, budget_lifetime
):
    """Create a new mission."""
    from modules.clients.cli.mc_mission import create

    async def _run():
        async with api_client() as api:
            await create(
                api,
                name=name,
                description=description,
                brief=brief,
                gate_mode=gate_mode,
                budget_per_run=budget_per_run,
                budget_per_month=budget_per_month,
                budget_lifetime=budget_lifetime,
            )

    asyncio.run(_run())


@mission.command("list")
def mission_list():
    """List all missions."""
    from modules.clients.cli.mc_mission import list_missions

    async def _run():
        async with api_client() as api:
            await list_missions(api)

    asyncio.run(_run())


@mission.command("use")
@click.option("--name", "name_or_id", required=True, help="Mission name or ID.")
def mission_use(name_or_id):
    """Set the active mission."""
    from modules.clients.cli.mc_mission import use

    async def _run():
        async with api_client() as api:
            await use(api, name_or_id)

    asyncio.run(_run())


@mission.command("info")
@click.pass_obj
def mission_info(ctx):
    """Show current mission detail."""
    from modules.clients.cli.mc_mission import info

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await info(api, mid)

    asyncio.run(_run())


@mission.command("set-gate")
@click.option(
    "--mode",
    required=True,
    type=click.Choice(["interactive", "manual", "ai_assisted", "autonomous"]),
    help="Gate mode.",
)
@click.pass_obj
def mission_set_gate(ctx, mode):
    """Set the default gate mode for the current mission."""
    from modules.clients.cli.mc_mission import set_gate

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await set_gate(api, mid, mode)

    asyncio.run(_run())


@mission.command("budget")
@click.pass_obj
def mission_budget(ctx):
    """Show the current mission's budget caps, spend and breach."""
    from modules.clients.cli.mc_mission import budget

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await budget(api, mid)

    asyncio.run(_run())


@mission.command("set-budget")
@click.option("--per-run", "per_run", type=float, required=True, help="Per-run cap in USD.")
@click.option(
    "--per-month", "per_month", type=float, required=True, help="Per-calendar-month cap in USD."
)
@click.option("--lifetime", type=float, default=None, help="Lifetime cap in USD.")
@click.option("--no-lifetime", "no_lifetime", is_flag=True, help="Remove the lifetime cap.")
@click.pass_obj
def mission_set_budget(ctx, per_run, per_month, lifetime, no_lifetime):
    """Replace the current mission's budget caps (all caps are set together)."""
    from modules.clients.cli.mc_mission import set_budget

    if (lifetime is None) == (not no_lifetime):
        raise click.UsageError("Give exactly one of --lifetime or --no-lifetime.")

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await set_budget(api, mid, per_run=per_run, per_month=per_month, lifetime=lifetime)

    asyncio.run(_run())


@mission.command("archive")
@click.pass_obj
def mission_archive(ctx):
    """Archive the current mission."""
    from modules.clients.cli.mc_mission import archive

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await archive(api, mid)

    asyncio.run(_run())


@mission.command("delete")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt.")
@click.pass_obj
def mission_delete(ctx, confirm):
    """Permanently delete the current mission and all its data."""
    if not confirm:
        click.confirm(
            "This will permanently delete the mission and all its data. Continue?",
            abort=True,
        )

    from modules.clients.cli.mc_mission import delete

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await delete(api, mid)

    asyncio.run(_run())


@mission.command("unarchive")
@click.option("--name", "name_or_id", required=True, help="Mission name or ID.")
def mission_unarchive(name_or_id):
    """Restore an archived mission to active status."""
    from modules.clients.cli.mc_mission import unarchive

    async def _run():
        async with api_client() as api:
            await unarchive(api, name_or_id)

    asyncio.run(_run())
