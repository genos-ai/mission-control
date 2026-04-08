"""
mc team — agent team management for the user CLI.

Thin renderers over MissionTeamService and AgentCatalogService.
"""

from modules.clients.cli.report import build_table
from modules.clients.common.display import get_console


async def list_team(mission_id: str) -> None:
    """List agents on the current mission's team."""
    from modules.backend.services.mission_team import MissionTeamService

    console = get_console()

    async with MissionTeamService.factory() as svc:
        team_info = await svc.list_team_with_names(mission_id, enabled_only=False)

    if not team_info:
        console.print("[dim]No agents assigned to this mission.[/dim]")
        console.print("[dim]  Use: mc team add <agent>[/dim]")
        return

    table = build_table(f"Team ({len(team_info)} agents)", columns=[
        ("Agent", {"style": "cyan", "width": 30}),
        ("Enabled", {"width": 10}),
        ("Added", {"width": 14, "style": "dim"}),
    ])

    for t in team_info:
        enabled = "[green]yes[/green]" if t["enabled"] else "[red]no[/red]"
        when = t["created_at"].strftime("%m-%d %H:%M") if t["created_at"] else ""
        table.add_row(t["agent_name"], enabled, when)

    console.print(table)


async def list_available(search: str | None = None) -> None:
    """Browse the global agent catalog."""
    from modules.backend.services.agent_catalog import AgentCatalogService

    console = get_console()

    async with AgentCatalogService.factory() as svc:
        if search:
            agents = await svc.search_by_keyword(search)
        else:
            agents = await svc.list_catalog(enabled_only=True)

    if not agents:
        console.print("[dim]No agents found.[/dim]")
        return

    table = build_table(f"Agent Catalog ({len(agents)} agents)", columns=[
        ("Name", {"style": "cyan", "width": 30}),
        ("Type", {"width": 15}),
        ("Description", {"ratio": 1}),
    ])

    for a in agents:
        desc = (a.description or "")[:60]
        table.add_row(a.agent_name, a.agent_type or "", desc)

    console.print(table)


async def add_agent(mission_id: str, agent_name: str) -> None:
    """Add an agent to the current mission by name."""
    from modules.backend.core.exceptions import ConflictError, NotFoundError
    from modules.backend.services.mission_team import MissionTeamService

    console = get_console()

    try:
        async with MissionTeamService.factory() as svc:
            await svc.add_agent_by_name(mission_id, agent_name)
    except NotFoundError:
        console.print(f"[red]Agent '{agent_name}' not found in catalog.[/red]")
        console.print("[dim]  Use: mc team available --search <query>[/dim]")
        return
    except ConflictError:
        console.print(f"[yellow]Agent '{agent_name}' is already on this team.[/yellow]")
        return

    console.print(f"[green]Added:[/green] {agent_name}")


async def remove_agent(mission_id: str, agent_name: str) -> None:
    """Remove an agent from the current mission by name."""
    from modules.backend.core.exceptions import NotFoundError
    from modules.backend.services.mission_team import MissionTeamService

    console = get_console()

    try:
        async with MissionTeamService.factory() as svc:
            await svc.remove_agent_by_name(mission_id, agent_name)
    except NotFoundError:
        console.print(f"[red]Agent '{agent_name}' not found on this team.[/red]")
        return

    console.print(f"[yellow]Removed:[/yellow] {agent_name}")
