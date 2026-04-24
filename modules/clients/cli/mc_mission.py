"""
mc mission — API-based mission CRUD handlers for the user CLI.

All operations go through the HTTP API. Zero backend service imports.
Used by mc.py only; admin.py continues to use mission_cmds.py.
"""

import json
import sys

from modules.clients.cli.api_client import ApiError, CliApiClient, extract_list, resolve_mission
from modules.clients.common.display import build_table, get_console, styled_status


async def create(
    api: CliApiClient,
    *,
    name: str,
    description: str,
    brief: str | None = None,
    gate_mode: str | None = None,
    budget: float | None = None,
) -> None:
    """Create a new mission."""
    console = get_console()

    # Get authenticated user's ID as owner
    me = await api.get("/auth/me")
    owner_id = me["id"]

    body: dict = {"name": name, "description": description, "owner_id": owner_id}
    if brief:
        body["brief"] = brief
    if budget is not None:
        body["budget_ceiling_usd"] = budget

    mission = await api.post("/missions", body=body)

    console.print(f"[green]Mission created:[/green] {mission['id']}")
    console.print(f"  Name: {mission['name']}")

    # Set gate mode if specified (via plan endpoint)
    if gate_mode:
        await api.patch(
            f"/missions/{mission['id']}/plan",
            body={"gate_mode": gate_mode},
        )
        console.print(f"  Gate: {gate_mode}")


async def list_missions(api: CliApiClient) -> None:
    """List all accessible missions."""
    console = get_console()

    data = await api.get("/missions")
    missions = extract_list(data, "missions")
    me = await api.get("/auth/me")
    current_id = me.get("current_mission_id")

    if not missions:
        console.print("[dim]No missions found.[/dim]")
        return

    table = build_table("Missions", columns=[
        ("Status", {"width": 10}),
        ("Name", {"style": "cyan", "width": 28}),
        ("ID", {"width": 38}),
        ("Description", {"ratio": 1}),
    ], show_lines=True)

    for m in missions:
        name = m["name"]
        if m["id"] == current_id:
            name = f"[bold]{name}[/bold] \u25c0"
        desc = (m.get("description") or "")[:60]
        table.add_row(styled_status(m.get("status", "")), name, m["id"], desc)

    console.print(table)

    if current_id:
        current = next((m for m in missions if m["id"] == current_id), None)
        if current:
            console.print(
                f"\n\U0001f449 Current mission: [bold]{current['name']}[/bold] ({current['id']})"
            )
    else:
        console.print(
            "\n[dim]No current mission set. Use 'mc mission use --name <name>'.[/dim]"
        )


async def use(api: CliApiClient, name_or_id: str) -> None:
    """Set the active mission by name or ID."""
    console = get_console()

    mission = await resolve_mission(api, name_or_id)
    if not mission:
        console.print(f"[red]Mission not found: {name_or_id}[/red]")
        sys.exit(1)

    await api.put(
        "/auth/me/current-mission",
        body={"mission_id": mission["id"]},
    )
    console.print(
        f"\U0001f449 Current mission: [bold]{mission['name']}[/bold] ({mission['id']})"
    )


async def info(api: CliApiClient, mission_id: str) -> None:
    """Show detailed mission info."""
    console = get_console()

    mission = await api.get(f"/missions/{mission_id}")

    console.print(f"[bold]{mission['name']}[/bold]  ({mission.get('status', '')})")
    console.print(f"  ID:          {mission['id']}")
    console.print(f"  Description: {mission.get('description', '')}")
    if mission.get("brief"):
        console.print(f"  Brief:       {mission['brief']}")
    console.print(f"  Owner:       {mission.get('owner_id', '')}")
    console.print(f"  Roster:      {mission.get('default_roster', 'default')}")
    if mission.get("budget_ceiling_usd"):
        console.print(f"  Budget:      ${mission['budget_ceiling_usd']:.2f}")
    if mission.get("repo_url"):
        console.print(f"  Repo:        {mission['repo_url']}")

    # Show team
    try:
        team_data = await api.get(f"/missions/{mission_id}/team")
        members = extract_list(team_data, "team_members")
        if members:
            console.print(f"\n  [bold]Team ({len(members)} agents):[/bold]")
            for m in members:
                agent = m.get("agent", {})
                agent_name = agent.get("agent_name", m.get("agent_catalog_id", ""))
                desc = (agent.get("description") or "")[:60]
                console.print(f"    [cyan]{agent_name}[/cyan]")
                if desc:
                    console.print(f"      {desc}")
    except ApiError as exc:
        if exc.status != 404:
            console.print(f"  [dim yellow]Could not load team: {exc.message}[/dim yellow]")


async def archive(api: CliApiClient, mission_id: str) -> None:
    """Archive the current mission."""
    console = get_console()
    mission = await api.patch(
        f"/missions/{mission_id}",
        body={"status": "archived"},
    )
    console.print(
        f"[yellow]Archived:[/yellow] {mission.get('name', mission_id)}"
    )


async def unarchive(api: CliApiClient, name_or_id: str) -> None:
    """Restore an archived mission to active status."""
    console = get_console()

    mission = await resolve_mission(api, name_or_id, include_archived=True)
    if not mission:
        console.print(f"[red]Mission not found: {name_or_id}[/red]")
        sys.exit(1)

    await api.patch(
        f"/missions/{mission['id']}",
        body={"status": "active"},
    )
    console.print(f"[green]Unarchived:[/green] {mission['name']}")


async def delete(api: CliApiClient, mission_id: str) -> None:
    """Permanently delete a mission and all its data."""
    console = get_console()
    await api.delete(f"/missions/{mission_id}")
    console.print(f"[red]Deleted:[/red] {mission_id}")


async def set_gate(api: CliApiClient, mission_id: str, mode: str) -> None:
    """Set the default gate mode for the current mission."""
    console = get_console()
    await api.patch(
        f"/missions/{mission_id}/plan",
        body={"gate_mode": mode},
    )
    console.print(f"[green]Gate mode set:[/green] {mode}")


async def set_budget(api: CliApiClient, mission_id: str, amount: float) -> None:
    """Set the budget ceiling for the current mission."""
    console = get_console()
    await api.patch(
        f"/missions/{mission_id}/plan",
        body={"budget_usd_ceiling": amount},
    )
    console.print(f"[green]Budget set:[/green] ${amount:.2f}")


async def context_show(api: CliApiClient, mission_id: str) -> None:
    """View the Mission Context Document."""
    console = get_console()
    data = await api.get(f"/missions/{mission_id}/context")
    if not data:
        console.print("[dim]No MCD found for this mission.[/dim]")
        return
    console.print("[bold]Mission Context Document[/bold]")
    console.print()
    console.print(json.dumps(data, indent=2, ensure_ascii=False))


async def context_history(api: CliApiClient, mission_id: str) -> None:
    """MCD change audit trail."""
    console = get_console()
    data = await api.get(f"/missions/{mission_id}/context/history")
    if not data:
        console.print("[dim]No changes recorded.[/dim]")
        return

    changes = extract_list(data, "changes") or extract_list(data, "items")

    table = build_table("MCD Changes", columns=[
        ("Version", {"width": 8}),
        ("Type", {"width": 10}),
        ("Path", {"style": "cyan", "width": 40}),
        ("Agent", {"width": 25}),
        ("Reason", {"ratio": 1}),
    ])

    for c in changes:
        table.add_row(
            str(c.get("version", "")),
            c.get("change_type", ""),
            c.get("path", ""),
            c.get("agent_id", "\u2014"),
            (c.get("reason") or "")[:60],
        )

    console.print(table)
