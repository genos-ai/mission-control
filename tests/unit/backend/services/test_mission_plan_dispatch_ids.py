"""dispatch_approved builds its gate from the plan's mode (Plan 88 steps 88.0.3, 88.1.7).

The run, plan and mission repositories are mocked; dispatch stops at the
patched create_gate, or at the patched handle_mission for the run-id check.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


def _mission_repo(execution_environment: str = "local") -> MagicMock:
    mission = SimpleNamespace(
        brief="brief",
        description=None,
        name="mission",
        default_roster="default",
        execution_environment=execution_environment,
        repo_root=None,
    )
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=mission)
    return MagicMock(return_value=repo)


def _run_repo(plan_id: str) -> MagicMock:
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=SimpleNamespace(plan_id=plan_id))
    return MagicMock(return_value=repo)


class _StopAfterGate(Exception):
    """Raised by the patched create_gate to end dispatch_approved early."""


async def test_dispatch_approved_builds_gate_from_plan_mode():
    plan = _plan(gate_mode=GateMode.MANUAL)
    approved = SimpleNamespace(id=str(uuid.uuid4()), status=None, last_attempt_at=None)
    list_by_run = AsyncMock(return_value=[approved])
    orchestrator = SimpleNamespace(
        _repo=SimpleNamespace(get_by_id=AsyncMock(return_value=plan)),
        _task_repo=SimpleNamespace(list_by_run=list_by_run),
        _session=SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock()),
        _event_bus=MagicMock(),
        _log_operation=MagicMock(),
    )
    create_gate = MagicMock(side_effect=_StopAfterGate)
    taskio = mission_plan_dispatch.mission_plan_taskio
    run_id = str(uuid.uuid4())

    with (
        patch.object(taskio, "materialize_task_plan", MagicMock()),
        patch.object(taskio, "derive_subset_task_plan", AsyncMock()),
        patch.object(mission_plan_dispatch, "MissionRunRepository", _run_repo(plan.id)),
        patch.object(mission_plan_dispatch, "MissionRepository", _mission_repo()),
        patch("modules.backend.agents.mission_control.gate.create_gate", create_gate),
        pytest.raises(_StopAfterGate),
    ):
        await mission_plan_dispatch.dispatch_approved(
            orchestrator,
            run_id,
            str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            execution_record_id=str(uuid.uuid4()),
        )

    assert list_by_run.await_args.args == (run_id,)
    assert create_gate.call_args.kwargs["mode_override"] == GateMode.MANUAL
    assert create_gate.call_args.kwargs["event_bus"] is orchestrator._event_bus


class _StopAtHandleMission(Exception):
    """Raised by the patched handle_mission once its kwargs are captured."""


async def test_dispatch_approved_passes_run_id_to_handle_mission():
    """A dropped mission_run_id kwarg here zeroes the run's recorded cost."""
    plan = _plan()
    approved = SimpleNamespace(id=str(uuid.uuid4()), status=None, last_attempt_at=None)
    orchestrator = SimpleNamespace(
        _repo=SimpleNamespace(get_by_id=AsyncMock(return_value=plan)),
        _task_repo=SimpleNamespace(list_by_run=AsyncMock(return_value=[approved])),
        _session=SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock()),
        _event_bus=MagicMock(),
        _log_operation=MagicMock(),
    )
    handle_mission = AsyncMock(side_effect=_StopAtHandleMission)
    taskio = mission_plan_dispatch.mission_plan_taskio
    run_id = str(uuid.uuid4())

    with (
        patch.object(taskio, "materialize_task_plan", MagicMock()),
        patch.object(taskio, "derive_subset_task_plan", AsyncMock()),
        patch.object(taskio, "load_prior_outputs", AsyncMock(return_value={})),
        patch.object(mission_plan_dispatch, "MissionRunRepository", _run_repo(plan.id)),
        patch.object(mission_plan_dispatch, "MissionRepository", _mission_repo()),
        patch("modules.backend.agents.mission_control.gate.create_gate", MagicMock()),
        patch(
            "modules.backend.agents.mission_control.mission_control.handle_mission",
            handle_mission,
        ),
        pytest.raises(_StopAtHandleMission),
    ):
        await mission_plan_dispatch.dispatch_approved(
            orchestrator,
            run_id,
            str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            execution_record_id=str(uuid.uuid4()),
        )

    assert handle_mission.await_args.kwargs["mission_run_id"] == run_id
