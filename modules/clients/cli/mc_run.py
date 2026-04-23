"""
mc run / mc retry — API-based execution handlers for the user CLI.

Run objectives and workflows via the HTTP API. Polls plan status for
live progress display. Zero backend service imports.
"""

import asyncio
import json
import sys

import click

from modules.clients.cli.api_client import ApiError, CliApiClient, extract_list
from modules.clients.common.display import get_console
from modules.clients.common.gate_helpers import STATUS_ICONS


async def run(
    api: CliApiClient,
    objective_or_workflow: str,
    *,
    mission_id: str,
    budget: float | None,
    gate_override: str | None,
    dry_run: bool,
    quiet: bool,
    verbose: bool,
) -> None:
    """Run a workflow (if name matches) or an ad-hoc objective."""
    # Check if it's a workflow name
    workflows = await api.get("/workflows")
    workflow_list = extract_list(workflows, "workflows")
    matched = [
        w for w in workflow_list
        if w.get("name") == objective_or_workflow
        or w.get("workflow_name") == objective_or_workflow
    ]

    if matched:
        await _run_workflow(
            api, matched[0],
            mission_id=mission_id,
            budget=budget,
            gate_override=gate_override,
            dry_run=dry_run,
            verbose=verbose,
        )
    else:
        await _run_adhoc(
            api, objective_or_workflow,
            mission_id=mission_id,
            budget=budget,
            gate_override=gate_override,
            dry_run=dry_run,
            quiet=quiet,
            verbose=verbose,
        )


async def retry(
    api: CliApiClient,
    n: int,
    *,
    mission_id: str,
    gate_override: str | None,
    quiet: bool = False,
    verbose: bool = False,
) -> None:
    """Retry failed tasks in the plan, or re-run the Nth recent objective."""
    console = get_console()

    # Check for failed tasks in current plan
    plan = None
    try:
        plan = await api.get(f"/missions/{mission_id}/plan")
    except ApiError as exc:
        if exc.status != 404:
            console.print(f"[dim yellow]Could not load plan: {exc.message}[/dim yellow]")

    if plan:
        task_states = plan.get("task_states", [])
        failed = [ts for ts in task_states if ts.get("status") == "failed"]

        if failed:
            failed_ids = [ts["task_id"] for ts in failed]
            console.print(
                f"[bold]Retrying {len(failed_ids)} failed task(s):[/bold] "
                f"{', '.join(failed_ids)}"
            )

            # Retry each failed task then dispatch via Temporal
            for ts in failed:
                await api.post(
                    f"/missions/{mission_id}/plan/tasks/{ts['task_id']}/retry",
                )

            result = await api.post(
                f"/missions/{mission_id}/plan/dispatch?autonomous=true",
            )

            outcome = result.get("outcome_status", "")
            if outcome in ("success", "failed"):
                console.print(
                    f"\n[bold]Retry complete:[/bold] {outcome}"
                    f" | ${result.get('total_cost_usd', 0):.4f}"
                )
            else:
                console.print(
                    f"Dispatched {len(failed_ids)} retried task(s). "
                    f"Polling for progress...\n"
                )
                await _poll_plan(api, mission_id, verbose=False, quiet=quiet)
            return

    # Fallback: re-run the Nth most recent objective
    exec_data = await api.get(
        "/executions",
        params={"mission_id": mission_id, "limit": n},
    )
    executions = extract_list(exec_data, "executions")

    if len(executions) < n:
        click.echo(f"Only {len(executions)} runs in history.")
        sys.exit(1)

    original = executions[n - 1]
    objective = original.get("objective") or original.get("objective_statement", "")
    await _run_adhoc(
        api, objective,
        mission_id=mission_id,
        budget=original.get("cost_ceiling_usd"),
        gate_override=gate_override,
        dry_run=False,
        quiet=quiet,
        verbose=verbose,
    )


# =============================================================================
# Internal
# =============================================================================


async def _run_workflow(
    api: CliApiClient,
    workflow: dict,
    *,
    mission_id: str,
    budget: float | None,
    gate_override: str | None,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Execute a named workflow via API."""
    wf_name = workflow.get("name") or workflow.get("workflow_name", "")
    console = get_console()

    if dry_run:
        console.print(f"[bold]Dry run:[/bold] {wf_name}\n")
        steps = workflow.get("steps", [])
        console.print(f"  Steps: {len(steps)}")
        for step in steps:
            deps = f" (after: {', '.join(step.get('depends_on', []))})" if step.get("depends_on") else ""
            console.print(f"  {step.get('id', '')}: {step.get('capability', '')}{deps}")
        console.print(f"\n[dim]Run without --dry-run to execute.[/dim]")
        return

    console.print(f"[bold]Running workflow:[/bold] {wf_name}\n")

    body: dict = {"triggered_by": "user:cli"}
    if gate_override:
        body["gate_mode"] = gate_override
    if budget is not None:
        body["budget_ceiling_usd"] = budget

    result = await api.post(
        f"/missions/{mission_id}/workflows/{wf_name}/run",
        body=body,
    )

    if verbose:
        print(json.dumps(result, default=str, indent=2), flush=True)
    else:
        console.print(f"[bold]Workflow dispatched:[/bold] {result.get('status', 'unknown')}")
        if result.get("id"):
            console.print(f"  Run ID: {result['id']}")
        console.print("[dim]Run 'mc status' for progress.[/dim]")


async def _run_adhoc(
    api: CliApiClient,
    objective: str,
    *,
    mission_id: str,
    budget: float | None,
    gate_override: str | None,
    dry_run: bool,
    quiet: bool,
    verbose: bool,
) -> None:
    """Execute an ad-hoc objective via the plan path.

    Uses async_dispatch=true then polls the plan endpoint for progress,
    avoiding HTTP timeout issues with long-running sync dispatch.
    """
    console = get_console()

    if dry_run:
        console.print(f"[bold]Dry run:[/bold] {objective}\n")
        console.print(f"  Mission: {mission_id}")
        if budget:
            console.print(f"  Budget: ${budget:.2f}")
        console.print(f"\n[dim]Run without --dry-run to execute.[/dim]")
        return

    console.print(f"[bold]Running:[/bold] {objective}\n")

    body: dict = {
        "objective": objective,
        "async_dispatch": True,
    }
    if gate_override:
        body["gate_mode"] = gate_override
    if budget is not None:
        body["budget_ceiling_usd"] = budget

    result = await api.post(
        f"/missions/{mission_id}/plan/run-objective",
        body=body,
    )

    task_count = result.get("task_count", 0)
    outcome = result.get("outcome_status", "")

    if verbose:
        print(json.dumps(result, default=str, indent=2), flush=True)
        if outcome not in ("success", "failed", "awaiting_approval"):
            await _poll_plan(api, mission_id, verbose=True)
        return

    if outcome in ("success", "failed"):
        _render_summary(console, result)
        return

    if outcome == "awaiting_approval":
        console.print(
            f"[bold]Plan created:[/bold] {task_count} task(s) awaiting approval"
        )
        console.print("[dim]Approve via the web UI or API.[/dim]")
        return

    # Dispatching — poll for completion
    console.print(f"Dispatched {task_count} task(s). Polling for progress...\n")
    await _poll_plan(api, mission_id, verbose=False, quiet=quiet)


async def _poll_plan(
    api: CliApiClient,
    mission_id: str,
    verbose: bool = False,
    quiet: bool = False,
    *,
    poll_interval: float = 3.0,
    max_iterations: int = 300,
) -> None:
    """Poll the plan endpoint until all tasks reach a terminal state.

    Args:
        poll_interval: Seconds between polls (default 3.0, matches
            application.yaml cli.plan_poll_interval_seconds).
        max_iterations: Maximum poll iterations before timeout (default 300,
            matches application.yaml cli.plan_poll_max_iterations).
    """
    console = get_console()
    terminal = {"completed", "failed", "cancelled"}
    seen_running: set[str] = set()

    for _ in range(max_iterations):
        await asyncio.sleep(poll_interval)

        plan = await api.get(f"/missions/{mission_id}/plan")
        task_states = plan.get("task_states", [])

        if not task_states:
            continue

        # Show progress for newly running/completed tasks
        if not quiet:
            for ts in task_states:
                tid = ts.get("task_id", "")
                status = ts.get("status", "")
                if status == "running" and tid not in seen_running:
                    seen_running.add(tid)
                    console.print(f"  {STATUS_ICONS['running']} {tid} running...")
                elif status in terminal and tid in seen_running:
                    seen_running.discard(tid)
                    icon = STATUS_ICONS.get(status, "\u00b7")
                    cost = f"${ts.get('cost_usd', 0):.4f}"
                    console.print(f"  {icon} {tid} {status} {cost}")

        # Check if all terminal
        all_terminal = all(
            ts.get("status", "") in terminal
            for ts in task_states
        )
        if all_terminal:
            cost = plan.get("total_spent_usd", 0)
            completed = sum(1 for ts in task_states if ts.get("status") == "completed")
            failed = sum(1 for ts in task_states if ts.get("status") == "failed")
            status_label = "success" if failed == 0 else "failed"
            console.print(
                f"\n[bold]Plan complete:[/bold] {status_label}"
                f" | {completed}/{len(task_states)} succeeded"
                f" | ${cost:.4f}"
            )
            return

    console.print("[yellow]Polling timed out. Run 'mc status' to check progress.[/yellow]")


def _render_summary(console, result: dict) -> None:
    """Render post-dispatch summary."""
    status = result.get("outcome_status", "unknown")
    cost = result.get("total_cost_usd", 0)
    task_count = result.get("task_count", 0)
    dispatched = result.get("dispatched_task_ids", [])

    console.print(f"\n[bold]Plan dispatch complete:[/bold] {status}")
    console.print(f"  Tasks: {len(dispatched)}/{task_count} dispatched")
    console.print(f"  Cost: ${cost:.4f}")
    console.print("[dim]Run 'mc status' for full task breakdown.[/dim]")
