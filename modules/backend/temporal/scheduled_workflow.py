"""
Scheduled Mission Check Workflow (Plan 52 Phase D).

Replaces MissionPlanDaemon's asyncio polling loop with a Temporal
scheduled workflow. Fires on a configurable interval, checks for
missions with approved tasks in autonomous/off gate_mode, and
starts a MissionRunWorkflow for each one.

No more Redis locking, heartbeat monitoring, or crash recovery —
Temporal handles timing, deduplication, and worker coordination.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from temporalio.workflow import ParentClosePolicy

with workflow.unsafe.imports_passed_through():
    from modules.backend.core.config import get_app_config, get_default_budget_usd
    from modules.backend.temporal import scheduled_activities
    from modules.backend.temporal.mission_run_workflow import MissionRunWorkflow
    from modules.backend.temporal.models import MissionWorkflowInput


@workflow.defn
class ScheduledMissionCheckWorkflow:
    """Check for dispatchable missions and start run workflows.

    This workflow runs once per scheduled trigger (every 1s).
    It queries the DB for missions with approved tasks in autonomous
    or off gate_mode, then starts a MissionRunWorkflow for each.

    The workflow itself is short-lived — it checks, starts children,
    and completes. The Temporal schedule fires it again on the next
    interval.

    Workflow ID deduplication ensures only one check runs at a time
    across all workers — no Redis locking needed.
    """

    @workflow.run
    async def run(self) -> dict:
        config = get_app_config().temporal

        # Find missions with approved tasks ready to dispatch
        ready_plans = await workflow.execute_local_activity(
            scheduled_activities.find_ready_plans,
            schedule_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        if not ready_plans:
            return {"checked": True, "dispatched": 0}

        # Start a MissionRunWorkflow for each ready plan
        dispatched = 0
        for plan_info in ready_plans:
            try:
                input_data = MissionWorkflowInput(
                    mission_run_id=plan_info["plan_id"],
                    session_id="",  # Created by execute_mission activity
                    mission_brief=plan_info.get("brief", ""),
                    roster_name=plan_info.get("roster", "default"),
                    mission_budget_usd=plan_info.get("budget") or get_default_budget_usd(),
                    mission_id=plan_info["mission_id"],
                    execution_mode=plan_info.get("gate_mode", "autonomous"),
                    owner_id=plan_info.get("owner_id", ""),
                )

                # Use plan_id as workflow ID for deduplication — only one
                # run workflow per plan at a time.
                workflow_id = f"mission-run-{plan_info['plan_id']}"

                await workflow.start_child_workflow(
                    MissionRunWorkflow.run,
                    input_data,
                    id=workflow_id,
                    task_queue=config.task_queue,
                    # ABANDON: child continues after parent completes.
                    # Without this, Temporal's default TERMINATE policy
                    # kills the child when the scheduled workflow finishes.
                    parent_close_policy=ParentClosePolicy.ABANDON,
                )
                dispatched += 1
            except Exception as exc:
                # Workflow already running for this plan, or other error.
                # Don't fail the scheduled check — log and continue.
                workflow.logger.warning(
                    "Failed to start MissionRunWorkflow for plan %s (mission %s): %s",
                    plan_info.get("plan_id", "?"),
                    plan_info.get("mission_id", "?"),
                    exc,
                )

        return {"checked": True, "dispatched": dispatched}
