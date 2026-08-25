"""Admin CLI — DB group (Plan 84 Phase 5.5, split out of root admin.py).

Pure move, no behavior change.
"""

import click

from modules.clients.cli.cli_context import ShowHelpOnMissingArgs

# =============================================================================
# DB group
# =============================================================================


@click.group(cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def db(ctx):
    """Database inspection and management.

    \b
    Examples:
        python admin.py db stats
        python admin.py db query missions --limit 5
        python admin.py db clear --yes
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@db.command("stats")
@click.pass_obj
def db_stats(ctx):
    """Show row counts for all tables."""
    from modules.clients.cli.db import run_db

    run_db(ctx.logger, action="stats", table=None, limit=10, confirm=False)


@db.command("tables")
@click.pass_obj
def db_tables(ctx):
    """Show table schemas (columns, types, nullability)."""
    from modules.clients.cli.db import run_db

    run_db(ctx.logger, action="tables", table=None, limit=10, confirm=False)


@db.command("query")
@click.argument("table")
@click.option("--limit", default=10, type=int, help="Number of rows to show.")
@click.pass_obj
def db_query(ctx, table, limit):
    """Query recent rows from a table."""
    from modules.clients.cli.db import run_db

    run_db(ctx.logger, action="query", table=table, limit=limit, confirm=False)


@db.command("clear")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@click.option(
    "--include-missions",
    is_flag=True,
    default=False,
    help="Also clear missions and MCD (full nuclear reset).",
)
@click.pass_obj
def db_clear(ctx, yes, include_missions):
    """Clear run data. Missions and MCD are preserved by default."""
    from modules.clients.cli.db import run_db

    run_db(
        ctx.logger,
        action="clear",
        table=None,
        limit=10,
        confirm=yes,
        include_missions=include_missions,
    )


@db.command("clear-executions")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@click.pass_obj
def db_clear_executions(ctx, yes):
    """Clear execution data only."""
    from modules.clients.cli.db import run_db

    run_db(ctx.logger, action="clear-executions", table=None, limit=10, confirm=yes)


@db.command("clear-sessions")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@click.pass_obj
def db_clear_sessions(ctx, yes):
    """Clear session data only."""
    from modules.clients.cli.db import run_db

    run_db(ctx.logger, action="clear-sessions", table=None, limit=10, confirm=yes)


@db.command("clear-tasks")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@click.pass_obj
def db_clear_tasks(ctx, yes):
    """Clear all tasks and task dependencies (Plan 72)."""
    from modules.clients.cli.db import run_db

    run_db(ctx.logger, action="clear-tasks", table=None, limit=10, confirm=yes)
