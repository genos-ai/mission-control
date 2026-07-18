"""WorkflowsTab — workflow design, DAG visualization, schedule management.

Two-column layout: workflow list on left, workflow detail with
ASCII DAG and step info on right.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Label, Static

from modules.backend.core.logging import get_logger
from modules.clients.tui.widgets.dag_renderer import DagRenderer

logger = get_logger(__name__)


class _WorkflowListItem(Static):
    """Clickable workflow entry in the list."""

    class Selected(Message):
        def __init__(self, workflow_name: str) -> None:
            super().__init__()
            self.workflow_name = workflow_name

    def __init__(self, workflow: dict, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._workflow = workflow

    def compose(self) -> ComposeResult:
        name = self._workflow.get("name", "Untitled")
        trigger = self._workflow.get("trigger_type", "manual")
        trigger_icons = {"cron": "🕐", "event": "⚡", "manual": "✋"}
        icon = trigger_icons.get(trigger, "")
        enabled = self._workflow.get("enabled", True)
        status = "" if enabled else " [dim](disabled)[/dim]"
        yield Static(
            f"  {icon} {name}{status}",
            markup=True,
        )

    def on_click(self) -> None:
        name = self._workflow.get("name", "")
        self.post_message(self.Selected(workflow_name=name))


class WorkflowsTab(Static):
    """Workflow management with two-column layout."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="workflows-container"):
            # ── Left: Workflow list ───────────────────────────────
            with Vertical(id="workflows-list-panel"):
                yield Label(
                    "[bold]WORKFLOWS[/bold]",
                    markup=True,
                    classes="sidebar-heading",
                )
                yield VerticalScroll(
                    Static(
                        "[dim]Loading workflows...[/dim]",
                        id="workflows-list-placeholder",
                        markup=True,
                    ),
                    id="workflows-list-scroll",
                )
                yield Button(
                    "+ New Workflow",
                    id="workflows-new-btn",
                    variant="default",
                )

            # ── Right: Workflow detail ────────────────────────────
            with VerticalScroll(id="workflows-detail-panel"):
                yield Static(
                    "[dim]Select a workflow to view details[/dim]",
                    id="workflows-detail-content",
                    markup=True,
                )

    async def on_mount(self) -> None:
        self.run_worker(self._load_workflows(), thread=False)

    async def _load_workflows(self) -> None:
        """Fetch workflows via ServiceBridge."""
        mission_id = self.app.state.current_mission_id
        if not mission_id:
            return

        try:
            workflows = await self.app.bridge.list_workflows(mission_id)
            self.app.state.workflow.workflows = workflows
            self._render_workflow_list(workflows)
        except Exception as exc:
            logger.warning("Could not load workflows", exc_info=True)
            self._show_list_error(str(exc))

    def _render_workflow_list(self, workflows: list[dict]) -> None:
        """Populate the workflow list."""
        scroll = self.query_one(
            "#workflows-list-scroll",
            VerticalScroll,
        )
        scroll.remove_children()

        if not workflows:
            scroll.mount(
                Static(
                    "No workflows yet.\n"
                    "Design one with the Architect or import a template.\n"
                    "[dim]Click [bold]+ New Workflow[/bold] below[/dim]",
                    markup=True,
                    classes="placeholder-panel",
                ),
            )
            return

        for wf in workflows:
            scroll.mount(
                _WorkflowListItem(wf, classes="mission-item"),
            )

    def _show_list_error(self, error: str) -> None:
        scroll = self.query_one(
            "#workflows-list-scroll",
            VerticalScroll,
        )
        scroll.remove_children()
        scroll.mount(
            Static(f"[red]Error: {error}[/red]", markup=True),
        )

    async def on__workflow_list_item_selected(
        self,
        event: _WorkflowListItem.Selected,
    ) -> None:
        """Show workflow detail when an item is clicked."""
        self.app.state.workflow.selected_workflow = event.workflow_name
        self.run_worker(
            self._load_detail(event.workflow_name),
            thread=False,
        )

    async def _load_detail(self, workflow_name: str) -> None:
        """Fetch and display workflow detail."""
        try:
            detail = await self.app.bridge.get_workflow_detail(
                workflow_name,
            )
            if detail:
                self._render_detail(detail)
        except Exception as exc:
            logger.warning("Could not load workflow detail", exc_info=True)
            self.app.notify(
                f"Could not load workflow: {exc}",
                severity="error",
            )

    def _render_detail(self, detail: dict) -> None:
        """Render workflow detail in the right panel."""
        panel = self.query_one(
            "#workflows-detail-panel",
            VerticalScroll,
        )
        panel.remove_children()

        name = detail.get("name", "Unknown")
        description = detail.get("description", "")
        trigger = detail.get("trigger_type", "manual")
        steps = detail.get("steps", [])

        # ── Header ────────────────────────────────────────────
        panel.mount(
            Label(f"[bold]{name}[/bold]", markup=True),
        )
        if description:
            panel.mount(
                Static(f"[dim]{description}[/dim]", markup=True),
            )

        panel.mount(
            Static("────────────────────────────────────"),
        )

        # ── DAG visualization ─────────────────────────────────
        if steps:
            dag_steps = [
                {
                    "step_id": s.get("step_id", s.get("name", "?")),
                    "agent_name": s.get("agent_name", ""),
                    "status": "pending",
                    "depends_on": s.get("depends_on", []),
                }
                for s in steps
            ]
            panel.mount(
                Label("[bold]DAG:[/bold]", markup=True),
            )
            panel.mount(DagRenderer(dag_steps))

        # ── Trigger info ──────────────────────────────────────
        trigger_icons = {
            "cron": "🕐",
            "event": "⚡",
            "manual": "✋",
        }
        icon = trigger_icons.get(trigger, "")
        schedule = detail.get("schedule", "")
        panel.mount(
            Static(
                f"\n[bold]Trigger:[/bold] {icon} {trigger}"
                + (f"  ({schedule})" if schedule else ""),
                markup=True,
            ),
        )

        # ── Step list ─────────────────────────────────────────
        if steps:
            panel.mount(
                Label("\n[bold]── STEPS ──[/bold]", markup=True),
            )
            for i, step in enumerate(steps, 1):
                step_id = step.get(
                    "step_id",
                    step.get("name", "?"),
                )
                agent = step.get("agent_name", "")
                gate = step.get("gate", "")
                deps = step.get("depends_on", [])
                line = f"  {i}. {step_id}"
                if agent:
                    line += f"  → {agent}"
                if gate:
                    line += f"  [dim]Gate: {gate}[/dim]"
                if deps:
                    line += f"  [dim]After: {', '.join(deps)}[/dim]"
                panel.mount(Static(line, markup=True))

        # ── Action buttons ────────────────────────────────────
        panel.mount(Static("\n"))
        actions = Horizontal(classes="prompt-editor-actions")
        panel.mount(actions)
        actions.mount(
            Button(
                "▶ Run Now",
                id="workflows-run-btn",
                variant="success",
            ),
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle workflow action buttons."""
        if event.button.id == "workflows-new-btn":
            self.app.notify(
                "Architect workflow design coming soon",
                severity="information",
            )
        elif event.button.id == "workflows-run-btn":
            await self._run_selected_workflow()

    async def _run_selected_workflow(self) -> None:
        """Run the currently selected workflow."""
        workflow_name = self.app.state.workflow.selected_workflow
        mission_id = self.app.state.current_mission_id
        if not workflow_name or not mission_id:
            return

        self.app.notify(
            f"Triggering {workflow_name}...",
            severity="information",
        )
