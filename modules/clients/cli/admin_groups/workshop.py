"""Admin CLI — Workshop (Plan 84 Phase 5.5, split out of root admin.py).

Pure move, no behavior change.
"""

import click

from modules.clients.cli.cli_context import ShowHelpOnMissingArgs

# =============================================================================
# Workshop
# =============================================================================


@click.group("workshop", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def workshop(ctx):
    """Run agents in workshop (sandbox) mode for testing and prompt iteration.

    \b
    Examples:
        admin.py workshop run code.qa.agent --inputs '{"target": "modules/"}'
        admin.py workshop cached-inputs code.qa.agent --mission <ID>
        admin.py workshop history --agent code.qa.agent
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@workshop.command("run")
@click.argument("agent_name")
@click.option("--inputs", "inputs_json", default=None, help="JSON string of input data.")
@click.option("--prompt-override", default=None, help="Temporary system prompt override.")
@click.pass_obj
def workshop_run(ctx, agent_name, inputs_json, prompt_override):
    """Run a single agent in isolation for testing."""
    from modules.clients.cli.workshop_cmds import run_workshop

    run_workshop(
        ctx.logger,
        "run",
        agent_name=agent_name,
        inputs_json=inputs_json,
        prompt_override=prompt_override,
        output_format=ctx.output_format,
    )


@workshop.command("cached-inputs")
@click.argument("agent_name")
@click.option("--mission", "mission_id", default=None, help="Scope to a specific mission.")
@click.option("--limit", default=10, help="Max results.")
@click.pass_obj
def workshop_cached_inputs(ctx, agent_name, mission_id, limit):
    """Show cached inputs from previous runs of this agent."""
    from modules.clients.cli.workshop_cmds import run_workshop

    run_workshop(
        ctx.logger,
        "cached-inputs",
        agent_name=agent_name,
        mission_id=mission_id,
        limit=limit,
        output_format=ctx.output_format,
    )


@workshop.command("history")
@click.option("--agent", "agent_name", default=None, help="Filter by agent name.")
@click.option("--limit", default=20, help="Max results.")
@click.pass_obj
def workshop_history(ctx, agent_name, limit):
    """List workshop run history."""
    from modules.clients.cli.workshop_cmds import run_workshop

    run_workshop(
        ctx.logger, "history", agent_name=agent_name, limit=limit, output_format=ctx.output_format
    )
