"""Tests for MissionContextManager.

Per P12: tests run against the live platform. Uses real db_session fixture
with transaction rollback for isolation.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.models.mission_context import ChangeType
from modules.backend.services.mission_context import (
    MissionContextManager,
    _cache,
    _delete_nested,
    _get_nested,
    _MCD_MAX_SIZE,
    _SENTINEL,
    _set_nested,
)


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
            mission_id="mission-1",
            mission_name="test-mission",
            description="A test mission",
        )
        assert ctx.mission_id == "mission-1"
        assert ctx.version == 1
        assert ctx.size_characters > 0
        assert ctx.context_data["identity"]["name"] == "test-mission"
        assert ctx.context_data["identity"]["purpose"] == "A test mission"

    @pytest.mark.asyncio
    async def test_seed_has_expected_sections(self, manager):
        ctx = await manager.create_context(
            mission_id="mission-2",
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
        await manager.create_context("mission-get", "get-test", "desc")
        data = await manager.get_context("mission-get")
        assert data["identity"]["name"] == "get-test"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_empty(self, manager):
        data = await manager.get_context("nonexistent")
        assert data == {}

    @pytest.mark.asyncio
    async def test_cache_hit(self, manager):
        await manager.create_context("mission-cache", "cache-test", "desc")
        await manager.get_context("mission-cache")
        assert "mission-cache" in _cache
        data = await manager.get_context("mission-cache")
        assert data["identity"]["name"] == "cache-test"


class TestGetContextWithVersion:
    @pytest.mark.asyncio
    async def test_returns_data_and_version(self, manager):
        await manager.create_context("mission-ver", "ver-test", "desc")
        data, version = await manager.get_context_with_version("mission-ver")
        assert version == 1
        assert data["identity"]["name"] == "ver-test"

    @pytest.mark.asyncio
    async def test_nonexistent_returns_empty(self, manager):
        data, version = await manager.get_context_with_version("nonexistent")
        assert data == {}
        assert version == 0


class TestGetContextSize:
    @pytest.mark.asyncio
    async def test_returns_size_metrics(self, manager):
        await manager.create_context("mission-size", "size-test", "desc")
        size = await manager.get_context_size("mission-size")
        assert size["size_characters"] > 0
        assert size["size_tokens"] > 0
        assert size["version"] == 1
        assert 0 < size["pct_of_max"] < 100

    @pytest.mark.asyncio
    async def test_nonexistent_returns_zeros(self, manager):
        size = await manager.get_context_size("nonexistent")
        assert size["size_characters"] == 0
        assert size["version"] == 0


class TestApplyUpdates:
    @pytest.mark.asyncio
    async def test_add_operation(self, manager):
        await manager.create_context("mission-add", "add-test", "desc")
        new_ver, errors = await manager.apply_updates(
            "mission-add",
            [{"op": "add", "path": "identity.tech_stack", "value": ["python", "fastapi"],
              "reason": "Set tech stack"}],
        )
        assert new_ver == 2
        assert errors == []
        data = await manager.get_context("mission-add")
        assert data["identity"]["tech_stack"] == ["python", "fastapi"]

    @pytest.mark.asyncio
    async def test_replace_operation(self, manager):
        await manager.create_context("mission-rep", "rep-test", "desc")
        await manager.apply_updates(
            "mission-rep",
            [{"op": "add", "path": "architecture.data_flow", "value": "initial",
              "reason": "init"}],
        )
        new_ver, errors = await manager.apply_updates(
            "mission-rep",
            [{"op": "replace", "path": "architecture.data_flow", "value": "updated",
              "reason": "update flow"}],
        )
        assert new_ver == 3
        assert errors == []

    @pytest.mark.asyncio
    async def test_remove_operation(self, manager):
        await manager.create_context("mission-rm", "rm-test", "desc")
        await manager.apply_updates(
            "mission-rm",
            [{"op": "add", "path": "architecture.components.auth",
              "value": {"type": "jwt"}, "reason": "add auth"}],
        )
        new_ver, errors = await manager.apply_updates(
            "mission-rm",
            [{"op": "remove", "path": "architecture.components.auth",
              "reason": "remove auth"}],
        )
        assert new_ver == 3
        assert errors == []
        data = await manager.get_context("mission-rm")
        assert "auth" not in data["architecture"]["components"]

    @pytest.mark.asyncio
    async def test_restricted_path_rejected(self, manager):
        await manager.create_context("mission-restricted", "test", "desc")
        new_ver, errors = await manager.apply_updates(
            "mission-restricted",
            [{"op": "replace", "path": "version", "value": 999,
              "reason": "hack version"}],
        )
        assert len(errors) == 1
        assert "Restricted path" in errors[0]

    @pytest.mark.asyncio
    async def test_agent_cannot_remove_guardrails(self, manager):
        await manager.create_context("mission-guard", "test", "desc")
        await manager.apply_updates(
            "mission-guard",
            [{"op": "replace", "path": "guardrails",
              "value": {"no_delete": "Never delete production data"}, "reason": "safety"}],
        )
        new_ver, errors = await manager.apply_updates(
            "mission-guard",
            [{"op": "remove", "path": "guardrails.no_delete",
              "reason": "trying to remove"}],
            agent_id="some.agent",
        )
        assert len(errors) == 1
        assert "cannot remove guardrails" in errors[0]

    @pytest.mark.asyncio
    async def test_replace_nonexistent_path_errors(self, manager):
        await manager.create_context("mission-nopath", "test", "desc")
        new_ver, errors = await manager.apply_updates(
            "mission-nopath",
            [{"op": "replace", "path": "nonexistent.deep.path",
              "value": "val", "reason": "test"}],
        )
        assert len(errors) == 1
        assert "Path not found" in errors[0]

    @pytest.mark.asyncio
    async def test_noop_replace_errors(self, manager):
        await manager.create_context("mission-noop", "test", "desc")
        new_ver, errors = await manager.apply_updates(
            "mission-noop",
            [{"op": "replace", "path": "identity.name", "value": "test",
              "reason": "no change"}],
        )
        assert len(errors) == 1
        assert "No-op" in errors[0]

    @pytest.mark.asyncio
    async def test_unknown_operation(self, manager):
        await manager.create_context("mission-unk", "test", "desc")
        new_ver, errors = await manager.apply_updates(
            "mission-unk",
            [{"op": "patch", "path": "identity.name", "value": "x",
              "reason": "bad op"}],
        )
        assert len(errors) == 1
        assert "Unknown operation" in errors[0]

    @pytest.mark.asyncio
    async def test_nonexistent_mission_errors(self, manager):
        new_ver, errors = await manager.apply_updates(
            "nonexistent-mission",
            [{"op": "add", "path": "x", "value": 1, "reason": "test"}],
        )
        assert new_ver == 0
        assert "not found" in errors[0]

    @pytest.mark.asyncio
    async def test_invalidates_cache(self, manager):
        await manager.create_context("mission-inv", "test", "desc")
        await manager.get_context("mission-inv")
        assert "mission-inv" in _cache
        await manager.apply_updates(
            "mission-inv",
            [{"op": "add", "path": "identity.tech_stack", "value": ["go"],
              "reason": "test"}],
        )
        assert "mission-inv" not in _cache


class TestGetHistory:
    @pytest.mark.asyncio
    async def test_returns_changes(self, manager):
        await manager.create_context("mission-hist", "test", "desc")
        await manager.apply_updates(
            "mission-hist",
            [{"op": "add", "path": "identity.tech_stack", "value": ["python"],
              "reason": "added stack"}],
            agent_id="test.agent",
        )
        changes = await manager.get_history("mission-hist")
        assert len(changes) == 1
        assert changes[0].change_type == ChangeType.ADD
        assert changes[0].agent_id == "test.agent"
        assert changes[0].path == "identity.tech_stack"

    @pytest.mark.asyncio
    async def test_empty_history_for_nonexistent(self, manager):
        changes = await manager.get_history("nonexistent")
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
            owner_id="user:test",
        )

        mgr = MissionContextManager(db_session)
        data = await mgr.get_context(mission.id)
        assert data != {}
        assert data["identity"]["name"] == "mcd-seeded"
        assert data["identity"]["purpose"] == "Test MCD seeding"
