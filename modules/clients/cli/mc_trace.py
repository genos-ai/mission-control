"""
mc trace — Temporal workflow execution tracer.

Queries Temporal workflow history and displays a timeline of activity
starts, completions, and failures. Combined with TRACE log entries,
this pinpoints exactly where execution hangs.
"""

from __future__ import annotations

from google.protobuf.json_format import MessageToDict

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


async def trace_workflow(
    workflow_id: str,
    verbose: bool = False,
    detail: bool = False,
    mission_id: str | None = None,
) -> None:
    """Query Temporal workflow history and display activity timeline."""
    from modules.backend.temporal.client import get_temporal_client
    from modules.clients.common.display import get_console

    console = get_console()
    client = await get_temporal_client()

    try:
        handle = client.get_workflow_handle(workflow_id)
        desc = await handle.describe()
    except Exception as e:
        console.print(f"[red]Could not find workflow: {e}[/red]")
        return

    console.print(f"[bold]Workflow:[/bold] {workflow_id}")
    console.print(f"[bold]Type:[/bold] {desc.workflow_type}")
    console.print(f"[bold]Status:[/bold] {desc.status.name}")
    console.print(f"[bold]Started:[/bold] {desc.start_time}")
    if desc.close_time:
        console.print(f"[bold]Closed:[/bold] {desc.close_time}")

    # Query run state if available
    try:
        run_state = await handle.query("get_run_state")
        console.print(
            f"[bold]Run:[/bold] iteration={run_state.get('iteration')}, "
            f"phase={run_state.get('phase')}, "
            f"pending_gate_id={run_state.get('pending_gate_id')}, "
            f"last_supervisor_action={run_state.get('last_supervisor_action')}"
        )
    except Exception:
        logger.debug("get_run_state query not available for %s", workflow_id, exc_info=True)

    console.print()
    console.print("[bold underline]Activity Timeline[/bold underline]")
    console.print()

    start_ts = desc.start_time
    activities: dict[str, str] = {}  # scheduled_event_id -> activity_type

    async for event in handle.fetch_history_events():
        d = MessageToDict(event)
        et = d.get("eventType", "")
        ts = d.get("eventTime", "")

        if et == "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED":
            elapsed = _elapsed_from_str(start_ts, ts)
            console.print(f"  [dim]{elapsed}[/dim]  [bold]WORKFLOW_STARTED[/bold]")

        elif et == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED":
            attrs = d.get("activityTaskScheduledEventAttributes", {})
            activity_type = attrs.get("activityType", {}).get("name", "?")
            event_id = str(d.get("eventId", ""))
            activities[event_id] = activity_type
            elapsed = _elapsed_from_str(start_ts, ts)
            timeout = attrs.get("startToCloseTimeout", "")
            console.print(
                f"  [dim]{elapsed}[/dim]  [yellow]SCHEDULED[/yellow]  "
                f"{activity_type}  [dim](timeout: {timeout})[/dim]"
            )

        elif et == "EVENT_TYPE_ACTIVITY_TASK_STARTED":
            attrs = d.get("activityTaskStartedEventAttributes", {})
            sched_id = str(attrs.get("scheduledEventId", ""))
            activity_type = activities.get(sched_id, "?")
            elapsed = _elapsed_from_str(start_ts, ts)
            attempt = attrs.get("attempt", 1)
            console.print(
                f"  [dim]{elapsed}[/dim]  [cyan]STARTED[/cyan]    "
                f"{activity_type}  [dim](attempt {attempt})[/dim]"
            )

        elif et == "EVENT_TYPE_ACTIVITY_TASK_COMPLETED":
            attrs = d.get("activityTaskCompletedEventAttributes", {})
            sched_id = str(attrs.get("scheduledEventId", ""))
            activity_type = activities.get(sched_id, "?")
            elapsed = _elapsed_from_str(start_ts, ts)
            console.print(f"  [dim]{elapsed}[/dim]  [green]COMPLETED[/green]  {activity_type}")

        elif et == "EVENT_TYPE_ACTIVITY_TASK_FAILED":
            attrs = d.get("activityTaskFailedEventAttributes", {})
            sched_id = str(attrs.get("scheduledEventId", ""))
            activity_type = activities.get(sched_id, "?")
            failure = attrs.get("failure", {})
            msg = failure.get("message", "")[:200]
            elapsed = _elapsed_from_str(start_ts, ts)
            console.print(f"  [dim]{elapsed}[/dim]  [red]FAILED[/red]     {activity_type}")
            if msg:
                console.print(f"               [red]{msg}[/red]")

        elif et == "EVENT_TYPE_ACTIVITY_TASK_TIMED_OUT":
            attrs = d.get("activityTaskTimedOutEventAttributes", {})
            sched_id = str(attrs.get("scheduledEventId", ""))
            activity_type = activities.get(sched_id, "?")
            elapsed = _elapsed_from_str(start_ts, ts)
            console.print(f"  [dim]{elapsed}[/dim]  [red]TIMED_OUT[/red]  {activity_type}")

        elif et == "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED":
            elapsed = _elapsed_from_str(start_ts, ts)
            console.print(f"  [dim]{elapsed}[/dim]  [bold green]WORKFLOW_COMPLETED[/bold green]")

        elif et == "EVENT_TYPE_WORKFLOW_EXECUTION_FAILED":
            attrs = d.get("workflowExecutionFailedEventAttributes", {})
            failure = attrs.get("failure", {})
            msg = failure.get("message", "")[:300]
            elapsed = _elapsed_from_str(start_ts, ts)
            console.print(f"  [dim]{elapsed}[/dim]  [bold red]WORKFLOW_FAILED[/bold red]")
            if msg:
                console.print(f"               [red]{msg}[/red]")

        elif verbose and "WORKFLOW" not in et and "TASK" not in et:
            elapsed = _elapsed_from_str(start_ts, ts)
            console.print(f"  [dim]{elapsed}[/dim]  [dim]{et}[/dim]")

    # Summary
    console.print()
    # (activities dict stores type strings, not dicts — skip summary for now)

    # Research phase breakdown
    if detail and mission_id:
        await _show_research_phases(console, mission_id)


async def _show_research_phases(console, mission_id: str) -> None:
    """Query mission_events for research phase timings."""

    from sqlalchemy import text

    from modules.backend.core.database import get_async_session

    async with get_async_session() as db:
        result = await db.execute(
            text(
                "SELECT event_type, timestamp FROM mission_events "
                "WHERE mission_id = :mid AND event_type LIKE 'research.%' "
                "ORDER BY timestamp ASC"
            ),
            {"mid": mission_id},
        )
        rows = result.fetchall()

    if not rows:
        console.print("[dim]No research events found for phase breakdown.[/dim]")
        return

    console.print("[bold underline]Research Phase Breakdown[/bold underline]")
    console.print()

    # Group into runs (split on research.started)
    runs: list[list] = []
    current: list = []
    for row in rows:
        if row[0] == "research.started":
            if current:
                runs.append(current)
            current = [row]
        else:
            current.append(row)
    if current:
        runs.append(current)

    for run_idx, run_events in enumerate(runs):
        if len(runs) > 1:
            console.print(f"  [bold]Run {run_idx + 1}[/bold]")

        first_ts = _parse_ts(run_events[0][1])
        prev_ts = first_ts

        PHASE_LABELS = {
            "research.started": "Started",
            "research.decomposed": "Decompose",
            "research.search.completed": "Search round",
            "research.coverage.updated": "Analyze coverage",
            "research.synthesizing": "Synthesizing",
            "research.completed": "Completed",
            "research.failed": "FAILED",
        }

        for event_type, ts_raw in run_events:
            if event_type not in PHASE_LABELS:
                continue
            ts = _parse_ts(ts_raw)
            elapsed = (ts - first_ts).total_seconds()
            duration = (ts - prev_ts).total_seconds()
            m, s = int(elapsed) // 60, int(elapsed) % 60
            label = PHASE_LABELS[event_type]

            if duration >= 1.0:
                dur_str = (
                    f"{duration:.0f}s"
                    if duration < 60
                    else f"{int(duration) // 60}m{int(duration) % 60}s"
                )
                console.print(f"    [dim]{m:02d}:{s:02d}[/dim]  {label:20s}  [dim]+{dur_str}[/dim]")
            else:
                console.print(f"    [dim]{m:02d}:{s:02d}[/dim]  {label}")

            prev_ts = ts

        total = (prev_ts - first_ts).total_seconds()
        console.print(f"    [bold]Total: {int(total) // 60}m{int(total) % 60}s[/bold]")
        console.print()


def _parse_ts(ts):
    """Parse a timestamp that may be string or datetime."""
    from datetime import datetime

    if isinstance(ts, str):
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return ts


def _elapsed_from_str(start, ts_str: str) -> str:
    """Format elapsed time from workflow start."""
    try:
        from datetime import datetime

        if isinstance(ts_str, str) and ts_str:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        else:
            return "??:??"

        if hasattr(start, "timestamp"):
            delta = ts.timestamp() - start.timestamp()
        else:
            return "??:??"

        minutes = int(delta) // 60
        seconds = int(delta) % 60
        return f"{minutes:02d}:{seconds:02d}"
    except Exception:
        return "??:??"
