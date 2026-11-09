"""mc CLI — schedule — recurring mission runs (Plan 88 step 88.1.13, contracts 3.5.4).

A schedule is addressed by NAME. It runs an objective template or a saved
workflow of the mission on a cron expression in an IANA time zone.
"""

import asyncio

import click

from modules.clients.cli.api_client import api_client, require_mission
from modules.clients.cli.cli_context import ShowHelpOnMissingArgs


def _target_options(func):
    """Flags shared by create and edit."""
    options = [
        click.option("--cron", default=None, help='5-field cron: "min hour day month weekday".'),
        click.option("--tz", default=None, help="IANA time zone, e.g. Europe/London."),
        click.option(
            "--objective",
            default=None,
            help="Objective template; may use {scheduled_for}, {sequence}, {mission_name}.",
        ),
        click.option("--workflow", default=None, help="Saved workflow name of this mission."),
        click.option(
            "--param",
            "params",
            multiple=True,
            help="Workflow parameter k=v (repeatable).",
        ),
        click.option("--starts-at", default=None, help="ISO 8601 start, with offset."),
        click.option("--ends-at", default=None, help="ISO 8601 end, with offset."),
        click.option("--max-runs", type=int, default=None, help="Stop after N runs."),
        click.option(
            "--catch-up-window",
            default=None,
            help="Missed-run catch-up window: 90s, 15m, 6h, 2d.",
        ),
    ]
    for option in reversed(options):
        func = option(func)
    return func


def _fields(cron, tz, objective, workflow, params, starts_at, ends_at, max_runs, catch_up_window):
    from modules.clients.cli.mc_schedule import parse_duration, parse_params

    return {
        "cron": cron,
        "tz": tz,
        "objective": objective,
        "workflow": workflow,
        "params": parse_params(params),
        "starts_at": starts_at,
        "ends_at": ends_at,
        "max_runs": max_runs,
        "catch_up_window_seconds": parse_duration(catch_up_window),
    }


@click.group("schedule", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def schedule(ctx):
    """Recurring runs for the current mission.

    \b
    Examples:
        mc schedule create daily --cron "0 6 * * *" --tz Europe/London --objective "Review"
        mc schedule create weekly --cron "0 9 * * 1" --tz UTC --workflow audit --param depth=2
        mc schedule list --all
        mc schedule show daily
        mc schedule edit daily --cron "30 6 * * *"
        mc schedule pause daily
        mc schedule resume daily
        mc schedule delete daily
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@schedule.command("list")
@click.option("--all", "include_archived", is_flag=True, help="Include archived schedules.")
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output.")
@click.pass_obj
def schedule_list(ctx, include_archived, as_json):
    """List schedules for the current mission."""
    from modules.clients.cli.mc_schedule import list_schedules

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await list_schedules(
                api, mission_id=mid, include_archived=include_archived, as_json=as_json
            )

    asyncio.run(_run())


@schedule.command("show")
@click.argument("name")
@click.pass_obj
def schedule_show(ctx, name):
    """Show a schedule with its next fire times and sync state."""
    from modules.clients.cli.mc_schedule import show_schedule

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await show_schedule(api, mission_id=mid, name=name)

    asyncio.run(_run())


@schedule.command("create")
@click.argument("name")
@_target_options
@click.pass_obj
def schedule_create(ctx, name, **flags):
    """Create a schedule (--cron and --tz required; --objective or --workflow)."""
    from modules.clients.cli.mc_schedule import create_schedule

    if flags["cron"] is None or flags["tz"] is None:
        raise click.UsageError("create needs --cron and --tz.")
    fields = _fields(**flags)

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await create_schedule(api, mission_id=mid, name=name, fields=fields)

    asyncio.run(_run())


@schedule.command("edit")
@click.argument("name")
@_target_options
@click.pass_obj
def schedule_edit(ctx, name, **flags):
    """Change a schedule; only the flags given are sent."""
    from modules.clients.cli.mc_schedule import edit_schedule

    fields = _fields(**flags)

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await edit_schedule(api, mission_id=mid, name=name, fields=fields)

    asyncio.run(_run())


def _status_command(action: str, help_text: str):
    @schedule.command(action, help=help_text)
    @click.argument("name")
    @click.pass_obj
    def _command(ctx, name):
        from modules.clients.cli.mc_schedule import change_status

        async def _run():
            async with api_client() as api:
                mid = await require_mission(api)
                await change_status(api, mission_id=mid, name=name, action=action)

        asyncio.run(_run())

    return _command


_status_command("pause", "Pause a schedule; it stops firing until resumed.")
_status_command("resume", "Resume a paused schedule.")
_status_command("delete", "Archive a schedule and delete its Temporal schedule.")
