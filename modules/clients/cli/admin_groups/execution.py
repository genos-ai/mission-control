"""Admin CLI — Execution group (Plan 84 Phase 5.5, split out of root admin.py).

Pure move, no behavior change.
"""

import click

from modules.clients.cli.cli_context import ShowHelpOnMissingArgs

# =============================================================================
# Execution group
# =============================================================================


@click.group(cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def execution(ctx):
    """Create, execute, and inspect executions.

    \b
    Examples:
        python admin.py execution run "audit the platform" --budget 2.00
        python admin.py execution list
        python admin.py execution detail <id>
        python admin.py execution cost <id>
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@execution.command("run")
@click.argument("objective")
@click.option("--roster", default="default", help="Agent roster to use.")
@click.option("--budget", default=None, type=float, help="Cost ceiling in USD.")
@click.option("--triggered-by", default="user:admin", help="Trigger origin.")
@click.option(
    "--mission",
    "-m",
    "mission_id",
    default=None,
    help="Mission ID (uses current mission if not specified).",
)
@click.pass_obj
def execution_run(ctx, objective, roster, budget, triggered_by, mission_id):
    """Create and execute in one step."""
    from modules.clients.cli.execution_cmds import run_execution

    run_execution(
        ctx.logger,
        action="run",
        objective=objective,
        execution_id=None,
        roster=roster,
        budget=budget,
        triggered_by=triggered_by,
        output_format=ctx.output_format,
        mission_id=mission_id,
    )


@execution.command("create")
@click.argument("objective")
@click.option("--roster", default="default", help="Agent roster to use.")
@click.option("--budget", default=None, type=float, help="Cost ceiling in USD.")
@click.option("--triggered-by", default="user:admin", help="Trigger origin.")
@click.option(
    "--mission",
    "-m",
    "mission_id",
    default=None,
    help="Mission ID (uses current mission if not specified).",
)
@click.pass_obj
def execution_create(ctx, objective, roster, budget, triggered_by, mission_id):
    """Create an execution (PENDING state, not yet executed)."""
    from modules.clients.cli.execution_cmds import run_execution

    run_execution(
        ctx.logger,
        action="create",
        objective=objective,
        execution_id=None,
        roster=roster,
        budget=budget,
        triggered_by=triggered_by,
        output_format=ctx.output_format,
        mission_id=mission_id,
    )


@execution.command("execute")
@click.argument("execution_id")
@click.option("--roster", default="default", help="Agent roster to use.")
@click.pass_obj
def execution_execute(ctx, execution_id, roster):
    """Execute an existing PENDING execution."""
    from modules.clients.cli.execution_cmds import run_execution

    run_execution(
        ctx.logger,
        action="execute",
        objective=None,
        execution_id=execution_id,
        roster=roster,
        budget=None,
        triggered_by="user:admin",
        output_format=ctx.output_format,
    )


@execution.command("list")
@click.pass_obj
def execution_list(ctx):
    """List recent executions."""
    from modules.clients.cli.execution_cmds import run_execution

    run_execution(
        ctx.logger,
        action="list",
        objective=None,
        execution_id=None,
        roster="default",
        budget=None,
        triggered_by="user:admin",
        output_format=ctx.output_format,
    )


@execution.command("detail")
@click.argument("execution_id")
@click.pass_obj
def execution_detail(ctx, execution_id):
    """Show execution detail with task results."""
    from modules.clients.cli.execution_cmds import run_execution

    run_execution(
        ctx.logger,
        action="detail",
        objective=None,
        execution_id=execution_id,
        roster="default",
        budget=None,
        triggered_by="user:admin",
        output_format=ctx.output_format,
    )


@execution.command("plan")
@click.argument("execution_id")
@click.pass_obj
def execution_plan(ctx, execution_id):
    """Show the TaskPlan DAG for an execution."""
    from modules.clients.cli.execution_cmds import run_execution

    run_execution(
        ctx.logger,
        action="plan",
        objective=None,
        execution_id=execution_id,
        roster="default",
        budget=None,
        triggered_by="user:admin",
        output_format=ctx.output_format,
    )


@execution.command("cost")
@click.argument("execution_id")
@click.pass_obj
def execution_cost(ctx, execution_id):
    """Show execution cost breakdown."""
    from modules.clients.cli.execution_cmds import run_execution

    run_execution(
        ctx.logger,
        action="cost",
        objective=None,
        execution_id=execution_id,
        roster="default",
        budget=None,
        triggered_by="user:admin",
        output_format=ctx.output_format,
    )
