"""OverviewTab — the live operational dashboard for the active mission.

This is the existing Plan 23 three-column layout preserved as-is,
now wrapped in a TabPane for the MissionWorkspaceScreen. All existing
widgets, event routing, and gate review continue unchanged.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static

from modules.clients.tui.widgets.agent_sidebar import AgentSidebar
from modules.clients.tui.widgets.chat_input import ChatInput
from modules.clients.tui.widgets.event_stream import EventStreamWidget
from modules.clients.tui.widgets.notification import NotificationStack


class OverviewTab(Static):
    """Existing Plan 23 three-column layout wrapped for TabbedContent.

    Left:   AgentSidebar (roster + mission summary)
    Center: Mission/agent view + chat input
    Right:  Event stream + notifications
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="main-container"):
            yield AgentSidebar(id="agent-sidebar")

            with Vertical(id="center-panel"):
                yield VerticalScroll(
                    Static(
                        "Press [bold]Ctrl+M[/bold] to start a mission\n"
                        "Press [bold]Ctrl+P[/bold] to switch mission",
                        classes="placeholder-panel",
                        markup=True,
                    ),
                    id="center-content",
                )
                yield ChatInput(id="chat-input")

            with Vertical(id="right-sidebar"):
                yield NotificationStack(id="notification-stack")
                yield EventStreamWidget(id="event-stream")
