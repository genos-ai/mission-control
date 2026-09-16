"""Director tools: workflow discovery, background-forked workflow runs, design.

Registration only. Each tool lives in its own module under `tools/`,
holding its implementation as a plain async function plus the thin
`@agent.tool` wrapper (P7). Registration order is preserved from the
pre-refactor file, since it determines the order the model sees tools in.

The fork helpers that previously lived here moved to `tools/_fork.py`,
and `_schedule_director_followup` moved to `tool_helpers` as
`schedule_director_followup`, since the plan tools use it too.

Note: start_research was removed in Plan 72. Research now goes through
refine_plan, where the Planning Agent decomposes it into individual
tasks with dependencies. The research_loop executor in
dispatch/research_loop.py is preserved for future conversion to a
workflow template.
"""

from __future__ import annotations

from pydantic_ai import Agent

from modules.backend.agents.mission.director.tools import (
    design_workflow,
    list_workflows,
    run_workflow,
)


def register_workflow_tools(agent: Agent) -> None:
    """Register workflow discovery/run/design tools on the Director agent."""
    list_workflows.register(agent)
    run_workflow.register(agent)
    design_workflow.register(agent)
