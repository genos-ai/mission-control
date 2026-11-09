"""
Execution Record Repository.

Standard CRUD plus execution-specific queries: cost aggregation,
status filtering, session lookups, re-plan lineage.
"""

from collections.abc import Collection
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from modules.backend.core.logging import get_logger
from modules.backend.models.execution_record import (
    ExecutionDecision,
    ExecutionRecord,
    ExecutionRecordStatus,
    TaskExecution,
)
from modules.backend.repositories.base import BaseRepository

logger = get_logger(__name__)


class ExecutionRecordRepository(BaseRepository[ExecutionRecord]):
    """Execution record repository with audit-specific queries."""

    model = ExecutionRecord

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_with_details(self, execution_id: str) -> ExecutionRecord | None:
        """Get execution record with task executions and decisions eagerly loaded."""
        stmt = (
            select(ExecutionRecord)
            .where(ExecutionRecord.id == execution_id)
            .options(
                selectinload(ExecutionRecord.task_executions).selectinload(TaskExecution.attempts),
                selectinload(ExecutionRecord.decisions),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_in_flight_older_than(
        self,
        cutoff: datetime,
        *,
        ids: Collection[str] | None = None,
        for_update: bool = False,
    ) -> list[ExecutionRecord]:
        """Return PENDING or RUNNING records last updated before ``cutoff``.

        Reconciler candidates: only records driven by Temporal, directly
        (``temporal_workflow_id``) or through a workflow run
        (``workflow_run_id``). In-process records carry neither and are
        never returned. ``ids`` narrows the select; ``for_update`` locks
        with SKIP LOCKED.
        """
        query = select(ExecutionRecord).where(
            ExecutionRecord.status.in_(
                [ExecutionRecordStatus.PENDING, ExecutionRecordStatus.RUNNING]
            ),
            ExecutionRecord.updated_at < cutoff,
            or_(
                ExecutionRecord.temporal_workflow_id.is_not(None),
                ExecutionRecord.workflow_run_id.is_not(None),
            ),
        )
        if ids is not None:
            query = query.where(ExecutionRecord.id.in_(list(ids)))
        if for_update:
            query = query.execution_options(populate_existing=True).with_for_update(
                skip_locked=True
            )
        result = await self.session.execute(query.order_by(ExecutionRecord.created_at))
        return list(result.scalars().all())

    async def get_by_mission_run(self, mission_run_id: str) -> ExecutionRecord | None:
        """The mission run's single ExecutionRecord (uq_execution_records_run)."""
        stmt = select(ExecutionRecord).where(ExecutionRecord.mission_run_id == mission_run_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_session(self, session_id: str) -> list[ExecutionRecord]:
        """Get all execution records for a session, newest first."""
        stmt = (
            select(ExecutionRecord)
            .where(ExecutionRecord.session_id == session_id)
            .order_by(ExecutionRecord.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_workflow_run(self, workflow_run_id: str) -> list[ExecutionRecord]:
        """Get all step execution records for a workflow run, in creation order."""
        stmt = (
            select(ExecutionRecord)
            .where(ExecutionRecord.workflow_run_id == workflow_run_id)
            .order_by(ExecutionRecord.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_executions(
        self,
        status: ExecutionRecordStatus | None = None,
        roster_name: str | None = None,
        objective_category: str | None = None,
        mission_id: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[ExecutionRecord], int]:
        """List execution records with optional filters and pagination."""
        conditions = []
        if status:
            conditions.append(ExecutionRecord.status == status)
        if roster_name:
            conditions.append(ExecutionRecord.roster_name == roster_name)
        if objective_category:
            conditions.append(ExecutionRecord.objective_category == objective_category)
        if mission_id:
            conditions.append(ExecutionRecord.mission_id == mission_id)

        count_stmt = select(func.count()).select_from(ExecutionRecord)
        if conditions:
            count_stmt = count_stmt.where(and_(*conditions))
        total = (await self.session.execute(count_stmt)).scalar_one()

        data_stmt = (
            select(ExecutionRecord)
            # Plan 46 Phase 2 #3: eager-load task_executions so the
            # Runs tab list row can render task_count without an N+1
            # query. selectinload uses a single secondary IN query
            # rather than a join, which keeps per-row select costs
            # down at list time.
            .options(selectinload(ExecutionRecord.task_executions))
            .order_by(ExecutionRecord.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if conditions:
            data_stmt = data_stmt.where(and_(*conditions))

        result = await self.session.execute(data_stmt)
        return list(result.scalars().all()), total

    async def get_decisions(self, execution_id: str) -> list[ExecutionDecision]:
        """Get all decisions for an execution, ordered chronologically."""
        stmt = (
            select(ExecutionDecision)
            .where(ExecutionDecision.execution_record_id == execution_id)
            .order_by(ExecutionDecision.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_task_executions(
        self,
        execution_id: str,
    ) -> list[TaskExecution]:
        """Get all task executions for an execution with attempts loaded."""
        stmt = (
            select(TaskExecution)
            .where(TaskExecution.execution_record_id == execution_id)
            .options(selectinload(TaskExecution.attempts))
            .order_by(TaskExecution.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_cost_by_model(self, execution_id: str) -> dict[str, float]:
        """Aggregate cost by model for an execution."""
        executions = await self.get_task_executions(execution_id)
        model_costs: dict[str, float] = {}
        for execution in executions:
            if execution.token_usage and "model" in execution.token_usage:
                model = execution.token_usage["model"]
                model_costs[model] = model_costs.get(model, 0.0) + execution.cost_usd
        return model_costs
