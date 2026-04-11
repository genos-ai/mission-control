"""
Mission Artifact Service (Plan 43).

Business logic for durable mission artifacts. Thin service — the
repository owns the queries; this layer validates inputs and adds a
single ``extract_from_outcome`` convenience that ``persist_mission_results``
calls to extract artifacts from a completed run's task results.

See ``docs/97-plans/43-plan-persistent-mission-artifacts.md`` §3.3 for
the extraction heuristic (the same ``summary`` / ``result`` fields the
live SSE emission site already reads).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ValidationError
from modules.backend.core.logging import get_logger
from modules.backend.models.mission_artifact import (
    VALID_ARTIFACT_TYPES,
    VALID_CONTENT_TYPES,
    MissionArtifact,
)
from modules.backend.repositories.mission_artifact import MissionArtifactRepository
from modules.backend.services.base import BaseService

if TYPE_CHECKING:
    from modules.backend.agents.mission_control.outcome import TaskResult

logger = get_logger(__name__)


# Hard cap on a single artifact's persisted content. Defends the DB
# from a runaway agent that dumps an entire file as a "summary".
# Generous enough that normal agent reports (few hundred to low
# thousands of chars) are never truncated.
_MAX_CONTENT_CHARS = 100_000


class MissionArtifactService(BaseService):
    """Orchestrates durable artifact storage for missions.

    Phase A scope:
        - Validated CRUD
        - Extraction from a completed ExecutionOutcome's task_results
        - List-for-mission query used by the API

    Not yet:
        - File artifact storage (deferred, see Plan 43 §3.7)
        - Cross-run deduplication (explicitly out of scope)
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._repo = MissionArtifactRepository(session)

    # ── Read ─────────────────────────────────────────────────────────────

    async def list_for_mission(
        self,
        mission_id: str,
        *,
        limit: int = 50,
        artifact_type: str | None = None,
    ) -> list[MissionArtifact]:
        """List artifacts for a mission, newest first."""
        if artifact_type is not None and artifact_type not in VALID_ARTIFACT_TYPES:
            raise ValidationError(
                f"Invalid artifact_type {artifact_type!r}. "
                f"Allowed: {sorted(VALID_ARTIFACT_TYPES)}"
            )
        return await self._repo.list_for_mission(
            mission_id, limit=limit, artifact_type=artifact_type,
        )

    async def list_for_execution_record(
        self, execution_record_id: str,
    ) -> list[MissionArtifact]:
        """List all artifacts produced by a specific run."""
        return await self._repo.list_for_execution_record(execution_record_id)

    # ── Write ────────────────────────────────────────────────────────────

    async def create_artifact(
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
        """Validate + persist a new artifact row.

        Raises:
            ValidationError: If ``artifact_type`` or ``content_type`` is
                not in the allowed enum, or if required fields are
                missing/empty.
        """
        if artifact_type not in VALID_ARTIFACT_TYPES:
            raise ValidationError(
                f"Invalid artifact_type {artifact_type!r}. "
                f"Allowed: {sorted(VALID_ARTIFACT_TYPES)}"
            )
        if content_type not in VALID_CONTENT_TYPES:
            raise ValidationError(
                f"Invalid content_type {content_type!r}. "
                f"Allowed: {sorted(VALID_CONTENT_TYPES)}"
            )
        if not title or not title.strip():
            raise ValidationError("Artifact title is required")
        if not content_text or not content_text.strip():
            raise ValidationError("Artifact content_text is required")

        # Defensive cap so a runaway agent can't flood the DB with a
        # 10MB "summary". Hard limit — applied silently with a log line.
        if len(content_text) > _MAX_CONTENT_CHARS:
            logger.warning(
                "Artifact content truncated at hard cap",
                extra={
                    "mission_id": mission_id,
                    "agent_id": agent_id,
                    "original_len": len(content_text),
                    "cap": _MAX_CONTENT_CHARS,
                },
            )
            content_text = content_text[:_MAX_CONTENT_CHARS]

        artifact = await self._repo.create(
            mission_id=mission_id,
            agent_id=agent_id,
            title=title.strip(),
            content_text=content_text,
            execution_record_id=execution_record_id,
            task_execution_id=task_execution_id,
            artifact_type=artifact_type,
            content_type=content_type,
            language=language,
        )
        self._log_operation(
            "MissionArtifact created",
            artifact_id=artifact.id,
            mission_id=mission_id,
            agent_id=agent_id,
            artifact_type=artifact_type,
            content_chars=len(content_text),
        )
        return artifact

    # ── Extraction from a completed run ─────────────────────────────────

    async def extract_from_task_result(
        self,
        *,
        mission_id: str,
        execution_record_id: str,
        task_execution_id: str,
        task_result: "TaskResult",
    ) -> MissionArtifact | None:
        """Extract an artifact from one completed task result, if any.

        Uses the same heuristic as the live SSE emission site in
        ``agents/mission_control/helpers/agent_executor.py``: if the
        task's ``output_reference`` dict has a non-empty ``summary`` or
        ``result`` string field, persist it as a ``report`` artifact.

        Returns the created artifact, or ``None`` if the task_result has
        no extractable content (no summary, no result, or both empty).

        This is the extraction hook called from
        ``persist_mission_results``. Failure is best-effort — caller
        wraps in a try/except and logs, never raises.
        """
        output = task_result.output_reference or {}
        if not isinstance(output, dict):
            return None

        content: str | None = None
        if isinstance(output.get("summary"), str) and output["summary"].strip():
            content = output["summary"]
        elif isinstance(output.get("result"), str) and output["result"].strip():
            content = output["result"]

        if not content:
            return None

        agent_name = task_result.agent_name or ""
        return await self.create_artifact(
            mission_id=mission_id,
            execution_record_id=execution_record_id,
            task_execution_id=task_execution_id,
            agent_id=agent_name,
            artifact_type="report",
            title=f"{agent_name} — result" if agent_name else "Agent result",
            content_text=content,
            content_type="markdown",
        )
