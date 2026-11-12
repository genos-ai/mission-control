"""Tests for compact_mission_context (Plan 88, 88.3.3).

The activity runs against the real test database: get_async_session is bound
to the rolled-back db_session, so the activity's commit stays inside the test
transaction. Redis and SessionEventBus are patched.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.testing import ActivityEnvironment

from modules.backend.events.mission_run_types import ContextCompactedEvent
from modules.backend.services.mission_context import MissionContextManager, _cache
from modules.backend.temporal.mission_run_models import CompactContextInput
from modules.backend.temporal.run_memory_activities import compact_mission_context
from tests.conftest import TEST_USER_ID

_MOD = "modules.backend.temporal.run_memory_activities"
_TEST_NS = UUID("00000000-0000-0000-0000-000000000000")
_TAGS = ["under", "over"]


def _MID(tag: str) -> str:
    return str(uuid5(_TEST_NS, f"mission:compact-activity-{tag}"))


@pytest.fixture(autouse=True)
async def _ensure_parent_rows(test_user, db_session: AsyncSession):
    from modules.backend.models.mission import Mission
    from modules.backend.models.mission_plan import GateMode, MissionPlan

    for tag in _TAGS:
        db_session.add(
            Mission(id=_MID(tag), name=f"cact-{tag}", description="test", owner_id=TEST_USER_ID)
        )
    await db_session.flush()
    for tag in _TAGS:
        db_session.add(MissionPlan(mission_id=_MID(tag), gate_mode=GateMode.MANUAL))
    await db_session.flush()


@pytest.fixture(autouse=True)
def _clear_cache():
    _cache.clear()
    yield
    _cache.clear()


async def _make_run(db_session: AsyncSession, mission_id: str) -> str:
    from sqlalchemy import select

    from modules.backend.models.mission_plan import MissionPlan
    from modules.backend.models.mission_run import MissionRun, MissionRunStatus, MissionRunTrigger
    from modules.backend.repositories.mission import MissionRepository

    plan_id = (
        await db_session.execute(select(MissionPlan.id).where(MissionPlan.mission_id == mission_id))
    ).scalar_one()
    run = MissionRun(
        mission_id=mission_id,
        plan_id=plan_id,
        sequence=await MissionRepository(db_session).increment_run_sequence(mission_id),
        trigger=MissionRunTrigger.MANUAL,
        status=MissionRunStatus.RUNNING,
    )
    db_session.add(run)
    await db_session.flush()
    return run.id


async def _run(db_session: AsyncSession, mission_id: str):
    @asynccontextmanager
    async def _session():
        yield db_session

    run_id = await _make_run(db_session, mission_id)
    redis = MagicMock(aclose=AsyncMock())
    with (
        patch(f"{_MOD}.get_async_session", _session),
        patch(f"{_MOD}.AsyncRedis.from_url", return_value=redis),
        patch(f"{_MOD}.SessionEventBus") as bus_cls,
    ):
        bus_cls.return_value.publish = AsyncMock()
        result = await ActivityEnvironment().run(
            compact_mission_context,
            CompactContextInput(mission_id=mission_id, mission_run_id=run_id),
        )
    return result, bus_cls, redis, run_id


@pytest.mark.asyncio
async def test_compact_mission_context_noop_under_threshold(db_session):
    mid = _MID("under")
    await MissionContextManager(db_session).create_context(mid, "under", "desc")

    result, bus_cls, _, _ = await _run(db_session, mid)

    assert result.compacted is False
    assert (result.from_bytes, result.to_bytes) == (0, 0)
    bus_cls.assert_not_called()


@pytest.mark.asyncio
async def test_compact_mission_context_publishes_after_commit(db_session):
    mid = _MID("over")
    manager = MissionContextManager(db_session)
    await manager.create_context(mid, "over", "desc")
    await manager.apply_updates(
        mid,
        [
            {"op": "replace", "path": "identity.purpose", "value": "p" * 13_000},
            {"op": "add", "path": "notes", "value": "n" * 4000},
        ],
        agent_id=None,
        task_id=None,
        mission_run_id=None,
        reason="seed",
    )

    commit = AsyncMock(wraps=db_session.commit)
    with patch.object(db_session, "commit", commit):
        result, bus_cls, redis, run_id = await _run(db_session, mid)

    assert result.compacted is True
    assert result.to_bytes < result.from_bytes
    commit.assert_awaited_once()
    bus_cls.assert_called_once_with(redis, mission_id=mid)
    bus_cls.return_value.publish.assert_awaited_once()
    event = bus_cls.return_value.publish.await_args.args[0]
    assert isinstance(event, ContextCompactedEvent)
    assert event.event_type == "context.compacted"
    assert str(event.session_id) == mid
    assert event.source == "compaction"
    assert event.mission_id == mid
    assert event.mission_run_id == run_id
    changes = await MissionContextManager(db_session).get_history(mid)
    assert {c.mission_run_id for c in changes if c.agent_id == "system:compaction"} == {run_id}
    assert (event.from_bytes, event.to_bytes) == (result.from_bytes, result.to_bytes)
    assert event.archived_paths == ["architecture", "decisions", "notes"]
    redis.aclose.assert_awaited_once()
