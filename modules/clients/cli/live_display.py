"""
CLI live execution display — Rich Live rendering of SessionEvents.

Provides CliEventBus (implements EventBusProtocol) and a LiveExecutionDisplay
that shows real-time agent activity during workflow and execution runs.

Layout:
    ┌─ Execution Progress ──────────────────────────┐
    │  Step Table (step status, agent, cost)         │
    │                                                │
    │  ── Agent Activity ──                          │
    │  14:30:05 🧠 planner thinking                  │
    │  14:30:07 🔧 read_file                         │
    │  14:30:08 ✓ planner done $0.012                │
    │                                                │
    │  Cost: $0.0234  |  2/5 steps  |  00:32 elapsed │
    └────────────────────────────────────────────────┘
"""

from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone

from rich import box
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from modules.backend.agents.mission_control.models import EventBusProtocol
from modules.backend.events.types import SessionEvent
from modules.clients.common.display import get_console, styled_status
from modules.clients.common.event_rendering import (
    EVENT_STYLES,
    DEFAULT_STYLE,
    format_event_line,
    is_noisy,
    is_streaming,
    summarize_event,
)


class CliEventBus(EventBusProtocol):
    """EventBusProtocol that feeds events to a LiveExecutionDisplay.

    When dispatch publishes SessionEvents, this bus stores them
    and triggers a display refresh.
    """

    def __init__(self, display: LiveExecutionDisplay) -> None:
        self._display = display

    async def publish(self, event: SessionEvent) -> None:
        self._display.handle_event(event)


class LiveExecutionDisplay:
    """Rich Live display for CLI execution progress.

    Tracks workflow steps, agent activity, and cost in real-time.
    Works with both the on_progress dict callback (workflow steps)
    and SessionEvent stream (agent-level activity).
    """

    def __init__(self, max_events: int = 15, show_thinking: bool = True) -> None:
        self._steps: dict[str, dict] = {}
        self._events: deque[SessionEvent] = deque(maxlen=max_events)
        self._total_cost: float = 0.0
        self._total_steps: int = 0
        self._start_time: float = time.monotonic()
        self._live: Live | None = None
        self._workflow_name: str = ""
        self._current_agents: dict[str, str] = {}  # agent_id → status
        self._show_thinking: bool = show_thinking
        self._thinking_buffer: dict[str, str] = {}  # agent_id → accumulated text

    def create_event_bus(self) -> CliEventBus:
        """Create a CliEventBus wired to this display."""
        return CliEventBus(self)

    def start(self) -> Live:
        """Create and return a Rich Live context for use with `with`."""
        console = get_console()
        self._start_time = time.monotonic()
        self._live = Live(
            self._render(),
            console=console,
            refresh_per_second=4,
            vertical_overflow="crop",
        )
        return self._live

    def handle_progress(self, event: dict) -> None:
        """Handle on_progress dict events from WorkflowRunService."""
        etype = event.get("type", "")

        if etype == "workflow_start":
            self._total_steps = event.get("total_steps", 0)
            self._workflow_name = event.get("workflow", "")

        elif etype == "step_start":
            self._steps[event["step_id"]] = {
                "capability": event.get("capability", ""),
                "description": event.get("description", ""),
                "status": "running",
            }
            self._refresh()

        elif etype == "step_done":
            sid = event["step_id"]
            if sid in self._steps:
                self._steps[sid]["status"] = event.get("status", "done")
                self._steps[sid]["cost_usd"] = event.get("cost_usd", 0)
            self._total_cost = sum(
                s.get("cost_usd", 0) for s in self._steps.values()
            )
            self._refresh()

    def handle_event(self, event: SessionEvent) -> None:
        """Handle a SessionEvent from the event bus."""
        etype = event.event_type
        agent_id = getattr(event, "agent_id", None)

        # Streaming events (thinking text) go to thinking buffer, not event log
        if is_streaming(event):
            if self._show_thinking and agent_id:
                content = getattr(event, "content", "")
                self._thinking_buffer[agent_id] = (
                    self._thinking_buffer.get(agent_id, "") + content
                )
            self._refresh()
            return

        if is_noisy(event):
            return

        self._events.append(event)

        # Track active agents
        if etype == "agent.thinking.started" and agent_id:
            self._current_agents[agent_id] = "thinking"
            self._thinking_buffer[agent_id] = ""
        elif etype == "agent.response.complete" and agent_id:
            self._current_agents.pop(agent_id, None)
            self._thinking_buffer.pop(agent_id, None)
            cost = getattr(event, "cost_usd", 0.0)
            self._total_cost += cost
        elif etype == "session.cost.updated":
            self._total_cost = getattr(event, "cumulative_cost_usd", self._total_cost)

        self._refresh()

    def _refresh(self) -> None:
        """Refresh the live display."""
        if self._live:
            self._live.update(self._render())

    def _render(self) -> Panel:
        """Build the full display renderable."""
        layout = Layout()
        parts = []

        # Step table (if we have steps)
        if self._steps:
            parts.append(Layout(name="steps", size=len(self._steps) + 4))

        # Agent activity log
        parts.append(Layout(name="activity", ratio=1))

        # Footer
        parts.append(Layout(name="footer", size=3))

        if len(parts) == 1:
            # No steps yet, just activity
            layout = Layout(name="root")
            layout.split_column(
                Layout(name="activity", ratio=1),
                Layout(name="footer", size=3),
            )
        else:
            layout.split_column(*parts)

        # ── Steps table ───────────────────────────────────
        if self._steps and "steps" in [p.name for p in layout.children]:
            table = Table(
                show_header=True,
                header_style="bold blue",
                box=box.SIMPLE_HEAVY,
                expand=True,
            )
            table.add_column("Status", width=3, no_wrap=True)
            table.add_column("Step", width=22, style="cyan")
            table.add_column("Capability", ratio=1)
            table.add_column("Cost", width=10, justify="right")

            for step_id, info in self._steps.items():
                status = info.get("status", "running")
                status_sym = {
                    "running": "[yellow]●[/yellow]",
                    "completed": "[green]✓[/green]",
                    "success": "[green]✓[/green]",
                    "failed": "[red]✗[/red]",
                }.get(status, styled_status(status))
                cost = f"${info.get('cost_usd', 0):.4f}" if "cost_usd" in info else "[dim]—[/dim]"
                table.add_row(status_sym, step_id, info.get("capability", ""), cost)

            layout["steps"].update(Panel(table, title="Steps", border_style="blue"))

        # ── Agent activity ────────────────────────────────
        activity_parts = []

        # Show thinking buffer (agent reasoning text)
        if self._show_thinking and self._thinking_buffer:
            for aid, text in self._thinking_buffer.items():
                if text:
                    # Show last 200 chars of thinking
                    display_text = text[-200:].replace("\n", " ")
                    if len(text) > 200:
                        display_text = "…" + display_text
                    activity_parts.append(
                        f"\U0001f4ad [cyan]{aid}[/cyan]:\n"
                        f"  [dim italic]{display_text}[/dim italic]"
                    )
            if activity_parts:
                activity_parts.append("")  # blank line separator

        # Show active agents indicator
        if self._current_agents:
            active = ", ".join(
                f"[cyan]{aid}[/cyan]" for aid in self._current_agents
            )
            activity_parts.append(f"[bold]Active:[/bold] {active}\n")

        if self._events:
            lines = [format_event_line(e) for e in self._events]
            activity_parts.append("\n".join(lines))
        elif not activity_parts:
            activity_parts.append("[dim]Waiting for agent activity...[/dim]")

        activity_text = "\n".join(activity_parts)

        layout["activity"].update(
            Panel(activity_text, title="Agent Activity", border_style="dim cyan")
        )

        # ── Footer ────────────────────────────────────────
        elapsed = time.monotonic() - self._start_time
        minutes, seconds = divmod(int(elapsed), 60)

        completed = sum(
            1 for s in self._steps.values()
            if s.get("status") in ("completed", "success")
        )
        total = self._total_steps or len(self._steps)

        footer_parts = [
            f"Cost: [bold]${self._total_cost:.4f}[/bold]",
            f"{completed}/{total} steps" if total else "starting",
            f"{minutes:02d}:{seconds:02d} elapsed",
        ]
        if self._workflow_name:
            footer_parts.insert(0, f"[bold]{self._workflow_name}[/bold]")

        layout["footer"].update(
            Panel(
                "  |  ".join(footer_parts),
                border_style="dim",
            )
        )

        title = "Execution Progress"
        if self._workflow_name:
            title = f"{self._workflow_name} — Execution Progress"

        return Panel(layout, title=title, border_style="cyan")
