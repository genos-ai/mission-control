"""Notification widget — toast-style alerts for budget warnings and failures.

Displays a stack of dismissible notifications at the top of the event stream
panel. Notifications auto-expire or can be dismissed with a click.

Also provides NotificationListModal for viewing all notifications (Ctrl+N).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Button, Label, Static

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

# ── Severity levels ──────────────────────────────────────────────────

_SEVERITY_STYLES: dict[str, tuple[str, str]] = {
    "info": ("ℹ", "cyan"),
    "warning": ("⚠", "yellow"),
    "error": ("✗", "red"),
    "success": ("✓", "green"),
}


class NotificationEntry(Static):
    """A single notification in the stack."""

    DEFAULT_CSS = """
    NotificationEntry {
        height: auto;
        min-height: 1;
        padding: 0 1;
        margin: 0 0 0 0;
    }
    NotificationEntry.severity-warning {
        background: $warning 10%;
    }
    NotificationEntry.severity-error {
        background: $error 10%;
    }
    """

    def __init__(
        self,
        message: str,
        severity: str = "info",
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._message = message
        self._severity = severity

    def compose(self) -> ComposeResult:
        icon, color = _SEVERITY_STYLES.get(self._severity, _SEVERITY_STYLES["info"])
        yield Label(
            f"[{color}]{icon}[/{color}] {self._message}",
            markup=True,
        )

    def on_click(self) -> None:
        """Dismiss on click."""
        self.remove()


class NotificationStack(Widget):
    """Stack of toast-style notifications. Most recent on top."""

    DEFAULT_CSS = """
    NotificationStack {
        height: auto;
        max-height: 6;
        overflow-y: auto;
    }
    """

    MAX_VISIBLE = 5

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._count = 0
        self._dismiss_timers: dict[str, Timer] = {}

    def compose(self) -> ComposeResult:
        yield Vertical(id="notification-container")

    def add_notification(
        self,
        message: str,
        severity: str = "info",
        timeout_seconds: float = 10.0,
    ) -> None:
        """Add a notification to the stack."""
        self._count += 1
        entry_id = f"notif-{self._count}"
        entry = NotificationEntry(
            message,
            severity=severity,
            id=entry_id,
        )
        entry.add_class(f"severity-{severity}")

        try:
            container = self.query_one("#notification-container", Vertical)
        except NoMatches:
            return

        container.mount(entry)

        # Trim old notifications
        children = list(container.children)
        while len(children) > self.MAX_VISIBLE:
            oldest = children.pop(0)
            oldest.remove()

        # Auto-dismiss after timeout
        if timeout_seconds > 0:
            timer = self.set_timer(
                timeout_seconds,
                lambda eid=entry_id: self._dismiss(eid),
            )
            self._dismiss_timers[entry_id] = timer

    def _dismiss(self, entry_id: str) -> None:
        """Remove a notification by ID."""
        try:
            entry = self.query_one(f"#{entry_id}", NotificationEntry)
            entry.remove()
        except NoMatches:
            pass
        self._dismiss_timers.pop(entry_id, None)

    def clear_all(self) -> None:
        """Remove all notifications."""
        try:
            container = self.query_one("#notification-container", Vertical)
            container.remove_children()
        except NoMatches:
            pass
        for timer in self._dismiss_timers.values():
            timer.stop()
        self._dismiss_timers.clear()


# ── Notification types ──────────────────────────────────────────────

URGENCY_HIGH = "high"
URGENCY_NORMAL = "normal"

_TYPE_CONFIG: dict[str, tuple[str, str]] = {
    "gate_pending": (URGENCY_HIGH, "Gate pending"),
    "run_failed": (URGENCY_HIGH, "Run failed"),
    "run_completed": (URGENCY_NORMAL, "Run completed"),
    "budget_warning": (URGENCY_NORMAL, "Budget warning"),
}


class NotificationRecord:
    """A stored notification with read/unread state."""

    __slots__ = (
        "id",
        "type",
        "message",
        "urgency",
        "read",
        "created_at",
    )

    _counter = 0

    def __init__(
        self,
        notification_type: str,
        message: str,
    ) -> None:
        NotificationRecord._counter += 1
        self.id = NotificationRecord._counter
        self.type = notification_type
        self.message = message
        urgency, _ = _TYPE_CONFIG.get(
            notification_type,
            (URGENCY_NORMAL, ""),
        )
        self.urgency = urgency
        self.read = False
        self.created_at = datetime.now(tz=timezone.utc)

    @property
    def label(self) -> str:
        _, prefix = _TYPE_CONFIG.get(self.type, (URGENCY_NORMAL, self.type))
        return prefix

    def mark_read(self) -> None:
        self.read = True


class NotificationStore:
    """In-memory store for notification records."""

    def __init__(self, max_size: int = 100) -> None:
        self._records: list[NotificationRecord] = []
        self._max_size = max_size

    def add(
        self,
        notification_type: str,
        message: str,
    ) -> NotificationRecord:
        record = NotificationRecord(notification_type, message)
        self._records.append(record)
        # Trim oldest
        while len(self._records) > self._max_size:
            self._records.pop(0)

        # Terminal bell for high-urgency
        if record.urgency == URGENCY_HIGH:
            sys.stdout.write("\a")
            sys.stdout.flush()

        return record

    @property
    def records(self) -> list[NotificationRecord]:
        return list(reversed(self._records))

    @property
    def unread_count(self) -> int:
        return sum(1 for r in self._records if not r.read)

    def mark_all_read(self) -> None:
        for r in self._records:
            r.read = True

    def clear(self) -> None:
        self._records.clear()


# ── Notification list modal ─────────────────────────────────────────


class _NotificationRow(Static):
    """Single notification in the list modal."""

    def __init__(self, record: NotificationRecord, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._record = record

    def compose(self) -> ComposeResult:
        dot = "●" if not self._record.read else "○"
        color = "yellow" if self._record.urgency == URGENCY_HIGH else "dim"
        age = self._format_age()
        yield Static(
            f"  [{color}]{dot}[/{color}] "
            f"[bold]{self._record.label}:[/bold] "
            f"{self._record.message}  "
            f"[dim]{age}[/dim]",
            markup=True,
        )

    def _format_age(self) -> str:
        delta = datetime.now(tz=timezone.utc) - self._record.created_at
        secs = int(delta.total_seconds())
        if secs < 60:
            return f"{secs}s ago"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"

    def on_click(self) -> None:
        self._record.mark_read()


class NotificationListModal(ModalScreen):
    """Full notification list modal, opened via Ctrl+N."""

    DEFAULT_CSS = """
    NotificationListModal {
        align: center middle;
    }
    #notif-list-dialog {
        width: 70%;
        max-width: 90;
        height: 60%;
        max-height: 24;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #notif-list-scroll {
        height: 1fr;
    }
    #notif-list-actions {
        height: 3;
        dock: bottom;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss_modal", "Close"),
    ]

    def __init__(
        self,
        store: NotificationStore,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._store = store

    def compose(self) -> ComposeResult:
        with Vertical(id="notif-list-dialog"):
            yield Label(
                "[bold]NOTIFICATIONS[/bold]",
                markup=True,
            )
            yield VerticalScroll(id="notif-list-scroll")
            with Vertical(id="notif-list-actions"):
                yield Button(
                    "Mark all read",
                    id="notif-mark-read-btn",
                    variant="default",
                )

    async def on_mount(self) -> None:
        self._render_list()

    def _render_list(self) -> None:
        try:
            scroll = self.query_one(
                "#notif-list-scroll",
                VerticalScroll,
            )
            scroll.remove_children()

            records = self._store.records
            if not records:
                scroll.mount(
                    Static(
                        "[dim]No notifications[/dim]",
                        markup=True,
                    ),
                )
                return

            for record in records:
                scroll.mount(_NotificationRow(record))
        except Exception:
            logger.debug("notification history render failed", exc_info=True)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "notif-mark-read-btn":
            self._store.mark_all_read()
            self._render_list()

    def action_dismiss_modal(self) -> None:
        self.dismiss()
