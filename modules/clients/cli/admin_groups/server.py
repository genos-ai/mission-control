"""Admin CLI — Server (with lifecycle actions) (Plan 84 Phase 5.5, split out of root admin.py).

Pure move, no behavior change.
"""

import click

from modules.clients.cli.cli_context import ShowHelpOnMissingArgs

# =============================================================================
# Server (with lifecycle actions)
# =============================================================================


@click.group(cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def server(ctx):
    """Manage the API server lifecycle.

    \b
    Examples:
        python admin.py server start --reload --port 8099
        python admin.py server stop
        python admin.py server status
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@server.command()
@click.option("--host", default=None, help="Server host.")
@click.option("--port", default=None, type=int, help="Server port.")
@click.option("--reload", is_flag=True, help="Enable auto-reload.")
@click.pass_obj
def start(ctx, host, port, reload):
    """Start the API server."""
    from modules.clients.cli.server import run_server

    run_server(ctx.logger, host, port, reload)


@server.command()
@click.option("--port", default=None, type=int, help="Port to stop.")
@click.pass_obj
def stop(ctx, port):
    """Stop a running server."""
    from modules.clients.cli.helpers import get_service_port, service_stop

    service_stop(ctx.logger, "server", get_service_port(port))


@server.command()
@click.option("--port", default=None, type=int, help="Port to check.")
@click.pass_obj
def status(ctx, port):
    """Check if the server is running."""
    from modules.clients.cli.helpers import get_service_port, service_status

    service_status(ctx.logger, "server", get_service_port(port))


@server.command()
@click.option("--host", default=None, help="Server host.")
@click.option("--port", default=None, type=int, help="Server port.")
@click.option("--reload", is_flag=True, help="Enable auto-reload.")
@click.pass_obj
def restart(ctx, host, port, reload):
    """Restart the server (stop then start)."""
    import time

    from modules.clients.cli.helpers import get_service_port, service_stop
    from modules.clients.cli.server import run_server

    service_stop(ctx.logger, "server", get_service_port(port))
    time.sleep(2)
    run_server(ctx.logger, host, port, reload)
