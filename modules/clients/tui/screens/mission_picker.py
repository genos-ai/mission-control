"""Mission picker modal — create or select a mission on launch.

Shown when the TUI starts without a pre-selected mission,
or when the user presses Ctrl+P.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from modules.clients.tui.messages import MissionCreated, MissionSelected


class MissionItem(Static):
    """A clickable mission row."""

    DEFAULT_CSS = """
    MissionItem {
        height: 3;
        padding: 0 1;
    }
    MissionItem:hover {
        background: $primary-background;
    }
    """

    def __init__(
        self, mission_id: str, mission_name: str, description: str, **kwargs: object
    ) -> None:
        super().__init__(**kwargs)
        self.mission_id = mission_id
        self.mission_name = mission_name
        self.description = description

    def compose(self) -> ComposeResult:
        yield Label(
            f"[bold]{self.mission_name}[/bold]  [dim]{self.description[:50]}[/dim]",
            markup=True,
        )

    def on_click(self) -> None:
        self.post_message(
            MissionSelected(
                mission_id=self.mission_id,
                mission_name=self.mission_name,
            )
        )


class MissionPickerScreen(ModalScreen[None]):
    """Modal screen for mission selection or creation."""

    DEFAULT_CSS = """
    MissionPickerScreen {
        align: center middle;
    }
    #picker-dialog {
        width: 60;
        height: auto;
        max-height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #picker-dialog Label {
        margin: 0 0 1 0;
    }
    #mission-list {
        max-height: 12;
    }
    #new-mission-section {
        margin-top: 1;
        border-top: solid $surface-lighten-2;
        padding-top: 1;
    }
    #new-mission-section Input {
        margin: 0 0 1 0;
    }
    """

    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, missions: list[dict[str, str]], **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._missions = missions

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-dialog"):
            yield Label("[bold]Select Mission[/bold]", markup=True)

            with VerticalScroll(id="mission-list"):
                for m in self._missions:
                    yield MissionItem(
                        mission_id=m["id"],
                        mission_name=m["name"],
                        description=m.get("description", ""),
                    )

            with Vertical(id="new-mission-section"):
                yield Label("[bold]— or create new —[/bold]", markup=True)
                yield Input(
                    placeholder="Mission name",
                    id="new-mission-name",
                )
                yield Input(
                    placeholder="Description",
                    id="new-mission-desc",
                )
                yield Button("Create", id="create-mission-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-mission-btn":
            name_input = self.query_one("#new-mission-name", Input)
            desc_input = self.query_one("#new-mission-desc", Input)
            name = name_input.value.strip()
            desc = desc_input.value.strip()
            if name:
                self.post_message(MissionCreated(mission_name=name, description=desc))
                self.dismiss()

    def on_mission_selected(self, event: MissionSelected) -> None:
        """Bubble up and dismiss."""
        self.dismiss()
