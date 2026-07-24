"""
Mission Artifact Model (Plan 43).

Durable storage for artifacts produced by agents during mission runs —
reports, findings, code, data summaries. Before Plan 43 these were
live-only: the ``MissionArtifactFoundEvent`` SSE event was emitted from
``agent_executor.py`` and accumulated in an in-memory Zustand store on
the frontend, then died on page refresh or backend restart. This model
persists them so a returning user can see what an overnight autonomous
run produced.

Linkage semantics:

  - ``mission_id`` is the hard owner. Mission delete cascades the
    artifact.
  - ``execution_record_id`` and ``task_execution_id`` are SET NULL on
    delete so artifacts survive archival of the specific run/task they
    originated from — the user cares about the artifact, not which
    execution row it was linked to.

See ``docs/97-plans/43-plan-persistent-mission-artifacts.md`` for the
full design rationale.
"""

import enum

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class ArtifactType(str, enum.Enum):
    """Typed artifact categories.

    Each value corresponds to an agent's ``artifact_type`` catalog field.
    Only agents with ``produces_artifact: true`` create artifacts — these
    are user-facing deliverables, not intermediate execution data.

    Domain-specific report types:
    ``research_report``           — research synthesizer output (executive summary, sections, sources)  # noqa: E501
    ``vulnerability_report``      — pentest/security scan findings with severity and remediation
    ``quality_audit``             — code quality assessment with scores and issues
    ``architecture_review``       — architecture analysis with recommendations
    ``deliberation_deliverable``  — Think Tank synthesiser FinalDeliverable (Plan 79; cruxes, minority position, committed answer)  # noqa: E501
    ``deliberation_transcript``   — Think Tank full debate transcript (Plan 79; rounds, critic reports, stance deltas)  # noqa: E501

    Generic types (for agents that don't fit a specific domain):
    ``report``    — general-purpose report
    ``code``      — generated or modified source code
    ``data``      — structured data dump (JSON, CSV, table)
    """

    # Domain-specific
    RESEARCH_REPORT = "research_report"
    VULNERABILITY_REPORT = "vulnerability_report"
    QUALITY_AUDIT = "quality_audit"
    ARCHITECTURE_REVIEW = "architecture_review"
    DELIBERATION_DELIVERABLE = "deliberation_deliverable"
    DELIBERATION_TRANSCRIPT = "deliberation_transcript"

    # Generic
    REPORT = "report"
    CODE = "code"
    DATA = "data"


class ArtifactContentType(str, enum.Enum):
    """How the ``content_text`` field should be interpreted by renderers.

    Mirrors the existing ``MissionArtifactFoundEvent.content_type`` field
    so extraction is a straight copy.
    """

    TEXT = "text"
    MARKDOWN = "markdown"
    JSON = "json"
    CODE = "code"


# Frozen sets for validation in the service layer. Kept here alongside
# the enums so a single import gets everything needed.
VALID_ARTIFACT_TYPES: frozenset[str] = frozenset(t.value for t in ArtifactType)
VALID_CONTENT_TYPES: frozenset[str] = frozenset(t.value for t in ArtifactContentType)


class MissionArtifact(UUIDMixin, TimestampMixin, Base):
    """A durable artifact produced by an agent during a mission run.

    Artifacts live as long as the mission does. When an ExecutionRecord
    or TaskExecution they were linked to is archived/deleted, the link
    column goes NULL but the artifact itself survives — the mission is
    the owner of record.

    Dual-write lifecycle (Plan 43 §3.6): during a run, the live
    ``MissionArtifactFoundEvent`` still fires via SSE for streaming
    preview. After the run completes, ``persist_mission_results`` walks
    the task results and inserts one row per non-empty
    ``summary`` / ``result`` text field. The frontend reads from the API
    on mount and invalidates on the live SSE event.
    """

    __tablename__ = "mission_artifacts"

    mission_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    execution_record_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("execution_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_execution_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("task_executions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    agent_id: Mapped[str] = mapped_column(
        String(200),
        default="",
        server_default="",
        nullable=False,
    )
    artifact_type: Mapped[str] = mapped_column(
        String(50),
        default=ArtifactType.REPORT.value,
        server_default=ArtifactType.REPORT.value,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(20),
        default=ArtifactContentType.MARKDOWN.value,
        server_default=ArtifactContentType.MARKDOWN.value,
        nullable=False,
    )
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)

    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<MissionArtifact(id={self.id!r}, mission={self.mission_id!r}, "
            f"type={self.artifact_type!r}, title={self.title[:40]!r})>"
        )
