"""ASCII DAG renderer for workflow step visualization.

Renders workflow steps as a simple ASCII DAG with status icons.
Shared between WorkflowsTab and RunsTab.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static

from modules.clients.common.gate_helpers import STATUS_ICONS


class DagRenderer(Static):
    """Renders workflow steps as a simple ASCII DAG.

    Args:
        steps: List of step dicts with at least 'step_id' and optionally
            'agent_name', 'status', 'depends_on'.
    """

    def __init__(
        self,
        steps: list[dict] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._steps = steps or []

    def compose(self) -> ComposeResult:
        yield Static(self._render_dag(), markup=True)

    def update_steps(self, steps: list[dict]) -> None:
        """Re-render with updated step data."""
        self._steps = steps
        try:
            child = self.query_one(Static)
            child.update(self._render_dag())
        except Exception:
            pass

    def update_step_status(
        self, step_id: str, status: str,
    ) -> None:
        """Update a single step's status and re-render."""
        for step in self._steps:
            if step.get("step_id") == step_id:
                step["status"] = status
                break
        self.update_steps(self._steps)

    def _render_dag(self) -> str:
        """Build ASCII representation of the DAG."""
        if not self._steps:
            return "[dim]No steps[/dim]"

        # Group steps into layers based on dependencies
        layers = self._build_layers()
        lines: list[str] = []

        for layer_idx, layer in enumerate(layers):
            if layer_idx > 0:
                # Draw connector between layers
                connector = "  " + "  ".join(
                    "│" for _ in layer
                )
                lines.append(f"  [dim]{connector}[/dim]")

            row_parts: list[str] = []
            for step in layer:
                step_id = step.get("step_id", "?")
                status = step.get("status", "pending")
                icon = STATUS_ICONS.get(status, "[dim]?[/dim]")
                label = step_id[:15]
                row_parts.append(f"[{icon} {label}]")

            lines.append("  " + "  →  ".join(row_parts))

        return "\n".join(lines)

    def _build_layers(self) -> list[list[dict]]:
        """Simple topological grouping by dependency depth."""
        if not self._steps:
            return []

        # Build dependency map
        step_map = {s.get("step_id", ""): s for s in self._steps}
        depths: dict[str, int] = {}

        def _depth(step_id: str) -> int:
            if step_id in depths:
                return depths[step_id]
            step = step_map.get(step_id, {})
            deps = step.get("depends_on", []) or []
            if not deps:
                depths[step_id] = 0
            else:
                depths[step_id] = 1 + max(
                    _depth(d) for d in deps if d in step_map
                )
            return depths[step_id]

        for s in self._steps:
            _depth(s.get("step_id", ""))

        # Group by depth
        max_depth = max(depths.values()) if depths else 0
        layers: list[list[dict]] = [[] for _ in range(max_depth + 1)]
        for step in self._steps:
            sid = step.get("step_id", "")
            d = depths.get(sid, 0)
            layers[d].append(step)

        return layers
