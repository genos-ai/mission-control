"""
CLI handler for workflow schedule commands.

Thin renderer over WorkflowScheduleService. Handles list, create, toggle, delete.
"""

import asyncio
import sys

from modules.backend.models.base import SYSTEM_CLI_ID
from modules.clients.cli.report import get_console, build_table, styled_status


def run_schedule(
    cli_logger,
    action: str,
    *,
    mission_id: str | None = None,
    schedule_id: str | None = None,
    workflow_definition_id: str | None = None,
    cron: str | None = None,
    description: str = "",
    budget: float | None = None,
    max_iterations: int | None = None,
    cooldown: int = 0,
    enabled: bool | None = None,
    output_format: str = "human",
) -> None:
    """Dispatch schedule CLI actions."""
    actions = {
        "list": _action_list,
        "create": _action_create,
        "enable": _action_toggle,
        "disable": _action_toggle,
        "delete": _action_delete,
    }
    fn = actions.get(action)
    if not fn:
        get_console().print(f"[red]Unknown action: {action}[/red]")
        sys.exit(1)

    asyncio.run(fn(
        cli_logger,
        mission_id=mission_id,
        schedule_id=schedule_id,
        workflow_definition_id=workflow_definition_id,
        cron=cron,
        description=description,
        budget=budget,
        max_iterations=max_iterations,
        cooldown=cooldown,
        enabled=True if action == "enable" else False if action == "disable" else enabled,
        output_format=output_format,
    ))


async def _action_list(cli_logger, *, mission_id, output_format, **_):
    """List schedules for a mission."""
    from modules.backend.services.workflow_schedule import WorkflowScheduleService

    console = get_console()
    if not mission_id:
        console.print("[red]--mission is required[/red]")
        sys.exit(1)

    async with WorkflowScheduleService.factory() as svc:
        schedules = await svc.list_by_mission(mission_id, enabled_only=False)

    if not schedules:
        console.print("[dim]No schedules found.[/dim]")
        return

    table = build_table("Workflow Schedules", columns=[
        ("Enabled", {"width": 9}),
        ("Cron", {"width": 20}),
        ("Workflow Def ID", {"width": 38}),
        ("Iterations", {"width": 12}),
        ("Next Fire", {"width": 22}),
        ("Description", {"ratio": 1}),
    ])
    for s in schedules:
        enabled = "[green]yes[/green]" if s.enabled else "[red]no[/red]"
        iters = f"{s.iteration_count}"
        if s.max_iterations:
            iters += f"/{s.max_iterations}"
        desc = s.description[:40] + "..." if len(s.description) > 40 else s.description
        table.add_row(
            enabled,
            s.cron_expression,
            s.workflow_definition_id,
            iters,
            s.next_fire_at or "—",
            desc,
        )

    console.print(table)


async def _action_create(
    cli_logger, *, mission_id, workflow_definition_id, cron, description,
    budget, max_iterations, cooldown, **_,
):
    """Create a new schedule."""
    from modules.backend.services.workflow_schedule import WorkflowScheduleService

    console = get_console()
    if not mission_id:
        console.print("[red]--mission is required[/red]")
        sys.exit(1)
    if not workflow_definition_id:
        console.print("[red]--workflow is required[/red]")
        sys.exit(1)
    if not cron:
        console.print("[red]--cron is required[/red]")
        sys.exit(1)

    async with WorkflowScheduleService.factory() as svc:
        schedule = await svc.create_schedule(
            workflow_definition_id=workflow_definition_id,
            mission_id=mission_id,
            cron_expression=cron,
            description=description,
            budget_per_run_usd=budget,
            max_iterations=max_iterations,
            cooldown_seconds=cooldown,
            created_by=SYSTEM_CLI_ID,
        )

    console.print(f"[green]Schedule created:[/green] {schedule.id}")
    console.print(f"  Cron:      {schedule.cron_expression}")
    console.print(f"  Next fire: {schedule.next_fire_at}")


async def _action_toggle(cli_logger, *, schedule_id, enabled, **_):
    """Enable or disable a schedule."""
    from modules.backend.services.workflow_schedule import WorkflowScheduleService

    console = get_console()
    if not schedule_id:
        console.print("[red]SCHEDULE_ID is required[/red]")
        sys.exit(1)

    async with WorkflowScheduleService.factory() as svc:
        schedule = await svc.toggle_enabled(schedule_id, enabled)

    state = "enabled" if schedule.enabled else "disabled"
    console.print(f"[green]Schedule {state}:[/green] {schedule.id}")


async def _action_delete(cli_logger, *, schedule_id, **_):
    """Delete a schedule."""
    from modules.backend.services.workflow_schedule import WorkflowScheduleService

    console = get_console()
    if not schedule_id:
        console.print("[red]SCHEDULE_ID is required[/red]")
        sys.exit(1)

    async with WorkflowScheduleService.factory() as svc:
        await svc.delete_schedule(schedule_id)

    console.print(f"[green]Schedule deleted:[/green] {schedule_id}")
