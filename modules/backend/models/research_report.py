"""
Research Report Model (Plan 40 §5.1).

Persistent storage for deep research reports. Each report is linked to
a mission and optionally to the execution that produced it. The full
report markdown, structured sections, sources, and metadata are stored
for post-completion access via API, CLI, and Director follow-up.
"""

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class ResearchReport(UUIDMixin, TimestampMixin, Base):
    """A persisted deep research report."""

    __tablename__ = "research_reports"

    mission_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True,
    )
    execution_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True,
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    report_markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    report_structured: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
    )
    sources: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list,
    )
    metadata_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft",
    )
    tags: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list,
    )
    citation_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    verification_score: Mapped[float | None] = mapped_column(
        Float, nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<ResearchReport(id={self.id!r}, mission={self.mission_id!r}, "
            f"query={self.query[:40]!r}, status={self.status!r})>"
        )
