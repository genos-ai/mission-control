"""
Mission Supervisor Agent (Plan 51 Phase D).

Two agent factories sharing the same deps and tools but with
different output types:

- create_event_agent → Agent[MissionSupervisorDeps, SupervisorDecision]
    Structured output for branch #8 of the decision matrix.
    Called by AutonomousPostRunReviewer when Haiku classification
    is needed.

- create_agent → Agent[MissionSupervisorDeps, str]
    Chat-mode variant for the registry. Returns plain text.
    Called when the user opens a chat with mission.supervisor.agent.

Both register the same three read-only tools via _register_tools().
"""

import json
from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model

from modules.backend.agents.mission.supervisor.deps import MissionSupervisorDeps
from modules.backend.agents.mission.supervisor.models import SupervisorDecision
from modules.backend.agents.mission_control.helpers import (
    _build_model,
    assemble_instructions,
)
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def _register_tools(agent: Agent) -> None:
    """Register the three read-only introspection tools.

    Shared between event-mode and chat-mode factories so the same
    tool code runs in both modes. Each tool delegates to a pure
    function in agents/tools/supervisor_introspection.py.
    """

    @agent.tool
    async def get_plan(ctx: RunContext[MissionSupervisorDeps]) -> str:
        """Read the current mission plan — tasks, status, gate mode, budget, supervisor counters."""
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            from modules.backend.agents.tools.plan_introspection import get_plan_state

            result = await get_plan_state(
                ctx.deps.db_session, mission_id=ctx.deps.mission_id,
            )
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            logger.error("supervisor get_plan failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True)
            return json.dumps({"error": str(e)})

    @agent.tool
    async def get_recent_run_outcomes(
        ctx: RunContext[MissionSupervisorDeps],
        limit: int = 5,
    ) -> str:
        """Read the last N run outcomes for this mission — status, cost, task counts."""
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            from modules.backend.agents.tools.supervisor_introspection import (
                get_recent_run_outcomes as _get_outcomes,
            )

            result = await _get_outcomes(
                ctx.deps.db_session,
                mission_id=ctx.deps.mission_id,
                limit=limit,
            )
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            logger.error("supervisor get_recent_run_outcomes failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True)
            return json.dumps({"error": str(e)})

    @agent.tool
    async def get_past_decisions(
        ctx: RunContext[MissionSupervisorDeps],
        limit: int = 10,
    ) -> str:
        """Read past post-run supervisor decisions for this mission — action, rule, reason."""
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            from modules.backend.agents.tools.supervisor_introspection import (
                get_past_decisions as _get_decisions,
            )

            result = await _get_decisions(
                ctx.deps.db_session,
                mission_id=ctx.deps.mission_id,
                limit=limit,
            )
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            logger.error("supervisor get_past_decisions failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True)
            return json.dumps({"error": str(e)})


def create_event_agent(
    model: str | Model,
) -> Agent[MissionSupervisorDeps, SupervisorDecision]:
    """Structured-output variant for branch #8 of the decision matrix.

    Called by AutonomousPostRunReviewer when the plan is exhausted
    and Haiku classification is needed. Output is a
    SupervisorDecision pydantic model that the reviewer converts
    into a GateDecision.
    """
    if isinstance(model, str):
        model = _build_model(model)

    system_prompt = assemble_instructions("mission", "supervisor")

    agent: Agent[MissionSupervisorDeps, SupervisorDecision] = Agent(
        model,
        system_prompt=system_prompt,
        output_type=SupervisorDecision,
        deps_type=MissionSupervisorDeps,
    )
    _register_tools(agent)
    return agent


def create_agent(model: str | Model) -> Agent[MissionSupervisorDeps, str]:
    """Chat-mode variant for the agent registry.

    Called when the user opens a chat with mission.supervisor.agent.
    Plain-string output — answers questions about past decisions;
    never makes new ones. Named `create_agent` (matching Director /
    Workflow convention) so the mission-tier registry picks it up
    automatically.
    """
    if isinstance(model, str):
        model = _build_model(model)

    system_prompt = assemble_instructions(
        "mission", "supervisor", variant="chat",
    )

    agent: Agent[MissionSupervisorDeps, str] = Agent(
        model,
        system_prompt=system_prompt,
        deps_type=MissionSupervisorDeps,
    )
    _register_tools(agent)
    return agent
