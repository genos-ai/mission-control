"""Dispatch package — Mission Control task execution engine.

Re-exports the public API so existing consumers continue to work
with ``from modules.backend.agents.mission_control.dispatch import ...``.
"""

from modules.backend.agents.mission_control.dispatch.dag import (
    resolve_upstream_inputs,
    topological_sort,
)
from modules.backend.agents.mission_control.dispatch.loop import dispatch
from modules.backend.agents.mission_control.dispatch.step_executor import verify_task

__all__ = [
    "dispatch",
    "resolve_upstream_inputs",
    "topological_sort",
    "verify_task",
]
