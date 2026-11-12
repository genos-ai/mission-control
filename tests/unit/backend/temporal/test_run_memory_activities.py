"""Tests for compact_mission_context (88.3.3) and write_run_digest (88.3.7), Plan 88.

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
_TAGS = ["under", "over", "digest"]


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


async def _run(db_session: AsyncSession, mission_id: str, on_publish=None):
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
        bus_cls.return_value.publish = AsyncMock(side_effect=on_publish)
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

    calls: list[str] = []
    real_commit = db_session.commit

    async def _commit():
        calls.append("commit")
        await real_commit()

    commit = AsyncMock(side_effect=_commit)
    with patch.object(db_session, "commit", commit):
        result, bus_cls, redis, run_id = await _run(
            db_session, mid, on_publish=lambda *_: calls.append("publish")
        )

    assert result.compacted is True
    assert result.to_bytes < result.from_bytes
    assert calls == ["commit", "publish"]
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


# ── write_run_digest (88.3.7) ────────────────────────────────────────────


async def _digest(db_session: AsyncSession, *, force_deterministic: bool, extractor=None):
    from modules.backend.core.utils import utc_now
    from modules.backend.models.mission_run import MissionRun
    from modules.backend.schemas.run_memory import DigestNarrative
    from modules.backend.temporal.mission_run_models import WriteDigestInput
    from modules.backend.temporal.run_memory_activities import write_run_digest

    @asynccontextmanager
    async def _session():
        yield db_session

    mid = _MID("digest")
    run_id = await _make_run(db_session, mid)
    run = await db_session.get(MissionRun, run_id)
    run.started_at = utc_now()
    run.context_version_start = 0
    await db_session.flush()

    narrator = AsyncMock(
        return_value=(DigestNarrative(summary="Narrated.", open_items=[], headlines=[]), 0.05)
    )
    extract = extractor or AsyncMock(return_value=[])
    with (
        patch(f"{_MOD}.get_async_session", _session),
        patch(f"{_MOD}.AsyncRedis.from_url", return_value=MagicMock(aclose=AsyncMock())),
        patch(f"{_MOD}.SessionEventBus") as bus_cls,
        patch(f"{_MOD}.generate_digest_narrative", narrator),
        patch(f"{_MOD}.MissionLearningExtractor") as extractor_cls,
    ):
        bus_cls.return_value.publish_to_mission = AsyncMock()
        extractor_cls.return_value.extract_for_mission = extract
        result = await ActivityEnvironment().run(
            write_run_digest,
            WriteDigestInput(
                mission_run_id=run_id,
                status="succeeded",
                reason="no_further_work",
                force_deterministic=force_deterministic,
            ),
        )
    return result, narrator, extract, bus_cls, run_id


@pytest.mark.asyncio
async def test_write_run_digest_activity_returns_generator(db_session):
    from modules.backend.events.mission_run_types import MissionRunDigestWrittenEvent
    from modules.backend.repositories.mission_run_digest import MissionRunDigestRepository

    result, narrator, extract, bus_cls, run_id = await _digest(
        db_session, force_deterministic=False
    )

    narrator.assert_awaited_once()
    assert result.generator == "agent"
    stored = await MissionRunDigestRepository(db_session).get_by_run(run_id)
    assert result.digest_id == stored.id
    extract.assert_awaited_once_with(_MID("digest"))
    event = bus_cls.return_value.publish_to_mission.await_args.args[1]
    assert isinstance(event, MissionRunDigestWrittenEvent)
    assert (event.digest_id, event.generator, event.source) == (stored.id, "agent", "run_memory")


@pytest.mark.asyncio
async def test_force_deterministic_passes_no_narrator(db_session):
    result, narrator, _, _, _ = await _digest(db_session, force_deterministic=True)

    narrator.assert_not_awaited()
    assert result.generator == "deterministic"


@pytest.mark.asyncio
async def test_learning_extraction_failure_does_not_fail_digest(db_session):
    from sqlalchemy.exc import OperationalError

    failing = AsyncMock(side_effect=OperationalError("SELECT 1", {}, Exception("db gone")))

    result, _, extract, bus_cls, _ = await _digest(
        db_session, force_deterministic=True, extractor=failing
    )

    extract.assert_awaited_once()
    last = bus_cls.return_value.publish_to_mission.await_args.args[1]
    assert (last.event_type, last.level) == ("system.info", "warning")
    assert result.generator == "deterministic"
    assert result.digest_id
