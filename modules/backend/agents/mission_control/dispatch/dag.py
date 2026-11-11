"""DAG utilities for the dispatch loop.

Topological sorting and upstream input resolution — pure functions
with no side effects or external dependencies.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from modules.backend.schemas.task_plan import TaskDefinition, TaskPlan


class UpstreamOutputMissingError(KeyError):
    """A from_upstream reference has no output to read (Plan 88, contracts 3.5.5)."""

    def __init__(self, message: str, *, source_task: str, source_field: str) -> None:
        super().__init__(message)
        self.message = message
        self.source_task = source_task
        self.source_field = source_field

    def __str__(self) -> str:
        return self.message


def topological_sort(plan: TaskPlan) -> list[list[str]]:
    """Sort tasks into execution layers. Each layer runs in parallel.

    Returns a list of layers, where each layer is a list of task_ids
    that can execute concurrently. Assumes DAG validation already passed.
    """
    task_ids = {t.task_id for t in plan.tasks}
    in_degree: dict[str, int] = {tid: 0 for tid in task_ids}
    dependents: dict[str, list[str]] = {tid: [] for tid in task_ids}

    for task in plan.tasks:
        for dep in task.dependencies:
            dependents[dep].append(task.task_id)
            in_degree[task.task_id] += 1

    layers: list[list[str]] = []
    queue: deque[str] = deque(tid for tid, deg in in_degree.items() if deg == 0)

    while queue:
        layer = list(queue)
        queue.clear()
        layers.append(layer)

        for node in layer:
            for neighbor in dependents[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

    return layers


def resolve_upstream_inputs(
    task: TaskDefinition,
    completed_outputs: dict[str, dict],
) -> dict[str, Any]:
    """Resolve from_upstream references using outputs from completed tasks.

    Returns the merged input dict (static + resolved upstream).
    Raises UpstreamOutputMissingError if a referenced task or field is missing.
    """
    resolved = dict(task.inputs.static)

    for field_name, ref_or_list in task.inputs.from_upstream.items():
        refs = ref_or_list if isinstance(ref_or_list, list) else [ref_or_list]
        values = []
        for ref in refs:
            source_output = completed_outputs.get(ref.source_task)
            if source_output is None:
                raise UpstreamOutputMissingError(
                    f"Task '{task.task_id}': upstream task '{ref.source_task}' "
                    f"has no output (did it fail?)",
                    source_task=ref.source_task,
                    source_field=ref.source_field,
                )
            if ref.source_field not in source_output:
                raise UpstreamOutputMissingError(
                    f"Task '{task.task_id}': upstream task '{ref.source_task}' "
                    f"output missing field '{ref.source_field}'",
                    source_task=ref.source_task,
                    source_field=ref.source_field,
                )
            values.append(source_output[ref.source_field])
        # Single ref → unwrap; list of refs → keep as list
        resolved[field_name] = values[0] if len(values) == 1 else values

    return resolved
