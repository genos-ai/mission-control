"""
Plan Refine Workflow.

Short-lived Temporal Workflow that runs the Planning Agent to refine
a mission plan. Single activity — same structure as ChatTurnWorkflow.

The workflow exists so the refine endpoint can return immediately.
MissionPlanService.refine() emits MissionPlanRefinedEvent via SSE
when done, so the frontend picks up the new plan without polling.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from modules.backend.temporal.plan_refine_models import PlanRefineInput, PlanRefineResult

with workflow.unsafe.imports_passed_through():
    from modules.backend.temporal import plan_refine_activities


@workflow.defn
class PlanRefineWorkflow:
    """Refine a mission plan as a durable Temporal Workflow.

    Single activity, short-lived (seconds to a minute). One workflow
    per refine request. If the worker crashes mid-refine, Temporal
    retries the activity automatically.
    """

    def __init__(self) -> None:
        self._result: PlanRefineResult | None = None

    @workflow.query
    def get_result(self) -> PlanRefineResult | None:
        """Read-only status for polling. Returns None while in progress."""
        return self._result

    @workflow.run
    async def run(self, input: PlanRefineInput) -> PlanRefineResult:
        """Execute the Planning Agent refinement."""
        result = await workflow.execute_activity(
            plan_refine_activities.execute_plan_refine,
            input,
            start_to_close_timeout=timedelta(seconds=input.timeouts.activity_timeout_seconds),
            retry_policy=RetryPolicy(
                maximum_attempts=2,
            ),
        )

        self._result = result
        return result
