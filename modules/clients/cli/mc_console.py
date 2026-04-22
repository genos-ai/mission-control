"""
mc console monitor — live mission event stream via SSE.

Connects to GET /streams/missions/{mission_id} and renders events
in real-time, matching the web frontend's console view.
Zero backend service imports.
"""

import asyncio
import json

from modules.clients.cli.api_client import CliApiClient
from modules.clients.common.display import get_console
from modules.clients.common.gate_helpers import STATUS_ICONS


# Category colors matching the web frontend's console view
_CATEGORY_STYLES: dict[str, str] = {
    "execution": "cyan",
    "chat": "green",
    "system": "dim",
}

# Event types to suppress in the default (user) view
_SUPPRESS_USER_VIEW: set[str] = {
    "session.cost.updated",
    "agent.response.chunk",
}


async def monitor(
    api: CliApiClient,
    mission_id: str,
    view: str = "user",
    refresh: float = 2.0,
) -> None:
    """Live mission console — streams events from the API via SSE.

    Mirrors the web frontend's console view with real-time events
    classified into execution, chat, and system categories.
    """
    console = get_console()

    # Get mission name for the header
    mission = await api.get(f"/missions/{mission_id}")
    mission_name = mission.get("name", mission_id[:16])

    # Get SSE token (EventSource can't send headers)
    sse_token_data = await api.post("/auth/sse-token")
    sse_token = sse_token_data.get("token", "")

    console.print(
        f"[bold cyan]Console Monitor[/bold cyan] — {mission_name}"
        f"  [dim]({view} view)[/dim]"
    )
    console.print(f"[dim]Streaming events from {mission_id}[/dim]")
    console.print(f"[dim]Press Ctrl+C to stop.[/dim]\n")

    developer = view == "developer"

    try:
        async for sse in api.stream_sse(
            "GET",
            f"/streams/missions/{mission_id}",
            params={"token": sse_token},
        ):
            event_type = sse.get("event", "")
            data = sse.get("data", {})

            # The stream sends the connected event first
            if event_type == "connected":
                console.print("[green]Connected to event stream.[/green]\n")
                continue

            _render_console_event(console, data, developer=developer)

    except KeyboardInterrupt:
        console.print("\n[dim]Monitor stopped.[/dim]")
    except asyncio.CancelledError:
        console.print("\n[dim]Monitor stopped.[/dim]")


def _render_console_event(
    console, event: dict, developer: bool = False,
) -> None:
    """Render a single console event to the terminal.

    User view: shows key events with icons and colors.
    Developer view: shows all events with full data.
    """
    evt_type = event.get("event_type", "")
    category = event.get("category", "system")
    timestamp = (event.get("timestamp") or "")[:19].replace("T", " ")
    source = event.get("source", "")
    data = event.get("data", {})

    # Suppress noisy events in user view
    if not developer and evt_type in _SUPPRESS_USER_VIEW:
        return

    cat_color = _CATEGORY_STYLES.get(category, "white")

    if developer:
        # Developer view: full JSON
        console.print(
            f"[dim]{timestamp}[/dim]  "
            f"[{cat_color}]{evt_type:35s}[/{cat_color}]  "
            f"[dim]{source}[/dim]"
        )
        if data:
            console.print(f"  [dim]{json.dumps(data, default=str)[:200]}[/dim]")
        return

    # User view: formatted events
    icon = _event_icon(evt_type)
    label = _event_label(evt_type, data)

    if label:
        console.print(
            f"[dim]{timestamp}[/dim]  {icon}  "
            f"[{cat_color}]{label}[/{cat_color}]"
        )


def _event_icon(event_type: str) -> str:
    """Map event type to a display icon."""
    icons: dict[str, str] = {
        "agent.thinking.started": "\U0001f9e0",
        "agent.tool.called": "\U0001f527",
        "agent.tool.returned": "\u2190",
        "agent.response.complete": "\U0001f4ac",
        "user.message.sent": "\U0001f464",
        "plan.created": "\U0001f4cb",
        "plan.step.started": STATUS_ICONS.get("running", "\u25cf"),
        "plan.step.completed": STATUS_ICONS.get("completed", "\u2713"),
        "plan.step.failed": STATUS_ICONS.get("failed", "\u2717"),
        "workflow.started": "\U0001f680",
        "workflow.completed": STATUS_ICONS.get("completed", "\u2713"),
        "workflow.failed": STATUS_ICONS.get("failed", "\u2717"),
        "execution.started": "\u25b6",
        "execution.completed": STATUS_ICONS.get("completed", "\u2713"),
        "execution.failed": STATUS_ICONS.get("failed", "\u2717"),
        "convergence.decision": "\u2696",
        "task.dispatched": "\u21e8",
    }
    return icons.get(event_type, "\u00b7")


def _event_label(event_type: str, data: dict) -> str:
    """Build a human-readable label for an event."""
    agent = data.get("agent_id", data.get("agent_name", ""))

    if event_type == "agent.thinking.started":
        return f"{agent} thinking..."

    if event_type == "agent.tool.called":
        tool = data.get("tool_name", data.get("content", ""))
        return f"{agent} \u2192 {tool}"

    if event_type == "agent.tool.returned":
        tool = data.get("tool_name", "")
        return f"{agent} \u2190 {tool}" if tool else ""

    if event_type == "agent.response.complete":
        cost = data.get("cost_usd", 0)
        content = data.get("full_content", "")
        preview = content[:80].replace("\n", " ") if content else ""
        cost_str = f"  [dim]${cost:.4f}[/dim]" if cost else ""
        return f"{agent}: {preview}{cost_str}"

    if event_type == "user.message.sent":
        content = data.get("content", "")[:80]
        return f"User: {content}"

    if event_type == "plan.created":
        task_count = data.get("task_count", "?")
        return f"Plan created ({task_count} tasks)"

    if event_type in ("plan.step.started", "task.dispatched"):
        task_id = data.get("task_id", "")
        return f"{task_id} started" if task_id else event_type

    if event_type == "plan.step.completed":
        task_id = data.get("task_id", "")
        cost = data.get("cost_usd", 0)
        cost_str = f"  ${cost:.4f}" if cost else ""
        return f"{task_id} completed{cost_str}"

    if event_type == "plan.step.failed":
        task_id = data.get("task_id", "")
        reason = data.get("reason", "")[:60]
        return f"{task_id} failed: {reason}"

    if event_type.startswith("workflow."):
        action = event_type.split(".")[-1]
        name = data.get("workflow_name", "")
        return f"Workflow {name} {action}"

    if event_type.startswith("execution."):
        action = event_type.split(".")[-1]
        return f"Execution {action}"

    if event_type == "convergence.decision":
        decision = data.get("action", data.get("decision", ""))
        reason = data.get("reason", "")[:60]
        return f"Supervisor: {decision} — {reason}" if reason else f"Supervisor: {decision}"

    # Generic fallback
    msg = data.get("message", data.get("content", ""))
    if msg:
        return f"{event_type}: {str(msg)[:80]}"
    return event_type
