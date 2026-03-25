"""ContextTab — mission context document and change history.

Two-column layout: rendered context document on left, chronological
change history on right. Context accumulates automatically as
workflows run.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Label, Markdown, Static

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


class _ChangeEntry(Static):
    """Clickable change history entry."""

    def __init__(self, change: dict, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._change = change

    def compose(self) -> ComposeResult:
        agent = self._change.get("agent_id", "system")
        created = self._change.get("created_at", "")[:16]
        summary = self._change.get("summary", "Context updated")
        version = self._change.get("version", "?")

        yield Static(
            f"  v{version} · {created}\n"
            f"  [dim]{agent}: {summary}[/dim]",
            markup=True,
        )


class ContextTab(Static):
    """Mission context document with change history."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="context-container"):
            # ── Left: Context document ────────────────────────────
            with Vertical(id="context-doc-panel"):
                yield Label(
                    "[bold]MISSION CONTEXT[/bold]",
                    markup=True,
                    classes="sidebar-heading",
                )
                yield VerticalScroll(
                    Markdown(
                        "*Loading context...*",
                        id="context-markdown",
                    ),
                    id="context-doc-scroll",
                )
                with Horizontal(id="context-actions"):
                    yield Button(
                        "Refresh",
                        id="context-refresh-btn",
                        variant="default",
                    )
                    yield Label(
                        "",
                        id="context-size-label",
                    )

            # ── Right: Change history ─────────────────────────────
            with Vertical(id="context-history-panel"):
                yield Label(
                    "[bold]CHANGE HISTORY[/bold]",
                    markup=True,
                    classes="sidebar-heading",
                )
                yield VerticalScroll(
                    Static(
                        "[dim]Loading history...[/dim]",
                        id="context-history-placeholder",
                        markup=True,
                    ),
                    id="context-history-scroll",
                )

    async def on_mount(self) -> None:
        self.run_worker(self._load_context(), thread=False)

    async def _load_context(self) -> None:
        """Fetch and display context document and history."""
        mission_id = self.app.state.current_mission_id
        if not mission_id:
            return

        # Load context document and history in parallel via sequential calls
        try:
            context = await self.app.bridge.get_mission_context(mission_id)
            self._render_context(context)
        except Exception as exc:
            logger.warning("Could not load context", exc_info=True)
            self._show_empty_state()

        try:
            history = await self.app.bridge.get_context_history(
                mission_id, limit=50,
            )
            self._render_history(history)
        except Exception as exc:
            logger.warning("Could not load context history", exc_info=True)

        # Load size info
        try:
            size_info = await self.app.bridge.get_context_size(mission_id)
            self._render_size(size_info)
        except Exception:
            pass

    def _render_context(self, context: dict[str, Any]) -> None:
        """Render context document as markdown."""
        try:
            md_widget = self.query_one("#context-markdown", Markdown)

            if not context:
                self._show_empty_state()
                return

            # Build markdown from context sections
            lines: list[str] = []

            identity = context.get("identity", {})
            if identity:
                lines.append("## Identity")
                if identity.get("name"):
                    lines.append(f"**Mission:** {identity['name']}")
                if identity.get("description"):
                    lines.append(f"\n{identity['description']}")
                lines.append("")

            architecture = context.get("architecture", {})
            if architecture:
                lines.append("## Architecture")
                for key, val in architecture.items():
                    if isinstance(val, list):
                        lines.append(f"**{key}:**")
                        for item in val:
                            lines.append(f"- {item}")
                    elif val:
                        lines.append(f"**{key}:** {val}")
                lines.append("")

            decisions = context.get("decisions", [])
            if decisions:
                lines.append("## Active Decisions")
                for d in decisions:
                    if isinstance(d, dict):
                        lines.append(
                            f"- **{d.get('decision', '')}** — "
                            f"{d.get('rationale', '')}",
                        )
                    else:
                        lines.append(f"- {d}")
                lines.append("")

            current_state = context.get("current_state", {})
            if current_state:
                lines.append("## Current State")
                for key, val in current_state.items():
                    if isinstance(val, list):
                        lines.append(f"**{key}:**")
                        for item in val:
                            lines.append(f"- {item}")
                    elif val:
                        lines.append(f"**{key}:** {val}")
                lines.append("")

            guardrails = context.get("guardrails", {})
            if guardrails:
                lines.append("## Guardrails")
                for key, val in guardrails.items():
                    if isinstance(val, list):
                        lines.append(f"**{key}:**")
                        for item in val:
                            lines.append(f"- {item}")
                    elif val:
                        lines.append(f"**{key}:** {val}")
                lines.append("")

            version = context.get("version", "")
            updated = context.get("last_updated", "")
            updated_by = context.get("last_updated_by", "")
            if version or updated:
                lines.append("---")
                lines.append(
                    f"*Version {version} · "
                    f"Updated {updated} by {updated_by}*",
                )

            md_text = "\n".join(lines) if lines else "*Empty context*"
            md_widget.update(md_text)
        except Exception:
            pass

    def _show_empty_state(self) -> None:
        """Show placeholder when no context exists."""
        try:
            md_widget = self.query_one("#context-markdown", Markdown)
            md_widget.update(
                "No context accumulated yet.\n\n"
                "Context builds automatically as your workflows run.\n"
                "The mission brief serves as initial context for "
                "your agents.",
            )
        except Exception:
            pass

    def _render_history(self, history: list[dict[str, Any]]) -> None:
        """Render change history entries."""
        try:
            scroll = self.query_one(
                "#context-history-scroll", VerticalScroll,
            )
            scroll.remove_children()

            if not history:
                scroll.mount(
                    Static(
                        "[dim]No changes recorded yet[/dim]",
                        markup=True,
                    ),
                )
                return

            for change in history:
                scroll.mount(
                    _ChangeEntry(change, classes="mission-item"),
                )
        except Exception:
            pass

    def _render_size(self, size_info: dict[str, Any]) -> None:
        """Show context size in the footer."""
        try:
            label = self.query_one("#context-size-label", Label)
            chars = size_info.get("size_characters", 0)
            pct = size_info.get("pct_of_max", 0.0)
            version = size_info.get("version", 0)

            color = "green"
            if pct > 75:
                color = "yellow"
            if pct > 90:
                color = "red"

            label.update(
                f"[{color}]v{version} · {chars:,} chars · "
                f"{pct:.0f}% capacity[/{color}]",
            )
        except Exception:
            pass

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "context-refresh-btn":
            self.run_worker(self._load_context(), thread=False)
