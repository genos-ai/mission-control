#!/usr/bin/env python3
"""
Mission Control — Admin CLI.

Usage:
    python admin.py --help
    python admin.py server --verbose
    python admin.py server stop
    python admin.py health
    python admin.py test unit --coverage
    python admin.py agent "run a health check"
    python admin.py execution run "audit the platform"
    python admin.py execution list
    python admin.py execution cost <id>
    python admin.py db stats
    python admin.py db query missions --limit 5
    python admin.py db clear --yes
    python admin.py workflow list
    python admin.py workflow run ops.platform-audit --mission my-app
    python admin.py credits
    python admin.py console monitor
    python admin.py console monitor --view developer
"""

import sys
from pathlib import Path

import click

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.clients.cli.admin_groups.admin_ops import admin  # noqa: E402
from modules.clients.cli.admin_groups.architect import architect  # noqa: E402
from modules.clients.cli.admin_groups.catalog import catalog  # noqa: E402
from modules.clients.cli.admin_groups.console import console  # noqa: E402
from modules.clients.cli.admin_groups.context import context  # noqa: E402
from modules.clients.cli.admin_groups.db import db  # noqa: E402
from modules.clients.cli.admin_groups.execution import execution  # noqa: E402
from modules.clients.cli.admin_groups.migrate import migrate  # noqa: E402
from modules.clients.cli.admin_groups.mission import mission  # noqa: E402
from modules.clients.cli.admin_groups.schedule import schedule  # noqa: E402
from modules.clients.cli.admin_groups.server import server  # noqa: E402
from modules.clients.cli.admin_groups.workflow import workflow  # noqa: E402
from modules.clients.cli.admin_groups.workshop import workshop  # noqa: E402
from modules.clients.cli.cli_context import CliContext, ShowHelpOnMissingArgs  # noqa: E402

# Unified output format for all commands — single source of truth.
OUTPUT_FORMATS = click.Choice(["human", "json", "jsonl"])


@click.group(cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.option("--verbose", "-v", is_flag=True, help="Enable INFO-level logging.")
@click.option("--debug", "-d", is_flag=True, help="Enable DEBUG-level logging.")
@click.option(
    "-o",
    "--output",
    "output_format",
    default="human",
    type=OUTPUT_FORMATS,
    help="Output format (human, json, jsonl).",
)
@click.pass_context
def admin_cli(ctx, verbose: bool, debug: bool, output_format: str):
    """Mission Control — Admin CLI.

    \b
    Infrastructure:  server, telegram
    Diagnostics:     health, config, info, credits, context
    Development:     test, migrate, db
    Agents:          agent, execution, workflow
    Missions:        mission
    """
    ctx.ensure_object(dict)
    ctx.obj = CliContext(verbose, debug, output_format=output_format, source="admin")
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# =============================================================================
# Simple commands — no subcommands
# =============================================================================


@admin_cli.command()
@click.pass_obj
def health(ctx):
    """Run local health checks."""
    from modules.clients.cli.health import check_health

    check_health(ctx.logger, output_format=ctx.output_format)


@admin_cli.command()
@click.pass_obj
def config(ctx):
    """Display loaded YAML configuration."""
    from modules.clients.cli.config_display import show_config

    show_config(ctx.logger, output_format=ctx.output_format)


@admin_cli.command()
@click.pass_obj
def info(ctx):
    """Show application metadata and version."""
    from modules.clients.cli.info import show_info

    show_info(ctx.logger, output_format=ctx.output_format)


@admin_cli.command()
@click.option("--roster", default="default", help="Roster to check models from.")
@click.pass_obj
def credits(ctx, roster: str):
    """Preflight credit check — verify all roster models have available credits."""
    from modules.clients.cli.credits import check_credits

    check_credits(ctx.logger, roster=roster, output_format=ctx.output_format)


# =============================================================================
# Agent dispatch
# =============================================================================


@admin_cli.command()
@click.argument("message", required=False, default=None)
@click.option("--name", default=None, help="Target a specific agent, bypassing routing.")
@click.option("--list", "list_agents", is_flag=True, help="List available agents.")
@click.pass_context
def agent(ctx, message: str | None, name: str | None, list_agents: bool):
    """Send a message to an agent.

    \b
    Examples:
        python admin.py agent "run a health check"
        python admin.py agent "scan code quality" --name software.quality.agent
        python admin.py -o jsonl agent "check health"
        python admin.py agent --list
    """
    if list_agents:
        from modules.clients.cli.agent import show_agents

        show_agents(ctx.obj.logger)
        return
    if not message:
        click.echo(ctx.get_help())
        return
    from modules.clients.cli.agent import run_agent

    run_agent(ctx.obj.logger, message, name, ctx.obj.output_format)


admin_cli.add_command(server)
# =============================================================================
# Telegram
# =============================================================================


@admin_cli.command()
@click.pass_obj
def telegram(ctx):
    """Start the Telegram bot in polling mode."""
    from modules.clients.cli.telegram import run_telegram_poll

    run_telegram_poll(ctx.logger)


# =============================================================================
# Test
# =============================================================================


@admin_cli.command()
@click.argument("type", default="all", type=click.Choice(["all", "unit", "integration", "e2e"]))
@click.option("--coverage", is_flag=True, help="Run with coverage reporting.")
@click.pass_obj
def test(ctx, type: str, coverage: bool):
    """Run the test suite.

    \b
    Examples:
        python admin.py test unit
        python admin.py test unit --coverage
        python admin.py test integration
    """
    from modules.clients.cli.testing import run_tests

    run_tests(ctx.logger, type, coverage)


admin_cli.add_command(migrate)
admin_cli.add_command(execution)
admin_cli.add_command(workflow)
admin_cli.add_command(mission)
admin_cli.add_command(context)
admin_cli.add_command(db)
# =============================================================================
# Tree — show full command hierarchy
# =============================================================================


def _format_tree(group: click.Group, prefix: str = "", is_last: bool = True) -> list[str]:
    """Recursively build a tree representation of a Click group."""
    lines: list[str] = []
    commands = sorted(group.list_commands(click.Context(group)))

    for i, name in enumerate(commands):
        cmd = group.get_command(click.Context(group), name)
        if cmd is None:
            continue

        last = i == len(commands) - 1
        connector = "└── " if last else "├── "
        child_prefix = prefix + ("    " if last else "│   ")

        # Build the label: name + params + options
        parts = [name]
        if hasattr(cmd, "params"):
            for param in cmd.params:
                if isinstance(param, click.Argument):
                    parts.append(param.human_readable_name.upper())
                elif isinstance(param, click.Option) and param.name not in (
                    "help",
                    "verbose",
                    "debug",
                ):
                    flag = param.opts[-1]
                    parts.append(f"[{flag}]")

        label = " ".join(parts)
        help_text = cmd.get_short_help_str(limit=60) if cmd.help else ""
        if help_text:
            label = f"{label}  — {help_text}"

        lines.append(f"{prefix}{connector}{label}")

        if isinstance(cmd, click.Group):
            lines.extend(_format_tree(cmd, child_prefix, last))

    return lines


admin_cli.add_command(catalog)
admin_cli.add_command(admin)
admin_cli.add_command(schedule)
# =============================================================================
# Tree command
# =============================================================================


@admin_cli.command("tree")
def tree_cmd():
    """Show the full command tree with all options."""
    click.echo("admin")
    lines = _format_tree(admin_cli)
    click.echo("\n".join(lines))


admin_cli.add_command(architect)
admin_cli.add_command(workshop)
admin_cli.add_command(console)
# =============================================================================
# Entry point
# =============================================================================


if __name__ == "__main__":
    admin_cli()
