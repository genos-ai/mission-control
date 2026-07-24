"""
Mission Learning Model.

Structured knowledge entries extracted from execution history.
Mission-scoped by default; promoted to platform scope via
``platform_promoted=True``.
"""

import enum

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class LearningKind(str, enum.Enum):
    """Classification of the learning."""

    FAILURE_PATTERN = "failure_pattern"
    SUCCESS_PATTERN = "success_pattern"
    ANTI_PATTERN = "anti_pattern"
    RETRY_STRATEGY = "retry_strategy"
    CAPABILITY_GAP = "capability_gap"


class LearningStatus(str, enum.Enum):
    """Lifecycle status of a learning entry."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"


class MissionLearning(UUIDMixin, TimestampMixin, Base):
    """A structured knowledge entry extracted from execution history.

    Created by MissionLearningExtractor (deterministic). Promoted to
    platform scope by the Knowledge Officer Agent. Evidence is stored
    uncapped; render pagination is a UI concern.
    """

    __tablename__ = "mission_learnings"

    mission_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Classification
    kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    body: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    recommendation: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Evidence — uncapped JSONB following Evidence schema
    evidence: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )

    # Tags and scope
    domain_tags: Mapped[list] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    agent_names: Mapped[list] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )

    # Confidence and frequency
    confidence: Mapped[float] = mapped_column(
        Numeric(12, 6, asdecimal=False),
        nullable=False,
        default=0.0,
    )
    occurrence_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )

    # Platform promotion
    platform_promoted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    promoted_at: Mapped[str | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    promoted_by: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    # Contradiction tracking
    contradicts_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("mission_learnings.id"),
        nullable=True,
    )

    # Status
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=LearningStatus.ACTIVE.value,
    )

    @property
    def embed_text(self) -> str:
        """Text representation used for embedding generation."""
        return f"{self.title}\n{self.body}\n{self.recommendation}"

    def __repr__(self) -> str:
        return (
            f"<MissionLearning(kind={self.kind}, title={self.title!r:.40}, "
            f"confidence={self.confidence:.2f}, promoted={self.platform_promoted})>"
        )
