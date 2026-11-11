"""
HumanInputWorkflow — Temporal-native durable pause (Plan 45 Phase 4).

Uses the Signal + wait_condition pattern (MissionRunWorkflow uses it too).
Starts a lightweight workflow that:
1. Records the pending request + notifies the human (activity)
2. Waits for a Signal (or timeout) — Temporal-durable across restarts
3. Marks the request resolved in the DB (activity)
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from modules.backend.temporal.human_input_models import (
    HumanInputResponse,
    HumanInputResult,
    HumanInputWorkflowInput,
)

with workflow.unsafe.imports_passed_through():
    from modules.backend.temporal import human_input_activities


@workflow.defn
class HumanInputWorkflow:
    """Durable human-in-the-loop pause for workflow steps."""

    def __init__(self) -> None:
        self._response: HumanInputResponse | None = None

    @workflow.signal
    async def submit_human_input(self, response: HumanInputResponse) -> None:
        """Receive the human's response via Temporal Signal."""
        self._response = response

    @workflow.query
    def get_status(self) -> dict:
        """Read-only query for dashboards."""
        return {
            "responded": self._response is not None,
            "response": self._response.response if self._response else None,
        }

    @workflow.run
    async def run(self, input: HumanInputWorkflowInput) -> HumanInputResult:
        # 1. Record pending request in DB + notify human
        await workflow.execute_activity(
            human_input_activities.notify_human_input_needed,
            input,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # 2. Wait for Signal or timeout (Temporal-native, durable)
        try:
            await workflow.wait_condition(
                lambda: self._response is not None,
                timeout=timedelta(seconds=input.timeout_seconds),
            )
        except TimeoutError:
            if input.default_response:
                self._response = HumanInputResponse(
                    response=input.default_response,
                    responder_type="timeout_default",
                )
            else:
                # Mark timed out in DB
                await workflow.execute_activity(
                    human_input_activities.mark_human_input_resolved,
                    args=[input.request_id, "", True],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                return HumanInputResult(
                    request_id=input.request_id,
                    response="",
                    timed_out=True,
                    status="timed_out",
                )

        # 3. Mark resolved in DB
        await workflow.execute_activity(
            human_input_activities.mark_human_input_resolved,
            args=[input.request_id, self._response.response, False],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        return HumanInputResult(
            request_id=input.request_id,
            response=self._response.response,
            responder_id=self._response.responder_id,
            timed_out=False,
            status="completed",
        )
