"""Admin CLI — Mission group (Plan 84 Phase 5.5, split out of root admin.py).

Pure move, no behavior change.
"""

import click

from modules.clients.cli.cli_context import ShowHelpOnMissingArgs

# =============================================================================
# Mission group
# =============================================================================


@click.group("mission", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def mission(ctx):
    """Create, list, and manage missions.

    \b
    Examples:
        python admin.py mission create --name my-mission --description "My mission" \\
            --gate-mode manual
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
@click.option("--repo-url", default=None, help="Repository URL.")
@click.option("--repo-root", default=None, help="Local repo root path.")
@click.option(
    "--tier", default="user", type=click.Choice(["user", "platform"]), help="Mission tier."
)
@click.option(
    "--gate-mode",
    "gate_mode",
    required=True,
    type=click.Choice(["interactive", "manual", "ai_assisted", "autonomous"]),
    help="Plan gate mode.",
)
@click.pass_obj
def mission_create(ctx, name, description, brief, roster, repo_url, repo_root, tier, gate_mode):
    """Create a new mission."""
    from modules.clients.cli.mission_cmds import run_mission

    run_mission(
        ctx.logger,
        "create",
        name=name,
        description=description,
        brief=brief,
        roster=roster,
        repo_url=repo_url,
        repo_root=repo_root,
        gate_mode=gate_mode,
        tier=tier,
        output_format=ctx.output_format,
    )


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

    run_mission(
        ctx.logger, "detail", mission_id=mission_id, name=name, output_format=ctx.output_format
    )


@mission.command("archive")
@click.argument("mission_id", required=False)
@click.pass_obj
def mission_archive(ctx, mission_id):
    """Archive a mission.

    Uses current mission if MISSION_ID is omitted.
    """
    from modules.clients.cli.mission_cmds import run_mission

    run_mission(ctx.logger, "archive", mission_id=mission_id, output_format=ctx.output_format)


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
        click.confirm(
            "This will permanently delete the mission and all its data. Continue?", abort=True
        )
    from modules.clients.cli.mission_cmds import run_mission

    run_mission(ctx.logger, "delete", mission_id=mission_id, output_format=ctx.output_format)


@mission.command("use")
@click.argument("mission_id")
@click.pass_obj
def mission_use(ctx, mission_id):
    """Set the current mission (persists across commands)."""
    from modules.clients.cli.mission_cmds import run_mission

    run_mission(ctx.logger, "use", mission_id=mission_id, output_format=ctx.output_format)


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

    run_mission(ctx.logger, "context-show", mission_id=mission_id, output_format=ctx.output_format)


@mission_context.command("history")
@click.argument("mission_id", required=False)
@click.pass_obj
def mission_context_history(ctx, mission_id):
    """Show MCD change audit trail.

    Uses current mission if MISSION_ID is omitted.
    """
    from modules.clients.cli.mission_cmds import run_mission

    run_mission(
        ctx.logger, "context-history", mission_id=mission_id, output_format=ctx.output_format
    )


@mission.command("summarize")
@click.argument("mission_id", required=False)
@click.pass_obj
def mission_summarize(ctx, mission_id):
    """Run the summarization pipeline for a mission.

    Uses current mission if MISSION_ID is omitted.
    """
    from modules.clients.cli.mission_cmds import run_mission

    run_mission(ctx.logger, "summarize", mission_id=mission_id, output_format=ctx.output_format)


@mission.command("clear-sessions")
@click.argument("mission_id", required=False)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@click.pass_obj
def mission_clear_sessions(ctx, mission_id, yes):
    """Delete all sessions (chat threads) for a mission.

    Removes sessions, messages, and channel bindings.
    Uses current mission if MISSION_ID is omitted.
    """
    import asyncio

    async def _run():
        from modules.backend.services.mission import MissionService

        # Resolve by name or UUID; fall back to current mission
        if mission_id:
            async with MissionService.factory() as msvc:
                m = await msvc.resolve_mission(mission_id)
                mid = str(m.id)
                mname = m.name
        else:
            from modules.clients.cli.mission_context import async_require_mission_id

            mid = await async_require_mission_id(None)
            mname = mid[:12]

        if not yes:
            click.echo(
                click.style(
                    f"This will DELETE all sessions and messages for mission '{mname}' ({mid}).",
                    fg="red",
                    bold=True,
                )
            )
            if not click.confirm("Are you sure?"):
                click.echo("Aborted.")
                return

        from modules.backend.services.session import SessionService

        async with SessionService.factory() as svc:
            count = await svc.delete_by_mission(mid)

        click.echo(click.style(f"Cleared {count} session(s) for '{mname}'.", fg="green"))

    asyncio.run(_run())
