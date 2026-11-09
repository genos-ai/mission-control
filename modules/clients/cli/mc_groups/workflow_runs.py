"""mc CLI — workflow-runs — WorkflowRun lifecycle (list / show / cancel).

Renamed from `mc runs` in Plan 88 step 88.1.13, with no alias: `mc runs`
now lists mission runs (mc_groups/runs.py).
"""

import asyncio

import click

from modules.clients.cli.api_client import api_client, require_mission
from modules.clients.cli.cli_context import ShowHelpOnMissingArgs

# =============================================================================
# workflow-runs — WorkflowRun lifecycle (list / show / cancel)
# =============================================================================


@click.group("workflow-runs", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def workflow_runs(ctx):
    """Manage existing workflow runs (list active, show detail, cancel)."""
    if ctx.invoked_subcommand is None:
        from modules.clients.cli.mc_runs import list_runs

        async def _run():
            async with api_client() as api:
                mid = await require_mission(api)
                await list_runs(api, mission_id=mid, include_terminal=False)

        asyncio.run(_run())


@workflow_runs.command("list")
@click.option(
    "--all",
    "include_terminal",
    is_flag=True,
    help="Include completed / failed / cancelled runs (default: active only).",
)
@click.pass_obj
def runs_list(ctx, include_terminal):
    """List workflow runs for the current mission (active by default)."""
    from modules.clients.cli.mc_runs import list_runs

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await list_runs(api, mission_id=mid, include_terminal=include_terminal)

    asyncio.run(_run())


@workflow_runs.command("show")
@click.argument("run_id")
@click.pass_obj
def runs_show(ctx, run_id):
    """Show full detail for one workflow run."""
    from modules.clients.cli.mc_runs import show_run

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await show_run(api, mission_id=mid, run_id=run_id)

    asyncio.run(_run())


@workflow_runs.command("cancel")
@click.argument("run_id")
@click.pass_obj
def runs_cancel(ctx, run_id):
    """Mark a workflow run as CANCELLED (useful for stale RUNNING orphans)."""
    from modules.clients.cli.mc_runs import cancel_run

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await cancel_run(api, mission_id=mid, run_id=run_id)

    asyncio.run(_run())
