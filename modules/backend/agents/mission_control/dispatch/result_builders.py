"""Factory functions for TaskResult and ExecutionOutcome construction.

Centralises the creation of failed, skipped, and aborted results so the
dispatch loop and retry handler stay focused on orchestration logic.
"""

from __future__ import annotations

import time

from modules.backend.agents.mission_control.outcome import (
    ExecutionOutcome,
    ExecutionStatus,
    RetryHistoryEntry,
    TaskResult,
    TaskStatus,
    TaskTokenUsage,
)
from modules.backend.schemas.task_failure import TaskFailure
from modules.backend.schemas.task_plan import TaskDefinition, TaskPlan


def append_feedback(original_instructions: str, feedback: str) -> str:
    """Append failure feedback to agent instructions (Reflection pattern)."""
    return f"{original_instructions}\n\n" f"--- FEEDBACK FROM PREVIOUS ATTEMPT ---\n" f"{feedback}"


def aborted_outcome(
    plan: TaskPlan,
    reason: str | None,
    start_time: float,
    task_results: list[TaskResult] | None = None,
) -> ExecutionOutcome:
    """Build an ExecutionOutcome for an aborted execution."""
    return ExecutionOutcome(
        mission_id=plan.mission_id,
        status=ExecutionStatus.FAILED,
        task_results=task_results or [],
        total_cost_usd=0.0,
        total_duration_seconds=round(time.monotonic() - start_time, 2),
        total_tokens=TaskTokenUsage(),
        abort_reason=reason,
    )


def skipped_result(
    task: TaskDefinition,
    reason: str | None = None,
    execution_id: str = "",
) -> TaskResult:
    """Build a TaskResult with SKIPPED status."""
    return TaskResult(
        task_id=task.task_id,
        agent_name=task.agent,
        status=TaskStatus.SKIPPED,
        output_reference={},
        token_usage=TaskTokenUsage(),
        cost_usd=0.0,
        duration_seconds=0.0,
        retry_count=0,
        retry_history=[],
        execution_id=execution_id,
        skip_reason=reason,
    )


def failed_result(
    task: TaskDefinition,
    failure: TaskFailure,
    *,
    status: TaskStatus = TaskStatus.FAILED,
    retry_count: int = 0,
    retry_history: list[RetryHistoryEntry] | None = None,
    execution_id: str = "",
    cost_usd: float = 0.0,
    token_usage: TaskTokenUsage | None = None,
    duration_seconds: float = 0.0,
) -> TaskResult:
    """Create a failed (or timed-out) TaskResult carrying its classified failure.

    The only failed-result builder (contracts 3.8.2). Spend already incurred
    is passed through ``cost_usd``, ``token_usage`` and ``duration_seconds``.
    """
    return TaskResult(
        task_id=task.task_id,
        agent_name=task.agent,
        status=status,
        output_reference={},
        token_usage=token_usage or TaskTokenUsage(),
        cost_usd=cost_usd,
        duration_seconds=duration_seconds,
        retry_count=retry_count,
        retry_history=retry_history or [],
        execution_id=execution_id,
        failure=failure,
    )
