"""
CLI handler for agent catalog commands.

Thin renderer over AgentCatalogService. Handles list, detail, and seeding.
"""

import asyncio
import sys

from modules.clients.cli.report import get_console, build_table


def run_catalog(cli_logger, action: str, *, agent_name: str | None = None, output_format: str = "human") -> None:
    """Dispatch catalog CLI actions."""
    actions = {
        "list": _action_list,
        "detail": _action_detail,
    }
    fn = actions.get(action)
    if not fn:
        get_console().print(f"[red]Unknown action: {action}[/red]")
        sys.exit(1)

    asyncio.run(fn(cli_logger, agent_name=agent_name, output_format=output_format))


def run_admin(cli_logger, action: str, *, force: bool = False, reset_prompts: bool = False, output_format: str = "human") -> None:
    """Dispatch admin CLI actions."""
    actions = {
        "seed-catalog": _action_seed_catalog,
    }
    fn = actions.get(action)
    if not fn:
        get_console().print(f"[red]Unknown action: {action}[/red]")
        sys.exit(1)

    asyncio.run(fn(cli_logger, force=force, reset_prompts=reset_prompts, output_format=output_format))


async def _action_list(cli_logger, *, output_format, **_):
    """List agents in the catalog."""
    from modules.backend.services.agent_catalog import AgentCatalogService

    console = get_console()
    async with AgentCatalogService.factory() as svc:
        agents = await svc.list_catalog(enabled_only=False, visibility=None)

    if not agents:
        console.print("[dim]No agents in catalog. Run: cli.py admin seed-catalog[/dim]")
        return

    table = build_table("Agent Catalog", columns=[
        ("Name", {"style": "cyan", "width": 35}),
        ("Type", {"width": 12}),
        ("Version", {"width": 10}),
        ("Enabled", {"width": 9}),
        ("Visibility", {"width": 12}),
        ("Description", {"ratio": 1}),
    ])
    for a in agents:
        enabled = "[green]yes[/green]" if a.enabled else "[red]no[/red]"
        desc = a.description[:60] + "..." if len(a.description) > 60 else a.description
        table.add_row(a.agent_name, a.agent_type, a.version, enabled, a.visibility, desc)

    console.print(table)
    console.print(f"\n  [dim]{len(agents)} agents total[/dim]")


async def _action_detail(cli_logger, *, agent_name, **_):
    """Show detail for a specific agent."""
    from modules.backend.services.agent_catalog import AgentCatalogService

    console = get_console()
    if not agent_name:
        console.print("[red]AGENT_NAME is required[/red]")
        sys.exit(1)

    async with AgentCatalogService.factory() as svc:
        agent = await svc.get_by_name_or_none(agent_name)

    if not agent:
        console.print(f"[red]Agent not found: {agent_name}[/red]")
        sys.exit(1)

    console.print(f"[bold]{agent.agent_name}[/bold]  v{agent.version}")
    console.print(f"  Type:        {agent.agent_type}")
    console.print(f"  Enabled:     {agent.enabled}")
    console.print(f"  Visibility:  {agent.visibility}")
    console.print(f"  Description: {agent.description}")
    console.print(f"  Model:       {(agent.model_config_json or {}).get('name', 'N/A')}")
    console.print(f"  Tools:       {', '.join(agent.tools or []) or 'none'}")
    console.print(f"  Keywords:    {', '.join(agent.keywords or []) or 'none'}")

    if agent.system_prompt:
        prompt_preview = agent.system_prompt[:200]
        if len(agent.system_prompt) > 200:
            prompt_preview += "..."
        console.print(f"\n  [bold]System Prompt[/bold] ({len(agent.system_prompt)} chars):")
        console.print(f"    {prompt_preview}")


async def _action_seed_catalog(cli_logger, *, force, reset_prompts=False, **_):
    """Seed the agent catalog from YAML config files via the admin API.

    Routed through the API so the backend's in-memory registry is
    invalidated atomically with the catalog write — a direct DB write
    here would leave the running backend serving stale model bindings.
    """
    from urllib.parse import urlencode
    from modules.clients.cli.api_client import api_client

    console = get_console()
    query = urlencode({"force": str(force).lower(), "reset_prompts": str(reset_prompts).lower()})
    async with api_client() as api:
        counts = await api.post(f"/admin/seed-catalog?{query}")

    console.print("[bold]Catalog seeding complete[/bold]")
    console.print(f"  Seeded:  {counts['seeded']}")
    console.print(f"  Skipped: {counts['skipped']}")
    console.print(f"  Errors:  {counts['errors']}")
