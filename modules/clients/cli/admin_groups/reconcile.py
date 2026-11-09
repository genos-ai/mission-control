"""Admin CLI — Reconcile group (Plan 88 step 88.1.10a, contracts 3.5.4).

Runs RunReconciliationService in-process: admin.py sits inside the backend
trust boundary (contracts 3.0.2) and never calls /admin/reconcile/run.
"""

import click

from modules.clients.cli.cli_context import ShowHelpOnMissingArgs


@click.group("reconcile", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def reconcile(ctx):
    """Reconcile in-flight runs against Temporal.

    \b
    Examples:
        python admin.py reconcile run
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@reconcile.command("run")
@click.pass_obj
def reconcile_run(ctx):
    """Run one reconciliation pass now and print its counts."""
    import asyncio

    stats = asyncio.run(_reconcile())
    _render(stats)


async def _reconcile():
    from redis.asyncio import Redis as AsyncRedis

    from modules.backend.core.config import get_app_config, get_redis_url
    from modules.backend.core.database import get_async_session
    from modules.backend.events.bus import SessionEventBus
    from modules.backend.services.run_reconciliation import RunReconciliationService
    from modules.backend.temporal.workflow_gateway import TemporalWorkflowGateway

    gateway = await TemporalWorkflowGateway.connect()
    redis = AsyncRedis.from_url(get_redis_url())
    try:
        event_bus = SessionEventBus(redis)
        async with get_async_session() as db:
            stats = await RunReconciliationService(db, gateway, event_bus).reconcile(
                get_app_config().temporal.reconciler.orphan_grace_seconds
            )
            await db.commit()
        return stats
    finally:
        await redis.aclose()


def _render(stats) -> None:
    from modules.clients.cli.report import build_table, get_console

    table = build_table(
        "Reconciliation",
        columns=[
            ("Rows", {"style": "cyan", "ratio": 1}),
            ("Examined", {"justify": "right", "width": 10}),
            ("Failed", {"justify": "right", "width": 10}),
        ],
    )
    table.add_row("Mission runs", str(stats.examined_mission_runs), str(stats.failed_mission_runs))
    table.add_row("Tasks", str(stats.examined_tasks), str(stats.failed_tasks))
    table.add_row(
        "Execution records",
        str(stats.examined_execution_records),
        str(stats.failed_execution_records),
    )
    table.add_row(
        "Workflow runs", str(stats.examined_workflow_runs), str(stats.failed_workflow_runs)
    )
    console = get_console()
    console.print(table)
    console.print(f"Left running: {stats.left_running}  Left in-process: {stats.left_in_process}")
