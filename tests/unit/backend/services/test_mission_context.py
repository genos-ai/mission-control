"""Tests for MissionContextManager.

Per P12: tests run against the live platform. Uses real db_session fixture
with transaction rollback for isolation.
"""

from uuid import UUID, uuid5

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ConflictError
from modules.backend.models.mission_context import ChangeType, ContextChange
from modules.backend.repositories.mission_context import (
    ContextChangeRepository,
    MissionContextRepository,
)
from modules.backend.services import mission_context as mission_context_module
from modules.backend.services.mcd_pruning import mcd_size_bytes
from modules.backend.services.mission_context import (
    _SENTINEL,
    MissionContextManager,
    _cache,
    _delete_nested,
    _get_nested,
    _set_nested,
)
from tests.conftest import TEST_USER_ID

_TEST_NS = UUID("00000000-0000-0000-0000-000000000000")


def _MID(tag):
    return str(uuid5(_TEST_NS, f"mission:ctx-{tag}"))


# Tags used in this file that need Mission parent rows.
# "nonexistent" and "nonexistent-mission" are deliberately omitted
# because those tests verify not-found behaviour.
_MISSION_TAGS = [
    "1",
    "2",
    "get",
    "cache",
    "ver",
    "size",
    "add",
    "rep",
    "rm",
    "restricted",
    "guard",
    "nopath",
    "noop",
    "unk",
    "inv",
    "hist",
    "attr",
    "runid",
    "utf8",
    "conflict",
    "reason",
    "between",
    "legacy",
]


@pytest.fixture(autouse=True)
async def _ensure_parent_rows(test_user, db_session: AsyncSession):
    """Create Mission rows that MissionContext.mission_id FKs to."""
    from modules.backend.models.mission import Mission
    from modules.backend.models.mission_plan import GateMode, MissionPlan

    for tag in _MISSION_TAGS:
        db_session.add(
            Mission(
                id=_MID(tag),
                name=f"ctx-{tag}",
                description="test",
                owner_id=TEST_USER_ID,
            )
        )
    await db_session.flush()
    for tag in _MISSION_TAGS:
        db_session.add(MissionPlan(mission_id=_MID(tag), gate_mode=GateMode.MANUAL))
    await db_session.flush()


@pytest.fixture
def manager(db_session: AsyncSession) -> MissionContextManager:
    return MissionContextManager(db_session)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear MCD cache between tests."""
    _cache.clear()
    yield
    _cache.clear()


class TestNestedHelpers:
    def test_get_nested_simple(self):
        data = {"a": {"b": {"c": 42}}}
        assert _get_nested(data, "a.b.c") == 42

    def test_get_nested_missing(self):
        data = {"a": {"b": 1}}
        assert _get_nested(data, "a.c") is _SENTINEL

    def test_set_nested_creates_intermediates(self):
        data = {}
        _set_nested(data, "a.b.c", "hello")
        assert data == {"a": {"b": {"c": "hello"}}}

    def test_set_nested_overwrites(self):
        data = {"a": {"b": "old"}}
        _set_nested(data, "a.b", "new")
        assert data["a"]["b"] == "new"

    def test_delete_nested(self):
        data = {"a": {"b": "val", "c": "keep"}}
        old = _delete_nested(data, "a.b")
        assert old == "val"
        assert "b" not in data["a"]
        assert data["a"]["c"] == "keep"

    def test_delete_nested_missing(self):
        data = {"a": 1}
        assert _delete_nested(data, "x.y") is None


class TestCreateContext:
    @pytest.mark.asyncio
    async def test_creates_seed_mcd(self, manager):
        ctx = await manager.create_context(
            mission_id=_MID("1"),
            mission_name="test-mission",
            description="A test mission",
        )
        assert ctx.mission_id == _MID("1")
        assert ctx.version == 1
        assert ctx.size_characters > 0
        assert ctx.context_data["identity"]["name"] == "test-mission"
        assert ctx.context_data["identity"]["purpose"] == "A test mission"

    @pytest.mark.asyncio
    async def test_seed_has_expected_sections(self, manager):
        ctx = await manager.create_context(
            mission_id=_MID("2"),
            mission_name="sections-test",
            description="Test sections",
        )
        data = ctx.context_data
        assert "identity" in data
        assert "architecture" in data
        assert "decisions" in data
        assert "current_state" in data
        assert "guardrails" in data
        assert data["version"] == 1


class TestGetContext:
    @pytest.mark.asyncio
    async def test_get_existing(self, manager):
        await manager.create_context(_MID("get"), "get-test", "desc")
        data = await manager.get_context(_MID("get"))
        assert data["identity"]["name"] == "get-test"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_empty(self, manager):
        data = await manager.get_context(_MID("nonexistent"))
        assert data == {}

    @pytest.mark.asyncio
    async def test_cache_hit(self, manager):
        await manager.create_context(_MID("cache"), "cache-test", "desc")
        await manager.get_context(_MID("cache"))
        assert _MID("cache") in _cache
        data = await manager.get_context(_MID("cache"))
        assert data["identity"]["name"] == "cache-test"


class TestGetContextWithVersion:
    @pytest.mark.asyncio
    async def test_returns_data_and_version(self, manager):
        await manager.create_context(_MID("ver"), "ver-test", "desc")
        data, version = await manager.get_context_with_version(_MID("ver"))
        assert version == 1
        assert data["identity"]["name"] == "ver-test"

    @pytest.mark.asyncio
    async def test_nonexistent_returns_empty(self, manager):
        data, version = await manager.get_context_with_version(_MID("nonexistent"))
        assert data == {}
        assert version == 0


class TestGetContextSize:
    @pytest.mark.asyncio
    async def test_returns_size_metrics(self, manager):
        await manager.create_context(_MID("size"), "size-test", "desc")
        size = await manager.get_context_size(_MID("size"))
        assert size["size_characters"] > 0
        assert size["size_tokens"] > 0
        assert size["version"] == 1
        assert 0 < size["pct_of_max"] < 100
        # The percentage is of this cap, which the UI shows next to the size.
        assert size["max_characters"] > size["size_characters"]
        assert size["pct_of_max"] == pytest.approx(
            size["size_characters"] / size["max_characters"] * 100
        )

    @pytest.mark.asyncio
    async def test_nonexistent_returns_zeros(self, manager):
        size = await manager.get_context_size(_MID("nonexistent"))
        assert size["size_characters"] == 0
        assert size["version"] == 0
        assert size["max_characters"] > 0


class TestApplyUpdates:
    @pytest.mark.asyncio
    async def test_add_operation(self, manager):
        await manager.create_context(_MID("add"), "add-test", "desc")
        new_ver, errors = await manager.apply_updates(
            _MID("add"),
            [
                {
                    "op": "add",
                    "path": "identity.tech_stack",
                    "value": ["python", "fastapi"],
                    "reason": "Set tech stack",
                }
            ],
            agent_id=None,
            task_id=None,
            mission_run_id=None,
            reason="test",
        )
        assert new_ver == 2
        assert errors == []
        data = await manager.get_context(_MID("add"))
        assert data["identity"]["tech_stack"] == ["python", "fastapi"]

    @pytest.mark.asyncio
    async def test_replace_operation(self, manager):
        await manager.create_context(_MID("rep"), "rep-test", "desc")
        await manager.apply_updates(
            _MID("rep"),
            [{"op": "add", "path": "architecture.data_flow", "value": "initial", "reason": "init"}],
            agent_id=None,
            task_id=None,
            mission_run_id=None,
            reason="test",
        )
        new_ver, errors = await manager.apply_updates(
            _MID("rep"),
            [
                {
                    "op": "replace",
                    "path": "architecture.data_flow",
                    "value": "updated",
                    "reason": "update flow",
                }
            ],
            agent_id=None,
            task_id=None,
            mission_run_id=None,
            reason="test",
        )
        assert new_ver == 3
        assert errors == []

    @pytest.mark.asyncio
    async def test_remove_operation(self, manager):
        await manager.create_context(_MID("rm"), "rm-test", "desc")
        await manager.apply_updates(
            _MID("rm"),
            [
                {
                    "op": "add",
                    "path": "architecture.components.auth",
                    "value": {"type": "jwt"},
                    "reason": "add auth",
                }
            ],
            agent_id=None,
            task_id=None,
            mission_run_id=None,
            reason="test",
        )
        new_ver, errors = await manager.apply_updates(
            _MID("rm"),
            [{"op": "remove", "path": "architecture.components.auth", "reason": "remove auth"}],
            agent_id=None,
            task_id=None,
            mission_run_id=None,
            reason="test",
        )
        assert new_ver == 3
        assert errors == []
        data = await manager.get_context(_MID("rm"))
        assert "auth" not in data["architecture"]["components"]

    @pytest.mark.asyncio
    async def test_restricted_path_rejected(self, manager):
        await manager.create_context(_MID("restricted"), "test", "desc")
        new_ver, errors = await manager.apply_updates(
            _MID("restricted"),
            [{"op": "replace", "path": "version", "value": 999, "reason": "hack version"}],
            agent_id=None,
            task_id=None,
            mission_run_id=None,
            reason="test",
        )
        assert len(errors) == 1
        assert "Restricted path" in errors[0]

    @pytest.mark.asyncio
    async def test_agent_cannot_remove_guardrails(self, manager):
        await manager.create_context(_MID("guard"), "test", "desc")
        await manager.apply_updates(
            _MID("guard"),
            [
                {
                    "op": "replace",
                    "path": "guardrails",
                    "value": {"no_delete": "Never delete production data"},
                    "reason": "safety",
                }
            ],
            agent_id=None,
            task_id=None,
            mission_run_id=None,
            reason="test",
        )
        new_ver, errors = await manager.apply_updates(
            _MID("guard"),
            [{"op": "remove", "path": "guardrails.no_delete", "reason": "trying to remove"}],
            agent_id="some.agent",
            task_id=None,
            mission_run_id=None,
            reason="test",
        )
        assert len(errors) == 1
        assert "cannot remove guardrails" in errors[0]

    @pytest.mark.asyncio
    async def test_replace_nonexistent_path_errors(self, manager):
        await manager.create_context(_MID("nopath"), "test", "desc")
        new_ver, errors = await manager.apply_updates(
            _MID("nopath"),
            [{"op": "replace", "path": "nonexistent.deep.path", "value": "val", "reason": "test"}],
            agent_id=None,
            task_id=None,
            mission_run_id=None,
            reason="test",
        )
        assert len(errors) == 1
        assert "Path not found" in errors[0]

    @pytest.mark.asyncio
    async def test_noop_replace_errors(self, manager):
        await manager.create_context(_MID("noop"), "test", "desc")
        new_ver, errors = await manager.apply_updates(
            _MID("noop"),
            [{"op": "replace", "path": "identity.name", "value": "test", "reason": "no change"}],
            agent_id=None,
            task_id=None,
            mission_run_id=None,
            reason="test",
        )
        assert len(errors) == 1
        assert "No-op" in errors[0]

    @pytest.mark.asyncio
    async def test_unknown_operation(self, manager):
        await manager.create_context(_MID("unk"), "test", "desc")
        new_ver, errors = await manager.apply_updates(
            _MID("unk"),
            [{"op": "patch", "path": "identity.name", "value": "x", "reason": "bad op"}],
            agent_id=None,
            task_id=None,
            mission_run_id=None,
            reason="test",
        )
        assert len(errors) == 1
        assert "Unknown operation" in errors[0]

    @pytest.mark.asyncio
    async def test_nonexistent_mission_errors(self, manager):
        new_ver, errors = await manager.apply_updates(
            _MID("nonexistent-mission"),
            [{"op": "add", "path": "x", "value": 1, "reason": "test"}],
            agent_id=None,
            task_id=None,
            mission_run_id=None,
            reason="test",
        )
        assert new_ver == 0
        assert "not found" in errors[0]

    @pytest.mark.asyncio
    async def test_invalidates_cache(self, manager):
        await manager.create_context(_MID("inv"), "test", "desc")
        await manager.get_context(_MID("inv"))
        assert _MID("inv") in _cache
        await manager.apply_updates(
            _MID("inv"),
            [{"op": "add", "path": "identity.tech_stack", "value": ["go"], "reason": "test"}],
            agent_id=None,
            task_id=None,
            mission_run_id=None,
            reason="test",
        )
        assert _MID("inv") not in _cache


class TestGetHistory:
    @pytest.mark.asyncio
    async def test_returns_changes(self, manager):
        await manager.create_context(_MID("hist"), "test", "desc")
        await manager.apply_updates(
            _MID("hist"),
            [
                {
                    "op": "add",
                    "path": "identity.tech_stack",
                    "value": ["python"],
                    "reason": "added stack",
                }
            ],
            agent_id="test.agent",
            task_id=None,
            mission_run_id=None,
            reason="test",
        )
        changes = await manager.get_history(_MID("hist"))
        assert len(changes) == 1
        assert changes[0].change_type == ChangeType.ADD
        assert changes[0].agent_id == "test.agent"
        assert changes[0].path == "identity.tech_stack"

    @pytest.mark.asyncio
    async def test_empty_history_for_nonexistent(self, manager):
        changes = await manager.get_history(_MID("nonexistent"))
        assert changes == []


class TestMCDCreationViaMissionService:
    """Verify that creating a mission also creates a seed MCD."""

    @pytest.mark.asyncio
    async def test_mission_creation_seeds_mcd(self, db_session):
        from modules.backend.services.mission import MissionService

        svc = MissionService(db_session)
        mission = await svc.create_mission(
            gate_mode="manual",
            name="mcd-seeded",
            description="Test MCD seeding",
            owner_id=TEST_USER_ID,
        )

        mgr = MissionContextManager(db_session)
        data = await mgr.get_context(mission.id)
        assert data != {}
        assert data["identity"]["name"] == "mcd-seeded"
        assert data["identity"]["purpose"] == "Test MCD seeding"


def _add(path: str, value: object, reason: str | None = "test") -> dict:
    update = {"op": "add", "path": path, "value": value}
    if reason is not None:
        update["reason"] = reason
    return update


async def _changes(db_session: AsyncSession, mission_id: str) -> list[ContextChange]:
    ctx = await MissionContextRepository(db_session).get_by_mission_id(mission_id)
    result = await db_session.execute(
        select(ContextChange).where(ContextChange.context_id == ctx.id)
    )
    return list(result.scalars().all())


async def _make_run(db_session: AsyncSession, mission_id: str) -> str:
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


class TestAttributionAndWatermarks:
    @pytest.mark.asyncio
    async def test_apply_updates_sets_mission_id_on_every_change(self, manager, db_session):
        mid = _MID("attr")
        await manager.create_context(mid, "attr", "desc")
        await manager.apply_updates(
            mid,
            [_add("identity.tech_stack", ["go"]), _add("architecture.data_flow", "x")],
            agent_id="workflow",
            task_id=None,
            mission_run_id=None,
            reason="batch",
        )
        changes = await _changes(db_session, mid)
        assert len(changes) == 2
        assert all(c.mission_id == mid for c in changes)
        roots = await ContextChangeRepository(db_session).latest_change_at_by_root(
            changes[0].context_id
        )
        assert set(roots) == {"identity", "architecture"}

    @pytest.mark.asyncio
    async def test_apply_updates_records_mission_run_id(self, manager, db_session):
        mid = _MID("runid")
        await manager.create_context(mid, "runid", "desc")
        run_id = await _make_run(db_session, mid)
        await manager.apply_updates(
            mid,
            [_add("identity.tech_stack", ["go"])],
            agent_id="a.agent",
            task_id=None,
            mission_run_id=run_id,
            reason="batch",
        )
        changes = await _changes(db_session, mid)
        assert [c.mission_run_id for c in changes] == [run_id]

    @pytest.mark.asyncio
    async def test_apply_updates_size_measured_in_utf8_bytes(
        self, manager, db_session, monkeypatch
    ):
        assert mcd_size_bytes("\u20ac") - mcd_size_bytes("") == 3

        mid = _MID("utf8")
        await manager.create_context(mid, "utf8", "desc")
        data, _ = await manager.get_context_with_version(mid)
        # 1000 three-byte characters: under the caps in characters, over them in bytes.
        # The update alone exceeds the target, so the write is rejected (88.3.3).
        cap = mcd_size_bytes(data) + 2000
        monkeypatch.setattr(mission_context_module, "_get_max_size", lambda: cap)
        monkeypatch.setattr(mission_context_module, "_get_target_size", lambda: 1500)
        version, errors = await manager.apply_updates(
            mid,
            [_add("architecture.data_flow", "\u20ac" * 1000)],
            agent_id=None,
            task_id=None,
            mission_run_id=None,
            reason="test",
        )
        assert version == 1
        assert errors == ["Update at architecture.data_flow exceeds pcd_target_size_bytes"]
        assert await _changes(db_session, mid) == []

    @pytest.mark.asyncio
    async def test_apply_updates_no_orphan_changes_on_conflict(
        self, manager, db_session, monkeypatch
    ):
        mid = _MID("conflict")
        await manager.create_context(mid, "conflict", "desc")

        async def _no_rows(*args, **kwargs) -> int:
            return 0

        monkeypatch.setattr(MissionContextRepository, "update_context", _no_rows)
        with pytest.raises(ConflictError):
            await manager.apply_updates(
                mid,
                [_add("identity.tech_stack", ["go"])],
                agent_id=None,
                task_id=None,
                mission_run_id=None,
                reason="test",
            )
        count = (
            await db_session.execute(
                select(func.count())
                .select_from(ContextChange)
                .where(ContextChange.mission_id == mid)
            )
        ).scalar_one()
        assert count == 0
        assert not [o for o in db_session.new if isinstance(o, ContextChange)]

    @pytest.mark.asyncio
    async def test_apply_updates_batch_reason_used_when_update_has_none(self, manager, db_session):
        mid = _MID("reason")
        await manager.create_context(mid, "reason", "desc")
        await manager.apply_updates(
            mid,
            [_add("identity.tech_stack", ["go"], reason=None), _add("architecture.data_flow", "x")],
            agent_id=None,
            task_id=None,
            mission_run_id=None,
            reason="batch reason",
        )
        reasons = {c.path: c.reason for c in await _changes(db_session, mid)}
        assert reasons == {"identity.tech_stack": "batch reason", "architecture.data_flow": "test"}

    @pytest.mark.asyncio
    async def test_get_changes_between_bounds_exclusive_inclusive(self, manager):
        mid = _MID("between")
        await manager.create_context(mid, "between", "desc")
        for i in range(4):
            await manager.apply_updates(
                mid,
                [_add(f"architecture.components.c{i}", i)],
                agent_id=None,
                task_id=None,
                mission_run_id=None,
                reason="test",
            )
        changes = await manager.get_changes_between(mid, 2, 4, limit=10)
        assert [c.version for c in changes] == [4, 3]
        assert await manager.count_changes_between(mid, 2, 4) == 2
        assert [c.version for c in await manager.get_changes_between(mid, 1, 5, limit=1)] == [5]

    @pytest.mark.asyncio
    async def test_get_changes_between_includes_legacy_null_mission_id_rows(
        self, manager, db_session
    ):
        mid = _MID("legacy")
        ctx = await manager.create_context(mid, "legacy", "desc")
        db_session.add(
            ContextChange(
                context_id=ctx.id,
                version=2,
                change_type=ChangeType.ADD,
                path="identity.tech_stack",
                new_value=["go"],
                mission_id=None,
                reason="legacy",
            )
        )
        await db_session.flush()
        changes = await manager.get_changes_between(mid, 1, 2, limit=10)
        assert [c.mission_id for c in changes] == [None]
        assert await manager.count_changes_between(mid, 1, 2) == 1

    @pytest.mark.asyncio
    async def test_changes_between_without_mcd(self, manager):
        assert await manager.get_changes_between(_MID("nonexistent"), 0, 5, limit=10) == []
        assert await manager.count_changes_between(_MID("nonexistent"), 0, 5) == 0
