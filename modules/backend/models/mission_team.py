"""
Mission Team Member Model.

Per-mission agent selection. Each row links a mission to an agent from
the global catalog, with an optional user-editable prompt and
mission-specific constraint overrides.
"""

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class MissionTeamMember(UUIDMixin, TimestampMixin, Base):
    """An agent assigned to a mission's team."""

    __tablename__ = "mission_team_members"
    __table_args__ = (
        UniqueConstraint(
            "mission_id", "agent_catalog_id",
            name="uq_mission_team_mission_agent",
        ),
    )

    mission_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_catalog_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agent_catalog.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_prompt: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="User-editable per-mission prompt layered on top of system prompt",
    )
    user_prompt_version: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
    )
    display_order: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
    )
    custom_constraints: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="Per-mission overrides for agent constraints",
    )

    agent_catalog = relationship(
        "AgentCatalog", lazy="raise", foreign_keys=[agent_catalog_id],
    )

    def __repr__(self) -> str:
        return (
            f"<MissionTeamMember(mission={self.mission_id}, "
            f"agent={self.agent_catalog_id}, enabled={self.enabled})>"
        )
