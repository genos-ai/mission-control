"""Admin CLI — Architect (Plan 84 Phase 5.5, split out of root admin.py).

Pure move, no behavior change.
"""

import click

from modules.clients.cli.cli_context import ShowHelpOnMissingArgs

# =============================================================================
# Architect
# =============================================================================


@click.group("architect", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def architect(ctx):
    """Design workflows with the Workflow Architect.

    \b
    Examples:
        admin.py architect chat --mission <ID> --message "Design a code review workflow"
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@architect.command("chat")
@click.option("--mission", "mission_id", required=True, help="Mission ID.")
@click.option("--message", required=True, help="Message to the Workflow Architect.")
@click.pass_obj
def architect_chat(ctx, mission_id, message):
    """Send a message to the Workflow Architect for conversational design."""
    from modules.clients.cli.architect_cmds import run_architect

    run_architect(
        ctx.logger, "chat", mission_id=mission_id, message=message, output_format=ctx.output_format
    )
