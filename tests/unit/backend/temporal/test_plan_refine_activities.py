"""Tests for execute_plan_refine (Plan 88 step 88.0.5): only AUTONOMOUS auto-approves.

refine(), approve_all_proposed(), the mission lookup, Redis and the DB
session are patched; the activity's gate decision runs for real.
"""

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from temporalio.testing import ActivityEnvironment

from modules.backend.temporal.plan_refine_activities import execute_plan_refine
from modules.backend.temporal.plan_refine_models import PlanRefineInput


async def _run_refine(gate_mode: str | None) -> AsyncMock:
    """Run the activity with a refined plan in ``gate_mode``; return the approve mock."""
    refined = SimpleNamespace(gate_mode=gate_mode, version=2, tasks=[object(), object()])
    approve = AsyncMock(return_value=["t1", "t2"])
    db = SimpleNamespace(commit=AsyncMock())
    redis = MagicMock(aclose=AsyncMock())

    @asynccontextmanager
    async def _session():
        yield db

    with (
        patch("redis.asyncio.Redis.from_url", return_value=redis),
        patch("modules.backend.core.config.get_redis_url", return_value="redis://test"),
        patch("modules.backend.core.database.get_async_session", _session),
        patch(
            "modules.backend.services.mission_plan_orchestrator.MissionPlanOrchestrator.refine",
            AsyncMock(return_value=refined),
        ),
        patch(
            "modules.backend.services.mission.MissionService.get_mission",
            AsyncMock(return_value=SimpleNamespace(owner_id=str(uuid.uuid4()))),
        ),
        patch(
            "modules.backend.services.mission_plan.MissionPlanService.approve_all_proposed",
            approve,
        ),
    ):
        await ActivityEnvironment().run(
            execute_plan_refine,
            PlanRefineInput(
                mission_id=str(uuid.uuid4()),
                plan_id=str(uuid.uuid4()),
                instructions="refine it",
                user_id=str(uuid.uuid4()),
            ),
        )
    return approve


@pytest.mark.asyncio
async def test_refine_null_gate_mode_does_not_approve():
    approve = await _run_refine(None)
    approve.assert_not_awaited()


@pytest.mark.asyncio
async def test_refine_manual_gate_mode_does_not_approve():
    approve = await _run_refine("manual")
    approve.assert_not_awaited()


@pytest.mark.asyncio
async def test_refine_autonomous_approves():
    approve = await _run_refine("autonomous")
    approve.assert_awaited_once()
