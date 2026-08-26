"""mc CLI — Schedule — recurring workflow runs (cron).

Split out of root mc.py (Plan 84 Phase 5.5). Pure move, no behavior change.
"""

import asyncio

import click

from modules.clients.cli.api_client import api_client, require_mission
from modules.clients.cli.cli_context import ShowHelpOnMissingArgs

# =============================================================================
# Schedule — recurring workflow runs (cron)
# =============================================================================


@click.group("schedule", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def schedule(ctx):
    """Recurring workflow runs (cron) for the current mission.

    Schedules a *defined workflow* to run on a cron cadence. Scheduling a
    free-form objective is not supported (Plan 83 §8).

    Examples:
        mc schedule list
        mc schedule create --workflow <id> --cron "0 9 * * *"   # daily 09:00
        mc schedule create --workflow <id> --cron "0 9 * * 1"   # weekly Mon
        mc schedule enable <schedule_id>
        mc schedule disable <schedule_id>
        mc schedule delete <schedule_id>
    """
    if ctx.invoked_subcommand is None:
        from modules.clients.cli.mc_schedule import list_schedules

        async def _run():
            async with api_client() as api:
                mid = await require_mission(api)
                await list_schedules(api, mission_id=mid)

        asyncio.run(_run())


@schedule.command("list")
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output.")
@click.pass_obj
def schedule_list(ctx, as_json):
    """List schedules for the current mission."""
    from modules.clients.cli.mc_schedule import list_schedules

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await list_schedules(
                api,
                mission_id=mid,
                output_format="json" if as_json else "human",
            )

    asyncio.run(_run())


@schedule.command("create")
@click.option("--workflow", required=True, help="Workflow definition id to schedule.")
@click.option("--cron", required=True, help='5-field cron: "min hour day month weekday".')
@click.option("--description", default="", help="Optional description.")
@click.option("--budget", type=float, default=None, help="USD ceiling per run.")
@click.option("--max-iterations", type=int, default=None, help="Total runs (unlimited if omitted).")
@click.option("--cooldown", type=int, default=0, help="Min seconds between runs.")
@click.pass_obj
def schedule_create(ctx, workflow, cron, description, budget, max_iterations, cooldown):
    """Create a cron schedule for a workflow."""
    from modules.clients.cli.mc_schedule import create_schedule

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await create_schedule(
                api,
                mission_id=mid,
                workflow=workflow,
                cron=cron,
                description=description,
                budget=budget,
                max_iterations=max_iterations,
                cooldown=cooldown,
            )

    asyncio.run(_run())


@schedule.command("enable")
@click.argument("schedule_id")
@click.pass_obj
def schedule_enable(ctx, schedule_id):
    """Enable a schedule so it fires on its cron cadence."""
    from modules.clients.cli.mc_schedule import set_enabled

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await set_enabled(api, mission_id=mid, schedule_id=schedule_id, enabled=True)

    asyncio.run(_run())


@schedule.command("disable")
@click.argument("schedule_id")
@click.pass_obj
def schedule_disable(ctx, schedule_id):
    """Disable a schedule so it stops firing (without deleting it)."""
    from modules.clients.cli.mc_schedule import set_enabled

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await set_enabled(api, mission_id=mid, schedule_id=schedule_id, enabled=False)

    asyncio.run(_run())


@schedule.command("delete")
@click.argument("schedule_id")
@click.pass_obj
def schedule_delete(ctx, schedule_id):
    """Delete a schedule permanently."""
    from modules.clients.cli.mc_schedule import delete_schedule

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await delete_schedule(api, mission_id=mid, schedule_id=schedule_id)

    asyncio.run(_run())
