"""
CLI live execution display — Rich Live rendering of SessionEvents.

Provides CliEventBus (implements EventBusProtocol) and a LiveExecutionDisplay
that shows real-time agent activity during workflow and execution runs.

Layout:
    ┌─ Live Activity (70%) ─────────────────┬─ Results (30%) ────────────────┐
    │  Active: code.quality.agent            │  ✓ task-001 code.quality $0.12│
    │                                        │    34.2s — 3 tools called     │
    │  💭 code.quality.agent:                │  ✗ task-002 system.health     │
    │    …reviewing the auth module code     │    Agent not found in roster  │
    │                                        │                               │
    │  14:30:05 🧠 code.quality thinking     │                               │
    │  14:30:07 🔧 read_file                 │                               │
    │  14:30:08 📎 read_file → ok            │                               │
    ├─ Execution Progress ───────────────────┴───────────────────────────────┤
    │  Cost: $0.0234  |  1/2 tasks  |  RUNNING  |  00:32 elapsed            │
    └────────────────────────────────────────────────────────────────────────┘
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
from modules.clients.common.display import styled_status
from modules.clients.common.event_rendering import (
    EVENT_STYLES,
    DEFAULT_STYLE,
    format_event_line,
    is_noisy,
    is_streaming,
    summarize_event,
)


class CliEventBus(EventBusProtocol):
    """EventBusProtocol that feeds events to a LiveExecutionDisplay."""

    def __init__(self, display: LiveExecutionDisplay) -> None:
        self._display = display

    async def publish(self, event: SessionEvent) -> None:
        self._display.handle_event(event)


class VerboseEventBus(EventBusProtocol):
    """EventBusProtocol that prints every event as JSONL — no Rich formatting.

    Use with ``mc run -v`` so AI agents or log pipelines can consume
    the raw event stream without terminal escape sequences.
    """

    def __init__(self) -> None:
        import json as _json
        self._json = _json
        self._start = time.monotonic()

    async def publish(self, event: SessionEvent) -> None:
        elapsed = time.monotonic() - self._start
        data = event.model_dump(mode="json")
        # Add a human-friendly elapsed field at the top level
        data["_elapsed_s"] = round(elapsed, 2)
        print(self._json.dumps(data, default=str), flush=True)


class LiveExecutionDisplay:
    """Rich Live display for CLI execution progress.

    Left pane (Live Activity): what's happening right now — active agents,
    thinking text, tool calls, event stream.

    Right pane (Results): what's done — completed/failed task outcomes,
    errors, verification summaries. Persists so nothing scrolls away.

    Footer: cost, progress, status, elapsed time.
    """

    def __init__(self, max_events: int = 100, show_thinking: bool = True) -> None:
        self._events: deque[SessionEvent] = deque(maxlen=max_events)
        self._total_cost: float = 0.0
        self._total_steps: int = 0
        self._start_time: float = time.monotonic()
        self._live: Live | None = None
        self._workflow_name: str = ""
        self._current_agents: dict[str, str] = {}
        self._show_thinking: bool = show_thinking
        self._thinking_buffer: dict[str, str] = {}

        # Results pane state
        self._results: list[dict] = []  # completed task outcomes
        self._errors: list[str] = []  # errors and warnings
        self._phase: str = "planning"  # planning | executing | done

        # Mapping: step_id → agent name, agent_id → cost/timing
        self._step_agents: dict[str, str] = {}  # step_id → assigned_agent
        self._agent_costs: dict[str, float] = {}  # agent_id → accumulated cost
        self._agent_start: dict[str, float] = {}  # agent_id → start time
        self._status: str = "running"  # running | success | failed

        # Steps (workflow mode)
        self._steps: dict[str, dict] = {}

    def create_event_bus(self) -> CliEventBus:
        """Create a CliEventBus wired to this display."""
        return CliEventBus(self)

    def start(self) -> Live:
        """Create and return a Rich Live context for use with `with`."""
        from rich.console import Console
        console = Console()
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

        # Streaming → thinking buffer only
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

        # All non-streaming events go to left pane event stream
        self._events.append(event)

        # Track active agents
        if etype == "agent.thinking.started" and agent_id:
            self._current_agents[agent_id] = "thinking"
            self._thinking_buffer[agent_id] = ""
            if agent_id not in self._agent_start:
                self._agent_start[agent_id] = time.monotonic()

        elif etype == "agent.response.complete" and agent_id:
            self._current_agents.pop(agent_id, None)
            self._thinking_buffer.pop(agent_id, None)
            cost = getattr(event, "cost_usd", 0.0)
            self._total_cost += cost
            self._agent_costs[agent_id] = self._agent_costs.get(agent_id, 0.0) + cost
            # Capture agent errors
            metadata = getattr(event, "metadata", None) or {}
            if metadata.get("error"):
                content = getattr(event, "full_content", "unknown error")
                self._errors.append(f"{agent_id}: {content}")

        elif etype == "session.cost.updated":
            self._total_cost = getattr(event, "cumulative_cost_usd", self._total_cost)

        # Plan created → switch to executing phase
        elif etype == "plan.created":
            self._phase = "executing"

        # Step started → track agent assignment
        elif etype == "plan.step.started":
            step_id = getattr(event, "step_id", "")
            agent = getattr(event, "assigned_agent", "")
            if step_id and agent:
                self._step_agents[step_id] = agent
                self._agent_start[agent] = time.monotonic()

        # Task completed → add to results pane
        elif etype == "plan.step.completed":
            step_id = getattr(event, "step_id", "?")
            status = getattr(event, "status", "?")
            result_summary = getattr(event, "result_summary", "")

            # Look up agent from step mapping
            agent = self._step_agents.get(step_id, "")
            cost = self._agent_costs.get(agent, 0.0)
            start = self._agent_start.get(agent, 0.0)
            duration = time.monotonic() - start if start else 0.0

            self._results.append({
                "step_id": step_id,
                "agent": agent,
                "status": status,
                "cost_usd": cost,
                "duration": duration,
                "summary": result_summary,
            })
            if status == "failed" and result_summary:
                self._errors.append(f"{step_id} ({agent}): {result_summary}")

        self._refresh()

    def add_error(self, message: str) -> None:
        """Add an error message to the results pane."""
        self._errors.append(message)
        self._status = "failed"
        self._refresh()

    def set_status(self, status: str) -> None:
        """Set the overall execution status."""
        self._status = status
        self._refresh()

    def _refresh(self) -> None:
        """Refresh the live display."""
        if self._live:
            self._live.update(self._render())

    def _render(self) -> Layout:
        """Build the full display renderable."""
        # ── Root: columns + footer ──
        root = Layout(name="root")
        root.split_column(
            Layout(name="columns", ratio=1),
            Layout(name="footer", size=3),
        )

        root["columns"].split_row(
            Layout(name="left", ratio=7),
            Layout(name="right", ratio=3),
        )

        # ── Left column: steps (if any) + live activity ──
        left_parts = []
        if self._steps:
            left_parts.append(Layout(name="steps", size=len(self._steps) + 4))
        left_parts.append(Layout(name="activity", ratio=1))
        root["columns"]["left"].split_column(*left_parts)

        # Steps table (workflow mode)
        if self._steps:
            table = Table(
                show_header=True,
                header_style="bold blue",
                box=box.SIMPLE_HEAVY,
                expand=True,
            )
            table.add_column("", width=2, no_wrap=True)
            table.add_column("Step", width=20, style="cyan")
            table.add_column("Capability", ratio=1)
            table.add_column("Cost", width=10, justify="right")

            for step_id, info in self._steps.items():
                status = info.get("status", "running")
                sym = {
                    "running": "[yellow]●[/yellow]",
                    "completed": "[green]✓[/green]",
                    "success": "[green]✓[/green]",
                    "failed": "[red]✗[/red]",
                }.get(status, styled_status(status))
                cost = f"${info.get('cost_usd', 0):.4f}" if "cost_usd" in info else "[dim]—[/dim]"
                table.add_row(sym, step_id, info.get("capability", ""), cost)

            root["columns"]["left"]["steps"].update(
                Panel(table, title="Steps", border_style="blue")
            )

        # ── Live Activity (left pane) ─────────────────────
        activity_lines = []

        # Active agents
        if self._current_agents:
            active = ", ".join(
                f"[bold cyan]{aid}[/bold cyan]" for aid in self._current_agents
            )
            activity_lines.append(f"[bold]Active:[/bold] {active}")
            activity_lines.append("")

        # Thinking buffers
        if self._show_thinking and self._thinking_buffer:
            for aid, buf in self._thinking_buffer.items():
                if buf:
                    display_text = buf[-800:].replace("\n", " ")
                    if len(buf) > 800:
                        display_text = "…" + display_text
                    activity_lines.append(
                        f"\U0001f4ad [cyan]{aid}[/cyan]:"
                    )
                    activity_lines.append(
                        f"  [dim italic]{display_text}[/dim italic]"
                    )
            if activity_lines:
                activity_lines.append("")

        # Event stream
        if self._events:
            for e in self._events:
                activity_lines.append(format_event_line(e))
        elif not activity_lines:
            if self._phase == "planning":
                elapsed = time.monotonic() - self._start_time
                dots = "." * (int(elapsed) % 4 + 1)
                activity_lines.append(
                    f"[yellow]⏳ Planning execution{dots}[/yellow]"
                )
                activity_lines.append(
                    "[dim]  Building task plan from objective and team roster[/dim]"
                )
            else:
                activity_lines.append("[dim]Waiting for agent activity...[/dim]")

        root["columns"]["left"]["activity"].update(
            Panel(
                "\n".join(activity_lines),
                title="Live Activity",
                border_style="dim cyan",
            )
        )

        # ── Results (right pane) ──────────────────────────
        result_lines = []

        # Errors first (always visible at top)
        for err in self._errors:
            result_lines.append(f"[bold red]✗ ERROR[/bold red]  {err}")

        if self._errors and self._results:
            result_lines.append("")

        # Task results
        for r in self._results:
            status = r["status"]
            if status in ("completed", "success"):
                sym = "[green]✓[/green]"
                cost_str = f"${r['cost_usd']:.4f}" if r.get("cost_usd") else ""
                dur_str = f"{r['duration']:.1f}s" if r.get("duration") else ""
                detail = f"{cost_str}  {dur_str}".strip()
                if r.get("summary"):
                    detail = f"{detail} — {r['summary']}" if detail else r["summary"]
            elif status == "failed":
                sym = "[red]✗[/red]"
                detail = r.get("summary") or "failed"
            elif status == "skipped":
                sym = "[yellow]–[/yellow]"
                detail = r.get("summary") or "skipped"
            else:
                sym = "[dim]?[/dim]"
                detail = status

            agent = r.get("agent", "")
            agent_short = agent.rsplit(".", 1)[0] if "." in agent else agent
            result_lines.append(
                f"{sym} [bold]{r['step_id']}[/bold] [cyan]{agent_short}[/cyan]"
            )
            result_lines.append(f"  [dim]{detail}[/dim]")

        if not result_lines:
            result_lines.append("[dim]No results yet...[/dim]")

        results_border = "dim red" if self._errors else "dim green"
        root["columns"]["right"].update(
            Panel(
                "\n".join(result_lines),
                title="Results",
                border_style=results_border,
            )
        )

        # ── Footer (full width) ───────────────────────────
        elapsed = time.monotonic() - self._start_time
        minutes, seconds = divmod(int(elapsed), 60)

        completed = sum(
            1 for s in self._steps.values()
            if s.get("status") in ("completed", "success")
        )
        total = self._total_steps or len(self._steps) or len(self._results) + len(self._current_agents)

        effective_status = self._status
        if effective_status == "running" and self._phase == "planning":
            effective_status = "planning"

        status_display = {
            "planning": "[yellow]PLANNING[/yellow]",
            "running": "[yellow]RUNNING[/yellow]",
            "success": "[green]SUCCESS[/green]",
            "failed": "[red]FAILED[/red]",
        }.get(effective_status, effective_status)

        footer_parts = [
            f"Cost: [bold]${self._total_cost:.4f}[/bold]",
        ]
        if total:
            done = completed or len(self._results)
            footer_parts.append(f"{done}/{total} tasks")
        footer_parts.append(status_display)
        footer_parts.append(f"{minutes:02d}:{seconds:02d} elapsed")

        if self._workflow_name:
            footer_parts.insert(0, f"[bold]{self._workflow_name}[/bold]")

        title = "Execution Progress"
        if self._workflow_name:
            title = f"{self._workflow_name} — Execution Progress"

        root["footer"].update(
            Panel(
                "  |  ".join(footer_parts),
                title=title,
                title_align="left",
                border_style="cyan",
            )
        )

        return root
