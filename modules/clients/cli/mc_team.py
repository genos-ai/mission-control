"""
mc team — API-based agent team management for the user CLI.

All operations go through the HTTP API. Zero backend service imports.
"""

from modules.clients.cli.api_client import ApiError, CliApiClient, extract_list
from modules.clients.common.display import build_table, get_console
from modules.clients.common.gate_helpers import filter_catalog_agents


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
        ("Agent", {"style": "cyan", "width": 30}),
        ("Enabled", {"width": 10}),
        ("Added", {"width": 14, "style": "dim"}),
    ])

    for m in members:
        agent = m.get("agent", {})
        name = agent.get("agent_name", m.get("agent_catalog_id", ""))
        enabled = "[green]yes[/green]" if m.get("enabled", True) else "[red]no[/red]"
        when = (m.get("created_at") or "")[:16].replace("T", " ")
        table.add_row(name, enabled, when)

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
