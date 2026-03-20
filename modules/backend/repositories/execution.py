"""
Execution Repository.

Standard CRUD plus execution-specific queries: lookup by workflow run,
active execution count, and status filtering.
"""

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.logging import get_logger
from modules.backend.models.execution import Execution, ExecutionState
from modules.backend.repositories.base import BaseRepository

logger = get_logger(__name__)


class ExecutionRepository(BaseRepository[Execution]):
    """Execution repository with workflow-specific queries."""

    model = Execution

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_by_session(self, session_id: str) -> list[Execution]:
        """Get all executions for a session."""
        stmt = (
            select(Execution)
            .where(Execution.session_id == session_id)
            .order_by(Execution.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_workflow_run(
        self, workflow_run_id: str,
    ) -> list[Execution]:
        """Get all executions for a specific workflow run."""
        stmt = (
            select(Execution)
            .where(Execution.workflow_run_id == workflow_run_id)
            .order_by(Execution.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_active(self) -> int:
        """Count currently running executions (for concurrency limits)."""
        stmt = (
            select(func.count())
            .select_from(Execution)
            .where(
                Execution.status.in_([
                    ExecutionState.PENDING,
                    ExecutionState.RUNNING,
                ])
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def list_executions(
        self,
        status: ExecutionState | None = None,
        workflow_run_id: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Execution], int]:
        """List executions with optional filters and pagination.

        Returns:
            Tuple of (executions, total_count).
        """
        conditions = []
        if status:
            conditions.append(Execution.status == status)
        if workflow_run_id:
            conditions.append(Execution.workflow_run_id == workflow_run_id)

        count_stmt = select(func.count()).select_from(Execution)
        if conditions:
            count_stmt = count_stmt.where(and_(*conditions))
        total = (await self.session.execute(count_stmt)).scalar_one()

        data_stmt = (
            select(Execution)
            .order_by(Execution.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if conditions:
            data_stmt = data_stmt.where(and_(*conditions))

        result = await self.session.execute(data_stmt)
        return list(result.scalars().all()), total
