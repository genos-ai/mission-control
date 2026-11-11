"""
Chat Turn Workflow (Plan 52 Phase B).

Temporal Workflow that executes a single chat turn with durable
guarantees:

1. Persist user message (Activity — own DB commit, survives agent crash)
2. Execute agent turn (Activity — runs handle() which persists the
   assistant response at step 11 and publishes events to Redis
   Pub/Sub in real-time)

Two activities, not three: the agent turn persists its own response
inline via handle(). This avoids a third Temporal dispatch round-trip
that added ~100-200ms of latency per chat turn.

Key rules (same as MissionRunWorkflow):
- Workflow code is deterministic — no I/O, no random, no wall-clock
  reads (use workflow.now() if workflow code ever needs the time)
- All side effects happen in Activities
- Temporal owns orchestration state, PostgreSQL owns domain state
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, is_cancelled_exception

from modules.backend.temporal.chat_models import ChatTurnInput, ChatTurnResult

with workflow.unsafe.imports_passed_through():
    from modules.backend.temporal import chat_activities
    from modules.backend.temporal.mission_run_models import RefinementOutcome


@workflow.defn
class ChatTurnWorkflow:
    """Execute a chat turn as a durable Temporal Workflow.

    Flow:
    1. Persist user message (survives any subsequent failure)
    2. Execute agent turn (publishes events live, persists response)

    Short-lived (seconds to minutes). One workflow per message.
    """

    def __init__(self) -> None:
        self._result: ChatTurnResult | None = None

    @workflow.query
    def get_result(self) -> ChatTurnResult | None:
        """Read-only status for polling. Returns None while in progress."""
        return self._result

    @workflow.run
    async def run(self, input: ChatTurnInput) -> ChatTurnResult:
        """Execute a single chat turn with durable persistence."""
        # Step 1: Persist user message (local activity — no scheduling hop)
        # Fast, retryable, own DB commit. After this, the user message
        # is safely in session_messages regardless of what happens next.
        await workflow.execute_local_activity(
            chat_activities.persist_user_message,
            input,
            schedule_to_close_timeout=timedelta(
                seconds=input.timeouts.persistence_timeout_seconds,
            ),
            retry_policy=RetryPolicy(
                maximum_attempts=input.timeouts.persistence_retry_max_attempts,
            ),
        )

        # Step 2: Execute agent turn
        # Runs handle() with skip_persistence=False so it persists
        # the assistant response at step 11 within the same activity.
        # Events publish to Redis Pub/Sub in real-time via the event
        # bus. No separate persist_assistant_message activity needed.
        activity_timeout = timedelta(seconds=input.timeouts.activity_timeout_seconds)
        try:
            result = await workflow.execute_activity(
                chat_activities.execute_chat_turn,
                input,
                start_to_close_timeout=activity_timeout,
                retry_policy=RetryPolicy(
                    maximum_attempts=1,  # Don't retry agent execution — user sees partial
                    non_retryable_error_types=["BudgetExceededError"],
                ),
            )
        except ActivityError as e:
            # A turn that never returned (timeout, worker loss) still tells a
            # waiting run why, so the run fails with the cause instead of
            # waiting out refine_wait_seconds.
            if input.parent_workflow_id and not is_cancelled_exception(e):
                cause = e.cause if e.cause is not None else e
                await self._signal_parent(
                    input.parent_workflow_id,
                    RefinementOutcome(error=f"Director turn failed: {cause}", reply=""),
                )
            raise

        self._result = result

        # Step 3: Signal parent workflow if this chat turn was spawned
        # by MissionRunWorkflow's advance_refine path. The signal wakes
        # the parent immediately instead of requiring it to poll for new
        # tasks on a timer. It reports that the turn ended, not that it
        # refined. refine_plan waits for its refinement to commit while a
        # run is active, so by now any tasks the turn added are visible;
        # the parent reads the task graph and fails the run, with this
        # outcome as the cause, when the turn produced none.
        if input.parent_workflow_id:
            await self._signal_parent(
                input.parent_workflow_id,
                RefinementOutcome(error=result.error, reply=result.content),
            )

        return result

    async def _signal_parent(self, parent_workflow_id: str, outcome: RefinementOutcome) -> None:
        try:
            parent = workflow.get_external_workflow_handle(parent_workflow_id)
            await parent.signal("refinement_complete", outcome)
        except Exception:
            # Parent may have completed or been cancelled — non-fatal.
            workflow.logger.warning(
                "Failed to signal parent workflow %s (non-fatal)",
                parent_workflow_id,
            )
