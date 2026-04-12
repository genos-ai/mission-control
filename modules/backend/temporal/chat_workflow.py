"""
Chat Turn Workflow (Plan 52 Phase B).

Temporal Workflow that executes a single chat turn with durable
guarantees:

1. Persist user message (Activity — own DB commit)
2. Execute agent turn (Activity — drains handle(), publishes events
   to Redis Pub/Sub in real-time)
3. Persist assistant response (Activity — own DB commit)

The browser can disconnect at any point. The workflow completes
regardless. Events flow through Redis Pub/Sub to any connected
SSE subscriber.

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
    2. Execute agent turn (publishes events to Redis Pub/Sub live)
    3. Persist assistant response (retried independently if it fails)

    The workflow is short-lived (seconds to minutes, depending on
    agent execution time). It's NOT a long-running workflow — it
    completes after one turn. Multi-turn conversations start a new
    workflow per message.
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

        # Step 1: Persist user message
        # Fast, retryable, own DB commit. After this, the user message
        # is safely in session_messages regardless of what happens next.
        await workflow.execute_activity(
            chat_activities.persist_user_message,
            input,
            start_to_close_timeout=timedelta(
                seconds=temporal_config.persistence_timeout_seconds,
            ),
            retry_policy=RetryPolicy(
                maximum_attempts=temporal_config.persistence_retry_max_attempts,
            ),
        )

        # Step 2: Execute agent turn
        # This is the expensive step — runs the LLM, tool calls, etc.
        # Events publish to Redis Pub/Sub in real-time via the event bus
        # passed to handle(). The frontend sees streaming via EventSource.
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

        # Step 3: Persist assistant response
        # Separate activity so Temporal retries it independently of
        # the agent execution. If the agent completed but persistence
        # failed (DB blip), Temporal retries ONLY the persistence —
        # the agent doesn't re-execute.
        await workflow.execute_activity(
            chat_activities.persist_assistant_message,
            args=[input.session_id, result],
            start_to_close_timeout=timedelta(
                seconds=temporal_config.persistence_timeout_seconds,
            ),
            retry_policy=RetryPolicy(
                maximum_attempts=temporal_config.persistence_retry_max_attempts,
            ),
        )

        return result
