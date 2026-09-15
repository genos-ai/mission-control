"""Director tools: mission plan read/refine/approve and objective execution.

Registration only. Each tool lives in its own module under `tools/`,
holding its implementation as a plain async function plus the thin
`@agent.tool` wrapper (P7). Registration order is preserved from the
pre-refactor file, since it determines the order the model sees tools in.
"""

from __future__ import annotations

from pydantic_ai import Agent

from modules.backend.agents.mission.director.tools import (
    approve_plan_tasks,
    get_plan,
    refine_plan,
    run_objective,
)


def register_plan_tools(agent: Agent) -> None:
    """Register mission plan read/refine/approve/dispatch tools."""
    get_plan.register(agent)
    refine_plan.register(agent)
    approve_plan_tasks.register(agent)
    run_objective.register(agent)
