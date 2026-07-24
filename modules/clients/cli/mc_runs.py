"""Workflow-run lifecycle CLI (Plan 80h follow-up).

Surfaces the existing `/missions/{mid}/workflow-runs` endpoints + a new
cancel endpoint as user CLI commands. Distinct from `mc run` (verb,
starts a workflow) — `mc runs` is the noun (manage existing runs).

Commands:
    mc runs                  # default: list active workflow runs
    mc runs list [--all]     # list (active by default, --all = include terminal)
    mc runs show <id>        # detail
    mc runs cancel <id>      # mark as CANCELLED (for stale RUNNING orphans)
"""

from __future__ import annotations

from modules.clients.cli.api_client import ApiError, CliApiClient
from modules.clients.common.display import build_table, get_console

_TERMINAL_STATES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})


async def list_runs(
    api: CliApiClient,
    *,
    mission_id: str,
    include_terminal: bool = False,
) -> None:
    """Print workflow runs for this mission."""
    console = get_console()
    data = await api.get(f"/missions/{mission_id}/workflow-runs")
    runs = data.get("runs", []) if isinstance(data, dict) else []
    if not include_terminal:
        runs = [r for r in runs if (r.get("status") or "").lower() not in _TERMINAL_STATES]

    if not runs:
        console.print(
            "[dim]No active workflow runs.[/dim]"
            if not include_terminal
            else "[dim]No workflow runs.[/dim]"
        )
        return

    table = build_table(
        columns=[
            ("#", {"justify": "right", "width": 4}),
            ("ID", {"style": "cyan", "width": 38}),
            ("Status", {"width": 12}),
            ("Workflow", {"width": 40}),
            ("Started", {"width": 19}),
            ("Cost", {"justify": "right", "width": 8}),
        ]
    )
    for i, r in enumerate(runs, start=1):
        table.add_row(
            str(i),
            r.get("id", ""),
            (r.get("status") or "").lower(),
            (r.get("workflow_name") or "")[:40],
            (r.get("started_at") or "")[:19],
            f"${float(r.get('total_cost_usd') or 0):.4f}",
        )
    console.print(f"[bold]{len(runs)} run(s)[/bold]")
    console.print(table)


async def show_run(
    api: CliApiClient,
    *,
    mission_id: str,
    run_id: str,
) -> None:
    """Print detail for one workflow run."""
    console = get_console()
    data = await api.get(f"/missions/{mission_id}/workflow-runs/{run_id}")
    console.print(
        f"[bold]Run {data.get('id', '')}[/bold]  "
        f"status=[cyan]{(data.get('status') or '').lower()}[/cyan]  "
        f"workflow=[cyan]{data.get('workflow_name', '?')}[/cyan]  "
        f"cost=${float(data.get('total_cost_usd') or 0):.4f}"
    )
    console.print(f"  started:   {data.get('started_at', '')}")
    if data.get("completed_at"):
        console.print(f"  completed: {data['completed_at']}")
    if data.get("triggered_by"):
        console.print(f"  triggered_by: {data['triggered_by']}")
    if data.get("error_data"):
        console.print("\n[bold red]Error:[/bold red]")
        console.print(f"  {data['error_data']}")
    if data.get("result_summary"):
        console.print("\n[bold]Result:[/bold]")
        console.print(f"  {data['result_summary']}")


async def cancel_run(
    api: CliApiClient,
    *,
    mission_id: str,
    run_id: str,
) -> None:
    """Mark a workflow run as CANCELLED."""
    console = get_console()
    try:
        result = await api.post(
            f"/missions/{mission_id}/workflow-runs/{run_id}/cancel",
        )
    except ApiError as exc:
        console.print(f"[red]Failed to cancel:[/red] {exc.message}")
        return

    status = (result.get("status") or "").lower()
    if "message" in result:
        # Already terminal — endpoint returned a no-op message.
        console.print(f"[dim]{result['message']}[/dim] (status: {status})")
    else:
        console.print(f"[yellow]Cancelled[/yellow] run {result.get('id')}  status={status}")
