"""
Execution Persistence Service.

Saves Mission Control execution artifacts to PostgreSQL for audit,
compliance, cost analytics, and historical queries.

Called by the dispatch loop (Plan 13) during and after execution.
This service is write-heavy during execution and read-heavy afterward.
"""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config import get_app_config
from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now


def _to_datetime(value: str | datetime | None) -> datetime | None:
    """Coerce a string or datetime to a datetime. Returns None if empty."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value)
    return None
from modules.backend.models.execution_record import (
    DecisionType,
    FailureTier,
    ExecutionDecision,
    ExecutionRecord,
    ExecutionRecordStatus,
    TaskAttempt,
    TaskAttemptStatus,
    TaskExecution,
    TaskExecutionStatus,
)
from modules.backend.repositories.execution_record import ExecutionRecordRepository
from modules.backend.schemas.execution_record import ExecutionCostBreakdown
from modules.backend.services.base import BaseService

logger = get_logger(__name__)


class ExecutionPersistenceService(BaseService):
    """Persist and query execution records.

    Write methods are called during/after dispatch loop execution.
    Read methods serve the REST API and analytics.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._repo = ExecutionRecordRepository(session)

    @staticmethod
    @asynccontextmanager
    async def factory() -> "AsyncGenerator[ExecutionPersistenceService, None]":
        """Create an ExecutionPersistenceService with its own DB session."""
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            yield ExecutionPersistenceService(db)
            await db.commit()

    # ---- Write operations (called by dispatch loop) ----

    async def save_execution(
        self,
        session_id: str,
        status: str,
        *,
        roster_name: str | None = None,
        task_plan_json: dict | None = None,
        execution_outcome_json: dict | None = None,
        planning_thinking_trace: str | None = None,
        total_cost_usd: float = 0.0,
        started_at: str | None = None,
        completed_at: str | None = None,
        parent_execution_record_id: str | None = None,
        objective_statement: str | None = None,
        objective_category: str | None = None,
        mission_id: str | None = None,
    ) -> ExecutionRecord:
        """Persist a complete execution record.

        Called after the dispatch loop completes (or fails/times out).
        """
        config = get_app_config().executions

        if planning_thinking_trace and config.persist_thinking_trace:
            if len(planning_thinking_trace) > config.max_thinking_trace_length:
                planning_thinking_trace = (
                    planning_thinking_trace[: config.max_thinking_trace_length]
                    + "\n\n[TRUNCATED]"
                )
        elif not config.persist_thinking_trace:
            planning_thinking_trace = None

        record = ExecutionRecord(
            session_id=session_id,
            roster_name=roster_name,
            status=ExecutionRecordStatus(status),
            task_plan_json=task_plan_json,
            execution_outcome_json=execution_outcome_json,
            planning_thinking_trace=planning_thinking_trace,
            total_cost_usd=total_cost_usd,
            started_at=_to_datetime(started_at) or utc_now(),
            completed_at=_to_datetime(completed_at) or utc_now(),
            parent_execution_record_id=parent_execution_record_id,
            objective_statement=objective_statement,
            objective_category=objective_category,
            mission_id=mission_id,
        )

        self._session.add(record)
        await self._session.flush()
        await self._session.refresh(record)

        logger.info(
            "Execution record saved",
            extra={
                "execution_id": record.id,
                "session_id": session_id,
                "roster": roster_name,
                "status": status,
                "cost": total_cost_usd,
            },
        )

        return record

    async def save_task_execution(
        self,
        execution_record_id: str,
        task_id: str,
        agent_name: str,
        status: str,
        *,
        output_data: dict | None = None,
        token_usage: dict | None = None,
        cost_usd: float = 0.0,
        duration_seconds: float | None = None,
        verification_outcome: dict | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
        execution_id: str | None = None,
        domain_tags: list[str] | None = None,
    ) -> TaskExecution:
        """Persist a single task execution result."""
        config = get_app_config().executions

        if output_data:
            output_size = len(json.dumps(output_data).encode("utf-8"))
            if output_size > config.max_task_output_size_bytes:
                output_data = {
                    "_truncated": True,
                    "_original_size_bytes": output_size,
                    "_message": "Output truncated. Exceeded max_task_output_size_bytes.",
                }

        if verification_outcome and not config.persist_verification_details:
            verification_outcome = {
                "passed": verification_outcome.get("passed"),
                "tier": verification_outcome.get("tier"),
            }

        execution = TaskExecution(
            execution_record_id=execution_record_id,
            task_id=task_id,
            agent_name=agent_name,
            status=TaskExecutionStatus(status),
            output_data=output_data,
            token_usage=token_usage,
            cost_usd=cost_usd,
            duration_seconds=duration_seconds,
            verification_outcome=verification_outcome,
            started_at=started_at,
            completed_at=completed_at,
            execution_id=execution_id,
            domain_tags=domain_tags,
        )

        self._session.add(execution)
        await self._session.flush()
        await self._session.refresh(execution)

        logger.debug(
            "Task execution saved",
            extra={
                "execution_id": execution.id,
                "record_id": execution_record_id,
                "task_id": task_id,
                "agent": agent_name,
                "status": status,
                "cost": cost_usd,
            },
        )

        return execution

    async def save_attempt(
        self,
        task_execution_id: str,
        attempt_number: int,
        status: str,
        *,
        failure_tier: str | None = None,
        failure_reason: str | None = None,
        feedback_provided: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> TaskAttempt:
        """Persist a single task attempt within a task execution."""
        attempt = TaskAttempt(
            task_execution_id=task_execution_id,
            attempt_number=attempt_number,
            status=TaskAttemptStatus(status),
            failure_tier=FailureTier(failure_tier) if failure_tier else None,
            failure_reason=failure_reason,
            feedback_provided=feedback_provided,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )

        self._session.add(attempt)
        await self._session.flush()
        await self._session.refresh(attempt)

        return attempt

    async def save_decision(
        self,
        execution_record_id: str,
        decision_type: str,
        reasoning: str,
        *,
        task_id: str | None = None,
    ) -> ExecutionDecision:
        """Log a Mission Control decision."""
        decision = ExecutionDecision(
            execution_record_id=execution_record_id,
            decision_type=DecisionType(decision_type),
            task_id=task_id,
            reasoning=reasoning,
        )

        self._session.add(decision)
        await self._session.flush()
        await self._session.refresh(decision)

        logger.debug(
            "Decision logged",
            extra={
                "decision_id": decision.id,
                "record_id": execution_record_id,
                "type": decision_type,
                "task_id": task_id,
            },
        )

        return decision

    # ---- Read operations (serve REST API) ----

    async def get_execution(self, execution_id: str) -> ExecutionRecord | None:
        """Get an execution record with all details loaded."""
        return await self._repo.get_with_details(execution_id)

    async def get_task_executions(self, execution_id: str) -> list:
        """Get task executions for an execution."""
        return await self._repo.get_task_executions(execution_id)

    async def list_executions(
        self,
        status: str | None = None,
        roster_name: str | None = None,
        objective_category: str | None = None,
        mission_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[ExecutionRecord], int]:
        """List execution records with optional filters."""
        config = get_app_config().executions
        if limit is None:
            limit = config.default_page_size
        limit = min(limit, config.max_page_size)

        try:
            record_status = ExecutionRecordStatus(status) if status else None
        except ValueError:
            record_status = None
        return await self._repo.list_executions(
            status=record_status,
            roster_name=roster_name,
            objective_category=objective_category,
            mission_id=mission_id,
            limit=limit,
            offset=offset,
        )

    async def get_decisions(self, execution_id: str) -> list[ExecutionDecision]:
        """Get the decision audit trail for an execution."""
        return await self._repo.get_decisions(execution_id)

    async def get_cost_breakdown(self, execution_id: str) -> ExecutionCostBreakdown:
        """Get detailed cost breakdown for an execution."""
        record = await self._repo.get_by_id_or_none(execution_id)
        if not record:
            from modules.backend.core.exceptions import NotFoundError
            raise NotFoundError(f"Execution '{execution_id}' not found")

        executions = await self._repo.get_task_executions(execution_id)
        model_costs = await self._repo.get_cost_by_model(execution_id)

        task_costs: list[dict[str, Any]] = []
        total_input_tokens = 0
        total_output_tokens = 0
        total_attempts = 0

        for execution in executions:
            input_tok = 0
            output_tok = 0
            if execution.token_usage:
                input_tok = execution.token_usage.get("input_tokens", 0)
                output_tok = execution.token_usage.get("output_tokens", 0)
            total_input_tokens += input_tok
            total_output_tokens += output_tok
            task_cost: dict[str, Any] = {
                "task_id": execution.task_id,
                "agent_name": execution.agent_name,
                "cost_usd": execution.cost_usd,
                "status": execution.status,
                "duration_seconds": execution.duration_seconds,
                "input_tokens": input_tok,
                "output_tokens": output_tok,
            }

            total_attempts += len(execution.attempts)
            task_costs.append(task_cost)

        return ExecutionCostBreakdown(
            execution_id=execution_id,
            total_cost_usd=record.total_cost_usd,
            task_costs=task_costs,
            model_costs=model_costs,
            attempt_count=total_attempts,
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
        )

    async def get_execution_status(self, execution_id: str) -> dict:
        """Get execution progress summary as a dict.

        Returns a dict with execution_id, status, objective, task counts,
        and progress percentage. Used by Temporal Queries and the
        /missions/{id}/status API endpoint.
        """
        record = await self._repo.get_by_id_or_none(execution_id)
        if not record:
            from modules.backend.core.exceptions import NotFoundError
            raise NotFoundError(f"Execution '{execution_id}' not found")

        executions = await self._repo.get_task_executions(execution_id)

        total = len(executions)
        completed = sum(
            1 for e in executions
            if e.status == TaskExecutionStatus.COMPLETED
        )
        failed = sum(
            1 for e in executions
            if e.status == TaskExecutionStatus.FAILED
        )
        skipped = sum(
            1 for e in executions
            if e.status == TaskExecutionStatus.SKIPPED
        )

        progress_pct = (completed / total * 100.0) if total > 0 else 0.0

        return {
            "execution_id": execution_id,
            "status": record.status.value if hasattr(record.status, "value") else str(record.status),
            "objective": record.objective_statement,
            "roster_name": record.roster_name,
            "total_tasks": total,
            "completed_tasks": completed,
            "failed_tasks": failed,
            "skipped_tasks": skipped,
            "progress_pct": round(progress_pct, 1),
            "total_cost_usd": record.total_cost_usd,
        }

    async def get_executions_by_session(
        self, session_id: str,
    ) -> list[ExecutionRecord]:
        """Get all execution records for a session."""
        return await self._repo.get_by_session(session_id)

    async def get_replan_chain(self, execution_id: str) -> list[ExecutionRecord]:
        """Get the full re-plan lineage for an execution."""
        return await self._repo.get_replan_chain(execution_id)
