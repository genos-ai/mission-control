#!/usr/bin/env python3
"""Mission Control — user CLI.

Usage:
    python mc.py                          Quick-start guide
    python mc.py run "audit auth module"  Run an objective
    python mc.py run ops.platform-audit   Run a workflow
    python mc.py chat                     Talk to your AI team
    python mc.py design                   Design a workflow with the Architect
    python mc.py status                   Current mission snapshot
    python mc.py history                  Recent runs
    python mc.py mission list             List missions
    python mc.py mission use my-app       Select active mission
"""

import asyncio
import sys
from pathlib import Path

import click

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.clients.cli.cli_context import CliContext, ShowHelpOnMissingArgs


# =============================================================================
# Mission guard
# =============================================================================


_MC_MISSION_HINT = (
    "No mission selected.\n\n"
    "  Set one with:  mc mission use <name>\n"
    "  Or create:     mc mission create --name my-project --description '...'\n"
)


async def _async_require_mission() -> str:
    """Resolve current mission or exit with user-friendly error.

    Wraps async_require_mission_id() with mc-specific error formatting.
    """
    from modules.clients.cli.mission_context import async_require_mission_id

    try:
        return await async_require_mission_id(None)
    except click.UsageError:
        click.echo(click.style(_MC_MISSION_HINT, fg="yellow"))
        raise SystemExit(1)


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
    ctx.obj = CliContext(verbose=verbose, debug=debug, quiet=quiet, source="mc")
    if ctx.invoked_subcommand is None:
        _show_quickstart()


def _show_quickstart():
    """Formatted quick-start guide."""
    from modules.clients.common.display import get_console

    console = get_console()
    console.print("""
[bold cyan]Mission Control[/bold cyan]

  [bold]Quick Start:[/bold]
    mc mission create --name my-app --description "My project"
    mc mission use my-app
    mc run "audit the auth module"

  [bold]Work:[/bold]
    mc run <objective|workflow>   Run a task or workflow
    mc chat                      Talk to your AI team
    mc design                    Design a workflow with the Architect
    mc status                    Current mission snapshot
    mc history [N]               Recent runs (detail for run #N)

  [bold]Setup:[/bold]
    mc mission list              List missions
    mc team list                 Your agent team
    mc context show              Mission Context Document

  [dim]Use mc <command> --help for details.[/dim]
""")


# =============================================================================
# Mission commands
# =============================================================================


@mc.group("mission", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def mission(ctx):
    """Manage missions."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@mission.command("create")
@click.option("--name", required=True, help="Mission name.")
@click.option("--description", required=True, help="Mission description.")
@click.option("--brief", default=None, help="Strategic brief for agents.")
@click.option("--gate", "gate_mode",
              type=click.Choice(["off", "interactive", "ai_assisted", "autonomous"]),
              default=None, help="Default gate mode.")
@click.option("--budget", type=float, default=None, help="Budget ceiling in USD.")
@click.pass_obj
def mission_create(ctx, name, description, brief, gate_mode, budget):
    """Create a new mission."""
    from modules.clients.cli.mission_cmds import run_mission

    run_mission(
        ctx.logger, "create",
        name=name, description=description, brief=brief,
        gate_mode=gate_mode, budget=budget,
    )


@mission.command("list")
@click.pass_obj
def mission_list(ctx):
    """List all missions."""
    from modules.clients.cli.mission_cmds import run_mission

    run_mission(ctx.logger, "list", output_format=ctx.output_format)


@mission.command("use")
@click.argument("name_or_id")
@click.pass_obj
def mission_use(ctx, name_or_id):
    """Set the active mission."""
    from modules.clients.cli.mission_cmds import run_mission

    run_mission(ctx.logger, "use", mission_id=name_or_id)


@mission.command("info")
@click.pass_obj
def mission_info(ctx):
    """Show current mission detail."""
    from modules.clients.cli.mission_cmds import _action_detail

    async def _run():
        mid = await _async_require_mission()
        await _action_detail(ctx.logger, mission_id=mid, name=None, output_format=ctx.output_format)

    asyncio.run(_run())


@mission.command("set-gate")
@click.argument("mode", type=click.Choice(["off", "interactive", "ai_assisted", "autonomous"]))
@click.pass_obj
def mission_set_gate(ctx, mode):
    """Set the default gate mode for the current mission."""
    from modules.clients.cli.mission_cmds import _action_set_gate

    async def _run():
        mid = await _async_require_mission()
        await _action_set_gate(ctx.logger, mission_id=mid, gate_mode=mode)

    asyncio.run(_run())


# =============================================================================
# Run command
# =============================================================================


@mc.command()
@click.argument("objective_or_workflow")
@click.option("--budget", type=float, default=None, help="Cost ceiling override.")
@click.option("--gate", "gate_override",
              type=click.Choice(["off", "interactive", "ai_assisted", "autonomous"]),
              default=None, help="Gate mode override.")
@click.option("--step", is_flag=True, help="Alias for --gate interactive.")
@click.option("--set", "overrides", multiple=True, help="key=value context override.")
@click.option("--dry-run", is_flag=True, help="Show plan + estimated cost, don't execute.")
@click.pass_obj
def run(ctx, objective_or_workflow, budget, gate_override, step, overrides, dry_run):
    """Run a task or workflow against the current mission."""
    if step:
        gate_override = "interactive"
    context_overrides = dict(kv.split("=", 1) for kv in overrides)
    from modules.clients.cli.mc_run import run as mc_run

    async def _run():
        mid = await _async_require_mission()
        await mc_run(
            objective_or_workflow,
            mission_id=mid,
            budget=budget,
            gate_override=gate_override,
            context_overrides=context_overrides,
            dry_run=dry_run,
            quiet=ctx.quiet,
            verbose=ctx.verbose,
        )

    asyncio.run(_run())


# =============================================================================
# Retry command
# =============================================================================


@mc.command()
@click.argument("n", type=int)
@click.option("--gate", "gate_override",
              type=click.Choice(["off", "interactive", "ai_assisted", "autonomous"]),
              default=None, help="Gate mode override.")
@click.pass_obj
def retry(ctx, n, gate_override):
    """Re-run the Nth most recent execution."""
    from modules.clients.cli.mc_run import retry as mc_retry

    async def _run():
        mid = await _async_require_mission()
        await mc_retry(
            n, mission_id=mid, gate_override=gate_override,
            quiet=ctx.quiet, verbose=ctx.verbose,
        )

    asyncio.run(_run())


# =============================================================================
# Status + History
# =============================================================================


@mc.command()
@click.pass_obj
def status(ctx):
    """Current mission snapshot."""
    from modules.clients.cli.mc_status import show_status

    async def _run():
        mid = await _async_require_mission()
        await show_status(mid, verbose=ctx.verbose)

    asyncio.run(_run())


@mc.command()
@click.argument("n", type=int, required=False, default=None)
@click.pass_obj
def history(ctx, n):
    """Recent runs. Pass N for detail on that run."""
    from modules.clients.cli.mc_status import show_history

    async def _run():
        mid = await _async_require_mission()
        await show_history(n, mission_id=mid, verbose=ctx.verbose)

    asyncio.run(_run())


@mission.command("archive")
@click.pass_obj
def mission_archive(ctx):
    """Archive the current mission."""
    from modules.backend.services.mission import MissionService

    async def _run():
        mid = await _async_require_mission()
        async with MissionService.factory() as svc:
            mission = await svc.archive_mission(mid)
        click.echo(f"Archived: {mission.name}")

    asyncio.run(_run())


@mission.command("delete")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt.")
@click.pass_obj
def mission_delete(ctx, confirm):
    """Permanently delete the current mission and all its data."""
    if not confirm:
        click.confirm("This will permanently delete the mission and all its data. Continue?", abort=True)

    from modules.backend.services.mission import MissionService

    async def _run():
        mid = await _async_require_mission()
        async with MissionService.factory() as svc:
            name = await svc.delete_mission(mid)
        click.echo(f"Deleted: {name}")

    asyncio.run(_run())


@mission.command("unarchive")
@click.argument("name_or_id")
@click.pass_obj
def mission_unarchive(ctx, name_or_id):
    """Restore an archived mission to active status."""
    from modules.backend.services.mission import MissionService

    async def _run():
        async with MissionService.factory() as svc:
            mission = await svc.get_mission_by_name(name_or_id)
            if not mission:
                mission = await svc.get_mission(name_or_id)
            await svc.unarchive_mission(str(mission.id))
        click.echo(f"Unarchived: {mission.name}")

    asyncio.run(_run())


# =============================================================================
# Chat + Design
# =============================================================================


@mc.command()
@click.argument("message", required=False)
@click.option("--agent", "-a", "agent_name", default=None,
              help="Target a specific agent (default: mission director).")
@click.option("--new", "new_thread", is_flag=True,
              help="Start a new conversation thread instead of resuming.")
@click.pass_obj
def chat(ctx, message, agent_name, new_thread):
    """Talk to your AI team. Interactive REPL or single-shot.

    Resumes the most recent conversation by default. Use --new to
    start a fresh thread. The web frontend and CLI share the same
    threads — both see the same conversation history.
    """
    from modules.clients.cli.mc_chat import chat_repl

    async def _run():
        mid = await _async_require_mission()
        await chat_repl(
            agent_name=agent_name, initial_message=message,
            mission_id=mid, verbose=ctx.verbose,
            new_thread=new_thread,
        )

    asyncio.run(_run())


@mc.command()
@click.argument("description", required=False)
@click.pass_obj
def design(ctx, description):
    """Design a workflow with the Architect."""
    from modules.clients.cli.mc_chat import design_repl

    async def _run():
        mid = await _async_require_mission()
        await design_repl(description=description, mission_id=mid, verbose=ctx.verbose)

    asyncio.run(_run())


# =============================================================================
# Team commands
# =============================================================================


@mc.group("team", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def team(ctx):
    """Manage your agent team."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@team.command("list")
@click.pass_obj
def team_list(ctx):
    """List agents on the current mission's roster."""
    from modules.clients.cli.mc_team import list_team

    async def _run():
        mid = await _async_require_mission()
        await list_team(mid)

    asyncio.run(_run())


@team.command("available")
@click.option("--search", "-s", default=None, help="Search query.")
@click.pass_obj
def team_available(ctx, search):
    """Browse the global agent catalog."""
    from modules.clients.cli.mc_team import list_available

    asyncio.run(list_available(search))


@team.command("add")
@click.argument("agent")
@click.pass_obj
def team_add(ctx, agent):
    """Add an agent to the current mission."""
    from modules.clients.cli.mc_team import add_agent

    async def _run():
        mid = await _async_require_mission()
        await add_agent(mid, agent)

    asyncio.run(_run())


@team.command("remove")
@click.argument("agent")
@click.pass_obj
def team_remove(ctx, agent):
    """Remove an agent from the current mission."""
    from modules.clients.cli.mc_team import remove_agent

    async def _run():
        mid = await _async_require_mission()
        await remove_agent(mid, agent)

    asyncio.run(_run())


# =============================================================================
# Context commands
# =============================================================================


@mc.group("context", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def context(ctx):
    """View mission context."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@context.command("show")
@click.pass_obj
def context_show(ctx):
    """View the Mission Context Document."""
    from modules.clients.cli.mission_cmds import _action_context_show

    async def _run():
        mid = await _async_require_mission()
        await _action_context_show(ctx.logger, mission_id=mid, output_format=ctx.output_format)

    asyncio.run(_run())


@context.command("history")
@click.pass_obj
def context_history(ctx):
    """MCD change audit trail."""
    from modules.clients.cli.mission_cmds import _action_context_history

    async def _run():
        mid = await _async_require_mission()
        await _action_context_history(ctx.logger, mission_id=mid, output_format=ctx.output_format)

    asyncio.run(_run())


# =============================================================================
# Console monitor (reuse)
# =============================================================================


@mc.group("console", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def console(ctx):
    """Console monitor."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@console.command("monitor")
@click.option("--view", type=click.Choice(["user", "developer"]), default="user")
@click.option("--refresh", type=float, default=2.0)
@click.pass_obj
def console_monitor(ctx, view, refresh):
    """Live terminal dashboard."""
    from modules.clients.cli.console_cmds import run_monitor

    run_monitor(ctx.logger, view=view, refresh_rate=refresh)


# =============================================================================
# Intent commands (Plan 57)
# =============================================================================


@mc.group("intent", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def intent(ctx):
    """View and manage mission intent."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@intent.command("show")
@click.pass_obj
def intent_show(ctx):
    """Show the current mission intent."""

    async def _run():
        mid = await _async_require_mission()
        from modules.clients.common.display import get_console
        from modules.clients.common.knowledge_rendering import render_intent
        from modules.backend.services.knowledge import KnowledgeService

        async with KnowledgeService.factory() as svc:
            data = await svc.get_current_intent(mid)

        console_obj = get_console()
        if data:
            console_obj.print(render_intent(data))
        else:
            console_obj.print("[dim]No intent set for this mission.[/dim]")

    asyncio.run(_run())


@intent.command("history")
@click.option("--limit", "-n", default=20, help="Max revisions to show")
@click.pass_obj
def intent_history(ctx, limit):
    """Show intent revision timeline."""

    async def _run():
        mid = await _async_require_mission()
        from modules.clients.common.display import get_console
        from modules.clients.common.knowledge_rendering import render_intent_history
        from modules.backend.services.mission_intent import MissionIntentService

        async with MissionIntentService.factory() as svc:
            revisions = await svc.list_revisions(mid, limit=limit)

        console_obj = get_console()
        if revisions:
            data = [
                {
                    "intent_summary": r.intent_summary,
                    "source": r.source,
                    "reason": r.reason,
                    "created_at": str(r.created_at),
                }
                for r in revisions
            ]
            console_obj.print(render_intent_history(data))
        else:
            console_obj.print("[dim]No intent revisions yet.[/dim]")

    asyncio.run(_run())


@intent.command("set")
@click.argument("intent_text")
@click.option("--reason", "-r", default="User-set via CLI", help="Reason for change")
@click.pass_obj
def intent_set(ctx, intent_text, reason):
    """Set a new mission intent."""

    async def _run():
        mid = await _async_require_mission()
        from modules.clients.common.display import get_console
        from modules.backend.services.mission_intent import MissionIntentService

        async with MissionIntentService.factory() as svc:
            result = await svc.create_intent(
                mid, intent_text, source="user_cli", reason=reason,
            )

        console_obj = get_console()
        if result:
            console_obj.print(f"[green]Intent updated:[/green] {result.intent_summary}")
        else:
            console_obj.print("[dim]Intent unchanged (identical to current).[/dim]")

    asyncio.run(_run())


# =============================================================================
# Learnings commands (Plan 57)
# =============================================================================


@mc.group("learnings", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def learnings(ctx):
    """View mission learnings."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@learnings.command("list")
@click.option("--kind", "-k", default=None, help="Filter by kind")
@click.option("--domain", "-d", default=None, help="Filter by domain tag")
@click.pass_obj
def learnings_list(ctx, kind, domain):
    """List learnings for the current mission."""

    async def _run():
        mid = await _async_require_mission()
        from modules.clients.common.display import get_console
        from modules.clients.common.knowledge_rendering import render_learning_list
        from modules.backend.services.mission_learning import MissionLearningService

        tags = [domain] if domain else None
        async with MissionLearningService.factory() as svc:
            items = await svc.list_by_mission(mid, kind=kind, domain_tags=tags)

        console_obj = get_console()
        if items:
            data = [
                {
                    "kind": l.kind,
                    "title": l.title,
                    "confidence": l.confidence,
                    "occurrence_count": l.occurrence_count,
                    "domain_tags": l.domain_tags,
                    "platform_promoted": l.platform_promoted,
                    "status": l.status,
                }
                for l in items
            ]
            console_obj.print(render_learning_list(data))
        else:
            console_obj.print("[dim]No learnings extracted yet.[/dim]")

    asyncio.run(_run())


@learnings.command("show")
@click.argument("learning_id")
@click.pass_obj
def learnings_show(ctx, learning_id):
    """Show a specific learning in detail."""

    async def _run():
        from modules.clients.common.display import get_console
        from modules.clients.common.knowledge_rendering import render_learning_card
        from modules.backend.repositories.mission_learning import MissionLearningRepository
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            repo = MissionLearningRepository(db)
            learning = await repo.get_by_id(learning_id)

        console_obj = get_console()
        console_obj.print(render_learning_card({
            "kind": learning.kind,
            "title": learning.title,
            "body": learning.body,
            "recommendation": learning.recommendation,
            "confidence": learning.confidence,
            "occurrence_count": learning.occurrence_count,
            "domain_tags": learning.domain_tags,
            "agent_names": learning.agent_names,
            "platform_promoted": learning.platform_promoted,
            "created_at": str(learning.created_at),
        }))

    asyncio.run(_run())


# =============================================================================
# Knowledge platform commands (Plan 57 — sysadmin)
# =============================================================================


@mc.group("knowledge", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def knowledge(ctx):
    """Platform knowledge (sysadmin)."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@knowledge.command("search")
@click.argument("query")
@click.option("--tags", "-t", default=None, help="Comma-separated domain tags")
@click.option("--kinds", "-k", default=None, help="Comma-separated kinds")
@click.option("--mode", "-m", default="hybrid", type=click.Choice(["structured", "hybrid", "semantic"]))
@click.option("--mission", default=None, help="Mission ID (uses current if omitted)")
@click.option("--platform-only", is_flag=True, help="Only platform-promoted entries")
@click.pass_obj
def knowledge_search(ctx, query, tags, kinds, mode, mission, platform_only):
    """Search the knowledge platform."""

    async def _run():
        from modules.clients.common.display import get_console
        from modules.clients.common.knowledge_rendering import render_knowledge_search_results
        from modules.backend.services.knowledge import KnowledgeService

        # Use current mission if not specified
        mid = mission
        if not mid and not platform_only:
            try:
                mid = await _async_require_mission()
            except SystemExit:
                mid = None

        tag_list = [t.strip() for t in tags.split(",")] if tags else None
        kind_list = [k.strip() for k in kinds.split(",")] if kinds else None

        async with KnowledgeService.factory() as svc:
            entries = await svc.search(
                query, mission_id=mid, platform_only=platform_only,
                domain_tags=tag_list, kinds=kind_list, mode=mode,
            )

        console_obj = get_console()
        if entries:
            data = [
                {
                    "kind": e.kind,
                    "title": e.title,
                    "domain_tags": e.domain_tags,
                    "confidence": e.confidence,
                    "distance": e.distance,
                }
                for e in entries
            ]
            console_obj.print(render_knowledge_search_results(data))
        else:
            console_obj.print("[dim]No matching knowledge entries found.[/dim]")

    asyncio.run(_run())


# =============================================================================
# Tree command
# =============================================================================


@mc.command()
def tree():
    """Show all commands in a tree structure."""
    from rich.tree import Tree

    console_obj = None
    try:
        from modules.clients.common.display import get_console
        console_obj = get_console()
    except Exception:
        from rich.console import Console
        console_obj = Console()

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

    root = Tree("[bold cyan]mc[/bold cyan]  [dim]Mission Control — user CLI[/dim]")
    _build(mc, root)
    console_obj.print(root)


# =============================================================================
# Entry point
# =============================================================================


if __name__ == "__main__":
    mc()
