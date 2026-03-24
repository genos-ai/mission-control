"""
CLI handler for --service db.

Thin presentation layer over DatabaseAdminService.
Parses args, calls the service, renders output.
"""

import asyncio
import sys

import click

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def run_db(
    cli_logger,
    action: str,
    table: str | None,
    limit: int,
    confirm: bool,
    include_missions: bool = False,
) -> None:
    """Dispatch db CLI actions."""
    actions = {
        "stats": _action_stats,
        "tables": _action_tables,
        "query": _action_query,
        "clear": _action_clear,
        "clear-executions": _action_clear_executions,
        "clear-sessions": _action_clear_sessions,
    }

    handler = actions.get(action)
    if not handler:
        click.echo(
            click.style(
                f"Unknown db action: {action}. "
                f"Valid: {', '.join(actions.keys())}",
                fg="red",
            ),
            err=True,
        )
        sys.exit(1)

    try:
        asyncio.run(handler(
            cli_logger,
            table=table,
            limit=limit,
            confirm=confirm,
            include_missions=include_missions,
        ))
    except (OSError, RuntimeError, ValueError) as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)
        cli_logger.error("DB action failed", extra={"action": action, "error": str(e)})
        sys.exit(1)


# =============================================================================
# Actions
# =============================================================================


async def _action_stats(cli_logger, *, table, limit, confirm, **_):
    """Show row counts for all tables."""
    from modules.backend.services.database_admin import DatabaseAdminService
    from modules.clients.cli.report import get_console, build_table

    console = get_console()

    async with DatabaseAdminService.factory() as svc:
        counts = await svc.get_table_row_counts()

    tbl_table = build_table("Database Statistics", columns=[
        ("Table", {"style": "cyan", "width": 28}),
        ("Rows",  {"justify": "right", "width": 10}),
    ])

    total = 0
    for tbl_name, count in counts:
        total += count
        count_str = f"[green]{count}[/green]" if count else str(count)
        tbl_table.add_row(tbl_name, count_str)
    tbl_table.add_row("[bold]TOTAL[/bold]", f"[bold]{total}[/bold]", end_section=True)

    console.print(tbl_table)


async def _action_tables(cli_logger, *, table, limit, confirm, **_):
    """List all application tables with column info."""
    from modules.backend.services.database_admin import ALL_TABLES, DatabaseAdminService
    from modules.clients.cli.report import get_console, build_table

    console = get_console()

    async with DatabaseAdminService.factory() as svc:
        for tbl in ALL_TABLES:
            columns = await svc.get_table_columns(tbl)
            count = await svc.get_table_row_count(tbl)

            col_table = build_table(f"{tbl}  ({count} rows)", columns=[
                ("Column",   {"style": "cyan", "width": 30}),
                ("Type",     {"width": 22}),
                ("Nullable", {"width": 10}),
            ])
            for col_name, data_type, nullable in columns:
                null_str = "yes" if nullable == "YES" else "[dim]NOT NULL[/dim]"
                col_table.add_row(col_name, data_type, null_str)
            console.print(col_table)


async def _action_query(cli_logger, *, table, limit, confirm, **_):
    """Query recent rows from a table."""
    from modules.backend.services.database_admin import ALL_TABLES, DatabaseAdminService

    if not table:
        click.echo(click.style("Error: --table is required for query.", fg="red"), err=True)
        click.echo(f"Available tables: {', '.join(ALL_TABLES)}")
        sys.exit(1)

    if table not in ALL_TABLES:
        click.echo(click.style(f"Error: unknown table '{table}'.", fg="red"), err=True)
        click.echo(f"Available tables: {', '.join(ALL_TABLES)}")
        sys.exit(1)

    async with DatabaseAdminService.factory() as svc:
        columns, rows = await svc.query_recent_rows(table, limit=limit)

    if not rows:
        click.echo(f"No rows in {table}.")
        return

    from modules.clients.cli.report import get_console, build_table

    console = get_console()
    row_table = build_table(f"{table}  ({len(rows)} rows shown)", columns=[
        ("Column", {"style": "cyan", "width": 30}),
        ("Value",  {"ratio": 1}),
    ], show_lines=True)

    for i, row in enumerate(rows):
        row_table.add_row(f"[dim]--- Row {i + 1} ---[/dim]", "", end_section=True)
        for col, val in zip(columns, row):
            row_table.add_row(col, _format_value(val))

    console.print(row_table)


async def _action_clear(cli_logger, *, table, limit, confirm, include_missions=False, **_):
    """Clear run data. Use --include-projects for full reset."""
    from modules.backend.services.database_admin import (
        ALL_TABLES,
        RUN_TABLES,
        DatabaseAdminService,
    )

    tables = ALL_TABLES if include_missions else RUN_TABLES

    if not confirm:
        if include_missions:
            click.echo(click.style(
                "This will DELETE ALL DATA including projects and context.",
                fg="red", bold=True,
            ))
        else:
            click.echo(click.style(
                "This will DELETE run data (executions, sessions, workflow runs).",
                fg="red", bold=True,
            ))
            click.echo("Projects and PCD are preserved. Use --include-projects for full reset.")
        click.echo(f"Tables: {', '.join(tables)}")
        click.echo()
        if not click.confirm("Are you sure?"):
            click.echo("Aborted.")
            return

    async with DatabaseAdminService.factory() as svc:
        await svc.truncate_tables(tables)

    scope = "All application data" if include_missions else "Run data"
    click.echo(click.style(f"{scope} cleared.", fg="green"))


async def _action_clear_executions(cli_logger, *, table, limit, confirm, **_):
    """Clear execution-related data only."""
    from modules.backend.services.database_admin import EXECUTION_TABLES, DatabaseAdminService

    if not confirm:
        click.echo(click.style("This will DELETE all execution data.", fg="red", bold=True))
        click.echo(f"Tables: {', '.join(EXECUTION_TABLES)}")
        click.echo()
        if not click.confirm("Are you sure?"):
            click.echo("Aborted.")
            return

    async with DatabaseAdminService.factory() as svc:
        await svc.truncate_tables(EXECUTION_TABLES)

    click.echo(click.style("Execution data cleared.", fg="green"))


async def _action_clear_sessions(cli_logger, *, table, limit, confirm, **_):
    """Clear session-related data only."""
    from modules.backend.services.database_admin import SESSION_TABLES, DatabaseAdminService

    if not confirm:
        click.echo(click.style("This will DELETE all session data.", fg="red", bold=True))
        click.echo(f"Tables: {', '.join(SESSION_TABLES)}")
        click.echo()
        if not click.confirm("Are you sure?"):
            click.echo("Aborted.")
            return

    async with DatabaseAdminService.factory() as svc:
        await svc.truncate_tables(SESSION_TABLES)

    click.echo(click.style("Session data cleared.", fg="green"))


# =============================================================================
# Helpers
# =============================================================================


def _format_value(val) -> str:
    """Format a DB value for display, truncating long strings."""
    if val is None:
        return click.style("NULL", dim=True)
    s = str(val)
    if len(s) > 120:
        return s[:117] + "..."
    return s
