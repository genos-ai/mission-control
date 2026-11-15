"""mc CLI — notify — mission notification recipients (Plan 88 step 88.4.4, contracts 3.5.4).

Recipients receive the current mission's notifications on Telegram once they
have a confirmed Telegram identity. Kinds are lowercase NotificationKind values.
"""

import asyncio

import click

from modules.clients.cli.api_client import api_client, require_mission
from modules.clients.cli.cli_context import ShowHelpOnMissingArgs


@click.group("notify", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def notify(ctx):
    """Mission notifications.

    \b
    Examples:
        mc notify recipients list
        mc notify recipients add alice@example.com --kind run_failed --kind gate_waiting
        mc notify recipients remove alice@example.com
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@notify.group("recipients", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def recipients(ctx):
    """Who receives the current mission's notifications."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@recipients.command("list")
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output.")
@click.pass_obj
def recipients_list(ctx, as_json):
    """List the current mission's recipients."""
    from modules.clients.cli.mc_notify import list_recipients

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await list_recipients(api, mission_id=mid, as_json=as_json)

    asyncio.run(_run())


@recipients.command("add")
@click.argument("email")
@click.option(
    "--kind",
    "kinds",
    multiple=True,
    help="Lowercase notification kind, e.g. run_failed (repeatable; the API validates it). "
    "Default: notifications.default_kinds.",
)
@click.pass_obj
def recipients_add(ctx, email, kinds):
    """Add the mission owner or a member, by email, as a Telegram recipient."""
    from modules.clients.cli.mc_notify import add_recipient

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await add_recipient(api, mission_id=mid, email=email, kinds=kinds)

    asyncio.run(_run())


@recipients.command("remove")
@click.argument("email")
@click.pass_obj
def recipients_remove(ctx, email):
    """Remove the recipient with this email."""
    from modules.clients.cli.mc_notify import remove_recipient

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await remove_recipient(api, mission_id=mid, email=email)

    asyncio.run(_run())
