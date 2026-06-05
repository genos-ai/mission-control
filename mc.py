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

from modules.clients.cli.api_client import (
    CliApiClient,
    api_client,
    require_mission,
    setup_cli_logging,
)


# =============================================================================
# Click utilities (no backend imports)
# =============================================================================


class ShowHelpOnMissingArgs(click.Group):
    """Show full help instead of terse error when required args are missing."""

    def resolve_command(self, ctx, args):
        cmd_name, cmd, remaining = super().resolve_command(ctx, args)
        if cmd is not None and not isinstance(cmd, click.Group):
            required_args = [
                p for p in cmd.params
                if isinstance(p, click.Argument) and p.required
            ]
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
            click.echo(click.style(
                f"Logged in as {user.get('email', _email)}", fg="green",
            ))

    asyncio.run(_run())


@mc.command()
def logout():
    """Clear stored authentication."""
    async def _run():
        async with api_client() as api:
            await api.logout()
        click.echo("Logged out.")

    asyncio.run(_run())


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
              type=click.Choice(["interactive", "manual", "ai_assisted", "autonomous"]),
              default=None, help="Default gate mode.")
@click.option("--budget", type=float, default=None, help="Budget ceiling in USD.")
def mission_create(name, description, brief, gate_mode, budget):
    """Create a new mission."""
    from modules.clients.cli.mc_mission import create

    async def _run():
        async with api_client() as api:
            await create(api, name=name, description=description,
                         brief=brief, gate_mode=gate_mode, budget=budget)

    asyncio.run(_run())


@mission.command("list")
def mission_list():
    """List all missions."""
    from modules.clients.cli.mc_mission import list_missions

    async def _run():
        async with api_client() as api:
            await list_missions(api)

    asyncio.run(_run())


@mission.command("use")
@click.option("--name", "name_or_id", required=True, help="Mission name or ID.")
def mission_use(name_or_id):
    """Set the active mission."""
    from modules.clients.cli.mc_mission import use

    async def _run():
        async with api_client() as api:
            await use(api, name_or_id)

    asyncio.run(_run())


@mission.command("info")
@click.pass_obj
def mission_info(ctx):
    """Show current mission detail."""
    from modules.clients.cli.mc_mission import info

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await info(api, mid)

    asyncio.run(_run())


@mission.command("set-gate")
@click.option("--mode", required=True,
              type=click.Choice(["interactive", "manual", "ai_assisted", "autonomous"]),
              help="Gate mode.")
@click.pass_obj
def mission_set_gate(ctx, mode):
    """Set the default gate mode for the current mission."""
    from modules.clients.cli.mc_mission import set_gate

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await set_gate(api, mid, mode)

    asyncio.run(_run())


@mission.command("set-budget")
@click.argument("amount", type=float)
@click.pass_obj
def mission_set_budget(ctx, amount):
    """Set the budget ceiling for the current mission."""
    from modules.clients.cli.mc_mission import set_budget

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await set_budget(api, mid, amount)

    asyncio.run(_run())


@mission.command("archive")
@click.pass_obj
def mission_archive(ctx):
    """Archive the current mission."""
    from modules.clients.cli.mc_mission import archive

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await archive(api, mid)

    asyncio.run(_run())


@mission.command("delete")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt.")
@click.pass_obj
def mission_delete(ctx, confirm):
    """Permanently delete the current mission and all its data."""
    if not confirm:
        click.confirm(
            "This will permanently delete the mission and all its data. Continue?",
            abort=True,
        )

    from modules.clients.cli.mc_mission import delete

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await delete(api, mid)

    asyncio.run(_run())


@mission.command("unarchive")
@click.option("--name", "name_or_id", required=True, help="Mission name or ID.")
def mission_unarchive(name_or_id):
    """Restore an archived mission to active status."""
    from modules.clients.cli.mc_mission import unarchive

    async def _run():
        async with api_client() as api:
            await unarchive(api, name_or_id)

    asyncio.run(_run())


# =============================================================================
# Run command
# =============================================================================


@mc.command()
@click.option("--objective", "-o", required=True, help="Objective text or workflow name.")
@click.option("--budget", type=float, default=None, help="Cost ceiling override.")
@click.option("--gate", "gate_override",
              type=click.Choice(["interactive", "manual", "ai_assisted", "autonomous"]),
              default=None, help="Gate mode override.")
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
            click.echo(click.style(f"Invalid --context: '{item}' (expected key=value)", fg="red"), err=True)
            raise SystemExit(1)
        key, value = item.split("=", 1)
        context_overrides[key] = value

    from modules.clients.cli.mc_run import run as mc_run

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await mc_run(
                api, objective,
                mission_id=mid, budget=budget,
                gate_override=gate_override,
                dry_run=dry_run,
                quiet=ctx.quiet, verbose=ctx.verbose,
                context_overrides=context_overrides or None,
            )

    asyncio.run(_run())


# =============================================================================
# Runs — workflow-run lifecycle (list / show / cancel)
# =============================================================================


@mc.group("runs", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def runs(ctx):
    """Manage existing workflow runs (list active, show detail, cancel)."""
    if ctx.invoked_subcommand is None:
        from modules.clients.cli.mc_runs import list_runs

        async def _run():
            async with api_client() as api:
                mid = await require_mission(api)
                await list_runs(api, mission_id=mid, include_terminal=False)

        asyncio.run(_run())


@runs.command("list")
@click.option("--all", "include_terminal", is_flag=True,
              help="Include completed / failed / cancelled runs (default: active only).")
@click.pass_obj
def runs_list(ctx, include_terminal):
    """List workflow runs for the current mission (active by default)."""
    from modules.clients.cli.mc_runs import list_runs

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await list_runs(api, mission_id=mid, include_terminal=include_terminal)

    asyncio.run(_run())


@runs.command("show")
@click.argument("run_id")
@click.pass_obj
def runs_show(ctx, run_id):
    """Show full detail for one workflow run."""
    from modules.clients.cli.mc_runs import show_run

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await show_run(api, mission_id=mid, run_id=run_id)

    asyncio.run(_run())


@runs.command("cancel")
@click.argument("run_id")
@click.pass_obj
def runs_cancel(ctx, run_id):
    """Mark a workflow run as CANCELLED (useful for stale RUNNING orphans)."""
    from modules.clients.cli.mc_runs import cancel_run

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await cancel_run(api, mission_id=mid, run_id=run_id)

    asyncio.run(_run())


# =============================================================================
# Retry command
# =============================================================================


@mc.command()
@click.option("--run", "n", type=int, required=True, help="Nth most recent execution to retry.")
@click.option("--gate", "gate_override",
              type=click.Choice(["interactive", "manual", "ai_assisted", "autonomous"]),
              default=None, help="Gate mode override.")
@click.pass_obj
def retry(ctx, n, gate_override):
    """Retry failed plan tasks, or re-run a past execution."""
    from modules.clients.cli.mc_run import retry as mc_retry

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await mc_retry(
                api, n, mission_id=mid, gate_override=gate_override,
                quiet=ctx.quiet, verbose=ctx.verbose,
            )

    asyncio.run(_run())


# =============================================================================
# Plan — fine-grained per-task control
# =============================================================================


@mc.group("plan", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def plan(ctx):
    """Per-task plan control (approve / reject / retry / dispatch one at a time)."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@plan.command("show")
@click.option("--status", "status_filter",
              type=click.Choice(["proposed", "approved", "queued", "running",
                                 "completed", "failed", "skipped", "cancelled"]),
              default=None, help="Only show tasks with this status.")
@click.option("--deps", "show_deps", is_flag=True, help="Include dependency column.")
@click.pass_obj
def plan_show(ctx, status_filter, show_deps):
    """Print the plan: every task with status, agent, cost, description."""
    from modules.clients.cli.mc_plan import show as plan_show_fn

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await plan_show_fn(api, mission_id=mid,
                               status_filter=status_filter, show_deps=show_deps)

    asyncio.run(_run())


@plan.command("task")
@click.argument("task_id")
@click.pass_obj
def plan_task(ctx, task_id):
    """Show full detail for one task (status, instructions, deps, failure reason)."""
    from modules.clients.cli.mc_plan import task_detail

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await task_detail(api, mission_id=mid, task_id=task_id)

    asyncio.run(_run())


@plan.command("approve")
@click.argument("task_id", required=False)
@click.option("--next", "pick_next", is_flag=True,
              help="Pick the topologically next PROPOSED task whose deps are all COMPLETED.")
@click.pass_obj
def plan_approve(ctx, task_id, pick_next):
    """Approve one task (also approves PROPOSED transitive dependencies)."""
    from modules.clients.cli.mc_plan import approve as plan_approve_fn

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await plan_approve_fn(api, mission_id=mid, task_id=task_id, pick_next=pick_next)

    asyncio.run(_run())


@plan.command("reject")
@click.argument("task_id", required=False)
@click.option("--all", "reject_all", is_flag=True,
              help="Cancel ALL non-terminal tasks in the plan.")
@click.pass_obj
def plan_reject(ctx, task_id, reject_all):
    """Reject one task (also cancels transitive dependents); --all cancels everything non-terminal."""
    from modules.clients.cli.mc_plan import reject as plan_reject_fn

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await plan_reject_fn(api, mission_id=mid, task_id=task_id, reject_all=reject_all)

    asyncio.run(_run())


@plan.command("retry")
@click.argument("task_id")
@click.pass_obj
def plan_retry(ctx, task_id):
    """Retry one FAILED task (bulk variant: `mc retry`)."""
    from modules.clients.cli.mc_plan import retry_one as plan_retry_fn

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await plan_retry_fn(api, mission_id=mid, task_id=task_id)

    asyncio.run(_run())


@plan.command("dispatch")
@click.pass_obj
def plan_dispatch(ctx):
    """Dispatch all currently APPROVED tasks via Temporal."""
    from modules.clients.cli.mc_plan import dispatch as plan_dispatch_fn

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await plan_dispatch_fn(api, mission_id=mid)

    asyncio.run(_run())


# =============================================================================
# Gate — manual approval over the HTTP API
# =============================================================================


@mc.group("gate", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def gate(ctx):
    """Gate configuration + post-execution decisions.

    Pre-execution approval is via `mc plan approve` (the task lifecycle).
    `mc gate` is for setting the gate mode and deciding the rare
    post-execution gates (post_task, verification_failed, post_run, ...).
    """
    if ctx.invoked_subcommand is None:
        # Default: show current mode + any pending gates.
        from modules.clients.cli.mc_gate import show as gate_show_fn

        async def _run():
            async with api_client() as api:
                mid = await require_mission(api)
                await gate_show_fn(api, mission_id=mid)

        asyncio.run(_run())


@gate.command("show")
@click.pass_obj
def gate_show(ctx):
    """Show the current gate mode and any pending post-execution gates."""
    from modules.clients.cli.mc_gate import show as gate_show_fn

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await gate_show_fn(api, mission_id=mid)

    asyncio.run(_run())


@gate.command("set")
@click.argument("mode",
    type=click.Choice(["autonomous", "manual", "interactive", "ai_assisted"]))
@click.pass_obj
def gate_set(ctx, mode):
    """Set the gate mode for the current mission's plan."""
    from modules.clients.cli.mc_gate import set_mode

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await set_mode(api, mission_id=mid, mode=mode)

    asyncio.run(_run())


@gate.command("modes")
@click.pass_obj
def gate_modes(ctx):
    """List the four supported gate modes with descriptions."""
    from modules.clients.cli.mc_gate import list_modes

    async def _run():
        async with api_client() as api:
            await list_modes(api)

    asyncio.run(_run())


@gate.command("pending")
@click.pass_obj
def gate_pending(ctx):
    """List pending post-execution gates (rare)."""
    from modules.clients.cli.mc_gate import pending

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await pending(api, mission_id=mid)

    asyncio.run(_run())


@gate.command("decide")
@click.argument("gate_id")
@click.argument("action")
@click.option("--reason", default=None, help="Optional note attached to the decision.")
@click.pass_obj
def gate_decide(ctx, gate_id, action, reason):
    """Decide a pending post-execution gate.

    Valid actions depend on the gate type:
      post_task / verification_failed:  continue | skip | retry | abort
      post_layer:                       continue | abort
      post_run:                         wait | advance_approved |
                                        advance_refine | propose_complete |
                                        escalate
    """
    from modules.clients.cli.mc_gate import decide

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await decide(api, mission_id=mid, gate_id=gate_id,
                         action=action, reason=reason)

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
        async with api_client() as api:
            mid = await require_mission(api)
            await show_status(api, mid, verbose=ctx.verbose)

    asyncio.run(_run())


@mc.command()
@click.option("--run", "n", type=int, default=None, help="Show detail for run #N.")
@click.pass_obj
def history(ctx, n):
    """Recent runs. Use --run N for detail on that run."""
    from modules.clients.cli.mc_status import show_history

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await show_history(api, n, mission_id=mid, verbose=ctx.verbose)

    asyncio.run(_run())


@mc.group()
@click.pass_context
def artifacts(ctx):
    """View mission artifacts."""
    pass


@artifacts.command("list")
@click.pass_obj
def artifacts_list(ctx):
    """List all artifacts for the current mission."""
    from modules.clients.cli.mc_mission import list_artifacts

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await list_artifacts(api, mid)

    asyncio.run(_run())


@artifacts.command("show")
@click.argument("num", type=int)
@click.pass_obj
def artifacts_show(ctx, num):
    """Show artifact #N (from artifacts list)."""
    from modules.clients.cli.mc_mission import show_artifact

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await show_artifact(api, mid, num)

    asyncio.run(_run())


@mc.group()
@click.pass_context
def report(ctx):
    """View research reports."""
    pass


@report.command("list")
@click.pass_obj
def report_list(ctx):
    """List completed runs with reports."""
    from modules.clients.cli.mc_mission import list_reports

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await list_reports(api, mid)

    asyncio.run(_run())


@report.command("show")
@click.option("--run", "n", type=int, default=None, help="Show report from run #N (default: latest).")
@click.pass_obj
def report_show(ctx, n):
    """View the research report from a completed run."""
    from modules.clients.cli.mc_mission import show_report

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await show_report(api, mid, n)

    asyncio.run(_run())


@mc.command()
@click.argument("workflow_id")
@click.option("--verbose", "-v", is_flag=True, help="Show all event types.")
@click.option("--detail", "-d", is_flag=True, help="Show research phase breakdown from mission events.")
@click.option("--mission", "-m", default=None, help="Mission ID for --detail (auto-detected if set via mc mission use).")
@click.pass_obj
def trace(ctx, workflow_id, verbose, detail, mission):
    """Trace a Temporal workflow execution — shows activity timeline.

    \b
    Examples:
        mc trace mission-run-f32ffb36-1d4-abe596f7
        mc trace mission-run-f32ffb36-1d4-abe596f7 -d
        mc trace mission-run-f32ffb36-1d4-abe596f7 -d -m <mission-id>
    """
    from modules.clients.cli.mc_trace import trace_workflow

    async def _run():
        mid = mission
        if detail and not mid:
            async with api_client() as api:
                mid = await require_mission(api)
        await trace_workflow(workflow_id, verbose=verbose, detail=detail, mission_id=mid)

    asyncio.run(_run())


# =============================================================================
# Chat + Design
# =============================================================================


@mc.command()
@click.option("--message", "-m", default=None, help="Single-shot message (skips REPL).")
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
        async with api_client() as api:
            mid = await require_mission(api)
            await chat_repl(
                api, agent_name=agent_name, initial_message=message,
                mission_id=mid, verbose=ctx.verbose,
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
            await design_repl(api, description=description,
                              mission_id=mid, verbose=ctx.verbose)

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
        async with api_client() as api:
            mid = await require_mission(api)
            await list_team(api, mid)

    asyncio.run(_run())


@team.command("ping")
@click.pass_obj
def team_ping(ctx):
    """Ping every agent on the current mission's team with a trivial LLM call.

    Probes each agent's catalog row → builds the model → sends "Reply with OK"
    in parallel (bounded). Reports per-agent latency, tokens, cost, and status.
    Health check for the full provider/auth/model chain.
    """
    from modules.clients.cli.mc_team import ping_team

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await ping_team(api, mid)

    asyncio.run(_run())


@team.command("available")
@click.option("--search", "-s", default=None, help="Search query.")
def team_available(search):
    """Browse the global agent catalog."""
    from modules.clients.cli.mc_team import list_available

    async def _run():
        async with api_client() as api:
            await list_available(api, search)

    asyncio.run(_run())


@team.command("add")
@click.option("--agent", required=True, help="Agent name to add.")
@click.pass_obj
def team_add(ctx, agent):
    """Add an agent to the current mission."""
    from modules.clients.cli.mc_team import add_agent

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await add_agent(api, mid, agent)

    asyncio.run(_run())


@team.command("remove")
@click.option("--agent", required=True, help="Agent name to remove.")
@click.pass_obj
def team_remove(ctx, agent):
    """Remove an agent from the current mission."""
    from modules.clients.cli.mc_team import remove_agent

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await remove_agent(api, mid, agent)

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
    from modules.clients.cli.mc_mission import context_show as _show

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await _show(api, mid)

    asyncio.run(_run())


@context.command("history")
@click.pass_obj
def context_history(ctx):
    """MCD change audit trail."""
    from modules.clients.cli.mc_mission import context_history as _history

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await _history(api, mid)

    asyncio.run(_run())


# =============================================================================
# Intent commands
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
    from modules.clients.cli.mc_knowledge import intent_show as _show

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await _show(api, mid)

    asyncio.run(_run())


@intent.command("history")
@click.option("--limit", "-n", default=20, help="Max revisions to show")
@click.pass_obj
def intent_history(ctx, limit):
    """Show intent revision timeline."""
    from modules.clients.cli.mc_knowledge import intent_history as _history

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await _history(api, mid, limit=limit)

    asyncio.run(_run())


@intent.command("set")
@click.option("--text", required=True, help="Intent text.")
@click.option("--reason", "-r", default="User-set via CLI", help="Reason for change")
@click.pass_obj
def intent_set(ctx, text, reason):
    """Set a new mission intent."""
    from modules.clients.cli.mc_knowledge import intent_set as _set

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await _set(api, mid, text, reason=reason)

    asyncio.run(_run())


# =============================================================================
# Learnings commands
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
    from modules.clients.cli.mc_knowledge import learnings_list as _list

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await _list(api, mid, kind=kind, domain=domain)

    asyncio.run(_run())


@learnings.command("show")
@click.option("--id", "learning_id", required=True, help="Learning ID.")
@click.pass_obj
def learnings_show(ctx, learning_id):
    """Show a specific learning in detail."""
    from modules.clients.cli.mc_knowledge import learnings_show as _show

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await _show(api, mid, learning_id)

    asyncio.run(_run())


# =============================================================================
# Knowledge platform commands
# =============================================================================


@mc.group("knowledge", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def knowledge(ctx):
    """Platform knowledge."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@knowledge.command("search")
@click.option("--query", "-q", required=True, help="Search query.")
@click.option("--tags", "-t", default=None, help="Comma-separated domain tags")
@click.option("--kinds", "-k", default=None, help="Comma-separated kinds")
@click.option("--mode", default="hybrid",
              type=click.Choice(["structured", "hybrid", "semantic"]))
@click.option("--mission", default=None, help="Mission ID (uses current if omitted)")
@click.option("--platform-only", is_flag=True, help="Only platform-promoted entries")
@click.pass_obj
def knowledge_search(ctx, query, tags, kinds, mode, mission, platform_only):
    """Search the knowledge platform."""
    from modules.clients.cli.mc_knowledge import knowledge_search as _search

    async def _run():
        async with api_client() as api:
            mid = mission
            if not mid and not platform_only:
                try:
                    mid = await require_mission(api)
                except SystemExit:
                    mid = None
            await _search(
                api, query, mission_id=mid,
                tags=tags, kinds=kinds, mode=mode,
                platform_only=platform_only,
            )

    asyncio.run(_run())


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


# =============================================================================
# Console monitor
# =============================================================================


@mc.group("console", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def console(ctx):
    """Live mission console monitor."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@console.command("monitor")
@click.option("--view", type=click.Choice(["user", "developer"]), default="user",
              help="Display mode: user (default) or developer.")
@click.option("--refresh", default=2.0, type=float, help="Refresh interval in seconds.")
@click.pass_obj
def console_monitor(ctx, view, refresh):
    """Live-updating event stream for the current mission."""
    from modules.clients.cli.mc_console import monitor

    async def _run():
        async with api_client() as api:
            mid = await require_mission(api)
            await monitor(api, mid, view=view, refresh=refresh)

    asyncio.run(_run())


# =============================================================================
# Entry point
# =============================================================================


if __name__ == "__main__":
    mc()
