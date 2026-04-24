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


# ── Artifacts ─────────────────────────────────────────────────────────


async def list_artifacts(api: CliApiClient, mission_id: str) -> None:
    """List artifacts for the current mission."""
    console = get_console()
    data = await api.get(f"/missions/{mission_id}/artifacts")
    artifacts = data.get("artifacts", [])
    if not artifacts:
        console.print("[dim]No artifacts found.[/dim]")
        return

    from rich.table import Table

    table = Table(title=f"Artifacts ({len(artifacts)})")
    table.add_column("#", style="dim", width=4)
    table.add_column("Type", width=10)
    table.add_column("Agent", width=30)
    table.add_column("Title", width=50)
    table.add_column("Created", width=16)

    for i, a in enumerate(artifacts, 1):
        table.add_row(
            str(i),
            a.get("artifact_type", ""),
            a.get("agent_id", ""),
            a.get("title", "")[:50],
            str(a.get("created_at", ""))[:16],
        )

    console.print(table)


async def show_artifact(api: CliApiClient, mission_id: str, num: int) -> None:
    """Show a specific artifact by its list number."""
    console = get_console()
    data = await api.get(f"/missions/{mission_id}/artifacts")
    artifacts = data.get("artifacts", [])

    if not artifacts:
        console.print("[dim]No artifacts found.[/dim]")
        return

    if num < 1 or num > len(artifacts):
        console.print(f"[red]Artifact #{num} not found. Available: 1-{len(artifacts)}[/red]")
        return

    a = artifacts[num - 1]
    console.print(f"\n[bold]Artifact #{num}[/bold]")
    console.print(f"[bold]ID:[/bold] {a.get('id', '')}")
    console.print(f"[bold]Type:[/bold] {a.get('artifact_type', '')}")
    console.print(f"[bold]Agent:[/bold] {a.get('agent_id', '')}")
    console.print(f"[bold]Title:[/bold] {a.get('title', '')}")
    console.print(f"[bold]Created:[/bold] {a.get('created_at', '')}")
    console.print()

    content = a.get("content_text", "")
    if content:
        if a.get("content_type") == "markdown":
            from rich.markdown import Markdown
            console.print(Markdown(content))
        else:
            console.print(content)
    else:
        console.print("[dim](no content)[/dim]")


# ── Reports ───────────────────────────────────────────────────────────


async def list_reports(api: CliApiClient, mission_id: str) -> None:
    """List research reports from completed runs."""
    console = get_console()

    execs = await api.get("/executions", params={"limit": 50})
    all_records = execs.get("executions", [])
    completed = [
        r for r in all_records
        if r.get("status") == "completed" and r.get("mission_id") == mission_id
    ]

    if not completed:
        console.print("[dim]No completed runs found.[/dim]")
        return

    from rich.table import Table

    table = Table(title=f"Reports ({len(completed)} completed runs)")
    table.add_column("#", style="dim", width=4)
    table.add_column("When", width=16)
    table.add_column("Cost", width=10)
    table.add_column("Objective", width=70)

    for i, r in enumerate(completed, 1):
        table.add_row(
            str(i),
            str(r.get("created_at", ""))[:16],
            f"${r.get('total_cost_usd', 0):.4f}",
            str(r.get("objective_statement", ""))[:70],
        )

    console.print(table)
    console.print("\n[dim]Use: mc.py report --run N  to view a report[/dim]")


async def show_report(api: CliApiClient, mission_id: str, run: int | None) -> None:
    """Show the research report from the latest (or specified) run."""
    console = get_console()

    # Get executions and filter by mission
    execs = await api.get("/executions", params={"limit": 50})
    all_records = execs.get("executions", [])
    completed = [
        r for r in all_records
        if r.get("status") == "completed" and r.get("mission_id") == mission_id
    ]

    if not completed:
        console.print("[dim]No completed runs found.[/dim]")
        return

    if run is not None:
        if run < 1 or run > len(completed):
            console.print(f"[red]Run #{run} not found. Available: 1-{len(completed)}[/red]")
            return
        target = completed[run - 1]
    else:
        target = completed[0]

    eid = target["id"]
    detail = await api.get(f"/executions/{eid}")
    tasks = detail.get("task_executions", [])

    # Find synthesizer output (the report)
    report_task = None
    search_task = None
    for t in tasks:
        agent = t.get("agent_name", "")
        if "synthesizer" in agent:
            report_task = t
        elif "searcher" in agent:
            search_task = t

    obj = target.get("objective_statement", "")
    console.print(f"\n[bold]Run:[/bold] {eid[:12]}  [dim]{target.get('created_at', '')[:16]}[/dim]")
    console.print(f"[bold]Objective:[/bold] {obj}")
    console.print(f"[bold]Cost:[/bold] ${target.get('total_cost_usd', 0):.4f}\n")

    if report_task:
        out = report_task.get("output_data") or {}
        title = out.get("title", "Research Report")
        summary = out.get("executive_summary", "")
        sections = out.get("sections", [])
        sources = out.get("sources", [])
        report_md = out.get("report_markdown", "")

        console.print(f"[bold cyan]# {title}[/bold cyan]\n")

        if summary:
            console.print(f"[bold]Executive Summary[/bold]\n{summary}\n")

        if report_md:
            from rich.markdown import Markdown
            console.print(Markdown(report_md))
        elif sections:
            for sec in sections:
                heading = sec.get("heading", sec.get("title", ""))
                body = sec.get("content", sec.get("body", ""))
                console.print(f"\n[bold]## {heading}[/bold]\n{body}")

        if sources:
            console.print(f"\n[bold]Sources ({len(sources)})[/bold]")
            for s in sources[:10]:
                url = s.get("url", "")
                title = s.get("title", url)
                console.print(f"  • {title}")
                if url and url != title:
                    console.print(f"    [dim]{url}[/dim]")
    elif search_task:
        # No synthesizer — show raw search findings
        out = search_task.get("output_data") or {}
        findings = out.get("findings", [])
        console.print(f"[bold]Search Findings ({len(findings)})[/bold]\n")
        for f in findings[:10]:
            claim = f.get("claim", "")
            evidence = f.get("evidence", "")
            console.print(f"  • {claim}")
            if evidence:
                console.print(f"    [dim]{evidence[:200]}[/dim]")
    else:
        console.print("[dim]No research output found in this run.[/dim]")


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
