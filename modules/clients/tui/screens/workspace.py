"""MissionWorkspaceScreen — tabbed workspace replacing the old MainScreen.

The core mission workspace with 7 tabs: Overview, Team, Chat,
Workflows, Runs, Workshop, Context. The Overview tab preserves the
existing Plan 23 three-column layout unchanged.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Label, TabbedContent, TabPane

from modules.clients.tui.tabs.chat import ChatTab
from modules.clients.tui.tabs.context import ContextTab
from modules.clients.tui.tabs.overview import OverviewTab
from modules.clients.tui.tabs.runs import RunsTab
from modules.clients.tui.tabs.team import TeamTab
from modules.clients.tui.tabs.workflows import WorkflowsTab
from modules.clients.tui.tabs.workshop import WorkshopTab
from modules.clients.tui.widgets.cost_bar import CostBar


class MissionWorkspaceScreen(Screen):
    """Tabbed mission workspace — replaces the old MainScreen."""

    BINDINGS = [
        ("alt+1", "switch_tab('overview')", "Overview"),
        ("alt+2", "switch_tab('team')", "Team"),
        ("alt+3", "switch_tab('chat')", "Chat"),
        ("alt+4", "switch_tab('workflows')", "Workflows"),
        ("alt+5", "switch_tab('runs')", "Runs"),
        ("alt+6", "switch_tab('workshop')", "Workshop"),
        ("alt+7", "switch_tab('context')", "Context"),
    ]

    def compose(self) -> ComposeResult:
        # ── Header bar ────────────────────────────────────────────
        with Horizontal(id="mission-header"):
            yield Label("[bold]MISSION CONTROL[/bold]", id="app-title", markup=True)
            yield Label("[bold]No Mission[/bold]", id="mission-name", markup=True)

        # ── Tabbed workspace ──────────────────────────────────────
        with TabbedContent(id="workspace-tabs"):
            with TabPane("Overview", id="overview"):
                yield OverviewTab()
            with TabPane("Team", id="team"):
                yield TeamTab()
            with TabPane("Chat", id="chat"):
                yield ChatTab()
            with TabPane("Workflows", id="workflows"):
                yield WorkflowsTab()
            with TabPane("Runs", id="runs"):
                yield RunsTab()
            with TabPane("Workshop", id="workshop"):
                yield WorkshopTab()
            with TabPane("Context", id="context"):
                yield ContextTab()

        # ── Status bar ────────────────────────────────────────────
        yield CostBar(id="cost-bar")

    def action_switch_tab(self, tab_id: str) -> None:
        """Switch to a specific tab via Alt+N shortcut."""
        tabs = self.query_one("#workspace-tabs", TabbedContent)
        tabs.active = tab_id
