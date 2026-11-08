"""
WorkflowRun Repository.

CRUD plus workflow-run-specific queries: list by status,
lookup by workflow name, cost aggregation.
"""

from collections.abc import Collection
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.logging import get_logger
from modules.backend.models.execution_record import ExecutionRecord
from modules.backend.models.workflow_run import WorkflowRun, WorkflowRunState
from modules.backend.repositories.base import BaseRepository

logger = get_logger(__name__)


class WorkflowRunRepository(BaseRepository[WorkflowRun]):
    """WorkflowRun repository."""

    model = WorkflowRun

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_runs(
        self,
        workflow_name: str | None = None,
        status: WorkflowRunState | None = None,
        mission_id: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[WorkflowRun], int]:
        """List workflow runs with optional filters."""
        conditions = []
        if mission_id:
            conditions.append(WorkflowRun.mission_id == mission_id)
        if workflow_name:
            conditions.append(WorkflowRun.workflow_name == workflow_name)
        if status:
            conditions.append(WorkflowRun.status == status)

        count_stmt = select(func.count()).select_from(WorkflowRun)
        if conditions:
            for cond in conditions:
                count_stmt = count_stmt.where(cond)
        total = (await self.session.execute(count_stmt)).scalar_one()

        data_stmt = (
            select(WorkflowRun).order_by(WorkflowRun.created_at.desc()).limit(limit).offset(offset)
        )
        if conditions:
            for cond in conditions:
                data_stmt = data_stmt.where(cond)

        result = await self.session.execute(data_stmt)
        return list(result.scalars().all()), total

    async def list_in_flight_older_than(
        self,
        cutoff: datetime,
        *,
        ids: Collection[str] | None = None,
        for_update: bool = False,
    ) -> list[WorkflowRun]:
        """Return PENDING or RUNNING runs last updated before ``cutoff``.

        Reconciler candidates: only runs whose execution record carries a
        Temporal workflow id. AWAITING_INPUT is excluded because it waits
        durably in HumanInputWorkflow. ``ids`` narrows the select;
        ``for_update`` locks the run rows with SKIP LOCKED.
        """
        query = (
            select(WorkflowRun)
            .join(ExecutionRecord, ExecutionRecord.id == WorkflowRun.execution_record_id)
            .where(
                WorkflowRun.status.in_([WorkflowRunState.PENDING, WorkflowRunState.RUNNING]),
                WorkflowRun.updated_at < cutoff,
                ExecutionRecord.temporal_workflow_id.is_not(None),
            )
        )
        if ids is not None:
            query = query.where(WorkflowRun.id.in_(list(ids)))
        if for_update:
            query = query.execution_options(populate_existing=True).with_for_update(
                skip_locked=True, of=WorkflowRun
            )
        result = await self.session.execute(query.order_by(WorkflowRun.created_at))
        return list(result.scalars().all())

    async def list_active_for_mission(self, mission_id: str) -> list[WorkflowRun]:
        """Return the mission's PENDING, RUNNING or AWAITING_INPUT runs."""
        result = await self.session.execute(
            select(WorkflowRun)
            .where(
                WorkflowRun.mission_id == mission_id,
                WorkflowRun.status.in_(
                    [
                        WorkflowRunState.PENDING,
                        WorkflowRunState.RUNNING,
                        WorkflowRunState.AWAITING_INPUT,
                    ]
                ),
            )
            .order_by(WorkflowRun.created_at)
        )
        return list(result.scalars().all())
