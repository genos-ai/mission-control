"""Single-task execution with timeout, cost ceiling, and lifecycle events.

Handles running one agent for one task, wrapped with PlanStep events
for the event bus. Verification is also triggered here as a bridge
to the verification pipeline.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic_ai import UsageLimits

from modules.backend.agents.mission_control.helpers import _emit
from modules.backend.agents.mission_control.middleware import _load_mission_control_config
from modules.backend.agents.mission_control.models import EventBusProtocol, ExecuteAgentFn
from modules.backend.agents.mission_control.outcome import TaskResult
from modules.backend.agents.mission_control.roster import RosterAgentEntry
from modules.backend.agents.mission_control.verification import (
    VerificationResult,
    run_verification_pipeline,
)
from modules.backend.events.types import (
    MissionNarrativeEvent,
    PlanStepCompletedEvent,
    PlanStepStartedEvent,
)
from modules.backend.schemas.task_plan import TaskDefinition


async def execute_task(
    task: TaskDefinition,
    roster_entry: RosterAgentEntry,
    resolved_inputs: dict[str, Any],
    execute_agent_fn: ExecuteAgentFn,
    instructions: str | None = None,
) -> dict:
    """Execute a single agent task with timeout and cost ceiling enforcement.

    Args:
        instructions: Override for task.instructions (used to deliver retry feedback).
    """
    timeout = task.constraints.timeout_override_seconds or roster_entry.constraints.timeout_seconds
    cost_ceiling = roster_entry.constraints.cost_ceiling_usd

    mc_config = _load_mission_control_config()
    usage_limits = UsageLimits(
        request_limit=mc_config.dispatch.default_request_limit,
        total_tokens_limit=int(cost_ceiling * mc_config.dispatch.token_cost_factor),
    )

    return await asyncio.wait_for(
        execute_agent_fn(
            agent_name=task.agent,
            instructions=instructions or task.instructions,
            inputs=resolved_inputs,
            usage_limits=usage_limits,
        ),
        timeout=timeout,
    )


async def verify_task(
    task: TaskDefinition,
    output: dict,
    roster_entry: RosterAgentEntry,
    execute_agent_fn: ExecuteAgentFn | None = None,
    session_id: str | None = None,
) -> VerificationResult:
    """Run the full 3-tier verification pipeline on a completed task."""
    agent_interface = None
    if roster_entry.interface:
        agent_interface = {
            "output": dict(roster_entry.interface.output),
        }

    task_dict = task.model_dump()

    return await run_verification_pipeline(
        output=output,
        task=task_dict,
        agent_interface=agent_interface,
        execute_agent_fn=execute_agent_fn,
        session_id=session_id,
    )


async def execute_with_step_events(
    task: TaskDefinition,
    roster_entry: RosterAgentEntry,
    resolved_inputs: dict[str, Any],
    execute_agent_fn: ExecuteAgentFn,
    execution_id: str,
    gate: Any,
    mission_id: str,
    budget_usd: float,
    event_bus: EventBusProtocol,
    session_id: str,
) -> TaskResult:
    """Wrap the retry handler with PlanStep lifecycle events."""
    from modules.backend.agents.mission_control.dispatch.retry_handler import execute_with_retry

    await _emit(
        event_bus,
        PlanStepStartedEvent,
        session_id=session_id,
        source=f"dispatch:{mission_id}",
        plan_id=mission_id,
        step_id=task.task_id,
        step_name=task.description or task.task_id,
        assigned_agent=task.agent,
    )
    await _emit(
        event_bus,
        MissionNarrativeEvent,
        session_id=session_id,
        source=f"dispatch:{mission_id}",
        mission_id=mission_id,
        agent_id=task.agent,
        narrative=f"Starting **{task.description or task.task_id}**",
        phase="executing",
        level="info",
    )

    result = await execute_with_retry(
        task=task,
        roster_entry=roster_entry,
        resolved_inputs=resolved_inputs,
        execute_agent_fn=execute_agent_fn,
        execution_id=execution_id,
        gate=gate,
        mission_id=mission_id,
        budget_usd=budget_usd,
        session_id=session_id,
    )

    await _emit(
        event_bus,
        PlanStepCompletedEvent,
        session_id=session_id,
        source=f"dispatch:{mission_id}",
        plan_id=mission_id,
        step_id=task.task_id,
        result_summary=f"{result.agent_name}: {result.status.value}",
        status=result.status.value,
    )
    _is_success = result.status.value in ("success",)
    await _emit(
        event_bus,
        MissionNarrativeEvent,
        session_id=session_id,
        source=f"dispatch:{mission_id}",
        mission_id=mission_id,
        agent_id=result.agent_name,
        narrative=(
            f"**{result.agent_name}** completed — {task.description or task.task_id}"
            if _is_success
            else f"**{result.agent_name}** failed on — {task.description or task.task_id}"
        ),
        phase="complete" if _is_success else "error",
        level="success" if _is_success else "warning",
    )

    return result
