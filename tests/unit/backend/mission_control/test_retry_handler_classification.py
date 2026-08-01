"""
Unit tests for retry_handler's provider-error reclassification (Plan 84 Phase 4.3).

execute_task can raise a raw, unclassified SDK exception (e.g. from
Anthropic/OpenAI/Foundry models running through PydanticAI) instead of
one of our typed ProviderError subclasses (which only Copilot currently
raises directly). The generic except Exception branch must classify
these via classify_provider_error and re-dispatch into the same
handling as the typed quota/transient branches, not generic failure.
"""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai.exceptions import ModelHTTPError

from modules.backend.agents.mission_control.dispatch import retry_handler
from modules.backend.agents.mission_control.outcome import TaskStatus
from modules.backend.agents.mission_control.roster import (
    RosterAgentEntry,
    RosterConstraintsSchema,
    RosterInterfaceSchema,
    RosterModelSchema,
)
from modules.backend.schemas.task_plan import TaskDefinition


def _roster_entry(*, retry_budget: int = 0) -> RosterAgentEntry:
    return RosterAgentEntry(
        agent_name="test.agent",
        agent_version="1.0.0",
        description="test",
        model=RosterModelSchema(name="anthropic:claude-sonnet-5"),
        interface=RosterInterfaceSchema(),
        constraints=RosterConstraintsSchema(retry_budget=retry_budget),
    )


def _task() -> TaskDefinition:
    return TaskDefinition(task_id="t1", agent="test.agent", description="test task")


@pytest.mark.asyncio
async def test_raw_quota_error_fails_without_retry():
    """A raw ModelHTTPError(402) is classified as quota-exhausted and fails immediately."""
    raw_exc = ModelHTTPError(status_code=402, model_name="claude-sonnet-5", body="quota exceeded")
    mock_execute = AsyncMock(side_effect=raw_exc)
    with patch.object(retry_handler, "execute_task", mock_execute):
        result = await retry_handler.execute_with_retry(
            task=_task(),
            roster_entry=_roster_entry(retry_budget=2),
            resolved_inputs={},
            execute_agent_fn=AsyncMock(),
        )
    assert result.status == TaskStatus.FAILED
    assert "QuotaExhaustedError" in result.retry_history[0].failure_reason
    # Only one attempt — quota exhaustion never retries regardless of budget.
    assert mock_execute.await_count == 1


@pytest.mark.asyncio
async def test_raw_transient_error_retries_then_fails():
    """A raw ModelHTTPError(503) is classified as transient and retried until budget exhausts."""
    raw_exc = ModelHTTPError(status_code=503, model_name="claude-sonnet-5", body="unavailable")
    mock_execute = AsyncMock(side_effect=raw_exc)
    with patch.object(retry_handler, "execute_task", mock_execute):
        result = await retry_handler.execute_with_retry(
            task=_task(),
            roster_entry=_roster_entry(retry_budget=1),
            resolved_inputs={},
            execute_agent_fn=AsyncMock(),
        )
    assert result.status == TaskStatus.FAILED
    # retry_budget=1 → attempts 0 and 1 (one retry) before giving up.
    assert mock_execute.await_count == 2


@pytest.mark.asyncio
async def test_unrelated_error_falls_through_to_generic_handling():
    """A plain, unclassifiable exception still hits the generic failure path."""
    raw_exc = RuntimeError("some bug in agent code")
    mock_execute = AsyncMock(side_effect=raw_exc)
    with patch.object(retry_handler, "execute_task", mock_execute):
        result = await retry_handler.execute_with_retry(
            task=_task(),
            roster_entry=_roster_entry(retry_budget=1),
            resolved_inputs={},
            execute_agent_fn=AsyncMock(),
        )
    assert result.status == TaskStatus.FAILED
    assert "some bug in agent code" in result.retry_history[0].failure_reason
    # retry_budget=1 → one retry attempted before giving up.
    assert mock_execute.await_count == 2
