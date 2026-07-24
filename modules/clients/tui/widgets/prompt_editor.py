"""Reusable prompt editor widget with save and version indicator.

Used by TeamTab for user prompt editing and WorkshopTab for prompt
iteration. Supports read-only mode for system prompts.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, Label, Static, TextArea


class PromptEditor(Static):
    """Editable prompt TextArea with save button and version label.

    Args:
        prompt_text: Initial prompt content.
        label: Header label (e.g. "User Prompt", "System Prompt").
        read_only: If True, disables editing and hides save button.
        member_id: Team member ID for save callbacks.
    """

    class PromptSaved(Message):
        """Emitted when user clicks Save."""

        def __init__(
            self,
            *,
            member_id: str,
            content: str,
        ) -> None:
            super().__init__()
            self.member_id = member_id
            self.content = content

    def __init__(
        self,
        *,
        prompt_text: str = "",
        label: str = "Prompt",
        read_only: bool = False,
        member_id: str = "",
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._prompt_text = prompt_text
        self._label = label
        self._read_only = read_only
        self._member_id = member_id

    def compose(self) -> ComposeResult:
        yield Label(
            f"[bold]{self._label}[/bold]",
            markup=True,
            classes="prompt-editor-label",
        )
        yield TextArea(
            self._prompt_text,
            id="prompt-textarea",
            read_only=self._read_only,
        )
        if not self._read_only:
            with Horizontal(classes="prompt-editor-actions"):
                yield Button("Save", id="prompt-save-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "prompt-save-btn":
            textarea = self.query_one("#prompt-textarea", TextArea)
            self.post_message(
                self.PromptSaved(
                    member_id=self._member_id,
                    content=textarea.text,
                ),
            )

    def set_content(self, text: str) -> None:
        """Update the textarea content programmatically."""
        textarea = self.query_one("#prompt-textarea", TextArea)
        textarea.load_text(text)
