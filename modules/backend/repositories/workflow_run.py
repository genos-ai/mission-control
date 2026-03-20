"""
WorkflowRun Repository.

CRUD plus workflow-run-specific queries: list by status,
lookup by workflow name, cost aggregation.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.logging import get_logger
from modules.backend.models.execution import WorkflowRun, WorkflowRunState
from modules.backend.repositories.base import BaseRepository

logger = get_logger(__name__)


class WorkflowRunRepository(BaseRepository[WorkflowRun]):
    """WorkflowRun repository."""

    model = WorkflowRun

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_runs(
        self,
        playbook_name: str | None = None,
        status: WorkflowRunState | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[WorkflowRun], int]:
        """List workflow runs with optional filters."""
        conditions = []
        if playbook_name:
            conditions.append(WorkflowRun.playbook_name == playbook_name)
        if status:
            conditions.append(WorkflowRun.status == status)

        count_stmt = select(func.count()).select_from(WorkflowRun)
        if conditions:
            for cond in conditions:
                count_stmt = count_stmt.where(cond)
        total = (await self.session.execute(count_stmt)).scalar_one()

        data_stmt = (
            select(WorkflowRun)
            .order_by(WorkflowRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if conditions:
            for cond in conditions:
                data_stmt = data_stmt.where(cond)

        result = await self.session.execute(data_stmt)
        return list(result.scalars().all()), total
