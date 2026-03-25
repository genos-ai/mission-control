"""TeamTab — agent roster management and user prompt editing.

Two-column layout: agent list on left, agent detail with prompt
editor on right. Supports add/remove agents and prompt saving.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Label, Static

from modules.backend.core.logging import get_logger
from modules.clients.tui.widgets.prompt_editor import PromptEditor

logger = get_logger(__name__)


class AgentListItem(Static):
    """Clickable agent entry in the team list."""

    class Selected(Message):
        def __init__(self, member: dict) -> None:
            super().__init__()
            self.member = member

    def __init__(self, member: dict, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._member = member

    def compose(self) -> ComposeResult:
        name = self._member.get("agent_name", "Unknown")
        agent_type = self._member.get("agent_type", "")
        yield Static(
            f"  {name}  [dim]{agent_type}[/dim]",
            markup=True,
        )

    def on_click(self) -> None:
        self.post_message(self.Selected(member=self._member))


class TeamTab(Static):
    """Agent team management with two-column layout."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="team-container"):
            # ── Left: Agent list ──────────────────────────────────
            with Vertical(id="team-list-panel"):
                yield Label(
                    "[bold]TEAM MEMBERS[/bold]",
                    markup=True,
                    classes="sidebar-heading",
                )
                yield VerticalScroll(
                    Static(
                        "[dim]Loading team...[/dim]",
                        id="team-list-placeholder",
                        markup=True,
                    ),
                    id="team-list-scroll",
                )
                yield Button(
                    "+ Add from Catalog",
                    id="team-add-btn",
                    variant="default",
                )

            # ── Right: Agent detail ───────────────────────────────
            with Vertical(id="team-detail-panel"):
                yield Static(
                    "[dim]Select an agent to view details[/dim]",
                    id="team-detail-content",
                    markup=True,
                )

    async def on_mount(self) -> None:
        """Load team data when tab is first mounted."""
        self.run_worker(self._load_team(), thread=False)

    async def _load_team(self) -> None:
        """Fetch team members via ServiceBridge."""
        mission_id = self.app.state.current_mission_id
        if not mission_id:
            return

        try:
            members = await self.app.bridge.get_team(mission_id)
            self.app.state.team.members = members
            self._render_team_list(members)
        except Exception as exc:
            logger.warning("Could not load team", exc_info=True)
            self._show_list_error(str(exc))

    def _render_team_list(self, members: list[dict]) -> None:
        """Populate the team list with agent entries."""
        scroll = self.query_one("#team-list-scroll", VerticalScroll)
        scroll.remove_children()

        if not members:
            scroll.mount(
                Static(
                    "Your mission has no agents yet.\n"
                    "[dim]Click [bold]+ Add from Catalog[/bold] below[/dim]",
                    markup=True,
                    classes="placeholder-panel",
                ),
            )
            return

        for member in members:
            scroll.mount(AgentListItem(member, classes="mission-item"))

    def _show_list_error(self, error: str) -> None:
        scroll = self.query_one("#team-list-scroll", VerticalScroll)
        scroll.remove_children()
        scroll.mount(
            Static(f"[red]Error: {error}[/red]", markup=True),
        )

    async def on_agent_list_item_selected(
        self, event: AgentListItem.Selected,
    ) -> None:
        """Show agent detail when an item is clicked."""
        member = event.member
        self.app.state.team.selected_member = member.get("id")
        self._render_detail(member)

    def _render_detail(self, member: dict) -> None:
        """Replace the detail panel with agent info and prompt editor."""
        panel = self.query_one("#team-detail-panel", Vertical)
        # Remove old content
        try:
            old = panel.query_one("#team-detail-content")
            old.remove()
        except Exception:
            pass
        # Also remove any existing prompt editors
        for child in list(panel.children):
            if isinstance(child, (PromptEditor, Static, _AgentDetailView)):
                child.remove()

        detail = _AgentDetailView(member, id="team-detail-content")
        panel.mount(detail, before=0)

    async def on_prompt_editor_prompt_saved(
        self, event: PromptEditor.PromptSaved,
    ) -> None:
        """Save updated prompt via bridge."""
        mission_id = self.app.state.current_mission_id
        if not mission_id:
            return

        try:
            await self.app.bridge.update_team_member_prompt(
                mission_id,
                member_id=event.member_id,
                user_prompt=event.content,
            )
            self.app.notify("Prompt saved", severity="information")
        except Exception as exc:
            logger.error("Failed to save prompt", exc_info=True)
            self.app.notify(f"Save failed: {exc}", severity="error")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle add/remove buttons."""
        if event.button.id == "team-add-btn":
            from modules.clients.tui.widgets.catalog_browse_modal import (
                CatalogBrowseModal,
            )
            self.app.push_screen(CatalogBrowseModal())

        elif event.button.id == "team-remove-btn":
            await self._remove_selected_member()

    async def _remove_selected_member(self) -> None:
        """Remove the currently selected team member."""
        member_id = self.app.state.team.selected_member
        mission_id = self.app.state.current_mission_id
        if not member_id or not mission_id:
            return

        try:
            await self.app.bridge.remove_team_member(
                mission_id, member_id=member_id,
            )
            self.app.notify("Agent removed", severity="information")
            self.app.state.team.selected_member = None
            await self._load_team()
        except Exception as exc:
            logger.error("Failed to remove agent", exc_info=True)
            self.app.notify(f"Remove failed: {exc}", severity="error")


class _AgentDetailView(Static):
    """Agent detail panel showing name, type, prompts, and remove button."""

    def __init__(self, member: dict, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._member = member

    def compose(self) -> ComposeResult:
        name = self._member.get("agent_name", "Unknown")
        agent_type = self._member.get("agent_type", "")
        version = self._member.get("version", "")
        description = self._member.get("description", "")
        member_id = self._member.get("id", "")

        yield Label(
            f"[bold]{name}[/bold]  {version}  {agent_type}",
            markup=True,
        )

        if description:
            yield Static(f"[dim]{description}[/dim]", markup=True)

        yield Static("───────────────────────────────────")

        # System prompt (read-only, collapsed by default)
        system_prompt = self._member.get("system_prompt", "")
        if system_prompt:
            yield PromptEditor(
                prompt_text=system_prompt,
                label="System Prompt (read-only)",
                read_only=True,
                member_id=member_id,
            )

        # User prompt (editable)
        yield PromptEditor(
            prompt_text=self._member.get("user_prompt", ""),
            label="User Prompt",
            read_only=False,
            member_id=member_id,
        )

        yield Button(
            "Remove Agent",
            id="team-remove-btn",
            variant="error",
        )
