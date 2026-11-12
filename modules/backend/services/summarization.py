"""
Summarization Service.

Fractal compression pipeline for project history:
  Task executions -> Mission summaries -> Milestone summaries -> PCD

Runs periodically or on-demand. Never deletes raw data — only marks
as summarized and excludes from default queries.
"""

from contextlib import asynccontextmanager
from datetime import timedelta
from typing import AsyncGenerator

from sqlalchemy import and_, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from modules.backend.core.config import get_app_config
from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now
from modules.backend.models.execution_record import (
    ExecutionRecord,
    ExecutionRecordStatus,
)
from modules.backend.repositories.mission_history import (
    MilestoneSummaryRepository,
    MissionDecisionRepository,
)
from modules.backend.services.base import BaseService
from modules.backend.services.mcd_pruning import (
    archive_decision_rows,
    archive_milestone_rows,
    split_decisions_by_age,
    split_milestones,
)
from modules.backend.services.mission_context import MissionContextManager

logger = get_logger(__name__)


class SummarizationService(BaseService):
    """Fractal compression pipeline for project history."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._decision_repo = MissionDecisionRepository(session)
        self._milestone_repo = MilestoneSummaryRepository(session)
        self._context_manager = MissionContextManager(session)

    @staticmethod
    @asynccontextmanager
    async def factory() -> AsyncGenerator["SummarizationService", None]:
        """Create a SummarizationService with its own DB session."""
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            yield SummarizationService(db)
            await db.commit()

    async def prune_mcd_decisions(self, mission_id: str) -> int:
        """Archive MCD decisions older than compaction.decisions_max_age_days to mission_decisions.

        Returns count of decisions archived.
        """
        max_age_days = get_app_config().missions.compaction.decisions_max_age_days
        data, version = await self._context_manager.get_context_with_version(
            mission_id,
        )
        if not data:
            return 0

        decisions = data.get("decisions", [])
        if not decisions:
            return 0

        cutoff = (utc_now() - timedelta(days=max_age_days)).isoformat()[:10]
        to_keep, to_archive = split_decisions_by_age(decisions, cutoff)
        if not to_archive:
            return 0

        await archive_decision_rows(self._decision_repo, mission_id, to_archive)

        # Update MCD with pruned decisions list
        reason = f"Archived {len(to_archive)} decisions older than {max_age_days} days"
        await self._context_manager.apply_updates(
            mission_id,
            [{"op": "replace", "path": "decisions", "value": to_keep, "reason": reason}],
            agent_id="system:summarization",
            task_id=None,
            mission_run_id=None,
            reason=reason,
        )

        self._log_operation(
            "MCD decisions pruned",
            mission_id=mission_id,
            archived=len(to_archive),
            remaining=len(to_keep),
        )

        return len(to_archive)

    async def prune_completed_workstreams(self, mission_id: str) -> int:
        """Move old milestones from current_state to milestone_summaries table.

        Keeps the most recent compaction.keep_recent_milestones milestones in the MCD.
        Returns count of milestones archived.
        """
        keep_recent = get_app_config().missions.compaction.keep_recent_milestones
        data, version = await self._context_manager.get_context_with_version(
            mission_id,
        )
        if not data:
            return 0

        current_state = data.get("current_state", {})
        milestones = current_state.get("recent_milestones", [])

        to_keep, to_archive = split_milestones(milestones, keep_recent)
        if not to_archive:
            return 0

        await archive_milestone_rows(self._milestone_repo, mission_id, to_archive)

        # Update MCD with pruned milestones list
        reason = f"Archived {len(to_archive)} old milestones"
        await self._context_manager.apply_updates(
            mission_id,
            [
                {
                    "op": "replace",
                    "path": "current_state.recent_milestones",
                    "value": to_keep,
                    "reason": reason,
                }
            ],
            agent_id="system:summarization",
            task_id=None,
            mission_run_id=None,
            reason=reason,
        )

        self._log_operation(
            "Milestones pruned",
            mission_id=mission_id,
            archived=len(to_archive),
            remaining=len(to_keep),
        )

        return len(to_archive)

    async def summarize_execution_records(
        self,
        mission_id: str,
        max_age_days: int = 30,
        batch_size: int = 10,
    ) -> int:
        """Compress old completed mission records into milestone summaries.

        Finds MissionRecords older than max_age_days that haven't been
        summarized yet, groups them into batches, and creates
        MilestoneSummary records. Marks originals as summarized=True.

        Raw data is never deleted — only excluded from default queries.
        Returns count of missions summarized.
        """
        cutoff = utc_now() - timedelta(days=max_age_days)

        result = await self.session.execute(
            select(ExecutionRecord)
            .options(selectinload(ExecutionRecord.task_executions))
            .where(
                and_(
                    ExecutionRecord.mission_id == mission_id,
                    ExecutionRecord.summarized == False,  # noqa: E712
                    ExecutionRecord.status.in_(
                        [
                            ExecutionRecordStatus.COMPLETED,
                            ExecutionRecordStatus.FAILED,
                        ]
                    ),
                    ExecutionRecord.completed_at < cutoff,
                )
            )
            .order_by(desc(ExecutionRecord.completed_at))
            .limit(batch_size * 5)
        )
        records = list(result.scalars().all())

        if not records:
            return 0

        # Process in batches
        total_summarized = 0
        for i in range(0, len(records), batch_size):
            batch = records[i : i + batch_size]
            execution_ids = [r.id for r in batch]
            objectives = [r.objective_statement or "(no objective)" for r in batch]
            statuses = [r.status for r in batch]

            # Determine period range
            completed_dates = [r.completed_at for r in batch if r.completed_at]
            _pstart = min(completed_dates) if completed_dates else None
            _pend = max(completed_dates) if completed_dates else None
            period_start = _pstart.replace(microsecond=0).isoformat() if _pstart else None
            period_end = _pend.replace(microsecond=0).isoformat() if _pend else None

            # Collect domain tags from task executions
            all_domain_tags: set[str] = set()
            for r in batch:
                if r.task_executions:
                    for te in r.task_executions:
                        if te.domain_tags:
                            all_domain_tags.update(te.domain_tags)

            # Build deterministic summary (no LLM needed for structured data)
            completed_count = sum(1 for s in statuses if s == ExecutionRecordStatus.COMPLETED)
            failed_count = sum(1 for s in statuses if s == ExecutionRecordStatus.FAILED)
            total_cost = sum(r.total_cost_usd for r in batch)

            summary_parts = [
                f"{len(batch)} missions ({completed_count} completed, "
                f"{failed_count} failed). Total cost: ${total_cost:.4f}.",
            ]
            for obj in objectives[:5]:
                summary_parts.append(f"- {obj[:100]}")
            if len(objectives) > 5:
                summary_parts.append(f"  ... and {len(objectives) - 5} more")

            await self._milestone_repo.create(
                mission_id=mission_id,
                title=f"Executions batch ({len(batch)} executions)",
                summary="\n".join(summary_parts),
                execution_ids=execution_ids,
                key_outcomes={
                    "completed": completed_count,
                    "failed": failed_count,
                    "total_cost_usd": round(total_cost, 4),
                    "objectives": objectives[:10],
                },
                domain_tags=sorted(all_domain_tags),
                period_start=period_start,
                period_end=period_end,
            )

            await self.session.execute(
                update(ExecutionRecord)
                .where(ExecutionRecord.id.in_(execution_ids))
                .values(summarized=True)
            )

            total_summarized += len(batch)

        self._log_operation(
            "Execution records summarized",
            mission_id=mission_id,
            missions_summarized=total_summarized,
        )

        return total_summarized

    async def run_full_pipeline(
        self,
        mission_id: str,
    ) -> dict:
        """Run the full summarization pipeline for a project.

        Returns summary of actions taken.
        """
        results = {
            "decisions_archived": 0,
            "missions_summarized": 0,
            "milestones_archived": 0,
        }

        results["decisions_archived"] = await self.prune_mcd_decisions(
            mission_id,
        )
        results["missions_summarized"] = await self.summarize_execution_records(
            mission_id,
        )
        results["milestones_archived"] = await self.prune_completed_workstreams(
            mission_id,
        )

        self._log_operation(
            "Summarization pipeline complete",
            mission_id=mission_id,
            **results,
        )

        return results
