"""mc CLI — Plan — fine-grained per-task control.

Split out of root mc.py (Plan 84 Phase 5.5). Pure move, no behavior change.
"""

import asyncio

import click

from modules.clients.cli.api_client import api_client, require_mission
from modules.clients.cli.cli_context import ShowHelpOnMissingArgs

# =============================================================================
# Plan — fine-grained per-task control
# =============================================================================


@click.group("plan", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def plan(ctx):
    """Per-task plan control (approve / reject / retry / dispatch one at a time)."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@plan.command("show")
@click.option(
    "--status",
    "status_filter",
    type=click.Choice(
        ["proposed", "approved", "queued", "running", "completed", "failed", "skipped", "cancelled"]
    ),
    default=None,
    help="Only show tasks with this status.",
)
@click.option("--deps", "show_deps", is_flag=True, help="Include dependency column.")
@click.pass_obj
def plan_show(ctx, status_filter, show_deps):
    """Print the plan: every task with status, agent, cost, description."""
    from modules.clients.cli.mc_plan import show as plan_show_fn

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await plan_show_fn(
                api, mission_id=mid, status_filter=status_filter, show_deps=show_deps
            )

    asyncio.run(_run())


@plan.command("task")
@click.argument("task_id")
@click.pass_obj
def plan_task(ctx, task_id):
    """Show full detail for one task (status, instructions, deps, failure reason)."""
    from modules.clients.cli.mc_plan import task_detail

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await task_detail(api, mission_id=mid, task_id=task_id)

    asyncio.run(_run())


@plan.command("approve")
@click.argument("task_id", required=False)
@click.option(
    "--next",
    "pick_next",
    is_flag=True,
    help="Pick the topologically next PROPOSED task whose deps are all COMPLETED.",
)
@click.pass_obj
def plan_approve(ctx, task_id, pick_next):
    """Approve one task (also approves PROPOSED transitive dependencies)."""
    from modules.clients.cli.mc_plan import approve as plan_approve_fn

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await plan_approve_fn(api, mission_id=mid, task_id=task_id, pick_next=pick_next)

    asyncio.run(_run())


@plan.command("reject")
@click.argument("task_id", required=False)
@click.option(
    "--all", "reject_all", is_flag=True, help="Cancel ALL non-terminal tasks in the plan."
)
@click.pass_obj
def plan_reject(ctx, task_id, reject_all):
    """Reject one task (cancels transitive dependents); --all cancels all non-terminal."""
    from modules.clients.cli.mc_plan import reject as plan_reject_fn

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await plan_reject_fn(api, mission_id=mid, task_id=task_id, reject_all=reject_all)

    asyncio.run(_run())


@plan.command("retry")
@click.argument("task_id")
@click.pass_obj
def plan_retry(ctx, task_id):
    """Retry one FAILED task (bulk variant: `mc retry`)."""
    from modules.clients.cli.mc_plan import retry_one as plan_retry_fn

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await plan_retry_fn(api, mission_id=mid, task_id=task_id)

    asyncio.run(_run())


@plan.command("dispatch")
@click.pass_obj
def plan_dispatch(ctx):
    """Dispatch all currently APPROVED tasks via Temporal."""
    from modules.clients.cli.mc_plan import dispatch as plan_dispatch_fn

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await plan_dispatch_fn(api, mission_id=mid)

    asyncio.run(_run())
