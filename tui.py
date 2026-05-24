"""
TUI Client — Mission Control Dashboard.

In-process interactive terminal interface for the agentic AI platform.
Calls backend services directly (not via HTTP) for gate integration
and real-time event streaming.

Usage:
    python tui.py                Launch the dashboard
    python tui.py --verbose      Launch with INFO logging
    python tui.py --debug        Launch with DEBUG logging
    python tui.py tree           Show all commands (rule 010.1)
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

import click

from modules.backend.core.config import validate_project_root
from modules.backend.core.logging import bind_context, get_logger, setup_logging


@click.group(invoke_without_command=True)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output (INFO level logging).")
@click.option("--debug", "-d", is_flag=True, help="Enable debug output (DEBUG level logging).")
@click.pass_context
def main(ctx: click.Context, verbose: bool, debug: bool) -> None:
    """Mission Control — Interactive Agent Dashboard."""
    if ctx.invoked_subcommand is not None:
        return

    validate_project_root()

    # Disable console logging — Textual owns stdout/stderr.
    # All logs go to var/logs/system.jsonl (configured in logging.yaml).
    if debug:
        setup_logging(level="DEBUG", enable_console=False)
    elif verbose:
        setup_logging(level="INFO", enable_console=False)
    else:
        setup_logging(level="WARNING", enable_console=False)

    bind_context(source="tui")

    logger = get_logger(__name__)
    logger.debug("Starting Mission Control TUI", extra={"debug": debug, "verbose": verbose})

    from modules.clients.tui import MissionControlApp

    app = MissionControlApp()
    app.run()


@main.command()
def tree() -> None:
    """Show all commands in a tree structure (rule 010.1)."""
    from rich.tree import Tree

    from modules.clients.common.display import get_console

    console_obj = get_console()
    root = Tree(
        "[bold cyan]tui[/bold cyan]  [dim]Mission Control — Interactive Agent Dashboard[/dim]"
    )
    for name in sorted(main.commands):
        cmd = main.commands[name]
        label = f"[cyan]{name}[/cyan]"
        if cmd.help:
            short = cmd.help.split("\n")[0]
            label += f"  [dim]{short}[/dim]"
        root.add(label)
    console_obj.print(root)


if __name__ == "__main__":
    main()
