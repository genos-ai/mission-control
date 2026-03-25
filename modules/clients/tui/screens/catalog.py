"""CatalogScreen — global agent catalog browse (read-only).

Accessible via Ctrl+G. Two-column layout with searchable agent list
on the left and agent detail on the right.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Input, Label, Static

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


class _CatalogListItem(Static):
    """Clickable agent entry in the catalog list."""

    def __init__(self, agent: dict, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._agent = agent

    def compose(self) -> ComposeResult:
        name = self._agent.get("agent_name", "Unknown")
        agent_type = self._agent.get("agent_type", "")
        version = self._agent.get("version", "")
        yield Static(
            f"  {name}  [dim]{agent_type}  v{version}[/dim]",
            markup=True,
        )

    def on_click(self) -> None:
        # Find the parent CatalogScreen and tell it to show detail
        screen = self.screen
        if isinstance(screen, CatalogScreen):
            screen.show_agent_detail(self._agent)


class CatalogScreen(Screen):
    """Global agent catalog — read-only browse."""

    BINDINGS = [("escape", "app.goto_dashboard", "Back")]

    def compose(self) -> ComposeResult:
        with Horizontal(id="catalog-header"):
            yield Label(
                "[bold]AGENT CATALOG[/bold]",
                id="catalog-title",
                markup=True,
            )
            yield Label(
                "[dim]Esc to go back[/dim]",
                markup=True,
            )

        with Horizontal(id="catalog-body"):
            # ── Left: Search + agent list ─────────────────────────
            with Vertical(id="catalog-list-panel"):
                yield Input(
                    placeholder="Search agents...",
                    id="catalog-search",
                )
                yield VerticalScroll(
                    Static(
                        "[dim]Loading...[/dim]",
                        id="catalog-list-placeholder",
                        markup=True,
                    ),
                    id="catalog-list-scroll",
                )

            # ── Right: Agent detail ───────────────────────────────
            with Vertical(id="catalog-detail-panel"):
                yield Static(
                    "[dim]Select an agent to view details[/dim]",
                    id="catalog-detail-content",
                    markup=True,
                )

    async def on_mount(self) -> None:
        self.run_worker(self._load_catalog(), thread=False)

    async def _load_catalog(self) -> None:
        """Fetch all catalog agents."""
        try:
            agents = await self.app.bridge.list_catalog_agents()
            self._all_agents = agents
            self._render_list(agents)
        except Exception as exc:
            logger.warning("Could not load catalog", exc_info=True)
            scroll = self.query_one(
                "#catalog-list-scroll", VerticalScroll,
            )
            scroll.remove_children()
            scroll.mount(
                Static(f"[red]Error: {exc}[/red]", markup=True),
            )

    def _render_list(self, agents: list[dict]) -> None:
        """Populate the agent list."""
        scroll = self.query_one("#catalog-list-scroll", VerticalScroll)
        scroll.remove_children()

        if not agents:
            scroll.mount(
                Static("[dim]No agents found[/dim]", markup=True),
            )
            return

        for agent in agents:
            scroll.mount(
                _CatalogListItem(agent, classes="mission-item"),
            )

    async def on_input_changed(self, event: Input.Changed) -> None:
        """Filter the catalog list as user types."""
        if event.input.id != "catalog-search":
            return

        query = event.value.lower().strip()
        if not query:
            self._render_list(getattr(self, "_all_agents", []))
            return

        filtered = [
            a for a in getattr(self, "_all_agents", [])
            if query in a.get("agent_name", "").lower()
            or query in a.get("description", "").lower()
            or any(query in k.lower() for k in a.get("keywords", []))
        ]
        self._render_list(filtered)

    def show_agent_detail(self, agent: dict) -> None:
        """Display agent detail in the right panel."""
        panel = self.query_one("#catalog-detail-panel", Vertical)
        # Remove old content
        try:
            old = panel.query_one("#catalog-detail-content")
            old.remove()
        except Exception:
            pass

        name = agent.get("agent_name", "Unknown")
        agent_type = agent.get("agent_type", "")
        version = agent.get("version", "")
        description = agent.get("description", "")
        keywords = agent.get("keywords", [])
        tools = agent.get("tools", [])
        constraints = agent.get("constraints", {})

        lines = [
            f"[bold]{name}[/bold]",
            f"Type: {agent_type}  Version: {version}",
            "",
        ]
        if description:
            lines.append(f"[bold]Description:[/bold]\n{description}")
            lines.append("")
        if keywords:
            lines.append(
                f"[bold]Keywords:[/bold] {', '.join(keywords)}",
            )
        if tools:
            lines.append(f"\n[bold]Tools:[/bold]")
            for tool in tools:
                lines.append(f"  - {tool}")
        if constraints:
            lines.append(f"\n[bold]Constraints:[/bold]")
            for k, v in constraints.items():
                lines.append(f"  {k}: {v}")

        detail = Static(
            "\n".join(lines),
            id="catalog-detail-content",
            markup=True,
        )
        panel.mount(detail, before=0)
