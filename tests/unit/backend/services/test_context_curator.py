"""Tests for ContextCurator.

Per P12: tests run against the live platform. Uses real db_session fixture
with transaction rollback for isolation.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.models.mission import Mission
from modules.backend.services.context_curator import ContextCurator
from modules.backend.services.mission_context import (
    MissionContextManager,
    _cache,
)
from uuid import uuid5, UUID
from tests.conftest import TEST_USER_ID

_NS = UUID("00000000-0000-0000-0000-000000000000")
_MID = lambda tag: str(uuid5(_NS, f"mission:curator-{tag}"))
_MISSION_REF = str(uuid5(_NS, "mission:ref"))
_NIL_UUID = "00000000-0000-0000-0000-000000000000"

# Mission slugs that need parent rows (exclude "nonexistent-project" — tests not-found path).
_MISSION_SLUGS = [
    _MID("proj-curator"), _MID("proj-errors"), _MID("proj-restricted"), _MID("proj-guard"), _MID("proj-audit"),
]


@pytest.fixture
def manager(db_session: AsyncSession) -> MissionContextManager:
    return MissionContextManager(db_session)


@pytest.fixture
def curator(manager: MissionContextManager) -> ContextCurator:
    return ContextCurator(manager)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear PCD cache between tests."""
    _cache.clear()
    yield
    _cache.clear()


@pytest.fixture(autouse=True)
async def _ensure_parent_rows(test_user, db_session: AsyncSession):
    """Create Mission rows that MissionContext.mission_id FKs to."""
    for mid in _MISSION_SLUGS:
        db_session.add(
            Mission(id=mid, name=mid, description="test", owner_id=TEST_USER_ID)
        )
    await db_session.flush()


class TestApplyTaskUpdates:
    @pytest.mark.asyncio
    async def test_empty_updates_returns_early(self, curator):
        """Empty context_updates list returns (0, []) without touching DB."""
        version, errors = await curator.apply_task_updates(
            "any-project", [],
        )
        assert version == 0
        assert errors == []

    @pytest.mark.asyncio
    async def test_applies_updates_to_pcd(self, curator, manager):
        """Valid updates are delegated to MissionContextManager."""
        await manager.create_context(_MID("proj-curator"), "curator-test", "desc")

        version, errors = await curator.apply_task_updates(
            _MID("proj-curator"),
            [{"op": "add", "path": "identity.tech_stack",
              "value": ["python"], "reason": "agent discovered stack"}],
            agent_id="code.analyzer",
            mission_id_ref=_MID("proj-curator"),
            task_id="task-1",
        )
        assert version == 2
        assert errors == []

        # Verify the PCD was updated
        data = await manager.get_context(_MID("proj-curator"))
        assert data["identity"]["tech_stack"] == ["python"]

    @pytest.mark.asyncio
    async def test_invalid_updates_return_errors(self, curator, manager):
        """Invalid operations produce errors but don't raise."""
        await manager.create_context(_MID("proj-errors"), "err-test", "desc")

        version, errors = await curator.apply_task_updates(
            _MID("proj-errors"),
            [{"op": "replace", "path": "nonexistent.deep.path",
              "value": "val", "reason": "bad path"}],
            agent_id="some.agent",
        )
        assert len(errors) == 1
        assert "Path not found" in errors[0]

    @pytest.mark.asyncio
    async def test_restricted_path_rejected(self, curator, manager):
        """Restricted paths are rejected via the manager."""
        await manager.create_context(_MID("proj-restricted"), "test", "desc")

        version, errors = await curator.apply_task_updates(
            _MID("proj-restricted"),
            [{"op": "replace", "path": "version", "value": 999,
              "reason": "hack"}],
            agent_id="bad.agent",
        )
        assert len(errors) == 1
        assert "Restricted path" in errors[0]

    @pytest.mark.asyncio
    async def test_agent_guardrail_protection(self, curator, manager):
        """Agents cannot remove guardrails via the curator."""
        await manager.create_context(_MID("proj-guard"), "test", "desc")
        # Replace guardrails with a dict for path-based access
        await manager.apply_updates(
            _MID("proj-guard"),
            [{"op": "replace", "path": "guardrails",
              "value": {"rule": "Never skip tests"}, "reason": "safety"}],
        )

        version, errors = await curator.apply_task_updates(
            _MID("proj-guard"),
            [{"op": "remove", "path": "guardrails.rule",
              "reason": "removing rule"}],
            agent_id="some.agent",
        )
        assert len(errors) == 1
        assert "cannot remove guardrails" in errors[0]

    @pytest.mark.asyncio
    async def test_nonexistent_project_returns_error(self, curator):
        """Updates to a nonexistent project return error."""
        version, errors = await curator.apply_task_updates(
            _NIL_UUID,
            [{"op": "add", "path": "x", "value": 1, "reason": "test"}],
        )
        assert version == 0
        assert "not found" in errors[0]

    @pytest.mark.asyncio
    async def test_change_audit_trail(self, curator, manager):
        """Changes made via curator appear in the audit trail."""
        await manager.create_context(_MID("proj-audit"), "audit-test", "desc")

        await curator.apply_task_updates(
            _MID("proj-audit"),
            [{"op": "add", "path": "architecture.components.api",
              "value": {"type": "fastapi"}, "reason": "discovered API"}],
            agent_id="code.analyzer",
            mission_id_ref=_MID("proj-audit"),
            task_id="task-1",
        )

        changes = await manager.get_history(_MID("proj-audit"))
        assert len(changes) == 1
        assert changes[0].agent_id == "code.analyzer"
        assert changes[0].path == "architecture.components.api"
        assert changes[0].reason == "discovered API"
