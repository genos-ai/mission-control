"""Tests for the MissionRunWorkflow activities' event bus binding (Plan 88 Phase 1).

plan_mission_run reaches the Planning Agent, whose tools call bare publish();
SessionEventBus drops those events unless the bus is bound to a mission. Redis,
the DB session, MissionRunRepository, MissionRunService and SessionEventBus are
patched; the activities' bus construction runs for real.
"""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from temporalio.testing import ActivityEnvironment

from modules.backend.temporal.mission_run_activities import begin_mission_run, plan_mission_run
from modules.backend.temporal.mission_run_models import BeginRunInput, PlanRunInput

MISSION_ID = "00000000-0000-0000-0000-000000000001"
RUN_ID = "00000000-0000-0000-0000-0000000000a1"


@contextmanager
def _patched_infra():
    """Patch the activity's infrastructure; yield the mocks the tests assert on."""
    from contextlib import asynccontextmanager

    db = SimpleNamespace()
    redis = MagicMock(aclose=AsyncMock())

    @asynccontextmanager
    async def _session():
        yield db

    app_config = MagicMock()
    app_config.temporal.mission_run.task_heartbeat_interval_seconds = 60

    with (
        patch("redis.asyncio.Redis.from_url", return_value=redis),
        patch("modules.backend.core.config.get_redis_url", return_value="redis://test"),
        patch("modules.backend.core.config.get_app_config", return_value=app_config),
        patch("modules.backend.core.database.get_async_session", _session),
        patch("modules.backend.repositories.mission_run.MissionRunRepository") as repo_cls,
        patch("modules.backend.services.mission_run.MissionRunService") as svc_cls,
        patch("modules.backend.events.bus.SessionEventBus") as bus_cls,
    ):
        repo_cls.return_value.get_by_id = AsyncMock(
            return_value=SimpleNamespace(id=RUN_ID, mission_id=MISSION_ID)
        )
        svc_cls.return_value.plan = AsyncMock(return_value="planned")
        svc_cls.return_value.begin = AsyncMock(return_value="begun")
        yield SimpleNamespace(
            db=db, redis=redis, repo_cls=repo_cls, svc_cls=svc_cls, bus_cls=bus_cls
        )


@pytest.mark.asyncio
async def test_plan_mission_run_binds_bus_to_runs_mission():
    with _patched_infra() as m:
        result = await ActivityEnvironment().run(
            plan_mission_run, PlanRunInput(mission_run_id=RUN_ID, session_id="s-1")
        )

    assert result == "planned"
    m.repo_cls.return_value.get_by_id.assert_awaited_once_with(RUN_ID)
    m.bus_cls.assert_called_once_with(m.redis, mission_id=MISSION_ID)
    m.svc_cls.assert_called_once_with(m.db, m.bus_cls.return_value)
    m.svc_cls.return_value.plan.assert_awaited_once_with(RUN_ID, "s-1")
    m.redis.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_begin_mission_run_keeps_unbound_bus():
    """begin only emits through publish_to_mission; it needs no run lookup for the bus."""
    with _patched_infra() as m:
        result = await ActivityEnvironment().run(
            begin_mission_run, BeginRunInput(mission_run_id=RUN_ID)
        )

    assert result == "begun"
    m.repo_cls.return_value.get_by_id.assert_not_called()
    m.bus_cls.assert_called_once_with(m.redis, mission_id=None)
