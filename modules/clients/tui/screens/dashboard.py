"""DashboardScreen — global overview shown on launch.

Displays mission cards, recent runs, cost summary, and system health.
Data loaded from ServiceBridge on mount.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Label, Static

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


class MissionCard(Static):
    """Clickable mission card in the dashboard grid."""

    def __init__(self, mission: dict, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._mission = mission

    def compose(self) -> ComposeResult:
        name = self._mission.get("name", "Untitled")
        status = self._mission.get("status", "unknown")
        yield Static(
            f"[bold]{name}[/bold]\n"
            f"{status}",
            markup=True,
        )

    def on_click(self) -> None:
        from modules.clients.tui.messages import MissionSelected
        self.post_message(MissionSelected(
            mission_id=self._mission["id"],
            mission_name=self._mission.get("name", ""),
        ))


class DashboardScreen(Screen):
    """Global overview — default screen on launch."""

    def compose(self) -> ComposeResult:
        # ── Header ────────────────────────────────────────────────
        with Horizontal(id="dashboard-header"):
            yield Label(
                "[bold]MISSION CONTROL DASHBOARD[/bold]",
                id="dashboard-title",
                markup=True,
            )

        # ── Scrollable content ────────────────────────────────────
        with VerticalScroll(id="dashboard-content"):
            yield Static(
                "[dim]Loading...[/dim]",
                id="dashboard-body",
                markup=True,
            )

    async def on_mount(self) -> None:
        """Load dashboard data from ServiceBridge."""
        self.run_worker(self._load_data(), thread=False)

    async def _load_data(self) -> None:
        """Fetch missions and recent executions."""
        body = self.query_one("#dashboard-body", Static)
        try:
            missions = await self.app.bridge.list_missions()
        except Exception:
            logger.warning("Could not load missions for dashboard", exc_info=True)
            missions = []

        if not missions:
            body.update(
                "[dim]Welcome to Mission Control[/dim]\n"
                "Create your first mission to get started.\n"
                "Press [bold]Ctrl+P[/bold] to create a mission."
            )
            return

        # Build dashboard content
        lines: list[str] = []

        # ── Missions section ──────────────────────────────────────
        lines.append("[bold]── MISSIONS ──[/bold]")
        for m in missions:
            name = m.get("name", "Untitled")
            status = m.get("status", "unknown")
            lines.append(f"  {name}  [{status}]")
        lines.append("")

        # ── Recent runs section ───────────────────────────────────
        lines.append("[bold]── RECENT RUNS ──[/bold]")
        try:
            executions = await self.app.bridge.list_executions(limit=10)
            if not executions:
                lines.append("  [dim]No runs yet[/dim]")
            else:
                for ex in executions:
                    obj = ex.get("objective", "")[:40] or "(no objective)"
                    status = ex.get("status", "?")
                    cost = ex.get("total_cost_usd", 0.0)
                    lines.append(f"  {status}  {obj}  ${cost:.2f}")
        except Exception:
            logger.warning("Could not load executions for dashboard", exc_info=True)
            lines.append("  [dim]Could not load runs[/dim]")

        body.update("\n".join(lines))
