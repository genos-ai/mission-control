"""Admin CLI — Migrate (Plan 84 Phase 5.5, split out of root admin.py).

Pure move, no behavior change.
"""

import click

from modules.clients.cli.cli_context import ShowHelpOnMissingArgs

# =============================================================================
# Migrate
# =============================================================================


@click.group(cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def migrate(ctx):
    """Database migrations (Alembic).

    \b
    Examples:
        python admin.py migrate current
        python admin.py migrate upgrade head
        python admin.py migrate autogenerate -m "add table"
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@migrate.command()
@click.argument("revision", default="head")
@click.pass_obj
def upgrade(ctx, revision: str):
    """Upgrade database to a revision (default: head)."""
    from modules.clients.cli.migrate import run_migrations

    run_migrations(ctx.logger, "upgrade", revision, None)


@migrate.command()
@click.argument("revision")
@click.pass_obj
def downgrade(ctx, revision: str):
    """Downgrade database to a revision."""
    from modules.clients.cli.migrate import run_migrations

    run_migrations(ctx.logger, "downgrade", revision, None)


@migrate.command()
@click.pass_obj
def current(ctx):
    """Show current database revision."""
    from modules.clients.cli.migrate import run_migrations

    run_migrations(ctx.logger, "current", "head", None)


@migrate.command()
@click.pass_obj
def history(ctx):
    """Show migration history."""
    from modules.clients.cli.migrate import run_migrations

    run_migrations(ctx.logger, "history", "head", None)


@migrate.command()
@click.option("-m", "--message", required=True, help="Migration message.")
@click.pass_obj
def autogenerate(ctx, message: str):
    """Auto-generate migration from model changes."""
    from modules.clients.cli.migrate import run_migrations

    run_migrations(ctx.logger, "autogenerate", "head", message)
