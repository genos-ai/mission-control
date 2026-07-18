"""Plan-level task operations (per-task approve / reject / retry / dispatch).

Thin client over /missions/{mid}/plan/* endpoints. Use when you want
fine-grained, one-task-at-a-time control over a workflow run rather
than dispatching the whole DAG and reacting to failures in bulk
(`mc retry` is the bulk variant).

Typical step-through loop:

    mc plan show
    mc plan approve --next
    mc plan dispatch
    # wait for the task to run, inspect with `mc plan show`
    # then approve the next one and repeat
"""

from __future__ import annotations

import sys
from typing import Any

import click

from modules.clients.cli.api_client import ApiError, CliApiClient, resolve_short_id
from modules.clients.common.display import build_table, get_console, styled_status

# =============================================================================
# Show
# =============================================================================


async def show(
    api: CliApiClient,
    *,
    mission_id: str,
    status_filter: str | None = None,
    show_deps: bool = False,
) -> None:
    """Print the plan's tasks as a status table."""
    console = get_console()

    try:
        plan = await api.get(f"/missions/{mission_id}/plan")
    except ApiError as exc:
        if exc.status == 404:
            console.print("[dim]No plan yet for this mission.[/dim]")
            return
        raise

    tasks = plan.get("tasks", [])
    if status_filter:
        tasks = [t for t in tasks if (t.get("status") or "").lower() == status_filter.lower()]

    if not tasks:
        if status_filter:
            console.print(f"[dim]No tasks with status='{status_filter}'.[/dim]")
        else:
            console.print("[dim]Plan has no tasks.[/dim]")
        return

    plan_status = plan.get("status", "?")
    gate_mode = plan.get("gate_mode") or "autonomous"
    spent = plan.get("total_spent_usd", 0.0) or 0.0
    ceiling = plan.get("budget_usd_ceiling")
    header = (
        f"Plan {plan.get('id', '')}  status={plan_status}  gate={gate_mode}  spent=${spent:.2f}"
    )
    if ceiling:
        header += f" / ${ceiling:.2f}"
    console.print(f"[bold]{header}[/bold]\n")

    columns = [
        ("#", {"justify": "right", "width": 4}),
        ("ID", {"style": "cyan", "width": 38}),
        ("Status", {"width": 11}),
        ("Agent", {"width": 38}),
        ("Cost", {"justify": "right", "width": 8}),
        ("Description", {"ratio": 1, "no_wrap": False}),
    ]
    if show_deps:
        columns.append(("Deps", {"ratio": 1, "no_wrap": False}))

    table = build_table(columns=columns)
    for i, t in enumerate(tasks, start=1):
        row = [
            str(i),
            t["id"],
            styled_status(t.get("status", "")),
            t.get("agent", "")[:38],
            f"${t.get('cost_usd', 0):.2f}",
            t.get("description") or "",
        ]
        if show_deps:
            deps = ", ".join(t.get("dependencies", []))
            row.append(deps or "[dim]—[/dim]")
        table.add_row(*row)
    console.print(table)


# =============================================================================
# Task detail — single-task view including instructions + failure_reason
# =============================================================================


async def task_detail(
    api: CliApiClient,
    *,
    mission_id: str,
    task_id: str,
) -> None:
    """Print full detail for one task: instructions, deps, result, failure reason."""
    console = get_console()
    resolved_id = await _resolve_task_id(api, mission_id, task_id)
    plan = await api.get(f"/missions/{mission_id}/plan")
    task = next((t for t in plan.get("tasks", []) if t["id"] == resolved_id), None)
    if task is None:
        console.print(f"[red]Task {resolved_id} not found in plan.[/red]")
        return

    status = (task.get("status") or "").lower()
    console.print(
        f"[bold]Task {resolved_id}[/bold]  "
        f"status=[cyan]{status}[/cyan]  "
        f"agent=[cyan]{task.get('agent', '?')}[/cyan]  "
        f"cost=${task.get('cost_usd', 0):.4f}  "
        f"duration={task.get('duration_seconds', 0):.1f}s"
    )
    if task.get("retry_count"):
        console.print(f"  [dim]retries: {task['retry_count']}[/dim]")
    if task.get("approved_at"):
        console.print(f"  [dim]approved: {task['approved_at']}[/dim]")
    console.print(f"\n[bold]Description:[/bold]")
    console.print(f"  {task.get('description') or '(none)'}")
    if task.get("instructions"):
        console.print(f"\n[bold]Instructions:[/bold]")
        console.print(f"  {task['instructions'][:2000]}")
        if len(task["instructions"]) > 2000:
            console.print(f"  [dim]... ({len(task['instructions'])} chars total)[/dim]")
    if task.get("dependencies"):
        console.print(f"\n[bold]Dependencies:[/bold]  {', '.join(task['dependencies'])}")
    if task.get("failure_reason"):
        console.print(f"\n[bold red]Failure reason:[/bold red]")
        console.print(f"  {task['failure_reason']}")
    if task.get("result_summary"):
        console.print(f"\n[bold]Result summary:[/bold]")
        console.print(f"  {task['result_summary'][:1000]}")


# =============================================================================
# Approve  (single task, or --next picks the topologically next ready one)
# =============================================================================


async def approve(
    api: CliApiClient,
    *,
    mission_id: str,
    task_id: str | None,
    pick_next: bool,
) -> None:
    """Approve one task (transitively also approves PROPOSED deps)."""
    console = get_console()

    if not task_id and not pick_next:
        console.print("[red]Provide TASK_ID or --next.[/red]")
        sys.exit(1)

    if pick_next:
        plan = await api.get(f"/missions/{mission_id}/plan")
        picked = _pick_next_ready_task(plan.get("tasks", []))
        if picked is None:
            console.print(
                "[dim]No PROPOSED tasks with all dependencies completed. "
                "Approve an upstream task first, or dispatch what's already approved.[/dim]"
            )
            return
        task_id = picked["id"]
        console.print(
            f"[bold]Next ready:[/bold] {task_id}  "
            f"[dim]{picked.get('agent', '')}[/dim]  "
            f"{(picked.get('description') or '')[:80]}"
        )

    resolved_id = await _resolve_task_id(api, mission_id, task_id)
    result = await api.post(f"/missions/{mission_id}/plan/tasks/{resolved_id}/approve")
    flipped = result.get("transitioned_task_ids", [])
    console.print(
        f"[green]Approved[/green] {resolved_id}"
        + (f" (+{len(flipped) - 1} transitive deps)" if len(flipped) > 1 else "")
    )


# =============================================================================
# Reject
# =============================================================================


async def reject(
    api: CliApiClient,
    *,
    mission_id: str,
    task_id: str | None,
    reject_all: bool = False,
) -> None:
    """Reject one task (transitively cancels dependents).

    With ``reject_all=True``, cancels every non-terminal task in the plan.
    Order doesn't matter — reject is idempotent and already-cancelled
    rows are no-ops, so repeated calls on overlapping dep chains are safe.
    """
    console = get_console()

    if reject_all:
        plan = await api.get(f"/missions/{mission_id}/plan")
        non_terminal = frozenset({"proposed", "approved", "queued", "running"})
        candidates = [
            t["id"]
            for t in plan.get("tasks", [])
            if (t.get("status") or "").lower() in non_terminal
        ]
        if not candidates:
            console.print("[dim]No non-terminal tasks to cancel.[/dim]")
            return
        console.print(f"[bold]Cancelling {len(candidates)} non-terminal task(s)...[/bold]")
        cancelled_total = 0
        for tid in candidates:
            try:
                result = await api.post(f"/missions/{mission_id}/plan/tasks/{tid}/reject")
                cancelled_total += len(result.get("transitioned_task_ids", []))
            except ApiError as exc:
                # Race: a previous transitive cancel already covered this id.
                # Skip and move on.
                console.print(f"  [dim]{tid}: {exc.message}[/dim]")
        console.print(f"[yellow]Cancelled[/yellow] {cancelled_total} task transition(s) total.")
        return

    if not task_id:
        console.print("[red]Provide TASK_ID or --all.[/red]")
        sys.exit(1)

    resolved_id = await _resolve_task_id(api, mission_id, task_id)
    result = await api.post(f"/missions/{mission_id}/plan/tasks/{resolved_id}/reject")
    cancelled = result.get("transitioned_task_ids", [])
    console.print(
        f"[yellow]Rejected[/yellow] {resolved_id}"
        + (
            f" (+{len(cancelled) - 1} transitive dependents cancelled)"
            if len(cancelled) > 1
            else ""
        )
    )


# =============================================================================
# Retry  (single-task variant; `mc retry` remains the bulk version)
# =============================================================================


async def retry_one(
    api: CliApiClient,
    *,
    mission_id: str,
    task_id: str,
) -> None:
    """Retry one FAILED task (flips it back to APPROVED, deps untouched)."""
    console = get_console()
    resolved_id = await _resolve_task_id(api, mission_id, task_id)
    await api.post(f"/missions/{mission_id}/plan/tasks/{resolved_id}/retry")
    console.print(
        f"[cyan]Retrying[/cyan] {resolved_id}  "
        f"[dim](status flipped FAILED → APPROVED; run `mc plan dispatch` to re-execute)[/dim]"
    )


# =============================================================================
# Dispatch
# =============================================================================


async def dispatch(
    api: CliApiClient,
    *,
    mission_id: str,
) -> None:
    """Start a Temporal MissionRunWorkflow for all APPROVED tasks."""
    console = get_console()
    result = await api.post(f"/missions/{mission_id}/plan/dispatch")
    wf_id = result.get("workflow_id") or result.get("run_id") or "(unknown)"
    approved = result.get("approved_count") or result.get("dispatched_count")
    if approved is not None:
        console.print(
            f"[green]Dispatched[/green] {approved} approved task(s) — workflow: [cyan]{wf_id}[/cyan]"
        )
    else:
        console.print(f"[green]Dispatched.[/green] Workflow: [cyan]{wf_id}[/cyan]")
    console.print("[dim]Watch progress with: mc console monitor[/dim]")


# =============================================================================
# Helpers
# =============================================================================


# Statuses that a dependency must be in for a PROPOSED child to be "ready".
# COMPLETED is the only one that has actually produced output; APPROVED /
# RUNNING means it's scheduled but not done. For "truly ready" we require
# all deps COMPLETED.
_DEP_DONE_STATUSES: frozenset[str] = frozenset({"completed"})


def _pick_next_ready_task(tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """First PROPOSED task whose dependencies are all COMPLETED.

    Walks ``tasks`` in their existing order (which the API returns in
    creation / topological order). No tie-breaker beyond that.
    """
    status_by_id = {t["id"]: (t.get("status") or "").lower() for t in tasks}
    for t in tasks:
        if (t.get("status") or "").lower() != "proposed":
            continue
        deps = t.get("dependencies", []) or []
        if all(status_by_id.get(d, "") in _DEP_DONE_STATUSES for d in deps):
            return t
    return None


async def _resolve_task_id(api: CliApiClient, mission_id: str, task_id: str) -> str:
    """Accept either a full UUID or a unique short prefix (>= 4 chars).

    Short prefixes match against the tasks table for this mission's plan.
    Fails loud on no match or ambiguous match.
    """
    return await resolve_short_id(
        api,
        list_url=f"/missions/{mission_id}/plan",
        list_field="tasks",
        prefix=task_id,
    )
