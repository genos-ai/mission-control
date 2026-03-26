"""
Shared event rendering for all Mission Control client surfaces.

Converts SessionEvents into display-ready strings with icons and colors.
Used by both the TUI EventStreamWidget and CLI live execution displays.

All functions are synchronous — they produce Rich markup strings,
not business logic.
"""

from __future__ import annotations

from modules.backend.events.types import SessionEvent


# ── Event type → display config ──────────────────────────────────────

EVENT_STYLES: dict[str, tuple[str, str]] = {
    # event_type → (icon, Rich color)
    "agent.thinking.started": ("🧠", "dim cyan"),
    "agent.response.chunk": ("·", "dim"),
    "agent.response.complete": ("✓", "green"),
    "agent.tool.called": ("🔧", "yellow"),
    "agent.tool.returned": ("📎", "dim yellow"),
    "session.cost.updated": ("$", "green"),
    "plan.created": ("📋", "bold blue"),
    "plan.step.started": ("▶", "cyan"),
    "plan.step.completed": ("■", "green"),
    "plan.revised": ("↻", "magenta"),
    "agent.approval.requested": ("⏸", "bold yellow"),
    "approval.response.received": ("▶", "bold green"),
    "workflow.run.started": ("🎬", "bold blue"),
    "workflow.mission.started": ("▶", "blue"),
    "workflow.mission.completed": ("■", "blue"),
    "workflow.run.completed": ("✓", "bold green"),
    "workflow.run.failed": ("✗", "bold red"),
    "user.message.sent": ("💬", "white"),
    "user.approval.granted": ("👍", "green"),
}

DEFAULT_STYLE: tuple[str, str] = ("·", "dim")

# Event types that are too noisy for stream display
NOISY_EVENT_TYPES: set[str] = set()

# Event types that represent streaming content (need special rendering)
STREAMING_EVENT_TYPES: set[str] = {"agent.response.chunk"}


def summarize_event(event: SessionEvent) -> str:
    """Build a one-line summary for any SessionEvent."""
    etype = event.event_type

    if etype == "agent.thinking.started":
        return f"{getattr(event, 'agent_id', '?')} thinking"

    if etype == "agent.response.chunk":
        content = getattr(event, "content", "")
        preview = content[:60].replace("\n", " ")
        return preview or "..."

    if etype == "agent.response.complete":
        agent = getattr(event, "agent_id", "?")
        cost = getattr(event, "cost_usd", 0.0)
        return f"{agent} done ${cost:.3f}"

    if etype == "agent.tool.called":
        return f"{getattr(event, 'tool_name', '?')}"

    if etype == "agent.tool.returned":
        status = getattr(event, "status", "ok")
        return f"{getattr(event, 'tool_name', '?')} → {status}"

    if etype == "session.cost.updated":
        return f"${getattr(event, 'cumulative_cost_usd', 0.0):.4f}"

    if etype == "plan.created":
        return f"{getattr(event, 'step_count', '?')} tasks planned"

    if etype == "plan.step.started":
        return f"{getattr(event, 'assigned_agent', '?')}: {getattr(event, 'step_name', '')[:25]}"

    if etype == "plan.step.completed":
        return f"{getattr(event, 'step_id', '?')} {getattr(event, 'status', '')}"

    if etype == "plan.revised":
        return getattr(event, "revision_reason", "revised")[:30]

    if etype == "agent.approval.requested":
        return f"gate: {getattr(event, 'action', '?')}"

    if etype in ("workflow.run.started", "workflow.run.completed", "workflow.run.failed"):
        return getattr(event, "workflow_name", "?")

    # Fallback: use last segment of event_type
    return etype.rsplit(".", 1)[-1]


def format_event_line(event: SessionEvent) -> str:
    """Format a SessionEvent as a Rich markup string.

    Returns a single line like: ``[dim]14:30:05[/dim] 🧠 [dim cyan]planner thinking[/dim cyan]``
    """
    icon, color = EVENT_STYLES.get(event.event_type, DEFAULT_STYLE)
    ts = event.timestamp.strftime("%H:%M:%S")
    summary = summarize_event(event)
    return f"[dim]{ts}[/dim] {icon} [{color}]{summary}[/{color}]"


def is_noisy(event: SessionEvent) -> bool:
    """Return True if this event type should be filtered from stream displays."""
    return event.event_type in NOISY_EVENT_TYPES


def is_streaming(event: SessionEvent) -> bool:
    """Return True if this event type represents streaming content (e.g. thinking text)."""
    return event.event_type in STREAMING_EVENT_TYPES


def format_thinking_line(event: SessionEvent) -> str:
    """Format a streaming chunk event as thinking text."""
    content = getattr(event, "content", "")
    # Truncate to last 200 chars for display
    if len(content) > 200:
        content = "…" + content[-200:]
    content = content.replace("\n", " ")
    return f"[dim italic]{content}[/dim italic]"
