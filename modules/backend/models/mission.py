"""
Mission Model.

A Mission is the top-level organizational boundary. It groups all executions,
workflow runs, context, and history for a single codebase or initiative.
Missions are long-lived (months to years), owned by humans, and scoped —
agents operate within a single mission at a time.
"""

import enum

from sqlalchemy import Enum, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class MissionStatus(str, enum.Enum):
    """Mission lifecycle status."""

    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class MissionMemberRole(str, enum.Enum):
    """Mission membership role."""

    OWNER = "owner"
    MAINTAINER = "maintainer"
    VIEWER = "viewer"


class Mission(UUIDMixin, TimestampMixin, Base):
    """A long-lived mission that groups executions, context, and history."""

    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(
        String(200), nullable=False, unique=True,
    )
    description: Mapped[str] = mapped_column(
        Text, nullable=False,
    )
    status: Mapped[str] = mapped_column(
        Enum(MissionStatus, native_enum=False),
        default=MissionStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    owner_id: Mapped[str] = mapped_column(
        String(200), nullable=False, index=True,
    )
    team_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
    )
    default_roster: Mapped[str] = mapped_column(
        String(100), default="default", nullable=False,
    )
    budget_ceiling_usd: Mapped[float | None] = mapped_column(
        Float, nullable=True,
    )
    repo_url: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    repo_root: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )

    # Relationships
    members: Mapped[list["MissionMember"]] = relationship(
        "MissionMember",
        back_populates="mission",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Mission(id={self.id}, name={self.name!r}, "
            f"status={self.status})>"
        )


class MissionMember(UUIDMixin, TimestampMixin, Base):
    """Human membership in a mission with role-based permissions."""

    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),
    )

    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(200), nullable=False, index=True,
    )
    role: Mapped[str] = mapped_column(
        Enum(MissionMemberRole, native_enum=False),
        default=MissionMemberRole.VIEWER,
        nullable=False,
    )

    # Relationships
    mission: Mapped["Mission"] = relationship(
        "Mission",
        back_populates="members",
    )

    def __repr__(self) -> str:
        return (
            f"<MissionMember(mission={self.project_id}, "
            f"user={self.user_id}, role={self.role})>"
        )
