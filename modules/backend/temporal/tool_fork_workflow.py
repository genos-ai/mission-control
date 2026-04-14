"""
Tool Fork Workflow (Plan 56 Phase B).

Generic Temporal Workflow that wraps Director tool calls that were forked
to Temporal for durability. Handles three tool types:
- design_workflow: Runs the Workflow Architect agent
- run_objective: Runs an ad-hoc execution
- run_workflow: Runs a named workflow

Flow:
1. Mark ExecutionRecord as "running"
2. Execute the actual work (appropriate activity)
3. Mark ExecutionRecord as "completed" or "failed"
4. Wake the Director with the result (ChatTurnWorkflow)
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from modules.backend.temporal.tool_fork_models import (
    DesignWorkflowInput,
    RunObjectiveInput,
    RunWorkflowInput,
    ToolForkResult,
)

with workflow.unsafe.imports_passed_through():
    from modules.backend.core.config import get_app_config
    from modules.backend.temporal import tool_fork_activities
    from modules.backend.temporal import supervisor_activities


def _build_followup_prompt(task_type: str, result: ToolForkResult) -> str:
    """Build a prompt for the Director to summarise the background task result."""
    if result.status == "completed":
        return (
            f"Background task '{task_type}' just completed successfully.\n"
            f"Summary: {result.summary}\n\n"
            f"Tell the user what happened in a brief, clear message."
        )
    else:
        return (
            f"Background task '{task_type}' failed.\n"
            f"Error: {result.error}\n\n"
            f"Tell the user what went wrong and suggest next steps."
        )


async def _notify_director(
    mission_id: str,
    session_id: str,
    task_type: str,
    result: ToolForkResult,
) -> None:
    """Wake the Director to report the background task result to the user."""
    prompt = _build_followup_prompt(task_type, result)
    await workflow.execute_activity(
        supervisor_activities.start_director_turn,
        args=[mission_id, session_id, prompt],
        start_to_close_timeout=timedelta(seconds=300),
        retry_policy=RetryPolicy(maximum_attempts=1),
    )


@workflow.defn
class DesignWorkflowWorkflow:
    """Fork design_workflow tool to Temporal for durability."""

    @workflow.run
    async def run(self, input: DesignWorkflowInput) -> ToolForkResult:
        config = get_app_config().temporal

        await workflow.execute_activity(
            tool_fork_activities.update_execution_record_status,
            args=[input.execution_record_id, "running"],
            start_to_close_timeout=timedelta(seconds=30),
        )

        result = await workflow.execute_activity(
            tool_fork_activities.execute_design_workflow,
            input,
            start_to_close_timeout=timedelta(
                seconds=max(config.min_activity_timeout_seconds, 300),
            ),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        await workflow.execute_activity(
            tool_fork_activities.update_execution_record_status,
            args=[input.execution_record_id, result.status, result.error],
            start_to_close_timeout=timedelta(seconds=30),
        )

        await _notify_director(
            input.mission_id, input.session_id,
            "design_workflow", result,
        )

        return result


@workflow.defn
class RunObjectiveWorkflow:
    """Fork run_objective tool to Temporal for durability."""

    @workflow.run
    async def run(self, input: RunObjectiveInput) -> ToolForkResult:
        config = get_app_config().temporal

        await workflow.execute_activity(
            tool_fork_activities.update_execution_record_status,
            args=[input.execution_record_id, "running"],
            start_to_close_timeout=timedelta(seconds=30),
        )

        result = await workflow.execute_activity(
            tool_fork_activities.execute_run_objective,
            input,
            start_to_close_timeout=timedelta(
                seconds=max(config.min_activity_timeout_seconds, 600),
            ),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        await workflow.execute_activity(
            tool_fork_activities.update_execution_record_status,
            args=[input.execution_record_id, result.status, result.error],
            start_to_close_timeout=timedelta(seconds=30),
        )

        await _notify_director(
            input.mission_id, input.session_id,
            "run_objective", result,
        )

        return result


@workflow.defn
class RunWorkflowWorkflow:
    """Fork run_workflow tool to Temporal for durability."""

    @workflow.run
    async def run(self, input: RunWorkflowInput) -> ToolForkResult:
        config = get_app_config().temporal

        await workflow.execute_activity(
            tool_fork_activities.update_execution_record_status,
            args=[input.execution_record_id, "running"],
            start_to_close_timeout=timedelta(seconds=30),
        )

        result = await workflow.execute_activity(
            tool_fork_activities.execute_run_workflow,
            input,
            start_to_close_timeout=timedelta(
                seconds=max(config.min_activity_timeout_seconds, 600),
            ),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        await workflow.execute_activity(
            tool_fork_activities.update_execution_record_status,
            args=[input.execution_record_id, result.status, result.error],
            start_to_close_timeout=timedelta(seconds=30),
        )

        await _notify_director(
            input.mission_id, input.session_id,
            "run_workflow", result,
        )

        return result
