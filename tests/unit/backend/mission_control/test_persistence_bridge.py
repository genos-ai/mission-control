"""Tests for persistence_bridge.persist_mission_results (Plan 88, 88.0.8).

Persistence failures raise and roll back; only per-artifact creation is
best-effort.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from modules.backend.agents.mission_control.persistence_bridge import persist_mission_results
from modules.backend.schemas.execution_outcome import (
    ExecutionOutcome,
    ExecutionStatus,
    TaskResult,
    TaskStatus,
)

_SERVICE = "modules.backend.agents.mission_control.persistence_bridge.ExecutionPersistenceService"
_BRIDGE = "modules.backend.agents.mission_control.persistence_bridge"


def _outcome() -> ExecutionOutcome:
    return ExecutionOutcome(
        mission_id="m-1",
        status=ExecutionStatus.SUCCESS,
        task_results=[
            TaskResult(
                task_id="t-1", agent_name="system.summarization.agent", status=TaskStatus.SUCCESS
            ),
        ],
    )


@pytest.mark.asyncio
async def test_raises_and_rolls_back_on_value_error():
    db_session = AsyncMock()
    with patch(f"{_SERVICE}.save_execution", AsyncMock(side_effect=ValueError("bad row"))):
        with pytest.raises(ValueError, match="bad row"):
            await persist_mission_results(
                _outcome(),
                session_id="s-1",
                db_session=db_session,
            )

    db_session.rollback.assert_awaited_once()
    db_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_artifact_failure_does_not_raise():
    db_session = AsyncMock()
    with (
        patch(f"{_SERVICE}.save_execution", AsyncMock(return_value=SimpleNamespace(id="rec-1"))),
        patch(
            f"{_SERVICE}.save_task_execution",
            AsyncMock(return_value=SimpleNamespace(id="te-1")),
        ),
        patch(
            "modules.backend.services.mission_plan.MissionPlanService.get_domain_tags_map",
            AsyncMock(return_value={}),
        ),
        patch(
            f"{_BRIDGE}._maybe_create_artifact",
            AsyncMock(side_effect=RuntimeError("artifact boom")),
        ) as maybe_create,
    ):
        record_id = await persist_mission_results(
            _outcome(),
            session_id="s-1",
            mission_id="m-1",
            db_session=db_session,
        )

    assert record_id == "rec-1"
    maybe_create.assert_awaited_once()
    db_session.commit.assert_awaited_once()
    db_session.rollback.assert_not_awaited()
