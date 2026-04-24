"""
mc trace — Temporal workflow execution tracer.

Queries Temporal workflow history and displays a timeline of activity
starts, completions, and failures. Combined with TRACE log entries,
this pinpoints exactly where execution hangs.
"""

from __future__ import annotations

from google.protobuf.json_format import MessageToDict


async def trace_workflow(workflow_id: str, verbose: bool = False) -> None:
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

    # Query loop status if available
    try:
        loop_status = await handle.query("get_loop_status")
        console.print(
            f"[bold]Loop:[/bold] iteration={loop_status.get('iteration')}, "
            f"cost=${loop_status.get('total_cost', 0):.4f}, "
            f"last_action={loop_status.get('last_action', '')}"
        )
    except Exception:
        pass

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
            console.print(
                f"  [dim]{elapsed}[/dim]  [green]COMPLETED[/green]  {activity_type}"
            )

        elif et == "EVENT_TYPE_ACTIVITY_TASK_FAILED":
            attrs = d.get("activityTaskFailedEventAttributes", {})
            sched_id = str(attrs.get("scheduledEventId", ""))
            activity_type = activities.get(sched_id, "?")
            failure = attrs.get("failure", {})
            msg = failure.get("message", "")[:200]
            elapsed = _elapsed_from_str(start_ts, ts)
            console.print(
                f"  [dim]{elapsed}[/dim]  [red]FAILED[/red]     {activity_type}"
            )
            if msg:
                console.print(f"               [red]{msg}[/red]")

        elif et == "EVENT_TYPE_ACTIVITY_TASK_TIMED_OUT":
            attrs = d.get("activityTaskTimedOutEventAttributes", {})
            sched_id = str(attrs.get("scheduledEventId", ""))
            activity_type = activities.get(sched_id, "?")
            elapsed = _elapsed_from_str(start_ts, ts)
            console.print(
                f"  [dim]{elapsed}[/dim]  [red]TIMED_OUT[/red]  {activity_type}"
            )

        elif et == "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED":
            elapsed = _elapsed_from_str(start_ts, ts)
            console.print(
                f"  [dim]{elapsed}[/dim]  [bold green]WORKFLOW_COMPLETED[/bold green]"
            )

        elif et == "EVENT_TYPE_WORKFLOW_EXECUTION_FAILED":
            attrs = d.get("workflowExecutionFailedEventAttributes", {})
            failure = attrs.get("failure", {})
            msg = failure.get("message", "")[:300]
            elapsed = _elapsed_from_str(start_ts, ts)
            console.print(
                f"  [dim]{elapsed}[/dim]  [bold red]WORKFLOW_FAILED[/bold red]"
            )
            if msg:
                console.print(f"               [red]{msg}[/red]")

        elif verbose and "WORKFLOW" not in et and "TASK" not in et:
            elapsed = _elapsed_from_str(start_ts, ts)
            console.print(f"  [dim]{elapsed}[/dim]  [dim]{et}[/dim]")


def _elapsed_from_str(start, ts_str: str) -> str:
    """Format elapsed time from workflow start."""
    try:
        from datetime import datetime, timezone

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
