"""refine_plan waits for its refinement while a mission run is active (Plan 88 Phase 2 drill B).

With no active run the tool starts the PlanRefineWorkflow and returns. While a
run is active the run reads its task graph when the Director's turn ends, so
the tool waits for the workflow and raises with the cause when it fails.
Services and the Temporal client are patched; no database or server is used.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ActivityError, ApplicationError, RetryState

from modules.backend.agents.deps.base import RunRefineTurn
from modules.backend.agents.mission.director.tools.refine_plan import refine_plan
from modules.backend.core.exceptions import ExternalServiceError
from modules.backend.services.budget import BudgetService
from modules.backend.services.mission import MissionService
from modules.backend.services.mission_plan import MissionPlanService
from modules.backend.services.mission_run import MissionRunService
from modules.backend.temporal.plan_refine_models import PlanRefineResult

PLAN_ID = "0b5a7c2e-1111-4222-8333-444455556666"
RUN_ID = "7f3e9d1c-aaaa-4bbb-8ccc-ddddeeeeffff"


@pytest.fixture
def client(monkeypatch) -> MagicMock:
    fake = MagicMock(start_workflow=AsyncMock(), execute_workflow=AsyncMock())
    monkeypatch.setattr(
        "modules.backend.temporal.client.get_temporal_client", AsyncMock(return_value=fake)
    )
    monkeypatch.setattr(
        MissionService, "get_mission", AsyncMock(return_value=SimpleNamespace(owner_id="owner"))
    )
    monkeypatch.setattr(
        MissionPlanService,
        "get_or_create_plan",
        AsyncMock(return_value=SimpleNamespace(id=PLAN_ID)),
    )
    monkeypatch.setattr(
        BudgetService, "get_status", AsyncMock(return_value=SimpleNamespace(per_run_usd=5.0))
    )
    return fake


def _active_run(monkeypatch, run: SimpleNamespace | None) -> None:
    monkeypatch.setattr(MissionRunService, "get_active_run", AsyncMock(return_value=run))


async def _call() -> dict:
    return await refine_plan(SimpleNamespace(commit=AsyncMock()), "mission-1", "next wave", None)


async def test_no_active_run_starts_and_returns(client, monkeypatch):
    _active_run(monkeypatch, None)

    result = await _call()

    assert result["status"] == "refining"
    client.start_workflow.assert_awaited_once()
    client.execute_workflow.assert_not_awaited()


async def test_active_run_waits_for_refinement(client, monkeypatch):
    _active_run(monkeypatch, SimpleNamespace(id=RUN_ID))
    client.execute_workflow.return_value = PlanRefineResult(
        plan_id=PLAN_ID, version=3, task_count=4, approved_count=1
    )

    result = await _call()

    client.start_workflow.assert_not_awaited()
    client.execute_workflow.assert_awaited_once()
    assert result["status"] == "refined"
    assert result["mission_run_id"] == RUN_ID
    assert (result["version"], result["task_count"], result["approved_count"]) == (3, 4, 1)


async def test_active_run_refine_failure_raises_cause(client, monkeypatch):
    _active_run(monkeypatch, SimpleNamespace(id=RUN_ID))
    activity_error = ActivityError(
        "activity failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="worker",
        activity_type="execute_plan_refine",
        activity_id="1",
        retry_state=RetryState.NON_RETRYABLE_FAILURE,
    )
    activity_error.__cause__ = ApplicationError("planner returned no tasks", type="ValidationError")
    failure = WorkflowFailureError(cause=activity_error)
    client.execute_workflow.side_effect = failure

    with pytest.raises(ExternalServiceError, match="Plan refinement failed: .*planner returned"):
        await _call()


async def test_refine_turn_marked_refined_even_when_the_refine_fails(client, monkeypatch):
    # The run's refine turn learns that refine_plan was called, whatever it
    # produced: with a declaration that is a contradiction (review of 4d5d315b).
    _active_run(monkeypatch, SimpleNamespace(id=RUN_ID))
    client.execute_workflow.side_effect = WorkflowFailureError(
        cause=ApplicationError("planner returned no tasks")
    )
    turn = RunRefineTurn(mission_run_id=RUN_ID)

    with pytest.raises(ExternalServiceError):
        await refine_plan(SimpleNamespace(commit=AsyncMock()), "mission-1", "next", None, turn)

    assert turn.refined is True
