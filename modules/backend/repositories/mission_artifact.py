"""
Mission Artifact Repository (Plan 43).

Data access for MissionArtifact. Thin repository — all business logic
(extraction, validation, dedup policy) lives in MissionArtifactService.
"""

from sqlalchemy import select

from modules.backend.models.execution_record import TaskExecution
from modules.backend.models.mission_artifact import MissionArtifact
from modules.backend.repositories.base import BaseRepository


class MissionArtifactRepository(BaseRepository[MissionArtifact]):
    """Repository for MissionArtifact CRUD."""

    model = MissionArtifact

    async def list_for_mission(
        self,
        mission_id: str,
        *,
        limit: int = 50,
        artifact_type: str | None = None,
    ) -> list[MissionArtifact]:
        """Return artifacts for a mission, newest first.

        Args:
            mission_id: Mission to filter on.
            limit: Maximum rows to return (caller-supplied hard cap).
            artifact_type: Optional exact-match filter (``report``,
                ``finding``, etc). No validation here — invalid values
                simply return zero rows.

        Returns:
            List of MissionArtifact instances ordered by created_at desc.
        """
        query = (
            select(MissionArtifact)
            .where(MissionArtifact.mission_id == mission_id)
            .order_by(MissionArtifact.created_at.desc())
            .limit(limit)
        )
        if artifact_type is not None:
            query = query.where(MissionArtifact.artifact_type == artifact_type)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def list_for_execution_record(
        self,
        execution_record_id: str,
    ) -> list[MissionArtifact]:
        """Return all artifacts linked to a specific run.

        Used by the Runs tab drill-in to show per-run output beyond
        raw task_executions.output_data JSON.
        """
        result = await self.session.execute(
            select(MissionArtifact)
            .where(MissionArtifact.execution_record_id == execution_record_id)
            .order_by(MissionArtifact.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_for_task_execution(
        self,
        task_execution_id: str,
    ) -> list[MissionArtifact]:
        """Return all artifacts linked to a specific task execution."""
        result = await self.session.execute(
            select(MissionArtifact)
            .where(MissionArtifact.task_execution_id == task_execution_id)
            .order_by(MissionArtifact.created_at.desc())
        )
        return list(result.scalars().all())

    async def ids_by_task_for_run(self, mission_run_id: str) -> dict[str, list[str]]:
        """Artifact ids per task id, linked through the run's task executions, oldest first."""
        result = await self.session.execute(
            select(TaskExecution.task_id, MissionArtifact.id)
            .join(TaskExecution, MissionArtifact.task_execution_id == TaskExecution.id)
            .where(TaskExecution.mission_run_id == mission_run_id)
            .order_by(MissionArtifact.created_at, MissionArtifact.id)
        )
        ids: dict[str, list[str]] = {}
        for task_id, artifact_id in result.all():
            ids.setdefault(task_id, []).append(artifact_id)
        return ids

    async def create(
        self,
        *,
        mission_id: str,
        agent_id: str,
        title: str,
        content_text: str,
        execution_record_id: str | None = None,
        task_execution_id: str | None = None,
        artifact_type: str = "report",
        content_type: str = "markdown",
        language: str | None = None,
    ) -> MissionArtifact:
        """Insert a new artifact row.

        The caller is responsible for validating ``artifact_type`` and
        ``content_type`` against the enums — the repository trusts its
        inputs. Use ``MissionArtifactService.create_artifact`` for the
        validated path.
        """
        artifact = MissionArtifact(
            mission_id=mission_id,
            execution_record_id=execution_record_id,
            task_execution_id=task_execution_id,
            agent_id=agent_id,
            artifact_type=artifact_type,
            title=title,
            content_type=content_type,
            language=language,
            content_text=content_text,
        )
        self.session.add(artifact)
        await self.session.flush()
        await self.session.refresh(artifact)
        return artifact
