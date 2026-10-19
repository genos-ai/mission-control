"""Tests for the execution record response schemas."""

from modules.backend.core.decision_reasoning import encode_decision_reasoning

META = {"action": "escalate", "reviewer": "config:rule_engine", "rule": 3, "model_metadata": None}


class TestExecutionDecisionResponse:
    """The API exposes the human reason only; other decision types pass through."""

    @staticmethod
    def _response(decision_type: str, reasoning: str):
        from datetime import datetime, timezone

        from modules.backend.schemas.execution_record import ExecutionDecisionResponse

        return ExecutionDecisionResponse(
            id="d1",
            decision_type=decision_type,
            task_id=None,
            reasoning=reasoning,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    def test_supervisor_decision_loses_its_stored_metadata(self):
        stored = encode_decision_reasoning("Stall detected.", META)

        response = self._response("post_run_supervisor", stored)

        assert response.reasoning == "Stall detected."

    def test_other_decision_types_are_untouched(self):
        text = 'Retry because of:\n{"action": "retry"}'

        response = self._response("retry", text)

        assert response.reasoning == text
