"""
Tool Fork Workflow (Plan 56 Phase B).

Generic Temporal Workflow that wraps Director tool calls that were forked
to Temporal for durability. Handles three tool types:
- design_workflow: Runs the Workflow Architect agent
- run_objective: Runs an ad-hoc execution
- run_workflow: Runs a named workflow

Flow:
1. Mark ExecutionRecord as "running"
2. Emit "started" event to Redis Pub/Sub
3. Execute the actual work (appropriate activity)
4. Mark ExecutionRecord as "completed" or "failed"
5. Emit "completed" event to Redis Pub/Sub

Uses regular activities (not local) because the work is heavy (LLM calls,
multi-step agent runs). The status update could be local, but keeping it
regular for simplicity — the overhead is trivial compared to the work.
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


@workflow.defn
class DesignWorkflowWorkflow:
    """Fork design_workflow tool to Temporal for durability."""

    @workflow.run
    async def run(self, input: DesignWorkflowInput) -> ToolForkResult:
        config = get_app_config().temporal

        # Mark as running
        await workflow.execute_activity(
            tool_fork_activities.update_execution_record_status,
            args=[input.execution_record_id, "running"],
            start_to_close_timeout=timedelta(seconds=30),
        )

        # Execute the Architect agent
        result = await workflow.execute_activity(
            tool_fork_activities.execute_design_workflow,
            input,
            start_to_close_timeout=timedelta(
                seconds=max(config.min_activity_timeout_seconds, 300),
            ),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        # Mark final status
        await workflow.execute_activity(
            tool_fork_activities.update_execution_record_status,
            args=[input.execution_record_id, result.status, result.error],
            start_to_close_timeout=timedelta(seconds=30),
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

        return result
