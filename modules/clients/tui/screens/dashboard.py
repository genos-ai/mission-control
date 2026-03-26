"""DashboardScreen — global overview shown on launch.

Displays clickable mission cards, recent runs, cost summary.
Data loaded from ServiceBridge on mount.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Label, Static

from modules.backend.core.logging import get_logger
from modules.clients.common.gate_helpers import STATUS_ICONS

logger = get_logger(__name__)


class MissionCard(Static):
    """Clickable mission card in the dashboard."""

    def __init__(self, mission: dict, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._mission = mission

    def compose(self) -> ComposeResult:
        name = self._mission.get("name", "Untitled")
        status = self._mission.get("status", "unknown")
        icon = STATUS_ICONS.get(status, "[dim]?[/dim]")
        yield Static(
            f"  {icon}  [bold]{name}[/bold]  [dim]\\[{status}][/dim]",
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
        with Horizontal(id="dashboard-header"):
            yield Label(
                "[bold]MISSION CONTROL DASHBOARD[/bold]",
                id="dashboard-title",
                markup=True,
            )

        with VerticalScroll(id="dashboard-content"):
            yield Static(
                "[dim]Loading...[/dim]",
                id="dashboard-body",
                markup=True,
            )

    async def on_mount(self) -> None:
        self.run_worker(self._load_data(), thread=False)

    async def _load_data(self) -> None:
        """Fetch missions and recent executions."""
        scroll = self.query_one("#dashboard-content", VerticalScroll)
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
                "Press [bold]Ctrl+P[/bold] to create a mission.",
            )
            return

        # Replace placeholder with mission cards
        body.update("[bold]── MISSIONS ── [dim](click to select)[/dim][/bold]")

        for m in missions:
            scroll.mount(MissionCard(m, classes="mission-item"))

        # Recent runs section
        runs_header = Static(
            "\n[bold]── RECENT RUNS ──[/bold]",
            markup=True,
        )
        scroll.mount(runs_header)

        try:
            executions = await self.app.bridge.list_executions(limit=10)
            if not executions:
                scroll.mount(
                    Static("  [dim]No runs yet[/dim]", markup=True),
                )
            else:
                lines: list[str] = []
                for ex in executions:
                    obj = ex.get("objective", "")[:40] or "(no objective)"
                    status = ex.get("status", "?")
                    cost = ex.get("total_cost_usd", 0.0)
                    icon = STATUS_ICONS.get(status, "[dim]?[/dim]")
                    lines.append(f"  {icon}  {obj}  ${cost:.2f}")
                scroll.mount(
                    Static("\n".join(lines), markup=True),
                )
        except Exception:
            logger.warning("Could not load executions for dashboard", exc_info=True)
            scroll.mount(
                Static("  [dim]Could not load runs[/dim]", markup=True),
            )
