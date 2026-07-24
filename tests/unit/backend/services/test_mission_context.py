"""Tests for MissionContextManager.

Per P12: tests run against the live platform. Uses real db_session fixture
with transaction rollback for isolation.
"""

from uuid import UUID, uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.models.mission_context import ChangeType
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
]


@pytest.fixture(autouse=True)
async def _ensure_parent_rows(test_user, db_session: AsyncSession):
    """Create Mission rows that MissionContext.mission_id FKs to."""
    from modules.backend.models.mission import Mission

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

    @pytest.mark.asyncio
    async def test_nonexistent_returns_zeros(self, manager):
        size = await manager.get_context_size(_MID("nonexistent"))
        assert size["size_characters"] == 0
        assert size["version"] == 0


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
        )
        new_ver, errors = await manager.apply_updates(
            _MID("rm"),
            [{"op": "remove", "path": "architecture.components.auth", "reason": "remove auth"}],
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
        )
        new_ver, errors = await manager.apply_updates(
            _MID("guard"),
            [{"op": "remove", "path": "guardrails.no_delete", "reason": "trying to remove"}],
            agent_id="some.agent",
        )
        assert len(errors) == 1
        assert "cannot remove guardrails" in errors[0]

    @pytest.mark.asyncio
    async def test_replace_nonexistent_path_errors(self, manager):
        await manager.create_context(_MID("nopath"), "test", "desc")
        new_ver, errors = await manager.apply_updates(
            _MID("nopath"),
            [{"op": "replace", "path": "nonexistent.deep.path", "value": "val", "reason": "test"}],
        )
        assert len(errors) == 1
        assert "Path not found" in errors[0]

    @pytest.mark.asyncio
    async def test_noop_replace_errors(self, manager):
        await manager.create_context(_MID("noop"), "test", "desc")
        new_ver, errors = await manager.apply_updates(
            _MID("noop"),
            [{"op": "replace", "path": "identity.name", "value": "test", "reason": "no change"}],
        )
        assert len(errors) == 1
        assert "No-op" in errors[0]

    @pytest.mark.asyncio
    async def test_unknown_operation(self, manager):
        await manager.create_context(_MID("unk"), "test", "desc")
        new_ver, errors = await manager.apply_updates(
            _MID("unk"),
            [{"op": "patch", "path": "identity.name", "value": "x", "reason": "bad op"}],
        )
        assert len(errors) == 1
        assert "Unknown operation" in errors[0]

    @pytest.mark.asyncio
    async def test_nonexistent_mission_errors(self, manager):
        new_ver, errors = await manager.apply_updates(
            _MID("nonexistent-mission"),
            [{"op": "add", "path": "x", "value": 1, "reason": "test"}],
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
            name="mcd-seeded",
            description="Test MCD seeding",
            owner_id=TEST_USER_ID,
        )

        mgr = MissionContextManager(db_session)
        data = await mgr.get_context(mission.id)
        assert data != {}
        assert data["identity"]["name"] == "mcd-seeded"
        assert data["identity"]["purpose"] == "Test MCD seeding"
