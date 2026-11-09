"""Admin CLI — Schedules group (Plan 88 step 88.1.13, contracts 3.5.4).

Runs MissionScheduleService in-process: admin.py sits inside the backend
trust boundary (contracts 3.0.2) and never calls /admin/schedules/sync.
"""

import click

from modules.clients.cli.cli_context import ShowHelpOnMissingArgs


@click.group("schedules", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def schedules(ctx):
    """Mirror mission schedules to Temporal.

    \b
    Examples:
        python admin.py schedules sync
        python admin.py schedules sync --mission <mission-id>
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@schedules.command("sync")
@click.option("--mission", "mission_id", default=None, help="Sync only this mission's schedules.")
@click.pass_obj
def schedules_sync(ctx, mission_id):
    """Sync one mission's schedules, or all of them, to Temporal now."""
    import asyncio

    stats = asyncio.run(_sync(mission_id))
    _render(stats)


async def _sync(mission_id: str | None):
    from modules.backend.temporal.mission_schedule_activities import schedule_service

    async with schedule_service() as (svc, _db):
        if mission_id is None:
            return await svc.sync_all()
        return await svc.sync_mission(mission_id)


def _render(stats) -> None:
    from modules.clients.cli.report import build_table, get_console

    table = build_table(
        "Schedule sync",
        columns=[
            ("Synced", {"justify": "right", "width": 10}),
            ("Failed", {"justify": "right", "width": 10}),
            ("Deleted orphans", {"justify": "right", "width": 16}),
            ("Completed", {"justify": "right", "width": 10}),
        ],
    )
    table.add_row(
        str(stats.synced),
        str(stats.failed),
        str(stats.deleted_orphans),
        str(stats.completed),
    )
    get_console().print(table)
