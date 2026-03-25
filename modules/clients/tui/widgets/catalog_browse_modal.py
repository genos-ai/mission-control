"""CatalogBrowseModal — full-screen modal for browsing and adding agents.

Opened from TeamTab's [+ Add from Catalog] button. Shows searchable
agent list with [+ Add] buttons per agent.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


class AgentAdded(Message):
    """Posted when user adds an agent from the catalog modal."""

    def __init__(self, agent_name: str) -> None:
        super().__init__()
        self.agent_name = agent_name


class _CatalogAgentRow(Static):
    """Single agent row in the catalog browse list."""

    def __init__(self, agent: dict, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._agent = agent

    def compose(self) -> ComposeResult:
        name = self._agent.get("agent_name", "Unknown")
        agent_type = self._agent.get("agent_type", "")
        version = self._agent.get("version", "")
        description = self._agent.get("description", "")[:60]

        with Horizontal(classes="catalog-row"):
            yield Static(
                f"[bold]{name}[/bold]  {agent_type}  v{version}\n"
                f"[dim]{description}[/dim]",
                markup=True,
                classes="catalog-row-info",
            )
            yield Button(
                "+ Add",
                id=f"add-{name}",
                variant="success",
                classes="catalog-add-btn",
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id and event.button.id.startswith("add-"):
            agent_name = self._agent.get("agent_name", "")
            self.post_message(AgentAdded(agent_name=agent_name))


class CatalogBrowseModal(ModalScreen[None]):
    """Full-screen catalog browse for adding agents to team."""

    BINDINGS = [("escape", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(id="catalog-modal-dialog"):
            with Horizontal(id="catalog-modal-header"):
                yield Label(
                    "[bold]AGENT CATALOG[/bold]",
                    markup=True,
                )
                yield Label("[dim]Esc to close[/dim]", markup=True)

            yield Input(
                placeholder="Search agents...",
                id="catalog-search-input",
            )

            yield VerticalScroll(
                Static(
                    "[dim]Loading catalog...[/dim]",
                    id="catalog-list-placeholder",
                    markup=True,
                ),
                id="catalog-modal-list",
            )

    async def on_mount(self) -> None:
        self.run_worker(self._load_catalog(), thread=False)

    async def _load_catalog(self) -> None:
        """Load all enabled agents from catalog."""
        try:
            agents = await self.app.bridge.list_catalog_agents()
            self._all_agents = agents
            self._render_agents(agents)
        except Exception as exc:
            logger.warning("Could not load catalog", exc_info=True)
            scroll = self.query_one(
                "#catalog-modal-list", VerticalScroll,
            )
            scroll.remove_children()
            scroll.mount(
                Static(f"[red]Error: {exc}[/red]", markup=True),
            )

    def _render_agents(self, agents: list[dict]) -> None:
        """Populate the agent list."""
        scroll = self.query_one("#catalog-modal-list", VerticalScroll)
        scroll.remove_children()

        if not agents:
            scroll.mount(
                Static(
                    "[dim]No agents found[/dim]",
                    markup=True,
                ),
            )
            return

        for agent in agents:
            scroll.mount(_CatalogAgentRow(agent))

    async def on_input_changed(self, event: Input.Changed) -> None:
        """Filter catalog list as user types."""
        query = event.value.lower().strip()
        if not query:
            self._render_agents(getattr(self, "_all_agents", []))
            return

        filtered = [
            a for a in getattr(self, "_all_agents", [])
            if query in a.get("agent_name", "").lower()
            or query in a.get("description", "").lower()
            or any(query in k.lower() for k in a.get("keywords", []))
        ]
        self._render_agents(filtered)

    async def on_agent_added(self, event: AgentAdded) -> None:
        """Add agent to team and dismiss modal."""
        mission_id = self.app.state.current_mission_id
        if not mission_id:
            return

        try:
            await self.app.bridge.add_team_member(
                mission_id, agent_name=event.agent_name,
            )
            self.app.notify(
                f"Added {event.agent_name} to team",
                severity="information",
            )
            self.dismiss()
        except Exception as exc:
            logger.error("Failed to add agent", exc_info=True)
            self.app.notify(f"Add failed: {exc}", severity="error")
