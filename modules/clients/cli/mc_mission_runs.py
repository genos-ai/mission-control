"""Mission run CLI renderer (Plan 88 step 88.1.13, contracts 3.5.4).

`mc runs` lists and manages a mission's runs through the REST API only.
A run is addressed by its per-mission sequence number (`mc runs show 37`);
the API resolves digits to the run. Zero backend-service imports.
"""

from __future__ import annotations

from typing import Any

from modules.clients.cli.api_client import CliApiClient
from modules.clients.cli.report import build_table, get_console, primary_panel


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
    """Print the run's digest, or `No digest yet` when it has none.

    A summary panel, then outcomes, open items, decisions (omitted when empty)
    and context changes, then a metrics line with the generator.
    """
    detail = await api.get(f"/missions/{mission_id}/runs/{sequence}")
    digest = detail.get("digest")
    console = get_console()
    if digest is None:
        console.print("No digest yet")
        return
    run_sequence = detail.get("run", {}).get("sequence")
    console.print(primary_panel(content=digest.get("summary", ""), title=f"Run #{run_sequence}"))
    for title, columns, key, cells in _DIGEST_SECTIONS:
        items = digest.get(key) or []
        if not items and key == "decisions":
            continue
        table = build_table(title, columns=columns)
        for item in items:
            table.add_row(*cells(item))
        console.print(table)
    metrics = digest.get("metrics") or {}
    console.print(
        f"generator={digest.get('generator')}  "
        f"tasks={metrics.get('completed_task_count', 0)}/{metrics.get('task_count', 0)} completed, "
        f"{metrics.get('failed_task_count', 0)} failed  "
        f"iterations={metrics.get('iteration_count', 0)}  "
        f"duration={float(metrics.get('duration_seconds') or 0):.0f}s  "
        f"cost=${float(metrics.get('cost_usd') or 0):.4f}  "
        f"digest cost=${float(digest.get('generation_cost_usd') or 0):.4f}"
    )


_FLEX = {"ratio": 1, "no_wrap": False}
_DIGEST_SECTIONS: list[tuple[str, list[tuple[str, dict[str, Any]]], str, Any]] = [
    (
        "Outcomes",
        [
            ("Agent", {"style": "cyan", "width": 30}),
            ("Status", {"width": 10}),
            ("Headline", _FLEX),
            ("Artifacts", {"justify": "right", "width": 9}),
        ],
        "outcomes",
        lambda o: (
            o.get("agent", ""),
            o.get("status", ""),
            o.get("headline", ""),
            str(len(o.get("artifact_ids") or [])),
        ),
    ),
    (
        "Open items",
        [("Item", _FLEX), ("Task", {"style": "dim", "width": 36})],
        "open_items",
        lambda i: (i.get("text", ""), i.get("source_task_id") or ""),
    ),
    (
        "Decisions",
        [("Gate point", {"width": 14}), ("Action", {"width": 12}), ("Channel", _FLEX)],
        "decisions",
        lambda d: (d.get("gate_point") or "", d.get("action") or "", d.get("channel") or ""),
    ),
    (
        "Context changes",
        [
            ("Version", {"justify": "right", "width": 8}),
            ("Change", {"width": 10}),
            ("Path", _FLEX),
        ],
        "context_changes",
        lambda c: (str(c.get("version", "")), c.get("change_type", ""), c.get("path", "")),
    ),
]


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
