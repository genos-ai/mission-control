"""
mc run / mc retry — API-based execution handlers for the user CLI.

Run objectives and workflows via the HTTP API. Streams plan progress
via SSE for real-time updates. Zero backend service imports.
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
    dry_run: bool,
    quiet: bool,
    verbose: bool,
    context_overrides: dict | None = None,
) -> None:
    """Run a workflow (if name matches) or an ad-hoc objective."""
    # Check if it's a workflow name
    workflows = await api.get("/workflows")
    workflow_list = extract_list(workflows, "workflows")
    matched = [
        w
        for w in workflow_list
        if w.get("name") == objective_or_workflow or w.get("workflow_name") == objective_or_workflow
    ]

    if matched:
        await _run_workflow(
            api,
            matched[0],
            mission_id=mission_id,
            dry_run=dry_run,
            verbose=verbose,
            context_overrides=context_overrides,
        )
    else:
        await _run_adhoc(
            api,
            objective_or_workflow,
            mission_id=mission_id,
            dry_run=dry_run,
            quiet=quiet,
            verbose=verbose,
        )


async def retry(
    api: CliApiClient,
    n: int,
    *,
    mission_id: str,
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
                f"/missions/{mission_id}/plan/dispatch",
            )

            outcome = result.get("outcome_status", "")
            if outcome in ("success", "failed"):
                console.print(
                    f"\n[bold]Retry complete:[/bold] {outcome}"
                    f" | ${result.get('total_cost_usd', 0):.4f}"
                )
            else:
                console.print(
                    f"Dispatched {len(failed_ids)} retried task(s). " f"Polling for progress...\n"
                )
                await _stream_plan_progress(api, mission_id, verbose=False, quiet=quiet)
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
        api,
        objective,
        mission_id=mission_id,
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
    dry_run: bool,
    verbose: bool,
    context_overrides: dict | None = None,
) -> None:
    """Execute a named workflow via API."""
    wf_name = workflow.get("name") or workflow.get("workflow_name", "")
    # The workflow seeder strips the .workflow suffix before storing in DB
    # (see services/workflow_seeder.py), so the run endpoint expects the
    # stripped form. GET /workflows returns workflow_name with the suffix.
    if wf_name.endswith(".workflow"):
        wf_name = wf_name[: -len(".workflow")]
    console = get_console()

    if dry_run:
        console.print(f"[bold]Dry run:[/bold] {wf_name}\n")
        steps = workflow.get("steps", [])
        console.print(f"  Steps: {len(steps)}")
        for step in steps:
            deps = (
                f" (after: {', '.join(step.get('depends_on', []))})"
                if step.get("depends_on")
                else ""
            )
            console.print(f"  {step.get('id', '')}: {step.get('capability', '')}{deps}")
        if context_overrides:
            console.print(f"\n  Context: {context_overrides}")
        console.print("\n[dim]Run without --dry-run to execute.[/dim]")
        return

    console.print(f"[bold]Running workflow:[/bold] {wf_name}\n")

    body: dict = {"triggered_by": "user:cli"}
    if context_overrides:
        body["context_overrides"] = context_overrides

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
    dry_run: bool,
    quiet: bool,
    verbose: bool,
) -> None:
    """Start a mission run for an ad-hoc objective (POST /missions/{id}/runs).

    Gate mode is a plan setting; per-run caps arrive in Plan 88 step 88.4.1.
    Progress is streamed via SSE with polling fallback.
    """
    console = get_console()

    if dry_run:
        console.print(f"[bold]Dry run:[/bold] {objective}\n")
        console.print(f"  Mission: {mission_id}")
        console.print("\n[dim]Run without --dry-run to execute.[/dim]")
        return

    console.print(f"[bold]Running:[/bold] {objective}\n")

    result = await api.post(f"/missions/{mission_id}/runs", body={"objective": objective})

    if verbose:
        print(json.dumps(result, default=str, indent=2), flush=True)

    # Endpoint returns immediately — planning and execution run in Temporal.
    # Stream progress via SSE until all tasks complete.
    console.print(f"[green]Run #{result.get('sequence')} started[/green]")
    console.print("Streaming progress...\n")
    await _stream_plan_progress(api, mission_id, verbose=verbose, quiet=quiet)


async def _stream_plan_progress(
    api: CliApiClient,
    mission_id: str,
    verbose: bool = False,
    quiet: bool = False,
) -> None:
    """Stream plan progress via SSE for real-time task updates.

    Falls back to REST polling if the SSE connection fails (e.g. when
    the SSE token exchange endpoint is unavailable).
    """
    try:
        await _stream_plan_sse(api, mission_id, verbose=verbose, quiet=quiet)
    except Exception as exc:
        # SSE unavailable — fall back to polling
        get_console().print(
            f"[dim yellow]SSE unavailable ({exc}), falling back to polling...[/dim yellow]"
        )
        await _poll_plan_fallback(api, mission_id, verbose=verbose, quiet=quiet)


async def _stream_plan_sse(
    api: CliApiClient,
    mission_id: str,
    verbose: bool = False,
    quiet: bool = False,
) -> None:
    """Stream plan progress via SSE — real-time, no polling."""
    console = get_console()

    # SSE token exchange (same pattern as mc console monitor)
    sse_token_data = await api.post("/auth/sse-token")
    sse_token = sse_token_data.get("token", "")

    task_statuses: dict[str, str] = {}  # step_id → latest status
    total_cost: float = 0.0
    terminal = {"completed", "failed", "cancelled"}

    # SSE wire format after format_event_for_sse():
    #   {event_type, category, timestamp, source, data: {step_id, ...}}
    async for sse in api.stream_sse(
        "GET",
        f"/streams/missions/{mission_id}",
        params={"token": sse_token},
    ):
        payload = sse.get("data", {})
        evt = payload.get("event_type", "")
        d = payload.get("data", {})

        if verbose:
            if evt and evt != "connected":
                print(json.dumps(payload, default=str)[:300], flush=True)

        if evt == "plan.step.started":
            tid = d.get("step_id", "")
            if tid:
                task_statuses[tid] = "running"
                if not quiet:
                    name = d.get("step_name", tid)
                    console.print(f"  {STATUS_ICONS['running']} {name} running...")

        elif evt == "plan.step.completed":
            tid = d.get("step_id", "")
            status = d.get("status", "completed")
            if tid:
                task_statuses[tid] = status if status in terminal else "completed"
                if not quiet:
                    console.print(
                        f"  {STATUS_ICONS.get('completed', chr(0x2713))} " f"{tid} {status}"
                    )

        elif evt == "plan.step.failed":
            tid = d.get("step_id", "")
            reason = d.get("result_summary", "")[:60]
            if tid:
                task_statuses[tid] = "failed"
                if not quiet:
                    console.print(
                        f"  {STATUS_ICONS.get('failed', chr(0x2717))} " f"{tid} failed: {reason}"
                    )

        elif evt == "mission_plan.supervisor_decision":
            action = d.get("action", "")
            if not quiet:
                reason = d.get("reason", "")[:80]
                console.print(
                    f"  [dim]{STATUS_ICONS.get('running', chr(0x00b7))} "
                    f"supervisor: {action}"
                    f"{' — ' + reason if reason else ''}[/dim]"
                )
            if action in ("propose_complete", "escalate"):
                break

        # After any task state change, check if all tracked tasks are done
        if task_statuses and all(s in terminal for s in task_statuses.values()):
            # Confirm via API — SSE events might not cover all tasks
            # (e.g. tasks that were already completed before we connected)
            plan = await api.get(f"/missions/{mission_id}/plan")
            plan_states = plan.get("task_states", [])
            all_done = plan_states and all(ts.get("status", "") in terminal for ts in plan_states)
            if all_done:
                cost = plan.get("total_spent_usd", total_cost)
                completed = sum(1 for ts in plan_states if ts.get("status") == "completed")
                failed_count = sum(1 for ts in plan_states if ts.get("status") == "failed")
                label = "success" if failed_count == 0 else "failed"
                console.print(
                    f"\n[bold]Plan complete:[/bold] {label}"
                    f" | {completed}/{len(plan_states)} succeeded"
                    f" | ${cost:.4f}"
                )
                return


async def _poll_plan_fallback(
    api: CliApiClient,
    mission_id: str,
    verbose: bool = False,
    quiet: bool = False,
    *,
    poll_interval: float = 3.0,
    max_iterations: int = 300,
) -> None:
    """Fallback: poll the plan endpoint until all tasks reach a terminal state."""
    console = get_console()
    terminal = {"completed", "failed", "cancelled"}
    seen_running: set[str] = set()

    for _ in range(max_iterations):
        await asyncio.sleep(poll_interval)

        plan = await api.get(f"/missions/{mission_id}/plan")
        task_states = plan.get("task_states", [])

        if not task_states:
            continue

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

        all_terminal = all(ts.get("status", "") in terminal for ts in task_states)
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

    console.print("[yellow]Timed out. Run 'mc status' to check progress.[/yellow]")
