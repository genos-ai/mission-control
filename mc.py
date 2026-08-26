#!/usr/bin/env python3
"""Mission Control — user CLI (thin HTTP client).

All commands go through the API server. Zero backend service imports.

Usage:
    python mc.py                                       Quick-start guide
    python mc.py run --objective "audit auth module"   Run an objective
    python mc.py chat                                  Talk to your AI team
    python mc.py design                                Design a workflow
    python mc.py status                                Current mission snapshot
    python mc.py history                               Recent runs
    python mc.py mission list                          List missions
    python mc.py mission use --name my-app             Select active mission
    python mc.py login                                 Authenticate with the API
"""

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

import click

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.clients.cli.api_client import (  # noqa: E402 — after sys.path bootstrap
    api_client,
    require_mission,
    setup_cli_logging,
)
from modules.clients.cli.mc_groups.console import console  # noqa: E402
from modules.clients.cli.mc_groups.context import context  # noqa: E402
from modules.clients.cli.mc_groups.gate import gate  # noqa: E402
from modules.clients.cli.mc_groups.intent import intent  # noqa: E402
from modules.clients.cli.mc_groups.knowledge import knowledge  # noqa: E402
from modules.clients.cli.mc_groups.learnings import learnings  # noqa: E402
from modules.clients.cli.mc_groups.mission import mission  # noqa: E402
from modules.clients.cli.mc_groups.plan import plan  # noqa: E402
from modules.clients.cli.mc_groups.runs import runs  # noqa: E402
from modules.clients.cli.mc_groups.schedule import schedule  # noqa: E402
from modules.clients.cli.mc_groups.status_history import (  # noqa: E402
    artifacts,
    history,
    report,
    status,
    trace,
)
from modules.clients.cli.mc_groups.team import team  # noqa: E402

# =============================================================================
# Click utilities (no backend imports)
# =============================================================================


class ShowHelpOnMissingArgs(click.Group):
    """Show full help instead of terse error when required args are missing."""

    def resolve_command(self, ctx, args):
        cmd_name, cmd, remaining = super().resolve_command(ctx, args)
        if cmd is not None and not isinstance(cmd, click.Group):
            required_args = [p for p in cmd.params if isinstance(p, click.Argument) and p.required]
            if required_args and len(remaining) < len(required_args):
                with click.Context(cmd, info_name=cmd_name, parent=ctx) as sub_ctx:
                    click.echo(cmd.get_help(sub_ctx))
                ctx.exit(0)
        return cmd_name, cmd, remaining


@dataclass
class McContext:
    """Lightweight CLI context — no backend dependencies."""

    verbose: bool = False
    debug: bool = False
    quiet: bool = False


# =============================================================================
# Root group
# =============================================================================


@click.group(cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.option("--verbose", "-v", is_flag=True, help="Enable INFO-level logging.")
@click.option("--debug", "-d", is_flag=True, help="Enable DEBUG-level logging.")
@click.option("--quiet", "-q", is_flag=True, help="Minimal output.")
@click.pass_context
def mc(ctx, verbose, debug, quiet):
    """Mission Control — user CLI."""
    ctx.ensure_object(dict)
    ctx.obj = McContext(verbose=verbose, debug=debug, quiet=quiet)
    setup_cli_logging(verbose, debug)
    if ctx.invoked_subcommand is None:
        _show_quickstart()


def _show_quickstart():
    """Formatted quick-start guide."""
    from modules.clients.common.display import get_console

    get_console().print("""
[bold cyan]Mission Control[/bold cyan]

  [bold]Quick Start:[/bold]
    mc login
    mc mission create --name my-app --description "My project"
    mc mission use --name my-app
    mc run --objective "audit the auth module"

  [bold]Work:[/bold]
    mc run --objective <text>     Run a task or workflow
    mc chat                      Talk to your AI team
    mc design                    Design a workflow with the Architect
    mc status                    Current mission snapshot
    mc history                   Recent runs

  [bold]Setup:[/bold]
    mc mission list              List missions
    mc team list                 Your agent team
    mc context show              Mission Context Document

  [dim]Use mc <command> --help for details.[/dim]
""")


# =============================================================================
# Auth commands
# =============================================================================


@mc.command()
@click.option("--email", "-e", default=None, help="Email address.")
@click.option("--password", "-p", default=None, help="Password (prompted if omitted).")
def login(email, password):
    """Authenticate with the Mission Control API."""

    async def _run():
        async with api_client() as api:
            if not email:
                _email = click.prompt("Email")
            else:
                _email = email
            if not password:
                _pw = click.prompt("Password", hide_input=True)
            else:
                _pw = password
            data = await api.login(_email, _pw)
            user = data.get("user", {})
            click.echo(
                click.style(
                    f"Logged in as {user.get('email', _email)}",
                    fg="green",
                )
            )

    asyncio.run(_run())


@mc.command()
def logout():
    """Clear stored authentication."""

    async def _run():
        async with api_client() as api:
            await api.logout()
        click.echo("Logged out.")

    asyncio.run(_run())


mc.add_command(mission)
# =============================================================================
# Run command
# =============================================================================


@mc.command()
@click.option("--objective", "-o", required=True, help="Objective text or workflow name.")
@click.option("--budget", type=float, default=None, help="Cost ceiling override.")
@click.option(
    "--gate",
    "gate_override",
    type=click.Choice(["interactive", "manual", "ai_assisted", "autonomous"]),
    default=None,
    help="Gate mode override.",
)
@click.option("--step", is_flag=True, help="Alias for --gate interactive.")
@click.option("--dry-run", is_flag=True, help="Show plan + estimated cost, don't execute.")
@click.option("--context", "-c", multiple=True, help="Context overrides as key=value (repeatable).")
@click.pass_obj
def run(ctx, objective, budget, gate_override, step, dry_run, context):
    """Run a task or workflow against the current mission."""
    if step:
        gate_override = "interactive"

    # Parse --context key=value pairs
    context_overrides = {}
    for item in context:
        if "=" not in item:
            click.echo(
                click.style(f"Invalid --context: '{item}' (expected key=value)", fg="red"), err=True
            )
            raise SystemExit(1)
        key, value = item.split("=", 1)
        context_overrides[key] = value

    from modules.clients.cli.mc_run import run as mc_run

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await mc_run(
                api,
                objective,
                mission_id=mid,
                budget=budget,
                gate_override=gate_override,
                dry_run=dry_run,
                quiet=ctx.quiet,
                verbose=ctx.verbose,
                context_overrides=context_overrides or None,
            )

    asyncio.run(_run())


mc.add_command(runs)
# =============================================================================
# Retry command
# =============================================================================


@mc.command()
@click.option("--run", "n", type=int, required=True, help="Nth most recent execution to retry.")
@click.option(
    "--gate",
    "gate_override",
    type=click.Choice(["interactive", "manual", "ai_assisted", "autonomous"]),
    default=None,
    help="Gate mode override.",
)
@click.pass_obj
def retry(ctx, n, gate_override):
    """Retry failed plan tasks, or re-run a past execution."""
    from modules.clients.cli.mc_run import retry as mc_retry

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await mc_retry(
                api,
                n,
                mission_id=mid,
                gate_override=gate_override,
                quiet=ctx.quiet,
                verbose=ctx.verbose,
            )

    asyncio.run(_run())


mc.add_command(plan)
mc.add_command(gate)
mc.add_command(schedule)
mc.add_command(status)
mc.add_command(history)
mc.add_command(artifacts)
mc.add_command(report)
mc.add_command(trace)
# =============================================================================
# Chat + Design
# =============================================================================


@mc.command()
@click.option("--message", "-m", default=None, help="Single-shot message (skips REPL).")
@click.option(
    "--agent",
    "-a",
    "agent_name",
    default=None,
    help="Target a specific agent (default: mission director).",
)
@click.option(
    "--new", "new_thread", is_flag=True, help="Start a new conversation thread instead of resuming."
)
@click.pass_obj
def chat(ctx, message, agent_name, new_thread):
    """Talk to your AI team. Interactive REPL or single-shot.

    Resumes the most recent conversation by default. Use --new to
    start a fresh thread. The web frontend and CLI share the same
    threads — both see the same conversation history.
    """
    from modules.clients.cli.mc_chat import chat_repl

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await chat_repl(
                api,
                agent_name=agent_name,
                initial_message=message,
                mission_id=mid,
                verbose=ctx.verbose,
                new_thread=new_thread,
            )

    asyncio.run(_run())


@mc.command()
@click.option("--description", "-d", default=None, help="Initial description of the workflow.")
@click.pass_obj
def design(ctx, description):
    """Design a workflow with the Architect."""
    from modules.clients.cli.mc_chat import design_repl

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await design_repl(api, description=description, mission_id=mid, verbose=ctx.verbose)

    asyncio.run(_run())


mc.add_command(team)
mc.add_command(context)
mc.add_command(intent)
mc.add_command(learnings)
mc.add_command(knowledge)
# =============================================================================
# Tree command
# =============================================================================


@mc.command()
def tree():
    """Show all commands in a tree structure."""
    from rich.tree import Tree

    from modules.clients.common.display import get_console

    console_obj = get_console()

    def _build(group: click.Group, node: Tree) -> None:
        for name in sorted(group.commands):
            cmd = group.commands[name]
            label = f"[cyan]{name}[/cyan]"
            if cmd.help:
                short = cmd.help.split("\n")[0]
                label += f"  [dim]{short}[/dim]"
            child = node.add(label)
            if isinstance(cmd, click.Group):
                _build(cmd, child)

    root = Tree("[bold cyan]mc[/bold cyan]  [dim]Mission Control \u2014 user CLI[/dim]")
    _build(mc, root)
    console_obj.print(root)


mc.add_command(console)
# =============================================================================
# Entry point
# =============================================================================


if __name__ == "__main__":
    mc()
