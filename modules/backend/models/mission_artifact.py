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
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class ArtifactType(str, enum.Enum):
    """Typed artifact categories.

    ``report``  — free-form markdown summary from an agent (the v1 default
                  and only type currently emitted in practice).
    ``finding`` — a structured security/quality finding. Reserved for
                  future emission sites where agents produce structured
                  output with severity, CVE, evidence, etc.
    ``code``    — generated or modified source code. Reserved.
    ``data``    — structured data dump (JSON, CSV, table). Reserved.
    ``file``    — binary or large file artifact. Reserved for v2; will
                  require a storage decision (DB blob / filesystem /
                  object store) when the first real use case lands.
    """

    REPORT = "report"
    FINDING = "finding"
    CODE = "code"
    DATA = "data"
    FILE = "file"


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
        String(36),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    execution_record_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("execution_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_execution_id: Mapped[str | None] = mapped_column(
        String(36),
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
        String(20),
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
