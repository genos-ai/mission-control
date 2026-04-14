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

Key rules (same as AgentMissionWorkflow):
- Workflow code is deterministic — no I/O, no random, no datetime.now()
- All side effects happen in Activities
- Temporal owns orchestration state, PostgreSQL owns domain state
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from modules.backend.temporal.chat_models import ChatTurnInput, ChatTurnResult

with workflow.unsafe.imports_passed_through():
    from modules.backend.core.config import get_app_config
    from modules.backend.temporal import chat_activities


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
        temporal_config = get_app_config().temporal

        # Step 1: Persist user message (local activity — no scheduling hop)
        # Fast, retryable, own DB commit. After this, the user message
        # is safely in session_messages regardless of what happens next.
        await workflow.execute_local_activity(
            chat_activities.persist_user_message,
            input,
            schedule_to_close_timeout=timedelta(
                seconds=temporal_config.persistence_timeout_seconds,
            ),
            retry_policy=RetryPolicy(
                maximum_attempts=temporal_config.persistence_retry_max_attempts,
            ),
        )

        # Step 2: Execute agent turn
        # Runs handle() with skip_persistence=False so it persists
        # the assistant response at step 11 within the same activity.
        # Events publish to Redis Pub/Sub in real-time via the event
        # bus. No separate persist_assistant_message activity needed.
        activity_timeout = timedelta(
            seconds=max(
                temporal_config.min_activity_timeout_seconds,
                600,  # 10 minutes floor for chat turns with tool calls
            ),
        )
        result = await workflow.execute_activity(
            chat_activities.execute_chat_turn,
            input,
            start_to_close_timeout=activity_timeout,
            retry_policy=RetryPolicy(
                maximum_attempts=1,  # Don't retry agent execution — user sees partial
                non_retryable_error_types=["BudgetExceededError"],
            ),
        )

        self._result = result
        return result
