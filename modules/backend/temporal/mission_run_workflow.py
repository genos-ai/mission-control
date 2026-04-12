"""
Mission Run Workflow (Plan 52 Phase C).

Temporal Workflow that executes a wave of approved tasks, then runs
the supervisor decision loop:

  execute_mission → persist → evaluate_post_run → route decision:
    WAIT          → sleep, poll for new approved tasks, loop
    ADVANCE_APPROVED → approve proposed, loop back to execute
    ADVANCE_REFINE   → start Director ChatTurnWorkflow to refine plan,
                       poll for new proposed tasks, loop
    PROPOSE_COMPLETE → start Director ChatTurnWorkflow to confirm
    ESCALATE         → start Director ChatTurnWorkflow + notification

This replaces the inline _run_post_run_reviewer + _apply_supervisor_decision
in MissionPlanService.dispatch_approved with a durable Temporal workflow
that survives process crashes and replays from the last completed activity.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from modules.backend.core.config import get_app_config
    from modules.backend.temporal import activities
    from modules.backend.temporal import supervisor_activities as sup
    from modules.backend.temporal.models import (
        MissionWorkflowInput,
        NotificationPayload,
    )


@workflow.defn
class MissionRunWorkflow:
    """Execute a mission wave + supervisor loop as a durable workflow.

    The workflow loops until the supervisor decides to stop (ESCALATE,
    PROPOSE_COMPLETE) or a circuit breaker trips (max iterations,
    budget, stall). Each iteration is independently recoverable —
    if the worker crashes between execute_mission and evaluate_post_run,
    Temporal replays from the last completed activity.
    """

    def __init__(self) -> None:
        self._iteration = 0
        self._last_action = ""
        self._total_cost = 0.0

    @workflow.query
    def get_loop_status(self) -> dict:
        """Read-only status for dashboards."""
        return {
            "iteration": self._iteration,
            "last_action": self._last_action,
            "total_cost": self._total_cost,
        }

    @workflow.run
    async def run(self, input: MissionWorkflowInput) -> dict:
        """Execute the autonomy loop."""
        config = get_app_config().temporal

        persist_policy = RetryPolicy(
            maximum_attempts=config.persistence_retry_max_attempts,
        )
        persist_timeout = timedelta(seconds=config.persistence_timeout_seconds)

        activity_timeout = timedelta(
            seconds=max(
                input.mission_budget_usd * config.budget_timeout_multiplier_seconds,
                config.min_activity_timeout_seconds,
            ),
        )

        max_loop_iterations = 25  # Hard safety cap

        while self._iteration < max_loop_iterations:
            self._iteration += 1

            # ── Step 1: Execute the current wave of approved tasks ────
            result = await workflow.execute_activity(
                activities.execute_mission,
                input,
                start_to_close_timeout=activity_timeout,
                retry_policy=RetryPolicy(
                    maximum_attempts=config.execution_retry_max_attempts,
                    non_retryable_error_types=["BudgetExceededError"],
                ),
            )

            self._total_cost += result.total_cost_usd

            # ── Step 2: Persist results ──────────────────────────────
            await workflow.execute_activity(
                activities.persist_mission_outcome,
                args=[
                    input.mission_run_id,
                    input.session_id,
                    input.roster_name,
                    result.outcome_json,
                    input.mission_id,
                ],
                start_to_close_timeout=persist_timeout,
                retry_policy=persist_policy,
            )

            # ── Step 3: Supervisor evaluates ─────────────────────────
            eval_input = sup.PostRunEvalInput(
                mission_id=input.mission_id or input.mission_run_id,
                plan_id=input.mission_run_id,
                execution_record_id=result.mission_id,
                gate_mode=input.execution_mode or "autonomous",
                supervisor_iteration_count=self._iteration - 1,
                max_supervisor_iterations=max_loop_iterations,
                budget_usd_ceiling=input.mission_budget_usd,
                total_spent_usd=self._total_cost,
                mission_brief=input.mission_brief,
            )

            eval_result = await workflow.execute_activity(
                sup.evaluate_post_run,
                eval_input,
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            self._last_action = eval_result.action
            self._total_cost += eval_result.cost_usd

            # ── Step 4: Route the decision ───────────────────────────

            if eval_result.action == "wait":
                # Approved tasks still pending — daemon-equivalent sleep
                await workflow.sleep(timedelta(seconds=5))
                continue

            elif eval_result.action == "advance_approved":
                # Flip proposed → approved, loop back to execute
                await workflow.execute_activity(
                    sup.approve_proposed_tasks,
                    input.mission_id or input.mission_run_id,
                    start_to_close_timeout=persist_timeout,
                    retry_policy=persist_policy,
                )
                continue

            elif eval_result.action == "advance_refine":
                # Start Director to refine the plan
                prompt = (
                    f"The supervisor decided to advance the plan after "
                    f"run {result.mission_id}. The last wave "
                    f"{'succeeded' if result.status == 'success' else 'had failures'}. "
                    f"Total cost so far: ${self._total_cost:.2f}. "
                    f"Please call refine_plan to generate the next wave of tasks "
                    f"based on the outcomes, then approve them."
                )
                await workflow.execute_activity(
                    sup.start_director_turn,
                    args=[
                        input.mission_id or input.mission_run_id,
                        input.session_id,
                        prompt,
                    ],
                    start_to_close_timeout=activity_timeout,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

                # Poll for new proposed/approved tasks (reuse last counts)
                counts = sup.PlanTaskCounts()
                for _ in range(12):  # 60 seconds max polling
                    await workflow.sleep(timedelta(seconds=5))
                    counts = await workflow.execute_activity(
                        sup.fetch_plan_task_counts,
                        input.mission_id or input.mission_run_id,
                        start_to_close_timeout=persist_timeout,
                        retry_policy=persist_policy,
                    )
                    if counts.approved > 0 or counts.proposed > 0:
                        break

                # If proposed tasks appeared, approve them
                if counts.proposed > 0:
                    await workflow.execute_activity(
                        sup.approve_proposed_tasks,
                        input.mission_id or input.mission_run_id,
                        start_to_close_timeout=persist_timeout,
                        retry_policy=persist_policy,
                    )

                if counts.approved > 0 or counts.proposed > 0:
                    continue  # Loop back to execute
                else:
                    # Director didn't produce new tasks — escalate
                    break

            elif eval_result.action == "propose_complete":
                # Ask Director to confirm completion with user
                prompt = (
                    f"The supervisor believes the mission objective may be met. "
                    f"Total cost: ${self._total_cost:.2f} across {self._iteration} waves. "
                    f"Please review the plan outcomes and ask the user to confirm "
                    f"whether the mission is complete or needs more work."
                )
                await workflow.execute_activity(
                    sup.start_director_turn,
                    args=[
                        input.mission_id or input.mission_run_id,
                        input.session_id,
                        prompt,
                    ],
                    start_to_close_timeout=activity_timeout,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                break

            elif eval_result.action == "escalate":
                # Director handles escalation + notification
                prompt = (
                    f"The supervisor escalated after wave {self._iteration}. "
                    f"Reason: {eval_result.reason[:200]}. "
                    f"Please inform the user and ask for guidance."
                )
                await workflow.execute_activity(
                    sup.start_director_turn,
                    args=[
                        input.mission_id or input.mission_run_id,
                        input.session_id,
                        prompt,
                    ],
                    start_to_close_timeout=activity_timeout,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                await workflow.execute_activity(
                    activities.send_notification,
                    NotificationPayload(
                        channel="webhook",
                        recipient="admin",
                        title=f"Mission escalated: {input.mission_run_id[:12]}",
                        body=eval_result.reason[:300],
                        action_url=f"/missions/{input.mission_id}",
                        urgency="high",
                    ),
                    start_to_close_timeout=timedelta(seconds=30),
                )
                break

            else:
                # Unknown action — break out safely
                break

        return {
            "iterations": self._iteration,
            "last_action": self._last_action,
            "total_cost_usd": self._total_cost,
            "status": "completed" if self._last_action == "propose_complete" else "stopped",
        }
