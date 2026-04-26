"""
Mission Model.

A Mission is the top-level organizational boundary. It groups all executions,
workflow runs, context, and history for a single codebase or initiative.
Missions are long-lived (months to years), owned by humans, and scoped —
agents operate within a single mission at a time.
"""

import enum

from sqlalchemy import Enum, Float, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class MissionTier(str, enum.Enum):
    """Mission trust tier.

    user     — standard mission, any authenticated user
    platform — admin-only, accesses platform internals
    """

    user = "user"
    platform = "platform"


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

    __tablename__ = "missions"

    name: Mapped[str] = mapped_column(
        String(200), nullable=False, unique=True,
    )
    description: Mapped[str] = mapped_column(
        Text, nullable=False,
    )
    brief: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Strategic directive that agents read to understand their purpose",
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
        Numeric(12, 6, asdecimal=False), nullable=True,
    )
    repo_url: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    repo_root: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    gate_mode: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default=None,
        comment="Default gate mode: off, interactive, ai_assisted, autonomous",
    )
    tier: Mapped[str] = mapped_column(
        Enum(MissionTier, native_enum=False),
        default=MissionTier.user,
        nullable=False,
        server_default="user",
        comment="Mission tier: user (standard) or platform (admin-only)",
    )
    execution_environment: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default=None,
        comment="Default execution environment for this mission: local, worktree, container. NULL = local.",
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

    __tablename__ = "mission_members"
    __table_args__ = (
        UniqueConstraint("mission_id", "user_id", name="uq_mission_members_mission_user"),
    )

    mission_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
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
    user: Mapped["User"] = relationship("User")

    def __repr__(self) -> str:
        return (
            f"<MissionMember(mission={self.mission_id}, "
            f"user={self.user_id}, role={self.role})>"
        )
