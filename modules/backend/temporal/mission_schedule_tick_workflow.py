"""Mission schedule tick workflow (Plan 88 step 88.1.8, contract 3.3.2).

Started by a mission schedule's Temporal Schedule on every fire. It claims the
occurrence in Postgres and, when the claim yields a run to start, starts that
run's MissionRunWorkflow as an abandoned child. Notifications are logged only
until 88.4.5 sends them. Reads no config: policies come from TickConfigSnapshot.
"""

from temporalio import workflow
from temporalio.common import SearchAttributeKey, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError
from temporalio.workflow import ParentClosePolicy

with workflow.unsafe.imports_passed_through():
    from modules.backend.temporal.activity_options import activity_kwargs
    from modules.backend.temporal.mission_run_models import (
        ClaimOccurrenceInput,
        MissionScheduleTickInput,
    )
    from modules.backend.temporal.mission_run_workflow import MissionRunWorkflow
    from modules.backend.temporal.mission_schedule_activities import claim_occurrence
    from modules.backend.temporal.workflow_ids import mission_run_workflow_id

SCHEDULED_START_TIME = SearchAttributeKey.for_datetime("TemporalScheduledStartTime")


@workflow.defn
class MissionScheduleTickWorkflow:
    @workflow.run
    async def run(self, inp: MissionScheduleTickInput) -> str:
        scheduled_for = workflow.info().typed_search_attributes.get(SCHEDULED_START_TIME)
        if scheduled_for is None:
            raise ApplicationError("NO_SCHEDULED_TIME", non_retryable=True)
        r = await workflow.execute_activity(
            claim_occurrence,
            ClaimOccurrenceInput(inp.mission_schedule_id, scheduled_for),
            **activity_kwargs(inp.config.claim),
        )
        workflow.logger.info("notifications pending phase", extra={"count": len(r.notifications)})
        if r.run_input is not None:
            try:
                await workflow.start_child_workflow(
                    MissionRunWorkflow.run,
                    r.run_input,
                    id=mission_run_workflow_id(r.mission_run_id),
                    task_queue=inp.config.task_queue,
                    parent_close_policy=ParentClosePolicy.ABANDON,
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                )
            except WorkflowAlreadyStartedError:
                workflow.logger.info(
                    "run workflow already started", extra={"mission_run_id": r.mission_run_id}
                )
        return r.outcome
