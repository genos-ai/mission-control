"""
mc status / mc history — mission snapshot and execution history.

Renders current mission state, active/recent runs, and detailed
execution views using shared report primitives.
"""

import json
import sys

import click

from modules.clients.cli.report import build_table, styled_status
from modules.clients.common.display import get_console


def _execution_to_dict(e) -> dict:
    """Convert an execution record to a plain dict for JSON output."""
    status_val = e.status.value if hasattr(e.status, "value") else str(e.status)
    return {
        "id": str(e.id),
        "objective": e.objective,
        "status": status_val,
        "cost_usd": e.total_cost_usd,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


async def show_status(mission_id: str, verbose: bool = False) -> None:
    """Show current mission snapshot: active runs, recent history, spend."""
    from modules.backend.services.execution import ExecutionService
    from modules.backend.services.mission import MissionService

    async with MissionService.factory() as svc:
        mission = await svc.get_mission(mission_id)

    async with ExecutionService.factory() as svc:
        executions, total = await svc.list_executions(
            mission_id=mission_id, limit=10,
        )

    total_cost = sum(e.total_cost_usd for e in executions)

    if verbose:
        data = {
            "mission": {
                "id": str(mission.id),
                "name": mission.name,
                "description": mission.description,
                "gate_mode": mission.gate_mode or "off",
                "budget_ceiling_usd": mission.budget_ceiling_usd,
            },
            "total_runs": total,
            "total_cost_usd": total_cost,
            "executions": [_execution_to_dict(e) for e in executions],
        }
        print(json.dumps(data, default=str, indent=2), flush=True)
        return

    console = get_console()

    gate_str = mission.gate_mode or "off"
    budget_str = (
        f"${mission.budget_ceiling_usd:.2f}"
        if mission.budget_ceiling_usd
        else "unlimited"
    )

    console.print(f"[bold]{mission.name}[/bold]  [{gate_str}]  Budget: {budget_str}")
    console.print(f"  {mission.description}")
    console.print()

    running = [
        e for e in executions
        if str(getattr(e.status, "value", e.status)) == "running"
    ]
    if running:
        console.print(f"[yellow bold]Active runs: {len(running)}[/yellow bold]")
        for e in running:
            console.print(f"  [yellow]\u25cf[/yellow] {e.objective[:60]}")
        console.print()

    recent = executions[:5]
    if recent:
        console.print(
            f"[bold]Recent ({total} total)  |  Spend: ${total_cost:.4f}[/bold]"
        )
        for e in recent:
            status_val = (
                e.status.value if hasattr(e.status, "value") else str(e.status)
            )
            icon = {
                "completed": "[green]\u2713[/green]",
                "failed": "[red]\u2717[/red]",
                "running": "[yellow]\u25cf[/yellow]",
            }.get(status_val, "\u00b7")
            when = (
                e.created_at.strftime("%m-%d %H:%M") if e.created_at else ""
            )
            console.print(
                f"  {icon} {e.objective[:50]}  "
                f"[dim]${e.total_cost_usd:.4f}  {when}[/dim]"
            )
    else:
        console.print("[dim]No runs yet.[/dim]")


async def show_history(
    n: int | None, mission_id: str, verbose: bool = False,
) -> None:
    """Show numbered run history, or detail for run #N."""
    if n is not None:
        await _show_detail(n, mission_id, verbose=verbose)
        return

    from modules.backend.services.execution import ExecutionService

    async with ExecutionService.factory() as svc:
        executions, total = await svc.list_executions(
            mission_id=mission_id, limit=20,
        )

    if verbose:
        data = {
            "total": total,
            "executions": [_execution_to_dict(e) for e in executions],
        }
        print(json.dumps(data, default=str, indent=2), flush=True)
        return

    console = get_console()

    if not executions:
        console.print("[dim]No runs yet.[/dim]")
        return

    table = build_table(f"History ({total} total)", columns=[
        ("#",      {"width": 4, "justify": "right"}),
        ("When",   {"width": 14, "style": "dim"}),
        ("Status", {"width": 10}),
        ("Cost",   {"width": 8, "justify": "right"}),
        ("What",   {"ratio": 1}),
    ])

    for i, e in enumerate(executions, 1):
        when = (
            e.created_at.strftime("%m-%d %H:%M") if e.created_at else "\u2014"
        )
        table.add_row(
            str(i), when, styled_status(e.status),
            f"${e.total_cost_usd:.4f}", e.objective[:60],
        )

    console.print(table)
    console.print(f"[dim]  mc history N for detail[/dim]")


async def _show_detail(n: int, mission_id: str, verbose: bool = False) -> None:
    """Show detail for the Nth most recent execution."""
    from modules.backend.services.execution import ExecutionService
    from modules.clients.cli.report import render_execution

    async with ExecutionService.factory() as svc:
        executions, _ = await svc.list_executions(
            mission_id=mission_id, limit=n,
        )

    if len(executions) < n:
        click.echo(f"Only {len(executions)} runs in history.")
        sys.exit(1)

    execution = executions[n - 1]
    await render_execution(execution, "jsonl" if verbose else "human")
