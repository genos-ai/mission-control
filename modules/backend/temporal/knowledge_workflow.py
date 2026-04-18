"""
Knowledge Platform Workflows (Plan 57).

Scheduled workflows for knowledge extraction, officer curation,
and embedding backfill. Same pattern as maintenance_workflow.py.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from modules.backend.temporal import knowledge_activities


@workflow.defn
class KnowledgeExtractionWorkflow:
    """Daily learning extraction across all active missions."""

    @workflow.run
    async def run(self) -> dict:
        return await workflow.execute_local_activity(
            knowledge_activities.extract_all_missions,
            schedule_to_close_timeout=timedelta(seconds=300),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@workflow.defn
class KnowledgeOfficerWorkflow:
    """Daily knowledge officer curation run."""

    @workflow.run
    async def run(self) -> dict:
        return await workflow.execute_activity(
            knowledge_activities.run_knowledge_officer,
            schedule_to_close_timeout=timedelta(seconds=120),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@workflow.defn
class EmbeddingBackfillWorkflow:
    """Daily embedding backfill for missing vectors."""

    @workflow.run
    async def run(self) -> dict:
        return await workflow.execute_local_activity(
            knowledge_activities.backfill_embeddings,
            schedule_to_close_timeout=timedelta(seconds=300),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
