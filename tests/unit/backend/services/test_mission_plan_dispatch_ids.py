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
from modules.backend.models.mission_plan import GateMode
from modules.backend.services import mission_plan_dispatch


def _plan(gate_mode: GateMode = GateMode.AUTONOMOUS) -> SimpleNamespace:
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
    plan = _plan(gate_mode=GateMode.MANUAL)
    client = MagicMock()
    client.start_workflow = AsyncMock()

    await _start(client, plan, execution_environment="container")

    workflow_input = client.start_workflow.await_args.args[1]
    assert workflow_input.gate_mode == "manual"


class _StopAfterGate(Exception):
    """Raised by the patched create_gate to end dispatch_approved early."""


async def test_dispatch_approved_builds_gate_from_plan_mode():
    plan = _plan(gate_mode=GateMode.MANUAL)
    approved = SimpleNamespace(id=str(uuid.uuid4()), status=None, last_attempt_at=None)
    orchestrator = SimpleNamespace(
        _repo=SimpleNamespace(get_by_id=AsyncMock(return_value=plan)),
        _task_repo=SimpleNamespace(get_by_plan_id=AsyncMock(return_value=[approved])),
        _session=SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock()),
        _event_bus=MagicMock(),
        _log_operation=MagicMock(),
    )
    create_gate = MagicMock(side_effect=_StopAfterGate)
    taskio = mission_plan_dispatch.mission_plan_taskio

    with (
        patch.object(taskio, "materialize_task_plan", MagicMock()),
        patch.object(taskio, "derive_subset_task_plan", AsyncMock()),
        patch.object(taskio, "infer_task_type", MagicMock(return_value="general")),
        patch.object(
            mission_plan_dispatch, "create_early_execution_record", AsyncMock(return_value=None)
        ),
        patch.object(mission_plan_dispatch, "MissionRepository", _mission_repo()),
        patch("modules.backend.agents.mission_control.gate.create_gate", create_gate),
        pytest.raises(_StopAfterGate),
    ):
        await mission_plan_dispatch.dispatch_approved(
            orchestrator, plan.id, str(uuid.uuid4()), temporal_workflow_id="mission-run-test"
        )

    assert create_gate.call_args.kwargs["mode_override"] == GateMode.MANUAL
    assert create_gate.call_args.kwargs["event_bus"] is orchestrator._event_bus
