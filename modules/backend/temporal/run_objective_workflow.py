"""
Run Objective Workflow.

Temporal Workflow that runs the full objective flow:
refine (Planning Agent) → approve → dispatch (MissionRunWorkflow).

The HTTP endpoint returns immediately after starting this workflow.
The refine step blocks inside the activity (managed by Temporal
timeouts, not HTTP). Dispatch chains to MissionRunWorkflow internally.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from modules.backend.temporal.run_objective_models import (
    RunObjectiveInput,
    RunObjectiveResult,
)

with workflow.unsafe.imports_passed_through():
    from modules.backend.core.config import get_app_config
    from modules.backend.temporal import run_objective_activities


@workflow.defn
class RunObjectiveWorkflow:
    """Execute an objective as a durable Temporal Workflow.

    Single activity that calls service.run_objective(). The Planning
    Agent (refine) blocks within the activity — safe because Temporal
    manages the timeout. Dispatch starts MissionRunWorkflow internally
    for the autonomous execution loop.
    """

    def __init__(self) -> None:
        self._result: RunObjectiveResult | None = None

    @workflow.query
    def get_result(self) -> RunObjectiveResult | None:
        """Read-only status for polling. Returns None while in progress."""
        return self._result

    @workflow.run
    async def run(self, input: RunObjectiveInput) -> RunObjectiveResult:
        """Execute the objective: refine → approve → dispatch."""
        config = get_app_config().temporal

        # Budget-proportional timeout: refine can take 10-60s depending
        # on complexity, plus the dispatch setup. 120s floor.
        timeout_seconds = max(config.min_activity_timeout_seconds, 120)
        if input.budget_ceiling_usd:
            timeout_seconds = max(
                timeout_seconds,
                input.budget_ceiling_usd * config.budget_timeout_multiplier_seconds,
            )

        result = await workflow.execute_activity(
            run_objective_activities.execute_run_objective,
            input,
            start_to_close_timeout=timedelta(seconds=timeout_seconds),
            retry_policy=RetryPolicy(
                maximum_attempts=2,
                non_retryable_error_types=["ConflictError", "ValidationError"],
            ),
        )

        self._result = result
        return result
