"""
mc team — API-based agent team management for the user CLI.

All operations go through the HTTP API. Zero backend service imports.
"""

from modules.clients.cli.api_client import ApiError, CliApiClient, extract_list
from modules.clients.common.display import build_table, get_console
from modules.clients.common.gate_helpers import filter_catalog_agents


def _split_model(model_str: str) -> tuple[str, str]:
    """Split a 'provider:model' string into its parts.

    Returns ('—', '—') if empty, or ('—', raw) if no provider prefix.
    """
    if not model_str:
        return "—", "—"
    if ":" not in model_str:
        return "—", model_str
    provider, model_name = model_str.split(":", 1)
    return provider, model_name


def _short_description(desc: str, limit: int = 70) -> str:
    """First line of the description, truncated for table display."""
    if not desc:
        return "—"
    first_line = desc.strip().split("\n", 1)[0]
    if len(first_line) <= limit:
        return first_line
    return first_line[: limit - 1].rstrip() + "…"


async def list_team(api: CliApiClient, mission_id: str) -> None:
    """List agents on the current mission's team."""
    console = get_console()

    data = await api.get(f"/missions/{mission_id}/team")
    members = extract_list(data, "team_members")

    if not members:
        console.print("[dim]No agents assigned to this mission.[/dim]")
        console.print("[dim]  Use: mc team add --agent <name>[/dim]")
        return

    table = build_table(f"Team ({len(members)} agents)", columns=[
        ("Agent", {"style": "cyan", "width": 32}),
        ("Provider", {"style": "magenta", "width": 10}),
        ("Model", {"style": "green", "width": 22}),
        ("Description", {"ratio": 1, "style": "dim"}),
        ("On", {"width": 4, "justify": "center"}),
    ])

    for m in members:
        agent = m.get("agent") or {}
        name = agent.get("agent_name", m.get("agent_catalog_id", ""))
        provider, model_name = _split_model((agent.get("model") or {}).get("name", ""))
        desc = _short_description(agent.get("description", ""))
        enabled = "[green]✓[/green]" if m.get("enabled", True) else "[red]✗[/red]"
        table.add_row(name, provider, model_name, desc, enabled)

    console.print(table)


async def list_available(api: CliApiClient, search: str | None = None) -> None:
    """Browse the global agent catalog."""
    console = get_console()

    agents = await api.get("/agents/registry")
    if not agents:
        console.print("[dim]No agents found.[/dim]")
        return

    if search:
        agents = filter_catalog_agents(agents, search)

    if not agents:
        console.print(f"[dim]No agents matching '{search}'.[/dim]")
        return

    table = build_table(f"Agent Catalog ({len(agents)} agents)", columns=[
        ("Name", {"style": "cyan", "width": 30}),
        ("Description", {"ratio": 1}),
    ])

    for a in agents:
        desc = (a.get("description") or "")[:60]
        table.add_row(a.get("agent_name", ""), desc)

    console.print(table)


async def add_agent(api: CliApiClient, mission_id: str, agent_name: str) -> None:
    """Add an agent to the current mission by name."""
    console = get_console()

    # Look up agent catalog entry by name
    catalog = await api.get("/catalog/agents")
    agents = extract_list(catalog, "agents")
    matched = [a for a in agents if a.get("agent_name") == agent_name]

    if not matched:
        console.print(f"[red]Agent '{agent_name}' not found in catalog.[/red]")
        console.print("[dim]  Use: mc team available --search <query>[/dim]")
        return

    catalog_id = matched[0].get("id", matched[0].get("agent_catalog_id"))

    try:
        await api.post(
            f"/missions/{mission_id}/team",
            body={"agent_catalog_id": catalog_id},
        )
    except ApiError as exc:
        if exc.status == 409:
            console.print(
                f"[yellow]Agent '{agent_name}' is already on this team.[/yellow]"
            )
            return
        raise

    console.print(f"[green]Added:[/green] {agent_name}")


async def remove_agent(api: CliApiClient, mission_id: str, agent_name: str) -> None:
    """Remove an agent from the current mission by name."""
    console = get_console()

    # Find team member by agent name
    data = await api.get(f"/missions/{mission_id}/team")
    members = extract_list(data, "team_members")

    matched = [
        m for m in members
        if m.get("agent", {}).get("agent_name") == agent_name
    ]

    if not matched:
        console.print(f"[red]Agent '{agent_name}' not found on this team.[/red]")
        return

    member_id = matched[0]["id"]
    await api.delete(f"/missions/{mission_id}/team/{member_id}")
    console.print(f"[yellow]Removed:[/yellow] {agent_name}")
