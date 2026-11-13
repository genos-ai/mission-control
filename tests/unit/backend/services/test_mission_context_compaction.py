"""Tests for deterministic MCD compaction (Plan 88, 88.3.3).

Per P12: tests run against the live platform. Uses the real db_session fixture
with transaction rollback for isolation and the real missions config
(pcd_max_size_bytes 20480, pcd_target_size_bytes 15360, threshold 80%).
"""

import copy
from datetime import datetime, timezone
from uuid import UUID, uuid5

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config import get_app_config
from modules.backend.models.mission_context import ChangeType, ContextChange
from modules.backend.models.mission_history import MissionDecision
from modules.backend.repositories.mission_context import (
    ContextMilestoneRepository,
    MissionContextRepository,
)
from modules.backend.services.mcd_pruning import mcd_size_bytes
from modules.backend.services.mission_context import MissionContextManager, _cache
from modules.backend.services.mission_context_compaction import MissionContextCompactor
from tests.conftest import TEST_USER_ID

_TEST_NS = UUID("00000000-0000-0000-0000-000000000000")
_TAGS = [
    "write",
    "snap",
    "order",
    "protect",
    "single",
    "over",
    "noop",
    "det",
    "explicit",
    "kept",
    "nothing",
    "skip",
]
_OLD_DATE = "2000-01-01"


def _MID(tag: str) -> str:
    return str(uuid5(_TEST_NS, f"mission:compact-{tag}"))


@pytest.fixture(autouse=True)
async def _ensure_parent_rows(test_user, db_session: AsyncSession):
    """Create Mission rows that MissionContext.mission_id FKs to."""
    from modules.backend.models.mission import Mission
    from modules.backend.models.mission_plan import GateMode, MissionPlan

    for tag in _TAGS:
        db_session.add(
            Mission(id=_MID(tag), name=f"compact-{tag}", description="test", owner_id=TEST_USER_ID)
        )
    await db_session.flush()
    for tag in _TAGS:
        db_session.add(
            MissionPlan(
                mission_id=_MID(tag),
                gate_mode=GateMode.MANUAL,
                budget_per_run_usd=5.0,
                budget_per_month_usd=100.0,
            )
        )
    await db_session.flush()


@pytest.fixture(autouse=True)
def _clear_cache():
    _cache.clear()
    yield
    _cache.clear()


@pytest.fixture
def manager(db_session: AsyncSession) -> MissionContextManager:
    return MissionContextManager(db_session)


def _limits() -> tuple[int, int]:
    cfg = get_app_config().missions
    return cfg.pcd_max_size_bytes, cfg.pcd_target_size_bytes


def _old_decisions(count: int, rationale_bytes: int) -> list[dict]:
    return [
        {
            "id": f"d{i}",
            "domain": "api",
            "decision": f"decision {i}",
            "rationale": "r" * rationale_bytes,
            "made_by": "architect",
            "date": _OLD_DATE,
        }
        for i in range(count)
    ]


async def _seed(manager: MissionContextManager, mid: str, updates: list[dict]) -> int:
    await manager.create_context(mid, mid, "desc")
    version, errors = await manager.apply_updates(
        mid, updates, agent_id=None, task_id=None, mission_run_id=None, reason="seed"
    )
    assert errors == []
    return version


async def _ctx(db_session: AsyncSession, mid: str):
    return await MissionContextRepository(db_session).get_by_mission_id(mid)


async def _changes_at(
    db_session: AsyncSession, context_id: str, version: int
) -> list[ContextChange]:
    result = await db_session.execute(
        select(ContextChange)
        .where(ContextChange.context_id == context_id)
        .where(ContextChange.version == version)
        .order_by(ContextChange.created_at)
    )
    return list(result.scalars().all())


class TestWritePath:
    @pytest.mark.asyncio
    async def test_write_over_max_triggers_compaction_not_rejection(self, manager, db_session):
        mid = _MID("write")
        max_bytes, target_bytes = _limits()
        await _seed(
            manager,
            mid,
            [
                {"op": "replace", "path": "identity.purpose", "value": "p" * 13_000},
                {"op": "replace", "path": "decisions", "value": _old_decisions(6, 1000)},
            ],
        )
        ctx = await _ctx(db_session, mid)
        assert target_bytes < mcd_size_bytes(ctx.context_data) <= max_bytes

        version, errors = await manager.apply_updates(
            mid,
            [{"op": "add", "path": "architecture.data_flow", "value": "x" * 1000}],
            agent_id="a.agent",
            task_id=None,
            mission_run_id=None,
            reason="test",
        )

        assert errors == []
        assert version == 3
        ctx = await _ctx(db_session, mid)
        assert ctx.version == 3
        assert ctx.context_data["decisions"] == []
        assert ctx.context_data["architecture"]["data_flow"] == "x" * 1000
        assert mcd_size_bytes(ctx.context_data) <= max_bytes
        changes = await _changes_at(db_session, ctx.id, 3)
        assert {(c.change_type, c.path) for c in changes} == {
            (ChangeType.PRUNE, "decisions"),
            (ChangeType.ADD, "architecture.data_flow"),
        }
        archived = (
            await db_session.execute(
                select(func.count())
                .select_from(MissionDecision)
                .where(MissionDecision.mission_id == mid)
            )
        ).scalar_one()
        assert archived == 6

    @pytest.mark.asyncio
    async def test_single_update_larger_than_target_rejected(self, manager, db_session):
        mid = _MID("single")
        max_bytes, _ = _limits()
        await manager.create_context(mid, mid, "desc")

        version, errors = await manager.apply_updates(
            mid,
            [{"op": "add", "path": "architecture.data_flow", "value": "x" * (max_bytes + 1)}],
            agent_id=None,
            task_id=None,
            mission_run_id=None,
            reason="test",
        )

        assert version == 1
        assert errors == ["Update at architecture.data_flow exceeds pcd_target_size_bytes"]
        ctx = await _ctx(db_session, mid)
        assert ctx.version == 1
        assert await _changes_at(db_session, ctx.id, 2) == []

    @pytest.mark.asyncio
    async def test_protected_sections_over_max_returns_error_without_write(
        self, manager, db_session
    ):
        mid = _MID("over")
        max_bytes, target_bytes = _limits()
        await _seed(
            manager, mid, [{"op": "replace", "path": "identity.purpose", "value": "p" * 19_500}]
        )
        ctx = await _ctx(db_session, mid)
        assert mcd_size_bytes(ctx.context_data) <= max_bytes

        version, errors = await manager.apply_updates(
            mid,
            [{"op": "add", "path": "guardrails.-", "value": "g" * 1500}],
            agent_id=None,
            task_id=None,
            mission_run_id=None,
            reason="test",
        )

        assert version == 2
        assert errors == ["MCD protected sections exceed pcd_max_size_bytes after compaction"]
        ctx = await _ctx(db_session, mid)
        assert ctx.version == 2
        assert ctx.context_data["guardrails"] == []
        assert await _changes_at(db_session, ctx.id, 3) == []
        assert await ContextMilestoneRepository(db_session).list_by_mission(mid) == []

    @pytest.mark.asyncio
    async def test_compaction_on_write_keeps_the_written_root(self, manager, db_session):
        mid = _MID("kept")
        max_bytes, _ = _limits()
        await _seed(
            manager,
            mid,
            [
                {"op": "replace", "path": "identity.purpose", "value": "p" * 13_000},
                {"op": "add", "path": "notes", "value": "n" * 2500},
            ],
        )

        version, errors = await manager.apply_updates(
            mid,
            [{"op": "add", "path": "architecture.data_flow", "value": "x" * 5000}],
            agent_id="a.agent",
            task_id=None,
            mission_run_id=None,
            reason="test",
        )

        assert errors == []
        ctx = await _ctx(db_session, mid)
        assert ctx.version == version == 3
        assert ctx.context_data["architecture"]["data_flow"] == "x" * 5000
        assert "notes" not in ctx.context_data
        assert mcd_size_bytes(ctx.context_data) <= max_bytes
        changes = await _changes_at(db_session, ctx.id, 3)
        assert (ChangeType.ARCHIVE, "architecture") not in {
            (c.change_type, c.path) for c in changes
        }
        assert (ChangeType.ARCHIVE, "notes") in {(c.change_type, c.path) for c in changes}


class TestPlan:
    @pytest.mark.asyncio
    async def test_plan_skips_written_roots_and_snapshots_nothing_when_idle(
        self, manager, db_session
    ):
        mid = _MID("skip")
        await manager.create_context(mid, mid, "desc")
        ctx = await _ctx(db_session, mid)
        data = copy.deepcopy(ctx.context_data)
        data["identity"]["purpose"] = "p" * 5000
        before = copy.deepcopy(data)
        unprotected = {
            k
            for k in data
            if k not in get_app_config().missions.compaction.protected_roots
            and k not in {"version", "last_updated", "last_updated_by"}
        }

        result = await MissionContextCompactor(db_session).plan(
            mid, ctx.id, ctx.version, data, 100, written_roots=frozenset(unprotected)
        )

        assert result.changes == []
        assert result.archived_paths == []
        assert data == before
        assert await ContextMilestoneRepository(db_session).list_by_mission(mid) == []

    @pytest.mark.asyncio
    async def test_compaction_snapshots_to_context_milestone(self, manager, db_session):
        mid = _MID("snap")
        await manager.create_context(mid, mid, "desc")
        ctx = await _ctx(db_session, mid)
        data = copy.deepcopy(ctx.context_data)
        data["notes"] = "n" * 2000
        passed_in = copy.deepcopy(data)

        await MissionContextCompactor(db_session).plan(
            mid, ctx.id, ctx.version, data, mcd_size_bytes(data) - 100, written_roots=frozenset()
        )

        milestones = await ContextMilestoneRepository(db_session).list_by_mission(mid)
        assert len(milestones) == 1
        assert milestones[0].created_by == "system:compaction"
        assert milestones[0].context_snapshot == passed_in
        assert milestones[0].version_snapshot == ctx.version
        assert milestones[0].title == f"MCD compaction before v{ctx.version + 1}"

    @pytest.mark.asyncio
    async def test_compaction_archives_oldest_unprotected_root_first(self, manager, db_session):
        mid = _MID("order")
        await _seed(
            manager,
            mid,
            [
                {"op": "add", "path": "zeta", "value": "z" * 2000},
                {"op": "add", "path": "alpha", "value": "a" * 2000},
            ],
        )
        ctx = await _ctx(db_session, mid)
        for path, year in (("zeta", 2000), ("alpha", 2001)):
            await db_session.execute(
                update(ContextChange)
                .where(ContextChange.context_id == ctx.id)
                .where(ContextChange.path == path)
                .values(created_at=datetime(year, 1, 1, tzinfo=timezone.utc))
            )
        data = copy.deepcopy(ctx.context_data)

        result = await MissionContextCompactor(db_session).plan(
            mid, ctx.id, ctx.version, data, mcd_size_bytes(data) - 1000, written_roots=frozenset()
        )

        assert result.archived_paths == ["zeta"]
        assert "zeta" not in data
        assert data["alpha"] == "a" * 2000
        assert result.changes == [
            {
                "change_type": ChangeType.ARCHIVE,
                "path": "zeta",
                "old_value": "z" * 2000,
                "new_value": None,
                "reason": "compaction: archived least recently changed section",
            }
        ]
        assert result.reached_target is True

    @pytest.mark.asyncio
    async def test_compaction_never_touches_protected_roots(self, manager, db_session):
        mid = _MID("protect")
        await manager.create_context(mid, mid, "desc")
        ctx = await _ctx(db_session, mid)
        data = copy.deepcopy(ctx.context_data)
        data["identity"]["purpose"] = "p" * 5000
        data["guardrails"] = ["g" * 500]
        data["custom"] = {"k": "v" * 500}
        protected = get_app_config().missions.compaction.protected_roots
        before = {root: copy.deepcopy(data[root]) for root in protected}

        result = await MissionContextCompactor(db_session).plan(
            mid, ctx.id, ctx.version, data, 100, written_roots=frozenset()
        )

        assert result.reached_target is False
        assert set(result.archived_paths) == {"architecture", "decisions", "custom"}
        assert {root: data[root] for root in protected} == before
        assert {"version", "last_updated", "last_updated_by"} <= set(data)

    @pytest.mark.asyncio
    async def test_compaction_is_deterministic(self, manager, db_session):
        mid = _MID("det")
        await manager.create_context(mid, mid, "desc")
        ctx = await _ctx(db_session, mid)
        doc = copy.deepcopy(ctx.context_data)
        doc["decisions"] = _old_decisions(3, 500)
        doc["current_state"]["recent_milestones"] = [f"m{i}" for i in range(8)]
        doc["notes"] = "n" * 3000
        doc["scratch"] = "s" * 3000
        compactor = MissionContextCompactor(db_session)

        first = await compactor.plan(
            mid, ctx.id, ctx.version, copy.deepcopy(doc), 100, written_roots=frozenset()
        )
        second = await compactor.plan(
            mid, ctx.id, ctx.version, copy.deepcopy(doc), 100, written_roots=frozenset()
        )

        assert first.changes == second.changes
        assert first.archived_paths == second.archived_paths
        assert [c["path"] for c in first.changes] == [
            "decisions",
            "current_state.recent_milestones",
            "architecture",
            "decisions",
            "notes",
            "scratch",
        ]


class TestExplicitCompact:
    @pytest.mark.asyncio
    async def test_compact_below_threshold_is_noop(self, manager, db_session):
        mid = _MID("noop")
        await manager.create_context(mid, mid, "desc")

        assert await manager.compact(mid, mission_run_id=None, reason="test") is None

        ctx = await _ctx(db_session, mid)
        assert ctx.version == 1
        assert await ContextMilestoneRepository(db_session).list_by_mission(mid) == []

    @pytest.mark.asyncio
    async def test_compact_over_threshold_writes_one_version(self, manager, db_session):
        mid = _MID("explicit")
        _, target_bytes = _limits()
        await _seed(
            manager,
            mid,
            [
                {"op": "replace", "path": "identity.purpose", "value": "p" * 13_000},
                {"op": "add", "path": "notes", "value": "n" * 4000},
            ],
        )

        result = await manager.compact(mid, mission_run_id=None, reason="run-end compaction")

        assert result is not None
        assert result.reached_target is True
        assert result.archived_paths == ["architecture", "decisions", "notes"]
        assert result.to_bytes <= target_bytes < result.from_bytes
        ctx = await _ctx(db_session, mid)
        assert ctx.version == 3
        assert "notes" not in ctx.context_data
        assert ctx.context_data["last_updated_by"] == "system:compaction"
        changes = await _changes_at(db_session, ctx.id, 3)
        assert sorted(c.path for c in changes) == ["architecture", "decisions", "notes"]
        assert {c.agent_id for c in changes} == {"system:compaction"}
        assert all(c.reason.startswith("run-end compaction: ") for c in changes)

    @pytest.mark.asyncio
    async def test_compact_with_nothing_archivable_writes_nothing(self, manager, db_session):
        mid = _MID("nothing")
        max_bytes, _ = _limits()
        threshold = max_bytes * get_app_config().missions.pcd_prune_threshold_pct / 100
        await _seed(
            manager,
            mid,
            [
                {"op": "replace", "path": "identity.purpose", "value": "p" * (int(threshold) + 1)},
                {"op": "remove", "path": "architecture"},
                {"op": "remove", "path": "decisions"},
            ],
        )

        assert await manager.compact(mid, mission_run_id=None, reason="run-end compaction") is None

        ctx = await _ctx(db_session, mid)
        assert ctx.version == 2
        assert await ContextMilestoneRepository(db_session).list_by_mission(mid) == []
        assert await _changes_at(db_session, ctx.id, 3) == []
