"""
mc status / mc history — API-based mission snapshot and execution history.

All operations go through the HTTP API. Zero backend service imports.
"""

import json
import sys

import click

from modules.clients.cli.api_client import ApiError, CliApiClient, extract_list
from modules.clients.common.display import build_table, get_console, styled_status
from modules.clients.common.gate_helpers import STATUS_ICONS


async def show_status(
    api: CliApiClient,
    mission_id: str,
    verbose: bool = False,
) -> None:
    """Show current mission snapshot: plan state, active runs, spend."""
    console = get_console()

    mission = await api.get(f"/missions/{mission_id}")

    # Fetch plan (may not exist yet)
    plan = None
    try:
        plan = await api.get(f"/missions/{mission_id}/plan")
    except ApiError as exc:
        if exc.status != 404:
            console.print(f"[dim yellow]Could not load plan: {exc.message}[/dim yellow]")

    # Fetch recent executions
    exec_data = await api.get(
        "/executions",
        params={"mission_id": mission_id, "limit": 10},
    )
    executions = extract_list(exec_data, "executions")
    total = (
        exec_data.get("total", len(executions)) if isinstance(exec_data, dict) else len(executions)
    )
    total_cost = sum(e.get("total_cost_usd", 0) for e in executions)
    budget = await api.get(f"/missions/{mission_id}/budget")

    if verbose:
        data = {
            "mission": {
                "id": mission["id"],
                "name": mission["name"],
                "description": mission.get("description", ""),
                "per_month_usd": budget["per_month_usd"],
                "month_spent_usd": budget["month_spent_usd"],
            },
            "total_runs": total,
            "total_cost_usd": total_cost,
            "executions": executions,
        }
        print(json.dumps(data, default=str, indent=2), flush=True)
        return

    budget_str = f"${budget['month_spent_usd']:.2f} this month of ${budget['per_month_usd']:.2f}"
    console.print(f"[bold]{mission['name']}[/bold]  Budget: {budget_str}")
    console.print(f"  {mission.get('description', '')}")
    console.print()

    # ── Plan state ────────────────────────────────────────────────
    if plan:
        task_states = plan.get("task_states", [])
        mission_status = mission["status"]
        if mission.get("paused_reason"):
            mission_status = f"{mission_status} ({mission['paused_reason']})"

        console.print(f"[bold]Plan[/bold] {mission_status}  v{plan.get('version', 1)}")

        for ts in sorted(task_states, key=lambda x: x.get("task_id", "")):
            status = ts.get("status", "")
            icon = STATUS_ICONS.get(status, "\u00b7")
            cost = f"${ts['cost_usd']:.4f}" if ts.get("cost_usd") else ""
            dur = f"{ts['duration_seconds']:.1f}s" if ts.get("duration_seconds") else ""
            meta = f"  [dim]{cost}  {dur}[/dim]" if cost or dur else ""
            fail = f"  [red]{ts['failure_reason'][:40]}[/red]" if ts.get("failure_reason") else ""
            console.print(f"  {icon} {ts.get('task_id', ''):12s} {status:12s}{meta}{fail}")
        console.print()

    # ── Active runs ───────────────────────────────────────────────
    running = [e for e in executions if e.get("status") == "running"]
    if running:
        console.print(f"[yellow bold]Active runs: {len(running)}[/yellow bold]")
        for e in running:
            obj = (e.get("objective") or e.get("objective_statement", ""))[:60]
            console.print(f"  {STATUS_ICONS['running']} {obj}")
        console.print()

    # ── Recent ────────────────────────────────────────────────────
    recent = executions[:5]
    if recent:
        console.print(f"[bold]Recent ({total} total)  |  Spend: ${total_cost:.4f}[/bold]")
        for e in recent:
            status = e.get("status", "")
            icon = STATUS_ICONS.get(status, "\u00b7")
            when = (e.get("created_at") or "")[:16].replace("T", " ")
            obj = (e.get("objective") or e.get("objective_statement") or "")[:50]
            console.print(
                f"  {icon} {obj}  " f"[dim]${e.get('total_cost_usd', 0):.4f}  {when}[/dim]"
            )
    else:
        console.print("[dim]No runs yet.[/dim]")


async def show_history(
    api: CliApiClient,
    n: int | None,
    mission_id: str,
    verbose: bool = False,
) -> None:
    """Show numbered run history, or detail for run #N."""
    if n is not None:
        await _show_detail(api, n, mission_id, verbose=verbose)
        return

    exec_data = await api.get(
        "/executions",
        params={"mission_id": mission_id, "limit": 20},
    )
    executions = extract_list(exec_data, "executions")
    total = (
        exec_data.get("total", len(executions)) if isinstance(exec_data, dict) else len(executions)
    )

    if verbose:
        print(
            json.dumps({"total": total, "executions": executions}, default=str, indent=2),
            flush=True,
        )
        return

    console = get_console()

    if not executions:
        console.print("[dim]No runs yet.[/dim]")
        return

    table = build_table(
        f"History ({total} total)",
        columns=[
            ("#", {"width": 4, "justify": "right"}),
            ("When", {"width": 14, "style": "dim"}),
            ("Status", {"width": 10}),
            ("Cost", {"width": 8, "justify": "right"}),
            ("What", {"ratio": 1}),
        ],
    )

    for i, e in enumerate(executions, 1):
        when = (e.get("created_at") or "\u2014")[:16].replace("T", " ")
        what = e.get("objective") or e.get("objective_statement", "")
        if not what:
            tc = e.get("task_count")
            what = f"{tc} task{'s' if tc != 1 else ''}" if tc else e.get("roster_name", "")
        table.add_row(
            str(i),
            when,
            styled_status(e.get("status", "")),
            f"${e.get('total_cost_usd', 0):.4f}",
            what[:60],
        )

    console.print(table)
    console.print("[dim]  mc history --run N for detail[/dim]")


async def _show_detail(
    api: CliApiClient,
    n: int,
    mission_id: str,
    verbose: bool = False,
) -> None:
    """Show detail for the Nth most recent execution."""
    exec_data = await api.get(
        "/executions",
        params={"mission_id": mission_id, "limit": n},
    )
    executions = extract_list(exec_data, "executions")

    if len(executions) < n:
        click.echo(f"Only {len(executions)} runs in history.")
        sys.exit(1)

    execution = executions[n - 1]
    exec_id = execution.get("id", "")

    # Fetch full detail
    detail = await api.get(f"/executions/{exec_id}")

    console = get_console()

    if verbose:
        print(json.dumps(detail, default=str, indent=2), flush=True)
        return

    obj = detail.get("objective") or detail.get("objective_statement") or f"Execution #{n}"
    console.print(f"[bold]{obj}[/bold]")
    console.print(f"  ID:     {detail.get('id', '')}")
    console.print(f"  Status: {detail.get('status', '')}")
    console.print(f"  Cost:   ${detail.get('total_cost_usd', 0):.4f}")
    console.print(f"  Start:  {detail.get('started_at', '')}")
    console.print(f"  End:    {detail.get('completed_at', '')}")

    tasks = detail.get("task_executions", [])
    if tasks:
        console.print(f"\n  [bold]Tasks ({len(tasks)}):[/bold]")
        for t in tasks:
            icon = STATUS_ICONS.get(t.get("status", ""), "\u00b7")
            console.print(
                f"    {icon} {t.get('agent_name', '')} " f"[dim]${t.get('cost_usd', 0):.4f}[/dim]"
            )
