"""Mission panel — DAG visualization with layer progress.

Renders the TaskPlan as a text-based DAG showing layers, task status
and agent assignments. Updated live as events arrive.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Label, Static

from modules.backend.schemas.task_plan import TaskDefinition, TaskPlan
from modules.clients.common.gate_helpers import STATUS_ICONS, safe_css_id
from modules.clients.tui.services.state import TaskStatusView


def _task_status_icon(
    task_id: str,
    *,
    active_tasks: set[str],
    results: dict[str, TaskStatusView],
) -> str:
    """Return the status icon for a task."""
    if task_id in results:
        return STATUS_ICONS.get(results[task_id].status, STATUS_ICONS["pending"])
    if task_id in active_tasks:
        return STATUS_ICONS["running"]
    return STATUS_ICONS["pending"]


def _agent_short_name(agent: str) -> str:
    """Extract a short display name from a dotted agent name."""
    if "." in agent:
        return agent.split(".")[-2]
    return agent


class TaskNode(Static):
    """A single task in the DAG display."""

    DEFAULT_CSS = """
    TaskNode {
        height: auto;
        min-height: 1;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        task_def: TaskDefinition,
        *,
        status_icon: str,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._task_def = task_def
        self._status_icon = status_icon

    def compose(self) -> ComposeResult:
        agent = _agent_short_name(self._task_def.agent)
        desc = self._task_def.description[:35]
        yield Label(
            f"  {self._status_icon} [{agent}] {desc}",
            markup=True,
        )


class MissionPanel(Widget):
    """DAG visualization for the active mission's TaskPlan."""

    DEFAULT_CSS = """
    MissionPanel {
        height: 1fr;
    }
    #mission-panel-header {
        height: 3;
        padding: 0 1;
        background: $surface-lighten-1;
    }
    #mission-panel-header Label {
        height: 3;
        content-align: left middle;
    }
    #dag-scroll {
        height: 1fr;
        padding: 0;
    }
    .layer-heading {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        text-style: bold;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._plan: TaskPlan | None = None
        self._layers: list[list[str]] = []
        self._results: dict[str, TaskStatusView] = {}
        self._active_tasks: set[str] = set()

    def compose(self) -> ComposeResult:
        with Vertical(id="mission-panel-header"):
            yield Label(
                "[bold]Mission Plan[/bold]  [dim]No plan loaded[/dim]",
                markup=True,
                id="mission-panel-title",
            )
        yield VerticalScroll(id="dag-scroll")

    def load_plan(
        self,
        plan: TaskPlan,
        layers: list[list[str]],
    ) -> None:
        """Load a TaskPlan and render the DAG."""
        self._plan = plan
        self._layers = layers
        self._results = {}
        self._active_tasks = set()
        self._render_dag()

    def update_task_status(
        self,
        task_id: str,
        *,
        active: bool = False,
        result: TaskStatusView | None = None,
    ) -> None:
        """Update a single task's status and refresh its node."""
        if result:
            self._results[task_id] = result
            self._active_tasks.discard(task_id)
        elif active:
            self._active_tasks.add(task_id)
        else:
            self._active_tasks.discard(task_id)
        self._refresh_task_node(task_id)
        self._update_header()

    def set_active_task(self, task_id: str) -> None:
        """Mark a task as currently executing."""
        self._active_tasks.add(task_id)
        self._refresh_task_node(task_id)

    def clear_active_task(self, task_id: str) -> None:
        """Remove a task from the active set."""
        self._active_tasks.discard(task_id)
        self._refresh_task_node(task_id)

    def _update_header(self) -> None:
        """Update the header label with current progress."""
        if not self._plan:
            return
        done = len(self._results)
        total = len(self._plan.tasks)
        title = self.query_one("#mission-panel-title", Label)
        title.update(f"[bold]Mission Plan[/bold]  [dim]{done}/{total} tasks[/dim]")

    def _render_dag(self) -> None:
        """Render the full DAG — called once when plan is loaded."""
        if not self._plan:
            return

        scroll = self.query_one("#dag-scroll", VerticalScroll)
        self._update_header()

        for layer_idx, layer_task_ids in enumerate(self._layers):
            layer_label = Label(
                f"  Layer {layer_idx}",
                classes="layer-heading",
            )
            scroll.mount(layer_label)

            for task_id in layer_task_ids:
                task_def = self._plan.get_task(task_id)
                if not task_def:
                    continue
                icon = _task_status_icon(
                    task_id,
                    active_tasks=self._active_tasks,
                    results=self._results,
                )
                safe_id = safe_css_id(task_id)
                node = TaskNode(
                    task_def,
                    status_icon=icon,
                    id=f"task-{safe_id}",
                )
                scroll.mount(node)

    def _refresh_task_node(self, task_id: str) -> None:
        """Update a single task node's display in-place."""
        if not self._plan:
            return
        safe_id = safe_css_id(task_id)
        try:
            node = self.query_one(f"#task-{safe_id}", TaskNode)
        except NoMatches:
            return
        task_def = self._plan.get_task(task_id)
        if not task_def:
            return
        icon = _task_status_icon(
            task_id,
            active_tasks=self._active_tasks,
            results=self._results,
        )
        agent = _agent_short_name(task_def.agent)
        desc = task_def.description[:35]
        node.update(f"  {icon} [{agent}] {desc}")
