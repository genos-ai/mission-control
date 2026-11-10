"""Approval endpoints and the refine activity start or wake mission runs (Plan 88 step 88.1.9).

Rows are committed (committed_owner) because the endpoints commit before they
start a run. TemporalWorkflowGateway is mocked; the event bus records events.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.testing import ActivityEnvironment

from modules.backend.core.database import get_db_session
from modules.backend.core.dependencies import get_current_user, get_event_bus
from modules.backend.models.mission import Mission, MissionMember, MissionMemberRole
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.models.mission_run import MissionRun, MissionRunTrigger
from modules.backend.models.task import Task, TaskStatus
from modules.backend.models.user import User
from modules.backend.repositories.task import TaskRepository
from modules.backend.services.mission_run import MissionRunService
from modules.backend.temporal.config_snapshots import build_workflow_timeouts_snapshot
from modules.backend.temporal.plan_refine_activities import execute_plan_refine
from modules.backend.temporal.plan_refine_models import PlanRefineInput
from modules.backend.temporal.workflow_gateway import TemporalWorkflowGateway, WorkflowState
from tests.integration.backend.services.test_mission_schedule_service import RecordingBus

Factory = async_sessionmaker[AsyncSession]
AGENT = "system.summarization.agent"


@pytest.fixture
def gateway(monkeypatch) -> AsyncMock:
    """The gateway every MissionRunService call connects to."""
    fake = AsyncMock()
    fake.signal.return_value = WorkflowState.RUNNING
    monkeypatch.setattr(TemporalWorkflowGateway, "connect", AsyncMock(return_value=fake))
    return fake


@pytest.fixture
def api(client: AsyncClient, db_session_factory: Factory):
    """Serve requests on committing sessions; returns a setter for the acting user."""

    async def committing_session():
        async with db_session_factory() as session:
            yield session
            await session.commit()

    app = client.app
    app.dependency_overrides[get_db_session] = committing_session
    app.dependency_overrides[get_event_bus] = RecordingBus

    def act_as(user: User) -> AsyncClient:
        app.dependency_overrides[get_current_user] = lambda: user
        return client

    return act_as


async def _gate_mode(factory: Factory, plan: MissionPlan, mode: GateMode) -> None:
    async with factory() as session:
        await session.execute(
            text("UPDATE mission_plans SET gate_mode = :mode WHERE id = :id"),
            {"mode": mode.name, "id": plan.id},
        )
        await session.commit()


async def _task(factory: Factory, plan: MissionPlan, status: TaskStatus) -> str:
    async with factory() as session:
        task = await TaskRepository(session).create_task(
            plan_id=plan.id,
            mission_id=plan.mission_id,
            agent=AGENT,
            description=f"{status.value} task",
            instructions="Do it",
            status=status,
        )
        await session.commit()
        return task.id


async def _runs(factory: Factory, mission: Mission) -> list[MissionRun]:
    async with factory() as session:
        result = await session.scalars(
            select(MissionRun).where(MissionRun.mission_id == mission.id)
        )
        return list(result)


async def _start(factory: Factory, mission: Mission, user: User) -> MissionRun:
    async with factory() as session:
        return await MissionRunService(session, RecordingBus()).start_run(
            mission.id,
            trigger=MissionRunTrigger.MANUAL,
            objective=None,
            user_id=user.id,
            session_id=None,
        )


def _plan_url(mission: Mission, path: str) -> str:
    return f"/api/v1/missions/{mission.id}/plan/{path}"


async def test_approve_endpoint_starts_run_for_autonomous_idle_mission(
    api, gateway, committed_owner, db_session_factory
) -> None:
    user, mission, plan = await committed_owner()
    await _gate_mode(db_session_factory, plan, GateMode.AUTONOMOUS)
    task_id = await _task(db_session_factory, plan, TaskStatus.PROPOSED)

    resp = await api(user).post(_plan_url(mission, f"tasks/{task_id}/approve"))

    assert resp.status_code == 200, resp.text
    (run,) = await _runs(db_session_factory, mission)
    gateway.start_mission_run.assert_awaited_once()
    (inp,) = gateway.start_mission_run.await_args.args
    assert inp.mission_run_id == run.id
    assert run.trigger == MissionRunTrigger.MANUAL
    gateway.signal.assert_not_awaited()


async def test_approve_endpoint_signals_active_run(
    api, gateway, committed_owner, db_session_factory
) -> None:
    user, mission, plan = await committed_owner()
    run = await _start(db_session_factory, mission, user)
    task_id = await _task(db_session_factory, plan, TaskStatus.PROPOSED)

    resp = await api(user).post(_plan_url(mission, f"tasks/{task_id}/approve"))

    assert resp.status_code == 200, resp.text
    gateway.signal.assert_awaited_once()
    workflow_id, signal, arg = gateway.signal.await_args.args
    assert (workflow_id, signal) == (run.temporal_workflow_id, "tasks_approved")
    assert arg.task_ids == [task_id]
    gateway.start_mission_run.assert_awaited_once()


async def test_retry_endpoint_starts_run_for_autonomous_idle_mission(
    api, gateway, committed_owner, db_session_factory
) -> None:
    user, mission, plan = await committed_owner()
    await _gate_mode(db_session_factory, plan, GateMode.AUTONOMOUS)
    task_id = await _task(db_session_factory, plan, TaskStatus.FAILED)

    resp = await api(user).post(_plan_url(mission, f"tasks/{task_id}/retry"))

    assert resp.status_code == 200, resp.text
    (run,) = await _runs(db_session_factory, mission)
    gateway.start_mission_run.assert_awaited_once()
    (inp,) = gateway.start_mission_run.await_args.args
    assert inp.mission_run_id == run.id


async def test_manual_mode_approve_does_not_start_run(
    api, gateway, committed_owner, db_session_factory
) -> None:
    user, mission, plan = await committed_owner()
    task_id = await _task(db_session_factory, plan, TaskStatus.PROPOSED)

    resp = await api(user).post(_plan_url(mission, f"tasks/{task_id}/approve"))

    assert resp.status_code == 200, resp.text
    async with db_session_factory() as session:
        assert (await session.get(Task, task_id)).status == TaskStatus.APPROVED
    gateway.start_mission_run.assert_not_awaited()
    gateway.signal.assert_not_awaited()
    assert await _runs(db_session_factory, mission) == []


async def test_dispatch_endpoint_conflict_when_active(
    api, gateway, committed_owner, db_session_factory
) -> None:
    user, mission, _ = await committed_owner()
    run = await _start(db_session_factory, mission, user)

    resp = await api(user).post(_plan_url(mission, "dispatch"))

    assert resp.status_code == 409, resp.text
    assert [r.id for r in await _runs(db_session_factory, mission)] == [run.id]


async def test_dispatch_endpoint_viewer_forbidden(
    api, gateway, committed_owner, db_session_factory
) -> None:
    _, mission, _ = await committed_owner()
    viewer, _, _ = await committed_owner()
    async with db_session_factory() as session:
        session.add(
            MissionMember(mission_id=mission.id, user_id=viewer.id, role=MissionMemberRole.VIEWER)
        )
        await session.commit()

    resp = await api(viewer).post(_plan_url(mission, "dispatch"))

    assert resp.status_code == 403, resp.text
    gateway.start_mission_run.assert_not_awaited()
    assert await _runs(db_session_factory, mission) == []


async def test_refine_activity_does_not_auto_approve_manual(
    gateway, committed_owner, db_session_factory
) -> None:
    user, mission, plan = await committed_owner()
    task_id = await _task(db_session_factory, plan, TaskStatus.PROPOSED)
    refined = MagicMock(gate_mode=GateMode.MANUAL, version=2, tasks=[task_id])

    @asynccontextmanager
    async def _session():
        async with db_session_factory() as session:
            yield session

    with (
        patch("redis.asyncio.Redis.from_url", return_value=MagicMock(aclose=AsyncMock())),
        patch("modules.backend.core.database.get_async_session", _session),
        patch(
            "modules.backend.services.mission_plan_orchestrator.MissionPlanOrchestrator.refine",
            AsyncMock(return_value=refined),
        ),
    ):
        result = await ActivityEnvironment().run(
            execute_plan_refine,
            PlanRefineInput(
                mission_id=mission.id,
                plan_id=plan.id,
                instructions="refine it",
                user_id=user.id,
                mission_budget_usd=10.0,
                timeouts=build_workflow_timeouts_snapshot(),
            ),
        )

    assert result.approved_count == 0
    async with db_session_factory() as session:
        assert (await session.get(Task, task_id)).status == TaskStatus.PROPOSED
    gateway.start_mission_run.assert_not_awaited()
    gateway.signal.assert_not_awaited()
    assert await _runs(db_session_factory, mission) == []
