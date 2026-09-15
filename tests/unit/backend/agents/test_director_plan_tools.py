"""Unit tests for the Director's plan tool implementations.

These functions were previously closures inside `register_plan_tools`,
reachable only through a PydanticAI agent, and so had no test coverage.
Extracting them per P7 makes them callable directly. No LLM and no agent
runtime is involved (P11).

The gate-mode check is the most important case here: it is what stops the
Director approving tasks on behalf of a user who asked to approve them
personally.
"""

from __future__ import annotations

import pytest

from modules.backend.agents.mission.director.tool_helpers import ToolRefusal
from modules.backend.agents.mission.director.tools.approve_plan_tasks import (
    _approve_each,
    _check_gate_mode,
    _dedupe_preserving_order,
    _validate_reason,
)


class _StubTask:
    """Minimal stand-in for a plan task, which only needs an id here."""

    def __init__(self, task_id: str) -> None:
        self.id = task_id


class _StubPlanService:
    """Test double for MissionPlanService at the approve_task boundary.

    Returns the transitions configured per task id, or raises when the id
    is listed in `failing`, mirroring the service rejecting a task that is
    absent from the plan or not in `proposed` state.
    """

    def __init__(
        self,
        transitions: dict[str, list[str]] | None = None,
        failing: set[str] | None = None,
    ) -> None:
        self.transitions = transitions or {}
        self.failing = failing or set()
        self.calls: list[tuple[str, str, str]] = []

    async def approve_task(self, plan_id: str, task_id: str, *, user_id: str):
        self.calls.append((plan_id, task_id, user_id))
        if task_id in self.failing:
            raise ValueError(f"task {task_id} is not approvable")
        return [_StubTask(t) for t in self.transitions.get(task_id, [task_id])]


class TestValidateReason:
    def test_accepts_a_normal_reason(self):
        _validate_reason("Approving the research tasks so the scan can start.")

    def test_accepts_exactly_the_maximum_length(self):
        _validate_reason("x" * 500)

    @pytest.mark.parametrize("reason", ["", "   ", "\n\t "])
    def test_rejects_missing_or_blank(self, reason: str):
        with pytest.raises(ToolRefusal) as exc:
            _validate_reason(reason)
        assert exc.value.message == "reason is required — explain why you are approving"
        assert exc.value.details == {}

    def test_rejects_over_length_and_reports_the_count(self):
        with pytest.raises(ToolRefusal) as exc:
            _validate_reason("x" * 501)
        assert exc.value.message == "reason too long (501 chars, max 500)"


class TestCheckGateMode:
    @pytest.mark.parametrize("mode", ["ai_assisted", "autonomous"])
    def test_permits_modes_that_delegate_approval(self, mode: str):
        _check_gate_mode(mode)

    @pytest.mark.parametrize("mode", ["interactive", None])
    def test_refuses_when_the_user_approves_manually(self, mode: str | None):
        """interactive, and an unset mode which defaults to it, must not be bypassed."""
        with pytest.raises(ToolRefusal) as exc:
            _check_gate_mode(mode)
        assert "interactive mode" in exc.value.message
        assert "ai_assisted" in exc.value.message
        # The mode is echoed back so the LLM can tell the user what to change.
        assert exc.value.details == {"gate_mode": mode}

    def test_refuses_an_unrecognised_mode(self):
        with pytest.raises(ToolRefusal) as exc:
            _check_gate_mode("something_new")
        assert exc.value.message == "Unsupported gate_mode for auto-approval: something_new"
        assert exc.value.details == {}


class TestDedupePreservingOrder:
    def test_removes_duplicates_and_keeps_first_seen_order(self):
        assert _dedupe_preserving_order(["c", "a", "c", "b", "a"]) == ["c", "a", "b"]

    def test_passes_through_unique_input(self):
        assert _dedupe_preserving_order(["a", "b"]) == ["a", "b"]

    def test_handles_empty_input(self):
        assert _dedupe_preserving_order([]) == []


class TestApproveEach:
    async def test_collects_every_transitioned_id(self):
        service = _StubPlanService(transitions={"t1": ["t1", "upstream-1"], "t2": ["t2"]})

        result = await _approve_each(
            service, "plan-1", ["t1", "t2"], user_id="user-1", mission_id="m-1"
        )

        # Includes the transitive upstream dependency the service approved.
        assert result == ["t1", "upstream-1", "t2"]
        assert service.calls == [
            ("plan-1", "t1", "user-1"),
            ("plan-1", "t2", "user-1"),
        ]

    async def test_skips_a_rejected_task_and_continues(self):
        """A task the service rejects is skipped, not fatal — the caller
        reports the real outcome via the returned ids."""
        service = _StubPlanService(transitions={"t2": ["t2"]}, failing={"t1"})

        result = await _approve_each(
            service, "plan-1", ["t1", "t2"], user_id="user-1", mission_id="m-1"
        )

        assert result == ["t2"]
        # Both were attempted; only the second contributed.
        assert len(service.calls) == 2

    async def test_returns_empty_when_every_task_is_rejected(self):
        service = _StubPlanService(failing={"t1", "t2"})

        result = await _approve_each(
            service, "plan-1", ["t1", "t2"], user_id="user-1", mission_id="m-1"
        )

        assert result == []

    async def test_approves_as_the_given_user(self):
        """The approval must be attributed to the mission owner, since
        tasks.approved_by_user_id is a FK to users.id."""
        service = _StubPlanService()

        await _approve_each(service, "plan-1", ["t1"], user_id="owner-uuid", mission_id="m-1")

        assert service.calls == [("plan-1", "t1", "owner-uuid")]
