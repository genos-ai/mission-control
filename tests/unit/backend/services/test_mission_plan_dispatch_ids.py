"""Tests for the deterministic MissionRunWorkflow start (Plan 88 step 88.0.3).

The Temporal client and the mission repository are mocked; the dispatch
function's id and policy choices are exercised for real.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from modules.backend.core.exceptions import ConflictError
from modules.backend.services import mission_plan_dispatch


def _plan(gate_mode: str | None = "autonomous") -> SimpleNamespace:
    return SimpleNamespace(
        id=str(uuid.uuid4()),
        mission_id=str(uuid.uuid4()),
        budget_usd_ceiling=10.0,
        total_spent_usd=1.0,
        supervisor_iteration_count=3,
        gate_mode=gate_mode,
    )


def _orchestrator() -> SimpleNamespace:
    return SimpleNamespace(_session=SimpleNamespace(flush=AsyncMock()))


def _mission_repo(execution_environment: str = "local") -> MagicMock:
    mission = SimpleNamespace(
        brief="brief",
        description=None,
        name="mission",
        default_roster="default",
        execution_environment=execution_environment,
    )
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=mission)
    return MagicMock(return_value=repo)


async def _start(
    client: MagicMock, plan: SimpleNamespace, execution_environment: str = "local"
) -> str:
    with (
        patch(
            "modules.backend.temporal.client.get_temporal_client",
            AsyncMock(return_value=client),
        ),
        patch.object(
            mission_plan_dispatch, "MissionRepository", _mission_repo(execution_environment)
        ),
    ):
        return await mission_plan_dispatch.start_temporal_run_workflow(
            _orchestrator(), plan, session_id=str(uuid.uuid4())
        )


async def test_start_uses_deterministic_id_and_fail_conflict_policy():
    plan = _plan()
    client = MagicMock()
    client.start_workflow = AsyncMock()

    workflow_id = await _start(client, plan)

    assert workflow_id == f"mission-run-{plan.id}"
    kwargs = client.start_workflow.await_args.kwargs
    assert kwargs["id"] == f"mission-run-{plan.id}"
    assert kwargs["id_reuse_policy"] == WorkflowIDReusePolicy.ALLOW_DUPLICATE
    assert kwargs["id_conflict_policy"] == WorkflowIDConflictPolicy.FAIL


async def test_start_conflict_raises_conflict_error():
    plan = _plan()
    client = MagicMock()
    client.start_workflow = AsyncMock(
        side_effect=WorkflowAlreadyStartedError(f"mission-run-{plan.id}", "MissionRunWorkflow")
    )

    with pytest.raises(ConflictError):
        await _start(client, plan)


async def test_start_passes_plan_gate_mode_not_environment():
    plan = _plan(gate_mode="manual")
    client = MagicMock()
    client.start_workflow = AsyncMock()

    await _start(client, plan, execution_environment="container")

    workflow_input = client.start_workflow.await_args.args[1]
    assert workflow_input.gate_mode == "manual"
