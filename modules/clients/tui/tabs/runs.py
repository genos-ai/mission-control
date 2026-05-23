"""RunsTab — completed run history, audit trail, output viewing.

Shows a scrollable list of past runs with inline expansion for
run details, DAG progress, decisions, and cost breakdown.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Label, Static

from modules.backend.core.logging import get_logger
from modules.clients.common.gate_helpers import STATUS_ICONS

logger = get_logger(__name__)


class _RunRow(Static):
    """Clickable run entry in the history list."""

    class Selected(Message):
        def __init__(self, execution_id: str) -> None:
            super().__init__()
            self.execution_id = execution_id

    def __init__(self, run: dict, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._run = run

    def compose(self) -> ComposeResult:
        status = self._run.get("status", "?")
        obj = (self._run.get("objective", "") or "")[:40] or "(no objective)"
        cost = self._run.get("total_cost_usd", 0.0)
        roster = self._run.get("roster_name", "")
        created = self._run.get("created_at", "")[:16]

        # Handle enum-like status
        status_str = status.value if hasattr(status, "value") else str(status)
        icon = STATUS_ICONS.get(status_str, "[dim]?[/dim]")

        yield Static(
            f"  {icon}  {obj}  [dim]{roster}  ${cost:.2f}  {created}[/dim]",
            markup=True,
        )

    def on_click(self) -> None:
        eid = self._run.get("id", "")
        self.post_message(self.Selected(execution_id=eid))


class RunsTab(Static):
    """Run history with expandable rows and detail panel."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="runs-container"):
            # ── Left: Run list ────────────────────────────────────
            with Vertical(id="runs-list-panel"):
                yield Label(
                    "[bold]RUN HISTORY[/bold]",
                    markup=True,
                    classes="sidebar-heading",
                )
                yield VerticalScroll(
                    Static(
                        "[dim]Loading runs...[/dim]",
                        id="runs-list-placeholder",
                        markup=True,
                    ),
                    id="runs-list-scroll",
                )
                with Horizontal(id="runs-pagination"):
                    yield Button("◄ Prev", id="runs-prev-btn")
                    yield Label(
                        "Page 1",
                        id="runs-page-label",
                        markup=True,
                    )
                    yield Button("Next ►", id="runs-next-btn")

            # ── Right: Run detail ─────────────────────────────────
            with VerticalScroll(id="runs-detail-panel"):
                yield Static(
                    "[dim]Select a run to view details[/dim]",
                    id="runs-detail-content",
                    markup=True,
                )

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._page = 0
        self._page_size = 20
        self._total = 0

    async def on_mount(self) -> None:
        self.run_worker(self._load_runs(), thread=False)

    async def _load_runs(self) -> None:
        """Fetch runs for current page."""
        try:
            runs, total = await self.app.bridge.list_executions_paginated(
                limit=self._page_size,
                offset=self._page * self._page_size,
            )
            self._total = total
            self._render_list(runs)
            self._update_page_label()
        except Exception as exc:
            logger.warning("Could not load runs", exc_info=True)
            scroll = self.query_one(
                "#runs-list-scroll", VerticalScroll,
            )
            scroll.remove_children()
            scroll.mount(
                Static(f"[red]Error: {exc}[/red]", markup=True),
            )

    def _render_list(self, runs: list[dict]) -> None:
        scroll = self.query_one("#runs-list-scroll", VerticalScroll)
        scroll.remove_children()

        if not runs:
            scroll.mount(
                Static(
                    "No runs yet.\n"
                    "Go to Workflows (Alt+4) to trigger your first run.",
                    markup=True,
                    classes="placeholder-panel",
                ),
            )
            return

        for run in runs:
            scroll.mount(_RunRow(run, classes="mission-item"))

    def _update_page_label(self) -> None:
        total_pages = max(
            1, (self._total + self._page_size - 1) // self._page_size,
        )
        try:
            label = self.query_one("#runs-page-label", Label)
            label.update(f"Page {self._page + 1}/{total_pages}")
        except Exception:
            logger.debug("runs page label update failed", exc_info=True)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "runs-prev-btn" and self._page > 0:
            self._page -= 1
            self.run_worker(self._load_runs(), thread=False)
        elif event.button.id == "runs-next-btn":
            total_pages = max(
                1,
                (self._total + self._page_size - 1) // self._page_size,
            )
            if self._page + 1 < total_pages:
                self._page += 1
                self.run_worker(self._load_runs(), thread=False)

    async def on__run_row_selected(
        self, event: _RunRow.Selected,
    ) -> None:
        """Show run detail when clicked."""
        self.run_worker(
            self._load_detail(event.execution_id), thread=False,
        )

    async def _load_detail(self, execution_id: str) -> None:
        """Fetch and render run detail."""
        try:
            detail = await self.app.bridge.get_execution_detail(
                execution_id,
            )
            if detail:
                self._render_detail(detail)
        except Exception as exc:
            logger.warning(
                "Could not load run detail", exc_info=True,
            )
            self.app.notify(
                f"Could not load run: {exc}", severity="error",
            )

    def _render_detail(self, detail: dict) -> None:
        """Render run detail in the right panel."""
        panel = self.query_one(
            "#runs-detail-panel", VerticalScroll,
        )
        panel.remove_children()

        objective = detail.get("objective", "(no objective)")
        status = detail.get("status", "?")
        cost = detail.get("total_cost_usd", 0.0)
        roster = detail.get("roster_name", "")
        created = detail.get("created_at", "")

        status_str = (
            status.value if hasattr(status, "value") else str(status)
        )

        panel.mount(
            Label(f"[bold]{objective}[/bold]", markup=True),
        )
        panel.mount(
            Static(
                f"Status: {status_str}  |  Cost: ${cost:.2f}\n"
                f"Roster: {roster}  |  Created: {created}",
                markup=True,
            ),
        )
        panel.mount(
            Static("────────────────────────────────────"),
        )

        # ── Task executions ───────────────────────────────────
        tasks = detail.get("task_executions", [])
        if tasks:
            panel.mount(
                Label("[bold]── TASKS ──[/bold]", markup=True),
            )
            for t in tasks:
                task_id = t.get("task_id", "?")
                agent = t.get("agent_name", "?")
                t_status = t.get("status", "?")
                t_cost = t.get("cost_usd", 0.0)
                t_status_str = (
                    t_status.value
                    if hasattr(t_status, "value")
                    else str(t_status)
                )
                panel.mount(
                    Static(
                        f"  {task_id}  → {agent}  "
                        f"{t_status_str}  ${t_cost:.3f}",
                        markup=True,
                    ),
                )

        # ── Action buttons ────────────────────────────────────
        eid = detail.get("id", "")
        panel.mount(Static("\n"))
        panel.mount(
            Button(
                "View Cost Breakdown",
                id=f"runs-cost-{eid}",
                variant="default",
            ),
        )
