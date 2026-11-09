"""Mission run CLI renderer (Plan 88 step 88.1.13, contracts 3.5.4).

`mc runs` lists and manages a mission's runs through the REST API only.
A run is addressed by its per-mission sequence number (`mc runs show 37`);
the API resolves digits to the run. Zero backend-service imports.
"""

from __future__ import annotations

from typing import Any

from modules.clients.cli.api_client import CliApiClient
from modules.clients.cli.report import build_table, get_console


async def list_runs(
    api: CliApiClient,
    *,
    mission_id: str,
    statuses: list[str],
    limit: int,
) -> None:
    """Print the newest `limit` runs, optionally filtered by lowercase status values."""
    params: dict[str, Any] = {"limit": limit}
    if statuses:
        params["status"] = statuses
    data = await api.get(f"/missions/{mission_id}/runs", params=params)
    runs = data.get("runs", []) if isinstance(data, dict) else []
    console = get_console()
    if not runs:
        console.print("[dim]No runs. Start one with `mc runs start --objective TEXT`.[/dim]")
        return

    table = build_table(
        "Mission Runs",
        columns=[
            ("#", {"justify": "right", "style": "cyan", "width": 6}),
            ("Status", {"width": 14}),
            ("Trigger", {"width": 9}),
            ("Scheduled for", {"width": 19}),
            ("Started", {"width": 19}),
            ("Cost", {"justify": "right", "width": 9}),
            ("Objective", {"ratio": 1, "no_wrap": False}),
        ],
    )
    for run in runs:
        table.add_row(
            str(run.get("sequence", "")),
            _status(run),
            run.get("trigger") or "",
            (run.get("scheduled_for") or "")[:19],
            (run.get("started_at") or "")[:19],
            f"${float(run.get('cost_usd') or 0):.4f}",
            run.get("objective") or "",
        )
    console.print(table)
    if data.get("next_before_sequence") is not None:
        console.print("[dim]More runs exist; raise --limit to see them.[/dim]")


async def show_run(api: CliApiClient, *, mission_id: str, sequence: str) -> None:
    """Print one run with its tasks."""
    detail = await api.get(f"/missions/{mission_id}/runs/{sequence}")
    run = detail.get("run", {})
    console = get_console()
    console.print(
        f"[bold]Run #{run.get('sequence')}[/bold]  status=[cyan]{_status(run)}[/cyan]  "
        f"trigger={run.get('trigger')}  cost=${float(run.get('cost_usd') or 0):.4f}"
    )
    for label, key in (
        ("id", "id"),
        ("objective", "objective"),
        ("gate mode", "gate_mode"),
        ("scheduled for", "scheduled_for"),
        ("started", "started_at"),
        ("ended", "ended_at"),
        ("workflow id", "temporal_workflow_id"),
        ("detail", "status_detail"),
    ):
        if run.get(key):
            console.print(f"  {label + ':':15}{run[key]}")
    console.print(
        f"  {'tasks:':15}{run.get('task_count', 0)} total, "
        f"{run.get('completed_task_count', 0)} completed, "
        f"{run.get('failed_task_count', 0)} failed"
    )

    tasks = detail.get("tasks", [])
    if not tasks:
        return
    table = build_table(
        "Tasks",
        columns=[
            ("Agent", {"style": "cyan", "width": 30}),
            ("Status", {"width": 12}),
            ("Cost", {"justify": "right", "width": 9}),
            ("Description", {"ratio": 1, "no_wrap": False}),
        ],
    )
    for task in tasks:
        table.add_row(
            task.get("agent", ""),
            task.get("status", ""),
            f"${float(task.get('cost_usd') or 0):.4f}",
            task.get("failure_reason") or task.get("description", ""),
        )
    console.print(table)


async def show_digest(api: CliApiClient, *, mission_id: str, sequence: str) -> None:
    """Print the run's digest, or `No digest yet` when it has none."""
    detail = await api.get(f"/missions/{mission_id}/runs/{sequence}")
    digest = detail.get("digest")
    console = get_console()
    if digest is None:
        console.print("No digest yet")
        return
    console.print(f"[bold]Digest for run #{detail.get('run', {}).get('sequence')}[/bold]")
    console.print(digest.get("summary", ""))
    for label in ("outcomes", "decisions", "open_items", "context_changes"):
        items = digest.get(label) or []
        if items:
            console.print(f"\n[bold]{label.replace('_', ' ').capitalize()}:[/bold]")
            for item in items:
                console.print(f"  - {item}")


async def cancel_run(api: CliApiClient, *, mission_id: str, sequence: str) -> None:
    """Resolve the sequence to the run id, then request cancellation."""
    detail = await api.get(f"/missions/{mission_id}/runs/{sequence}")
    run_id = detail.get("run", {}).get("id")
    run = await api.post(f"/missions/{mission_id}/runs/{run_id}/cancel")
    get_console().print(
        f"[yellow]Run #{run.get('sequence')} cancel requested[/yellow]  " f"status={_status(run)}"
    )


async def start_run(api: CliApiClient, *, mission_id: str, objective: str) -> dict[str, Any]:
    """Start a manual run for the objective and print its sequence."""
    run = await api.post(f"/missions/{mission_id}/runs", body={"objective": objective})
    get_console().print(f"[green]Run #{run.get('sequence')} started[/green]")
    return run


def _status(run: dict[str, Any]) -> str:
    status = run.get("status") or ""
    reason = run.get("status_reason")
    return f"{status}/{reason}" if reason else status
