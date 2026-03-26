"""Event stream — scrolling log of SessionEvents in the right sidebar.

Color-coded by event type with timestamp and one-line summary.
The App posts events here via add_event(); the widget auto-scrolls.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Label, Static

from modules.backend.events.types import SessionEvent
from modules.clients.common.event_rendering import format_event_line, is_noisy


class EventEntry(Static):
    """A single event row in the stream."""

    DEFAULT_CSS = """
    EventEntry {
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, event: SessionEvent, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._event = event

    def compose(self) -> ComposeResult:
        yield Label(format_event_line(self._event), markup=True)


class EventStreamWidget(Widget):
    """Scrolling event log for the right sidebar."""

    DEFAULT_CSS = """
    EventStreamWidget {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("  EVENTS", classes="sidebar-heading")
        yield VerticalScroll(id="event-scroll")

    def add_event(self, event: SessionEvent) -> None:
        """Append an event to the stream and auto-scroll."""
        scroll = self.query_one("#event-scroll", VerticalScroll)
        # Skip noisy chunk events — they'd flood the stream
        if is_noisy(event):
            return
        entry = EventEntry(event)
        scroll.mount(entry)
        entry.scroll_visible()
