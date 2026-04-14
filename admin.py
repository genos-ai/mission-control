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

from modules.clients.cli.cli_context import CliContext, ShowHelpOnMissingArgs

# Unified output format for all commands — single source of truth.
OUTPUT_FORMATS = click.Choice(["human", "json", "jsonl"])


@click.group(cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.option("--verbose", "-v", is_flag=True, help="Enable INFO-level logging.")
@click.option("--debug", "-d", is_flag=True, help="Enable DEBUG-level logging.")
@click.option("-o", "--output", "output_format", default="human",
              type=OUTPUT_FORMATS, help="Output format (human, json, jsonl).")
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


# =============================================================================
# Server (with lifecycle actions)
# =============================================================================


@admin_cli.group(cls=ShowHelpOnMissingArgs, invoke_without_command=True)
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


# =============================================================================
# Migrate
# =============================================================================


@admin_cli.group(cls=ShowHelpOnMissingArgs, invoke_without_command=True)
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


# =============================================================================
# Execution group
# =============================================================================


@admin_cli.group(cls=ShowHelpOnMissingArgs, invoke_without_command=True)
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
@click.option("--mission", "-m", "mission_id", default=None, help="Mission ID (uses current mission if not specified).")
@click.pass_obj
def execution_run(ctx, objective, roster, budget, triggered_by, mission_id):
    """Create and execute in one step."""
    from modules.clients.cli.execution_cmds import run_execution
    run_execution(ctx.logger, action="run", objective=objective, execution_id=None,
                  roster=roster, budget=budget, triggered_by=triggered_by,
                  output_format=ctx.output_format, mission_id=mission_id)


@execution.command("create")
@click.argument("objective")
@click.option("--roster", default="default", help="Agent roster to use.")
@click.option("--budget", default=None, type=float, help="Cost ceiling in USD.")
@click.option("--triggered-by", default="user:admin", help="Trigger origin.")
@click.option("--mission", "-m", "mission_id", default=None, help="Mission ID (uses current mission if not specified).")
@click.pass_obj
def execution_create(ctx, objective, roster, budget, triggered_by, mission_id):
    """Create an execution (PENDING state, not yet executed)."""
    from modules.clients.cli.execution_cmds import run_execution
    run_execution(ctx.logger, action="create", objective=objective, execution_id=None,
                  roster=roster, budget=budget, triggered_by=triggered_by,
                  output_format=ctx.output_format, mission_id=mission_id)


@execution.command("execute")
@click.argument("execution_id")
@click.option("--roster", default="default", help="Agent roster to use.")
@click.pass_obj
def execution_execute(ctx, execution_id, roster):
    """Execute an existing PENDING execution."""
    from modules.clients.cli.execution_cmds import run_execution
    run_execution(ctx.logger, action="execute", objective=None, execution_id=execution_id,
                  roster=roster, budget=None, triggered_by="user:admin",
                  output_format=ctx.output_format)


@execution.command("list")
@click.pass_obj
def execution_list(ctx):
    """List recent executions."""
    from modules.clients.cli.execution_cmds import run_execution
    run_execution(ctx.logger, action="list", objective=None, execution_id=None,
                  roster="default", budget=None, triggered_by="user:admin",
                  output_format=ctx.output_format)


@execution.command("detail")
@click.argument("execution_id")
@click.pass_obj
def execution_detail(ctx, execution_id):
    """Show execution detail with task results."""
    from modules.clients.cli.execution_cmds import run_execution
    run_execution(ctx.logger, action="detail", objective=None, execution_id=execution_id,
                  roster="default", budget=None, triggered_by="user:admin",
                  output_format=ctx.output_format)


@execution.command("plan")
@click.argument("execution_id")
@click.pass_obj
def execution_plan(ctx, execution_id):
    """Show the TaskPlan DAG for an execution."""
    from modules.clients.cli.execution_cmds import run_execution
    run_execution(ctx.logger, action="plan", objective=None, execution_id=execution_id,
                  roster="default", budget=None, triggered_by="user:admin",
                  output_format=ctx.output_format)


@execution.command("cost")
@click.argument("execution_id")
@click.pass_obj
def execution_cost(ctx, execution_id):
    """Show execution cost breakdown."""
    from modules.clients.cli.execution_cmds import run_execution
    run_execution(ctx.logger, action="cost", objective=None, execution_id=execution_id,
                  roster="default", budget=None, triggered_by="user:admin",
                  output_format=ctx.output_format)


# =============================================================================
# Workflow group
# =============================================================================


@admin_cli.group(cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def workflow(ctx):
    """List, run, and inspect workflows.

    \b
    Examples:
        python admin.py workflow list
        python admin.py workflow run ops.platform-audit --mission my-app
        python admin.py workflow detail ops.platform-audit
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@workflow.command("list")
@click.pass_obj
def workflow_list(ctx):
    """List available workflows."""
    from modules.clients.cli.workflow_cmds import run_workflow_cli
    run_workflow_cli(ctx.logger, action="list", workflow_name=None, run_id=None,
                     triggered_by="user:admin", output_format=ctx.output_format)


@workflow.command("detail")
@click.argument("name")
@click.pass_obj
def workflow_detail(ctx, name):
    """Show workflow configuration and steps."""
    from modules.clients.cli.workflow_cmds import run_workflow_cli
    run_workflow_cli(ctx.logger, action="detail", workflow_name=name, run_id=None,
                     triggered_by="user:admin", output_format=ctx.output_format)


@workflow.command("run")
@click.argument("name")
@click.option("--triggered-by", default="user:admin", help="Trigger origin.")
@click.option("--mission", required=True, help="Mission name to run against (created if new).")
@click.option(
    "--gate",
    type=click.Choice(["off", "interactive", "ai_assisted", "autonomous"], case_sensitive=False),
    default=None,
    help="Gate review mode. Overrides config/settings/gate.yaml.",
)
@click.option("--step", is_flag=True, help="Alias for --gate interactive.")
@click.pass_obj
def workflow_run(ctx, name, triggered_by, mission, gate, step):
    """Execute a workflow."""
    from modules.clients.cli.workflow_cmds import run_workflow_cli

    if step and gate is None:
        gate = "interactive"

    gate_obj = None
    if gate and gate != "off":
        from modules.backend.agents.mission_control.gate import create_gate
        gate_obj = create_gate(mode_override=gate)

    run_workflow_cli(ctx.logger, action="run", workflow_name=name, run_id=None,
                     triggered_by=triggered_by, output_format=ctx.output_format,
                     mission_name=mission, gate=gate_obj)


@workflow.command("runs")
@click.option("--name", default=None, help="Filter by workflow name.")
@click.pass_obj
def workflow_runs(ctx, name):
    """List workflow runs."""
    from modules.clients.cli.workflow_cmds import run_workflow_cli
    run_workflow_cli(ctx.logger, action="runs", workflow_name=name, run_id=None,
                     triggered_by="user:admin", output_format=ctx.output_format)


@workflow.command("run-detail")
@click.argument("run_id")
@click.pass_obj
def workflow_run_detail(ctx, run_id):
    """Show details for a specific workflow run."""
    from modules.clients.cli.workflow_cmds import run_workflow_cli
    run_workflow_cli(ctx.logger, action="run-detail", workflow_name=None,
                     run_id=run_id, triggered_by="user:admin", output_format=ctx.output_format)


@workflow.command("report")
@click.argument("run_id")
@click.pass_obj
def workflow_report(ctx, run_id):
    """Render a report for a past workflow run."""
    from modules.clients.cli.workflow_cmds import run_workflow_cli
    run_workflow_cli(ctx.logger, action="report", workflow_name=None,
                     run_id=run_id, triggered_by="user:admin", output_format=ctx.output_format)


# =============================================================================
# Mission group
# =============================================================================


@admin_cli.group("mission", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def mission(ctx):
    """Create, list, and manage missions.

    \b
    Examples:
        python admin.py mission create --name my-mission --description "My mission"
        python admin.py mission list
        python admin.py mission detail <id>
        python admin.py mission archive <id>
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@mission.command("create")
@click.option("--name", required=True, help="Unique mission name.")
@click.option("--description", required=True, help="Mission purpose.")
@click.option("--brief", default=None, help="Strategic directive for agents.")
@click.option("--roster", default="default", help="Default agent roster.")
@click.option("--budget", type=float, default=None, help="Budget ceiling (USD).")
@click.option("--repo-url", default=None, help="Repository URL.")
@click.option("--repo-root", default=None, help="Local repo root path.")
@click.option("--tier", default="user", type=click.Choice(["user", "platform"]), help="Mission tier.")
@click.pass_obj
def mission_create(ctx, name, description, brief, roster, budget, repo_url, repo_root, tier):
    """Create a new mission."""
    from modules.clients.cli.mission_cmds import run_mission
    run_mission(ctx.logger, "create", name=name, description=description,
                brief=brief, roster=roster, budget=budget, repo_url=repo_url,
                repo_root=repo_root, tier=tier, output_format=ctx.output_format)


@mission.command("list")
@click.pass_obj
def mission_list(ctx):
    """List all active missions."""
    from modules.clients.cli.mission_cmds import run_mission
    run_mission(ctx.logger, "list", output_format=ctx.output_format)


@mission.command("detail")
@click.argument("mission_id", required=False)
@click.option("--name", default=None, help="Look up by mission name.")
@click.pass_obj
def mission_detail(ctx, mission_id, name):
    """Show mission details.

    Uses current mission if MISSION_ID is omitted.
    """
    from modules.clients.cli.mission_cmds import run_mission
    run_mission(ctx.logger, "detail", mission_id=mission_id, name=name,
                output_format=ctx.output_format)


@mission.command("archive")
@click.argument("mission_id", required=False)
@click.pass_obj
def mission_archive(ctx, mission_id):
    """Archive a mission.

    Uses current mission if MISSION_ID is omitted.
    """
    from modules.clients.cli.mission_cmds import run_mission
    run_mission(ctx.logger, "archive", mission_id=mission_id,
                output_format=ctx.output_format)


@mission.command("delete")
@click.argument("mission_id", required=False)
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt.")
@click.pass_obj
def mission_delete(ctx, mission_id, confirm):
    """Permanently delete a mission and all related data.

    Cascades through all executions, records, workflows, team members.
    Also cleans up any Docker containers for this mission.

    Uses current mission if MISSION_ID is omitted.
    """
    if not confirm:
        click.confirm("This will permanently delete the mission and all its data. Continue?", abort=True)
    from modules.clients.cli.mission_cmds import run_mission
    run_mission(ctx.logger, "delete", mission_id=mission_id,
                output_format=ctx.output_format)


@mission.command("use")
@click.argument("mission_id")
@click.pass_obj
def mission_use(ctx, mission_id):
    """Set the current mission (persists across commands)."""
    from modules.clients.cli.mission_cmds import run_mission
    run_mission(ctx.logger, "use", mission_id=mission_id,
                output_format=ctx.output_format)


@mission.command("clear")
@click.pass_obj
def mission_clear(ctx):
    """Clear the current mission selection."""
    from modules.clients.cli.mission_cmds import run_mission
    run_mission(ctx.logger, "clear-mission", output_format=ctx.output_format)


@mission.group("context", cls=ShowHelpOnMissingArgs)
def mission_context():
    """View and manage the Mission Context Document (MCD)."""
    pass


@mission_context.command("show")
@click.argument("mission_id", required=False)
@click.pass_obj
def mission_context_show(ctx, mission_id):
    """Show the MCD for a mission.

    Uses current mission if MISSION_ID is omitted.
    """
    from modules.clients.cli.mission_cmds import run_mission
    run_mission(ctx.logger, "context-show", mission_id=mission_id,
                output_format=ctx.output_format)


@mission_context.command("history")
@click.argument("mission_id", required=False)
@click.pass_obj
def mission_context_history(ctx, mission_id):
    """Show MCD change audit trail.

    Uses current mission if MISSION_ID is omitted.
    """
    from modules.clients.cli.mission_cmds import run_mission
    run_mission(ctx.logger, "context-history", mission_id=mission_id,
                output_format=ctx.output_format)


@mission.command("summarize")
@click.argument("mission_id", required=False)
@click.pass_obj
def mission_summarize(ctx, mission_id):
    """Run the summarization pipeline for a mission.

    Uses current mission if MISSION_ID is omitted.
    """
    from modules.clients.cli.mission_cmds import run_mission
    run_mission(ctx.logger, "summarize", mission_id=mission_id,
                output_format=ctx.output_format)


# =============================================================================
# Context group — inspect what agents see
# =============================================================================


@admin_cli.group("context", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def context(ctx):
    """Inspect agent context: Code Map, PQI scores, dependencies.

    \b
    Examples:
        python admin.py context show
        python admin.py context show --mission <id>
        python admin.py context assembled --mission <id>
        python admin.py context codemap
        python admin.py context codemap --generate
        python admin.py context pqi
        python admin.py context deps
    """
    if ctx.invoked_subcommand is None:
        # Default to "show" when no subcommand given
        ctx.invoke(context_show)


@context.command("show")
@click.option("--mission", "mission_id", default=None, help="Mission ID for full assembled context.")
@click.pass_obj
def context_show(ctx, mission_id):
    """Show all context layers and token costs.

    Without --mission: global view (disk-only, no DB).
    With --mission: full assembled context packet from DB + disk.
    """
    from modules.clients.cli.context import run_context
    run_context(ctx.logger, "show", output_format=ctx.output_format, mission_id=mission_id)


@context.command("assembled")
@click.option("--mission", "mission_id", required=True, help="Mission ID.")
@click.option("--tags", "domain_tags", default=None, help="Comma-separated domain tags (e.g. code,implementation).")
@click.pass_obj
def context_assembled(ctx, mission_id, domain_tags):
    """Build the full assembled context packet for a mission.

    Shows exactly what an agent receives: PCD + task + Code Map + history.
    Requires a running database.
    """
    from modules.clients.cli.context import run_context
    tags = domain_tags.split(",") if domain_tags else None
    run_context(ctx.logger, "assembled", output_format=ctx.output_format,
                mission_id=mission_id, domain_tags=tags)


@context.command("codemap")
@click.option("--generate", is_flag=True, help="Regenerate before showing.")
@click.option("--format", "format_type", type=click.Choice(["markdown", "json"]),
              default="markdown", help="Output format.")
@click.pass_obj
def context_codemap(ctx, generate, format_type):
    """Show or generate the Code Map."""
    from modules.clients.cli.context import run_context
    run_context(ctx.logger, "codemap", output_format=ctx.output_format,
                generate=generate, format_type=format_type)


@context.command("pqi")
@click.pass_obj
def context_pqi(ctx):
    """Run the PyQuality Index scorer."""
    from modules.clients.cli.context import run_context
    run_context(ctx.logger, "pqi", output_format=ctx.output_format)


@context.command("deps")
@click.pass_obj
def context_deps(ctx):
    """Show dependency graph analysis."""
    from modules.clients.cli.context import run_context
    run_context(ctx.logger, "deps", output_format=ctx.output_format)


# =============================================================================
# DB group
# =============================================================================


@admin_cli.group(cls=ShowHelpOnMissingArgs, invoke_without_command=True)
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
@click.option("--include-missions", is_flag=True, default=False,
              help="Also clear missions and MCD (full nuclear reset).")
@click.pass_obj
def db_clear(ctx, yes, include_missions):
    """Clear run data. Missions and MCD are preserved by default."""
    from modules.clients.cli.db import run_db
    run_db(ctx.logger, action="clear", table=None, limit=10, confirm=yes,
           include_missions=include_missions)


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
                elif isinstance(param, click.Option) and param.name not in ("help", "verbose", "debug"):
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


# =============================================================================
# Agent Catalog commands
# =============================================================================


@admin_cli.group("catalog", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def catalog(ctx):
    """Browse and manage the agent catalog.

    \b
    Examples:
        python admin.py catalog list
        python admin.py catalog detail vertical.software.quality.agent
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@catalog.command("list")
@click.pass_obj
def catalog_list(ctx):
    """List all agents in the catalog."""
    from modules.clients.cli.catalog_cmds import run_catalog
    run_catalog(ctx.logger, "list", output_format=ctx.output_format)


@catalog.command("detail")
@click.argument("agent_name")
@click.pass_obj
def catalog_detail(ctx, agent_name):
    """Show detail for a specific agent."""
    from modules.clients.cli.catalog_cmds import run_catalog
    run_catalog(ctx.logger, "detail", agent_name=agent_name, output_format=ctx.output_format)


# =============================================================================
# Admin commands
# =============================================================================


@admin_cli.group("admin", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def admin(ctx):
    """Administrative operations.

    \b
    Examples:
        python admin.py admin seed-catalog
        python admin.py admin seed-catalog --force
        python admin.py admin metrics
        python admin.py admin costs
        python admin.py admin config
        python admin.py admin health
        python admin.py admin roles
        python admin.py admin update-prompt --agent <name> --content @path/to/prompt.md
        python admin.py admin toggle-agent --agent <name>
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@admin.command("seed-catalog")
@click.option("--force", is_flag=True, help="Clear and re-seed the catalog.")
@click.pass_obj
def admin_seed_catalog(ctx, force):
    """Seed the agent catalog from config/agents/ YAML files."""
    from modules.clients.cli.catalog_cmds import run_admin
    run_admin(ctx.logger, "seed-catalog", force=force, output_format=ctx.output_format)


@admin.command("seed-workflows")
@click.option("--force", is_flag=True, help="Delete and re-seed system workflow templates.")
@click.pass_obj
def admin_seed_workflows(ctx, force):
    """Seed workflow_definitions from config/workflow_templates/ YAML files."""
    import asyncio

    async def _run():
        from modules.backend.services.workflow_definition import WorkflowDefinitionService
        from modules.backend.services.workflow_seeder import seed_workflows

        async with WorkflowDefinitionService.factory() as svc:
            result = await seed_workflows(svc, force=force)
        ctx.logger.info(f"Workflow seeding: {result}")
        click.echo(f"Seeded: {result['seeded']}, Skipped: {result['skipped']}, Errors: {result['errors']}")

    asyncio.run(_run())


@admin.command("metrics")
@click.pass_obj
def admin_metrics(ctx):
    """Show platform overview metrics (missions, sessions, costs)."""
    from modules.clients.cli.admin_cmds import run_admin_cmd
    run_admin_cmd(ctx.logger, "metrics", output_format=ctx.output_format)


@admin.command("costs")
@click.pass_obj
def admin_costs(ctx):
    """Show cost breakdown by agent and execution status."""
    from modules.clients.cli.admin_cmds import run_admin_cmd
    run_admin_cmd(ctx.logger, "costs", output_format=ctx.output_format)


@admin.command("config")
@click.pass_obj
def admin_config(ctx):
    """View platform configuration (non-secret values)."""
    from modules.clients.cli.admin_cmds import run_admin_cmd
    run_admin_cmd(ctx.logger, "config", output_format=ctx.output_format)


@admin.command("health")
@click.pass_obj
def admin_health(ctx):
    """Run system health check (database, Redis)."""
    from modules.clients.cli.admin_cmds import run_admin_cmd
    run_admin_cmd(ctx.logger, "health", output_format=ctx.output_format)


@admin.command("roles")
@click.pass_obj
def admin_roles(ctx):
    """List configured role hierarchy."""
    from modules.clients.cli.admin_cmds import run_admin_cmd
    run_admin_cmd(ctx.logger, "roles", output_format=ctx.output_format)


@admin.command("user-roles")
@click.pass_obj
def admin_user_roles(ctx):
    """List user-to-role assignments."""
    from modules.clients.cli.admin_cmds import run_admin_cmd
    run_admin_cmd(ctx.logger, "user-roles", output_format=ctx.output_format)


@admin.command("update-prompt")
@click.option("--agent", "agent_name", required=True, help="Agent name.")
@click.option("--content", required=True, help="Prompt text or @filepath to read from file.")
@click.option("--reason", "change_reason", default=None, help="Reason for the change.")
@click.pass_obj
def admin_update_prompt(ctx, agent_name, content, change_reason):
    """Update an agent's system prompt with version tracking."""
    from modules.clients.cli.admin_cmds import run_admin_cmd
    run_admin_cmd(
        ctx.logger, "update-prompt",
        agent_name=agent_name, content=content, change_reason=change_reason,
        output_format=ctx.output_format,
    )


@admin.command("toggle-agent")
@click.option("--agent", "agent_name", required=True, help="Agent name to enable/disable.")
@click.pass_obj
def admin_toggle_agent(ctx, agent_name):
    """Toggle an agent's enabled/disabled state."""
    from modules.clients.cli.admin_cmds import run_admin_cmd
    run_admin_cmd(ctx.logger, "toggle-agent", agent_name=agent_name, output_format=ctx.output_format)


@admin.command("bootstrap-user")
@click.option("--email", required=True, help="Admin email address.")
@click.option("--name", "display_name", default=None, help="Display name (defaults to email prefix).")
@click.option("--password", default=None, help="Password (prompted if omitted).")
@click.pass_obj
def admin_bootstrap_user(ctx, email, display_name, password):
    """Create the first admin user and generate their API key."""
    from modules.clients.cli.admin_cmds import run_admin_cmd
    run_admin_cmd(
        ctx.logger, "bootstrap-user",
        email=email, display_name=display_name, password=password,
        output_format=ctx.output_format,
    )


@admin.command("reset-password")
@click.option("--email", required=True, help="User email address.")
@click.option("--password", default=None, help="New password (prompted if omitted).")
@click.pass_obj
def admin_reset_password(ctx, email, password):
    """Reset a user's password from the command line."""
    from modules.clients.cli.admin_cmds import run_admin_cmd
    run_admin_cmd(
        ctx.logger, "reset-password",
        email=email, password=password,
        output_format=ctx.output_format,
    )


@admin.command("ensure-system-accounts")
@click.pass_obj
def admin_ensure_system_accounts(ctx):
    """Create system service accounts (workflow runner, CLI, scheduler)."""
    from modules.clients.cli.admin_cmds import run_admin_cmd
    run_admin_cmd(
        ctx.logger, "ensure-system-accounts",
        output_format=ctx.output_format,
    )


# =============================================================================
# Schedule commands
# =============================================================================


@admin_cli.group("schedule", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def schedule(ctx):
    """Manage cron-based workflow schedules.

    \b
    Examples:
        python admin.py schedule list --mission <id>
        python admin.py schedule create --mission <id> --workflow <id> --cron "0 5 * * *"
        python admin.py schedule enable <id>
        python admin.py schedule disable <id>
        python admin.py schedule delete <id>
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@schedule.command("list")
@click.option("--mission", "mission_id", required=True, help="Mission ID.")
@click.pass_obj
def schedule_list(ctx, mission_id):
    """List schedules for a mission."""
    from modules.clients.cli.schedule_cmds import run_schedule
    run_schedule(ctx.logger, "list", mission_id=mission_id,
                 output_format=ctx.output_format)


@schedule.command("create")
@click.option("--mission", "mission_id", required=True, help="Mission ID.")
@click.option("--workflow", "workflow_definition_id", required=True,
              help="Workflow definition ID.")
@click.option("--cron", required=True, help='Cron expression, e.g. "0 5 * * *".')
@click.option("--description", default="", help="Schedule description.")
@click.option("--budget", type=float, default=None, help="Budget per run (USD).")
@click.option("--max-iterations", type=int, default=None,
              help="Max total runs (NULL = unlimited).")
@click.option("--cooldown", type=int, default=0,
              help="Min seconds between runs.")
@click.pass_obj
def schedule_create(ctx, mission_id, workflow_definition_id, cron, description,
                    budget, max_iterations, cooldown):
    """Create a cron-based workflow schedule."""
    from modules.clients.cli.schedule_cmds import run_schedule
    run_schedule(ctx.logger, "create", mission_id=mission_id,
                 workflow_definition_id=workflow_definition_id,
                 cron=cron, description=description,
                 budget=budget, max_iterations=max_iterations,
                 cooldown=cooldown, output_format=ctx.output_format)


@schedule.command("enable")
@click.argument("schedule_id")
@click.pass_obj
def schedule_enable(ctx, schedule_id):
    """Enable a schedule."""
    from modules.clients.cli.schedule_cmds import run_schedule
    run_schedule(ctx.logger, "enable", schedule_id=schedule_id,
                 output_format=ctx.output_format)


@schedule.command("disable")
@click.argument("schedule_id")
@click.pass_obj
def schedule_disable(ctx, schedule_id):
    """Disable a schedule."""
    from modules.clients.cli.schedule_cmds import run_schedule
    run_schedule(ctx.logger, "disable", schedule_id=schedule_id,
                 output_format=ctx.output_format)


@schedule.command("delete")
@click.argument("schedule_id")
@click.pass_obj
def schedule_delete(ctx, schedule_id):
    """Delete a schedule."""
    from modules.clients.cli.schedule_cmds import run_schedule
    run_schedule(ctx.logger, "delete", schedule_id=schedule_id,
                 output_format=ctx.output_format)


# =============================================================================
# Tree command
# =============================================================================


@admin_cli.command("tree")
def tree_cmd():
    """Show the full command tree with all options."""
    click.echo("admin")
    lines = _format_tree(admin_cli)
    click.echo("\n".join(lines))


# =============================================================================
# Architect
# =============================================================================


@admin_cli.group("architect", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def architect(ctx):
    """Design workflows with the Workflow Architect.

    \b
    Examples:
        admin.py architect chat --mission <ID> --message "Design a code review workflow"
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@architect.command("chat")
@click.option("--mission", "mission_id", required=True, help="Mission ID.")
@click.option("--message", required=True, help="Message to the Workflow Architect.")
@click.pass_obj
def architect_chat(ctx, mission_id, message):
    """Send a message to the Workflow Architect for conversational design."""
    from modules.clients.cli.architect_cmds import run_architect
    run_architect(ctx.logger, "chat", mission_id=mission_id, message=message,
                  output_format=ctx.output_format)


# =============================================================================
# Workshop
# =============================================================================


@admin_cli.group("workshop", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def workshop(ctx):
    """Run agents in workshop (sandbox) mode for testing and prompt iteration.

    \b
    Examples:
        admin.py workshop run code.qa.agent --inputs '{"target": "modules/"}'
        admin.py workshop cached-inputs code.qa.agent --mission <ID>
        admin.py workshop history --agent code.qa.agent
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@workshop.command("run")
@click.argument("agent_name")
@click.option("--inputs", "inputs_json", default=None, help="JSON string of input data.")
@click.option("--prompt-override", default=None, help="Temporary system prompt override.")
@click.pass_obj
def workshop_run(ctx, agent_name, inputs_json, prompt_override):
    """Run a single agent in isolation for testing."""
    from modules.clients.cli.workshop_cmds import run_workshop
    run_workshop(ctx.logger, "run", agent_name=agent_name, inputs_json=inputs_json,
                 prompt_override=prompt_override, output_format=ctx.output_format)


@workshop.command("cached-inputs")
@click.argument("agent_name")
@click.option("--mission", "mission_id", default=None, help="Scope to a specific mission.")
@click.option("--limit", default=10, help="Max results.")
@click.pass_obj
def workshop_cached_inputs(ctx, agent_name, mission_id, limit):
    """Show cached inputs from previous runs of this agent."""
    from modules.clients.cli.workshop_cmds import run_workshop
    run_workshop(ctx.logger, "cached-inputs", agent_name=agent_name,
                 mission_id=mission_id, limit=limit, output_format=ctx.output_format)


@workshop.command("history")
@click.option("--agent", "agent_name", default=None, help="Filter by agent name.")
@click.option("--limit", default=20, help="Max results.")
@click.pass_obj
def workshop_history(ctx, agent_name, limit):
    """List workshop run history."""
    from modules.clients.cli.workshop_cmds import run_workshop
    run_workshop(ctx.logger, "history", agent_name=agent_name, limit=limit,
                 output_format=ctx.output_format)


# =============================================================================
# Console — Rich Live terminal dashboard
# =============================================================================


@admin_cli.group("console", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def console(ctx):
    """Live terminal dashboard for monitoring Mission Control.

    \b
    Examples:
        python admin.py console monitor
        python admin.py console monitor --view developer
        python admin.py console monitor --refresh 5
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@console.command("monitor")
@click.option("--view", type=click.Choice(["user", "developer"]), default="user",
              help="Display mode: user (default) or developer.")
@click.option("--refresh", default=2.0, type=float, help="Refresh interval in seconds.")
@click.pass_obj
def console_monitor(ctx, view, refresh):
    """Live-updating console monitor with missions, runs, and system health."""
    from modules.clients.cli.console_cmds import run_monitor
    run_monitor(view=view, refresh=refresh)


# =============================================================================
# Entry point
# =============================================================================


if __name__ == "__main__":
    admin_cli()
