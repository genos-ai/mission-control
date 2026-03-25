"""
CLI handler for mission commands.

Thin renderer over MissionService. Handles create, list, detail, archive, use.
"""

import asyncio
import sys

from modules.clients.cli.mission_context import CLI_SERVICE_ACCOUNT_ID
from modules.clients.cli.report import get_console, build_table, DOTTED_ROWS, styled_status
from modules.clients.common.display import annotate_current_mission


def run_mission(
    cli_logger,
    action: str,
    *,
    name: str | None = None,
    mission_id: str | None = None,
    description: str | None = None,
    brief: str | None = None,
    owner_id: str = "system:cli",
    roster: str = "default",
    budget: float | None = None,
    repo_url: str | None = None,
    repo_root: str | None = None,
    output_format: str = "human",
) -> None:
    """Dispatch mission CLI actions."""
    actions = {
        "create": _action_create,
        "list": _action_list,
        "detail": _action_detail,
        "archive": _action_archive,
        "use": _action_use,
        "clear-mission": _action_clear_mission,
        "context-show": _action_context_show,
        "context-history": _action_context_history,
        "summarize": _action_summarize,
    }
    fn = actions.get(action)
    if not fn:
        get_console().print(f"[red]Unknown action: {action}[/red]")
        sys.exit(1)

    asyncio.run(fn(
        cli_logger,
        name=name,
        mission_id=mission_id,
        description=description,
        brief=brief,
        owner_id=owner_id,
        roster=roster,
        budget=budget,
        repo_url=repo_url,
        repo_root=repo_root,
        output_format=output_format,
    ))


async def _action_create(cli_logger, *, name, description, brief, owner_id, roster, budget, repo_url, repo_root, **_):
    """Create a new mission."""
    from modules.backend.services.mission import MissionService

    console = get_console()
    if not name:
        console.print("[red]--name is required[/red]")
        sys.exit(1)
    if not description:
        console.print("[red]--description is required[/red]")
        sys.exit(1)

    async with MissionService.factory() as svc:
        mission = await svc.create_mission(
            name=name,
            description=description,
            brief=brief,
            owner_id=owner_id,
            default_roster=roster,
            budget_ceiling_usd=budget,
            repo_url=repo_url,
            repo_root=repo_root,
        )
    console.print(f"[green]Mission created:[/green] {mission.id}")
    console.print(f"  Name: {mission.name}")
    console.print(f"  Owner: {mission.owner_id}")


async def _action_list(cli_logger, *, output_format, **_):
    """List all active missions."""
    from modules.backend.services.mission import MissionService
    from modules.clients.cli.mission_context import _async_resolve_current_mission_id

    console = get_console()

    current_mission_id = await _async_resolve_current_mission_id()

    async with MissionService.factory() as svc:
        missions = await svc.list_missions()

    if not missions:
        console.print("[dim]No missions found.[/dim]")
        return

    table = build_table("Missions", columns=[
        ("Status", {"width": 10}),
        ("Name", {"style": "cyan", "width": 32}),
        ("ID", {"width": 38}),
        ("Roster", {"width": 15}),
        ("Description", {"ratio": 1}),
    ], show_lines=True, table_box=DOTTED_ROWS)
    for m in missions:
        desc = m.description[:60] + "..." if len(m.description or "") > 60 else (m.description or "")
        name = annotate_current_mission(m.name, m.id, current_mission_id)
        table.add_row(styled_status(m.status), name, m.id, m.default_roster, desc)

    console.print(table)

    if current_mission_id:
        current = next((m for m in missions if m.id == current_mission_id), None)
        if current:
            console.print(f"\n\U0001f449 Current mission: [bold]{current.name}[/bold] ({current.id})")
    else:
        console.print("\n[dim]No current mission set. Use 'mission use <id>' to select one.[/dim]")


async def _action_detail(cli_logger, *, mission_id, name, output_format, **_):
    """Show mission details."""
    from modules.backend.services.mission import MissionService
    from modules.clients.cli.mission_context import async_require_mission_id

    console = get_console()
    if not mission_id and not name:
        mission_id = await async_require_mission_id(mission_id)

    async with MissionService.factory() as svc:
        if mission_id:
            mission = await svc.get_mission(mission_id)
        else:
            mission = await svc.get_mission_by_name(name)
            if not mission:
                console.print(f"[red]Mission not found: {name}[/red]")
                sys.exit(1)

    console.print(f"[bold]{mission.name}[/bold]  ({mission.status})")
    console.print(f"  ID:          {mission.id}")
    console.print(f"  Description: {mission.description}")
    if mission.brief:
        console.print(f"  Brief:       {mission.brief}")
    console.print(f"  Owner:       {mission.owner_id}")
    console.print(f"  Roster:      {mission.default_roster}")
    if mission.budget_ceiling_usd:
        console.print(f"  Budget:      ${mission.budget_ceiling_usd:.2f}")
    if mission.repo_url:
        console.print(f"  Repo:        {mission.repo_url}")

    # Show roster and agents
    from modules.backend.agents.mission_control.roster import load_roster
    try:
        roster = load_roster(mission.default_roster or "default")
        roster_name = mission.default_roster or "default"
        vertical_agents = [
            a for a in roster.agents if not a.agent_name.startswith("horizontal.")
        ]
        console.print(f"\n  [bold]Roster:[/bold] {roster_name}  ({len(vertical_agents)} agents)")
        for agent in vertical_agents:
            desc = agent.description.strip()[:60]
            if len(agent.description.strip()) > 60:
                desc += "..."
            console.print(f"    [cyan]{agent.agent_name}[/cyan]  v{agent.agent_version}")
            console.print(f"      {desc}")
    except FileNotFoundError:
        console.print(f"\n  [dim]Roster '{mission.default_roster}' not found.[/dim]")

    from modules.backend.services.workflow import WorkflowService
    workflow_svc = WorkflowService()
    try:
        workflow_svc.load_workflows()
    except Exception as e:
        cli_logger.debug("Could not load workflows: %s", e)
    mapped = [
        wf for wf in workflow_svc.list_workflows(enabled_only=False)
        if wf.mission_name and wf.mission_name == mission.name
    ]
    if mapped:
        console.print(f"\n  [bold]Workflows ({len(mapped)}):[/bold]")
        for wf in mapped:
            status = "[green]enabled[/green]" if wf.enabled else "[dim]disabled[/dim]"
            console.print(f"    {wf.workflow_name}  {status}")
    else:
        console.print(f"\n  [dim]No workflows mapped to this mission.[/dim]")


async def _action_archive(cli_logger, *, mission_id, **_):
    """Archive a mission."""
    from modules.backend.services.mission import MissionService
    from modules.clients.cli.mission_context import async_require_mission_id

    console = get_console()
    mission_id = await async_require_mission_id(mission_id)

    async with MissionService.factory() as svc:
        mission = await svc.archive_mission(mission_id)

    console.print(f"[yellow]Mission archived:[/yellow] {mission.name} ({mission.id})")


async def _action_use(cli_logger, *, mission_id, **_):
    """Set the current mission."""
    from modules.backend.services.user import UserService

    console = get_console()
    if not mission_id:
        console.print("[red]MISSION_ID is required[/red]")
        sys.exit(1)

    async with UserService.factory() as svc:
        cli_user = await svc.user_repo.get_by_id_or_none(CLI_SERVICE_ACCOUNT_ID)
        if cli_user is None:
            console.print("[red]CLI service account not found. Run 'admin bootstrap-user' first.[/red]")
            sys.exit(1)

        user = await svc.set_current_mission(
            user_id=CLI_SERVICE_ACCOUNT_ID,
            mission_id=mission_id,
            requesting_user=cli_user,
        )

    mission_name = user.current_mission.name if user.current_mission else mission_id
    console.print(f"\U0001f449 Current mission: [bold]{mission_name}[/bold] ({mission_id})")


async def _action_clear_mission(cli_logger, **_):
    """Clear the current mission selection."""
    from modules.backend.services.user import UserService

    console = get_console()

    async with UserService.factory() as svc:
        cli_user = await svc.user_repo.get_by_id_or_none(CLI_SERVICE_ACCOUNT_ID)
        if cli_user is None:
            console.print("[red]CLI service account not found.[/red]")
            sys.exit(1)

        await svc.set_current_mission(
            user_id=CLI_SERVICE_ACCOUNT_ID,
            mission_id=None,
            requesting_user=cli_user,
        )

    console.print("Current mission cleared.")


async def _action_context_show(cli_logger, *, mission_id, output_format, **_):
    """Show the MCD for a mission."""
    import json as _json
    from modules.backend.services.mission_context import MissionContextManager
    from modules.clients.cli.mission_context import async_require_mission_id

    console = get_console()
    mission_id = await async_require_mission_id(mission_id)

    async with MissionContextManager.factory() as mgr:
        data = await mgr.get_context(mission_id)
        size = await mgr.get_context_size(mission_id)

    if not data:
        console.print("[dim]No MCD found for this mission.[/dim]")
        return

    console.print(f"[bold]Mission Context Document[/bold]  (v{size['version']}, "
                  f"{size['size_characters']} chars, {size['pct_of_max']:.0f}% of cap)")
    console.print()
    console.print(_json.dumps(data, indent=2, ensure_ascii=False))


async def _action_context_history(cli_logger, *, mission_id, output_format, **_):
    """Show MCD change history."""
    from modules.backend.services.mission_context import MissionContextManager
    from modules.clients.cli.mission_context import async_require_mission_id

    console = get_console()
    mission_id = await async_require_mission_id(mission_id)

    async with MissionContextManager.factory() as mgr:
        changes = await mgr.get_history(mission_id, limit=20)

    if not changes:
        console.print("[dim]No changes recorded.[/dim]")
        return

    table = build_table("MCD Changes", columns=[
        ("Version", {"width": 8}),
        ("Type", {"width": 10}),
        ("Path", {"style": "cyan", "width": 40}),
        ("Agent", {"width": 25}),
        ("Reason", {"ratio": 1}),
    ])
    for c in changes:
        table.add_row(str(c.version), c.change_type, c.path,
                      c.agent_id or "—", c.reason[:60])

    console.print(table)


async def _action_summarize(cli_logger, *, mission_id, **_):
    """Run the summarization pipeline."""
    from modules.backend.services.summarization import SummarizationService
    from modules.clients.cli.mission_context import async_require_mission_id

    console = get_console()
    mission_id = await async_require_mission_id(mission_id)

    async with SummarizationService.factory() as svc:
        results = await svc.run_full_pipeline(mission_id)

    console.print("[bold]Summarization complete[/bold]")
    console.print(f"  Decisions archived:    {results['decisions_archived']}")
    console.print(f"  Executions summarized: {results['missions_summarized']}")
    console.print(f"  Milestones archived:   {results['milestones_archived']}")
