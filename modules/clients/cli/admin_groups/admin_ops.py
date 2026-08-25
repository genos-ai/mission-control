"""Admin CLI — Admin commands (Plan 84 Phase 5.5, split out of root admin.py).

Pure move, no behavior change.
"""

import click

from modules.clients.cli.cli_context import ShowHelpOnMissingArgs

# =============================================================================
# Admin commands
# =============================================================================


@click.group("admin", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
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
@click.option("--force", is_flag=True, help="Update all agents from YAML (preserves DB prompts).")
@click.option(
    "--reset-prompts",
    is_flag=True,
    help="Also overwrite system prompts from disk (use with --force).",
)
@click.pass_obj
def admin_seed_catalog(ctx, force, reset_prompts):
    """Seed the agent catalog from config/agents/ YAML files.

    --force updates config fields (model, tools, scope) but preserves
    system prompts edited via the admin API.

    --force --reset-prompts also overwrites prompts from disk layers.
    """
    from modules.clients.cli.catalog_cmds import run_admin

    run_admin(
        ctx.logger,
        "seed-catalog",
        force=force,
        reset_prompts=reset_prompts,
        output_format=ctx.output_format,
    )


@admin.command("migrate-planning-agent")
@click.pass_obj
def admin_migrate_planning_agent(ctx):
    """Add mission.planning.agent to all existing mission teams.

    Run once after renaming system.planning.agent → mission.planning.agent.
    Safe to re-run — missions that already have the agent are skipped.
    """
    import asyncio

    async def _run():
        from modules.backend.core.exceptions import ConflictError
        from modules.backend.services.mission import MissionService
        from modules.backend.services.mission_team import MissionTeamService

        added = skipped = errors = 0
        async with MissionService.factory() as msvc:
            # One-off maintenance migration — every mission needs checking,
            # including archived ones, so this uses an effectively-unbounded
            # limit rather than the service's normal page size default.
            missions = await msvc.list_missions(include_archived=True, limit=100_000)
            async with MissionTeamService.factory() as svc:
                for mission in missions:
                    try:
                        await svc.add_agent_by_name(str(mission.id), "mission.planning.agent")
                        added += 1
                    except ConflictError:
                        skipped += 1
                    except Exception as e:
                        ctx.logger.warning(f"Failed for mission {mission.id}: {e}")
                        errors += 1

        click.echo(f"Added: {added}, Already present (skipped): {skipped}, Errors: {errors}")

    asyncio.run(_run())


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
        click.echo(
            f"Seeded: {result['seeded']}, Skipped: {result['skipped']}, Errors: {result['errors']}"
        )

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
        ctx.logger,
        "update-prompt",
        agent_name=agent_name,
        content=content,
        change_reason=change_reason,
        output_format=ctx.output_format,
    )


@admin.command("toggle-agent")
@click.option("--agent", "agent_name", required=True, help="Agent name to enable/disable.")
@click.pass_obj
def admin_toggle_agent(ctx, agent_name):
    """Toggle an agent's enabled/disabled state."""
    from modules.clients.cli.admin_cmds import run_admin_cmd

    run_admin_cmd(
        ctx.logger, "toggle-agent", agent_name=agent_name, output_format=ctx.output_format
    )


@admin.command("bootstrap-user")
@click.option("--email", required=True, help="Admin email address.")
@click.option(
    "--name", "display_name", default=None, help="Display name (defaults to email prefix)."
)
@click.option("--password", default=None, help="Password (prompted if omitted).")
@click.pass_obj
def admin_bootstrap_user(ctx, email, display_name, password):
    """Create the first admin user and generate their API key."""
    from modules.clients.cli.admin_cmds import run_admin_cmd

    run_admin_cmd(
        ctx.logger,
        "bootstrap-user",
        email=email,
        display_name=display_name,
        password=password,
        output_format=ctx.output_format,
    )


@admin.command("seed-dev-users")
@click.pass_obj
def admin_seed_dev_users(ctx):
    """Create dev/test users (sysadmin, admin, user) with known passwords."""
    from modules.clients.cli.admin_cmds import run_admin_cmd

    run_admin_cmd(ctx.logger, "seed-dev-users", output_format=ctx.output_format)


@admin.command("reset-password")
@click.option("--email", required=True, help="User email address.")
@click.option("--password", default=None, help="New password (prompted if omitted).")
@click.pass_obj
def admin_reset_password(ctx, email, password):
    """Reset a user's password from the command line."""
    from modules.clients.cli.admin_cmds import run_admin_cmd

    run_admin_cmd(
        ctx.logger,
        "reset-password",
        email=email,
        password=password,
        output_format=ctx.output_format,
    )


@admin.command("ensure-system-accounts")
@click.pass_obj
def admin_ensure_system_accounts(ctx):
    """Create system service accounts (workflow runner, CLI, scheduler)."""
    from modules.clients.cli.admin_cmds import run_admin_cmd

    run_admin_cmd(
        ctx.logger,
        "ensure-system-accounts",
        output_format=ctx.output_format,
    )
