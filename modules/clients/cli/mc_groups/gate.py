"""mc CLI — Gate — manual approval over the HTTP API.

Split out of root mc.py (Plan 84 Phase 5.5). Pure move, no behavior change.
"""

import asyncio

import click

from modules.clients.cli.api_client import api_client, require_mission
from modules.clients.cli.cli_context import ShowHelpOnMissingArgs

# =============================================================================
# Gate — manual approval over the HTTP API
# =============================================================================


@click.group("gate", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def gate(ctx):
    """Gate configuration + post-execution decisions.

    Pre-execution approval is via `mc plan approve` (the task lifecycle).
    `mc gate` is for setting the gate mode and deciding the rare
    post-execution gates (post_task, verification_failed, post_run, ...).
    """
    if ctx.invoked_subcommand is None:
        # Default: show current mode + any pending gates.
        from modules.clients.cli.mc_gate import show as gate_show_fn

        async def _run():
            async with api_client() as api:
                mid = await require_mission(api)
                await gate_show_fn(api, mission_id=mid)

        asyncio.run(_run())


@gate.command("show")
@click.pass_obj
def gate_show(ctx):
    """Show the current gate mode and any pending post-execution gates."""
    from modules.clients.cli.mc_gate import show as gate_show_fn

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await gate_show_fn(api, mission_id=mid)

    asyncio.run(_run())


@gate.command("set")
@click.argument("mode", type=click.Choice(["autonomous", "manual", "interactive", "ai_assisted"]))
@click.pass_obj
def gate_set(ctx, mode):
    """Set the gate mode for the current mission's plan."""
    from modules.clients.cli.mc_gate import set_mode

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await set_mode(api, mission_id=mid, mode=mode)

    asyncio.run(_run())


@gate.command("modes")
@click.pass_obj
def gate_modes(ctx):
    """List the four supported gate modes with descriptions."""
    from modules.clients.cli.mc_gate import list_modes

    async def _run():
        async with api_client() as api:
            await list_modes(api)

    asyncio.run(_run())


@gate.command("pending")
@click.pass_obj
def gate_pending(ctx):
    """List pending post-execution gates (rare)."""
    from modules.clients.cli.mc_gate import pending

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await pending(api, mission_id=mid)

    asyncio.run(_run())


@gate.command("decide")
@click.argument("gate_id")
@click.argument("action")
@click.option("--reason", default=None, help="Optional note attached to the decision.")
@click.pass_obj
def gate_decide(ctx, gate_id, action, reason):
    """Decide a pending post-execution gate.

    Valid actions depend on the gate type:
      post_task / verification_failed:  continue | skip | retry | abort
      post_layer:                       continue | abort
      post_run:                         wait | advance_approved |
                                        advance_refine | propose_complete |
                                        escalate
    """
    from modules.clients.cli.mc_gate import decide

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await decide(api, mission_id=mid, gate_id=gate_id, action=action, reason=reason)

    asyncio.run(_run())
