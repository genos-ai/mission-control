"""mc CLI — Status + History.

Split out of root mc.py (Plan 84 Phase 5.5). Pure move, no behavior change.
"""

import asyncio

import click

from modules.clients.cli.api_client import api_client, require_mission

# =============================================================================
# Status + History
# =============================================================================


@click.command()
@click.pass_obj
def status(ctx):
    """Current mission snapshot."""
    from modules.clients.cli.mc_status import show_status

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await show_status(api, mid, verbose=ctx.verbose)

    asyncio.run(_run())


@click.command()
@click.option("--run", "n", type=int, default=None, help="Show detail for run #N.")
@click.pass_obj
def history(ctx, n):
    """Recent runs. Use --run N for detail on that run."""
    from modules.clients.cli.mc_status import show_history

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await show_history(api, n, mission_id=mid, verbose=ctx.verbose)

    asyncio.run(_run())


@click.group()
@click.pass_context
def artifacts(ctx):
    """View mission artifacts."""
    pass


@artifacts.command("list")
@click.pass_obj
def artifacts_list(ctx):
    """List all artifacts for the current mission."""
    from modules.clients.cli.mc_mission import list_artifacts

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await list_artifacts(api, mid)

    asyncio.run(_run())


@artifacts.command("show")
@click.argument("num", type=int)
@click.pass_obj
def artifacts_show(ctx, num):
    """Show artifact #N (from artifacts list)."""
    from modules.clients.cli.mc_mission import show_artifact

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await show_artifact(api, mid, num)

    asyncio.run(_run())


@click.group()
@click.pass_context
def report(ctx):
    """View research reports."""
    pass


@report.command("list")
@click.pass_obj
def report_list(ctx):
    """List completed runs with reports."""
    from modules.clients.cli.mc_mission import list_reports

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await list_reports(api, mid)

    asyncio.run(_run())


@report.command("show")
@click.option(
    "--run", "n", type=int, default=None, help="Show report from run #N (default: latest)."
)
@click.pass_obj
def report_show(ctx, n):
    """View the research report from a completed run."""
    from modules.clients.cli.mc_mission import show_report

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await show_report(api, mid, n)

    asyncio.run(_run())


@click.command()
@click.argument("seq_or_workflow_id")
@click.option("--verbose", "-v", is_flag=True, help="Show all event types.")
@click.option(
    "--detail", "-d", is_flag=True, help="Show research phase breakdown from mission events."
)
@click.option(
    "--mission",
    "-m",
    default=None,
    help="Mission ID for a run sequence and --detail (default: mc mission use).",
)
@click.pass_obj
def trace(ctx, seq_or_workflow_id, verbose, detail, mission):
    """Trace a Temporal workflow execution — shows activity timeline.

    Accepts a mission run sequence (digits) or a Temporal workflow id.

    \b
    Examples:
        mc trace 37
        mc trace <temporal_workflow_id from mc runs show>
        mc trace 37 -d
        mc trace 37 -d -m <mission-id>
    """
    from modules.clients.cli.mc_trace import resolve_workflow_id, trace_workflow

    async def _run():
        mid = mission
        workflow_id = seq_or_workflow_id
        if seq_or_workflow_id.isdigit() or (detail and not mid):
            async with api_client() as api:
                mid = mid or await require_mission(api)
                workflow_id = await resolve_workflow_id(api, mid, seq_or_workflow_id)
        await trace_workflow(workflow_id, verbose=verbose, detail=detail, mission_id=mid)

    asyncio.run(_run())
