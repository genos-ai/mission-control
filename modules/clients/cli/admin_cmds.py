"""
CLI handlers for admin operations.

Provides metrics, config view, health check, and role management CLI actions.
Catalog seeding lives in catalog_cmds.py; these are the other admin subcommands.
"""

import asyncio
import json
import sys

from modules.clients.cli.report import build_table, get_console


def run_admin_cmd(
    cli_logger,
    action: str,
    *,
    agent_name: str | None = None,
    content: str | None = None,
    change_reason: str | None = None,
    user_id: str | None = None,
    role: str | None = None,
    email: str | None = None,
    display_name: str | None = None,
    password: str | None = None,
    output_format: str = "human",
) -> None:
    """Dispatch admin CLI actions."""
    actions = {
        "metrics": _action_metrics,
        "costs": _action_costs,
        "config": _action_config,
        "health": _action_health,
        "roles": _action_roles,
        "user-roles": _action_user_roles,
        "update-prompt": _action_update_prompt,
        "toggle-agent": _action_toggle_agent,
        "bootstrap-user": _action_bootstrap_user,
        "reset-password": _action_reset_password,
        "ensure-system-accounts": _action_ensure_system_accounts,
        "seed-dev-users": _action_seed_dev_users,
    }
    fn = actions.get(action)
    if not fn:
        get_console().print(f"[red]Unknown admin action: {action}[/red]")
        sys.exit(1)

    asyncio.run(
        fn(
            cli_logger,
            agent_name=agent_name,
            content=content,
            change_reason=change_reason,
            user_id=user_id,
            role=role,
            email=email,
            display_name=display_name,
            password=password,
            output_format=output_format,
        )
    )


async def _action_metrics(cli_logger, *, output_format, **_):
    """Show platform overview metrics."""
    from modules.backend.services.platform_metrics import PlatformMetricsService

    console = get_console()
    async with PlatformMetricsService.factory() as svc:
        overview = await svc.get_overview()

    if output_format == "json":
        console.print_json(json.dumps(overview, default=str))
        return

    table = build_table(
        "Platform Overview",
        columns=[
            ("Metric", {"style": "cyan", "width": 25}),
            ("Value", {"justify": "right", "width": 15}),
        ],
    )
    for key, val in overview["counts"].items():
        table.add_row(key.replace("_", " ").title(), str(val))
    table.add_row("Total Cost USD", f"${overview['total_cost_usd']:.4f}", end_section=True)

    console.print(table)


async def _action_costs(cli_logger, *, output_format, **_):
    """Show cost breakdown by agent and status."""
    from modules.backend.services.platform_metrics import PlatformMetricsService

    console = get_console()
    async with PlatformMetricsService.factory() as svc:
        costs = await svc.get_cost_summary()

    if output_format == "json":
        console.print_json(json.dumps(costs, default=str))
        return

    if costs["by_agent"]:
        agent_table = build_table(
            "Cost by Agent",
            columns=[
                ("Agent", {"style": "cyan", "width": 35}),
                ("Runs", {"justify": "right", "width": 10}),
                ("Total Cost", {"justify": "right", "width": 14}),
            ],
        )
        for row in costs["by_agent"]:
            agent_table.add_row(
                row["agent_name"], str(row["runs"]), f"${row['total_cost_usd']:.4f}"
            )
        console.print(agent_table)

    if costs["by_status"]:
        status_table = build_table(
            "Cost by Status",
            columns=[
                ("Status", {"style": "cyan", "width": 20}),
                ("Count", {"justify": "right", "width": 10}),
                ("Total Cost", {"justify": "right", "width": 14}),
            ],
        )
        for row in costs["by_status"]:
            status_table.add_row(row["status"], str(row["count"]), f"${row['total_cost_usd']:.4f}")
        console.print(status_table)


async def _action_config(cli_logger, *, output_format, **_):
    """Show platform configuration (non-secret values)."""
    from modules.backend.core.config import get_app_config

    console = get_console()
    config = get_app_config()

    data = {
        "application": {
            "name": config.application.name,
            "version": config.application.version,
            "environment": config.application.environment,
            "debug": config.application.debug,
        },
        "workflows": {
            "max_steps": config.workflows.max_steps_per_workflow,
            "default_budget": config.workflows.default_budget_usd,
            "max_budget": config.workflows.max_budget_usd,
            "max_concurrent": config.workflows.max_concurrent_missions,
            "max_runs_per_day": config.workflows.max_scheduled_runs_per_day,
        },
    }

    if output_format == "json":
        console.print_json(json.dumps(data, default=str))
        return

    for section, values in data.items():
        table = build_table(
            section.title(),
            columns=[
                ("Key", {"style": "cyan", "width": 30}),
                ("Value", {"width": 30}),
            ],
        )
        for k, v in values.items():
            table.add_row(k, str(v))
        console.print(table)


async def _action_health(cli_logger, *, output_format, **_):
    """Run system health check."""
    from modules.backend.services.health import HealthCheckService

    console = get_console()
    svc = HealthCheckService()
    report = await svc.check_readiness()

    if output_format == "json":
        checks = {
            c.name: {"status": c.status, "latency_ms": c.latency_ms, "error": c.error}
            for c in report.components
        }
        console.print_json(json.dumps(checks, default=str))
        return

    for component in report.components:
        status = component.status
        color = (
            "green" if status == "healthy" else ("yellow" if status == "not_configured" else "red")
        )
        console.print(f"  [{color}]{component.name}: {status}[/{color}]")
        if component.latency_ms is not None:
            console.print(f"    latency: {component.latency_ms}ms")


async def _action_roles(cli_logger, *, output_format, **_):
    """Show configured roles."""
    from modules.backend.core.config import get_app_config

    console = get_console()
    config = get_app_config()

    if output_format == "json":
        data = {
            name: {"level": r.level, "description": r.description}
            for name, r in config.security.roles.items()
        }
        console.print_json(json.dumps(data))
        return

    table = build_table(
        "Roles",
        columns=[
            ("Role", {"style": "cyan", "width": 15}),
            ("Level", {"justify": "right", "width": 8}),
            ("Description", {"ratio": 1}),
        ],
    )
    for name, r in sorted(config.security.roles.items(), key=lambda x: x[1].level):
        table.add_row(name, str(r.level), r.description)
    console.print(table)


async def _action_user_roles(cli_logger, *, output_format, **_):
    """Show user-role assignments."""
    from modules.backend.core.config import get_app_config

    console = get_console()
    config = get_app_config()

    user_roles = config.security.user_roles
    if output_format == "json":
        console.print_json(json.dumps(user_roles))
        return

    if not user_roles:
        console.print("[dim]No user role assignments. All users default to 'viewer'.[/dim]")
        return

    table = build_table(
        "User Role Assignments",
        columns=[
            ("User ID", {"style": "cyan", "width": 30}),
            ("Role", {"width": 15}),
        ],
    )
    for uid, r in user_roles.items():
        table.add_row(uid, r)
    console.print(table)


async def _action_update_prompt(cli_logger, *, agent_name, content, change_reason, **_):
    """Update an agent's system prompt from the CLI."""
    console = get_console()
    if not agent_name:
        console.print("[red]--agent is required[/red]")
        sys.exit(1)
    if not content:
        console.print("[red]--content is required (prompt text or @filepath)[/red]")
        sys.exit(1)

    prompt_content = content
    if content.startswith("@"):
        import pathlib

        path = pathlib.Path(content[1:])
        if not path.exists():
            console.print(f"[red]File not found: {path}[/red]")
            sys.exit(1)
        prompt_content = path.read_text()

    from modules.backend.services.agent_catalog import AgentCatalogService

    async with AgentCatalogService.factory() as svc:
        entry = await svc.update_system_prompt(
            agent_name=agent_name,
            content=prompt_content,
            changed_by="admin:cli",
            change_reason=change_reason,
        )

    console.print(
        f"[green]Updated prompt for {entry.agent_name} ({len(entry.system_prompt)} chars)[/green]"
    )


async def _action_toggle_agent(cli_logger, *, agent_name, **_):
    """Toggle an agent's enabled state."""
    console = get_console()
    if not agent_name:
        console.print("[red]--agent is required[/red]")
        sys.exit(1)

    from modules.backend.services.agent_catalog import AgentCatalogService

    async with AgentCatalogService.factory() as svc:
        entry = await svc.get_by_name(agent_name)
        new_state = not entry.enabled
        await svc.update_entry(agent_name, enabled=new_state)

    state_str = "[green]enabled[/green]" if new_state else "[red]disabled[/red]"
    console.print(f"Agent {agent_name}: {state_str}")


def _prompt_password(console, prompt: str = "Password (min 12 chars): ") -> str:
    """Prompt for a password with confirmation. Exits on failure."""
    import getpass

    password = getpass.getpass(prompt)
    if len(password) < 12:
        console.print("[red]Password must be at least 12 characters[/red]")
        sys.exit(1)
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        console.print("[red]Passwords do not match[/red]")
        sys.exit(1)
    return password


async def _action_bootstrap_user(cli_logger, *, email, display_name, password, **_):
    """Create the first admin user and generate their API key."""
    from modules.backend.core.exceptions import ConflictError
    from modules.backend.services.bootstrap import BootstrapService

    console = get_console()

    if not email:
        console.print("[red]--email is required[/red]")
        sys.exit(1)
    if not display_name:
        display_name = email.split("@")[0]
    if not password:
        password = _prompt_password(console, "Admin password (min 12 chars): ")

    try:
        async with BootstrapService.factory() as svc:
            user, api_key = await svc.bootstrap_admin(
                email=email,
                display_name=display_name,
                password=password,
            )
    except ConflictError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    console.print("\n[green]Admin user created:[/green]")
    console.print(f"  Email: {user.email}")
    console.print(f"  Name:  {user.display_name}")
    console.print(f"  ID:    {user.id}")
    console.print("\n[yellow]API Key (save this — it will not be shown again):[/yellow]")
    console.print(f"  {api_key}")
    console.print()


async def _action_reset_password(cli_logger, *, email, password, **_):
    """Reset a user's password from the CLI."""
    from modules.backend.core.exceptions import NotFoundError
    from modules.backend.services.bootstrap import BootstrapService

    console = get_console()

    if not email:
        console.print("[red]--email is required[/red]")
        sys.exit(1)
    if not password:
        password = _prompt_password(console, "New password (min 12 chars): ")

    try:
        async with BootstrapService.factory() as svc:
            await svc.reset_password_by_email(email, password)
    except NotFoundError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    console.print(f"[green]Password reset for {email}[/green]")


async def _action_ensure_system_accounts(cli_logger, **_):
    """Create well-known system service accounts if they don't exist."""
    from modules.backend.services.bootstrap import BootstrapService

    console = get_console()

    async with BootstrapService.factory() as svc:
        created = await svc.ensure_system_accounts()

    if created:
        for user in created:
            console.print(f"  [green]Created:[/green] {user.id} ({user.display_name})")
    else:
        console.print("[dim]All system accounts already exist.[/dim]")


async def _action_seed_dev_users(cli_logger, **_):
    """Create dev/test users (sysadmin, admin, user) with known passwords."""
    from modules.backend.core.exceptions import AuthorizationError
    from modules.backend.services.bootstrap import BootstrapService

    console = get_console()

    try:
        async with BootstrapService.factory() as svc:
            created = await svc.ensure_dev_users()
    except AuthorizationError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    if created:
        for user in created:
            console.print(f"  [green]Created:[/green] {user.email} ({user.system_role})")
        console.print(f"\n[bold]{len(created)} dev user(s) created.[/bold]")
        console.print("[dim]Passwords are in config/.env under Dev/Test Users.[/dim]")
    else:
        console.print("[dim]All dev users already exist.[/dim]")
