"""
Mission Context Model.

The MissionContext stores the Mission Context Document (MCD) — a living,
curated JSON document that captures everything an agent needs to orient
itself within a mission. The ContextChange table is the audit trail of
every MCD mutation.
"""

import enum

from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class ChangeType(str, enum.Enum):
    """Type of MCD mutation."""

    ADD = "add"
    REPLACE = "replace"
    REMOVE = "remove"
    PRUNE = "prune"
    ARCHIVE = "archive"


class MissionContext(UUIDMixin, TimestampMixin, Base):
    """The Mission Context Document (MCD) for a single mission.

    One row per mission. Contains the entire MCD as a JSON blob.
    Versioned with monotonically increasing integer for optimistic concurrency.
    """

    __tablename__ = "mission_contexts"

    mission_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    context_data: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False,
    )
    version: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False,
    )
    size_characters: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
    )
    size_tokens: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
    )

    # Relationships
    changes: Mapped[list["ContextChange"]] = relationship(
        "ContextChange",
        back_populates="context",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<MissionContext(mission={self.mission_id}, "
            f"version={self.version}, size={self.size_characters})>"
        )


class ContextMilestone(UUIDMixin, TimestampMixin, Base):
    """A named snapshot of the MCD at a point in time."""

    __tablename__ = "context_milestones"

    mission_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(
        String(200), nullable=False,
    )
    description: Mapped[str] = mapped_column(
        Text, nullable=False, default="",
    )
    version_snapshot: Mapped[int] = mapped_column(
        Integer, nullable=False,
    )
    context_snapshot: Mapped[dict] = mapped_column(
        JSON, nullable=False,
    )
    created_by: Mapped[str] = mapped_column(
        String(200), nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<ContextMilestone(mission={self.mission_id}, "
            f"title={self.title!r}, version={self.version_snapshot})>"
        )


class ContextChange(UUIDMixin, TimestampMixin, Base):
    """Audit trail entry for a single MCD mutation."""

    __tablename__ = "context_changes"

    context_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("mission_contexts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False,
    )
    change_type: Mapped[str] = mapped_column(
        Enum(ChangeType, native_enum=False), nullable=False,
    )
    path: Mapped[str] = mapped_column(
        String(500), nullable=False,
    )
    old_value: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
    )
    new_value: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
    )
    mission_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True,
    )
    task_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
    )
    execution_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True,
    )
    reason: Mapped[str] = mapped_column(
        Text, nullable=False,
    )

    # Relationships
    context: Mapped["MissionContext"] = relationship(
        "MissionContext",
        back_populates="changes",
    )

    def __repr__(self) -> str:
        return (
            f"<ContextChange(version={self.version}, "
            f"type={self.change_type}, path={self.path!r})>"
        )
