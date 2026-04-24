"""
Tool Fork Workflow (Plan 56 Phase B).

Generic Temporal Workflow that wraps Director tool calls that were forked
to Temporal for durability. Handles two tool types:
- design_workflow: Runs the Workflow Architect agent
- run_workflow: Runs a named workflow

Flow:
1. Mark ExecutionRecord as "running"
2. Execute the actual work (appropriate activity)
3. Mark ExecutionRecord as "completed" or "failed"
4. Notify the Director with the result (fires scheduled followups
   for a specific prompt, or falls back to a generic summary)
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from modules.backend.temporal.tool_fork_models import (
    DesignWorkflowInput,
    RunWorkflowInput,
    ToolForkResult,
)

with workflow.unsafe.imports_passed_through():
    from modules.backend.core.config import get_app_config
    from modules.backend.temporal import tool_fork_activities


def _build_fallback_prompt(task_type: str, result: ToolForkResult) -> str:
    """Build a generic prompt when no scheduled followup matches."""
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
    followup_event_types: list[str] | None = None,
) -> None:
    """Notify the Director after a background task completes.

    Fires any scheduled followups matching ``followup_event_types``.
    If a followup matches, its rendered prompt (e.g. "Check the
    research results…") is used instead of the generic fallback.
    Either way, exactly one ChatTurnWorkflow is started.
    """
    fallback = _build_fallback_prompt(task_type, result)
    await workflow.execute_activity(
        tool_fork_activities.notify_director_on_completion,
        args=[mission_id, session_id, followup_event_types, fallback],
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

        try:
            result = await workflow.execute_activity(
                tool_fork_activities.execute_design_workflow,
                input,
                start_to_close_timeout=timedelta(
                    seconds=max(config.min_activity_timeout_seconds, 300),
                ),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except Exception as exc:
            await workflow.execute_activity(
                tool_fork_activities.update_execution_record_status,
                args=[input.execution_record_id, "failed", str(exc)[:500]],
                start_to_close_timeout=timedelta(seconds=30),
            )
            raise

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

        try:
            result = await workflow.execute_activity(
                tool_fork_activities.execute_run_workflow,
                input,
                start_to_close_timeout=timedelta(
                    seconds=max(config.min_activity_timeout_seconds, 600),
                ),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except Exception as exc:
            await workflow.execute_activity(
                tool_fork_activities.update_execution_record_status,
                args=[input.execution_record_id, "failed", str(exc)[:500]],
                start_to_close_timeout=timedelta(seconds=30),
            )
            raise

        await workflow.execute_activity(
            tool_fork_activities.update_execution_record_status,
            args=[input.execution_record_id, result.status, result.error],
            start_to_close_timeout=timedelta(seconds=30),
        )

        await _notify_director(
            input.mission_id, input.session_id,
            "run_workflow", result,
            followup_event_types=input.followup_event_types,
        )

        return result
