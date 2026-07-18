"""
Platform Metrics Service.

Aggregates system-wide statistics from execution records, workflow runs,
sessions, costs, and agent catalog for the admin dashboard. All queries
are read-only and designed for periodic polling, not real-time streaming.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now
from modules.backend.models.agent_catalog import AgentCatalog
from modules.backend.models.execution_record import ExecutionRecord, TaskExecution
from modules.backend.models.mission import Mission
from modules.backend.models.session import Session
from modules.backend.models.workflow_run import WorkflowRun
from modules.backend.services.base import BaseService

logger = get_logger(__name__)


class PlatformMetricsService(BaseService):
    """Aggregate platform-wide statistics for admin dashboards."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    @asynccontextmanager
    async def factory() -> AsyncGenerator["PlatformMetricsService", None]:
        """Create a PlatformMetricsService with its own DB session."""
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            yield PlatformMetricsService(db)

    async def get_overview(self) -> dict[str, Any]:
        """Get high-level platform overview metrics.

        Returns counts for missions, sessions, executions, workflow runs,
        agents, and total cost.
        """
        queries = {
            "missions": select(func.count()).select_from(Mission),
            "sessions": select(func.count()).select_from(Session),
            "execution_records": select(func.count()).select_from(ExecutionRecord),
            "workflow_runs": select(func.count()).select_from(WorkflowRun),
            "agents": select(func.count()).select_from(AgentCatalog),
        }

        counts: dict[str, int] = {}
        for key, stmt in queries.items():
            result = await self._session.execute(stmt)
            counts[key] = result.scalar() or 0

        cost_result = await self._session.execute(
            select(func.coalesce(func.sum(ExecutionRecord.total_cost_usd), 0.0))
        )
        total_cost = float(cost_result.scalar() or 0.0)

        return {
            "counts": counts,
            "total_cost_usd": total_cost,
            "generated_at": utc_now().isoformat(),
        }

    async def get_cost_summary(
        self,
        *,
        since: datetime | None = None,
    ) -> dict[str, Any]:
        """Get cost breakdown by agent and by status.

        Args:
            since: Optional datetime to filter records created after this time.
                   When None, returns all-time aggregates.
        """
        by_agent_stmt = (
            select(
                TaskExecution.agent_name,
                func.count().label("runs"),
                func.coalesce(func.sum(TaskExecution.cost_usd), 0.0).label("total_cost"),
            )
            .group_by(TaskExecution.agent_name)
            .order_by(func.sum(TaskExecution.cost_usd).desc())
            .limit(20)
        )
        if since is not None:
            by_agent_stmt = by_agent_stmt.where(TaskExecution.created_at >= since)

        agent_result = await self._session.execute(by_agent_stmt)
        by_agent = [
            {
                "agent_name": row.agent_name,
                "runs": row.runs,
                "total_cost_usd": float(row.total_cost),
            }
            for row in agent_result
        ]

        by_status_stmt = select(
            ExecutionRecord.status,
            func.count().label("count"),
            func.coalesce(func.sum(ExecutionRecord.total_cost_usd), 0.0).label("cost"),
        ).group_by(ExecutionRecord.status)
        if since is not None:
            by_status_stmt = by_status_stmt.where(ExecutionRecord.created_at >= since)

        status_result = await self._session.execute(by_status_stmt)
        by_status = [
            {"status": row.status, "count": row.count, "total_cost_usd": float(row.cost)}
            for row in status_result
        ]

        return {
            "by_agent": by_agent,
            "by_status": by_status,
            "since": since.isoformat() if since else None,
            "generated_at": utc_now().isoformat(),
        }

    async def get_agent_utilisation(self) -> list[dict[str, Any]]:
        """Get per-agent utilisation stats from task executions."""
        stmt = (
            select(
                TaskExecution.agent_name,
                func.count().label("total_runs"),
                func.coalesce(func.sum(TaskExecution.cost_usd), 0.0).label("total_cost"),
                func.coalesce(func.avg(TaskExecution.cost_usd), 0.0).label("avg_cost"),
                func.coalesce(func.avg(TaskExecution.duration_seconds), 0.0).label("avg_duration"),
            )
            .group_by(TaskExecution.agent_name)
            .order_by(func.count().desc())
        )
        result = await self._session.execute(stmt)
        return [
            {
                "agent_name": row.agent_name,
                "total_runs": row.total_runs,
                "total_cost_usd": float(row.total_cost),
                "avg_cost_usd": float(row.avg_cost),
                "avg_duration_seconds": float(row.avg_duration) if row.avg_duration else None,
            }
            for row in result
        ]

    async def get_recent_activity(self, limit: int = 20) -> dict[str, Any]:
        """Get recent executions and workflow runs."""
        exec_stmt = select(ExecutionRecord).order_by(ExecutionRecord.created_at.desc()).limit(limit)
        exec_result = await self._session.execute(exec_stmt)
        executions = [
            {
                "id": r.id,
                "status": r.status,
                "roster_name": r.roster_name,
                "objective_category": r.objective_category,
                "cost_usd": r.total_cost_usd,
                "created_at": r.created_at,
            }
            for r in exec_result.scalars()
        ]

        run_stmt = select(WorkflowRun).order_by(WorkflowRun.created_at.desc()).limit(limit)
        run_result = await self._session.execute(run_stmt)
        runs = [
            {
                "id": r.id,
                "workflow_name": r.workflow_name,
                "status": r.status if isinstance(r.status, str) else r.status.value,
                "cost_usd": r.total_cost_usd,
                "created_at": r.created_at,
            }
            for r in run_result.scalars()
        ]

        return {
            "recent_executions": executions,
            "recent_workflow_runs": runs,
        }
